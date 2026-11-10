"""An explicit single- or multi-coin flow over the existing task and execution guards.

The two source slots are user supplied roles, never an image classification.  The
collect click accepts only the displayed immutable recognition snapshots; the original
review, plan, account binding and executor remain the authority for all writes.
"""
from __future__ import annotations

import copy
import secrets
from contextlib import contextmanager
from pathlib import Path

from workspace_executor import digest
from workspace_store import WorkspaceError, identifier
from workspace_tasks import IMAGE_EXTENSIONS, operations, workspace_review
from workspace_connector_photos import adjust_photos, editable_target


INTENT_KIND = "connector-collect-intent"


class WorkspaceConnector:
    def __init__(self, store, tasks, executor):
        self.store, self.tasks, self.executor = store, tasks, executor

    def assert_unclaimed_command(self, command_id):
        """Legacy and other intents cannot borrow a connector collect ID."""
        identifier(command_id, "操作 ID")
        if self.store.get_entity(INTENT_KIND, command_id):
            raise WorkspaceError("idempotency_conflict", "此操作 ID 已用于采纳并收藏，不能用于其他请求", 409)

    def _photo_idle(self, key):
        self.executor.assert_idle(key)
        organization = self.store.get_entity("organization", key)
        if organization and organization["data"].get("status") in {"queued", "running"}:
            raise WorkspaceError("organization_pending", "正在整理本批照片，请完成后再调整", 409)

    def photos(self, body, actor):
        with self.executor.lock:
            self._photo_idle(body["taskKey"])
            self.tasks._checked(body["taskKey"], body["expectedRevision"])
            self.tasks._call(body["taskKey"], body["expectedRevision"], actor, adjust_photos,
                             local_id=body["localId"], obverse_source_id=body["obverseSourceId"],
                             reverse_source_id=body["reverseSourceId"])
            return self.tasks.snapshot(body["taskKey"])

    def stage_photo(self, key, revision, local_id, name, content, actor):
        with self.executor.lock:
            self._photo_idle(key)
            current = self.tasks._checked(key, revision)
            editable_target(current["items"], local_id)
            if not isinstance(name, str) or Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
                raise WorkspaceError("invalid_sources", "请选择要放入照片槽的图片")
            # Local archive only: no automatic organizer and no evidence move
            # until the page submits both explicit source slots to /photos.
            return self.tasks.ingest(key, revision, name, content, actor)

    @contextmanager
    def _confirmation_scope(self, command_id):
        """Only a missing reservation proves this confirmation never wrote.

        Keep the lookup under the same executor lock as confirmation.  A failed
        read-only eligibility/capacity query can then be shown as recoverable,
        while any existing operation retains the normal recovery safeguards.
        Unexpected exceptions carry no new claim about remote state.
        """
        with self.executor.lock:
            try:
                yield
            except WorkspaceError as exc:
                if isinstance(command_id, str):
                    if self.store.get_entity("operation", command_id) is None:
                        exc.details["remoteWriteStarted"] = False
                    elif exc.details.get("remoteWriteStarted") is False:
                        exc.details.pop("remoteWriteStarted")
                raise

    def prepare(self, body, actor):
        with self.executor.lock:
            self.executor.assert_idle(body["taskKey"])
            current = self.tasks._checked(body["taskKey"], body["expectedRevision"])
            front, back = body["obverseSourceId"], body["reverseSourceId"]
            if not all(isinstance(value, str) and value for value in (front, back)) or front == back:
                raise WorkspaceError("incomplete_pair", "请分别提供两张不同来源的正面与反面照片")
            sources = {source["source_id"]: source for source in current["sources"]}
            if any(source_id not in sources or not sources[source_id]["mime_type"].startswith("image/")
                   for source_id in (front, back)):
                raise WorkspaceError("invalid_sources", "正反面必须是当前任务已归档的图片", 409)
            if sources[front]["sha256"] == sources[back]["sha256"]:
                raise WorkspaceError("incomplete_pair", "正反面不能使用同一份照片，请分别提供两面的照片")
            selected = {front, back}
            matching = [item for item in current["items"] if item.get("status") == "active"
                        and {entry["source_id"] for entry in item.get("evidence", [])} == selected]
            if len(matching) > 1:
                raise WorkspaceError("source_conflict", "同一对照片对应多条活动记录，请先核对原任务", 409)
            if not matching:
                active_items = [value for value in current["items"] if value.get("status") == "active"]
                if active_items:
                    # A user may replace a slot before identification.  Never
                    # turn that convenience into changing a business identity,
                    # moving another coin's evidence, or bypassing a remote call.
                    previous = active_items[0]
                    has_operations = any(entry["data"].get("taskKey") == body["taskKey"]
                                         for entry in self.store.list_entities("operation"))
                    if (len(active_items) != 1 or has_operations or previous.get("active_identification")
                            or previous.get("collection_projection")):
                        raise WorkspaceError("photo_replacement_requires_new_task",
                                             "原任务已有业务记录或多枚钱币，请用新整理任务放入替换照片", 409)
                    replacement = copy.deepcopy(previous)
                    old_evidence = {value["source_id"]: value for value in replacement.get("evidence", [])}
                    replacement["evidence"] = [old_evidence.get(source_id) or {
                        "evidence_id": "evidence-" + secrets.token_hex(8), "source_id": source_id,
                        "role": "unknown", "is_primary": True, "pair_confidence": None,
                        "rationale": "用户在正反面来源槽中替换的照片"} for source_id in (front, back)]
                    replacement["source_refs"] = [front, back]
                    replacement["version"] += 1
                    replacement["updated_at"] = operations.now_iso()
                    replacement["organization"] = {"pairing_state": "needs_review"}
                    replacement["attention_flags"] = list(dict.fromkeys(replacement.get("attention_flags", []) + ["pairing_needs_confirmation"]))
                    if replacement.get("review_projection"):
                        replacement["review_projection"]["stale"] = True
                    self.tasks._import_json(body["taskKey"], current["manifest"]["revision"], actor,
                                            operations.import_items, [replacement], mode="merge")
                    current = self.tasks.snapshot(body["taskKey"])
                else:
                    title = Path((sources[front].get("origin") or {}).get("original_name") or "我的钱币").stem[:200]
                    current = self.tasks.create_candidate(body["taskKey"], current["manifest"]["revision"],
                                                          [front, back], title or "我的钱币", actor)
                item = next(value for value in current["items"] if value.get("status") == "active"
                            and {entry["source_id"] for entry in value.get("evidence", [])} == selected)
            else:
                item = matching[0]
            roles = operations.identification_source_roles(item)
            if (item.get("organization") or {}).get("pairing_state") == "confirmed" and roles == {"obverse": front, "reverse": back}:
                return current
            if (item.get("collection_projection") or {}).get("collection_uri"):
                raise WorkspaceError("collection_conflict", "已收藏记录的照片方向不能直接重配，请先核对原档案", 409)
            # The existing operation expires old recognition, reviews and plans
            # when a user reverses the slots, retaining their immutable evidence.
            return self.tasks.pair(body["taskKey"], current["manifest"]["revision"], item["local_id"],
                                   "confirm_pair", [{"sourceId": front, "role": "obverse"},
                                                    {"sourceId": back, "role": "reverse"}], actor)

    def identification_plan(self, body):
        with self.executor.lock:
            self.executor.assert_idle(body["taskKey"])
            plan = self.executor.identification_plan(body["taskKey"], body["expectedRevision"], body.get("localIds"))
            # Read-only preflight stays outside the immutable source/account hash.
            # Execution rechecks it before reserving any remote write.
            try:
                eligibility = self.executor.query(["identify", "eligibility"])
            except WorkspaceError as exc:
                exc.details["remoteWriteStarted"] = False
                raise
            return {**plan, "eligibility": eligibility}

    def identify(self, body, actor):
        with self._confirmation_scope(body["commandId"]):
            self.assert_unclaimed_command(body["commandId"])
            return self.executor.identify(body, actor)

    def collect(self, body, actor):
        """Accept exactly what was shown, then execute the unchanged collection plan.

        Persist the public request before local review/plan changes.  This binds
        a command ID even if preparation is interrupted.  After an operation was
        reserved, every replay returns it without account queries or CLI writes.
        An interrupted intent with no operation fails closed instead of quietly
        building a new plan from a newer task revision.
        """
        with self._confirmation_scope(body["commandId"]):
            command_id = identifier(body["commandId"], "操作 ID")
            request_hash = digest({"kind": "connector.collect", "body": body})
            intent = self.store.get_entity(INTENT_KIND, command_id)
            existing = self.store.get_entity("operation", command_id)
            if intent:
                if intent["data"]["requestHash"] != request_hash:
                    raise WorkspaceError("idempotency_conflict", "同一操作 ID 不能用于不同收藏范围或快照", 409)
                if existing:
                    if existing["data"].get("requestHash") != digest({"kind": "collect", "body": intent["data"].get("executorRequest")}):
                        raise WorkspaceError("idempotency_conflict", "操作记录与原收藏确认不一致，请核验执行记录", 409)
                    return existing
                raise WorkspaceError("confirmation_interrupted", "此确认在远程执行前已停止；未自动重放，请重新查看任务后确认", 409,
                                     commandId=command_id, remoteWriteStarted=False)
            if existing:
                raise WorkspaceError("idempotency_conflict", "此操作 ID 已用于其他请求，不能改为采纳并收藏", 409)
            self.executor.assert_idle(body["taskKey"])
            current = self.tasks._checked(body["taskKey"], body["expectedRevision"])
            selected = body.get("items") if "items" in body else [{"localId": body["localId"], "snapshotId": body["snapshotId"]}]
            if (not isinstance(selected, list) or not 1 <= len(selected) <= 500
                    or any(not isinstance(value, dict) or set(value) != {"localId", "snapshotId"}
                           or not all(isinstance(value[k], str) and value[k] for k in ("localId", "snapshotId")) for value in selected)):
                raise WorkspaceError("invalid_selection", "请选择 1–500 枚钱币及已展示的识别快照")
            ids = [value["localId"] for value in selected]
            if len(set(ids)) != len(ids):
                raise WorkspaceError("invalid_selection", "收藏范围不能包含重复钱币")
            indexed = {value["local_id"]: value for value in current["items"]}
            snapshots = {}
            for value in selected:
                item = indexed.get(value["localId"])
                active = (item or {}).get("active_identification") or {}
                if (not item or item.get("status") != "active" or active.get("status") != "succeeded"
                        or not active.get("identify_uri") or active.get("snapshot_id") != value["snapshotId"]):
                    raise WorkspaceError("stale_snapshot", "识别结果已变化或尚未成功，请重新查看当前结果后再收藏", 409)
                if (item.get("collection_projection") or {}).get("collection_uri"):
                    raise WorkspaceError("already_collected", "所选钱币已有收藏关联，请查看原收藏结果", 409)
                if workspace_review.collect_reason(item):
                    raise WorkspaceError("review_conflict", workspace_review.collect_reason(item), 409)
                snapshots[value["localId"]] = (value["snapshotId"], active["identify_uri"])
            intent = self.store.save_entity(INTENT_KIND, command_id, {"requestHash": request_hash,
                "request": dict(body), "status": "preparing"}, 0, actor)
            try:
                self.tasks._call(body["taskKey"], current["manifest"]["revision"], actor, workspace_review.save,
                                 entries=[{"localId": value, "decision": "collect"} for value in ids],
                                 batch_id=command_id if len(ids) > 1 else None)
                reviewed = self.tasks.snapshot(body["taskKey"])
                plan = self.executor.collection_plan(body["taskKey"], reviewed["manifest"]["revision"], ids, actor)
                capacity = plan.get("capacity")
                # Only honor an explicit refusal.  Do not infer allowance,
                # remaining quota, price or a purchase requirement from fields
                # whose service semantics are not part of this contract.
                if isinstance(capacity, dict) and capacity.get("allowed") is False:
                    raise WorkspaceError("collection_not_allowed", "当前服务未允许新增收藏，请查看容量说明；未发起收藏写入", 409,
                                         capacity=capacity)
                scoped = plan["items"]
                if (len(scoped) != len(ids) or {entry["local_id"] for entry in scoped} != set(ids)
                        or any((entry.get("identification_snapshot_id"), entry.get("identify_uri"))
                               != snapshots.get(entry["local_id"]) for entry in scoped)):
                    raise WorkspaceError("stale_snapshot", "收藏计划没有精确对应已展示结果，请重新核对", 409)
                request = {"taskKey": body["taskKey"], "expectedRevision": plan["revision"],
                           "planId": plan["plan_id"], "planHash": plan["payload_sha256"], "commandId": command_id}
                intent = self.store.save_entity(INTENT_KIND, command_id,
                    {**intent["data"], "status": "planned", "executorRequest": request}, intent["revision"], actor)
                return self.executor.collect(request, actor)
            except Exception as exc:
                self.store.save_entity(INTENT_KIND, command_id, {**intent["data"], "status": "stopped",
                    "errorCode": getattr(exc, "code", "local_error")}, intent["revision"], actor)
                raise
