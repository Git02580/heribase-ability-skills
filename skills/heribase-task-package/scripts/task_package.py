#!/usr/bin/env python3
"""HeriBase 任务包的确定性创建、校验、完整性刷新与目录重建工具。

本脚本只使用 Python 标准库，避免任务包的可验证性依赖项目运行环境。
生产环境默认只操作 ~/.heribase/user-tasks；--root 仅用于测试或显式隔离的数据根目录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TASK_KEY_RE = re.compile(
    r"^[0-9]{8}-[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*(?:-[0-9]{2})?$"
)
RESERVED_NAMES = {"_catalog", "_runtime"}
ACTIVE_ITEM_STATUSES = {"active", "source_incomplete", "identity_conflict"}
SENSITIVE_KEY_PARTS = {
    "authorization",
    "cookie",
    "setcookie",
    "accesstoken",
    "refreshtoken",
    "password",
    "passwd",
    "secret",
    "privatekey",
    "apikey",
}

SCHEMA_FILES = (
    "manifest.schema.json",
    "sources.schema.json",
    "items.schema.json",
    "recognition-attempt.schema.json",
    "review-decision.schema.json",
    "review-export.schema.json",
    "pairing-decision.schema.json",
    "pairing-export.schema.json",
    "collection-plan.schema.json",
    "collection-operation.schema.json",
    "audit-event.schema.json",
    "integrity.schema.json",
)

REQUIRED_FILES = (
    "manifest.json",
    "README.md",
    "integrity.json",
    "inputs/sources.json",
    "data/items.json",
    "recognition/attempts.jsonl",
    "review/decisions.jsonl",
    "collection/attempts.jsonl",
    "audit/events.jsonl",
)

REQUIRED_DIRS = (
    "schemas",
    "inputs/originals/spreadsheets",
    "inputs/originals/images",
    "inputs/originals/documents",
    "inputs/remote-images",
    "inputs/extracted/spreadsheet-images",
    "recognition/raw",
    "review/exports",
    "collection/raw",
    "audit",
    "derived/reports",
)

# 这些区域保存不可替代的来源事实。完整性刷新即使显式接受受控变更，也不能重设其基线。
IMMUTABLE_PREFIXES = (
    "schemas/",
    "inputs/originals/",
    "inputs/remote-images/",
    "inputs/extracted/",
    "recognition/raw/",
    "collection/raw/",
)

LOG_PATHS = {
    "recognition/attempts.jsonl",
    "review/decisions.jsonl",
    "pairing/decisions.jsonl",
    "collection/attempts.jsonl",
    "audit/events.jsonl",
}


class PackageError(RuntimeError):
    """可直接呈现给用户、且不会暴露堆栈或敏感内容的任务包错误。"""


def canonical_json(value: Any) -> bytes:
    """返回跨平台稳定的 UTF-8 JSON，用于指纹和事件哈希。"""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def dataset_fingerprint(sources: List[Any], items: List[Any]) -> str:
    """计算用户审核所依据的数据集指纹。

    审核和收藏 projection 是从日志重放得到的状态，不能参与自身依据的指纹，
    否则写入一条决定会让这条决定立刻过期。item 的证据、组织、字段和识别身份仍参与指纹。
    """

    normalized_items: List[Any] = []
    for item in items:
        if not isinstance(item, dict):
            normalized_items.append(item)
            continue
        normalized_items.append(
            {
                key: value
                for key, value in item.items()
                if key not in {"review_projection", "collection_projection", "updated_at"}
            }
        )
    return sha256_bytes(canonical_json({"sources": sources, "items": normalized_items}))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file_prefix(path: Path, byte_count: int) -> str:
    """计算文件前缀哈希，用于证明 JSONL 只追加而没有重写历史字节。"""

    digest = hashlib.sha256()
    remaining = byte_count
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    if remaining:
        raise PackageError(f"文件短于期望前缀：{path}")
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json_atomic(path: Path, value: Any) -> None:
    """在目标目录内写临时文件后替换，避免跨文件系统 rename 与半截 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"无法读取 JSON：{path}：{exc}") from exc


def json_type_matches(value: Any, expected: str) -> bool:
    """实现本任务 Schemas 所需的 JSON Schema 基础类型判断。

    Python 的 bool 是 int 子类，因此必须显式排除，避免 true 被接受为 revision。
    """

    checks = {
        "null": value is None,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }
    return checks.get(expected, False)


def resolve_local_ref(root_schema: Dict[str, Any], reference: str) -> Dict[str, Any]:
    if not reference.startswith("#/"):
        raise PackageError(f"Schema 只允许包内 $ref：{reference}")
    value: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise PackageError(f"Schema $ref 无法解析：{reference}")
        value = value[part]
    if not isinstance(value, dict):
        raise PackageError(f"Schema $ref 目标不是 object：{reference}")
    return value


def validate_schema_value(
    value: Any,
    schema: Dict[str, Any],
    root_schema: Optional[Dict[str, Any]] = None,
    path: str = "$",
) -> List[str]:
    """验证本 Skill 使用的 JSON Schema 2020-12 子集。

    任务包不能假设系统安装 jsonschema；这个小型验证器覆盖资产 Schemas 实际使用的
    required/type/properties/items/ref/enum/const/anyOf/allOf/if-then 等关键字。
    """

    root = root_schema or schema
    if "$ref" in schema:
        return validate_schema_value(value, resolve_local_ref(root, schema["$ref"]), root, path)

    errors: List[str] = []
    if "anyOf" in schema:
        alternatives = [validate_schema_value(value, child, root, path) for child in schema["anyOf"]]
        if all(alternative for alternative in alternatives):
            errors.append(f"{path} 不满足 anyOf 中的任一分支")
        return errors

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(json_type_matches(value, expected) for expected in expected_types):
            errors.append(f"{path} 类型应为 {'|'.join(expected_types)}")
            return errors

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} 必须等于 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} 不在允许枚举中")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key} 缺失")
        properties = schema.get("properties", {})
        for key, child in properties.items():
            if key in value:
                errors.extend(validate_schema_value(value[key], child, root, f"{path}.{key}"))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key} 是未允许字段")
        elif isinstance(additional, dict):
            for key in value:
                if key not in properties:
                    errors.extend(validate_schema_value(value[key], additional, root, f"{path}.{key}"))

    if isinstance(value, list):
        if schema.get("uniqueItems"):
            encoded = [canonical_json(item) for item in value]
            if len(set(encoded)) != len(encoded):
                errors.append(f"{path} 包含重复项")
        if isinstance(schema.get("items"), dict):
            for index, child in enumerate(value):
                errors.extend(validate_schema_value(child, schema["items"], root, f"{path}[{index}]"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path} 长度小于 {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path} 长度大于 {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path} 不匹配指定格式")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path} 不是 ISO 8601 date-time")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} 小于最小值 {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} 大于最大值 {schema['maximum']}")

    for child in schema.get("allOf", []):
        errors.extend(validate_schema_value(value, child, root, path))
    if "if" in schema and not validate_schema_value(value, schema["if"], root, path):
        if "then" in schema:
            errors.extend(validate_schema_value(value, schema["then"], root, path))
    return errors


def validate_with_schema(task: Path, schema_name: str, value: Any, label: str) -> List[str]:
    schema = read_json(task / "schemas" / schema_name)
    return [f"{label}: {message}" for message in validate_schema_value(value, schema)]


def normalize_sensitive_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def sensitive_paths(value: Any, prefix: str = "$") -> List[str]:
    """递归扫描 key；只返回 key 路径，绝不把可疑值写到错误输出。"""

    findings: List[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = normalize_sensitive_key(str(key))
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                findings.append(f"{prefix}.{key}")
            findings.extend(sensitive_paths(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(sensitive_paths(child, f"{prefix}[{index}]"))
    return findings


def slugify(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "task"


def validate_task_key(task_key: str) -> None:
    if task_key in RESERVED_NAMES or not TASK_KEY_RE.fullmatch(task_key):
        raise PackageError(
            "task_key 必须符合 YYYYMMDD-HHmm-<slug>，并且不能使用保留目录名"
        )


def resolve_root(raw_root: Optional[str]) -> Path:
    # 任务包与 HeriBase CLI daemon 的 ~/.heribase/task_*.json 缓存分离，避免
    # 面向用户的任务、派生索引与运行锁和 CLI 内部缓存混在同一目录。
    root = Path(raw_root).expanduser() if raw_root else Path.home() / ".heribase" / "user-tasks"
    return root.resolve()


def resolve_task(root: Path, task_key: str, must_exist: bool = True) -> Path:
    validate_task_key(task_key)
    candidate = root / task_key
    if candidate.is_symlink():
        raise PackageError("任务目录不能是符号链接")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PackageError("任务路径逃逸出 tasks 根目录") from exc
    if must_exist and (not resolved.exists() or not resolved.is_dir()):
        raise PackageError(f"任务不存在：{task_key}")
    return resolved


def safe_relative_path(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def package_files(task: Path) -> Iterable[Path]:
    """返回完整性保护范围；派生缓存、临时文件和 integrity 本身被排除。"""

    for path in sorted(task.rglob("*")):
        if path.is_dir() or path.is_symlink():
            continue
        relative = path.relative_to(task).as_posix()
        if relative == "integrity.json" or relative.startswith("derived/"):
            continue
        # Finder 会在用户浏览任务目录时自动写入这个本机展示缓存。它不属于任务
        # 数据，也不会被 CLI 消费；若计入完整性，用户只要打开目录就可能无法恢复任务。
        if Path(relative).name == ".DS_Store":
            continue
        if Path(relative).name.startswith(".") and ".tmp" in Path(relative).name:
            continue
        yield path


def file_role(relative: str) -> str:
    if relative == "README.md":
        return "documentation"
    if relative.startswith("schemas/"):
        return "schema"
    if relative.startswith("inputs/originals/") or relative.startswith("inputs/remote-images/") or relative.startswith("inputs/extracted/"):
        return "source"
    if relative.endswith(".jsonl"):
        return "log"
    if "/raw/" in relative:
        return "raw"
    if relative == "data/items.json":
        return "snapshot"
    return "metadata"


def log_identity(event: Dict[str, Any]) -> Optional[str]:
    for key in ("event_id", "decision_id", "pairing_id", "attempt_id", "operation_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def parse_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    events: List[Dict[str, Any]] = []
    errors: List[str] = []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        errors.append(f"{path.name} 最后一行被截断，需要显式恢复")
        return events, errors
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            errors.append(f"{path.name}:{line_number} 存在空行")
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"{path.name}:{line_number} 不是合法 JSON")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path.name}:{line_number} 必须是 JSON object")
            continue
        events.append(value)
    return events, errors


def event_digest(event: Dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "event_sha256"}
    return sha256_bytes(canonical_json(payload))


def collection_plan_payload_hash(plan: Dict[str, Any]) -> str:
    """计划状态和签名元数据会变化，不属于用户确认的业务 payload。"""

    payload = {
        key: value
        for key, value in plan.items()
        if key not in {"status", "payload_sha256", "authorization"}
    }
    return sha256_bytes(canonical_json(payload))


def validate_log(path: Path, task_key: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    events, errors = parse_jsonl(path)
    previous: Optional[str] = None
    for index, event in enumerate(events, start=1):
        if event.get("task_key") != task_key:
            errors.append(f"{path.name}:{index} task_key 不匹配")
        if event.get("sequence") != index:
            errors.append(f"{path.name}:{index} sequence 应为 {index}")
        if event.get("previous_event_sha256") != previous:
            errors.append(f"{path.name}:{index} previous_event_sha256 断链")
        actual = event_digest(event)
        if event.get("event_sha256") != actual:
            errors.append(f"{path.name}:{index} event_sha256 不匹配")
        previous = actual
    return errors, events


def last_log_metadata(path: Path) -> Tuple[Optional[int], Optional[str]]:
    events, errors = parse_jsonl(path)
    if errors or not events:
        return None, None
    return events[-1].get("sequence"), log_identity(events[-1])


def build_integrity(task: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    digest_lines: List[str] = []
    for path in package_files(task):
        relative = path.relative_to(task).as_posix()
        size = path.stat().st_size
        digest = sha256_file(path)
        last_sequence: Optional[int] = None
        last_event_id: Optional[str] = None
        if relative in LOG_PATHS:
            last_sequence, last_event_id = last_log_metadata(path)
        files.append(
            {
                "path": relative,
                "role": file_role(relative),
                "byte_size": size,
                "sha256": digest,
                "last_sequence": last_sequence,
                "last_event_id": last_event_id,
            }
        )
        digest_lines.append(f"{relative}\0{size}\0{digest}\n")
    return {
        "schema_version": "heribase.integrity.v1",
        "task_key": manifest["task_key"],
        "revision": manifest["revision"],
        "generated_at": utc_now(),
        "files": files,
        "package_sha256": sha256_bytes("".join(digest_lines).encode("utf-8")),
    }


def integrity_differences(task: Path, integrity: Dict[str, Any]) -> List[Dict[str, str]]:
    old = {entry["path"]: entry for entry in integrity.get("files", []) if isinstance(entry, dict) and "path" in entry}
    current = {path.relative_to(task).as_posix(): path for path in package_files(task)}
    differences: List[Dict[str, str]] = []
    for relative in sorted(set(old) | set(current)):
        if relative not in old:
            differences.append({"path": relative, "change": "added"})
        elif relative not in current:
            differences.append({"path": relative, "change": "removed"})
        else:
            path = current[relative]
            if path.stat().st_size != old[relative].get("byte_size") or sha256_file(path) != old[relative].get("sha256"):
                differences.append({"path": relative, "change": "modified"})
    return differences


def create_task(args: argparse.Namespace) -> Dict[str, Any]:
    root = resolve_root(args.root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "_catalog").mkdir(exist_ok=True)
    (root / "_runtime" / "locks").mkdir(parents=True, exist_ok=True)
    try:
        task_zone = ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError as exc:
        raise PackageError(f"未知 IANA timezone：{args.timezone}") from exc

    if args.now:
        try:
            parsed = datetime.fromisoformat(args.now)
        except ValueError as exc:
            raise PackageError("--now 必须是 ISO 8601 时间") from exc
        parsed = parsed.replace(tzinfo=task_zone) if parsed.tzinfo is None else parsed.astimezone(task_zone)
    else:
        parsed = datetime.now(task_zone)

    display_name = args.display_name
    if getattr(args, "prefix_display_name", False):
        # 仅 task-package CLI 创建入口启用前缀；工作台直接调用本函数时
        # 默认保留用户输入，避免把 skill 的命名规则扩散到其他入口。
        # 已有时间前缀保持原样，且 task_key 碰撞后缀不进入显示名称。
        if not re.match(r"^[0-9]{8}-[0-9]{4}-", display_name):
            display_name = f"{parsed.strftime('%Y%m%d-%H%M')}-{display_name}"

    slug = slugify(args.slug or args.display_name)
    base = f"{parsed.strftime('%Y%m%d-%H%M')}-{slug}"
    task_key = base
    suffix = 2
    while (root / task_key).exists():
        task_key = f"{base}-{suffix:02d}"
        suffix += 1
    task = resolve_task(root, task_key, must_exist=False)
    task.mkdir()
    for relative in REQUIRED_DIRS:
        (task / relative).mkdir(parents=True, exist_ok=True)

    schema_source = Path(__file__).resolve().parent.parent / "assets" / "schemas"
    for name in SCHEMA_FILES:
        source = schema_source / name
        if not source.is_file():
            raise PackageError(f"Skill 缺少 Schema：{name}")
        shutil.copy2(source, task / "schemas" / name)

    created_at = parsed.isoformat(timespec="seconds")
    manifest = {
        "schema_version": "heribase.task-manifest.v1",
        "task_key": task_key,
        "display_name": display_name,
        "description": args.description or "",
        "created_at": created_at,
        "created_timezone": args.timezone,
        "updated_at": created_at,
        "revision": 1,
        "dataset_revision": 1,
        "state": "received",
        "data_health": "healthy",
        "schema_versions": {
            "sources": "heribase.sources.v1",
            "items": "heribase.items.v1",
            "recognition_attempt": "heribase.recognition-attempt.v1",
            "review_decision": "heribase.review-decision.v1",
            "review_export": "heribase.review-export.v2",
            "collection_plan": "heribase.collection-plan.v1",
            "collection_operation": "heribase.collection-operation.v1",
            "audit_event": "heribase.audit-event.v1",
            "integrity": "heribase.integrity.v1",
        },
        "statistics": {
            "sources": 0,
            "items": 0,
            "identified": 0,
            "reviewed": 0,
            "collect": 0,
            "need_photo": 0,
            "excluded": 0,
            "collected": 0,
            "exceptions": 0,
        },
        "dataset_fingerprint": None,
        "created_by": {"type": "agent", "name": args.created_by},
    }
    sources = {
        "schema_version": "heribase.sources.v1",
        "task_key": task_key,
        "revision": 1,
        "updated_at": created_at,
        "sources": [],
    }
    items = {
        "schema_version": "heribase.items.v1",
        "task_key": task_key,
        "revision": 1,
        "updated_at": created_at,
        "items": [],
    }
    manifest["dataset_fingerprint"] = dataset_fingerprint(sources["sources"], items["items"])
    write_json_atomic(task / "manifest.json", manifest)
    write_json_atomic(task / "inputs" / "sources.json", sources)
    write_json_atomic(task / "data" / "items.json", items)
    readme = (
        f"# {display_name}\n\n"
        f"- task_key: `{task_key}`\n"
        f"- created_at: `{created_at}`\n"
        f"- schema: `heribase.task-manifest.v1`\n\n"
        "该目录是自包含的 HeriBase 任务包。`derived/` 可重建；输入原件、raw 响应和 JSONL 历史不可修改。\n"
    )
    write_text_atomic(task / "README.md", readme)
    for relative in LOG_PATHS:
        if relative.startswith("pairing/"):
            (task / "pairing" / "exports").mkdir(parents=True, exist_ok=True)
        (task / relative).touch(exist_ok=False)
    write_json_atomic(task / "integrity.json", build_integrity(task, manifest))
    return {"ok": True, "task_key": task_key, "task_path": str(task), "revision": 1}


def validate_package_structure(task: Path, task_key: str, check_integrity: bool = True) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    for relative in REQUIRED_FILES:
        if not (task / relative).is_file():
            errors.append(f"缺少文件：{relative}")
    for relative in REQUIRED_DIRS:
        if not (task / relative).is_dir():
            errors.append(f"缺少目录：{relative}")
    for name in SCHEMA_FILES:
        if name.startswith("pairing-") and not (task / "pairing" / "decisions.jsonl").is_file():
            continue
        if not (task / "schemas" / name).is_file():
            errors.append(f"缺少 Schema：schemas/{name}")
    for path in task.rglob("*"):
        if path.is_symlink():
            errors.append(f"不允许符号链接：{path.relative_to(task).as_posix()}")

    if errors:
        return {"ok": False, "task_key": task_key, "data_health": "inconsistent", "online_writes_allowed": False, "errors": errors, "warnings": warnings}

    manifest = read_json(task / "manifest.json")
    sources_doc = read_json(task / "inputs" / "sources.json")
    items_doc = read_json(task / "data" / "items.json")
    errors.extend(validate_with_schema(task, "manifest.schema.json", manifest, "manifest.json"))
    errors.extend(validate_with_schema(task, "sources.schema.json", sources_doc, "inputs/sources.json"))
    errors.extend(validate_with_schema(task, "items.schema.json", items_doc, "data/items.json"))
    if manifest.get("schema_version") != "heribase.task-manifest.v1":
        errors.append("manifest schema_version 不正确")
    if manifest.get("task_key") != task_key:
        errors.append("manifest.task_key 与目录名不匹配")
    revisions = {manifest.get("revision"), sources_doc.get("revision"), items_doc.get("revision")}
    if len(revisions) != 1:
        errors.append("manifest、sources、items revision 不一致")
    expected_fingerprint = dataset_fingerprint(
        sources_doc.get("sources", []), items_doc.get("items", [])
    )
    if manifest.get("dataset_fingerprint") != expected_fingerprint:
        errors.append("manifest.dataset_fingerprint 与当前 sources/items 不匹配")
    for name, document, expected in (
        ("sources", sources_doc, "heribase.sources.v1"),
        ("items", items_doc, "heribase.items.v1"),
    ):
        if document.get("schema_version") != expected:
            errors.append(f"{name} schema_version 不正确")
        if document.get("task_key") != task_key:
            errors.append(f"{name}.task_key 不匹配")

    source_ids: Set[str] = set()
    stored_source_paths: Set[str] = set()
    for source in sources_doc.get("sources", []):
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append("source_id 缺失")
            continue
        if source_id in source_ids:
            errors.append(f"source_id 重复：{source_id}")
        source_ids.add(source_id)
        stored_path = source.get("stored_path")
        if not isinstance(stored_path, str) or not safe_relative_path(stored_path):
            errors.append(f"source {source_id} 的 stored_path 不安全")
            continue
        stored = task / stored_path
        stored_source_paths.add(stored_path)
        if stored.is_symlink() or not stored.is_file():
            errors.append(f"source {source_id} 的本地副本不存在")
        else:
            if stored.stat().st_size != source.get("byte_size") or sha256_file(stored) != source.get("sha256"):
                errors.append(f"source {source_id} 的大小或 SHA-256 不匹配")

    for prefix in (
        "inputs/originals/",
        "inputs/remote-images/",
        "inputs/extracted/",
    ):
        source_root = task / prefix
        if source_root.exists():
            for stored in source_root.rglob("*"):
                if stored.is_file() and not stored.is_symlink():
                    # 与完整性范围保持一致，忽略 Finder 生成的目录展示缓存。
                    if stored.name == ".DS_Store":
                        continue
                    relative = stored.relative_to(task).as_posix()
                    if relative not in stored_source_paths:
                        errors.append(f"存在未登记输入文件：{relative}")

    log_events: Dict[str, List[Dict[str, Any]]] = {}
    referenced_raw: Set[str] = set()
    log_schemas = {
        "recognition/attempts.jsonl": "recognition-attempt.schema.json",
        "review/decisions.jsonl": "review-decision.schema.json",
        "pairing/decisions.jsonl": "pairing-decision.schema.json",
        "collection/attempts.jsonl": "collection-operation.schema.json",
        "audit/events.jsonl": "audit-event.schema.json",
    }
    for relative in sorted(LOG_PATHS):
        # 配对日志是 v2 任务的可选扩展；缺失表示可恢复的旧任务，不能使其失效。
        if relative.startswith("pairing/") and not (task / relative).is_file():
            continue
        log_errors, events = validate_log(task / relative, task_key)
        errors.extend(f"{relative}: {message}" for message in log_errors)
        log_events[relative] = events
        for event_index, event in enumerate(events, start=1):
            errors.extend(
                validate_with_schema(
                    task,
                    log_schemas[relative],
                    event,
                    f"{relative}:{event_index}",
                )
            )
            reference = event.get("raw_response_ref")
            if isinstance(reference, str):
                referenced_raw.add(reference)
            if relative == "collection/attempts.jsonl" and event.get("status") == "succeeded":
                result = event.get("result") or {}
                if not result.get("collection_uri"):
                    errors.append(f"collection succeeded 缺少 collection_uri：{event.get('attempt_id')}")

    local_ids: Set[str] = set()
    items_by_id: Dict[str, Dict[str, Any]] = {}
    verified_entities: Dict[str, List[str]] = {}
    item_versions: Dict[str, int] = {}
    for item in items_doc.get("items", []):
        item_key = item.get("item_key")
        local_id = item.get("local_id")
        expected_local_id = f"{task_key}:{item_key}"
        if local_id != expected_local_id:
            errors.append(f"local_id 不符合 task_key:item_key：{local_id}")
        if local_id in local_ids:
            errors.append(f"local_id 重复：{local_id}")
        local_ids.add(local_id)
        if isinstance(local_id, str):
            items_by_id[local_id] = item
        if isinstance(local_id, str) and isinstance(item.get("version"), int):
            item_versions[local_id] = item["version"]
        for source_ref in item.get("source_refs", []):
            if source_ref not in source_ids:
                errors.append(f"item {local_id} 引用了不存在的 source：{source_ref}")
        for evidence in item.get("evidence", []):
            if evidence.get("source_id") not in source_ids:
                errors.append(f"item {local_id} 的 evidence 引用了不存在的 source")
        identification = item.get("active_identification")
        if isinstance(identification, dict):
            for field in ("identify_uri", "user_uniq_uri"):
                if identification.get(field) == "":
                    errors.append(f"item {local_id} 的 {field} 不能是空字符串")
            raw_ref = identification.get("raw_response_ref")
            raw_hash = identification.get("raw_response_sha256")
            if isinstance(raw_ref, str):
                referenced_raw.add(raw_ref)
                if not safe_relative_path(raw_ref) or not (task / raw_ref).is_file():
                    errors.append(f"item {local_id} 的识别 raw_response_ref 无效")
                elif sha256_file(task / raw_ref) != raw_hash:
                    errors.append(f"item {local_id} 的识别 raw SHA-256 不匹配")
            user_uri = identification.get("user_uniq_uri")
            if item.get("status") in ACTIVE_ITEM_STATUSES and isinstance(user_uri, str) and user_uri:
                verified_entities.setdefault(user_uri, []).append(local_id)
        collection = item.get("collection_projection")
        if isinstance(collection, dict):
            for field in ("collection_uri", "user_uniq_uri"):
                if collection.get(field) == "":
                    errors.append(f"item {local_id} 的 collection_projection.{field} 不能是空字符串")
            raw_ref = collection.get("raw_response_ref")
            if isinstance(raw_ref, str):
                referenced_raw.add(raw_ref)

    for user_uri, members in verified_entities.items():
        if len(members) > 1:
            errors.append(f"同一任务存在 user_uniq_uri 冲突：{user_uri} -> {', '.join(members)}")

    for relative, events in log_events.items():
        for event in events:
            local_id = event.get("local_id")
            if isinstance(local_id, str) and local_id not in local_ids:
                errors.append(f"{relative} 引用了不存在的 local_id：{local_id}")

    # 日志是历史事实，快照是当前投影。两者脱节时必须恢复，不能继续线上写入。
    latest_review: Dict[str, Dict[str, Any]] = {}
    latest_identification: Dict[str, Dict[str, Any]] = {}
    latest_collection: Dict[str, Dict[str, Any]] = {}
    for event in log_events.get("review/decisions.jsonl", []):
        if isinstance(event.get("local_id"), str):
            latest_review[event["local_id"]] = event
    for event in log_events.get("recognition/attempts.jsonl", []):
        if event.get("status") == "succeeded" and isinstance(event.get("local_id"), str):
            latest_identification[event["local_id"]] = event
    for event in log_events.get("collection/attempts.jsonl", []):
        if event.get("status") == "succeeded" and isinstance(event.get("local_id"), str):
            latest_collection[event["local_id"]] = event
    for local_id, event in latest_review.items():
        projection = (items_by_id.get(local_id) or {}).get("review_projection") or {}
        if projection.get("decision_id") != event.get("decision_id"):
            errors.append(f"review 日志尚未投影到 items 快照：{local_id}")
    for local_id, event in latest_identification.items():
        item = items_by_id.get(local_id) or {}
        projection = item.get("active_identification") or {}
        conflicts = (item.get("field_claims") or {}).get("identity_conflicts", [])
        conflict_recorded = item.get("status") == "identity_conflict" and any(
            isinstance(conflict, dict) and conflict.get("attempt_id") == event.get("attempt_id")
            for conflict in conflicts
        )
        if projection.get("attempt_id") != event.get("attempt_id") and not conflict_recorded:
            errors.append(f"recognition 日志尚未投影到 items 快照：{local_id}")
    for local_id, event in latest_collection.items():
        projection = (items_by_id.get(local_id) or {}).get("collection_projection") or {}
        if projection.get("operation_id") != event.get("operation_id"):
            errors.append(f"collection 日志尚未投影到 items 快照：{local_id}")

    raw_paths: Set[str] = set()
    for raw_dir in (task / "recognition" / "raw", task / "collection" / "raw"):
        for raw_file in raw_dir.glob("*.json"):
            relative = raw_file.relative_to(task).as_posix()
            raw_paths.add(relative)
            raw_value = read_json(raw_file)
            if not isinstance(raw_value, dict):
                errors.append(f"raw 响应必须是 JSON object：{relative}")
            findings = sensitive_paths(raw_value)
            if findings:
                errors.append(f"raw 响应含敏感字段，必须隔离：{relative}（{', '.join(findings)}）")
    for orphan in sorted(raw_paths - referenced_raw):
        errors.append(f"存在未挂接 raw 响应：{orphan}")
    for missing in sorted(referenced_raw - raw_paths):
        errors.append(f"引用的 raw 响应不存在：{missing}")

    plan_path = task / "collection" / "plan.json"
    plan_status: Optional[str] = None
    plan_authorized = False
    if plan_path.exists():
        plan = read_json(plan_path)
        errors.extend(validate_with_schema(task, "collection-plan.schema.json", plan, "collection/plan.json"))
        plan_status = plan.get("status")
        if plan.get("task_key") != task_key:
            errors.append("collection plan 的 task_key 不匹配")
        if plan.get("based_on", {}).get("dataset_revision") != manifest.get("dataset_revision") or plan.get("based_on", {}).get("dataset_fingerprint") != manifest.get("dataset_fingerprint"):
            warnings.append("collection plan 已过期")
        planned_items = plan.get("items", [])
        if plan_status in {"authorized", "executing"} and not planned_items:
            warnings.append("collection plan 没有可执行条目")
        for planned in planned_items:
            local_id = planned.get("local_id")
            current_item = items_by_id.get(local_id)
            if current_item is None:
                warnings.append(f"collection plan item 不存在：{local_id}")
                continue
            operation_type = planned.get("operation_type") or plan.get("operation_type")
            collection = current_item.get("collection_projection") or {}
            # 与执行器保持同一语义：执行中计划里已经成功归档的条目会改变
            # item version，但不应阻止原确认范围中的剩余条目继续执行。
            completed_status = "cancelled" if operation_type == "collection_cancel" else "succeeded"
            if plan_status == "executing" and collection.get("status") == completed_status:
                continue
            if item_versions.get(local_id) != planned.get("item_version"):
                warnings.append(f"collection plan item 已过期：{local_id}")
            if operation_type == "collection_add":
                review = current_item.get("review_projection") or {}
                if review.get("decision_id") != planned.get("decision_id") or review.get("decision") != "collect" or review.get("stale") is True:
                    warnings.append(f"collection plan 的人工决定无效或已变化：{local_id}")
            else:
                collection = current_item.get("collection_projection") or {}
                if not planned.get("collection_uri") or collection.get("collection_uri") != planned.get("collection_uri"):
                    warnings.append(f"collection plan 的 collection_uri 无效或已变化：{local_id}")
            identification = current_item.get("active_identification") or {}
            if identification.get("snapshot_id") != planned.get("identification_snapshot_id"):
                warnings.append(f"collection plan 的识别快照已变化：{local_id}")
            for field in ("identify_uri", "user_uniq_uri"):
                if identification.get(field) != planned.get(field):
                    warnings.append(f"collection plan 的 {field} 已变化：{local_id}")
            if plan.get("operation_type") in {"collection_add", "mixed"} and not planned.get("identify_uri"):
                warnings.append(f"collection add 缺少 identify_uri：{local_id}")
        calculated_payload = collection_plan_payload_hash(plan)
        if plan.get("payload_sha256") != calculated_payload:
            errors.append("collection plan payload_sha256 不匹配")
        authorization = plan.get("authorization")
        if plan_status == "authorized" and isinstance(authorization, dict):
            plan_authorized = authorization.get("confirmed_payload_sha256") == calculated_payload
            if not plan_authorized:
                errors.append("collection plan 授权摘要不匹配")

    if check_integrity:
        integrity = read_json(task / "integrity.json")
        errors.extend(validate_with_schema(task, "integrity.schema.json", integrity, "integrity.json"))
        if integrity.get("task_key") != task_key or integrity.get("revision") != manifest.get("revision"):
            errors.append("integrity 的 task_key 或 revision 不匹配")
        differences = integrity_differences(task, integrity)
        for difference in differences:
            errors.append(f"integrity 不匹配：{difference['change']} {difference['path']}")
        rebuilt = build_integrity(task, manifest)
        if not differences and integrity.get("package_sha256") != rebuilt.get("package_sha256"):
            errors.append("integrity package_sha256 不匹配")

    data_health = "inconsistent" if errors else manifest.get("data_health", "healthy")
    online_writes_allowed = (
        not errors
        and not warnings
        and data_health == "healthy"
        and plan_status == "authorized"
        and plan_authorized
    )
    return {
        "ok": not errors,
        "task_key": task_key,
        "data_health": data_health,
        "online_writes_allowed": online_writes_allowed,
        "plan_status": plan_status,
        "statistics": manifest.get("statistics", {}),
        "errors": errors,
        "warnings": warnings,
    }


def validate_task(args: argparse.Namespace) -> Dict[str, Any]:
    root = resolve_root(args.root)
    task = resolve_task(root, args.task_key)
    return validate_package_structure(task, args.task_key, check_integrity=True)


def refresh_integrity(args: argparse.Namespace) -> Dict[str, Any]:
    root = resolve_root(args.root)
    task = resolve_task(root, args.task_key)
    manifest = read_json(task / "manifest.json")
    if manifest.get("task_key") != args.task_key:
        raise PackageError("manifest.task_key 与目录名不匹配")
    if args.expected_revision is not None and manifest.get("revision") != args.expected_revision:
        raise PackageError("任务 revision 已变化，拒绝刷新完整性")

    old_integrity = read_json(task / "integrity.json") if (task / "integrity.json").exists() else None
    differences = integrity_differences(task, old_integrity) if old_integrity else []
    if differences and not args.accept_controlled_changes:
        raise PackageError("检测到文件变化；先核验变更，再使用 --accept-controlled-changes")
    if differences and old_integrity:
        old_revision = old_integrity.get("revision")
        new_revision = manifest.get("revision")
        stateful_changes = [change for change in differences if change["path"] != "README.md"]
        if stateful_changes and (
            not isinstance(old_revision, int)
            or not isinstance(new_revision, int)
            or new_revision <= old_revision
        ):
            raise PackageError("受控数据变更必须递增 manifest/sources/items revision")
    immutable_changes = [
        change
        for change in differences
        if any(change["path"].startswith(prefix) for prefix in IMMUTABLE_PREFIXES)
        and (
            change["change"] in {"modified", "removed"}
            or change["path"].startswith("schemas/")
        )
    ]
    if immutable_changes:
        summary = ", ".join(f"{entry['change']} {entry['path']}" for entry in immutable_changes)
        raise PackageError(f"不可变文件发生变化，拒绝重设完整性基线：{summary}")

    old_entries = {
        entry.get("path"): entry
        for entry in (old_integrity or {}).get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    for change in differences:
        relative = change["path"]
        if relative not in LOG_PATHS:
            continue
        if change["change"] != "modified":
            raise PackageError(f"append-only 日志不能被新增或删除：{relative}")
        old_entry = old_entries[relative]
        current_path = task / relative
        old_size = old_entry.get("byte_size")
        if not isinstance(old_size, int) or current_path.stat().st_size < old_size:
            raise PackageError(f"append-only 日志被截短：{relative}")
        if sha256_file_prefix(current_path, old_size) != old_entry.get("sha256"):
            raise PackageError(f"append-only 日志历史内容被重写：{relative}")

    structural = validate_package_structure(task, args.task_key, check_integrity=False)
    if not structural["ok"]:
        raise PackageError("结构校验失败，拒绝刷新完整性：" + "; ".join(structural["errors"][:5]))
    write_json_atomic(task / "integrity.json", build_integrity(task, manifest))
    return {
        "ok": True,
        "task_key": args.task_key,
        "revision": manifest.get("revision"),
        "accepted_changes": differences,
    }


def rebuild_catalog(args: argparse.Namespace) -> Dict[str, Any]:
    root = resolve_root(args.root)
    root.mkdir(parents=True, exist_ok=True)
    catalog_dir = root / "_catalog"
    catalog_dir.mkdir(exist_ok=True)
    tasks: List[Dict[str, Any]] = []
    entities: Dict[str, List[Dict[str, Any]]] = {}
    collection_owners: Dict[str, Set[str]] = {}
    conflicts: List[Dict[str, Any]] = []

    for task_dir in sorted(root.iterdir()):
        if not task_dir.is_dir() or task_dir.name in RESERVED_NAMES or not TASK_KEY_RE.fullmatch(task_dir.name):
            continue
        result = validate_package_structure(task_dir, task_dir.name, check_integrity=True)
        manifest = read_json(task_dir / "manifest.json") if (task_dir / "manifest.json").is_file() else {}
        tasks.append(
            {
                "task_key": task_dir.name,
                "display_name": manifest.get("display_name", task_dir.name),
                "state": manifest.get("state", "data_inconsistent"),
                "data_health": result["data_health"],
                "revision": manifest.get("revision"),
                "updated_at": manifest.get("updated_at"),
                "trusted": result["ok"],
            }
        )
        if not result["ok"]:
            continue
        items_doc = read_json(task_dir / "data" / "items.json")
        for item in items_doc.get("items", []):
            identification = item.get("active_identification") or {}
            user_uri = identification.get("user_uniq_uri")
            if not isinstance(user_uri, str) or not user_uri:
                continue
            collection = item.get("collection_projection") or {}
            collection_uri = collection.get("collection_uri")
            member = {
                "task_key": task_dir.name,
                "local_id": item.get("local_id"),
                "collection_uri": collection_uri,
                "status": item.get("status"),
                "updated_at": item.get("updated_at"),
            }
            entities.setdefault(user_uri, []).append(member)
            if isinstance(collection_uri, str) and collection_uri:
                collection_owners.setdefault(collection_uri, set()).add(user_uri)

    for collection_uri, owners in sorted(collection_owners.items()):
        if len(owners) > 1:
            conflicts.append({"type": "collection_identity_conflict", "collection_uri": collection_uri, "user_uniq_uris": sorted(owners)})

    generated_at = utc_now()
    tasks_doc = {"schema_version": "heribase.task-catalog.v1", "generated_at": generated_at, "tasks": tasks}
    entities_doc = {
        "schema_version": "heribase.entity-catalog.v1",
        "generated_at": generated_at,
        "entities": [
            {"user_uniq_uri": uri, "members": sorted(members, key=lambda value: (value["task_key"], value.get("local_id") or ""))}
            for uri, members in sorted(entities.items())
        ],
        "conflicts": conflicts,
    }
    write_json_atomic(catalog_dir / "tasks.json", tasks_doc)
    write_json_atomic(catalog_dir / "entities.json", entities_doc)
    return {"ok": not conflicts, "task_count": len(tasks), "entity_count": len(entities), "conflicts": conflicts, "catalog_path": str(catalog_dir)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HeriBase 任务包工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="创建自包含任务包骨架")
    create.add_argument("--root", help="测试/隔离任务根目录；生产环境省略")
    create.add_argument("--display-name", required=True)
    create.add_argument("--slug")
    create.add_argument("--description")
    create.add_argument("--timezone", default="Asia/Shanghai")
    create.add_argument("--created-by", default="Codex")
    create.add_argument("--now", help="测试用 ISO 8601 时间")
    # CLI 命令是 heribase-task-package skill 的创建入口；通过 API 直接复用
    # create_task() 的其他调用方不设置此标志，因此维持既有 display_name。
    create.set_defaults(handler=create_task, prefix_display_name=True)

    validate = subparsers.add_parser("validate", help="校验任务结构、日志、身份与完整性")
    validate.add_argument("--root", help="测试/隔离任务根目录；生产环境省略")
    validate.add_argument("--task-key", required=True)
    validate.set_defaults(handler=validate_task)

    refresh = subparsers.add_parser("refresh-integrity", help="在受控变更后刷新完整性")
    refresh.add_argument("--root", help="测试/隔离任务根目录；生产环境省略")
    refresh.add_argument("--task-key", required=True)
    refresh.add_argument("--expected-revision", type=int)
    refresh.add_argument("--accept-controlled-changes", action="store_true")
    refresh.set_defaults(handler=refresh_integrity)

    catalog = subparsers.add_parser("rebuild-catalog", help="从有效任务重建全局目录")
    catalog.add_argument("--root", help="测试/隔离任务根目录；生产环境省略")
    catalog.set_defaults(handler=rebuild_catalog)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
    except PackageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
