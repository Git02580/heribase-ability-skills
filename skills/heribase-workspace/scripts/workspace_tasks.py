"""工作空间到已有任务包的受控适配器。

SQLite 保存工作台记录与通讯，任务证据/审核/收藏事实仍由任务包事务写入。
HTTP 请求不能指定脚本、shell、root 或任意文件路径；路径只由可信 task/source ID 派生。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import sys
import tempfile
import threading
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Tuple

from workspace_store import WorkspaceError, WorkspaceStore, safe_json
import workspace_review

TASK_SCRIPTS = Path(__file__).resolve().parents[2] / "heribase-task-package" / "scripts"
sys.path.insert(0, str(TASK_SCRIPTS))
import task_package as core
import task_operations as operations

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic", ".heif"}
FILE_EXTENSIONS = IMAGE_EXTENSIONS | {".csv", ".xlsx", ".pdf", ".txt"}
_LOCAL_LOCKS = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def serialized(function):
    """同一服务的事件读取和业务写入排队；外部进程仍由原任务包锁仲裁。"""
    @wraps(function)
    def invoke(self, task_key, *args, **kwargs):
        with _LOCAL_LOCKS_GUARD:
            lock = _LOCAL_LOCKS.setdefault((str(self.root), task_key), threading.RLock())
        with lock:
            return function(self, task_key, *args, **kwargs)
    return invoke


class WorkspaceTasks:
    def __init__(self, store: WorkspaceStore):
        self.store = store
        self.root = store.directory / "user-tasks"
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink():
            raise WorkspaceError("unsafe_path", "任务根目录不能是符号链接")
        # macOS /var → /private/var 由系统管理；两端使用同一规范化根再校验边界。
        self.root = self.root.resolve()
        self._create_lock = threading.Lock()
        self._external_lock = threading.Lock()
        self._signatures = {}
        self._observed = False

    def resolve(self, task_key: str) -> Path:
        try:
            return core.resolve_task(self.root, task_key)
        except (core.PackageError, TypeError) as exc:
            raise WorkspaceError("invalid_task", "任务标识无效或任务不存在", 404) from exc

    def keys(self) -> List[str]:
        return sorted([p.name for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()
                       and re.fullmatch(r"\d{8}-\d{4}-[a-z0-9][a-z0-9-]*", p.name)], reverse=True)

    def summaries(self) -> List[Dict[str, Any]]:
        result = []
        for key in self.keys():
            try:
                task = self.snapshot(key)
                result.append({**task["manifest"], "health": task["health"]})
            except WorkspaceError as exc:
                # 任务可能只是在媒体摘要或日志校验失败；此时只读、非符号链接的
                # manifest 可用于“任务管理”标题，但绝不据此放开资料或业务写入。
                try:
                    manifest_path = self.resolve(key) / "manifest.json"
                    if manifest_path.is_symlink():
                        raise OSError("manifest 不能是符号链接")
                    manifest = core.read_json(manifest_path)
                    display_name = manifest.get("display_name") if isinstance(manifest, dict) else None
                    updated_at = manifest.get("updated_at") if isinstance(manifest, dict) else None
                except (core.PackageError, ValueError, OSError, AttributeError):
                    display_name, updated_at = None, None
                health = exc.details.get("health") if isinstance(exc.details.get("health"), dict) else {"ok": False, "errors": [str(exc)]}
                result.append({"task_key": key, "display_name": display_name or key, "updated_at": updated_at,
                               "data_health": "data_inconsistent", "health": health})
        return result

    @serialized
    def snapshot(self, task_key: str) -> Dict[str, Any]:
        task = self.resolve(task_key)
        try:
            with operations.task_lock(self.root, task_key):
                health = core.validate_package_structure(task, task_key, check_integrity=True)
                if not health["ok"]:
                    # 损坏的 manifest/items 也可能是符号链接，不能为了“只读预览”
                    # 再跟随读取。列表保留任务键与异常状态，原件等待受控恢复。
                    raise WorkspaceError("data_inconsistent", "任务完整性检查失败", 409, health=health)
                manifest = core.read_json(task / "manifest.json")
                items = core.read_json(task / "data/items.json")["items"]
                # 展示结果从已校验的不可变响应派生，来源字段仍独立保留。
                for item in items:
                    active = item.get("active_identification") or {}
                    reference = active.get("raw_response_ref")
                    if reference and core.safe_relative_path(reference):
                        raw = core.read_json(task / reference)
                        item["recognitionResult"] = raw.get("result", raw)
                review_path = task / "review/decisions.jsonl"
                review_events = [json.loads(line) for line in review_path.read_text().splitlines()] if review_path.exists() else []
                workspace_review.decorate(items, review_events)
                sources = core.read_json(task / "inputs/sources.json")["sources"]
                plan_path = task / "collection/plan.json"
                return {"manifest": manifest, "items": items, "sources": sources, "health": health,
                        "organization": (self.store.get_entity("organization", task_key) or {}).get("data"),
                        "plan": core.read_json(plan_path) if plan_path.is_file() else None,
                        "batches": self._batch_history(task), "collectionHistory": self._collection_history(task)}
        except (core.PackageError, ValueError, OSError, KeyError) as exc:
            raise WorkspaceError("data_inconsistent", "任务数据无法安全读取：" + str(exc), 409) from exc

    def _batch_history(self, task):
        """只从已经完整性验证的任务日志派生历史，决定不另存第二份。"""
        groups = {}
        for stage, relative in (("pairing", "pairing/decisions.jsonl"), ("review", "review/decisions.jsonl")):
            path = task / relative
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                batch_id = event.get("interaction", {}).get("batch_action_id")
                if not batch_id:
                    continue
                group = groups.setdefault(batch_id, {"batchActionId": batch_id, "stage": stage,
                    "createdAt": event["created_at"], "actor": event["actor"]["name"], "items": []})
                group["items"].append({"localId": event["local_id"], "action": workspace_review.payload(event).get("decision") or event.get("decision") or event["action"], "status": "applied"})
        for batch_id, group in groups.items():
            context = self.store.get_entity("batch-context", batch_id)
            if context:
                applied = {i["localId"] for i in group["items"]}
                group["items"] = [{**item, "action": context["data"]["action"],
                    "status": "applied" if item["localId"] in applied else item["status"]}
                    for item in context["data"]["items"]]
            group["appliedCount"] = sum(i["status"] == "applied" for i in group["items"])
        return sorted(groups.values(), key=lambda g: g["createdAt"], reverse=True)

    def _collection_history(self, task):
        """从任务包不可变审计日志派生收藏编辑历史，绝不另存可被覆盖的副本。"""
        path = task / "audit/events.jsonl"
        if not path.is_file():
            return []
        history = []
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("event_type") not in {"collection_plan_created", "collection_operation_recorded"}:
                continue
            details = event.get("details") or {}
            operation_type = details.get("operation_type")
            if operation_type not in {"collection_update", "collection_cancel"}:
                continue
            # 只返回档案页展示需要的字段；远程快照原值仍在审计事件中校验保存。
            history.append({
                "eventId": event.get("event_id"), "eventType": event.get("event_type"),
                "createdAt": event.get("created_at"), "localId": (event.get("entity") or {}).get("id"),
                "operationType": operation_type, "changes": details.get("changes"),
                "items": details.get("items"), "remoteBefore": details.get("remote_before"),
                "rawResponseRef": details.get("raw_response_ref"), "status": (event.get("after") or {}).get("status"),
                "correlationId": event.get("correlation_id"),
            })
        return sorted(history, key=lambda event: event.get("createdAt") or "", reverse=True)

    def _checked(self, task_key: str, revision: int) -> Dict[str, Any]:
        if type(revision) is not int or revision < 1:
            raise WorkspaceError("invalid_revision", "必须提供当前任务版本")
        current = self.snapshot(task_key)
        if not current["health"]["ok"]:
            raise WorkspaceError("data_inconsistent", "任务完整性检查失败，先恢复或核验原始数据", 409)
        if current["manifest"]["revision"] != revision:
            raise WorkspaceError("revision_conflict", "任务已更新，请重新查看后再保存", 409,
                                 currentRevision=current["manifest"]["revision"])
        return current

    @serialized
    def _call(self, task_key: str, revision: int, actor: str, function, **options) -> Dict[str, Any]:
        try:
            result = function(argparse.Namespace(root=str(self.root), task_key=task_key, expected_revision=revision, actor=actor, **options))
        except core.PackageError as exc:
            code = "revision_conflict" if "revision 冲突" in str(exc) else "task_validation_failed"
            raise WorkspaceError(code, str(exc), 409) from exc
        self.store.emit("task.updated", "task", task_key, actor, {"revision": result.get("revision")})
        return result

    def create(self, name: str, timezone: str, actor: str) -> Dict[str, Any]:
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise WorkspaceError("invalid_name", "任务名称应为 1–100 字符")
        try:
            with self._create_lock:
                created = core.create_task(argparse.Namespace(root=str(self.root), display_name=name.strip(),
                    slug="collection", description="", timezone=timezone, created_by=actor, now=None))
        except (core.PackageError, TypeError) as exc:
            raise WorkspaceError("invalid_task", str(exc)) from exc
        self.store.emit("task.created", "task", created["task_key"], actor, {"displayName": name.strip()})
        return self.snapshot(created["task_key"])

    def ingest(self, task_key: str, revision: int, name: str, content: bytes, actor: str,
               *, supplement_local_id=None, supplement_side=None) -> Dict[str, Any]:
        if (not isinstance(name, str) or not name or len(name) > 200 or "/" in name or "\\" in name
                or any(ord(c) < 32 for c in name) or name in {".", ".."}):
            raise WorkspaceError("invalid_filename", "文件名不合法")
        extension = Path(name).suffix.lower()
        if extension not in FILE_EXTENSIONS or not content or len(content) > 20 * 1024 * 1024:
            raise WorkspaceError("invalid_upload", "支持图片、CSV、XLSX、PDF 或 TXT，单个文件不超过 20 MiB")
        self._checked(task_key, revision)
        kind = "local_image" if extension in IMAGE_EXTENSIONS else "spreadsheet" if extension in {".csv", ".xlsx"} else "document"
        with tempfile.TemporaryDirectory(prefix="upload-", dir=str(self.store.directory)) as temporary:
            path = Path(temporary) / name
            path.write_bytes(content)
            return self._call(task_key, revision, actor, operations.ingest_source,
                              file=str(path), kind=kind, source_id="source-" + secrets.token_hex(12),
                              origin_type="local", origin_url=None, original_path=None, browser_upload=True,
                              mime_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                              parent_source_id=None, sheet=None, row=None, column=None, cell=None, relationship_id=None,
                              supplement_local_id=supplement_local_id, supplement_side=supplement_side)

    def create_candidate(self, task_key: str, revision: int, source_ids: List[str], title: str, actor: str) -> Dict[str, Any]:
        current = self._checked(task_key, revision)
        if not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 10 or any(not isinstance(s, str) for s in source_ids) or len(set(source_ids)) != len(source_ids):
            raise WorkspaceError("invalid_sources", "请为候选选择不重复的图片来源")
        sources = {source["source_id"]: source for source in current["sources"]}
        used = {e["source_id"] for item in current["items"] if item["status"] in core.ACTIVE_ITEM_STATUSES for e in item["evidence"]}
        if any(source not in sources or source in used or not sources[source]["mime_type"].startswith("image/") for source in source_ids):
            raise WorkspaceError("source_conflict", "来源不是图片，或已经属于另一枚候选", 409)
        if not isinstance(title, str) or len(title) > 200:
            raise WorkspaceError("invalid_title", "来源名称不能超过 200 字符")
        number = max([int(item["item_key"].split("-")[-1]) for item in current["items"] if item["item_key"].startswith("local-")] or [0]) + 1
        item_key = "local-" + str(number).zfill(3)
        timestamp = operations.now_iso()
        item = {"local_id": task_key + ":" + item_key, "item_key": item_key, "legacy_ids": [], "version": 1,
                "status": "active", "lineage": {"derived_from": [], "superseded_by": []}, "source_refs": source_ids,
                "evidence": [{"evidence_id": "evidence-" + secrets.token_hex(8), "source_id": source,
                              "role": "unknown", "is_primary": True, "pair_confidence": None, "rationale": "用户选择的候选图片，方向待确认"} for source in source_ids],
                "organization": {"pairing_state": "needs_review"}, "field_claims": {"source": {"name": title}},
                "resolved_fields": {"name": {"value": title, "source": "user"}}, "active_identification": None,
                "review_projection": None, "collection_projection": None, "attention_flags": ["pairing_needs_confirmation"],
                "created_at": timestamp, "updated_at": timestamp}
        self._import_json(task_key, revision, actor, operations.import_items, [item], mode="merge")
        return self.snapshot(task_key)

    @serialized
    def merge_candidates(self, task_key: str, revision: int, target_local_id: str, source_local_id: str, actor: str) -> Dict[str, Any]:
        """把跨图建议对应的两条未确认候选合并，并保留来源候选的沿袭记录。"""
        current = self._checked(task_key, revision)
        if not isinstance(target_local_id, str) or not isinstance(source_local_id, str) or target_local_id == source_local_id:
            raise WorkspaceError("invalid_candidates", "请选择两条不同的候选记录")
        indexed = {item["local_id"]: item for item in current["items"]}
        target = indexed.get(target_local_id)
        source = indexed.get(source_local_id)
        if not target or not source:
            raise WorkspaceError("candidate_not_found", "候选记录不存在或已更新", 404)

        # 合并只面向还没有被确认或识别的活动候选；已识别/收藏的记录需要先单独核对，
        # 避免跨候选移动证据后悄悄改写既有服务身份。
        for item in (target, source):
            organization = item.get("organization") or {}
            if item.get("status") != "active" or organization.get("pairing_state") in {"confirmed", "excluded"}:
                raise WorkspaceError("candidate_not_mergeable", "只有尚未确认配对的活动候选可以合并", 409)
            if item.get("active_identification") or (item.get("collection_projection") or {}).get("collection_uri"):
                raise WorkspaceError("candidate_has_business_result", "已有识别或收藏关联的候选不能直接合并，请先核对该记录", 409)

        target_sources = {entry.get("source_id") for entry in target.get("evidence", [])}
        source_sources = {entry.get("source_id") for entry in source.get("evidence", [])}
        if not target_sources or not source_sources or target_sources.intersection(source_sources):
            raise WorkspaceError("candidate_source_conflict", "两条候选的图片来源为空或重复，无法安全合并", 409)

        # 合并必须来自任务中已保存的跨图建议，防止调用方借该接口把任意记录拼接起来。
        has_suggestion = any(
            set(suggestion.get("source_ids", [])).intersection(target_sources)
            and set(suggestion.get("source_ids", [])).intersection(source_sources)
            for item in (target, source)
            for suggestion in (item.get("organization") or {}).get("pairing_suggestions", [])
        )
        if not has_suggestion:
            raise WorkspaceError("suggestion_not_found", "当前两条候选没有相互关联的跨图建议，请刷新后重新选择", 409)

        # 从快照副本开始修改；统一导入两条 item，确保任一校验失败时不会只写入一半。
        target = json.loads(json.dumps(target))
        source = json.loads(json.dumps(source))
        moved_evidence = json.loads(json.dumps(source.get("evidence", [])))
        for evidence in moved_evidence:
            # 合并后要求用户重新确认正反面方向，防止继承旧候选中的猜测分配。
            evidence["role"] = "unknown"
            evidence["pair_confidence"] = None
        target["evidence"].extend(moved_evidence)
        target["source_refs"] = list(dict.fromkeys(target.get("source_refs", []) + source.get("source_refs", [])))
        target["version"] += 1
        target["updated_at"] = operations.now_iso()
        target["lineage"]["derived_from"] = list(dict.fromkeys(target["lineage"].get("derived_from", []) + [source_local_id]))
        target["organization"]["pairing_state"] = "needs_review"
        target["organization"].pop("pairing_decision_id", None)
        target["organization"].pop("source_assignment", None)
        target["organization"].pop("pair_confidence", None)
        target["organization"].pop("pairing_suggestions", None)
        target["attention_flags"] = list(dict.fromkeys(
            [flag for flag in target.get("attention_flags", []) if flag != "pairing_needs_confirmation"]
            + ["pairing_needs_confirmation"]
        ))
        if target.get("review_projection"):
            target["review_projection"]["stale"] = True

        source["status"] = "superseded"
        source["version"] += 1
        source["updated_at"] = target["updated_at"]
        source["lineage"]["superseded_by"] = list(dict.fromkeys(source["lineage"].get("superseded_by", []) + [target_local_id]))
        if source.get("review_projection"):
            source["review_projection"]["stale"] = True

        self._import_json(task_key, revision, actor, operations.import_items, [target, source], mode="merge")
        self.store.emit("task.updated", "task", task_key, actor, {
            "operation": "candidate_merge", "targetLocalId": target_local_id,
            "supersededLocalId": source_local_id, "movedSourceCount": len(moved_evidence),
        })
        return self.snapshot(task_key)

    def _import_json(self, task_key: str, revision: int, actor: str, function, value: Any, **options) -> Dict[str, Any]:
        if function is operations.import_items:
            # 快照里的审核展示投影不是任务包事实，不能回写进 items Schema。
            derived = {"recognitionResult", "reviewDetails", "reviewDetailsStale", "reviewHistory", "reviewIssues", "reviewIssuesResolved"}
            value = [{k: v for k, v in item.items() if k not in derived} for item in value]
        with tempfile.TemporaryDirectory(prefix="handoff-", dir=str(self.store.directory)) as temporary:
            path = Path(temporary) / "input.json"
            path.write_text(safe_json(value), encoding="utf-8")
            return self._call(task_key, revision, actor, function, file=str(path), **options)

    def pair(self, task_key: str, revision: int, local_id: str, action: str, assignments: List[Dict[str, str]], actor: str) -> Dict[str, Any]:
        current = self._checked(task_key, revision)
        if action not in {"confirm_pair", "need_photo", "exclude"}:
            raise WorkspaceError("invalid_action", "不支持的配对动作")
        if not isinstance(assignments, list) or not assignments or any(not isinstance(a, dict) or set(a) != {"sourceId", "role"} for a in assignments):
            raise WorkspaceError("invalid_assignment", "图片方向分配不完整")
        if action == "confirm_pair":
            roles = [a["role"] for a in assignments]
            ids = [a["sourceId"] for a in assignments]
            if roles.count("obverse") != 1 or roles.count("reverse") != 1 or len(set(ids)) != len(ids):
                raise WorkspaceError("incomplete_pair", "确认配对需要不同来源的完整正反面")
        package = {"schemaVersion": 1, "taskKey": task_key, "datasetFingerprint": current["manifest"]["dataset_fingerprint"],
                   "exportedAt": operations.now_iso(), "summary": {action: 1},
                   "decisions": [{"localId": local_id, "action": action, "sourceAssignments": assignments, "updatedAt": operations.now_iso()}]}
        self._import_json(task_key, revision, actor, operations.import_pairing, package)
        return self.snapshot(task_key)

    def review(self, task_key: str, revision: int, local_id: str, decision, actor: str, details=None) -> Dict[str, Any]:
        self._checked(task_key, revision)
        entry = {"localId": local_id}
        if decision is not None: entry["decision"] = decision
        if details is not None: entry["details"] = details
        self._call(task_key, revision, actor, workspace_review.save, entries=[entry], batch_id=None)
        return self.snapshot(task_key)

    def source(self, task_key: str, source_id: str) -> Tuple[bytes, str]:
        path, mime = self.source_path(task_key, source_id)
        return path.read_bytes(), mime

    def source_path(self, task_key: str, source_id: str) -> Tuple[Path, str]:
        task = self.resolve(task_key)
        snapshot = self.snapshot(task_key)
        if not snapshot["health"]["ok"]:
            raise WorkspaceError("data_inconsistent", "原始资料完整性检查失败", 409)
        source = next((s for s in snapshot["sources"] if s["source_id"] == source_id), None)
        if not source or not core.safe_relative_path(source["stored_path"]):
            raise WorkspaceError("source_not_found", "来源资料不存在", 404)
        path = task
        for component in Path(source["stored_path"]).parts:
            path = path / component
            if path.is_symlink():
                raise WorkspaceError("unsafe_path", "不允许读取符号链接", 403)
        path.resolve().relative_to(task.resolve())
        return path, source["mime_type"]

    def refresh_external_changes(self) -> None:
        # 同一来源的 Agent 可继续使用原任务包工具；观察提交后的 manifest/integrity
        # 变化并通知页面重取事实，不要求 Agent 同时更新第二套数据库快照。
        with self._external_lock:
            for key in self.keys():
                task = self.root / key
                try:
                    signature = tuple((task / file).stat().st_mtime_ns for file in ("manifest.json", "integrity.json"))
                except OSError:
                    continue
                previous = self._signatures.get(key)
                self._signatures[key] = signature
                if (previous is not None and previous != signature) or (previous is None and self._observed):
                    self.store.emit("task.updated", "task", key, "system:package", {"external": True})
            self._observed = True
