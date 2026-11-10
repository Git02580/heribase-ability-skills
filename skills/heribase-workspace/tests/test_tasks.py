import argparse
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workspace_store import WorkspaceStore, WorkspaceError
from workspace_tasks import WorkspaceTasks, operations


class TaskBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.tmp.name))
        self.tasks = WorkspaceTasks(self.store)
        self.task = self.tasks.create("真实本地任务", "Asia/Shanghai", "user:web")
        self.key = self.task["manifest"]["task_key"]

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, name, content):
        revision = self.tasks.snapshot(self.key)["manifest"]["revision"]
        return self.tasks.ingest(self.key, revision, name, content, "user:web")

    def make_pair(self):
        one = self.ingest("front.png", b"front-image")
        two = self.ingest("back.png", b"back-image")
        current = self.tasks.snapshot(self.key)
        result = self.tasks.create_candidate(self.key, current["manifest"]["revision"], [one["source"]["source_id"], two["source"]["source_id"]], "我的钱币", "user:web")
        return result["items"][0]

    def test_ingest_candidate_pairing_and_review_survive_reopen(self):
        item = self.make_pair()
        before = self.tasks.snapshot(self.key)
        sources = before["sources"]
        self.assertIsNone(sources[0]["origin"]["original_path"])
        after = self.tasks.pair(self.key, before["manifest"]["revision"], item["local_id"], "confirm_pair",
                                [{"sourceId": sources[0]["source_id"], "role": "obverse"}, {"sourceId": sources[1]["source_id"], "role": "reverse"}], "user:web")
        self.assertEqual(after["items"][0]["organization"]["pairing_state"], "confirmed")
        reviewed = self.tasks.review(self.key, after["manifest"]["revision"], item["local_id"], "need_photo", "user:web")
        reopened = WorkspaceTasks(WorkspaceStore(Path(self.tmp.name))).snapshot(self.key)
        self.assertTrue(reopened["health"]["ok"])
        self.assertEqual(reopened["items"][0]["review_projection"]["decision"], "need_photo")
        self.assertEqual(reviewed["manifest"]["revision"], reopened["manifest"]["revision"])
        media, mime = self.tasks.source(self.key, sources[0]["source_id"])
        self.assertEqual(media, b"front-image")
        self.assertEqual(mime, "image/png")

    def test_unidentified_item_cannot_be_marked_collect(self):
        item = self.make_pair()
        revision = self.tasks.snapshot(self.key)["manifest"]["revision"]
        with self.assertRaises(WorkspaceError):
            self.tasks.review(self.key, revision, item["local_id"], "collect", "user:web")
        self.assertEqual(self.tasks.snapshot(self.key)["manifest"]["revision"], revision)

    def test_repairing_expires_old_recognition_and_collection_plan_but_keeps_raw(self):
        item = self.make_pair()
        current = self.tasks.snapshot(self.key)
        raw = Path(self.tmp.name) / "recognition.json"
        raw.write_text(json.dumps({"status": "completed", "result": {"uri": "fixture-identification"}}))
        event = Path(self.tmp.name) / "event.json"
        timestamp = operations.now_iso()
        event.write_text(json.dumps({"schema_version": "heribase.recognition-attempt.v1", "attempt_id": "fixture-attempt",
            "task_key": self.key, "local_id": item["local_id"], "attempt_number": 1, "operation_type": "identify", "status": "succeeded",
            "input": {"item_version": item["version"], "evidence": []}, "cli": {"command": "heribase identify", "args": ["--json"]},
            "remote_task_id": "fixture-cli-task", "started_at": timestamp, "finished_at": timestamp, "exit_code": 0,
            "classification": "success", "raw_response_ref": None, "raw_response_sha256": None, "error": None}))
        operations.record_recognition(argparse.Namespace(root=str(self.tasks.root), task_key=self.key,
            expected_revision=current["manifest"]["revision"], actor="fixture", event_json=str(event), raw_json=str(raw)))
        current = self.tasks.snapshot(self.key)
        current = self.tasks.review(self.key, current["manifest"]["revision"], item["local_id"], "collect", "user:web")
        operations.build_plan(argparse.Namespace(root=str(self.tasks.root), task_key=self.key,
            expected_revision=current["manifest"]["revision"], actor="fixture", operation="collection_add", operations_json=None))
        current = self.tasks.snapshot(self.key)
        assignments = [{"sourceId": current["sources"][0]["source_id"], "role": "reverse"},
                       {"sourceId": current["sources"][1]["source_id"], "role": "obverse"}]
        changed = self.tasks.pair(self.key, current["manifest"]["revision"], item["local_id"], "confirm_pair", assignments, "user:web")
        self.assertEqual(changed["items"][0]["active_identification"]["status"], "stale")
        self.assertTrue(changed["items"][0]["review_projection"]["stale"])
        self.assertEqual(changed["plan"]["status"], "stale")
        self.assertEqual(json.loads((self.tasks.root / self.key / "recognition/raw/fixture-attempt.json").read_text())["result"]["uri"], "fixture-identification")

    def test_changed_revision_and_corrupt_evidence_block_writes(self):
        item = self.make_pair()
        current = self.tasks.snapshot(self.key)
        with self.assertRaises(WorkspaceError) as error:
            self.tasks.review(self.key, 1, item["local_id"], "exclude", "user:web")
        self.assertEqual(error.exception.code, "revision_conflict")
        source = current["sources"][0]
        (self.tasks.root / self.key / source["stored_path"]).write_bytes(b"tampered")
        with self.assertRaises(WorkspaceError) as error:
            self.tasks.review(self.key, current["manifest"]["revision"], item["local_id"], "exclude", "user:web")
        self.assertEqual(error.exception.code, "data_inconsistent")

    def test_inconsistent_task_remains_listed_with_integrity_details_for_management(self):
        source = self.ingest("front.png", b"front-image")["source"]
        (self.tasks.root / self.key / source["stored_path"]).write_bytes(b"tampered")
        summary = next(value for value in self.tasks.summaries() if value["task_key"] == self.key)
        self.assertFalse(summary["health"]["ok"])
        self.assertTrue(summary["health"]["errors"])
        self.assertNotEqual(summary["display_name"], self.key)

    def test_browser_identifiers_cannot_escape_task_root(self):
        for task in ["../", "/tmp/test", "20260923-0000-x/../../"]:
            with self.assertRaises(WorkspaceError):
                self.tasks.snapshot(task)
        with self.assertRaises(WorkspaceError):
            self.tasks.ingest(self.key, 1, "../../escape.png", b"image", "user:web")

    def test_same_source_cannot_be_assigned_to_two_active_coins(self):
        self.make_pair()
        current = self.tasks.snapshot(self.key)
        with self.assertRaises(WorkspaceError):
            self.tasks.create_candidate(self.key, current["manifest"]["revision"], [s["source_id"] for s in current["sources"]], "重复实物", "user:web")
        self.assertEqual(len(self.tasks.snapshot(self.key)["items"]), 1)

    def test_read_refresh_does_not_break_concurrent_ingest(self):
        def read_many():
            for _ in range(30):
                self.assertTrue(self.tasks.snapshot(self.key)['health']['ok'])
        with ThreadPoolExecutor(max_workers=3) as pool:
            readers = [pool.submit(read_many) for _ in range(2)]
            for number in range(4):
                self.ingest('image-' + str(number) + '.png', ('image-' + str(number)).encode())
            for future in readers:
                future.result()
        self.assertEqual(len(self.tasks.snapshot(self.key)['sources']), 4)

    def test_external_package_mutations_emit_a_refresh_event(self):
        self.tasks.refresh_external_changes()
        cursor = self.store.cursor()
        self.make_pair()
        # 另一个 adapter 模拟宿主从外部现有任务包脚本产生的变更。
        self.tasks.refresh_external_changes()
        self.assertTrue(any(event["type"] == "task.updated" for event in self.store.events(cursor)))


if __name__ == "__main__":
    unittest.main()
