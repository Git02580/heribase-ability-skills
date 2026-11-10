"""Isolated connector regressions: real local transactions and a fake remote CLI.

No test starts a browser/server, reads the real home, or contacts an API.  The
existing FakeCLI is shared with the stable executor regression suite.
"""
import copy
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_executor import FakeCLI
import connector
from workspace_connector import INTENT_KIND
from workspace_service import WorkspaceService
from workspace_store import WorkspaceError, WorkspaceStore
from workspace_tasks import operations


class ConnectorCLI(FakeCLI):
    def __init__(self):
        super().__init__()
        self.unknown_collect = False
        self.recognized_year = None
        self.capacity_allowed = True
        self.identification_allowed = True
        self.readonly_failures = {}

    def __call__(self, argv):
        result = super().__call__(argv)
        if tuple(argv) in self.readonly_failures:
            failure = self.readonly_failures[tuple(argv)]
            if isinstance(failure, Exception):
                raise failure
            return failure
        if argv == ["collection", "capacity"] and self.capacity_allowed is False:
            envelope = json.loads(result)
            envelope["result"]["allowed"] = False
            result = json.dumps(envelope).encode()
            self.responses[self.last_id] = result
        if argv == ["identify", "eligibility"] and self.identification_allowed is False:
            envelope = json.loads(result)
            envelope["result"]["allowed"] = False
            result = json.dumps(envelope).encode()
            self.responses[self.last_id] = result
        if argv[0] == "identify" and "--front-img" in argv and self.recognized_year:
            envelope = json.loads(result)
            envelope["result"]["year"] = self.recognized_year
            result = json.dumps(envelope).encode()
            self.responses[self.last_id] = result
        if self.unknown_collect and argv[:2] == ["collection", "add"]:
            raise WorkspaceError("cli_timeout", "收藏终态未知", 409)
        return result


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.store = WorkspaceStore(self.home)
        self.cli = ConnectorCLI()
        self.service = WorkspaceService(self.store, self.cli, background=False)
        self.task = self.service.tasks.create("一枚钱币", "Asia/Shanghai", "user:web")
        self.key = self.task["manifest"]["task_key"]
        # Misleading names demonstrate that filenames never determine roles.
        self.front = self.ingest("looks-like-back.png", b"front-image")
        self.back = self.ingest("looks-like-front.png", b"back-image")

    def tearDown(self):
        self.tmp.cleanup()

    def task_now(self):
        return self.service.tasks.snapshot(self.key)

    def ingest(self, name, content):
        return self.service.tasks.ingest(self.key, self.task_now()["manifest"]["revision"],
                                         name, content, "user:web")["source"]["source_id"]

    def call(self, name, body, role="browser"):
        return self.service.mutate("/api/connector/" + name, body, role)

    def prepare(self, front=None, back=None):
        return self.call("prepare", {"taskKey": self.key, "expectedRevision": self.task_now()["manifest"]["revision"],
                         "obverseSourceId": front or self.front, "reverseSourceId": back or self.back})

    def identify(self, command_id="identify-one"):
        task = self.prepare()
        local_id = task["items"][0]["local_id"]
        plan = self.call("identification-plan", {"taskKey": self.key, "expectedRevision": task["manifest"]["revision"],
                                                "localIds": [local_id]})
        request = {"taskKey": self.key, "expectedRevision": plan["revision"], "localIds": [local_id],
                   "planHash": plan["hash"], "commandId": command_id}
        return self.call("identify", request), request

    def collect_body(self, command_id="collect-one"):
        task = self.task_now()
        item = task["items"][0]
        return {"taskKey": self.key, "expectedRevision": task["manifest"]["revision"],
                "localId": item["local_id"], "snapshotId": item["active_identification"]["snapshot_id"],
                "commandId": command_id}

    def writes(self):
        return [argv for argv in self.cli.calls if argv[:2] in (["file", "upload"], ["collection", "add"])
                or (argv[0] == "identify" and "--front-img" in argv)]

    def test_prepare_is_local_explicit_and_same_pair_does_not_mutate(self):
        task = self.prepare()
        item = task["items"][0]
        self.assertEqual(operations.identification_source_roles(item), {"obverse": self.front, "reverse": self.back})
        self.assertEqual(item["organization"]["pairing_state"], "confirmed")
        self.assertEqual(task["manifest"]["revision"], self.prepare()["manifest"]["revision"])
        self.assertEqual(len(self.task_now()["items"]), 1)
        self.assertEqual(self.cli.calls, [])

    def incomplete(self, source_id=None, role="obverse"):
        task = self.service.tasks.create_candidate(self.key, self.task_now()["manifest"]["revision"],
                                                    [source_id or self.front], "待补图的钱币", "user:web")
        item = task["items"][-1]
        task = self.service.tasks.pair(self.key, task["manifest"]["revision"], item["local_id"], "need_photo",
                                      [{"sourceId": source_id or self.front, "role": role}], "user:web")
        return task["items"][-1]["local_id"]

    def test_supplement_archives_and_confirms_each_missing_side_in_one_revision(self):
        for role, source_id, content in [("obverse", self.front, b"new-reverse"), ("reverse", self.back, b"new-obverse")]:
            local_id = self.incomplete(source_id, role)
            before = self.task_now()
            side = "reverse" if role == "obverse" else "obverse"
            reply = self.service.tasks.ingest(self.key, before["manifest"]["revision"], "missing.png", content, "user:web",
                                               supplement_local_id=local_id, supplement_side=side)
            after = self.task_now()
            item = next(i for i in after["items"] if i["local_id"] == local_id)
            self.assertEqual(after["manifest"]["revision"], before["manifest"]["revision"] + 1)
            self.assertEqual(operations.identification_source_roles(item), {role: source_id, side: reply["source"]["source_id"]})
            self.assertTrue(operations.identification_eligible(item))
            self.assertEqual(item["organization"]["pairing_state"], "confirmed")
            self.assertNotIn("source_incomplete", item["attention_flags"])
            self.assertTrue(after["health"]["ok"])
            self.assertEqual(len(after["items"]), len(before["items"]))
        self.assertEqual(self.cli.calls, [])

    def test_invalid_supplement_cannot_archive_a_file_or_change_an_existing_side(self):
        local_id = self.incomplete()
        before = self.task_now()
        inputs = set((self.service.tasks.root / self.key / "inputs").rglob("*"))
        for target, side, name, content in [(local_id, "obverse", "front.png", b"new-front"),
                                           (local_id, "reverse", "same.png", b"front-image"),
                                           (local_id, "reverse", "notes.txt", b"notes"),
                                           ("other:item", "reverse", "new.png", b"other")]:
            with self.assertRaises(WorkspaceError):
                self.service.tasks.ingest(self.key, before["manifest"]["revision"], name, content, "user:web",
                                          supplement_local_id=target, supplement_side=side)
            self.assertEqual(self.task_now()["manifest"]["revision"], before["manifest"]["revision"])
            self.assertEqual(self.task_now()["sources"], before["sources"])
            self.assertEqual(set((self.service.tasks.root / self.key / "inputs").rglob("*")), inputs)

    def test_supplement_keeps_previously_collected_items_and_their_evidence_unchanged(self):
        self.identify()
        self.call("collect", self.collect_body())
        collected = copy.deepcopy(self.task_now()["items"][0])
        source_id = self.ingest("third-front.png", b"third-front")
        local_id = self.incomplete(source_id)
        self.service.tasks.ingest(self.key, self.task_now()["manifest"]["revision"], "third-back.png", b"third-back", "user:web",
                                  supplement_local_id=local_id, supplement_side="reverse")
        self.assertEqual(self.task_now()["items"][0], collected)
        self.assertTrue(self.task_now()["health"]["ok"])
        self.assertEqual(self.task_now()["manifest"]["statistics"]["collected"], 1)
        with self.assertRaises(WorkspaceError):
            self.service.tasks.ingest(self.key, self.task_now()["manifest"]["revision"], "replacement.png", b"replacement", "user:web",
                                      supplement_local_id=collected["local_id"], supplement_side="reverse")

    def test_reverse_slots_expires_result_review_and_plan_without_losing_raw(self):
        self.identify()
        body = self.collect_body()
        reviewed = self.service.tasks.review(self.key, body["expectedRevision"], body["localId"], "collect", "user:web")
        self.service.executor.collection_plan(self.key, reviewed["manifest"]["revision"], [body["localId"]], "user:web")
        old = self.task_now()["items"][0]["active_identification"]
        task = self.prepare(self.back, self.front)
        item = task["items"][0]
        self.assertEqual(operations.identification_source_roles(item), {"obverse": self.back, "reverse": self.front})
        self.assertEqual(item["active_identification"]["status"], "stale")
        self.assertTrue(item["review_projection"]["stale"])
        self.assertEqual(task["plan"]["status"], "stale")
        self.assertTrue((self.service.tasks.root / self.key / old["raw_response_ref"]).is_file())

    def test_prepare_rejects_stale_revision_and_non_image_sources(self):
        task = self.prepare()
        with self.assertRaises(WorkspaceError) as caught:
            self.call("prepare", {"taskKey": self.key, "expectedRevision": 1,
                                   "obverseSourceId": self.front, "reverseSourceId": self.back})
        self.assertEqual(caught.exception.code, "revision_conflict")
        document = self.ingest("notes.txt", b"notes")
        for front, back in [(self.front, self.front), (self.front, document), ("/private/coin.png", self.back)]:
            with self.assertRaises(WorkspaceError):
                self.prepare(front, back)
        self.assertEqual(len(self.task_now()["items"]), 1)
        self.assertEqual(self.cli.calls, [])

    def test_prepare_never_moves_sources_between_two_active_coins(self):
        self.prepare()
        third = self.ingest("second-front.png", b"second-front")
        fourth = self.ingest("second-back.png", b"second-back")
        current = self.task_now()
        self.service.tasks.create_candidate(self.key, current["manifest"]["revision"], [third, fourth], "第二枚", "user:web")
        before = self.task_now()
        with self.assertRaises(WorkspaceError) as caught:
            self.prepare(self.front, third)
        self.assertEqual(caught.exception.code, "photo_replacement_requires_new_task")
        self.assertEqual(self.task_now()["manifest"]["revision"], before["manifest"]["revision"])
        self.assertEqual(len(self.task_now()["items"]), 2)
        self.assertEqual(self.cli.calls, [])

    def test_replacing_photo_before_identification_keeps_coin_and_archived_sources(self):
        first = self.prepare()
        old_item = first["items"][0]
        new_front = self.ingest("replacement.png", b"replacement-front")
        changed = self.prepare(new_front, self.back)
        self.assertEqual(len(changed["items"]), 1)
        self.assertEqual(changed["items"][0]["local_id"], old_item["local_id"])
        self.assertGreater(changed["items"][0]["version"], old_item["version"])
        self.assertEqual(operations.identification_source_roles(changed["items"][0]), {"obverse": new_front, "reverse": self.back})
        self.assertEqual(len(changed["sources"]), 3)
        self.assertTrue(changed["health"]["ok"])
        self.assertEqual(self.cli.calls, [])

    def test_distinct_source_ids_with_identical_photo_bytes_are_not_two_faces(self):
        duplicate_front = self.ingest("duplicate-front.png", b"front-image")
        before = self.task_now()["manifest"]["revision"]
        with self.assertRaises(WorkspaceError) as caught:
            self.prepare(self.front, duplicate_front)
        self.assertEqual(caught.exception.code, "incomplete_pair")
        self.assertEqual(self.task_now()["manifest"]["revision"], before)
        self.assertEqual(self.task_now()["items"], [])
        self.assertEqual(self.cli.calls, [])

    def test_replacing_photo_after_any_remote_result_requires_new_task(self):
        self.identify()
        new_front = self.ingest("replacement.png", b"replacement-front")
        before = self.task_now()
        with self.assertRaises(WorkspaceError) as caught:
            self.prepare(new_front, self.back)
        self.assertEqual(caught.exception.code, "photo_replacement_requires_new_task")
        self.assertEqual(self.task_now()["manifest"]["revision"], before["manifest"]["revision"])

    def test_routes_accept_authenticated_host_and_reject_extra_paths_actor_and_roles(self):
        created = self.call("create", {"name": "宿主单币", "timezone": "Asia/Shanghai"}, role="host")
        self.assertTrue(created["health"]["ok"])
        body = {"taskKey": self.key, "expectedRevision": self.task_now()["manifest"]["revision"],
                "obverseSourceId": self.front, "reverseSourceId": self.back}
        for extra in [{"path": "/etc/passwd"}, {"actor": "user:admin"}, {"root": "/tmp"}]:
            with self.assertRaises(WorkspaceError) as caught:
                self.call("prepare", {**body, **extra})
            self.assertEqual(caught.exception.code, "invalid_request")
        with self.assertRaises(WorkspaceError):
            self.call("prepare", body, role="untrusted")
        self.assertEqual(self.call("prepare", body, role="host")["items"][0]["organization"]["pairing_state"], "confirmed")

    def test_identify_keeps_plan_hash_revision_account_and_replay_guards(self):
        task = self.prepare()
        local_id = task["items"][0]["local_id"]
        plan = self.call("identification-plan", {"taskKey": self.key, "expectedRevision": task["manifest"]["revision"], "localIds": [local_id]})
        body = {"taskKey": self.key, "expectedRevision": plan["revision"], "localIds": [local_id], "planHash": plan["hash"], "commandId": "safe-identify"}
        with self.assertRaises(WorkspaceError) as caught:
            self.call("identify", {**body, "planHash": "changed"})
        self.assertEqual(caught.exception.code, "stale_plan")
        self.cli.account = "other-account"
        with self.assertRaises(WorkspaceError) as caught:
            self.call("identify", body)
        self.assertEqual(caught.exception.code, "stale_plan")
        self.assertEqual(self.writes(), [])
        self.cli.account = "fixture-account"
        first = self.call("identify", body)
        before = len(self.cli.calls)
        self.assertEqual(self.call("identify", body)["id"], first["id"])
        self.assertEqual(len(self.cli.calls), before)
        with self.assertRaises(WorkspaceError) as caught:
            self.call("identify", {**body, "localIds": ["other-coin"]})
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_identify_readonly_failures_explicitly_prove_no_write_started(self):
        for number, failure in enumerate([b"[]", b"not-json", WorkspaceError("cli_timeout", "资格查询中断", 409)]):
            with self.subTest(failure=repr(failure)):
                command_id = "identify-readonly-failure-" + str(number)
                self.cli.readonly_failures[("identify", "eligibility")] = failure
                with self.assertRaises(WorkspaceError) as caught:
                    self.identify(command_id)
                self.assertEqual(caught.exception.code, "cli_invalid_output" if isinstance(failure, bytes) else "cli_timeout")
                self.assertIs(caught.exception.details.get("remoteWriteStarted"), False)
                self.assertIsNone(self.store.get_entity("operation", command_id))
                self.assertEqual(self.writes(), [])

    def test_collect_readonly_failures_keep_review_and_intent_without_writing(self):
        self.identify()
        for number, failure in enumerate([b"[]", WorkspaceError("cli_timeout", "容量查询中断", 409)]):
            with self.subTest(failure=repr(failure)):
                body = self.collect_body("collect-readonly-failure-" + str(number))
                before = len(self.writes())
                self.cli.readonly_failures[("collection", "capacity")] = failure
                with self.assertRaises(WorkspaceError) as caught:
                    self.call("collect", body)
                self.assertEqual(caught.exception.code, "cli_invalid_output" if isinstance(failure, bytes) else "cli_timeout")
                self.assertIs(caught.exception.details.get("remoteWriteStarted"), False)
                self.assertIsNone(self.store.get_entity("operation", body["commandId"]))
                intent = self.store.get_entity(INTENT_KIND, body["commandId"])
                self.assertEqual(intent["data"]["status"], "stopped")
                self.assertEqual(intent["data"]["request"], body)
                item = self.task_now()["items"][0]
                self.assertEqual(item["review_projection"]["decision"], "collect")
                self.assertEqual(item["review_projection"]["identification_snapshot_id"], body["snapshotId"])
                self.assertEqual(len(self.writes()), before)
                calls_before_replay = len(self.cli.calls)
                with self.assertRaises(WorkspaceError) as replay:
                    self.call("collect", body)
                self.assertEqual(replay.exception.code, "confirmation_interrupted")
                self.assertIs(replay.exception.details.get("remoteWriteStarted"), False)
                self.assertEqual(len(self.cli.calls), calls_before_replay)

    def test_workspace_errors_after_reservation_never_claim_no_write(self):
        original_call = self.service.tasks._call
        def reject_authorization(key, revision, actor, function, **options):
            if function in {operations.authorize_identification, operations.authorize_plan}:
                raise WorkspaceError("task_validation_failed", "授权事务失败", 409, remoteWriteStarted=False)
            return original_call(key, revision, actor, function, **options)
        with patch.object(self.service.tasks, "_call", side_effect=reject_authorization):
            with self.assertRaises(WorkspaceError) as caught:
                self.identify("identify-reserved-failure")
        self.assertIsNot(caught.exception.details.get("remoteWriteStarted"), False)
        self.assertEqual(self.store.get_entity("operation", "identify-reserved-failure")["data"]["status"], "blocked")
        self.assertEqual(self.writes(), [])
        self.identify("identify-after-blocked-reservation")
        body = self.collect_body("collect-reserved-failure")
        before = len(self.writes())
        with patch.object(self.service.tasks, "_call", side_effect=reject_authorization):
            with self.assertRaises(WorkspaceError) as caught:
                self.call("collect", body)
        self.assertIsNot(caught.exception.details.get("remoteWriteStarted"), False)
        self.assertEqual(self.store.get_entity("operation", body["commandId"])["data"]["status"], "blocked")
        self.assertEqual(len(self.writes()), before)

    def test_unexpected_query_exception_gets_no_remote_state_annotation(self):
        failure = RuntimeError("unexpected read failure")
        self.cli.readonly_failures[("identify", "eligibility")] = failure
        with self.assertRaises(RuntimeError) as caught:
            self.identify("unexpected-identify-failure")
        self.assertIs(caught.exception, failure)
        self.assertFalse(hasattr(caught.exception, "details"))
        self.assertIsNone(self.store.get_entity("operation", "unexpected-identify-failure"))
        self.assertEqual(self.writes(), [])
        self.cli.readonly_failures.clear()
        self.identify("identify-before-unexpected-collect-failure")
        body = self.collect_body("unexpected-collect-failure")
        failure = RuntimeError("unexpected capacity failure")
        self.cli.readonly_failures[("collection", "capacity")] = failure
        before = len(self.writes())
        with self.assertRaises(RuntimeError) as caught:
            self.call("collect", body)
        self.assertIs(caught.exception, failure)
        self.assertFalse(hasattr(caught.exception, "details"))
        self.assertIsNone(self.store.get_entity("operation", body["commandId"]))
        self.assertEqual(len(self.writes()), before)

    def test_collect_accepts_only_current_displayed_snapshot_and_is_idempotent(self):
        self.identify()
        body = self.collect_body()
        for invalid in [{"snapshotId": "older-result"}, {"expectedRevision": body["expectedRevision"] - 1}, {"localId": "other-coin"}]:
            before = len(self.cli.calls)
            with self.assertRaises(WorkspaceError):
                self.call("collect", {**body, **invalid})
            self.assertEqual(len(self.cli.calls), before)
        first = self.call("collect", body)
        self.assertEqual(first["data"]["status"], "completed")
        current = self.task_now()
        self.assertEqual(current["items"][0]["review_projection"]["decision"], "collect")
        self.assertEqual(current["items"][0]["review_projection"]["identification_snapshot_id"], body["snapshotId"])
        self.assertEqual(current["items"][0]["collection_projection"]["status"], "succeeded")
        self.assertEqual(first["data"]["scope"][0]["identification_snapshot_id"], body["snapshotId"])
        before = len(self.cli.calls)
        self.cli.account = "changed-after-completion"
        self.assertEqual(self.call("collect", body)["id"], first["id"])
        self.assertEqual(len(self.cli.calls), before)
        self.assertEqual(len([argv for argv in self.writes() if argv[:2] == ["collection", "add"]]), 1)
        for changed in [{"snapshotId": "other"}, {"localId": "other"}, {"expectedRevision": current["manifest"]["revision"]}, {"taskKey": "other-task"}]:
            with self.assertRaises(WorkspaceError) as caught:
                self.call("collect", {**body, **changed})
            self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_command_ids_cannot_cross_connector_and_legacy_intents(self):
        _, identify_body = self.identify()
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", self.collect_body(identify_body["commandId"]))
        self.assertEqual(caught.exception.code, "idempotency_conflict")
        collect_body = self.collect_body()
        self.call("collect", collect_body)
        for path in ["/api/tasks/identify", "/api/tasks/collect"]:
            with self.assertRaises(WorkspaceError) as caught:
                self.service.mutate(path, {**identify_body, "commandId": collect_body["commandId"]}, "browser")
            self.assertEqual(caught.exception.code, "idempotency_conflict")
        with self.assertRaises(WorkspaceError) as caught:
            self.call("identify", {**identify_body, "commandId": collect_body["commandId"]})
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_unknown_collection_never_replays_and_blocks_other_commands(self):
        self.identify()
        body = self.collect_body()
        self.cli.unknown_collect = True
        first = self.call("collect", body)
        self.assertEqual(first["data"]["status"], "reconcile_required")
        before = len(self.cli.calls)
        self.assertEqual(self.call("collect", body)["data"]["status"], "reconcile_required")
        self.assertEqual(len(self.cli.calls), before)
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", {**body, "commandId": "a-new-command"})
        self.assertEqual(caught.exception.code, "operation_pending")
        with self.assertRaises(WorkspaceError):
            self.prepare()
        reopened = WorkspaceService(self.store, self.cli, background=False)
        self.assertEqual(reopened.connector.collect(body, "agent:connector")["data"]["status"], "reconcile_required")
        self.assertEqual(len(self.cli.calls), before)

    def test_unknown_identification_and_integrity_failure_block_shortcuts(self):
        self.cli.unknown = True
        operation, _ = self.identify()
        self.assertEqual(operation["data"]["status"], "reconcile_required")
        before = len(self.cli.calls)
        with self.assertRaises(WorkspaceError):
            self.prepare()
        with self.assertRaises(WorkspaceError):
            self.call("collect", {"taskKey": self.key, "expectedRevision": self.task_now()["manifest"]["revision"],
                                   "localId": self.task_now()["items"][0]["local_id"], "snapshotId": "unknown", "commandId": "unsafe"})
        self.assertEqual(len(self.cli.calls), before)

    def test_collect_review_conflict_cannot_be_automatically_resolved(self):
        self.prepare()
        current = self.task_now()
        item = copy.deepcopy(current["items"][0])
        item["resolved_fields"]["year"] = {"value": "1919", "source": "user"}
        item["version"] += 1
        self.service.tasks._import_json(self.key, current["manifest"]["revision"], "user:web", operations.import_items, [item], mode="merge")
        self.cli.recognized_year = "1920"
        self.identify()
        self.assertTrue(self.task_now()["items"][0]["reviewIssues"])
        body = self.collect_body()
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", body)
        self.assertEqual(caught.exception.code, "review_conflict")
        self.assertFalse(any(argv[:2] == ["collection", "add"] for argv in self.cli.calls))

    def test_corrupt_source_prevents_collect_before_review_or_queries(self):
        self.identify()
        body = self.collect_body()
        source = self.task_now()["sources"][0]
        (self.service.tasks.root / self.key / source["stored_path"]).write_bytes(b"changed-photo")
        before = len(self.cli.calls)
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", body)
        self.assertEqual(caught.exception.code, "data_inconsistent")
        self.assertEqual(len(self.cli.calls), before)

    def test_interrupted_preparation_owns_id_and_does_not_rebuild_on_replay(self):
        self.identify()
        body = self.collect_body()
        with patch.object(self.service.executor, "collection_plan", side_effect=WorkspaceError("account_changed", "账户变化", 409)):
            with self.assertRaises(WorkspaceError):
                self.call("collect", body)
        self.assertIsNotNone(self.store.get_entity(INTENT_KIND, body["commandId"]))
        self.assertIsNone(self.store.get_entity("operation", body["commandId"]))
        before = len(self.cli.calls)
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", body)
        self.assertEqual(caught.exception.code, "confirmation_interrupted")
        self.assertFalse(caught.exception.details["remoteWriteStarted"])
        self.assertEqual(len(self.cli.calls), before)
        with self.assertRaises(WorkspaceError) as caught:
            self.call("identify", {"taskKey": self.key, "expectedRevision": 1, "planHash": "x", "localIds": [], "commandId": body["commandId"]})
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_simultaneous_same_collect_command_writes_once(self):
        self.identify()
        body = self.collect_body()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call("collect", body), range(2)))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(len([argv for argv in self.cli.calls if argv[:2] == ["collection", "add"]]), 1)

    def test_collection_binding_and_collected_repair_guard_remain(self):
        self.identify()
        self.cli.account = "another-account"
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", self.collect_body())
        self.assertEqual(caught.exception.code, "account_changed")
        self.assertFalse(any(argv[:2] == ["collection", "add"] for argv in self.cli.calls))
        self.cli.account = "fixture-account"
        self.call("collect", self.collect_body("new-explicit-confirmation"))
        with self.assertRaises(WorkspaceError) as caught:
            self.prepare(self.back, self.front)
        self.assertEqual(caught.exception.code, "collection_conflict")
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", self.collect_body("no-duplicate-coin"))
        self.assertEqual(caught.exception.code, "already_collected")

    def test_explicit_capacity_refusal_never_issues_collection_add(self):
        self.identify()
        self.cli.capacity_allowed = False
        body = self.collect_body()
        with self.assertRaises(WorkspaceError) as caught:
            self.call("collect", body)
        self.assertEqual(caught.exception.code, "collection_not_allowed")
        self.assertIs(caught.exception.details["capacity"]["allowed"], False)
        self.assertFalse(any(argv[:2] == ["collection", "add"] for argv in self.cli.calls))
        self.assertIsNone(self.store.get_entity("operation", body["commandId"]))

    def test_explicit_identification_refusal_never_uploads_photos(self):
        self.cli.identification_allowed = False
        with self.assertRaises(WorkspaceError) as caught:
            self.identify()
        self.assertEqual(caught.exception.code, "not_eligible")
        self.assertEqual(self.writes(), [])

    def batch_identified(self):
        task = self.prepare()
        first = task['items'][0]['local_id']
        front = self.ingest('second-front.png', b'second-front')
        back = self.ingest('second-back.png', b'second-back')
        task = self.service.tasks.create_candidate(self.key, self.task_now()['manifest']['revision'], [front, back], '第二枚', 'user:web')
        second = next(item['local_id'] for item in task['items'] if item['local_id'] != first)
        task = self.service.tasks.pair(self.key, task['manifest']['revision'], second, 'confirm_pair',
            [{'sourceId':front,'role':'obverse'},{'sourceId':back,'role':'reverse'}], 'user:web')
        plan = self.call('identification-plan', {'taskKey':self.key,'expectedRevision':task['manifest']['revision'],'localIds':[first,second]})
        self.call('identify', {'taskKey':self.key,'expectedRevision':plan['revision'],'localIds':[first,second],
            'planHash':plan['hash'],'commandId':'identify-batch'})
        task = self.task_now()
        return {'taskKey':self.key,'expectedRevision':task['manifest']['revision'],'commandId':'collect-batch',
            'items':[{'localId':item['local_id'],'snapshotId':item['active_identification']['snapshot_id']} for item in task['items']]}

    def test_batch_collection_accepts_exact_snapshots_once_and_replays_without_cli(self):
        body = self.batch_identified()
        op = self.call('collect-batch', body)
        self.assertEqual(op['data']['status'], 'completed')
        self.assertEqual(len(op['data']['scope']), 2)
        self.assertTrue(all(item['collection_projection']['collection_uri'] for item in self.task_now()['items']))
        before = len(self.cli.calls)
        self.assertEqual(self.call('collect-batch', body)['id'], op['id'])
        self.assertEqual(len(self.cli.calls), before)
        with self.assertRaises(WorkspaceError) as caught:
            self.call('collect-batch', {**body,'items':body['items'][:1]})
        self.assertEqual(caught.exception.code,'idempotency_conflict')

    def test_batch_stale_or_duplicate_snapshot_rejects_entire_scope_before_review(self):
        body = self.batch_identified()
        before = self.task_now()['manifest']['revision']
        for items in [[body['items'][0],{**body['items'][1],'snapshotId':'old-snapshot'}], [body['items'][0]]*2]:
            with self.assertRaises(WorkspaceError) as caught:
                self.call('collect-batch',{**body,'items':items})
            self.assertIn(caught.exception.code,{'stale_snapshot','invalid_selection'})
            self.assertFalse(caught.exception.details['remoteWriteStarted'])
            self.assertEqual(self.task_now()['manifest']['revision'],before)
        self.assertFalse(any(call[:2]==['collection','add'] for call in self.cli.calls))

    def test_batch_unknown_collection_retains_original_operation_without_replay(self):
        body = self.batch_identified()
        self.cli.unknown_collect = True
        op = self.call('collect-batch', body)
        self.assertEqual(op['data']['status'],'reconcile_required')
        before = len(self.cli.calls)
        self.assertEqual(self.call('collect-batch',body)['id'],op['id'])
        self.assertEqual(len(self.cli.calls),before)

    def test_authentication_failure_is_actionable_before_any_write_reservation(self):
        task = self.prepare()
        self.cli.readonly_failures[('identify','eligibility')] = json.dumps({'status':'failed',
            'error':{'code':'UNAUTHENTICATED','message':'authentication_required','httpStatus':200}}).encode()
        with self.assertRaises(WorkspaceError) as caught:
            self.call('identification-plan', {'taskKey':self.key,'expectedRevision':task['manifest']['revision'],
                'localIds':[task['items'][0]['local_id']]})
        self.assertEqual(caught.exception.code,'account_required')
        self.assertFalse(caught.exception.details['remoteWriteStarted'])
        self.assertEqual(self.task_now()['manifest']['revision'],task['manifest']['revision'])
        self.assertEqual(self.store.list_entities('operation'),[])
        self.assertEqual(self.writes(),[])
        self.assertTrue(self.store.list_entities('cli-query-log'))

    def test_preflight_translates_service_contract_error_without_creating_write_intent(self):
        task = self.prepare()
        self.cli.readonly_failures[('identify','eligibility')] = json.dumps({'status':'failed',
            'error':{'code':'API_ERROR','message':'Agent API response is not valid JSON','httpStatus':200}}).encode()
        with self.assertRaises(WorkspaceError) as caught:
            self.call('identification-plan', {'taskKey':self.key,'expectedRevision':task['manifest']['revision'],
                'localIds':[task['items'][0]['local_id']]})
        self.assertEqual(caught.exception.code,'service_invalid_response')
        self.assertFalse(caught.exception.details['remoteWriteStarted'])
        self.assertEqual(self.store.list_entities('operation'),[])
        self.assertEqual(self.writes(),[])
        self.assertTrue(self.store.list_entities('cli-query-log'))


class DescribeTests(unittest.TestCase):
    def task(self):
        return {"manifest": {"task_key": "20261019-0001-collection", "revision": 7, "display_name": "单枚钱币"},
                "health": {"ok": True}, "sources": [], "items": [{"status": "active", "local_id": "coin-one",
                "evidence": [], "active_identification": {"status": "succeeded", "snapshot_id": "snapshot-one"},
                "recognitionResult": {"title": "当前结果", "year": "1920"},
                "reviewIssues": [{"field": "年份", "original": "1919", "recognized": "1920"}],
                "reviewIssuesResolved": False}]}

    def test_current_healthy_result_exposes_unresolved_source_differences(self):
        task = self.task()
        result = connector.describe(task)
        self.assertEqual(result["result"], task["items"][0]["recognitionResult"])
        self.assertEqual(result["reviewIssues"], task["items"][0]["reviewIssues"])
        self.assertIs(result["reviewIssuesResolved"], False)
        self.assertEqual(result["stage"], "identified")
        self.assertEqual(result["nextAction"], "review_source_differences")

    def test_resolved_or_absent_differences_keep_collection_next_action(self):
        for issues, resolved in [([], False), ([{"field": "年份"}], True)]:
            with self.subTest(issues=issues, resolved=resolved):
                task = self.task()
                task["items"][0].update(reviewIssues=issues, reviewIssuesResolved=resolved)
                result = connector.describe(task)
                self.assertEqual(result["reviewIssues"], issues)
                self.assertIs(result["reviewIssuesResolved"], resolved)
                self.assertEqual(result["nextAction"], "accept_result_and_collect")

    def test_unhealthy_or_stale_results_do_not_publish_review_conclusions(self):
        for state in ["unhealthy", "stale"]:
            with self.subTest(state=state):
                task = self.task()
                if state == "unhealthy":
                    task["health"]["ok"] = False
                else:
                    task["items"][0]["active_identification"]["status"] = "stale"
                result = connector.describe(task)
                self.assertIsNone(result["result"])
                self.assertNotIn("reviewIssues", result)
                self.assertNotIn("reviewIssuesResolved", result)
                self.assertNotEqual(result["nextAction"], "review_source_differences")

    def test_pending_reconciliation_takes_precedence_over_difference_review(self):
        task = self.task()
        operation = {"id": "original-command", "data": {"taskKey": task["manifest"]["task_key"],
                     "kind": "collect", "status": "reconcile_required", "message": "需要核验原操作"}}
        result = connector.describe(task, [operation])
        self.assertEqual(result["reviewIssues"], task["items"][0]["reviewIssues"])
        self.assertEqual(result["stage"], "reconcile_required")
        self.assertEqual(result["nextAction"], "inspect_original_operation")


class HostHelperTests(unittest.TestCase):
    tearDown = ConnectorTests.tearDown
    task_now = ConnectorTests.task_now
    ingest = ConnectorTests.ingest
    call = ConnectorTests.call
    prepare = ConnectorTests.prepare
    identify = ConnectorTests.identify
    collect_body = ConnectorTests.collect_body
    def setUp(self):
        ConnectorTests.setUp(self)
        self.started, self.requested, self.archived = [], [], []
        self.client = connector.ConnectorClient(self.home, self.request, self.start, self.upload)

    def start(self, home, open_browser):
        self.started.append((home, open_browser))
        return {"url": "http://127.0.0.1:1/#access=secret"}

    def request(self, home, path, body=None, role="host"):
        self.requested.append((path, copy.deepcopy(body), role))
        if path == "/api/snapshot":
            return self.service.snapshot()
        if path.startswith("/api/task?"):
            return self.service.tasks.snapshot(parse_qs(urlsplit(path).query)["key"][0])
        return self.service.mutate(path, body, role)

    def upload(self, home, key, revision, name, content):
        self.archived.append((key, revision, name, content))
        with self.service.executor.lock:
            self.service.executor.assert_idle(key)
            return self.service.tasks.ingest(key, revision, name, content, "agent:connector")

    def test_helper_complete_flow_uses_durable_runtime_and_current_ids(self):
        front, back = self.home / "front.png", self.home / "back.png"
        front.write_bytes(b"helper-front")
        back.write_bytes(b"helper-back")
        prepared = self.client.prepare(front, back, title="聊天里的钱币")
        key = prepared["taskKey"]
        self.assertEqual(prepared["stage"], "prepared")
        self.assertEqual(self.cli.calls, [])
        self.assertEqual(len(self.archived), 2)
        replay = self.client.prepare(front, back, task_key=key)
        self.assertEqual(replay["revision"], prepared["revision"])
        self.assertEqual(len(self.archived), 2)
        preview = self.client.identification_plan(key)
        self.assertEqual(preview["stage"], "awaiting_identification_confirmation")
        recognized = self.client.identify(key, preview["plan"]["revision"], preview["plan"]["hash"], "helper-identify", confirmed=True)
        self.assertEqual(recognized["stage"], "identified")
        self.assertEqual(recognized["result"]["title"], "真实返回标题")
        collected = self.client.collect(key, recognized["revision"], recognized["localId"], recognized["snapshotId"], "helper-collect", confirmed=True)
        self.assertEqual(collected["stage"], "collected")
        self.assertEqual(self.client.status(key)["collectionUri"], "fixture-collection")
        self.assertTrue(all(open_browser is False for _, open_browser in self.started))
        self.assertTrue(all(role == "host" for _, _, role in self.requested))
        self.assertFalse(any("inbox" in path for path, _, _ in self.requested))
        self.assertNotIn("secret", json.dumps(collected))
        self.assertFalse(any(str(front) in json.dumps(body) or str(back) in json.dumps(body)
                             for _, body, _ in self.requested if body))

    def test_helper_requires_confirmation_before_starting_or_sending(self):
        for call in [lambda: self.client.identify(self.key, 1, "hash", "id"),
                     lambda: self.client.collect(self.key, 1, "coin", "snapshot", "id")]:
            with self.assertRaises(WorkspaceError) as caught:
                call()
            self.assertEqual(caught.exception.code, "confirmation_required")
        self.assertEqual(self.started, [])
        self.assertEqual(self.requested, [])

    def test_helper_unknown_results_report_original_operation_without_new_intent(self):
        self.identify()
        self.cli.unknown_collect = True
        body = self.collect_body()
        result = self.client.collect(self.key, body["expectedRevision"], body["localId"], body["snapshotId"], body["commandId"], confirmed=True)
        self.assertEqual(result["stage"], "reconcile_required")
        self.assertEqual(result["nextAction"], "inspect_original_operation")
        before = len(self.cli.calls)
        replay = self.client.collect(self.key, body["expectedRevision"], body["localId"], body["snapshotId"], body["commandId"], confirmed=True)
        self.assertEqual(replay["operation"]["id"], body["commandId"])
        self.assertEqual(len(self.cli.calls), before)

    def test_helper_upload_has_host_auth_and_only_basename_query(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"source":{"source_id":"fixture"},"revision":2}'
        captured = []
        class Opener:
            def open(self, request, timeout):
                captured.append(request)
                return Response()
        with patch.object(connector, "read_runtime", return_value={"url": "http://127.0.0.1:1", "hostKey": "host-secret"}), \
             patch.object(connector, "build_opener", return_value=Opener()):
            connector.upload_source(self.home, self.key, 1, "front.png", b"photo")
        self.assertEqual(captured[0].get_header("Authorization"), "Bearer host-secret")
        self.assertEqual(captured[0].data, b"photo")
        self.assertEqual(parse_qs(urlsplit(captured[0].full_url).query)["name"], ["front.png"])
        self.assertNotIn(str(self.home), captured[0].full_url)


if __name__ == "__main__":
    unittest.main()
