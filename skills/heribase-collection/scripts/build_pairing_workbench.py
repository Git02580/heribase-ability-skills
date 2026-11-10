#!/usr/bin/env python3
"""从任务包生成识别前的照片配对确认审核台。"""
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


def needs_review(item: Dict[str, Any]) -> bool:
    organization = item.get("organization") or {}
    confidence = organization.get("pair_confidence")
    flags = {str(flag) for flag in item.get("attention_flags", [])}
    # 已导入的人工确认优先于历史的低/中置信自动建议；但来源缺失仍必须重新处理。
    if item.get("status") == "source_incomplete" or "source_incomplete" in flags:
        return True
    evidence_sources = {value.get("source_id") for value in item.get("evidence", []) if value.get("is_primary")}
    direct_roles = {value.get("role") for value in item.get("evidence", []) if value.get("is_primary")}
    assigned_roles = {value.get("role") for value in organization.get("source_assignment", []) if value.get("source_id") in evidence_sources}
    # “同一枚”与“知道哪张是正面”是两项独立事实；后者缺失时不能调用双面识别。
    if organization.get("pairing_state") == "confirmed" and not {"obverse", "reverse"}.issubset(direct_roles | assigned_roles):
        return True
    if organization.get("pairing_state") == "confirmed" or organization.get("pairing") == "table_row_complete":
        return False
    if isinstance(confidence, (int, float)) and confidence < 0.85:
        return True
    if confidence in {"low", "medium"} or "pairing_needs_confirmation" in flags:
        return True
    return any("conflict" in flag or "缺面" in flag for flag in flags)


def slab_label_clue(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把任务包中的盒标来源声明投影为审核台线索，不混入服务端识别身份。"""

    claim = (item.get("field_claims") or {}).get("slab_label_analysis")
    if not isinstance(claim, dict):
        return None
    raw_fields = claim.get("fields")
    if not isinstance(raw_fields, dict):
        return None
    fields = []
    for name, value in raw_fields.items():
        if not isinstance(value, dict):
            continue
        fields.append({
            "name": name,
            "rawValue": value.get("raw_value"),
            "normalizedValue": value.get("normalized_value"),
            "confidence": value.get("confidence"),
            "evidenceRegion": value.get("evidence_region"),
        })
    return {
        "sourceId": claim.get("source_id"),
        "method": claim.get("method"),
        "confidence": claim.get("confidence"),
        "fields": fields,
    }


def build_workbench(args: argparse.Namespace) -> Dict[str, Any]:
    root = core.resolve_root(args.root)
    task = core.resolve_task(root, args.task_key)
    checked = core.validate_package_structure(task, args.task_key, check_integrity=True)
    if not checked["ok"]:
        raise core.PackageError("任务未通过完整性校验，拒绝生成配对审核台：" + "; ".join(checked["errors"][:5]))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.output_name):
        raise core.PackageError("output-name 只能包含小写字母、数字和连字符")
    sources = {value["source_id"]: value for value in core.read_json(task / "inputs" / "sources.json")["sources"]}
    records: List[Dict[str, Any]] = []
    output = task / "derived" / args.output_name
    output.mkdir(parents=True, exist_ok=True)
    evidence_output = output / "evidence"
    evidence_output.mkdir(exist_ok=True)
    for item in core.read_json(task / "data" / "items.json")["items"]:
        if item.get("status") in {"superseded", "archived", "excluded"}:
            continue
        evidence = []
        for value in item.get("evidence", []):
            source = sources.get(value.get("source_id"))
            if source and (task / source["stored_path"]).is_file():
                source_file = task / source["stored_path"]
                copied_name = source["source_id"] + source_file.suffix.lower()
                copied_file = evidence_output / copied_name
                # 审核台静态服务只允许访问自身目录；复制到 derived/ 保持来源原件不可变。
                if not copied_file.is_file():
                    shutil.copy2(source_file, copied_file)
                evidence.append({"sourceId": source["source_id"], "role": value.get("role", "unknown"), "image": f"evidence/{copied_name}"})
        organization = item.get("organization") or {}
        is_table = item.get("item_key", "").startswith("table-")
        acquisition = organization.get("table_image_acquisition") or {}
        records.append({
            "id": item["local_id"],
            "title": item["item_key"],
            "needsReview": needs_review(item),
            "evidence": evidence,
            "warnings": item.get("attention_flags", []),
            "confidence": organization.get("pair_confidence", "high"),
            "slabLabel": slab_label_clue(item),
            # 表格元数据让审核者能判断配对来自同一行，而不是误以为与散图自动合并。
            "sourceType": "spreadsheet" if is_table else "local_photo",
            "tableRows": organization.get("source_rows", []) if is_table else [],
            "imageStatus": {"downloaded": len(acquisition.get("succeeded_source_ids", [])), "failed": len(acquisition.get("failures", []))} if is_table else None,
        })
    counts = {"needs_review": sum(record["needsReview"] for record in records), "auto_ready": sum(not record["needsReview"] for record in records)}
    data = {"records": records, "statusCounts": counts, "requiresReview": bool(counts["needs_review"]), "buildMeta": {"taskKey": args.task_key, "datasetFingerprint": core.read_json(task / "manifest.json")["dataset_fingerprint"], "generatedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}}
    assets = Path(__file__).resolve().parent.parent / "assets" / "pairing-workbench"
    page = (assets / "index.html").read_text(encoding="utf-8")
    (output / "index.html").write_text(page.replace("</body>", '<script src="pairing-bulk.js"></script><script src="pairing-handoff.js"></script><script src="interaction.js"></script></body>'), encoding="utf-8")
    shutil.copy2(assets / "pairing-bulk.js", output / "pairing-bulk.js")
    shutil.copy2(assets / "pairing-handoff.js", output / "pairing-handoff.js")
    shutil.copy2(assets / "interaction.js", output / "interaction.js")
    (output / "pairing-data.js").write_text("window.COIN_PAIRING_DATA=" + json.dumps(data, ensure_ascii=True) + ";\n", encoding="utf-8")
    core.write_json_atomic(task / "derived" / "pairing-dataset.json", data)
    return {"ok": True, "task_key": args.task_key, "output_path": str(output), "record_count": len(records), "status_counts": counts, "requires_review": data["requiresReview"]}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成硬币配对确认审核台")
    parser.add_argument("--root")
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--output-name", default="pairing-workbench")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build_workbench(args), ensure_ascii=False, indent=2))
    except core.PackageError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
