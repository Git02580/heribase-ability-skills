import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

CORE_SPEC = importlib.util.spec_from_file_location("task_package", SCRIPT_DIR / "task_package.py")
task_package = importlib.util.module_from_spec(CORE_SPEC)
assert CORE_SPEC.loader is not None
CORE_SPEC.loader.exec_module(task_package)
sys.modules["task_package"] = task_package

OPS_SPEC = importlib.util.spec_from_file_location("task_operations", SCRIPT_DIR / "task_operations.py")
task_operations = importlib.util.module_from_spec(OPS_SPEC)
assert OPS_SPEC.loader is not None
OPS_SPEC.loader.exec_module(task_operations)


class TaskOperationsEndToEndTests(unittest.TestCase):
    def test_confirmed_pairing_direction_overrides_initial_evidence_roles(self):
        item = {"status": "active", "attention_flags": [], "evidence": [
            {"source_id": "a", "role": "obverse", "is_primary": True},
            {"source_id": "b", "role": "reverse", "is_primary": True}],
            "organization": {"pairing_state": "confirmed", "source_assignment": [
                {"source_id": "a", "role": "reverse"}, {"source_id": "b", "role": "obverse"}]}}
        self.assertEqual(task_operations.identification_source_roles(item), {"obverse": "b", "reverse": "a"})

    def test_excluded_or_incomplete_pairing_is_never_identification_eligible(self):
        for state in ["excluded", "single_side", "needs_review"]:
            item = {"status": "active", "attention_flags": [], "organization": {"pairing_state": state},
                    "evidence": [{"source_id": "a", "role": "obverse", "is_primary": True},
                                 {"source_id": "b", "role": "reverse", "is_primary": True}]}
            self.assertFalse(task_operations.identification_eligible(item))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        created = task_package.create_task(
            argparse.Namespace(
                root=str(self.root),
                display_name="端到端测试",
                slug="workflow",
                description="",
                timezone="Asia/Shanghai",
                created_by="test",
                now="2026-08-28T19:00:00+08:00",
            )
        )
        self.task_key = created["task_key"]
        self.task = self.root / self.task_key

    def tearDown(self):
        self.temporary.cleanup()

    def args(self, revision, **values):
        return argparse.Namespace(
            root=str(self.root),
            task_key=self.task_key,
            expected_revision=revision,
            actor="test",
            **values,
        )

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
        return str(path)

    def test_service_identity_is_read_from_completed_cli_result_envelope(self):
        raw = {"status": "completed", "result": {"uri": "identify-1", "userUniqUri": "physical-coin-1"}}
        self.assertEqual(task_operations.service_value(raw, "identify_uri"), "identify-1")
        self.assertEqual(task_operations.service_value(raw, "user_uniq_uri"), "physical-coin-1")

    def test_migration_replaces_copied_legacy_schema_and_removes_sensitive_projection(self):
        """模板升级后，旧任务的复制 schema 也必须经审计迁移才能恢复可写。"""

        raw_path = self.task / "recognition" / "raw" / "attempt-1.json"
        raw_path.write_text(json.dumps({"uri": "identify-1", "userUniqUri": "physical-coin-1"}), encoding="utf-8")
        raw_hash = task_package.sha256_file(raw_path)
        items_doc = task_package.read_json(self.task / "data" / "items.json")
        items_doc["items"] = [{
            "local_id": f"{self.task_key}:local-01", "item_key": "local-01", "legacy_ids": [],
            "version": 1, "status": "active", "lineage": {"derived_from": [], "superseded_by": []},
            "source_refs": [], "evidence": [], "organization": {}, "field_claims": {}, "resolved_fields": {},
            "active_identification": {
                "attempt_id": "attempt-1", "snapshot_id": "snapshot-1", "status": "succeeded",
                "identify_uri": "identify-1", "user_uniq_uri": "physical-coin-1",
                "raw_response_ref": "recognition/raw/attempt-1.json", "raw_response_sha256": raw_hash,
                "recognized_at": "2026-08-28T11:00:00+00:00",
            },
            "review_projection": None, "collection_projection": None, "attention_flags": [],
            "created_at": "2026-08-28T11:00:00+00:00", "updated_at": "2026-08-28T11:00:00+00:00",
        }]
        manifest = task_package.read_json(self.task / "manifest.json")
        sources_doc = task_package.read_json(self.task / "inputs" / "sources.json")
        for document in (items_doc, manifest, sources_doc):
            document["revision"] = 2
        manifest["dataset_revision"] = 2
        manifest["dataset_fingerprint"] = task_package.dataset_fingerprint([], items_doc["items"])
        task_package.write_json_atomic(self.task / "data" / "items.json", items_doc)
        task_package.write_json_atomic(self.task / "manifest.json", manifest)
        task_package.write_json_atomic(self.task / "inputs" / "sources.json", sources_doc)
        recognition_event = {
            "schema_version": "heribase.recognition-attempt.v1", "attempt_id": "attempt-1",
            "task_key": self.task_key, "local_id": f"{self.task_key}:local-01", "attempt_number": 1,
            "operation_type": "identify", "status": "succeeded", "input": {"item_version": 1, "evidence": []},
            "cli": {"command": "heribase identify", "args": ["--json"]}, "remote_task_id": "snapshot-1",
            "started_at": "2026-08-28T11:00:00+00:00", "finished_at": "2026-08-28T11:00:01+00:00",
            "exit_code": 0, "classification": "success", "raw_response_ref": "recognition/raw/attempt-1.json",
            "raw_response_sha256": raw_hash, "error": None, "sequence": 1, "previous_event_sha256": None,
        }
        recognition_event["event_sha256"] = task_package.event_digest(recognition_event)
        (self.task / "recognition" / "attempts.jsonl").write_bytes(task_package.canonical_json(recognition_event) + b"\n")

        legacy_schema = task_package.read_json(self.task / "schemas" / "items.schema.json")
        active = legacy_schema["$defs"]["item"]["properties"]["active_identification"]["anyOf"][1]
        active["required"].extend(["currency_number", "uniq_uri"])
        active["properties"]["currency_number"] = {"type": ["string", "null"]}
        active["properties"]["uniq_uri"] = {"type": ["string", "null"]}
        task_package.write_json_atomic(self.task / "schemas" / "items.schema.json", legacy_schema)
        task_package.write_json_atomic(self.task / "integrity.json", task_package.build_integrity(self.task, manifest))

        self.assertFalse(task_package.validate_package_structure(self.task, self.task_key, check_integrity=True)["ok"])
        migrated = task_operations.migrate_drop_sensitive_identifiers(self.args(2))
        self.assertEqual(migrated["revision"], 3)
        self.assertTrue(task_package.validate_package_structure(self.task, self.task_key, check_integrity=True)["ok"])
        migrated_item = task_package.read_json(self.task / "data" / "items.json")["items"][0]
        self.assertNotIn("currency_number", migrated_item["active_identification"])
        self.assertNotIn("uniq_uri", migrated_item["active_identification"])

    def test_successful_recognition_clears_an_older_retryable_failure_flag(self):
        """一次后续成功不应继续把候选显示为“识别失败”。"""

        original = self.root / "coin.jpg"
        original.write_bytes(b"fixture-image")
        source = task_operations.ingest_source(
            self.args(1, file=str(original), kind="local_image", source_id="source-coin",
                      origin_type="local", origin_url=None, original_path=None,
                      mime_type="image/jpeg", parent_source_id=None, sheet=None, row=None,
                      column=None, cell=None, relationship_id=None)
        )
        item = {
            "local_id": f"{self.task_key}:local-01", "item_key": "local-01", "legacy_ids": [],
            "version": 1, "status": "active", "lineage": {"derived_from": [], "superseded_by": []},
            "source_refs": ["source-coin"],
            "evidence": [{"evidence_id": "coin", "source_id": "source-coin", "role": "obverse", "is_primary": True, "pair_confidence": 0.95, "rationale": "测试"}],
            "organization": {}, "field_claims": {}, "resolved_fields": {}, "active_identification": None,
            "review_projection": None, "collection_projection": None, "attention_flags": ["identity_not_identified"],
            "created_at": "2026-08-28T11:00:00+00:00", "updated_at": "2026-08-28T11:00:00+00:00",
        }
        self.assertTrue(task_operations.import_items(self.args(2, file=self.write_json("item.json", [item]), mode="merge"))["ok"])

        def event(attempt_id, version, status):
            return {
                "schema_version": "heribase.recognition-attempt.v1", "attempt_id": attempt_id,
                "local_id": item["local_id"], "attempt_number": 1, "operation_type": "identify", "status": status,
                "input": {"item_version": version, "evidence": [{"evidence_id": "coin", "sha256": source["source"]["sha256"]}]},
                "cli": {"command": "heribase identify", "args": ["--json"]}, "remote_task_id": None,
                "started_at": "2026-08-28T11:00:00+00:00", "finished_at": "2026-08-28T11:00:01+00:00",
                "exit_code": 1 if status != "succeeded" else 0,
                "classification": "retryable_error" if status != "succeeded" else "success",
                "error": {"message": "temporary"} if status != "succeeded" else None,
            }

        failed = task_operations.record_recognition(self.args(3, event_json=self.write_json("failed.json", event("attempt-failed", 1, "failed_retryable")), raw_json=None))
        self.assertIn("recognition_failed", failed["item"]["attention_flags"])
        succeeded = task_operations.record_recognition(
            self.args(4, event_json=self.write_json("succeeded.json", event("attempt-succeeded", 2, "succeeded")),
                      raw_json=self.write_json("success-raw.json", {"uri": "identify-1"}))
        )
        self.assertNotIn("recognition_failed", succeeded["item"]["attention_flags"])
        self.assertNotIn("identity_not_identified", succeeded["item"]["attention_flags"])

    def test_authorize_identification_binds_the_exact_active_pair_scope(self):
        """首次识别授权必须持久化确切候选、版本与当时的数据集指纹。"""

        timestamp = "2026-08-28T11:00:00+00:00"
        source_ids = []
        for role in ("front", "back"):
            fixture = self.root / f"{role}.jpg"
            fixture.write_bytes(f"fixture-{role}".encode("utf-8"))
            result = task_operations.ingest_source(
                self.args(
                    1 + len(source_ids),
                    file=str(fixture),
                    kind="local_image",
                    source_id=f"source-{role}",
                    origin_type="local",
                    origin_url=None,
                    original_path=None,
                    mime_type="image/jpeg",
                    parent_source_id=None,
                    sheet=None,
                    row=None,
                    column=None,
                    cell=None,
                    relationship_id=None,
                )
            )
            self.assertTrue(result["ok"])
            source_ids.append(f"source-{role}")
        item = {
            "local_id": f"{self.task_key}:local-01",
            "item_key": "local-01",
            "legacy_ids": [], "version": 1, "status": "active",
            "lineage": {"derived_from": [], "superseded_by": []},
            "source_refs": source_ids,
            "evidence": [
                {"evidence_id": "front", "source_id": "source-front", "role": "unknown", "is_primary": True, "pair_confidence": 0.95, "rationale": "测试配对"},
                {"evidence_id": "back", "source_id": "source-back", "role": "unknown", "is_primary": True, "pair_confidence": 0.95, "rationale": "测试配对"},
            ],
            "organization": {"pairing_state": "auto_ready", "source_assignment": [{"source_id": "source-front", "role": "obverse"}, {"source_id": "source-back", "role": "reverse"}]}, "field_claims": {}, "resolved_fields": {},
            "active_identification": None, "review_projection": None, "collection_projection": None,
            "attention_flags": [], "created_at": timestamp, "updated_at": timestamp,
        }
        self.assertTrue(task_operations.import_items(self.args(3, file=self.write_json("active-pair.json", [item]), mode="merge"))["ok"])
        # Import itself advances to a local precheck without a fabricated user
        # pairing decision or an ad hoc state rewrite.
        manifest = task_package.read_json(self.task / "manifest.json")
        self.assertEqual(manifest["state"], "awaiting_precheck")
        self.assertEqual((self.task / "pairing" / "decisions.jsonl").read_text(), "")
        self.assertEqual((self.task / "recognition" / "attempts.jsonl").read_text(), "")

        authorized = task_operations.authorize_identification(
            self.args(4, local_ids=[item["local_id"]], confirmed_by="fixture-user")
        )
        self.assertEqual(authorized["revision"], 5)
        self.assertEqual(authorized["authorized_local_ids"], [item["local_id"]])
        manifest = task_package.read_json(self.task / "manifest.json")
        self.assertEqual(manifest["state"], "identification_pending")
        audit_lines, _ = task_package.parse_jsonl(self.task / "audit" / "events.jsonl")
        self.assertEqual(audit_lines[-1]["event_type"], "identification_authorized")
        self.assertEqual(audit_lines[-1]["after"]["dataset_fingerprint"], manifest["dataset_fingerprint"])

    def test_full_source_identification_review_plan_and_collection_flow(self):
        original = self.root / "coin-front.jpg"
        original.write_bytes(b"fixture-image")
        source_result = task_operations.ingest_source(
            self.args(
                1,
                file=str(original),
                kind="local_image",
                source_id="source-front",
                origin_type="local",
                origin_url=None,
                original_path=None,
                mime_type="image/jpeg",
                parent_source_id=None,
                sheet=None,
                row=None,
                column=None,
                cell=None,
                relationship_id=None,
            )
        )
        self.assertEqual(source_result["revision"], 2)
        self.assertEqual(source_result["dataset_revision"], 2)

        source_sha = source_result["source"]["sha256"]
        timestamp = "2026-08-28T11:01:00+00:00"
        item = {
            "local_id": f"{self.task_key}:local-01",
            "item_key": "local-01",
            "legacy_ids": ["candidate_01"],
            "version": 1,
            "status": "active",
            "lineage": {"derived_from": [], "superseded_by": []},
            "source_refs": ["source-front"],
            "evidence": [
                {
                    "evidence_id": "evidence-front",
                    "source_id": "source-front",
                    "role": "obverse",
                    "is_primary": True,
                    "pair_confidence": 0.95,
                    "rationale": "文件名与人工配对",
                }
            ],
            "organization": {"type": "raw_coin", "image_pair_complete": True},
            "field_claims": {},
            "resolved_fields": {"title": {"value": "Test Coin", "claim_id": None}},
            "active_identification": None,
            "review_projection": None,
            "collection_projection": None,
            "attention_flags": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        items_path = self.write_json("items-input.json", [item])
        item_result = task_operations.import_items(
            self.args(2, file=items_path, mode="merge")
        )
        self.assertEqual(item_result["revision"], 3)

        recognition_raw = self.write_json(
            "recognition-raw.json",
            {
                "uri": "identify-1",
                "userUniqUri": "physical-coin-1",
                "currencyNumber": "USD-1",
                "uniqUri": "variant-1",
                "title": "Test Coin",
            },
        )
        recognition_event = {
            "schema_version": "heribase.recognition-attempt.v1",
            "attempt_id": "attempt-1",
            "local_id": f"{self.task_key}:local-01",
            "attempt_number": 1,
            "operation_type": "identify",
            "status": "succeeded",
            "input": {
                "item_version": 1,
                "evidence": [{"evidence_id": "evidence-front", "sha256": source_sha}],
            },
            "cli": {"command": "heribase identify", "args": ["--json"]},
            "remote_task_id": None,
            "started_at": "2026-08-28T11:02:00+00:00",
            "finished_at": "2026-08-28T11:02:01+00:00",
            "exit_code": 0,
            "classification": "success",
            "error": None,
        }
        recognition_event_path = self.write_json("recognition-event.json", recognition_event)
        recognition = task_operations.record_recognition(
            self.args(3, event_json=recognition_event_path, raw_json=recognition_raw)
        )
        self.assertEqual(recognition["revision"], 4)
        self.assertEqual(recognition["item"]["active_identification"]["user_uniq_uri"], "physical-coin-1")
        # API 即使暂时仍返回这些字段，也不能把敏感目录/标准身份写入任务快照。
        self.assertNotIn("currency_number", recognition["item"]["active_identification"])
        self.assertNotIn("uniq_uri", recognition["item"]["active_identification"])

        manifest = task_package.read_json(self.task / "manifest.json")
        review_package = {
            "schemaVersion": 2,
            "datasetFingerprint": manifest["dataset_fingerprint"],
            "exportedAt": "2026-08-28T11:03:00+00:00",
            "summary": {"collect": 1, "needPhoto": 0, "excluded": 0},
            "decisions": [
                {
                    "recordId": f"{self.task_key}:local-01",
                    "sourceRows": [],
                    "decision": "collect",
                    "updatedAt": "2026-08-28T11:03:00+00:00",
                    "source": "single",
                }
            ],
        }
        review_path = self.write_json("review-export.json", review_package)
        review = task_operations.import_review(
            self.args(4, file=review_path, mode="replace", allow_legacy=False)
        )
        self.assertEqual(review["revision"], 5)

        plan_result = task_operations.build_plan(
            self.args(5, operation="collection_add")
        )
        self.assertEqual(plan_result["revision"], 6)
        self.assertEqual(plan_result["impact"]["included"], 1)
        self.assertNotIn("currency_number", plan_result["items"][0])
        self.assertNotIn("uniq_uri", plan_result["items"][0])

        authorization = task_operations.authorize_plan(
            self.args(
                6,
                plan_id=plan_result["plan_id"],
                confirmed_payload_sha256=plan_result["payload_sha256"],
                confirmed_by="fixture-user",
            )
        )
        self.assertTrue(authorization["online_writes_allowed"], authorization)
        self.assertEqual(authorization["revision"], 7)

        preflight = task_operations.preflight_plan(
            argparse.Namespace(root=str(self.root), task_key=self.task_key)
        )
        self.assertTrue(preflight["online_writes_allowed"], preflight)

        ambiguous_raw = self.write_json(
            "collection-ambiguous.json",
            {"userUniqUri": "physical-coin-1", "message": "accepted but record id unavailable"},
        )
        collection_event = {
            "schema_version": "heribase.collection-operation.v1",
            "operation_id": "operation-1",
            "attempt_id": "collection-attempt-1",
            "plan_id": plan_result["plan_id"],
            "local_id": f"{self.task_key}:local-01",
            "attempt_number": 1,
            "operation_type": "collection_add",
            "status": "succeeded",
            "expected": {
                "item_version": 2,
                "identify_uri": "identify-1",
                "user_uniq_uri": "physical-coin-1",
            },
            "cli": {"command": "heribase collection add", "args": ["--uri", "identify-1", "--json"]},
            "started_at": "2026-08-28T11:04:00+00:00",
            "finished_at": "2026-08-28T11:04:01+00:00",
            "exit_code": 0,
            "classification": "success_without_collection_uri",
            "error": None,
        }
        collection_event_path = self.write_json("collection-event.json", collection_event)
        ambiguous = task_operations.record_collection(
            self.args(7, event_json=collection_event_path, raw_json=ambiguous_raw)
        )
        self.assertEqual(ambiguous["status"], "reconcile_required")
        self.assertEqual(ambiguous["plan_status"], "executing")

        collection_raw = self.write_json(
            "collection-raw.json",
            {"collectionUri": "collection-1", "userUniqUri": "physical-coin-1"},
        )
        collection_event.update(
            {
                "operation_id": "operation-2",
                "attempt_id": "collection-attempt-2",
                "attempt_number": 2,
                "classification": "reconciled_not_found",
            }
        )
        collection_event_path = self.write_json("collection-event-2.json", collection_event)
        collection = task_operations.record_collection(
            self.args(8, event_json=collection_event_path, raw_json=collection_raw)
        )
        self.assertEqual(collection["status"], "succeeded")
        self.assertEqual(collection["plan_status"], "consumed")
        self.assertEqual(collection["collection_projection"]["collection_uri"], "collection-1")

        # 已收藏记录的修改与取消使用同一套 plan → payload confirmation → preflight 闸门。
        update_intent = self.write_json(
            "update-intent.json",
            {"operations": [{"local_id": f"{self.task_key}:local-01", "changes": {"notes": "重点关注"}}]},
        )
        update_plan = task_operations.build_plan(
            self.args(9, operation="collection_update", operations_json=update_intent)
        )
        self.assertEqual(update_plan["items"][0]["collection_uri"], "collection-1")
        self.assertEqual(update_plan["items"][0]["changes"], {"notes": "重点关注"})
        update_auth = task_operations.authorize_plan(
            self.args(
                10,
                plan_id=update_plan["plan_id"],
                confirmed_payload_sha256=update_plan["payload_sha256"],
                confirmed_by="fixture-user",
            )
        )
        self.assertTrue(update_auth["online_writes_allowed"], update_auth)
        update_raw = self.write_json(
            "collection-update-raw.json",
            {"collectionUri": "collection-1", "userUniqUri": "physical-coin-1"},
        )
        update_event = {
            **collection_event,
            "operation_id": "operation-update",
            "attempt_id": "collection-attempt-update",
            "plan_id": update_plan["plan_id"],
            "attempt_number": 3,
            "operation_type": "collection_update",
            "classification": "success",
            "cli": {"command": "heribase collection update", "args": ["--collection-uri", "collection-1", "--notes", "重点关注", "--json"]},
        }
        update_event_path = self.write_json("collection-update-event.json", update_event)
        updated = task_operations.record_collection(
            self.args(11, event_json=update_event_path, raw_json=update_raw)
        )
        self.assertEqual(updated["collection_projection"]["applied_changes"], {"notes": "重点关注"})

        cancel_intent = self.write_json(
            "cancel-intent.json",
            {"operations": [{"local_id": f"{self.task_key}:local-01", "changes": {}}]},
        )
        cancel_plan = task_operations.build_plan(
            self.args(12, operation="collection_cancel", operations_json=cancel_intent)
        )
        cancel_auth = task_operations.authorize_plan(
            self.args(
                13,
                plan_id=cancel_plan["plan_id"],
                confirmed_payload_sha256=cancel_plan["payload_sha256"],
                confirmed_by="fixture-user",
            )
        )
        self.assertTrue(cancel_auth["online_writes_allowed"], cancel_auth)
        cancel_raw = self.write_json("collection-cancel-raw.json", {"collectionUri": "collection-1"})
        cancel_event = {
            **collection_event,
            "operation_id": "operation-cancel",
            "attempt_id": "collection-attempt-cancel",
            "plan_id": cancel_plan["plan_id"],
            "attempt_number": 4,
            "operation_type": "collection_cancel",
            "classification": "success",
            "cli": {"command": "heribase collection cancel", "args": ["--collection-uri", "collection-1", "--json"]},
        }
        cancel_event_path = self.write_json("collection-cancel-event.json", cancel_event)
        cancelled = task_operations.record_collection(
            self.args(14, event_json=cancel_event_path, raw_json=cancel_raw)
        )
        self.assertEqual(cancelled["collection_projection"]["status"], "cancelled")

        final = task_package.validate_package_structure(
            self.task, self.task_key, check_integrity=True
        )
        self.assertTrue(final["ok"], final)
        self.assertFalse(final["online_writes_allowed"])

    def test_sensitive_raw_is_rejected_without_creating_task_file(self):
        # 先走最小 source/item 流程，确保失败发生在 raw 写入前。
        original = self.root / "coin.jpg"
        original.write_bytes(b"fixture")
        source = task_operations.ingest_source(
            self.args(
                1,
                file=str(original),
                kind="local_image",
                source_id="source-1",
                origin_type="local",
                origin_url=None,
                original_path=None,
                mime_type="image/jpeg",
                parent_source_id=None,
                sheet=None,
                row=None,
                column=None,
                cell=None,
                relationship_id=None,
            )
        )
        self.assertTrue(source["ok"])
        sensitive = self.write_json("sensitive.json", {"access_token": "secret"})
        with self.assertRaisesRegex(task_package.PackageError, "敏感字段"):
            task_operations.read_exact_json(sensitive)
        self.assertEqual(list((self.task / "recognition" / "raw").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
