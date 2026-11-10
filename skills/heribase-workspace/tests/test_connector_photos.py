"""Real local photo transactions; all recognition/collection calls use FakeCLI."""
import copy
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_executor import FakeCLI
import workspace_connector_photos as photo_ops
from workspace_service import WorkspaceService
from workspace_store import WorkspaceError, WorkspaceStore
from workspace_tasks import operations


class ConnectorPhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.tmp.name))
        self.cli = FakeCLI()
        self.service = WorkspaceService(self.store, self.cli, background=False, organizer_runner=lambda *_: {})
        self.tasks = self.service.tasks
        self.key = self.tasks.create("添加页照片", "Asia/Shanghai", "user:web")["manifest"]["task_key"]
        self.number = 0

    def tearDown(self):
        self.service.organizer.close()
        self.tmp.cleanup()

    def snapshot(self):
        return self.tasks.snapshot(self.key)

    def source(self, content=None, name=None):
        self.number += 1
        return self.tasks.ingest(self.key, self.snapshot()["manifest"]["revision"], name or f"photo-{self.number}.png",
                                 content or f"photo-{self.number}".encode(), "user:web")["source"]["source_id"]

    def candidate(self, source_ids, *, state="needs_review", status="active", kind="coin", roles=None):
        task = self.tasks.create_candidate(self.key, self.snapshot()["manifest"]["revision"], source_ids, "待核对的钱币", "user:web")
        item = copy.deepcopy(task["items"][-1])
        item["version"] += 1
        item["status"] = status
        item["organization"].update(input_kind=kind, pairing_state="needs_review" if state == "confirmed" else state)
        item["attention_flags"] = ["source_incomplete"] if status == "source_incomplete" or state == "single_side" else [] if state == "auto_ready" else ["pairing_needs_confirmation"]
        if roles:
            item["organization"]["source_assignment"] = [{"source_id": source_id, "role": role} for source_id, role in zip(source_ids, roles)]
            for entry, role in zip(item["evidence"], roles):
                entry["role"] = role
        self.tasks._import_json(self.key, task["manifest"]["revision"], "user:web", operations.import_items, [item], mode="merge")
        if state == "confirmed":
            self.tasks.pair(self.key, self.snapshot()["manifest"]["revision"], item["local_id"], "confirm_pair",
                            [{"sourceId": source_id, "role": role} for source_id, role in zip(source_ids, roles or ["obverse", "reverse"])], "user:web")
        return item["local_id"]

    def item(self, local_id):
        return next(item for item in self.snapshot()["items"] if item["local_id"] == local_id)

    def request(self, local_id, front, back, revision=None):
        return {"taskKey": self.key, "expectedRevision": revision or self.snapshot()["manifest"]["revision"],
                "localId": local_id, "obverseSourceId": front, "reverseSourceId": back}

    def photos(self, local_id, front, back, revision=None):
        return self.service.mutate("/api/connector/photos", self.request(local_id, front, back, revision), "browser")

    def files(self):
        task = self.tasks.resolve(self.key)
        names = ["manifest.json", "data/items.json", "inputs/sources.json", "integrity.json",
                 "pairing/decisions.jsonl", "audit/events.jsonl", "collection/plan.json"]
        return {name: (task / name).read_bytes() if (task / name).exists() else None for name in names}

    def identify(self, local_id, command_id="identify-fixture"):
        revision = self.snapshot()["manifest"]["revision"]
        plan = self.service.executor.identification_plan(self.key, revision, [local_id])
        return self.service.executor.identify({"taskKey": self.key, "expectedRevision": revision,
            "planHash": plan["hash"], "localIds": [local_id], "commandId": command_id}, "user:web")

    def test_swaps_own_pair_and_latest_same_pair_is_a_noop(self):
        front, back = self.source(), self.source()
        target = self.candidate([front, back], state="confirmed")
        before = self.snapshot()
        changed = self.photos(target, back, front)
        item = self.item(target)
        self.assertEqual(changed["manifest"]["revision"], before["manifest"]["revision"] + 1)
        self.assertEqual(operations.identification_source_roles(item), {"obverse": back, "reverse": front})
        self.assertTrue(operations.identification_eligible(item))
        files = self.files()
        self.photos(target, back, front)
        self.assertEqual(self.files(), files)
        self.assertEqual(self.cli.calls, [])

    def test_partial_donor_keeps_every_unselected_photo_and_origin(self):
        front, back, extra, detail = [self.source() for _ in range(4)]
        target = self.candidate([front], status="source_incomplete", roles=["unknown"])
        donor = self.candidate([back, extra, detail])
        before = self.snapshot()
        originals = {source["source_id"]: self.tasks.source(self.key, source["source_id"])[0] for source in before["sources"]}
        changed = self.photos(target, front, back)
        self.assertEqual(changed["manifest"]["revision"], before["manifest"]["revision"] + 1)
        self.assertTrue(changed["health"]["ok"])
        self.assertEqual(len(changed["items"]), 2)
        current_donor, current_target = self.item(donor), self.item(target)
        self.assertEqual([entry["source_id"] for entry in current_donor["evidence"]], [extra, detail])
        self.assertEqual(current_donor["status"], "active")
        self.assertEqual(current_donor["organization"]["pairing_state"], "needs_review")
        self.assertEqual(current_donor["source_refs"], [back, extra, detail])
        self.assertEqual(current_donor["lineage"]["superseded_by"], [])
        self.assertIn(donor, current_target["lineage"]["derived_from"])
        self.assertEqual(current_target["status"], "active")
        self.assertEqual(current_target["organization"]["pairing_state"], "confirmed")
        self.assertTrue(operations.identification_eligible(current_target))
        for source_id, content in originals.items():
            self.assertEqual(self.tasks.source(self.key, source_id)[0], content)
        events = [json.loads(line) for line in (self.tasks.resolve(self.key) / "audit/events.jsonl").read_text().splitlines()]
        transfer = events[-1]["details"]["transfers"][0]
        self.assertEqual(transfer["remainingSourceIds"], [extra, detail])
        self.assertEqual(self.cli.calls, [])

    def test_empty_donor_is_superseded_with_bidirectional_lineage(self):
        front, back = self.source(), self.source()
        target = self.candidate([front], state="single_side", status="source_incomplete", roles=["obverse"])
        donor = self.candidate([back], state="single_side", status="source_incomplete", roles=["reverse"])
        self.photos(target, front, back)
        self.assertEqual(self.item(donor)["status"], "superseded")
        self.assertEqual(self.item(donor)["evidence"], [])
        self.assertEqual(self.item(donor)["source_refs"], [back])
        self.assertIn(target, self.item(donor)["lineage"]["superseded_by"])
        self.assertIn(donor, self.item(target)["lineage"]["derived_from"])
        self.assertTrue(self.snapshot()["health"]["ok"])

    def test_two_donors_keep_remainders_and_released_target_photo_stays_processed(self):
        old, front, extra_front, back, extra_back = [self.source() for _ in range(5)]
        target = self.candidate([old], roles=["unknown"])
        donor_one = self.candidate([front, extra_front])
        donor_two = self.candidate([back, extra_back])
        before = self.snapshot()["manifest"]["revision"]
        self.photos(target, front, back)
        self.assertEqual(self.snapshot()["manifest"]["revision"], before + 1)
        for donor, remaining in [(donor_one, extra_front), (donor_two, extra_back)]:
            item = self.item(donor)
            self.assertEqual([entry["source_id"] for entry in item["evidence"]], [remaining])
            self.assertEqual(item["status"], "source_incomplete")
        item = self.item(target)
        self.assertIn(old, item["source_refs"])
        self.assertNotIn(old, [entry["source_id"] for entry in item["evidence"]])
        self.assertEqual(set(item["lineage"]["derived_from"]), {donor_one, donor_two})

    def test_auto_ready_is_adjustable_but_confirmed_owner_is_protected_including_hash_alias(self):
        front, back, extra = [self.source() for _ in range(3)]
        target = self.candidate([front])
        donor = self.candidate([back, extra], state="auto_ready", roles=["obverse", "reverse"])
        self.photos(target, front, back)
        self.assertEqual(self.item(donor)["status"], "source_incomplete")
        protected_front, protected_back = self.source(b"protected-front"), self.source()
        protected = self.candidate([protected_front, protected_back], state="confirmed")
        alias = self.source(b"protected-front")
        for selected in [protected_front, alias]:
            files = self.files()
            with self.assertRaises(WorkspaceError) as caught:
                self.photos(donor, extra, selected)
            self.assertEqual(caught.exception.code, "photo_source_locked")
            self.assertEqual(caught.exception.details["localId"], protected)
            self.assertEqual(self.files(), files)

    def test_recognized_target_and_historical_business_owner_cannot_change(self):
        front, back, other = [self.source() for _ in range(3)]
        recognized = self.candidate([front, back], state="confirmed")
        target = self.candidate([other])
        self.identify(recognized)
        before, calls = self.files(), len(self.cli.calls)
        with self.assertRaises(WorkspaceError) as caught:
            self.photos(recognized, back, front)
        self.assertEqual(caught.exception.code, "photo_target_locked")
        with self.assertRaises(WorkspaceError) as caught:
            self.photos(target, other, front)
        self.assertEqual(caught.exception.code, "photo_source_locked")
        self.assertEqual(self.files(), before)
        self.assertEqual(len(self.cli.calls), calls)

    def test_collected_target_cannot_replace_or_reuse_its_photos(self):
        front, back, other = [self.source() for _ in range(3)]
        collected = self.candidate([front, back], state="confirmed")
        target = self.candidate([other])
        self.identify(collected)
        current = self.snapshot()
        current = self.tasks.review(self.key, current["manifest"]["revision"], collected, "collect", "user:web")
        plan = self.service.executor.collection_plan(self.key, current["manifest"]["revision"], [collected], "user:web")
        self.service.executor.collect({"taskKey": self.key, "expectedRevision": plan["revision"], "planId": plan["plan_id"],
                                      "planHash": plan["payload_sha256"], "commandId": "collect-fixture"}, "user:web")
        before = self.files()
        for local_id, a, b, code in [(collected, back, front, "photo_target_locked"), (target, other, back, "photo_source_locked")]:
            with self.assertRaises(WorkspaceError) as caught:
                self.photos(local_id, a, b)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.files(), before)

    def test_bad_source_second_donor_conflict_has_no_partial_move_or_log(self):
        old, front, retained, protected_front, protected_back = [self.source() for _ in range(5)]
        target = self.candidate([old])
        donor = self.candidate([front, retained])
        self.candidate([protected_front, protected_back], state="confirmed")
        before = self.files()
        with self.assertRaises(WorkspaceError):
            self.photos(target, front, protected_front)
        self.assertEqual(self.files(), before)
        self.assertEqual([entry["source_id"] for entry in self.item(donor)["evidence"]], [front, retained])

    def test_promotion_document_and_identity_conflicts_are_not_coin_photo_sources(self):
        for kind in ["promotional_material", "document"]:
            own, outside = self.source(), self.source()
            target = self.candidate([own])
            protected = self.candidate([outside], kind=kind)
            before = self.files()
            with self.assertRaises(WorkspaceError) as caught:
                self.photos(target, own, outside)
            self.assertEqual(caught.exception.code, "photo_source_locked")
            with self.assertRaises(WorkspaceError) as caught:
                self.photos(protected, outside, own)
            self.assertEqual(caught.exception.code, "photo_target_locked")
            self.assertEqual(self.files(), before)
        source = self.source()
        conflict = self.candidate([source], status="identity_conflict")
        with self.assertRaises(WorkspaceError) as caught:
            self.photos(conflict, source, self.source())
        self.assertEqual(caught.exception.code, "photo_target_locked")

    def test_same_id_same_hash_non_image_and_missing_sources_cannot_mutate(self):
        first = self.source(b"duplicate")
        duplicate = self.source(b"duplicate")
        target = self.candidate([first])
        document = self.source(b"text", "notes.txt")
        before = self.files()
        for a, b in [(first, first), (first, duplicate), (first, document), (first, "/etc/passwd")]:
            with self.assertRaises(WorkspaceError):
                self.photos(target, a, b)
            self.assertEqual(self.files(), before)

    def test_schema_failure_and_second_log_validation_leave_every_file_unchanged(self):
        front, back, remaining = [self.source() for _ in range(3)]
        target = self.candidate([front])
        self.candidate([back, remaining])
        before = self.files()
        validate = photo_ops.core.validate_with_schema
        for rejected_label in ["调整照片", "audit/events.jsonl"]:
            def reject(task, schema, data, label):
                return ["fixture validation refusal"] if label == rejected_label else validate(task, schema, data, label)
            with patch.object(photo_ops.core, "validate_with_schema", side_effect=reject):
                with self.assertRaises(WorkspaceError):
                    self.photos(target, front, back)
            self.assertEqual(self.files(), before)

    def test_revision_pending_operation_and_organization_are_real_guards(self):
        front, back, spare = [self.source() for _ in range(3)]
        target = self.candidate([spare])
        before = self.files()
        with self.assertRaises(WorkspaceError) as caught:
            self.photos(target, spare, back, revision=1)
        self.assertEqual(caught.exception.code, "revision_conflict")
        self.assertEqual(self.files(), before)
        self.store.save_entity("organization", self.key, {"status": "running"}, 0, "system:test")
        with self.assertRaises(WorkspaceError) as caught:
            self.photos(target, spare, back)
        self.assertEqual(caught.exception.code, "organization_pending")
        self.assertEqual(self.files(), before)
        entry = self.store.get_entity("organization", self.key)
        self.store.save_entity("organization", self.key, {"status": "completed"}, entry["revision"], "system:test")
        recognized = self.candidate([front, back], state="confirmed")
        self.cli.unknown = True
        self.identify(recognized)
        before, calls = self.files(), len(self.cli.calls)
        with self.assertRaises(WorkspaceError) as caught:
            self.photos(target, spare, back)
        self.assertEqual(caught.exception.code, "operation_pending")
        self.assertEqual(self.files(), before)
        self.assertEqual(len(self.cli.calls), calls)

    def test_stage_then_explicit_unknown_single_pair_works_in_both_directions(self):
        for existing_role in ["obverse", "reverse"]:
            existing = self.source()
            target = self.candidate([existing], state="single_side", status="source_incomplete", roles=["unknown"])
            before = self.snapshot()
            staged = self.service.connector.stage_photo(self.key, before["manifest"]["revision"], target,
                f"new-{existing_role}.png", f"new-{existing_role}".encode(), "user:web")
            self.assertEqual(self.item(target)["evidence"], next(item for item in before["items"] if item["local_id"] == target)["evidence"])
            self.assertIsNone(self.store.get_entity("organization", self.key))
            a, b = (existing, staged["source"]["source_id"]) if existing_role == "obverse" else (staged["source"]["source_id"], existing)
            self.photos(target, a, b)
            self.assertEqual(operations.identification_source_roles(self.item(target)), {"obverse": a, "reverse": b})
            self.assertTrue(operations.identification_eligible(self.item(target)))
        self.assertEqual(self.cli.calls, [])

    def test_stage_validates_target_revision_and_image_without_archive_side_effects(self):
        front = self.source()
        target = self.candidate([front], roles=["unknown"])
        revision = self.snapshot()["manifest"]["revision"]
        before = self.files()
        for key, rev, local_id, name in [(self.key, 1, target, "new.png"), (self.key, revision, "missing", "new.png"),
                                          (self.key, revision, target, "notes.txt"), (self.key, revision, target, "../new.png")]:
            with self.assertRaises(WorkspaceError):
                self.service.connector.stage_photo(key, rev, local_id, name, b"new", "user:web")
            self.assertEqual(self.files(), before)

    def test_concurrent_saves_only_commit_once_and_http_shape_rejects_paths(self):
        front, back = self.source(), self.source()
        target = self.candidate([front])
        body = self.request(target, front, back)
        def save(_):
            try:
                return self.service.mutate("/api/connector/photos", body, "browser")["manifest"]["revision"]
            except WorkspaceError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(save, range(2)))
        self.assertIn("revision_conflict", replies)
        self.assertIn(body["expectedRevision"] + 1, replies)
        before = self.files()
        with self.assertRaises(WorkspaceError) as caught:
            self.service.mutate("/api/connector/photos", {**body, "path": "/etc/passwd"}, "browser")
        self.assertEqual(caught.exception.code, "invalid_request")
        self.assertEqual(self.files(), before)


if __name__ == "__main__":
    unittest.main()
