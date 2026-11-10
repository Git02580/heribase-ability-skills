#!/usr/bin/env python3
"""HeriBase 任务包的高层、受控事务命令。

与 task_package.py 的只读校验/骨架能力不同，本脚本负责容易出错的业务写入：
来源归档、规范化 item 导入、识别事实、审核决定、收藏计划和收藏结果。
每个命令都在短租约锁内完成预校验、追加日志、原子快照与完整性更新。
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import task_package as core


SOURCE_DESTINATIONS = {
    "local_image": "inputs/originals/images",
    "spreadsheet": "inputs/originals/spreadsheets",
    "document": "inputs/originals/documents",
    "remote_image": "inputs/remote-images",
    "extracted_image": "inputs/extracted/spreadsheet-images",
}
UI_DECISIONS = {"collect", "need-photo", "exclude"}
INTERNAL_DECISION_MAP = {"collect": "collect", "need-photo": "need_photo", "exclude": "exclude"}
SERVICE_FIELDS = {
    "identify_uri": ("identifyUri", "uri", "identify_uri"),
    "user_uniq_uri": ("userUniqUri", "user_uniq_uri"),
    "collection_uri": ("collectionUri", "collection_uri"),
}
REMOVED_IDENTIFICATION_FIELDS = ("currency_number", "uniq_uri")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def load_input_json(path: str) -> Any:
    return core.read_json(Path(path).expanduser().resolve())


def require_safe_object(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise core.PackageError(f"{label} 必须是 JSON object")
    sensitive = core.sensitive_paths(value)
    if sensitive:
        raise core.PackageError(f"{label} 含敏感字段，拒绝处理：{', '.join(sensitive)}")
    return value


def require_safe_cli(event: Dict[str, Any]) -> None:
    cli = event.get("cli")
    if not isinstance(cli, dict):
        return
    arguments = cli.get("args", [])
    for argument in arguments if isinstance(arguments, list) else []:
        text = str(argument)
        if re.search(r"(?i)(?:bearer\s+|authorization|access[_-]?token|refresh[_-]?token|password|private[_-]?key|api[_-]?key)", text):
            raise core.PackageError("CLI 事件参数疑似包含凭据，拒绝写入日志")


def service_value(raw: Dict[str, Any], normalized_name: str) -> Optional[str]:
    """只映射服务响应的已知字段名；不搜索相似字段，不从标题等内容推测。"""

    # CLI 的 sync 模式可能直出业务字段，也可能返回 {status, result:{...}} 完成信封。
    # 仅解包这一固定字段，不递归模糊搜索，避免把无关嵌套值误当成服务身份。
    candidates = [raw]
    if isinstance(raw.get("result"), dict):
        candidates.append(raw["result"])
    for candidate in candidates:
        for key in SERVICE_FIELDS[normalized_name]:
            if key not in candidate:
                continue
            value = candidate[key]
            if value is None or value == "":
                return None
            if not isinstance(value, str):
                raise core.PackageError(f"服务字段 {key} 必须是 string 或 null")
            return value
    return None


def read_exact_json(path: str) -> Tuple[bytes, Dict[str, Any]]:
    source = Path(path).expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise core.PackageError(f"raw JSON 文件不存在或不是普通文件：{source}")
    raw_bytes = source.read_bytes()
    try:
        value = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise core.PackageError("CLI stdout 必须是单一 UTF-8 JSON object") from exc
    return raw_bytes, require_safe_object(value, "CLI raw 响应")


def save_immutable_bytes(path: Path, content: bytes) -> None:
    """以 O_EXCL 创建不可变事实；同名文件绝不能覆盖。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise core.PackageError(f"不可变文件已存在，拒绝覆盖：{path.name}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # 创建过程中失败的零散文件没有成为任务事实，立即清理这一精确目标。
        with contextlib.suppress(OSError):
            path.unlink()
        raise


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextlib.contextmanager
def task_lock(root: Path, task_key: str, lease_seconds: int = 120) -> Iterable[None]:
    """用原子建文件实现短租约锁；只回收已过期且 owner 进程不存在的锁。"""

    lock_dir = root / "_runtime" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{task_key}.lock"
    owner = {"pid": os.getpid(), "created_at": now_iso(), "lease_seconds": lease_seconds}
    for _ in range(2):
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(owner, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            break
        except FileExistsError:
            try:
                existing = core.read_json(lock_path)
                created = datetime.fromisoformat(existing["created_at"].replace("Z", "+00:00"))
                age = time.time() - created.timestamp()
                stale = age > int(existing.get("lease_seconds", lease_seconds)) and not process_alive(int(existing.get("pid", -1)))
            except Exception:
                stale = False
            if not stale:
                raise core.PackageError(f"任务正被另一事务占用：{task_key}")
            lock_path.unlink()
    else:
        raise core.PackageError(f"无法取得任务锁：{task_key}")
    try:
        yield
    finally:
        # 仅删除仍属于本进程的锁，避免误删后来者的锁。
        try:
            current = core.read_json(lock_path)
            if current.get("pid") == os.getpid():
                lock_path.unlink()
        except Exception:
            pass


def open_task(args: argparse.Namespace) -> Tuple[Path, Path, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    root = core.resolve_root(args.root)
    task = core.resolve_task(root, args.task_key)
    result = core.validate_package_structure(task, args.task_key, check_integrity=True)
    if not result["ok"]:
        raise core.PackageError("任务当前不一致，拒绝写入：" + "; ".join(result["errors"][:5]))
    manifest = core.read_json(task / "manifest.json")
    expected = getattr(args, "expected_revision", None)
    if expected is not None and manifest.get("revision") != expected:
        raise core.PackageError(
            f"revision 冲突：期望 {expected}，当前 {manifest.get('revision')}"
        )
    return root, task, manifest, core.read_json(task / "inputs/sources.json"), core.read_json(task / "data/items.json")


def next_log_event(task: Path, relative: str, event: Dict[str, Any]) -> Dict[str, Any]:
    path = task / relative
    existing, errors = core.parse_jsonl(path)
    if errors:
        raise core.PackageError(f"日志不可追加：{relative}：{'; '.join(errors)}")
    value = copy.deepcopy(event)
    value["task_key"] = task.name
    value["sequence"] = len(existing) + 1
    value["previous_event_sha256"] = existing[-1]["event_sha256"] if existing else None
    value["event_sha256"] = core.event_digest(value)
    return value


def prepare_log_line(task: Path, relative: str, event: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    value = next_log_event(task, relative, event)
    errors = core.validate_with_schema(task, schema_name, value, relative)
    if errors:
        raise core.PackageError("事件不符合 Schema：" + "; ".join(errors[:5]))
    return value


def write_log_line(task: Path, relative: str, value: Dict[str, Any]) -> Dict[str, Any]:
    path = task / relative
    with path.open("ab") as handle:
        handle.write(core.canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return value


def append_log_line(task: Path, relative: str, event: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    return write_log_line(task, relative, prepare_log_line(task, relative, event, schema_name))


def append_audit(
    task: Path,
    event_type: str,
    entity_type: str,
    entity_id: Optional[str],
    actor_type: str,
    actor_name: str,
    before: Any,
    after: Any,
    details: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    event = {
        "schema_version": "heribase.audit-event.v1",
        "event_id": new_id("audit"),
        "event_type": event_type,
        "entity": {"type": entity_type, "id": entity_id},
        "actor": {"type": actor_type, "name": actor_name},
        "correlation_id": correlation_id,
        "before": before,
        "after": after,
        "details": details or {},
        "created_at": now_iso(),
    }
    return append_log_line(task, "audit/events.jsonl", event, "audit-event.schema.json")


def recompute_statistics(items: List[Dict[str, Any]], sources: List[Dict[str, Any]]) -> Dict[str, int]:
    decisions = [(item.get("review_projection") or {}).get("decision") for item in items]
    return {
        "sources": len(sources),
        "items": len(items),
        "identified": sum(1 for item in items if (item.get("active_identification") or {}).get("status") == "succeeded"),
        "reviewed": sum(1 for item in items if (item.get("review_projection") or {}).get("decision") in {"collect", "need_photo", "exclude"} and not (item.get("review_projection") or {}).get("stale")),
        "collect": decisions.count("collect"),
        "need_photo": decisions.count("need_photo"),
        "excluded": decisions.count("exclude"),
        "collected": sum(1 for item in items if (item.get("collection_projection") or {}).get("collection_uri")),
        "exceptions": sum(1 for item in items if item.get("status") in {"source_incomplete", "identity_conflict"} or bool(item.get("attention_flags"))),
    }


def commit_snapshots(
    task: Path,
    manifest: Dict[str, Any],
    sources_doc: Dict[str, Any],
    items_doc: Dict[str, Any],
    *,
    dataset_changed: bool,
    plan: Optional[Dict[str, Any]] = None,
) -> int:
    timestamp = now_iso()
    revision = int(manifest["revision"]) + 1
    manifest["revision"] = revision
    if dataset_changed:
        manifest["dataset_revision"] = int(manifest["dataset_revision"]) + 1
    manifest["updated_at"] = timestamp
    sources_doc["revision"] = revision
    sources_doc["updated_at"] = timestamp
    items_doc["revision"] = revision
    items_doc["updated_at"] = timestamp
    manifest["dataset_fingerprint"] = core.dataset_fingerprint(
        sources_doc["sources"], items_doc["items"]
    )
    manifest["statistics"] = recompute_statistics(items_doc["items"], sources_doc["sources"])

    # 日志已先 fsync；随后三个快照逐个原子替换。任一点崩溃都可由 revision 差异恢复。
    core.write_json_atomic(task / "inputs/sources.json", sources_doc)
    core.write_json_atomic(task / "data/items.json", items_doc)
    if plan is not None:
        core.write_json_atomic(task / "collection/plan.json", plan)
    core.write_json_atomic(task / "manifest.json", manifest)
    core.write_json_atomic(task / "integrity.json", core.build_integrity(task, manifest))
    return revision


def find_item(items_doc: Dict[str, Any], local_id: str) -> Dict[str, Any]:
    for item in items_doc.get("items", []):
        if item.get("local_id") == local_id:
            return item
    raise core.PackageError(f"任务中不存在 local_id：{local_id}")


def ensure_item_id(task_key: str, item: Dict[str, Any]) -> None:
    item_key = item.get("item_key")
    if not isinstance(item_key, str) or not re.fullmatch(r"(?:local-[0-9]+|table-[0-9]+)", item_key):
        raise core.PackageError("item_key 必须是 local-N 或 table-N")
    expected = f"{task_key}:{item_key}"
    if item.get("local_id") not in {None, expected}:
        raise core.PackageError(f"local_id 必须是 {expected}")
    item["local_id"] = expected


def validate_candidate_items(
    task: Path,
    items: List[Dict[str, Any]],
    sources_doc: Dict[str, Any],
) -> None:
    """在落盘前检查跨文档约束，避免“写完才发现任务失效”。"""

    source_ids = {source.get("source_id") for source in sources_doc.get("sources", [])}
    recognition_events, _ = core.parse_jsonl(task / "recognition" / "attempts.jsonl")
    collection_events, _ = core.parse_jsonl(task / "collection" / "attempts.jsonl")
    recognition_attempts = {event.get("attempt_id") for event in recognition_events}
    collection_operations = {event.get("operation_id") for event in collection_events}
    active_entities: Dict[str, str] = {}
    for item in items:
        local_id = item["local_id"]
        for source_id in item.get("source_refs", []):
            if source_id not in source_ids:
                raise core.PackageError(f"item {local_id} 引用了不存在的 source：{source_id}")
        for evidence in item.get("evidence", []):
            if evidence.get("source_id") not in source_ids:
                raise core.PackageError(f"item {local_id} 的 evidence source 不存在")
        # 配对建议允许指向同一任务中另一条候选的图片；至少一端必须属于当前 item，
        # 并且两端都必须是已归档来源，避免工作台展示悬空或跨任务的建议。
        item_source_ids = {evidence.get("source_id") for evidence in item.get("evidence", [])}
        for suggestion in (item.get("organization") or {}).get("pairing_suggestions", []):
            suggested_sources = set(suggestion.get("source_ids", []))
            if not suggested_sources.issubset(source_ids):
                raise core.PackageError(f"item {local_id} 的配对建议引用了不存在的图片来源")
            if not suggested_sources.intersection(item_source_ids):
                raise core.PackageError(f"item {local_id} 的配对建议不包含本条目的图片来源")
        identification = item.get("active_identification")
        if not isinstance(identification, dict):
            collection = item.get("collection_projection")
            if isinstance(collection, dict) and collection.get("operation_id") not in collection_operations:
                raise core.PackageError(f"item {local_id} 的 collection_projection 没有对应事件")
            continue
        if identification.get("attempt_id") not in recognition_attempts:
            raise core.PackageError(f"item {local_id} 的 active_identification 没有对应识别事件")
        raw_ref = identification.get("raw_response_ref")
        if not isinstance(raw_ref, str) or not core.safe_relative_path(raw_ref) or not (task / raw_ref).is_file():
            raise core.PackageError(f"item {local_id} 的识别 raw_response_ref 不存在")
        if core.sha256_file(task / raw_ref) != identification.get("raw_response_sha256"):
            raise core.PackageError(f"item {local_id} 的识别 raw SHA-256 不匹配")
        user_uri = identification.get("user_uniq_uri")
        if item.get("status") in core.ACTIVE_ITEM_STATUSES and isinstance(user_uri, str) and user_uri:
            previous = active_entities.get(user_uri)
            if previous:
                raise core.PackageError(f"同一任务存在 user_uniq_uri 冲突：{previous}、{local_id}")
            active_entities[user_uri] = local_id
        collection = item.get("collection_projection")
        if isinstance(collection, dict) and collection.get("operation_id") not in collection_operations:
            raise core.PackageError(f"item {local_id} 的 collection_projection 没有对应事件")


def supplement_target(items_doc, sources_doc, local_id, side, source):
    """Validate a user-selected missing side before archiving any bytes."""
    if side not in {"obverse", "reverse"} or not isinstance(local_id, str):
        raise core.PackageError("请选择要补充的正面或反面")
    item = find_item(items_doc, local_id)
    if (item.get("status") not in {"active", "source_incomplete"}
            or item.get("active_identification") or item.get("collection_projection")
            or "identity_conflict" in item.get("attention_flags", [])
            or item.get("organization", {}).get("input_kind") in {"promotional_material", "document"}):
        raise core.PackageError("这条记录不能补图，请查看当前照片和识别结果")
    roles = identification_source_roles(item)
    opposite = "reverse" if side == "obverse" else "obverse"
    if set(roles) != {opposite}:
        raise core.PackageError("照片已更新，请刷新后查看缺少哪一面")
    if source["kind"] != "local_image" or not source["mime_type"].startswith("image/"):
        raise core.PackageError("请补充一张钱币照片")
    used = {e["source_id"] for value in items_doc["items"] if value.get("status") in core.ACTIVE_ITEM_STATUSES
            for e in value.get("evidence", [])}
    if any(value["sha256"] == source["sha256"] and value["source_id"] in used for value in sources_doc["sources"]):
        raise core.PackageError("这张照片已在使用，请选择这枚钱币缺少的另一面")
    return item, roles


def ingest_source(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        source_file = Path(args.file).expanduser().resolve()
        if source_file.is_symlink() or not source_file.is_file():
            raise core.PackageError("来源必须是现有普通文件，不能是符号链接")
        digest = core.sha256_file(source_file)
        source_id = args.source_id or f"source-{digest[:16]}"
        if any(source.get("source_id") == source_id for source in sources_doc["sources"]):
            raise core.PackageError(f"source_id 已存在：{source_id}")
        existing_source_ids = {source.get("source_id") for source in sources_doc["sources"]}
        if args.parent_source_id and args.parent_source_id not in existing_source_ids:
            raise core.PackageError(f"parent_source_id 不存在：{args.parent_source_id}")
        if args.origin_type == "remote" and not (
            isinstance(args.origin_url, str)
            and re.match(r"^https?://", args.origin_url, flags=re.IGNORECASE)
        ):
            raise core.PackageError("remote 来源必须保留 http/https origin-url")
        if args.kind == "extracted_image" and not args.parent_source_id:
            raise core.PackageError("extracted_image 必须关联 parent_source_id")
        extension = source_file.suffix.lower()
        destination_relative = f"{SOURCE_DESTINATIONS[args.kind]}/{source_id}{extension}"
        destination = task / destination_relative
        locator = None
        if any(value is not None for value in (args.sheet, args.row, args.column, args.cell, args.relationship_id)):
            locator = {
                "sheet": args.sheet,
                "row": args.row,
                "column": args.column,
                "cell": args.cell,
                "relationship_id": args.relationship_id,
            }
        timestamp = now_iso()
        source = {
            "source_id": source_id,
            "kind": args.kind,
            "origin": {
                "type": args.origin_type,
                "original_name": source_file.name,
                # 浏览器只提供文件名和字节，不知道用户原始绝对路径。临时接收路径
                # 不应冒充来源路径；原件仍由 stored_path + SHA-256 完整追溯。
                "original_path": None if getattr(args, "browser_upload", False) else str(source_file) if args.origin_type == "local" else args.original_path,
                "url": args.origin_url,
            },
            "stored_path": destination_relative,
            "mime_type": args.mime_type or mimetypes.guess_type(source_file.name)[0] or "application/octet-stream",
            "byte_size": source_file.stat().st_size,
            "sha256": digest,
            "acquired_at": timestamp,
            "parent_source_id": args.parent_source_id,
            "locator": locator,
            "integrity_status": "verified",
        }
        supplement = None
        if getattr(args, "supplement_local_id", None) is not None or getattr(args, "supplement_side", None) is not None:
            supplement = supplement_target(items_doc, sources_doc, args.supplement_local_id, args.supplement_side, source)
        candidate_sources = {**sources_doc, "sources": [*sources_doc["sources"], source]}
        schema_errors = core.validate_with_schema(
            task, "sources.schema.json", candidate_sources, "新增 source"
        )
        if schema_errors:
            raise core.PackageError("source 不符合 Schema：" + "; ".join(schema_errors[:5]))
        save_immutable_bytes(destination, source_file.read_bytes())
        sources_doc["sources"].append(source)
        append_audit(
            task,
            "source_ingested",
            "source",
            source_id,
            "agent",
            args.actor,
            None,
            {"stored_path": destination_relative, "sha256": digest},
            {"kind": args.kind, "origin_type": args.origin_type},
        )
        plan = None
        if supplement:
            item, roles = supplement
            roles[args.supplement_side] = source_id
            assignments = [{"source_id": roles[role], "role": role} for role in ("obverse", "reverse")]
            pairing_id = new_id("pairing")
            append_log_line(task, "pairing/decisions.jsonl", {
                "schema_version": "heribase.pairing-decision.v1", "pairing_id": pairing_id,
                "local_id": item["local_id"], "action": "confirm_pair", "source_assignments": assignments,
                "actor": {"type": "user", "name": args.actor},
                "interaction": {"source": "photo_supplement", "side": args.supplement_side},
                "based_on": {"item_version": item["version"], "dataset_revision": manifest["dataset_revision"],
                             "dataset_fingerprint": manifest["dataset_fingerprint"]}, "created_at": timestamp,
            }, "pairing-decision.schema.json")
            item["evidence"].append({"evidence_id": new_id("evidence"), "source_id": source_id,
                                     "role": args.supplement_side, "is_primary": True, "pair_confidence": None,
                                     "rationale": "用户为这枚钱币补充的照片"})
            item["source_refs"].append(source_id)
            item["organization"].update({"pairing_state": "confirmed", "pairing_decision_id": pairing_id,
                                         "source_assignment": assignments})
            item["attention_flags"] = [flag for flag in item.get("attention_flags", [])
                                       if flag not in {"source_incomplete", "pairing_needs_confirmation"}]
            item["status"] = "active"
            item["version"] += 1
            item["updated_at"] = timestamp
            if item.get("review_projection"):
                item["review_projection"]["stale"] = True
            manifest["state"] = "identification_pending"
            plan_path = task / "collection/plan.json"
            plan = core.read_json(plan_path) if plan_path.is_file() else None
            if plan and plan.get("status") not in {"consumed", "cancelled", "stale"}:
                plan["status"] = "stale"
            append_audit(task, "photo_supplemented", "item", item["local_id"], "user", args.actor, None,
                         {"source_id": source_id, "side": args.supplement_side}, {"pairing_id": pairing_id})
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=True, plan=plan)
        return {"ok": True, "task_key": args.task_key, "revision": revision, "dataset_revision": manifest["dataset_revision"], "source": source}


def column_cell_name(column_number: int, row_number: int) -> str:
    """将 CSV 表头位置转为熟悉的表格单元格表示，便于人工追溯。"""

    letters = ""
    number = column_number
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row_number}"


def remote_image_bytes(url: str) -> Tuple[bytes, str]:
    """获取用户表格声明的图片，并拒绝被错误页伪装的非图片内容。"""

    request = Request(url, headers={"User-Agent": "HeriBase-Task-Package/1.0"})
    try:
        with urlopen(request, timeout=25) as response:  # nosec B310: URL 来自已归档的用户表格。
            content_type = response.headers.get_content_type()
            declared_length = response.headers.get("Content-Length")
            maximum_size = 20 * 1024 * 1024
            if declared_length and int(declared_length) > maximum_size:
                raise core.PackageError("远程图片超过 20 MiB 限制")
            content = response.read(maximum_size + 1)
    except (OSError, URLError, ValueError) as error:
        raise core.PackageError(f"远程图片获取失败：{error}") from error
    if len(content) > 20 * 1024 * 1024:
        raise core.PackageError("远程图片超过 20 MiB 限制")
    # 不只信任 Content-Type：CDN 错误页常返回 text/html 或伪造的成功状态。
    signatures = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"RIFF")
    if not content.startswith(signatures):
        raise core.PackageError("远程 URL 未返回可归档的图片内容")
    return content, content_type if content_type.startswith("image/") else "application/octet-stream"


def ingest_table_images(args: argparse.Namespace) -> Dict[str, Any]:
    """将 CSV 各行的正反面 URL 归档为来源，并原子关联回 table-* 候选。

    这是一个单事务批量操作：先完整下载每行图片，随后才写入 sources/items，避免把
    已下载但未关联的来源伪装成已完成。失败则保留在候选的 acquisition 记录中，供配对
    审核台清楚展示，绝不静默省略。
    """

    csv_path = Path(args.csv_file).expanduser().resolve()
    if csv_path.is_symlink() or not csv_path.is_file():
        raise core.PackageError("表格文件必须是现有普通文件，不能是符号链接")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if args.front_column not in headers or args.back_column not in headers:
            raise core.PackageError("表格缺少指定的正面或反面图片列")
        rows = {row_number: row for row_number, row in enumerate(reader, start=2)}
    header_positions = {name: index + 1 for index, name in enumerate(headers)}

    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key, lease_seconds=600):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        source_ids = {source["source_id"] for source in sources_doc["sources"]}
        if args.parent_source_id not in source_ids:
            raise core.PackageError("parent-source-id 不存在")

        new_sources: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []
        successes: Dict[str, List[Tuple[str, str, int]]] = {}
        table_items = [item for item in items_doc["items"] if item.get("item_key", "").startswith("table-")]
        for item in table_items:
            source_rows = (item.get("organization") or {}).get("source_rows", [])
            if not isinstance(source_rows, list) or not source_rows:
                failures.append({"local_id": item["local_id"], "reason": "缺少表格行定位", "at": now_iso()})
                continue
            for row_number in source_rows:
                row = rows.get(row_number)
                if row is None:
                    failures.append({"local_id": item["local_id"], "row": row_number, "reason": "表格中找不到该行", "at": now_iso()})
                    continue
                for role, column_name in (("obverse", args.front_column), ("reverse", args.back_column)):
                    url = (row.get(column_name) or "").strip()
                    entry_base = {"local_id": item["local_id"], "row": row_number, "role": role, "url": url}
                    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
                        failures.append({**entry_base, "reason": "缺少有效 http/https 图片 URL", "at": now_iso()})
                        continue
                    try:
                        content, mime_type = remote_image_bytes(url)
                    except core.PackageError as error:
                        failures.append({**entry_base, "reason": str(error), "at": now_iso()})
                        continue
                    suffix = Path(urlsplit(url).path).suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
                        suffix = ".jpg" if content.startswith(b"\xff\xd8\xff") else ".img"
                    # 以 item、行与面别派生 ID：重复行即使图片字节相同，也保留各自的来源位置。
                    source_id = f"source-table-{row_number}-{role}-{hashlib.sha256((item['local_id'] + url).encode('utf-8')).hexdigest()[:12]}"
                    if source_id in source_ids:
                        raise core.PackageError(f"表格图片来源已存在：{source_id}；拒绝重复导入")
                    stored_path = f"inputs/remote-images/{source_id}{suffix}"
                    save_immutable_bytes(task / stored_path, content)
                    source_ids.add(source_id)
                    source = {
                        "source_id": source_id,
                        "kind": "remote_image",
                        "origin": {"type": "remote", "original_name": Path(urlsplit(url).path).name or None, "original_path": None, "url": url},
                        "stored_path": stored_path,
                        "mime_type": mime_type,
                        "byte_size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "acquired_at": now_iso(),
                        "parent_source_id": args.parent_source_id,
                        "locator": {"sheet": None, "row": row_number, "column": header_positions[column_name], "cell": column_cell_name(header_positions[column_name], row_number), "relationship_id": None},
                        "integrity_status": "verified",
                    }
                    new_sources.append(source)
                    successes.setdefault(item["local_id"], []).append((source_id, role, row_number))

        candidate_sources_doc = {**sources_doc, "sources": [*sources_doc["sources"], *new_sources]}
        errors = core.validate_with_schema(task, "sources.schema.json", candidate_sources_doc, "表格远程图片来源")
        if errors:
            raise core.PackageError("表格远程图片来源不符合 Schema：" + "; ".join(errors[:5]))
        failures_by_item: Dict[str, List[Dict[str, Any]]] = {}
        for failure in failures:
            failures_by_item.setdefault(failure["local_id"], []).append(failure)
        for item in table_items:
            organization = item.setdefault("organization", {})
            item_successes = successes.get(item["local_id"], [])
            item_failures = failures_by_item.get(item["local_id"], [])
            primary_row = min(organization.get("source_rows") or [0])
            primary = [(source_id, role) for source_id, role, row in item_successes if row == primary_row]
            item["source_refs"] = list(dict.fromkeys([*item.get("source_refs", []), *(source_id for source_id, _, _ in item_successes)]))
            item["evidence"] = [value for value in item.get("evidence", []) if value.get("source_id") not in {source_id for source_id, _, _ in item_successes}]
            for source_id, role in primary:
                item["evidence"].append({"evidence_id": f"evidence-{source_id}", "source_id": source_id, "role": role, "is_primary": True, "pair_confidence": 0.98, "rationale": "同一表格行提供的已归档正反面 URL"})
            item.setdefault("field_claims", {})["table_image_urls"] = [{"row": row, "front_image_url": rows[row].get(args.front_column), "back_image_url": rows[row].get(args.back_column)} for row in organization.get("source_rows", []) if row in rows]
            organization["table_image_acquisition"] = {"succeeded_source_ids": [source_id for source_id, _, _ in item_successes], "failures": item_failures, "updated_at": now_iso()}
            completed_pair = {role for _, role in primary} == {"obverse", "reverse"} and not item_failures
            if completed_pair:
                item["status"] = "active"
                organization.update({"pairing": "table_row_complete", "pair_confidence": 0.98, "pairing_rationale": "同一表格行的正反面图片已成功归档", "pairing_needs_confirmation": False})
                # 获取完成后的快照必须反映当前证据，不能继续展示导入前遗留的“缺图”告警。
                # 保留无关风险标记（如估值或重复项），只移除已被本次下载闭合的状态标记。
                item["attention_flags"] = [
                    flag for flag in item.get("attention_flags", [])
                    if flag not in {"pairing_needs_confirmation", "source_incomplete", "remote_images_not_acquired"}
                ]
            else:
                item["status"] = "source_incomplete"
                organization.update({"pairing": "source_incomplete", "pair_confidence": "low", "pairing_needs_confirmation": True})
                item["attention_flags"] = list(dict.fromkeys([*item.get("attention_flags", []), "pairing_needs_confirmation", "source_incomplete"]))
            item["version"] += 1
            item["updated_at"] = now_iso()

        candidate_items_doc = {**items_doc, "items": items_doc["items"]}
        errors = core.validate_with_schema(task, "items.schema.json", candidate_items_doc, "表格图片关联后的 items")
        if errors:
            raise core.PackageError("表格图片关联后的 items 不符合 Schema：" + "; ".join(errors[:5]))
        validate_candidate_items(task, items_doc["items"], candidate_sources_doc)
        sources_doc["sources"] = candidate_sources_doc["sources"]
        manifest["state"] = "awaiting_precheck"
        append_audit(task, "table_images_ingested", "task", args.task_key, "agent", args.actor, None, {"table_item_count": len(table_items)}, {"downloaded_source_count": len(new_sources), "failure_count": len(failures), "failures": failures})
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=True)
        return {"ok": True, "task_key": args.task_key, "revision": revision, "table_item_count": len(table_items), "downloaded_source_count": len(new_sources), "failure_count": len(failures), "failures": failures}


def import_items(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        imported = load_input_json(args.file)
        incoming = imported.get("items") if isinstance(imported, dict) else imported
        if not isinstance(incoming, list):
            raise core.PackageError("item 导入文件必须是数组或包含 items 数组")
        incoming = copy.deepcopy(incoming)
        existing = {item["local_id"]: item for item in items_doc["items"]}
        for item in incoming:
            if not isinstance(item, dict):
                raise core.PackageError("每个 item 必须是 JSON object")
            ensure_item_id(args.task_key, item)
            previous = existing.get(item["local_id"])
            if previous is None and item.get("version") != 1:
                raise core.PackageError(f"新 item 必须从 version 1 开始：{item['local_id']}")
            if previous is not None and item != previous and int(item.get("version", 0)) <= int(previous.get("version", 0)):
                raise core.PackageError(f"修改已有 item 必须递增 version：{item['local_id']}")
        incoming_by_id = {item["local_id"]: item for item in incoming}
        if len(incoming_by_id) != len(incoming):
            raise core.PackageError("导入文件包含重复 local_id")
        if args.mode == "replace":
            removed = sorted(set(existing) - set(incoming_by_id))
            if removed:
                raise core.PackageError("replace 不能删除既有 item；请用 superseded 状态与 lineage：" + ", ".join(removed[:5]))
            next_items = incoming
        else:
            merged = dict(existing)
            merged.update(incoming_by_id)
            next_items = list(merged.values())
        candidate_doc = {**items_doc, "items": next_items}
        errors = core.validate_with_schema(task, "items.schema.json", candidate_doc, "导入 items")
        if errors:
            raise core.PackageError("items 不符合 Schema：" + "; ".join(errors[:5]))
        validate_candidate_items(task, next_items, sources_doc)
        before_count = len(items_doc["items"])
        items_doc["items"] = next_items
        # Imported automatic pairs are ready for the first scope confirmation.
        # This advances local preparation only; no user authorization is added.
        if manifest.get("state") in {"received", "organizing"} and any(
            identification_eligible(item) and not item.get("active_identification") for item in next_items
        ):
            manifest["state"] = "awaiting_precheck"
        append_audit(
            task,
            "items_imported",
            "task",
            args.task_key,
            "agent",
            args.actor,
            {"item_count": before_count},
            {"item_count": len(next_items)},
            {"mode": args.mode, "input_sha256": core.sha256_file(Path(args.file).expanduser().resolve())},
        )
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=True)
        result = core.validate_package_structure(task, args.task_key, check_integrity=True)
        if not result["ok"]:
            raise core.PackageError("导入后任务未通过校验：" + "; ".join(result["errors"][:5]))
        return {"ok": True, "task_key": args.task_key, "revision": revision, "dataset_revision": manifest["dataset_revision"], "item_count": len(next_items)}

def import_pairing(args: argparse.Namespace) -> Dict[str, Any]:
    """持久化用户导出的配对确认；不触发任何线上操作。"""
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        raw_bytes, payload = read_exact_json(args.file)
        pairing_dir = task / "pairing"; pairing_dir.mkdir(exist_ok=True); (pairing_dir / "exports").mkdir(exist_ok=True)
        if not (pairing_dir / "decisions.jsonl").exists():
            (pairing_dir / "decisions.jsonl").touch()
            for name in ("pairing-decision.schema.json", "pairing-export.schema.json"):
                shutil.copy2(Path(__file__).resolve().parent.parent / "assets" / "schemas" / name, task / "schemas" / name)
        errors = core.validate_with_schema(task, "pairing-export.schema.json", payload, "配对审核包")
        if errors: raise core.PackageError("配对审核包不符合 Schema：" + "; ".join(errors[:5]))
        if payload.get("taskKey") != args.task_key or payload.get("datasetFingerprint") != manifest.get("dataset_fingerprint"):
            raise core.PackageError("配对审核包与当前任务或数据集不一致")
        source_ids = {source["source_id"] for source in sources_doc["sources"]}; seen, assigned = set(), {}
        for decision in payload["decisions"]:
            local_id = decision["localId"]
            if local_id in seen: raise core.PackageError(f"配对审核包包含重复 localId：{local_id}")
            seen.add(local_id); item = find_item(items_doc, local_id)
            item_sources = {entry.get("source_id") for entry in item.get("evidence", [])}
            for value in decision["sourceAssignments"]:
                source_id = value["sourceId"]
                if source_id not in source_ids or source_id not in item_sources: raise core.PackageError(f"配对决定引用了非本条目的 source：{source_id}")
                if source_id in assigned: raise core.PackageError(f"同一图片被多个配对决定分配：{source_id}")
                assigned[source_id] = local_id
        digest = hashlib.sha256(raw_bytes).hexdigest(); export_ref = f"pairing/exports/import-{digest[:12]}.json"; save_immutable_bytes(task / export_ref, raw_bytes)
        for decision in payload["decisions"]:
            item = find_item(items_doc, decision["localId"]); pairing_id = new_id("pairing")
            assignments = [{"source_id": v["sourceId"], "role": v["role"]} for v in decision["sourceAssignments"]]
            event = {"schema_version":"heribase.pairing-decision.v1","pairing_id":pairing_id,"local_id":item["local_id"],"action":decision["action"],"source_assignments":assignments,"actor":{"type":"import","name":args.actor},"interaction":{"source":"import","batch_action_id":decision.get("batchActionId"),"import_ref":export_ref},"based_on":{"item_version":item["version"],"dataset_revision":manifest["dataset_revision"],"dataset_fingerprint":manifest["dataset_fingerprint"]},"created_at":decision["updatedAt"]}
            append_log_line(task, "pairing/decisions.jsonl", event, "pairing-decision.schema.json")
            state = {"confirm_pair":"confirmed","need_photo":"single_side","exclude":"excluded","split":"needs_review","merge":"needs_review"}[decision["action"]]
            item["organization"].update({"pairing_state":state,"pairing_decision_id":pairing_id,"source_assignment":assignments})
            item["version"] += 1; item["updated_at"] = now_iso(); item["attention_flags"] = [v for v in item.get("attention_flags", []) if v != "pairing_needs_confirmation"]
            # 旧识别仍保留其不可变 raw 和身份出处，但不能继续当作新证据的有效结果。
            # 仅让审核投影过期是不够的：否则重新点“收藏”会复用改图前的识别。
            if item.get("active_identification"):
                item["active_identification"]["status"] = "stale"
            if item.get("review_projection"): item["review_projection"]["stale"] = True
        manifest["state"] = "identification_pending"
        plan_path = task / "collection" / "plan.json"
        plan = core.read_json(plan_path) if plan_path.is_file() else None
        if plan and plan.get("status") not in {"consumed", "cancelled", "stale"}:
            plan["status"] = "stale"
        append_audit(task, "pairing_imported", "task", args.task_key, "user", args.actor, None, {"decision_count":len(payload["decisions"])}, {"import_ref":export_ref})
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=True, plan=plan)
        return {"ok":True,"task_key":args.task_key,"revision":revision,"decision_count":len(payload["decisions"]),"import_ref":export_ref}


def identification_source_roles(item: Dict[str, Any]) -> Dict[str, str]:
    """返回识别可用的正反面来源；用户确认的配对分配优先于初始猜测角色。"""

    evidence_sources = {value.get("source_id") for value in item.get("evidence", []) if value.get("is_primary")}
    direct = {
        value["role"]: value["source_id"]
        for value in item.get("evidence", [])
        if value.get("is_primary") and value.get("role") in {"obverse", "reverse"}
    }
    assignments = (item.get("organization") or {}).get("source_assignment", [])
    confirmed = {
        value.get("role"): value.get("source_id")
        for value in assignments
        if value.get("role") in {"obverse", "reverse"} and value.get("source_id") in evidence_sources
    }
    # 用户在工作台改过方向后，必须使用当前分配；即使分配缺面也不能退回旧图。
    return confirmed if assignments else direct


def identification_eligible(item: Dict[str, Any]) -> bool:
    """判断候选是否已具备本地正反面证据且没有待处理的配对阻断项。"""

    if item.get("status") != "active":
        return False
    if (item.get("organization") or {}).get("pairing_state") in {"excluded", "single_side", "needs_review"}:
        return False
    flags = set(item.get("attention_flags", []))
    if {"pairing_needs_confirmation", "source_incomplete", "identity_conflict"} & flags:
        return False
    roles = identification_source_roles(item)
    return {"obverse", "reverse"}.issubset(roles) and roles["obverse"] != roles["reverse"]


def authorize_identification(args: argparse.Namespace) -> Dict[str, Any]:
    """把用户看过的首次识别范围绑定到当前数据集，尚不执行任何上传。"""

    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        if manifest.get("state") not in {"awaiting_precheck", "identification_pending"}:
            raise core.PackageError("任务不在首次识别确认阶段")
        requested = list(dict.fromkeys(args.local_ids))
        if not requested or len(requested) != len(args.local_ids):
            raise core.PackageError("首次识别确认必须提供不重复的 local-id")
        eligible = {item["local_id"] for item in items_doc["items"] if identification_eligible(item)}
        if set(requested) - eligible:
            raise core.PackageError("确认范围包含未完成配对、缺面或不可识别的候选")
        versions = {local_id: find_item(items_doc, local_id)["version"] for local_id in requested}
        scope = {"local_ids": requested, "item_versions": versions, "dataset_revision": manifest["dataset_revision"], "dataset_fingerprint": manifest["dataset_fingerprint"]}
        scope_sha256 = hashlib.sha256(json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        before = {"state": manifest.get("state")}
        manifest["state"] = "identification_pending"
        append_audit(task, "identification_authorized", "task", args.task_key, "user", args.confirmed_by, before, {"state": "identification_pending", **scope, "scope_sha256": scope_sha256})
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False)
        return {"ok": True, "task_key": args.task_key, "revision": revision, "authorized_local_ids": requested, "dataset_revision": scope["dataset_revision"], "dataset_fingerprint": scope["dataset_fingerprint"], "scope_sha256": scope_sha256}


def migrate_drop_sensitive_identifiers(args: argparse.Namespace) -> Dict[str, Any]:
    """受控升级任务内复制 schema，并移除已废弃的身份字段。

    普通完整性刷新绝不允许重设 `schemas/` 的基线；此迁移是唯一窄口，先确认
    任务没有其他完整性差异，再替换两个受影响 schema、使旧计划失效并记录审计。
    原始服务响应不改写，仍作为不可变证据保留。
    """

    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        task = core.resolve_task(root, args.task_key)
        manifest = core.read_json(task / "manifest.json")
        if getattr(args, "expected_revision", None) is not None and manifest.get("revision") != args.expected_revision:
            raise core.PackageError(f"revision 冲突：期望 {args.expected_revision}，当前 {manifest.get('revision')}")
        integrity = core.read_json(task / "integrity.json")
        differences = core.integrity_differences(task, integrity)
        if differences:
            summary = ", ".join(f"{entry['change']} {entry['path']}" for entry in differences[:5])
            raise core.PackageError(f"迁移前任务完整性不一致，拒绝覆盖：{summary}")

        sources_doc = core.read_json(task / "inputs/sources.json")
        items_doc = core.read_json(task / "data/items.json")
        removed_items: List[str] = []
        for item in items_doc.get("items", []):
            identification = item.get("active_identification")
            if not isinstance(identification, dict):
                continue
            removed = [field for field in REMOVED_IDENTIFICATION_FIELDS if field in identification]
            if not removed:
                continue
            for field in removed:
                identification.pop(field, None)
            item["version"] = int(item.get("version", 0)) + 1
            item["updated_at"] = now_iso()
            projection = item.get("review_projection")
            if isinstance(projection, dict):
                projection["stale"] = True
            removed_items.append(item["local_id"])

        plan_path = task / "collection/plan.json"
        plan: Optional[Dict[str, Any]] = None
        plan_invalidated = False
        if plan_path.is_file():
            plan = core.read_json(plan_path)
            for planned in plan.get("items", []):
                for field in REMOVED_IDENTIFICATION_FIELDS:
                    if field in planned:
                        planned.pop(field)
                        plan_invalidated = True
            if plan_invalidated:
                plan["status"] = "stale"
                plan["authorization"] = None
                plan["payload_sha256"] = core.collection_plan_payload_hash(plan)

        schema_root = Path(__file__).resolve().parent.parent / "assets" / "schemas"
        for schema_name in ("items.schema.json", "collection-plan.schema.json"):
            source = schema_root / schema_name
            if not source.is_file():
                raise core.PackageError(f"迁移源 Schema 缺失：{schema_name}")
            core.write_json_atomic(task / "schemas" / schema_name, core.read_json(source))

        append_audit(
            task,
            "schema_migration_drop_sensitive_identifiers",
            "task",
            args.task_key,
            "agent",
            getattr(args, "actor", "codex"),
            {"revision": manifest.get("revision")},
            {"removed_fields": list(REMOVED_IDENTIFICATION_FIELDS)},
            {"items_changed": removed_items, "plan_invalidated": plan_invalidated},
        )
        revision = commit_snapshots(
            task,
            manifest,
            sources_doc,
            items_doc,
            dataset_changed=bool(removed_items),
            plan=plan,
        )
        validation = core.validate_package_structure(task, args.task_key, check_integrity=True)
        if not validation["ok"]:
            raise core.PackageError("迁移后任务校验失败：" + "; ".join(validation["errors"][:5]))
        return {
            "ok": True,
            "task_key": args.task_key,
            "revision": revision,
            "items_changed": removed_items,
            "plan_invalidated": plan_invalidated,
        }


def record_recognition(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        event = require_safe_object(load_input_json(args.event_json), "识别事件")
        require_safe_cli(event)
        local_id = event.get("local_id")
        if not isinstance(local_id, str):
            raise core.PackageError("识别事件缺少 local_id")
        item = find_item(items_doc, local_id)
        if event.get("input", {}).get("item_version") != item.get("version"):
            raise core.PackageError("识别事件的 item_version 已过期")
        attempt_id = event.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise core.PackageError("识别事件缺少 attempt_id")

        raw_value: Optional[Dict[str, Any]] = None
        raw_relative: Optional[str] = None
        raw_hash: Optional[str] = None
        normalized: Optional[Dict[str, Optional[str]]] = None
        if args.raw_json:
            raw_bytes, raw_value = read_exact_json(args.raw_json)
            raw_relative = f"recognition/raw/{attempt_id}.json"
            raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        if event.get("status") == "succeeded":
            if raw_value is None:
                raise core.PackageError("成功识别必须保存 raw JSON")
            # 只投影后续流程实际需要的服务身份。目录编号和标准对象 URI 即使
            # 出现在不可变 raw 响应中，也不能进入任务快照或后续计划。
            normalized = {field: service_value(raw_value, field) for field in ("identify_uri", "user_uniq_uri")}
            if normalized["identify_uri"] is None:
                raise core.PackageError("成功识别响应缺少 identifyUri/uri")
        event = copy.deepcopy(event)
        event.update({"raw_response_ref": raw_relative, "raw_response_sha256": raw_hash})
        prepared = prepare_log_line(task, "recognition/attempts.jsonl", event, "recognition-attempt.schema.json")
        if args.raw_json:
            save_immutable_bytes(task / raw_relative, raw_bytes)
        recorded = write_log_line(task, "recognition/attempts.jsonl", prepared)

        previous_identification = copy.deepcopy(item.get("active_identification"))
        item["version"] = int(item["version"]) + 1
        item["updated_at"] = now_iso()
        flags = set(item.get("attention_flags", []))
        if event.get("status") == "succeeded":
            assert normalized is not None
            # 失败事件是尝试历史而非永久结论。后续成功成为 active_identification 时，
            # 清除会误导审核员的运行态失败/排队标记，但原始失败事件仍不可变地保留在日志中。
            flags.discard("recognition_failed")
            flags.discard("recognition_pending")
            flags.discard("identity_not_identified")
            previous_user_uri = (previous_identification or {}).get("user_uniq_uri")
            if previous_user_uri and normalized["user_uniq_uri"] and previous_user_uri != normalized["user_uniq_uri"]:
                item["status"] = "identity_conflict"
                flags.add("identity_conflict")
                conflicts = item.setdefault("field_claims", {}).setdefault("identity_conflicts", [])
                conflicts.append({
                    "attempt_id": attempt_id,
                    "previous_user_uniq_uri": previous_user_uri,
                    "new_user_uniq_uri": normalized["user_uniq_uri"],
                    "raw_response_ref": raw_relative,
                    "created_at": now_iso(),
                })
            else:
                item["active_identification"] = {
                    "attempt_id": attempt_id,
                    "snapshot_id": event.get("remote_task_id") or attempt_id,
                    "status": "succeeded",
                    **normalized,
                    "raw_response_ref": raw_relative,
                    "raw_response_sha256": raw_hash,
                    "recognized_at": event.get("finished_at") or now_iso(),
                }
        else:
            flags.add("recognition_pending" if event.get("status") in {"queued", "uploading", "requested", "polling", "unknown"} else "recognition_failed")
        item["attention_flags"] = sorted(flags)
        if item.get("review_projection"):
            item["review_projection"]["stale"] = True

        append_audit(
            task,
            "recognition_recorded",
            "item",
            local_id,
            "agent",
            args.actor,
            {"active_identification": previous_identification},
            {"attempt_id": attempt_id, "status": event.get("status")},
            {"raw_response_ref": raw_relative, "raw_response_sha256": raw_hash},
            attempt_id,
        )
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=True)
        return {"ok": True, "task_key": args.task_key, "revision": revision, "dataset_revision": manifest["dataset_revision"], "attempt": recorded, "item": item}


def current_decisions(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        item["local_id"]: item["review_projection"]
        for item in items
        if isinstance(item.get("review_projection"), dict)
        and item["review_projection"].get("decision") in {"collect", "need_photo", "exclude"}
        and not item["review_projection"].get("stale")
    }


def import_review(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        raw_bytes, package = read_exact_json(args.file)
        schema_version = package.get("schemaVersion")
        if schema_version != 2:
            if not (schema_version == 1 and args.allow_legacy):
                raise core.PackageError("审核包必须是带数据集指纹的 schemaVersion 2；旧版需显式 --allow-legacy")
        if schema_version == 2:
            schema_errors = core.validate_with_schema(
                task, "review-export.schema.json", package, "审核导出包"
            )
            if schema_errors:
                raise core.PackageError("审核包不符合 Schema：" + "; ".join(schema_errors[:5]))
        if schema_version == 2 and package.get("datasetFingerprint") != manifest.get("dataset_fingerprint"):
            raise core.PackageError("审核包数据集指纹与当前任务不一致")
        decisions = package.get("decisions")
        if not isinstance(decisions, list):
            raise core.PackageError("审核包 decisions 必须是数组")
        imported: Dict[str, Dict[str, Any]] = {}
        summary = {"collect": 0, "needPhoto": 0, "excluded": 0}
        for decision in decisions:
            if not isinstance(decision, dict) or decision.get("decision") not in UI_DECISIONS:
                raise core.PackageError("审核包包含无效决定")
            local_id = decision.get("recordId")
            if not isinstance(local_id, str):
                raise core.PackageError("审核决定缺少 recordId")
            if local_id in imported:
                raise core.PackageError(f"审核包包含重复 recordId：{local_id}")
            find_item(items_doc, local_id)
            imported[local_id] = decision
            if decision["decision"] == "collect":
                summary["collect"] += 1
            elif decision["decision"] == "need-photo":
                summary["needPhoto"] += 1
            else:
                summary["excluded"] += 1
        if package.get("summary") != summary:
            raise core.PackageError("审核包 summary 与 decisions 实际计数不一致")

        export_hash = hashlib.sha256(raw_bytes).hexdigest()
        export_name = f"import-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{export_hash[:12]}.json"
        export_relative = f"review/exports/{export_name}"
        save_immutable_bytes(task / export_relative, raw_bytes)
        previous = current_decisions(items_doc["items"])
        targets = set(imported)
        if args.mode == "replace":
            targets |= set(previous)
        written = 0
        for local_id in sorted(targets):
            item = find_item(items_doc, local_id)
            incoming = imported.get(local_id)
            old_projection = item.get("review_projection")
            if incoming:
                action = "set"
                decision_value: Optional[str] = INTERNAL_DECISION_MAP[incoming["decision"]]
            else:
                action = "clear"
                decision_value = None
            decision_id = new_id("decision")
            event = {
                "schema_version": "heribase.review-decision.v1",
                "decision_id": decision_id,
                "local_id": local_id,
                "action": action,
                "decision": decision_value,
                "note": None,
                "actor": {"type": "import", "name": args.actor},
                "interaction": {
                    "source": "import",
                    "batch_action_id": incoming.get("batchActionId") if incoming else None,
                    "import_ref": export_relative,
                },
                "based_on": {
                    "item_version": item["version"],
                    "identification_snapshot_id": (item.get("active_identification") or {}).get("snapshot_id"),
                    "dataset_revision": manifest["dataset_revision"],
                    "dataset_fingerprint": manifest["dataset_fingerprint"],
                },
                "supersedes": old_projection.get("decision_id") if isinstance(old_projection, dict) else None,
                "reverts": None,
                "created_at": incoming.get("updatedAt") if incoming else now_iso(),
            }
            append_log_line(task, "review/decisions.jsonl", event, "review-decision.schema.json")
            if incoming:
                item["review_projection"] = {
                    "decision_id": decision_id,
                    "decision": decision_value,
                    "actor": args.actor,
                    "item_version": item["version"],
                    "identification_snapshot_id": (item.get("active_identification") or {}).get("snapshot_id"),
                    "dataset_revision": manifest["dataset_revision"],
                    "dataset_fingerprint": manifest["dataset_fingerprint"],
                    "updated_at": incoming.get("updatedAt"),
                    "stale": False,
                }
            else:
                item["review_projection"] = None
            written += 1

        plan_path = task / "collection" / "plan.json"
        plan = core.read_json(plan_path) if plan_path.exists() else None
        if plan and plan.get("status") not in {"consumed", "cancelled", "stale"}:
            plan["status"] = "stale"
        append_audit(
            task,
            "review_imported",
            "task",
            args.task_key,
            "user",
            args.actor,
            {"decision_count": len(previous)},
            {"decision_count": len(imported)},
            {"mode": args.mode, "import_ref": export_relative, "events_written": written, "legacy": schema_version == 1},
        )
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False, plan=plan)
        return {"ok": True, "task_key": args.task_key, "revision": revision, "import_ref": export_relative, "events_written": written, "summary": package.get("summary")}


def display_for_item(item: Dict[str, Any]) -> Dict[str, Any]:
    resolved = item.get("resolved_fields") or {}
    def value(name: str) -> Any:
        field = resolved.get(name)
        return field.get("value") if isinstance(field, dict) else field
    return {"title": value("title") or value("name") or item["local_id"], "year": value("year"), "grade": value("grade")}


def plan_current_errors(plan: Dict[str, Any], manifest: Dict[str, Any], items_doc: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if plan.get("based_on", {}).get("dataset_revision") != manifest.get("dataset_revision"):
        errors.append("dataset_revision 已变化")
    if plan.get("based_on", {}).get("dataset_fingerprint") != manifest.get("dataset_fingerprint"):
        errors.append("dataset_fingerprint 已变化")
    for planned in plan.get("items", []):
        try:
            item = find_item(items_doc, planned.get("local_id"))
        except core.PackageError:
            errors.append(f"item 不存在：{planned.get('local_id')}")
            continue
        identification = item.get("active_identification") or {}
        operation_type = planned.get("operation_type") or plan.get("operation_type")
        collection = item.get("collection_projection") or {}
        # record_collection 会在一条调用成功后递增该枚的 item version。
        # 计划处于 executing 时，这些已归档的条目不再是后续调用的前置条件；
        # 继续用创建计划时的 version 校验它们，会把正常的逐条执行误判为计划过期。
        completed_status = "cancelled" if operation_type == "collection_cancel" else "succeeded"
        if plan.get("status") == "executing" and collection.get("status") == completed_status:
            continue
        if item.get("version") != planned.get("item_version"):
            errors.append(f"item version 已变化：{item['local_id']}")
        if operation_type == "collection_add":
            review = item.get("review_projection") or {}
            if review.get("decision") != "collect" or review.get("decision_id") != planned.get("decision_id") or review.get("stale"):
                errors.append(f"审核决定已变化：{item['local_id']}")
            if identification.get("snapshot_id") != planned.get("identification_snapshot_id"):
                errors.append(f"识别快照已变化：{item['local_id']}")
        else:
            collection = item.get("collection_projection") or {}
            if not planned.get("collection_uri") or collection.get("collection_uri") != planned.get("collection_uri"):
                errors.append(f"collection_uri 已变化：{item['local_id']}")
        for field in ("identify_uri", "user_uniq_uri"):
            if identification.get(field) != planned.get(field):
                errors.append(f"{field} 已变化：{item['local_id']}")
    return errors


def load_requested_operations(args: argparse.Namespace) -> Dict[str, Dict[str, Any]]:
    """读取修改/取消意图；只接受 local_id 和 typed changes，不接收命令或路径。"""

    operations_json = getattr(args, "operations_json", None)
    if args.operation == "collection_add":
        if operations_json:
            raise core.PackageError("collection_add 的范围来自最新审核决定，不能另传 operations-json")
        return {}
    if not operations_json:
        raise core.PackageError(f"{args.operation} 必须提供 --operations-json")
    package = require_safe_object(load_input_json(operations_json), "收藏修改意图")
    operations = package.get("operations")
    if not isinstance(operations, list) or not operations:
        raise core.PackageError("operations-json 必须包含非空 operations 数组")
    requested: Dict[str, Dict[str, Any]] = {}
    for index, value in enumerate(operations, start=1):
        if not isinstance(value, dict) or set(value) - {"local_id", "changes"}:
            raise core.PackageError(f"operations[{index}] 只允许 local_id 和 changes")
        local_id = value.get("local_id")
        if not isinstance(local_id, str) or not local_id or local_id in requested:
            raise core.PackageError(f"operations[{index}] 的 local_id 缺失或重复")
        changes = value.get("changes", {})
        if not isinstance(changes, dict):
            raise core.PackageError(f"operations[{index}].changes 必须是 object")
        if args.operation == "collection_update" and not changes:
            raise core.PackageError(f"operations[{index}] 的修改内容不能为空")
        if args.operation == "collection_cancel" and changes:
            raise core.PackageError("collection_cancel 不接受 changes")
        requested[local_id] = {"changes": copy.deepcopy(changes)}
    return requested


def build_plan(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        requested = load_requested_operations(args)
        # 工作台确认的勾选范围是授权边界；省略时保留原 CLI 的全量行为。
        selected_ids = getattr(args, "local_ids", None)
        if selected_ids is not None and (not selected_ids or len(set(selected_ids)) != len(selected_ids)
                                         or set(selected_ids) - {item["local_id"] for item in items_doc["items"]}):
            raise core.PackageError("收藏范围为空、重复或包含不存在的条目")
        included: List[Dict[str, Any]] = []
        excluded: List[Dict[str, str]] = []
        for item in items_doc["items"]:
            if selected_ids is not None and item["local_id"] not in selected_ids:
                continue
            review = item.get("review_projection") or {}
            identification = item.get("active_identification") or {}
            collection = item.get("collection_projection") or {}
            reasons: List[str] = []
            if args.operation == "collection_add":
                if collection.get("collection_uri"):
                    reasons.append("已有收藏关联，不能重复新增")
                selected = review.get("decision") == "collect" and not review.get("stale")
                if not selected:
                    reasons.append("未被用户决定收藏或决定已过期")
                if identification.get("status") != "succeeded" or not identification.get("identify_uri"):
                    reasons.append("缺少成功识别及 identify_uri")
            else:
                selected = item["local_id"] in requested
                if not selected:
                    continue
                if not collection.get("collection_uri"):
                    reasons.append("缺少已验证的 collection_uri")
            if item.get("status") != "active":
                reasons.append(f"item 状态为 {item.get('status')}")
            if reasons:
                excluded.append({"local_id": item["local_id"], "reason": "；".join(reasons)})
                continue
            included.append({
                "local_id": item["local_id"],
                "item_version": item["version"],
                "decision_id": review.get("decision_id") if args.operation == "collection_add" else None,
                "identification_snapshot_id": identification.get("snapshot_id"),
                "identify_uri": identification.get("identify_uri"),
                "user_uniq_uri": identification.get("user_uniq_uri"),
                "operation_type": args.operation,
                "collection_uri": collection.get("collection_uri"),
                "changes": requested.get(item["local_id"], {}).get("changes", {}),
                "display": display_for_item(item),
            })
        if requested:
            existing_ids = {item["local_id"] for item in items_doc["items"]}
            for missing in sorted(set(requested) - existing_ids):
                excluded.append({"local_id": missing, "reason": "任务中不存在该 local_id"})
        if not included:
            raise core.PackageError("没有满足当前收藏操作条件的条目")
        plan = {
            "schema_version": "heribase.collection-plan.v1",
            "plan_id": new_id("plan"),
            "task_key": args.task_key,
            "status": "awaiting_confirmation",
            "operation_type": args.operation,
            "created_at": now_iso(),
            "based_on": {
                "dataset_revision": manifest["dataset_revision"],
                "dataset_fingerprint": manifest["dataset_fingerprint"],
            },
            "items": included,
            "excluded": excluded,
            "impact": {
                "included": len(included),
                "excluded": len(excluded),
                "estimated_fee": None,
                "fee_unknown": True,
            },
            "payload_sha256": "",
            "authorization": None,
        }
        plan["payload_sha256"] = core.collection_plan_payload_hash(plan)
        errors = core.validate_with_schema(task, "collection-plan.schema.json", plan, "collection plan")
        if errors:
            raise core.PackageError("收藏计划不符合 Schema：" + "; ".join(errors[:5]))
        manifest["state"] = "awaiting_collection_confirmation"
        append_audit(
            task,
            "collection_plan_created",
            "plan",
            plan["plan_id"],
            "agent",
            args.actor,
            None,
            {"payload_sha256": plan["payload_sha256"], "included": len(included), "excluded": len(excluded)},
            # 编辑和取消的计划是本地历史的一部分：保留编辑前的服务端快照引用值
            # 与精确字段差异，之后的 collection operation raw 响应形成完整前后证据。
            {
                "operation_type": args.operation,
                "items": [
                    {"local_id": item["local_id"], "collection_uri": item.get("collection_uri"), "changes": item.get("changes", {})}
                    for item in included
                ],
                "remote_before": getattr(args, "remote_before", None),
            },
        )
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False, plan=plan)
        return {"ok": True, "task_key": args.task_key, "revision": revision, "plan_id": plan["plan_id"], "payload_sha256": plan["payload_sha256"], "impact": plan["impact"], "items": included, "excluded": excluded}


def authorize_plan(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        plan_path = task / "collection" / "plan.json"
        if not plan_path.exists():
            raise core.PackageError("当前任务没有收藏计划")
        plan = core.read_json(plan_path)
        if plan.get("plan_id") != args.plan_id or plan.get("status") != "awaiting_confirmation":
            raise core.PackageError("计划 ID 不匹配或计划不在待确认状态")
        calculated = core.collection_plan_payload_hash(plan)
        if calculated != plan.get("payload_sha256") or calculated != args.confirmed_payload_sha256:
            raise core.PackageError("用户确认的 payload 摘要与当前计划不一致")
        current_errors = plan_current_errors(plan, manifest, items_doc)
        if current_errors:
            plan["status"] = "stale"
            append_audit(
                task,
                "collection_plan_stale",
                "plan",
                plan["plan_id"],
                "system",
                "task_operations",
                {"status": "awaiting_confirmation"},
                {"status": "stale"},
                {"reasons": current_errors[:20]},
            )
            revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False, plan=plan)
            raise core.PackageError(
                f"计划已过期并在 revision {revision} 留痕：" + "; ".join(current_errors[:5])
            )
        plan["status"] = "authorized"
        plan["authorization"] = {
            "confirmed_by": args.confirmed_by,
            "confirmed_at": now_iso(),
            "confirmed_payload_sha256": calculated,
        }
        append_audit(
            task,
            "collection_plan_authorized",
            "plan",
            plan["plan_id"],
            "user",
            args.confirmed_by,
            {"status": "awaiting_confirmation"},
            {"status": "authorized", "confirmed_payload_sha256": calculated},
        )
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False, plan=plan)
        validation = core.validate_package_structure(task, args.task_key, check_integrity=True)
        return {"ok": validation["online_writes_allowed"], "task_key": args.task_key, "revision": revision, "plan_id": plan["plan_id"], "payload_sha256": calculated, "online_writes_allowed": validation["online_writes_allowed"], "errors": validation["errors"], "warnings": validation["warnings"]}


def record_collection(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    with task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = open_task(args)
        plan = core.read_json(task / "collection" / "plan.json")
        if plan.get("status") not in {"authorized", "executing"}:
            raise core.PackageError("收藏计划尚未授权或已经结束")
        current_errors = plan_current_errors(plan, manifest, items_doc)
        if current_errors:
            plan["status"] = "stale"
            append_audit(
                task,
                "collection_plan_stale",
                "plan",
                plan.get("plan_id"),
                "system",
                "task_operations",
                {"status": "authorized"},
                {"status": "stale"},
                {"reasons": current_errors[:20]},
            )
            revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False, plan=plan)
            raise core.PackageError(
                f"收藏计划已过期并在 revision {revision} 留痕：" + "; ".join(current_errors[:5])
            )
        event = require_safe_object(load_input_json(args.event_json), "收藏事件")
        require_safe_cli(event)
        local_id = event.get("local_id")
        planned = next((value for value in plan["items"] if value["local_id"] == local_id), None)
        if planned is None:
            raise core.PackageError("收藏事件的 local_id 不在已授权计划中")
        item = find_item(items_doc, local_id)
        operation_type = planned.get("operation_type") or plan.get("operation_type")
        expected = event.get("expected", {})
        if (
            event.get("plan_id") != plan.get("plan_id")
            or event.get("operation_type") != operation_type
            or expected.get("item_version") != item.get("version")
            or expected.get("identify_uri") != planned.get("identify_uri")
            or expected.get("user_uniq_uri") != planned.get("user_uniq_uri")
        ):
            raise core.PackageError("收藏事件没有绑定当前计划或 item version")
        previous_attempts, _ = core.parse_jsonl(task / "collection/attempts.jsonl")
        local_attempts = [value for value in previous_attempts if value.get("local_id") == local_id]
        latest_attempt = local_attempts[-1] if local_attempts else None
        if latest_attempt and latest_attempt.get("status") == "reconcile_required" and event.get("classification") != "reconciled_not_found":
            raise core.PackageError("该条目存在 reconcile_required；必须先记录只读核验为 reconciled_not_found")

        attempt_id = event.get("attempt_id")
        raw_value: Optional[Dict[str, Any]] = None
        raw_relative: Optional[str] = None
        raw_hash: Optional[str] = None
        if args.raw_json:
            raw_bytes, raw_value = read_exact_json(args.raw_json)
            raw_relative = f"collection/raw/{attempt_id}.json"
            raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        status = event.get("status")
        result: Optional[Dict[str, Optional[str]]] = None
        if status == "succeeded":
            if raw_value is None:
                status = "reconcile_required"
            else:
                collection_uri = service_value(raw_value, "collection_uri")
                result_user_uri = service_value(raw_value, "user_uniq_uri")
                if not collection_uri or (planned.get("user_uniq_uri") and result_user_uri and result_user_uri != planned.get("user_uniq_uri")):
                    status = "reconcile_required"
                else:
                    result = {"collection_uri": collection_uri, "user_uniq_uri": result_user_uri}
        event = copy.deepcopy(event)
        event.update({"status": status, "raw_response_ref": raw_relative, "raw_response_sha256": raw_hash, "result": result})
        prepared = prepare_log_line(task, "collection/attempts.jsonl", event, "collection-operation.schema.json")
        if args.raw_json:
            save_immutable_bytes(task / raw_relative, raw_bytes)
        recorded = write_log_line(task, "collection/attempts.jsonl", prepared)
        previous_projection = copy.deepcopy(item.get("collection_projection"))
        if status == "succeeded" and result:
            item["collection_projection"] = {
                "status": "cancelled" if operation_type == "collection_cancel" else "succeeded",
                "operation_id": event["operation_id"],
                "collection_uri": result["collection_uri"],
                "user_uniq_uri": result["user_uniq_uri"],
                "applied_changes": planned.get("changes", {}) if operation_type == "collection_update" else {},
                "raw_response_ref": raw_relative,
                "raw_response_sha256": raw_hash,
                "last_error": None,
            }
        else:
            item["collection_projection"] = {
                "status": status,
                "operation_id": event["operation_id"],
                "collection_uri": None,
                "user_uniq_uri": planned.get("user_uniq_uri"),
                "raw_response_ref": raw_relative,
                "raw_response_sha256": raw_hash,
                "last_error": event.get("error"),
            }
        item["updated_at"] = now_iso()
        plan["status"] = "executing"
        planned_ids = {value["local_id"] for value in plan["items"]}
        terminal = {
            value["local_id"]
            for value in items_doc["items"]
            if value["local_id"] in planned_ids
            and (value.get("collection_projection") or {}).get("status") in {"succeeded", "failed_terminal", "cancelled"}
        }
        if terminal == planned_ids:
            failures = [value for value in items_doc["items"] if value["local_id"] in planned_ids and (value.get("collection_projection") or {}).get("status") != "succeeded"]
            plan["status"] = "consumed"
            manifest["state"] = "completed_with_exceptions" if failures else "completed"
        else:
            manifest["state"] = "collecting"
        append_audit(
            task,
            "collection_operation_recorded",
            "item",
            local_id,
            "agent",
            args.actor,
            {"collection_projection": previous_projection},
            {"status": status, "collection_uri": (result or {}).get("collection_uri")},
            # 计划中的 changes 与执行回执并列记录，档案页才能从不可变历史还原
            # “请求修改了什么”以及“服务端实际如何响应”。
            {"plan_id": plan["plan_id"], "attempt_id": attempt_id, "raw_response_ref": raw_relative,
             "operation_type": operation_type, "changes": planned.get("changes", {})},
            event.get("operation_id"),
        )
        revision = commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False, plan=plan)
        return {"ok": True, "task_key": args.task_key, "revision": revision, "status": status, "plan_status": plan["status"], "attempt": recorded, "collection_projection": item["collection_projection"]}


def preflight_plan(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    task = core.resolve_task(root, args.task_key)
    validation = core.validate_package_structure(task, args.task_key, check_integrity=True)
    plan_path = task / "collection" / "plan.json"
    plan = core.read_json(plan_path) if plan_path.exists() else None
    return {
        "ok": validation["online_writes_allowed"],
        "task_key": args.task_key,
        "revision": core.read_json(task / "manifest.json").get("revision"),
        "online_writes_allowed": validation["online_writes_allowed"],
        "plan": plan,
        "errors": validation["errors"],
        "warnings": validation["warnings"],
    }


def add_common_task_arguments(parser: argparse.ArgumentParser, *, mutation: bool = True) -> None:
    parser.add_argument("--root", help="测试/隔离任务根目录；生产环境省略")
    parser.add_argument("--task-key", required=True)
    if mutation:
        parser.add_argument("--expected-revision", required=True, type=int)
        parser.add_argument("--actor", default="Codex")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HeriBase 任务包受控事务工具")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest-source", help="复制并登记一个本地来源文件")
    add_common_task_arguments(ingest)
    ingest.add_argument("--file", required=True)
    ingest.add_argument("--kind", required=True, choices=sorted(SOURCE_DESTINATIONS))
    ingest.add_argument("--source-id")
    ingest.add_argument("--origin-type", choices=["local", "remote", "spreadsheet_embedded"], default="local")
    ingest.add_argument("--origin-url")
    ingest.add_argument("--original-path")
    ingest.add_argument("--mime-type")
    ingest.add_argument("--parent-source-id")
    ingest.add_argument("--sheet")
    ingest.add_argument("--row", type=int)
    ingest.add_argument("--column", type=int)
    ingest.add_argument("--cell")
    ingest.add_argument("--relationship-id")
    ingest.set_defaults(handler=ingest_source)

    table_images = commands.add_parser("ingest-table-images", help="归档 CSV 表格中逐行的正反面远程图片")
    add_common_task_arguments(table_images)
    table_images.add_argument("--csv-file", required=True)
    table_images.add_argument("--parent-source-id", required=True)
    table_images.add_argument("--front-column", default="Front Image")
    table_images.add_argument("--back-column", default="Back Image")
    table_images.set_defaults(handler=ingest_table_images)

    items = commands.add_parser("import-items", help="校验并导入规范化 item 快照")
    add_common_task_arguments(items)
    items.add_argument("--file", required=True)
    items.add_argument("--mode", choices=["merge", "replace"], default="merge")
    items.set_defaults(handler=import_items)

    pairing = commands.add_parser("import-pairing", help="把配对审核 JSON 写入逐项事件")
    add_common_task_arguments(pairing)
    pairing.add_argument("--file", required=True)
    pairing.set_defaults(handler=import_pairing)

    authorize_identify = commands.add_parser("authorize-identification", help="记录用户确认的首次识别范围")
    add_common_task_arguments(authorize_identify)
    authorize_identify.add_argument("--local-id", dest="local_ids", action="append", required=True)
    authorize_identify.add_argument("--confirmed-by", required=True)
    authorize_identify.set_defaults(handler=authorize_identification)

    migrate_identifiers = commands.add_parser("migrate-drop-sensitive-identifiers", help="受控移除任务内废弃身份字段并升级复制 Schema")
    add_common_task_arguments(migrate_identifiers)
    migrate_identifiers.set_defaults(handler=migrate_drop_sensitive_identifiers)

    recognition = commands.add_parser("record-recognition", help="原子保存识别 raw、attempt 与 item 投影")
    add_common_task_arguments(recognition)
    recognition.add_argument("--event-json", required=True)
    recognition.add_argument("--raw-json")
    recognition.set_defaults(handler=record_recognition)

    review = commands.add_parser("import-review", help="把审核台 JSON 包转换为逐项决定事件")
    add_common_task_arguments(review)
    review.add_argument("--file", required=True)
    review.add_argument("--mode", choices=["merge", "replace"], default="replace")
    review.add_argument("--allow-legacy", action="store_true")
    review.set_defaults(handler=import_review)

    plan = commands.add_parser("build-plan", help="从最新人工决定生成待确认收藏计划")
    add_common_task_arguments(plan)
    plan.add_argument(
        "--operation",
        choices=["collection_add", "collection_update", "collection_cancel"],
        default="collection_add",
    )
    plan.add_argument(
        "--operations-json",
        help="修改/取消的 typed 意图文件：{operations:[{local_id,changes}]}；新增收藏不得使用",
    )
    plan.set_defaults(handler=build_plan)

    authorize = commands.add_parser("authorize-plan", help="把用户确认绑定到当前计划摘要")
    add_common_task_arguments(authorize)
    authorize.add_argument("--plan-id", required=True)
    authorize.add_argument("--confirmed-payload-sha256", required=True)
    authorize.add_argument("--confirmed-by", required=True)
    authorize.set_defaults(handler=authorize_plan)

    collection = commands.add_parser("record-collection", help="原子保存收藏 raw、attempt 与 item 投影")
    add_common_task_arguments(collection)
    collection.add_argument("--event-json", required=True)
    collection.add_argument("--raw-json")
    collection.set_defaults(handler=record_collection)

    preflight = commands.add_parser("preflight-plan", help="只读验证当前计划是否允许线上写入")
    add_common_task_arguments(preflight, mutation=False)
    preflight.set_defaults(handler=preflight_plan)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
    except core.PackageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
