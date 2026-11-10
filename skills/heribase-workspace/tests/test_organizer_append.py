"""Append during real threaded local preparation; model and online work are fakes."""
import copy
import io
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workspace_service import WorkspaceService
from workspace_store import WorkspaceError, WorkspaceStore
import workspace_organizer_inputs


def image(number):
    output = io.BytesIO()
    Image.new("RGB", (80, 80), (number % 255, 120, 160)).save(output, "PNG")
    return output.getvalue()


def full_analysis(catalog):
    groups = []
    for offset in range(0, len(catalog), 2):
        selected = catalog[offset:offset + 2]
        groups.append({"title": f"候选 {offset // 2 + 1}", "kind": "coin", "confidence": 0.97,
            "summary": "测试图片的完整分组", "supportingSignals": ["来源一致", "币缘一致"], "conflicts": [],
            "parts": [{"sourceId": entry["sourceId"], "role": role, "roleConfidence": 0.97, "bounds": [0, 0, 1000, 1000]}
                      for entry, role in zip(selected, ["obverse", "reverse"])]})
    return {"groups": groups, "suggestions": []}


class OrganizerAppendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.tmp.name))
        self.catalogs, self.bytes = [], {}
        self.number = 0
        self.service = self.make_service(False, self.model)
        self.key = self.service.tasks.create("追加照片测试", "Asia/Shanghai", "user:web")["manifest"]["task_key"]

    def tearDown(self):
        self.service.organizer.close()
        self.tmp.cleanup()

    def make_service(self, background, model):
        def no_remote(argv):
            raise AssertionError(f"unexpected remote command: {argv}")
        return WorkspaceService(self.store, no_remote, background=background, organizer_runner=model)

    def model(self, catalog, *_):
        self.catalogs.append(copy.deepcopy(catalog))
        return full_analysis(catalog)

    def snapshot(self):
        return self.service.tasks.snapshot(self.key)

    def upload(self, *, schedule=True, revision=None):
        self.number += 1
        content = image(self.number)
        result = self.service.organizer.archive_upload(self.key, revision or self.snapshot()["manifest"]["revision"],
            f"photo-{self.number}.png", content, "user:web", schedule=schedule)
        self.bytes[result["source"]["source_id"]] = content
        return result

    def flush(self):
        current = self.snapshot()
        return self.service.organizer.enqueue(self.key, current["manifest"]["revision"], immediate=True)

    def test_background_worker_continues_latest_whole_batch_and_preserves_confirmed_results(self):
        first, second = self.upload(schedule=False), self.upload(schedule=False)
        current = self.snapshot()
        current = self.service.tasks.create_candidate(self.key, current["manifest"]["revision"],
            [first["source"]["source_id"], second["source"]["source_id"]], "已确认的一枚", "user:web")
        fixed_id = current["items"][0]["local_id"]
        current = self.service.tasks.pair(self.key, current["manifest"]["revision"], fixed_id, "confirm_pair", [
            {"sourceId": first["source"]["source_id"], "role": "obverse"},
            {"sourceId": second["source"]["source_id"], "role": "reverse"}], "user:web")
        fixed = current["items"][0]
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def model(catalog, *_):
            self.catalogs.append(copy.deepcopy(catalog))
            if len(self.catalogs) == 1:
                started.set()
                release.wait(8)
            return full_analysis(catalog)
        self.service.organizer.close()
        self.service = self.make_service(True, model)
        self.service.organizer.debounce = 0
        update = self.service.organizer._update
        def observed_update(key, job_id, **values):
            result = update(key, job_id, **values)
            if result and values.get("status") == "completed":
                finished.set()
            return result
        with patch.object(self.service.organizer, "_update", side_effect=observed_update):
            try:
                initial = self.upload()
                self.assertTrue(started.wait(5))
                old_job = self.snapshot()["organization"]["jobId"]
                receipts = [initial] + [self.upload() for _ in range(3)]
                pending = self.snapshot()
                latest_job = pending["organization"]["jobId"]
                self.assertNotEqual(latest_job, old_job)
                self.assertEqual(pending["organization"]["status"], "queued")
                self.assertEqual(len(pending["items"]), 1)
                expected_ids = [entry["source"]["source_id"] for entry in receipts]
                self.assertEqual(pending["organization"]["sourceIds"], expected_ids)
                release.set()
                self.assertTrue(finished.wait(8))
            finally:
                release.set()
        current = self.snapshot()
        self.assertEqual(current["organization"]["jobId"], latest_job)
        self.assertEqual([len(catalog) for catalog in self.catalogs], [1, 4])
        self.assertEqual([entry["sourceId"] for entry in self.catalogs[-1]], expected_ids)
        self.assertEqual(current["manifest"]["revision"], receipts[-1]["revision"] + 1)
        self.assertEqual(len(current["items"]), 3)
        self.assertEqual(next(item for item in current["items"] if item["local_id"] == fixed_id), fixed)
        self.assertTrue(current["health"]["ok"])
        self.assertFalse((self.store.directory / "workspace/organization" / (old_job + ".json")).exists())
        for source_id, content in self.bytes.items():
            self.assertEqual(self.service.tasks.source(self.key, source_id)[0], content)
        self.assertEqual(self.store.list_entities("operation"), [])

    def test_superseded_input_preparation_does_not_start_an_obsolete_model_call(self):
        self.upload()
        self.flush()
        original = workspace_organizer_inputs.prepare_inputs
        def append_after_preparation(*args):
            value = original(*args)
            self.upload()
            return value
        with patch.object(workspace_organizer_inputs, "prepare_inputs", side_effect=append_after_preparation):
            self.service.organizer.run_job(self.key)
        self.assertEqual(self.catalogs, [])
        self.assertEqual(self.snapshot()["organization"]["status"], "queued")
        self.assertEqual(self.snapshot()["items"], [])
        self.service.organizer.run_job(self.key)
        self.assertEqual(len(self.catalogs), 1)
        self.assertEqual(len(self.catalogs[0]), 2)
        self.assertEqual(self.snapshot()["organization"]["status"], "completed")

    def test_one_inflight_analysis_per_task_while_a_replacement_job_waits(self):
        self.upload()
        self.flush()
        started, release = threading.Event(), threading.Event()
        def model(catalog, *_):
            self.catalogs.append(copy.deepcopy(catalog))
            if len(self.catalogs) == 1:
                started.set()
                release.wait(8)
            return full_analysis(catalog)
        self.service.organizer.runner = model
        worker = threading.Thread(target=self.service.organizer.run_job, args=(self.key,))
        worker.start()
        try:
            self.assertTrue(started.wait(5))
            self.upload()
            latest = self.flush()["data"]["jobId"]
            self.service.organizer.run_job(self.key)
            self.assertEqual(len(self.catalogs), 1)
            self.assertEqual(self.snapshot()["organization"]["status"], "queued")
        finally:
            release.set()
            worker.join(8)
        self.assertFalse(worker.is_alive())
        self.service.organizer.run_job(self.key)
        self.assertEqual([len(value) for value in self.catalogs], [1, 2])
        self.assertEqual(self.snapshot()["organization"]["jobId"], latest)
        self.assertEqual(self.snapshot()["organization"]["status"], "completed")

    def test_obsolete_model_failure_does_not_fail_or_remove_latest_upload_job(self):
        self.upload()
        self.flush()
        def failing_old_model(catalog, *_):
            self.upload()
            raise WorkspaceError("organizer_timeout", "旧整理超时", 503)
        self.service.organizer.runner = failing_old_model
        self.service.organizer.run_job(self.key)
        self.assertEqual(self.snapshot()["organization"]["status"], "queued")
        self.assertEqual(len(self.snapshot()["sources"]), 2)
        self.service.organizer.runner = self.model
        self.service.organizer.run_job(self.key)
        self.assertEqual(self.snapshot()["organization"]["status"], "completed")

    def test_append_at_submission_boundary_cannot_commit_the_old_scope(self):
        self.upload()
        self.flush()
        apply = self.service.organizer.apply
        def append_then_apply(*args):
            self.upload()
            return apply(*args)
        with patch.object(self.service.organizer, "apply", side_effect=append_then_apply):
            self.service.organizer.run_job(self.key)
        current = self.snapshot()
        self.assertEqual(current["items"], [])
        self.assertEqual(current["organization"]["status"], "queued")
        self.assertEqual(len(current["sources"]), 2)
        self.service.organizer.run_job(self.key)
        self.assertEqual(self.snapshot()["organization"]["status"], "completed")

    def test_append_after_commit_before_completion_preserves_old_result_and_new_queue(self):
        self.upload()
        self.upload()
        old_job = self.flush()["data"]["jobId"]
        apply = self.service.organizer.apply
        def append_after_apply(*args):
            result = apply(*args)
            self.upload()
            return result
        with patch.object(self.service.organizer, "apply", side_effect=append_after_apply):
            self.service.organizer.run_job(self.key)
        current = self.snapshot()
        first_item = copy.deepcopy(current["items"][0])
        self.assertEqual(len(current["items"]), 1)
        self.assertNotEqual(current["organization"]["jobId"], old_job)
        self.assertEqual(current["organization"]["status"], "queued")
        self.assertEqual(len(current["organization"]["sourceIds"]), 1)
        self.service.organizer.run_job(self.key)
        current = self.snapshot()
        self.assertEqual(current["organization"]["status"], "completed")
        self.assertEqual(current["items"][0], first_item)
        self.assertEqual(len(current["items"]), 2)

    def test_known_stale_revision_upload_is_not_archived_and_latest_retry_archives_once(self):
        self.upload()
        self.flush()
        old_revision = self.snapshot()["manifest"]["revision"]
        errors, entered = [], threading.Event()
        def delayed_upload():
            entered.set()
            try:
                self.upload(revision=old_revision)
            except WorkspaceError as error:
                errors.append(error.code)
        with self.service.executor.lock:
            thread = threading.Thread(target=delayed_upload)
            thread.start()
            self.assertTrue(entered.wait(3))
            self.service.organizer.run_job(self.key)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["revision_conflict"])
        self.assertEqual(len(self.snapshot()["sources"]), 1)
        source_count = len(self.snapshot()["sources"])
        self.upload()
        self.assertEqual(len(self.snapshot()["sources"]), source_count + 1)

    def test_scheduling_warning_still_returns_one_archived_source_receipt(self):
        with patch.object(self.service.organizer, "enqueue", side_effect=WorkspaceError("revision_conflict", "排队时版本变化", 409)):
            receipt = self.upload()
        self.assertEqual(receipt["organizationWarning"]["code"], "revision_conflict")
        self.assertEqual(len(self.snapshot()["sources"]), 1)
        self.assertEqual(self.service.tasks.source(self.key, receipt["source"]["source_id"])[0], self.bytes[receipt["source"]["source_id"]])
        self.flush()
        self.service.organizer.run_job(self.key)
        self.assertEqual(self.snapshot()["organization"]["status"], "completed")

    def test_remote_unknown_write_still_prevents_additive_upload_before_archival(self):
        self.upload()
        before = self.snapshot()
        self.store.save_entity("operation", "unknown-write", {"taskKey": self.key, "status": "reconcile_required"}, 0, "user:web")
        with self.assertRaises(WorkspaceError) as caught:
            self.upload()
        self.assertEqual(caught.exception.code, "operation_pending")
        self.assertEqual(len(self.snapshot()["sources"]), len(before["sources"]))
        self.assertEqual(self.snapshot()["manifest"]["revision"], before["manifest"]["revision"])


if __name__ == "__main__":
    unittest.main()
