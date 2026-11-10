"""One local transaction for explicit in-page photo pairing and evidence moves."""
from __future__ import annotations

import copy

from workspace_store import WorkspaceError
from workspace_tasks import core, operations


EDITABLE_STATUSES = {"active", "source_incomplete"}
NON_COIN_KINDS = {"promotional_material", "document"}
PAIR_FLAGS = {"source_incomplete", "pairing_needs_confirmation", "remote_images_not_acquired"}


def editable_target(items, local_id):
    if not isinstance(local_id, str) or not local_id:
        raise WorkspaceError("invalid_selection", "请选择要调整照片的钱币")
    target = next((item for item in items if item["local_id"] == local_id), None)
    if not target:
        raise WorkspaceError("invalid_selection", "未找到当前钱币", 404)
    if (target.get("status") not in EDITABLE_STATUSES or target.get("active_identification") is not None
            or target.get("collection_projection") is not None
            or "identity_conflict" in target.get("attention_flags", [])
            or target.get("organization", {}).get("input_kind") in NON_COIN_KINDS):
        raise WorkspaceError("photo_target_locked", "这条记录不能调整币面，请查看已有识别、收藏或资料冲突", 409)
    return target


def source_owner_locked(item):
    # Historical business evidence stays protected even on an inactive record.
    if item.get("active_identification") is not None or item.get("collection_projection") is not None:
        return True
    if item.get("status") in {"superseded", "archived"}:
        return False
    return (item.get("status") not in EDITABLE_STATUSES
            or item.get("organization", {}).get("pairing_state") == "confirmed"
            or item.get("organization", {}).get("input_kind") in NON_COIN_KINDS
            or "identity_conflict" in item.get("attention_flags", []))


def _changed(item, timestamp):
    item["version"] += 1
    item["updated_at"] = timestamp
    if item.get("review_projection"):
        item["review_projection"]["stale"] = True


def _reset_suggestions(item):
    organization = item["organization"]
    for key in ("pairing_suggestions", "pair_confidence", "pairing_needs_confirmation", "pairing_decision_id"):
        organization.pop(key, None)


def adjust_photos(args):
    """Validate all owners first, then persist one revision and one pairing event.

    source_refs remain provenance, including released photos and document/crop
    ancestors. Only evidence conveys the current photo ownership. A partial
    donor keeps every unselected evidence entry; an empty donor is superseded.
    """
    root = core.resolve_root(args.root)
    with operations.task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = operations.open_task(args)
        target = editable_target(items_doc["items"], args.local_id)
        front, back = args.obverse_source_id, args.reverse_source_id
        if not all(isinstance(value, str) and value for value in (front, back)) or front == back:
            raise WorkspaceError("incomplete_pair", "请为正面和反面分别选择不同照片")
        sources = {source["source_id"]: source for source in sources_doc["sources"]}
        if any(value not in sources or not sources[value]["mime_type"].startswith("image/") for value in (front, back)):
            raise WorkspaceError("invalid_sources", "只能选择本批已保存的图片", 409)
        hashes = {sources[value]["sha256"] for value in (front, back)}
        if len(hashes) != 2:
            raise WorkspaceError("incomplete_pair", "正反面不能使用内容相同的照片")
        selected = {front, back}
        donors = []
        for owner in items_doc["items"]:
            if owner["local_id"] == target["local_id"]:
                continue
            moved = [entry for entry in owner.get("evidence", [])
                     if sources[entry["source_id"]]["sha256"] in hashes]
            if not moved:
                continue
            if source_owner_locked(owner):
                raise WorkspaceError("photo_source_locked", "所选照片已属于其他已确认、识别、收藏或受保护记录，不能移用", 409,
                                     localId=owner["local_id"])
            if owner.get("status") in EDITABLE_STATUSES:
                donors.append((owner, moved))

        roles = {"obverse": front, "reverse": back}
        if (not donors and target["status"] == "active"
                and target.get("organization", {}).get("pairing_state") == "confirmed"
                and target.get("organization", {}).get("input_kind", "coin") == "coin"
                and operations.identification_source_roles(target) == roles
                and {entry["source_id"] for entry in target["evidence"]} == selected
                and not set(target["attention_flags"]).intersection(PAIR_FLAGS)
                and operations.identification_eligible(target)):
            return {"revision": manifest["revision"], "unchanged": True}

        timestamp, pairing_id = operations.now_iso(), operations.new_id("pairing")
        affected = [target] + [owner for owner, _ in donors]
        before = [{"localId": item["local_id"], "version": item["version"], "status": item["status"],
                   "sourceIds": [entry["source_id"] for entry in item["evidence"]]} for item in affected]
        target_version = target["version"]
        previous_evidence = {entry["source_id"]: entry for entry in target["evidence"]}
        evidence = []
        for role, source_id in roles.items():
            entry = copy.deepcopy(previous_evidence.get(source_id)) or {"evidence_id": operations.new_id("evidence"), "source_id": source_id}
            entry.update(role=role, is_primary=True, pair_confidence=None, rationale="用户在添加页明确选择的币面照片")
            evidence.append(entry)
        target["evidence"] = evidence
        target["source_refs"] = list(dict.fromkeys([*target["source_refs"], front, back]))
        # Include source ancestry for newly selected extracted/cropped photos.
        for source_id in (front, back):
            seen = set()
            while source_id and source_id not in seen:
                seen.add(source_id)
                if source_id not in target["source_refs"]:
                    target["source_refs"].append(source_id)
                source_id = sources[source_id].get("parent_source_id")
        target["status"] = "active"
        _reset_suggestions(target)
        target["organization"].update(pairing_state="confirmed", input_kind="coin", pairing_decision_id=pairing_id,
            source_assignment=[{"source_id": value, "role": role} for role, value in roles.items()],
            pairing_rationale="用户在添加页明确指定正反面")
        target["attention_flags"] = [flag for flag in target["attention_flags"] if flag not in PAIR_FLAGS]
        _changed(target, timestamp)
        transfers = []
        for donor, moved in donors:
            moved_ids = {entry["source_id"] for entry in moved}
            donor["evidence"] = [entry for entry in donor["evidence"] if entry["source_id"] not in moved_ids]
            previous_state = donor["organization"].get("pairing_state")
            _reset_suggestions(donor)
            donor["organization"]["source_assignment"] = [
                {"source_id": entry["source_id"], "role": entry["role"] if entry["role"] in {"obverse", "reverse"} else "unknown"}
                for entry in donor["evidence"]]
            if donor["evidence"]:
                single = len(donor["evidence"]) == 1
                donor["status"] = "source_incomplete" if single else "active"
                donor["organization"]["pairing_state"] = "excluded" if previous_state == "excluded" else "single_side" if single else "needs_review"
                donor["attention_flags"] = list(dict.fromkeys(
                    [flag for flag in donor["attention_flags"] if flag not in PAIR_FLAGS]
                    + (["source_incomplete"] if single else ["pairing_needs_confirmation"])))
            else:
                donor["status"] = "superseded"
                donor["organization"]["pairing_state"] = "needs_review"
                donor["lineage"]["superseded_by"] = list(dict.fromkeys([*donor["lineage"]["superseded_by"], target["local_id"]]))
            target["lineage"]["derived_from"] = list(dict.fromkeys([*target["lineage"]["derived_from"], donor["local_id"]]))
            _changed(donor, timestamp)
            transfers.append({"fromLocalId": donor["local_id"], "sourceIds": sorted(moved_ids),
                              "remainingSourceIds": [entry["source_id"] for entry in donor["evidence"]], "status": donor["status"]})

        errors = core.validate_with_schema(task, "items.schema.json", items_doc, "调整照片")
        if errors:
            raise core.PackageError("调整照片不符合 Schema：" + "; ".join(errors[:5]))
        operations.validate_candidate_items(task, items_doc["items"], sources_doc)
        if not operations.identification_eligible(target):
            raise WorkspaceError("photo_target_locked", "该记录仍有未处理的身份或来源问题，未保存照片调整", 409)
        # Prepare both event schemas before the first append. Semantic/schema
        # conflicts therefore cannot leave a pairing log or a donor half moved.
        pairing_event = operations.prepare_log_line(task, "pairing/decisions.jsonl", {
            "schema_version": "heribase.pairing-decision.v1", "pairing_id": pairing_id,
            "local_id": target["local_id"], "action": "confirm_pair",
            "source_assignments": target["organization"]["source_assignment"],
            "actor": {"type": "user" if args.actor.startswith("user:") else "agent", "name": args.actor},
            "interaction": {"source": "connector_photos", "transfers": transfers},
            "based_on": {"item_version": target_version, "dataset_revision": manifest["dataset_revision"],
                         "dataset_fingerprint": manifest["dataset_fingerprint"]}, "created_at": timestamp,
        }, "pairing-decision.schema.json")
        audit_event = operations.prepare_log_line(task, "audit/events.jsonl", {
            "schema_version": "heribase.audit-event.v1", "event_id": operations.new_id("audit"),
            "event_type": "connector_photos_adjusted", "entity": {"type": "item", "id": target["local_id"]},
            "actor": {"type": "user" if args.actor.startswith("user:") else "agent", "name": args.actor},
            "correlation_id": pairing_id, "before": before,
            "after": [{"localId": item["local_id"], "version": item["version"], "status": item["status"],
                       "sourceIds": [entry["source_id"] for entry in item["evidence"]]} for item in affected],
            "details": {"transfers": transfers, "sourceAssignments": target["organization"]["source_assignment"]},
            "created_at": timestamp,
        }, "audit-event.schema.json")
        plan_path = task / "collection/plan.json"
        plan = core.read_json(plan_path) if plan_path.is_file() else None
        if plan and plan.get("status") not in {"consumed", "cancelled", "stale"}:
            plan["status"] = "stale"
        manifest["state"] = "identification_pending"
        operations.write_log_line(task, "pairing/decisions.jsonl", pairing_event)
        operations.write_log_line(task, "audit/events.jsonl", audit_event)
        revision = operations.commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=True, plan=plan)
        return {"revision": revision}
