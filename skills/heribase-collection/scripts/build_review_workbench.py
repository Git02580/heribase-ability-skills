#!/usr/bin/env python3
"""从 HeriBase 任务包稳定生成双栏硬币审核台。

输出只位于任务的 derived/，因此可随时重建，不参与任务包事实完整性。
页面使用本地证据副本，提供 WebMCP 只读交接和 JSON 导入/导出双轨。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


TASK_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "heribase-task-package" / "scripts"
sys.path.insert(0, str(TASK_PACKAGE_SCRIPTS))
import task_package as core  # noqa: E402


STATUSES = ("collect", "review", "normal", "unidentified")


def resolved_value(item: Dict[str, Any], *names: str) -> Any:
    resolved = item.get("resolved_fields") or {}
    for name in names:
        value = resolved.get(name)
        if isinstance(value, dict):
            value = value.get("value")
        if value not in (None, ""):
            return value
    return ""


def identification_display_fields(task: Path, identification: Dict[str, Any]) -> Dict[str, str]:
    """从已冻结的 CLI 识别响应读取仅供审核展示的字段。

    服务身份仍只以任务包中的 active_identification 为准；这里不把标题或价格写回
    任务事实，也不对缺失字段作推断。引用路径必须位于任务目录中，以免派生页面
    被损坏数据引向任意本地文件。
    """

    reference = identification.get("raw_response_ref")
    if not isinstance(reference, str) or not core.safe_relative_path(reference):
        return {}
    # macOS 的 /var 可能链接到 /private/var；两端都规范化后再做包含关系检查。
    task_root = task.resolve(strict=False)
    raw_path = (task_root / reference).resolve(strict=False)
    try:
        raw_path.relative_to(task_root)
    except ValueError:
        return {}
    if raw_path.is_symlink() or not raw_path.is_file():
        return {}
    try:
        raw = core.read_json(raw_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    result = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    if not isinstance(result, dict):
        return {}

    def text(*keys: str) -> str:
        for key in keys:
            value = result.get(key)
            if isinstance(value, (str, int, float)) and str(value):
                return str(value)
        return ""

    price = result.get("price")
    price_value = price.get("value") if isinstance(price, dict) else None
    return {
        "name": text("title", "name"),
        "year": text("year"),
        "mint_mark": text("mintMark", "mint_mark"),
        "grade": text("grade"),
        "value": str(price_value) if isinstance(price_value, (str, int, float)) else text("value"),
    }


def source_rows(item: Dict[str, Any], sources: Dict[str, Dict[str, Any]]) -> List[int]:
    rows = {
        locator["row"]
        for source_id in item.get("source_refs", [])
        for locator in [sources.get(source_id, {}).get("locator")]
        if isinstance(locator, dict) and isinstance(locator.get("row"), int)
    }
    return sorted(rows)


def image_paths(
    task: Path,
    output: Path,
    item: Dict[str, Any],
    sources: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    candidates: Dict[str, List[str]] = {"front": [], "back": [], "other": []}
    for evidence in item.get("evidence", []):
        source = sources.get(evidence.get("source_id"))
        if not source:
            continue
        stored = task / source["stored_path"]
        if stored.is_symlink() or not stored.is_file():
            continue
        # 审核台 HTTP 服务严格只暴露 derived/<output-name>，不能让浏览器通过
        # ../../ 回跳到任务包事实目录。因此为每张已归档证据生成审核台专属副本。
        # 文件名由稳定 source_id 派生，同一证据被多个视图引用时也只复制一次。
        suffix = stored.suffix.lower() if re.fullmatch(r"\.[a-z0-9]{1,5}", stored.suffix.lower()) else ".img"
        evidence_target = output / "evidence" / f"{source['source_id']}{suffix}"
        evidence_target.parent.mkdir(parents=True, exist_ok=True)
        if not evidence_target.is_file():
            shutil.copy2(stored, evidence_target)
        relative = evidence_target.relative_to(output).as_posix()
        role = evidence.get("role")
        bucket = "front" if role == "obverse" else "back" if role == "reverse" else "other"
        candidates[bucket].append(relative)
    front = (candidates["front"] + candidates["other"] + candidates["back"] + [""])[0]
    back_pool = candidates["back"] + [value for value in candidates["other"] if value != front]
    back = (back_pool + [""])[0]
    return {"front": front, "back": back}


def derive_status(item: Dict[str, Any]) -> str:
    organization = item.get("organization") or {}
    explicit = organization.get("review_group") or organization.get("system_status")
    if explicit in STATUSES:
        return explicit
    if item.get("status") in {"source_incomplete", "identity_conflict"}:
        return "review"
    identification = item.get("active_identification") or {}
    if identification.get("status") != "succeeded":
        return "unidentified"
    recommendation = resolved_value(item, "recommendation_group", "recommendation")
    if recommendation in {"collect", "worth_collecting", "关注", "推荐收藏"}:
        return "collect"
    if recommendation in {"review", "need_review", "需复核", "需补图"}:
        return "review"
    if item.get("attention_flags") or organization.get("warnings"):
        return "review"
    return "normal"


def record_from_item(
    task: Path,
    output: Path,
    item: Dict[str, Any],
    sources: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    identification = item.get("active_identification") or {}
    collection = item.get("collection_projection") or {}
    organization = item.get("organization") or {}
    paths = image_paths(task, output, item, sources)
    display = identification_display_fields(task, identification)
    rows = source_rows(item, sources)
    warnings = [str(value) for value in organization.get("warnings", []) if value]
    flags = [str(value) for value in item.get("attention_flags", []) if value]
    conflicts = [value for value in warnings + flags if "conflict" in value.lower() or "冲突" in value]
    system_status = derive_status(item)
    return {
        "id": item["local_id"],
        "source": "table" if item.get("item_key", "").startswith("table-") else "local",
        "sourceRows": rows,
        "displayName": resolved_value(item, "title", "name") or item["item_key"],
        "imageFront": paths["front"],
        "imageBack": paths["back"],
        "imagePairComplete": bool(paths["front"] and paths["back"]),
        "table": {
            "name": resolved_value(item, "source_name", "name", "title"),
            "series": resolved_value(item, "series"),
            "year": resolved_value(item, "source_year", "year"),
            "mintMark": resolved_value(item, "source_mint_mark", "mint_mark"),
            "grade": resolved_value(item, "source_grade", "grade"),
            "value": resolved_value(item, "source_value", "value"),
        },
        "identification": {
            "status": "success" if identification.get("status") == "succeeded" else "failed",
            "name": resolved_value(item, "identified_title") or display.get("name", "") or resolved_value(item, "title", "name"),
            "year": resolved_value(item, "identified_year") or display.get("year", "") or resolved_value(item, "year"),
            "mintMark": resolved_value(item, "identified_mint_mark") or display.get("mint_mark", "") or resolved_value(item, "mint_mark"),
            "grade": resolved_value(item, "identified_grade") or display.get("grade", "") or resolved_value(item, "grade"),
            "value": resolved_value(item, "identified_value") or display.get("value", "") or resolved_value(item, "value"),
            "confidence": resolved_value(item, "identification_confidence", "confidence"),
            "recordId": identification.get("identify_uri"),
            "identifyUri": identification.get("identify_uri"),
            "userUniqUri": identification.get("user_uniq_uri"),
            "collectionUri": collection.get("collection_uri"),
            "failureReason": "；".join(flags) if identification.get("status") != "succeeded" else "",
        },
        "reviewFlag": system_status == "review",
        "evidenceNotes": warnings + [value for value in flags if value not in conflicts],
        "conflictReasons": conflicts,
        "systemStatus": system_status,
    }


def build_review_data(task: Path, output: Path) -> Dict[str, Any]:
    manifest = core.read_json(task / "manifest.json")
    items_doc = core.read_json(task / "data" / "items.json")
    sources_doc = core.read_json(task / "inputs" / "sources.json")
    sources = {source["source_id"]: source for source in sources_doc["sources"]}
    records = [
        record_from_item(task, output, item, sources)
        for item in items_doc["items"]
        if item.get("status") not in {"superseded", "archived"}
    ]
    counts = {status: 0 for status in STATUSES}
    for record in records:
        counts[record["systemStatus"]] += 1
    return {
        "records": records,
        "statusCounts": counts,
        "buildMeta": {
            "taskKey": task.name,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "datasetFingerprint": manifest["dataset_fingerprint"],
            "datasetRevision": manifest["dataset_revision"],
            "taskRevision": manifest["revision"],
            "totalRecordCount": len(records),
        },
    }


def build_workbench(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    task = core.resolve_task(root, args.task_key)
    validation = core.validate_package_structure(task, args.task_key, check_integrity=True)
    if not validation["ok"]:
        raise core.PackageError("任务未通过完整性校验，拒绝生成审核台：" + "; ".join(validation["errors"][:5]))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.output_name):
        raise core.PackageError("output-name 只能包含小写字母、数字和连字符")
    output = task / "derived" / args.output_name
    output.mkdir(parents=True, exist_ok=True)
    assets = Path(__file__).resolve().parent.parent / "assets" / "review-workbench"
    shutil.copy2(assets / "index.html", output / "index.html")
    shutil.copy2(assets / "review-handoff.js", output / "review-handoff.js")
    data = build_review_data(task, output)
    dataset_schema = core.read_json(
        Path(__file__).resolve().parent.parent / "assets" / "schemas" / "review-dataset.schema.json"
    )
    schema_errors = core.validate_schema_value(data, dataset_schema)
    if schema_errors:
        raise core.PackageError("审核台数据不符合 Schema：" + "; ".join(schema_errors[:5]))
    script = "(function(){window.COIN_REVIEW_DATA=" + json.dumps(data, ensure_ascii=True, separators=(",", ":")) + ";}());\n"
    with (output / "review-data.js").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(script)
    core.write_json_atomic(task / "derived" / "review-dataset.json", data)
    return {
        "ok": True,
        "task_key": args.task_key,
        "output_path": str(output),
        "index_path": str(output / "index.html"),
        "record_count": len(data["records"]),
        "status_counts": data["statusCounts"],
        "dataset_fingerprint": data["buildMeta"]["datasetFingerprint"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 HeriBase 任务包生成硬币审核台")
    parser.add_argument("--root", help="测试/隔离任务根目录；生产环境省略")
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--output-name", default="review-workbench")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_workbench(args)
    except core.PackageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
