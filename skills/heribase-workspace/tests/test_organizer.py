"""Actual task transactions and event delivery; model/remote calls are injected, never contacted."""
import copy
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workspace_service import WorkspaceService
from workspace_store import WorkspaceStore, WorkspaceError
from workspace_organizer import validate_result


def photo():
    stream = io.BytesIO()
    Image.new("RGB", (240, 120), "silver").save(stream, "PNG")
    return stream.getvalue()


def analysis(ids, combined=False):
    parts = [{"sourceId": source, "role": role, "roleConfidence": 0.97,
              "bounds": [offset * 500, 0, (offset + 1) * 500, 1000] if combined else [0, 0, 1000, 1000]}
             for offset, (source, role) in enumerate(zip(ids if not combined else ids * 2, ["obverse", "reverse"]))]
    return {"groups": [{"title": "来源图示例", "kind": "coin", "confidence": 0.97, "summary": "同图展示完整两面，币缘及币种信息相符。",
                        "supportingSignals": ["同图明确来源", "币缘与币种兼容"], "conflicts": [], "parts": parts}], "suggestions": []}


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.tmp.name))
        self.calls = []
        def runner(catalog, images, directory):
            self.calls.append(copy.deepcopy(catalog))
            return analysis([entry["sourceId"] for entry in catalog], len(catalog) == 1)
        self.service = WorkspaceService(self.store, background=False, organizer_runner=runner)
        self.task = self.service.tasks.create("自动整理", "Asia/Shanghai", "user:web")
        self.key = self.task["manifest"]["task_key"]

    def tearDown(self):
        self.service.organizer.close()
        self.tmp.cleanup()

    def upload(self, name="coin.png", content=None):
        current = self.service.tasks.snapshot(self.key)
        result = self.service.tasks.ingest(self.key, current["manifest"]["revision"], name, content or photo(), "user:web")
        self.service.organizer.enqueue(self.key, result["revision"])
        return result

    def start(self, retry=False):
        current = self.service.tasks.snapshot(self.key)
        return self.service.mutate("/api/connector/organize", {"taskKey": self.key, "expectedRevision": current["manifest"]["revision"], "retry": retry}, "browser")

    def test_multiple_uploads_coalesce_and_finish_starts_once_without_user_confirmation_or_online_calls(self):
        self.upload("front.png")
        self.upload("back.png")
        first = self.start()
        self.assertEqual(self.start()["data"]["jobId"], first["data"]["jobId"])
        self.service.organizer.run_job(self.key)
        self.service.organizer.run_job(self.key)
        current = self.service.tasks.snapshot(self.key)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(current["organization"]["status"], "completed")
        self.assertEqual(current["items"][0]["organization"]["pairing_state"], "auto_ready")
        self.assertEqual(current["manifest"]["state"], "awaiting_precheck")
        self.assertTrue(current["health"]["ok"])
        task = self.service.tasks.resolve(self.key)
        self.assertEqual((task / "pairing/decisions.jsonl").read_text(), "")
        self.assertEqual((task / "recognition/attempts.jsonl").read_text(), "")
        self.assertEqual(self.store.list_entities("operation"), [])

    def test_combined_photo_is_cropped_with_parent_provenance_and_original_is_unchanged(self):
        saved = self.upload()
        self.start()
        self.service.organizer.run_job(self.key)
        current = self.service.tasks.snapshot(self.key)
        self.assertEqual(current["organization"]["status"], "completed", current["organization"])
        self.assertEqual(len(current["sources"]), 3)
        self.assertEqual(self.service.tasks.source(self.key, saved["source"]["source_id"])[0], photo())
        for source in current["sources"][1:]:
            self.assertEqual(source["parent_source_id"], saved["source"]["source_id"])
            path, _ = self.service.tasks.source_path(self.key, source["source_id"])
            with Image.open(path) as image:
                self.assertEqual(image.size, (120, 120))
        self.assertTrue(current["health"]["ok"])

    def test_stale_model_does_not_overwrite_manual_decisions_or_consume_a_newer_upload_job(self):
        self.upload()
        self.start()
        def changed(catalog, images, directory):
            self.upload("new.png")
            return analysis([entry["sourceId"] for entry in catalog], True)
        self.service.organizer.runner = changed
        old = self.store.get_entity("organization", self.key)["data"]["jobId"]
        self.service.organizer.run_job(self.key)
        current = self.service.tasks.snapshot(self.key)
        self.assertEqual(current["items"], [])
        self.assertNotEqual(current["organization"]["jobId"], old)
        self.assertEqual(current["organization"]["status"], "queued")
        self.assertEqual(len(current["sources"]), 2)

    def test_failure_is_visible_persistent_and_retry_is_explicit_and_scoped(self):
        self.upload()
        self.start()
        self.service.organizer.runner = lambda *args: (_ for _ in ()).throw(WorkspaceError("organizer_timeout", "整理超时，原件保留"))
        self.service.organizer.run_job(self.key)
        job = self.service.tasks.snapshot(self.key)["organization"]
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.start()["data"]["jobId"], job["jobId"])
        self.assertNotEqual(self.start(retry=True)["data"]["jobId"], job["jobId"])
        self.assertEqual(len(self.service.tasks.snapshot(self.key)["sources"]), 1)

    def test_unknown_remote_operation_blocks_organization_and_cannot_be_bypassed_with_retry(self):
        self.upload()
        self.store.save_entity("operation", "pending", {"taskKey": self.key, "status": "reconcile_required"}, 0, "user:web")
        with self.assertRaises(WorkspaceError) as error:
            self.start(retry=True)
        self.assertEqual(error.exception.code, "operation_pending")
        self.assertFalse(self.calls)

    def test_invalid_coverage_duplicate_pixels_and_unknown_source_are_rejected_before_any_crop_or_item_write(self):
        saved = self.upload()
        self.start()
        source_id = saved["source"]["source_id"]
        result = analysis([source_id], True)
        bad = []
        missing = copy.deepcopy(result)
        missing["groups"] = []
        bad.append(missing)
        overlap = copy.deepcopy(result)
        overlap["groups"][0]["parts"][1]["bounds"] = [0, 0, 1000, 1000]
        bad.append(overlap)
        unknown = copy.deepcopy(result)
        unknown["groups"][0]["parts"][0]["sourceId"] = "outside"
        bad.append(unknown)
        for value in bad:
            with self.assertRaises(WorkspaceError):
                validate_result(value, [{"sourceId": source_id}])
        self.assertEqual(len(self.service.tasks.snapshot(self.key)["sources"]), 1)

    def test_csv_without_images_preserves_every_row_and_never_claims_ready_or_online_recognition(self):
        self.upload("coins.csv", "名称,年份\n硬币甲,1981\n硬币乙,1963\n".encode())
        self.start()
        self.service.organizer.run_job(self.key)
        current = self.service.tasks.snapshot(self.key)
        self.assertEqual(current["organization"]["status"], "completed", current["organization"])
        self.assertEqual(len(current["items"]), 2)
        self.assertEqual([item["organization"]["source_rows"] for item in current["items"]], [[2], [3]])
        self.assertTrue(all(item["organization"]["pairing_state"] == "single_side" for item in current["items"]))
        self.assertTrue(all(item["item_key"].startswith("table-") for item in current["items"]))
        self.assertTrue(current["health"]["ok"])
        self.assertFalse(self.calls)

    def test_csv_image_urls_are_archived_with_row_and_url_provenance_before_a_pair_can_be_ready(self):
        self.upload("coins.csv", b'name,front,back\ncoin,https://example.com/a.png,https://example.com/b.png\n')
        self.start()
        with patch("workspace_organizer_inputs.operations.remote_image_bytes", return_value=(photo(), "image/png")):
            self.service.organizer.run_job(self.key)
        current = self.service.tasks.snapshot(self.key)
        self.assertEqual(current["organization"]["status"], "completed", current["organization"])
        self.assertEqual(len(current["sources"]), 3)
        self.assertEqual(current["items"][0]["organization"]["source_rows"], [2])
        self.assertEqual({source["origin"]["url"] for source in current["sources"][1:]}, {"https://example.com/a.png", "https://example.com/b.png"})
        self.assertTrue(current["health"]["ok"])

    def test_background_worker_consumes_events_without_manual_run_or_chat_polling(self):
        started, release = threading.Event(), threading.Event()
        def runner(catalog, images, directory):
            started.set()
            release.wait(5)
            return analysis([entry["sourceId"] for entry in catalog], True)
        live = WorkspaceService(self.store, background=True, organizer_runner=runner)
        self.service.organizer.close()
        self.service = live
        self.upload()
        self.start()
        self.assertTrue(started.wait(5))
        self.assertEqual(self.service.tasks.snapshot(self.key)["organization"]["status"], "running")
        release.set()

    def test_later_photo_can_complete_a_single_face_without_reassigning_a_confirmed_pair(self):
        saved = self.upload()
        def single(catalog, images, directory):
            result = analysis([entry["sourceId"] for entry in catalog], False)
            result["groups"][0]["parts"] = result["groups"][0]["parts"][:1]
            return result
        original_runner = self.service.organizer.runner
        self.service.organizer.runner = single
        self.start()
        self.service.organizer.run_job(self.key)
        first = self.service.tasks.snapshot(self.key)["items"][0]
        self.upload("back.png")
        self.service.organizer.runner = original_runner
        self.start()
        self.service.organizer.run_job(self.key)
        current = self.service.tasks.snapshot(self.key)
        self.assertEqual(current["organization"]["status"], "completed", current["organization"])
        old, new = current["items"]
        self.assertEqual(old["local_id"], first["local_id"])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["organization"]["pairing_state"], "auto_ready")
        self.assertIn(new["local_id"], old["lineage"]["superseded_by"])
        self.assertTrue(current["health"]["ok"])

    def test_manual_revision_change_during_analysis_cannot_be_overwritten(self):
        front = self.upload("front.png")
        back = self.upload("back.png")
        self.start()
        def manual(catalog, images, directory):
            task = self.service.tasks.snapshot(self.key)
            self.service.tasks.create_candidate(self.key, task["manifest"]["revision"], [front["source"]["source_id"], back["source"]["source_id"]], "用户自己的分组", "user:web")
            return analysis([entry["sourceId"] for entry in catalog])
        self.service.organizer.runner = manual
        self.service.organizer.run_job(self.key)
        current = self.service.tasks.snapshot(self.key)
        self.assertEqual(current["organization"]["errorCode"], "revision_conflict")
        self.assertEqual(len(current["items"]), 1)
        self.assertEqual(current["items"][0]["resolved_fields"]["name"]["value"], "用户自己的分组")

    def test_pending_job_survives_restart_and_interrupted_analysis_has_an_explicit_retry(self):
        self.upload()
        job = self.start()["data"]
        self.service.organizer.close()
        self.service = WorkspaceService(self.store, background=False, organizer_runner=lambda catalog, *_: analysis([entry["sourceId"] for entry in catalog], True))
        self.assertEqual(self.service.tasks.snapshot(self.key)["organization"]["jobId"], job["jobId"])
        self.service.organizer._update(self.key, job["jobId"], status="running")
        self.service.organizer.close()
        self.service = WorkspaceService(self.store, background=False)
        self.assertEqual(self.service.tasks.snapshot(self.key)["organization"]["stage"], "interrupted")
        self.assertNotEqual(self.start(retry=True)["data"]["jobId"], job["jobId"])


if __name__ == "__main__":
    unittest.main()
