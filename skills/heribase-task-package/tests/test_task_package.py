import argparse
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "task_package.py"
SPEC = importlib.util.spec_from_file_location("task_package", SCRIPT)
task_package = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(task_package)


class TaskPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_task_root_is_separate_from_cli_task_cache(self):
        """整理任务默认根目录不能与 CLI daemon 的 task_*.json 缓存混用。"""

        self.assertEqual(
            task_package.resolve_root(None),
            (Path.home() / ".heribase" / "user-tasks").resolve(),
        )

    def create(self, now="2026-08-28T10:34:00+08:00"):
        return task_package.create_task(
            argparse.Namespace(
                root=str(self.root),
                display_name="测试任务",
                slug="batch-flat",
                description="",
                timezone="Asia/Shanghai",
                created_by="test",
                now=now,
            )
        )

    def task(self, task_key="20260828-1034-batch-flat"):
        return self.root / task_key

    def refresh(self, task_key, accept=False, expected_revision=1):
        return task_package.refresh_integrity(
            argparse.Namespace(
                root=str(self.root),
                task_key=task_key,
                expected_revision=expected_revision,
                accept_controlled_changes=accept,
            )
        )

    def add_identified_item(self, task_key, user_uniq_uri, collection_uri=None):
        task = self.root / task_key
        now = "2026-08-28T10:40:00+08:00"
        raw_rel = "recognition/raw/attempt-1.json"
        raw_file = task / raw_rel
        raw_file.write_text(
            json.dumps(
                {
                    "uri": f"identify-{task_key}",
                    "userUniqUri": user_uniq_uri,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        raw_hash = hashlib.sha256(raw_file.read_bytes()).hexdigest()
        item = {
            "local_id": f"{task_key}:local-01",
            "item_key": "local-01",
            "legacy_ids": [],
            "version": 1,
            "status": "active",
            "lineage": {"derived_from": [], "superseded_by": []},
            "source_refs": [],
            "evidence": [],
            "organization": {},
            "field_claims": {},
            "resolved_fields": {},
            "active_identification": {
                "attempt_id": "attempt-1",
                "snapshot_id": "snapshot-1",
                "status": "succeeded",
                "identify_uri": f"identify-{task_key}",
                "user_uniq_uri": user_uniq_uri,
                "raw_response_ref": raw_rel,
                "raw_response_sha256": raw_hash,
                "recognized_at": now,
            },
            "review_projection": None,
            "collection_projection": (
                {
                    "status": "succeeded",
                    "operation_id": "operation-1",
                    "collection_uri": collection_uri,
                    "user_uniq_uri": user_uniq_uri,
                    "raw_response_ref": None,
                    "last_error": None,
                }
                if collection_uri
                else None
            ),
            "attention_flags": [],
            "created_at": now,
            "updated_at": now,
        }
        items_doc = task_package.read_json(task / "data" / "items.json")
        items_doc["items"] = [item]
        items_doc["revision"] = 2
        task_package.write_json_atomic(task / "data" / "items.json", items_doc)
        manifest = task_package.read_json(task / "manifest.json")
        manifest["revision"] = 2
        manifest["dataset_revision"] = 2
        manifest["dataset_fingerprint"] = task_package.dataset_fingerprint([], [item])
        task_package.write_json_atomic(task / "manifest.json", manifest)
        sources = task_package.read_json(task / "inputs" / "sources.json")
        sources["revision"] = 2
        task_package.write_json_atomic(task / "inputs" / "sources.json", sources)
        self.refresh(task_key, accept=True, expected_revision=2)

    def test_create_collision_and_validate_without_online_authorization(self):
        first = self.create()
        second = self.create("2026-08-28T10:34:30+08:00")
        self.assertEqual(first["task_key"], "20260828-1034-batch-flat")
        self.assertEqual(second["task_key"], "20260828-1034-batch-flat-02")
        result = task_package.validate_package_structure(
            self.task(), first["task_key"], check_integrity=True
        )
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["online_writes_allowed"])
        self.assertIsNone(result["plan_status"])

    def test_new_task_contains_pairing_log_and_schemas(self):
        created = self.create()
        task = self.task(created["task_key"])
        self.assertTrue((task / "pairing" / "decisions.jsonl").is_file())
        self.assertTrue((task / "pairing" / "exports").is_dir())
        self.assertTrue((task / "schemas" / "pairing-decision.schema.json").is_file())
        self.assertTrue((task / "schemas" / "pairing-export.schema.json").is_file())
        self.assertTrue(task_package.validate_package_structure(task, created["task_key"])["ok"])

    def test_macos_finder_metadata_is_not_part_of_task_integrity(self):
        """Finder 可在目录内写入 .DS_Store，不能因此把可恢复任务锁死。"""

        created = self.create()
        task = self.task(created["task_key"])
        (task / ".DS_Store").write_bytes(b"finder-metadata")
        (task / "recognition" / ".DS_Store").write_bytes(b"finder-metadata")

        result = task_package.validate_package_structure(task, created["task_key"], check_integrity=True)
        self.assertTrue(result["ok"], result)

    def test_task_key_path_traversal_is_rejected(self):
        with self.assertRaises(task_package.PackageError):
            task_package.resolve_task(self.root.resolve(), "../../auth.json", False)

    def test_controlled_refresh_requires_explicit_acceptance(self):
        created = self.create()
        readme = self.task() / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "受控说明。\n", encoding="utf-8")
        with self.assertRaises(task_package.PackageError):
            self.refresh(created["task_key"], accept=False)
        refreshed = self.refresh(created["task_key"], accept=True)
        self.assertTrue(refreshed["ok"])
        self.assertEqual(refreshed["accepted_changes"][0]["path"], "README.md")

    def test_immutable_evidence_cannot_be_rebaselined(self):
        created = self.create()
        evidence = self.task() / "inputs" / "originals" / "images" / "coin.jpg"
        evidence.write_bytes(b"not-a-real-image")
        sources = task_package.read_json(self.task() / "inputs" / "sources.json")
        sources["sources"].append(
            {
                "source_id": "source-1",
                "kind": "local_image",
                "origin": {
                    "type": "local",
                    "original_name": "coin.jpg",
                    "original_path": "/tmp/original/coin.jpg",
                    "url": None,
                },
                "stored_path": "inputs/originals/images/coin.jpg",
                "mime_type": "image/jpeg",
                "byte_size": evidence.stat().st_size,
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                "acquired_at": "2026-08-28T10:35:00+08:00",
                "parent_source_id": None,
                "locator": None,
                "integrity_status": "verified",
            }
        )
        sources["revision"] = 2
        task_package.write_json_atomic(self.task() / "inputs" / "sources.json", sources)
        items_doc = task_package.read_json(self.task() / "data" / "items.json")
        items_doc["revision"] = 2
        task_package.write_json_atomic(self.task() / "data" / "items.json", items_doc)
        manifest = task_package.read_json(self.task() / "manifest.json")
        manifest["revision"] = 2
        manifest["dataset_revision"] = 2
        manifest["dataset_fingerprint"] = task_package.dataset_fingerprint(
            sources["sources"], []
        )
        task_package.write_json_atomic(self.task() / "manifest.json", manifest)
        self.refresh(created["task_key"], accept=True, expected_revision=2)
        evidence.write_bytes(b"changed-existing-evidence")
        for relative in ("manifest.json", "inputs/sources.json", "data/items.json"):
            document = task_package.read_json(self.task() / relative)
            document["revision"] = 3
            task_package.write_json_atomic(self.task() / relative, document)
        with self.assertRaisesRegex(task_package.PackageError, "不可变文件"):
            self.refresh(created["task_key"], accept=True, expected_revision=3)

    def test_sensitive_raw_response_is_rejected_by_validation(self):
        created = self.create()
        raw = self.task() / "recognition" / "raw" / "attempt-1.json"
        raw.write_text('{"access_token":"must-not-persist"}\n', encoding="utf-8")
        result = task_package.validate_package_structure(
            self.task(), created["task_key"], check_integrity=False
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("敏感字段" in error for error in result["errors"]))

    def test_same_user_uniq_uri_inside_task_is_identity_conflict(self):
        created = self.create()
        task = self.task()
        now = "2026-08-28T10:35:00+08:00"
        items = []
        for number in (1, 2):
            attempt_id = f"attempt-{number}"
            raw_rel = f"recognition/raw/{attempt_id}.json"
            raw_file = task / raw_rel
            raw_file.write_text(json.dumps({"uri": f"identify-{number}", "userUniqUri": "same-physical-coin"}) + "\n", encoding="utf-8")
            raw_hash = hashlib.sha256(raw_file.read_bytes()).hexdigest()
            item_key = f"local-{number:02d}"
            local_id = f"{created['task_key']}:{item_key}"
            items.append(
                {
                    "local_id": local_id,
                    "item_key": item_key,
                    "legacy_ids": [],
                    "version": 1,
                    "status": "active",
                    "lineage": {"derived_from": [], "superseded_by": []},
                    "source_refs": [],
                    "evidence": [],
                    "organization": {},
                    "field_claims": {},
                    "resolved_fields": {},
                    "active_identification": {
                        "attempt_id": attempt_id,
                        "snapshot_id": f"snapshot-{number}",
                        "status": "succeeded",
                        "identify_uri": f"identify-{number}",
                        "user_uniq_uri": "same-physical-coin",
                        "raw_response_ref": raw_rel,
                        "raw_response_sha256": raw_hash,
                        "recognized_at": now,
                    },
                    "review_projection": None,
                    "collection_projection": None,
                    "attention_flags": [],
                    "created_at": now,
                    "updated_at": now,
                }
            )
        items_doc = task_package.read_json(task / "data" / "items.json")
        items_doc["items"] = items
        task_package.write_json_atomic(task / "data" / "items.json", items_doc)
        result = task_package.validate_package_structure(
            task, created["task_key"], check_integrity=False
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("user_uniq_uri 冲突" in error for error in result["errors"]))

    def test_authorized_unchanged_plan_opens_gate(self):
        created = self.create()
        task = self.task()
        self.add_identified_item(created["task_key"], "physical-coin-1")

        items_doc = task_package.read_json(task / "data" / "items.json")
        manifest = task_package.read_json(task / "manifest.json")
        item = items_doc["items"][0]
        decision = {
            "schema_version": "heribase.review-decision.v1",
            "decision_id": "decision-1",
            "task_key": created["task_key"],
            "local_id": item["local_id"],
            "action": "set",
            "decision": "collect",
            "note": None,
            "actor": {"type": "user", "name": "test"},
            "interaction": {"source": "single", "batch_action_id": None, "import_ref": None},
            "based_on": {
                "item_version": item["version"],
                "identification_snapshot_id": item["active_identification"]["snapshot_id"],
                "dataset_revision": manifest["dataset_revision"],
                "dataset_fingerprint": manifest["dataset_fingerprint"],
            },
            "supersedes": None,
            "reverts": None,
            "created_at": "2026-08-28T10:36:00+08:00",
            "sequence": 1,
            "previous_event_sha256": None,
        }
        decision["event_sha256"] = task_package.event_digest(decision)
        (task / "review" / "decisions.jsonl").write_text(
            json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8"
        )
        item["review_projection"] = {
            "decision_id": "decision-1",
            "decision": "collect",
            "actor": "user",
            "item_version": item["version"],
            "stale": False,
        }
        for document, path in (
            (items_doc, task / "data" / "items.json"),
            (manifest, task / "manifest.json"),
        ):
            document["revision"] = 3
            task_package.write_json_atomic(path, document)
        sources_doc = task_package.read_json(task / "inputs" / "sources.json")
        sources_doc["revision"] = 3
        task_package.write_json_atomic(task / "inputs" / "sources.json", sources_doc)
        self.refresh(created["task_key"], accept=True, expected_revision=3)

        manifest = task_package.read_json(task / "manifest.json")
        items_doc = task_package.read_json(task / "data" / "items.json")
        item = items_doc["items"][0]
        for document, path in (
            (manifest, task / "manifest.json"),
            (items_doc, task / "data" / "items.json"),
            (sources_doc, task / "inputs" / "sources.json"),
        ):
            document["revision"] = 4
            task_package.write_json_atomic(path, document)
        plan = {
            "schema_version": "heribase.collection-plan.v1",
            "plan_id": "plan-1",
            "task_key": created["task_key"],
            "status": "authorized",
            "operation_type": "collection_add",
            "created_at": "2026-08-28T10:36:00+08:00",
            "based_on": {
                "dataset_revision": manifest["dataset_revision"],
                "dataset_fingerprint": manifest["dataset_fingerprint"],
            },
            "items": [
                {
                    "local_id": item["local_id"],
                    "item_version": item["version"],
                    "decision_id": "decision-1",
                    "identification_snapshot_id": item["active_identification"]["snapshot_id"],
                    "identify_uri": item["active_identification"]["identify_uri"],
                    "user_uniq_uri": item["active_identification"]["user_uniq_uri"],
                    "display": {"title": "Test coin"},
                }
            ],
            "excluded": [],
            "impact": {
                "included": 1,
                "excluded": 0,
                "estimated_fee": None,
                "fee_unknown": True,
            },
        }
        payload_hash = task_package.collection_plan_payload_hash(plan)
        plan["payload_sha256"] = payload_hash
        plan["authorization"] = {
            "confirmed_by": "user",
            "confirmed_at": "2026-08-28T10:37:00+08:00",
            "confirmed_payload_sha256": payload_hash,
        }
        task_package.write_json_atomic(task / "collection" / "plan.json", plan)
        self.refresh(created["task_key"], accept=True, expected_revision=4)
        result = task_package.validate_package_structure(
            task, created["task_key"], check_integrity=True
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["online_writes_allowed"], result)

    def test_jsonl_hash_chain_tampering_is_detected(self):
        created = self.create()
        task = self.task()
        manifest = task_package.read_json(task / "manifest.json")
        event = {
            "schema_version": "heribase.review-decision.v1",
            "decision_id": "decision-1",
            "task_key": created["task_key"],
            "local_id": f"{created['task_key']}:local-01",
            "action": "set",
            "decision": "collect",
            "note": None,
            "actor": {"type": "user", "name": "test"},
            "interaction": {"source": "single", "batch_action_id": None, "import_ref": None},
            "based_on": {"item_version": 1, "identification_snapshot_id": None, "dataset_revision": manifest["dataset_revision"], "dataset_fingerprint": manifest["dataset_fingerprint"]},
            "supersedes": None,
            "reverts": None,
            "created_at": "2026-08-28T10:38:00+08:00",
            "sequence": 1,
            "previous_event_sha256": None,
            "event_sha256": "0" * 64,
        }
        (task / "review" / "decisions.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        result = task_package.validate_package_structure(
            task, created["task_key"], check_integrity=False
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("event_sha256 不匹配" in error for error in result["errors"]))

    def test_catalog_links_same_physical_coin_without_merging_tasks(self):
        first = self.create("2026-08-28T10:34:00+08:00")
        second = self.create("2026-08-28T10:35:00+08:00")
        self.add_identified_item(first["task_key"], "physical-coin-1")
        self.add_identified_item(second["task_key"], "physical-coin-1")
        result = task_package.rebuild_catalog(argparse.Namespace(root=str(self.root)))
        self.assertTrue(result["ok"], result)
        entities = task_package.read_json(self.root / "_catalog" / "entities.json")
        self.assertEqual(len(entities["entities"]), 1)
        self.assertEqual(len(entities["entities"][0]["members"]), 2)
        self.assertNotEqual(
            entities["entities"][0]["members"][0]["local_id"],
            entities["entities"][0]["members"][1]["local_id"],
        )

    def test_append_only_log_allows_append_but_rejects_history_rewrite(self):
        created = self.create()
        task = self.task()
        event = {
            "schema_version": "heribase.audit-event.v1",
            "event_id": "audit-1",
            "task_key": created["task_key"],
            "event_type": "task_updated",
            "entity": {"type": "task", "id": created["task_key"]},
            "actor": {"type": "system", "name": "test"},
            "correlation_id": None,
            "before": None,
            "after": {"revision": 2},
            "details": {},
            "created_at": "2026-08-28T10:41:00+08:00",
            "sequence": 1,
            "previous_event_sha256": None,
        }
        event["event_sha256"] = task_package.event_digest(event)
        audit_path = task / "audit" / "events.jsonl"
        audit_path.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
        for relative in ("manifest.json", "inputs/sources.json", "data/items.json"):
            document = task_package.read_json(task / relative)
            document["revision"] = 2
            task_package.write_json_atomic(task / relative, document)
        self.refresh(created["task_key"], accept=True, expected_revision=2)
        rewritten = audit_path.read_text(encoding="utf-8").replace("task_updated", "task_rewrite")
        audit_path.write_text(rewritten, encoding="utf-8")
        for relative in ("manifest.json", "inputs/sources.json", "data/items.json"):
            document = task_package.read_json(task / relative)
            document["revision"] = 3
            task_package.write_json_atomic(task / relative, document)
        with self.assertRaisesRegex(task_package.PackageError, "历史内容被重写"):
            self.refresh(created["task_key"], accept=True, expected_revision=3)


if __name__ == "__main__":
    unittest.main()
