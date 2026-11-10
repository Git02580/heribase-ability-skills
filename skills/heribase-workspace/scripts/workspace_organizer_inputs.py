"""Read archived inputs without executing spreadsheet formulas, documents, or embedded instructions."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

from workspace_tasks import operations


def prepare_inputs(tasks, current, sources, directory):
    from PIL import Image, ImageOps
    catalog, images, documents = [], [], []
    hints = []
    analyzer = Path(__file__).resolve().parents[2] / "heribase-collection/scripts/analyze_image_metadata.py"
    try:
        subprocess.run([sys.executable, "-B", str(analyzer), "--root", str(tasks.root), "--task-key", current["manifest"]["task_key"]],
                       capture_output=True, timeout=30, check=True)
        hints = json.loads((tasks.resolve(current["manifest"]["task_key"]) / "derived/image-metadata-analysis.json").read_text())["candidate_pairs"]
    except (OSError, ValueError, subprocess.SubprocessError, KeyError):
        pass  # optional metadata never substitutes for pixels or blocks visual analysis

    def picture(source_id, path, **metadata):
        try:
            with Image.open(path) as original:
                image = ImageOps.exif_transpose(original).convert("RGB")
                # Coordinates remain in original orientation. Do not transform a rotated source for crop inference.
                if original.getexif().get(274, 1) != 1:
                    image = original.convert("RGB")
                size = image.size
                image.thumbnail((2000, 2000))
                image.info.clear()
                rendered = directory / f"image-{len(catalog)}.jpg"
                image.save(rendered, "JPEG", quality=94)
            catalog.append({"sourceId": source_id, "width": size[0], "height": size[1],
                            "metadataHints": [entry for entry in hints if source_id in entry["source_ids"]], **metadata})
            images.append(rendered)
            return True
        except (OSError, ValueError):
            return False

    def document(source_id, title, summary, **metadata):
        documents.append({"title": title[:200], "kind": "document", "summary": summary, "confidence": 0,
                          "supportingSignals": [], "conflicts": [], "parts": [{"sourceId": source_id, "role": "unknown", "roleConfidence": 0, "bounds": [0, 0, 1000, 1000]}], **metadata})

    def table_row(parent, sheet, row, fields, attachments):
        identity = parent["source_id"] + ":" + sheet + ":" + str(row)
        row_key = hashlib.sha256(identity.encode()).hexdigest()[:20]
        table = {"source_table": parent["source_id"], "source_sheet": sheet, "source_rows": [row]}
        fields = {str(key)[:200]: str(value)[:3000] for key, value in fields.items()}
        failures = []
        available = []
        for attachment_index, attachment in enumerate(attachments):
            role, content, suffix, error, *origin = attachment
            if error:
                failures.append(error)
                continue
            source_id = "source-table-" + hashlib.sha256((identity + str(attachment_index) + role + hashlib.sha256(content).hexdigest()).encode()).hexdigest()[:20]
            path = directory / (source_id + suffix)
            path.write_bytes(content)
            metadata = {"rowKey": row_key, "table": table, "sourceFields": fields, "declaredRole": role, "parentSourceId": parent["source_id"],
                        "pendingPath": str(path), "kind": "remote_image" if origin else "extracted_image", "originUrl": origin[0] if origin else None,
                        "locator": {"sheet": sheet, "row": row}, "mimeType": "image/" + ("png" if suffix == ".png" else "jpeg")}
            if picture(source_id, path, **metadata):
                available.append(source_id)
            else:
                failures.append("表格图片不可读取")
        if failures:
            for entry in catalog:
                if entry.get("rowKey") == row_key:
                    entry["acquisitionWarnings"] = failures
        if not available:
            source_id = "source-row-" + row_key
            path = directory / (source_id + ".txt")
            path.write_text(json.dumps({"sheet": sheet, "row": row, "fields": fields}, ensure_ascii=False), encoding="utf-8")
            title = next((value for key, value in fields.items() if key.lower() in {"name", "title", "名称", "币名", "钱币名称"} and value), f"{sheet} 第 {row} 行")
            document(source_id, title, "表格字段已保留；" + ("；".join(failures) if failures else "未找到可读取的正反面图片，请补充照片。"),
                     kind="coin", table=table, sourceFields=fields, pendingSource={"sourceId": source_id, "pendingPath": str(path), "parentSourceId": parent["source_id"],
                     "kind": "document", "mimeType": "text/plain", "locator": {"sheet": sheet, "row": row}})

    def links(fields):
        found = []
        aliases = {"obverse": {"obverse", "front", "frontimage", "frontimg", "obverseurl", "正面", "正面图片", "正面图片url", "正面url"},
                   "reverse": {"reverse", "back", "backimage", "backimg", "reverseurl", "反面", "反面图片", "反面图片url", "反面url"}}
        for role, names in aliases.items():
            value = next((str(value).strip() for key, value in fields.items() if str(key).lower().replace("_", "").replace(" ", "") in names), "")
            if not value:
                continue
            if not value.lower().startswith(("https://", "http://")):
                found.append((role, b"", ".png", f"{role} 列没有有效图片 URL"))
                continue
            try:
                content, _ = operations.remote_image_bytes(value)
                found.append((role, content, ".png" if content.startswith(b"\x89PNG") else ".jpg", None, value))
            except Exception:
                found.append((role, b"", ".png", f"{role} 图片下载未成功，请补充照片"))
        return found

    for source in sources:
        path, _ = tasks.source_path(current["manifest"]["task_key"], source["source_id"])
        source_id = source["source_id"]
        if source["mime_type"].startswith("image/"):
            if not picture(source_id, path):
                document(source_id, "图片需要重新提供", "原件已保存，但当前图片格式无法读取，请补充 PNG 或 JPEG 图片。")
            continue
        suffix = path.suffix.lower()
        if suffix in {".csv", ".xlsx"}:
            try:
                if suffix == ".csv":
                    content = path.read_bytes()
                    try:
                        text = content.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        text = content.decode("gb18030")
                    reader = csv.DictReader(io.StringIO(text))
                    count = 0
                    for row, fields in enumerate(reader, 2):
                        if not any(fields.values()):
                            continue
                        if row > 5001:
                            raise ValueError("表格超过5000行")
                        table_row(source, "CSV", row, fields, links(fields))
                        count += 1
                    if not count:
                        document(source_id, "空表格", "未找到数据行，请检查表头和资料内容。")
                else:
                    import openpyxl
                    book = openpyxl.load_workbook(path, data_only=True)
                    for sheet in book:
                        if sheet.max_row > 5001:
                            raise ValueError("工作表超过5000行")
                        rows = sheet.iter_rows(values_only=True)
                        headers = [str(value) if value is not None else f"列{index + 1}" for index, value in enumerate(next(rows, []))]
                        embedded = {}
                        for image in sheet._images:
                            marker = image.anchor._from
                            embedded.setdefault(marker.row + 1, []).append(("unknown", image._data(), "." + image.format, None))
                        for row, values in enumerate(rows, 2):
                            fields = dict(zip(headers, ["" if value is None else str(value) for value in values]))
                            if any(fields.values()) or row in embedded:
                                table_row(source, sheet.title, row, fields, links(fields) + embedded.get(row, []))
                    book.close()
            except Exception:
                document(source_id, "表格需要核对", "表格未能完整解析，原件保留；请检查文件格式及工作表大小。")
            continue
        # Document pages become genuine archived image sources before being offered as coin evidence.
        if suffix == ".pdf":
            try:
                import fitz
                with fitz.open(path) as pdf:
                    for index, page in enumerate(pdf):
                        rendered = directory / f"pdf-{source_id}-{index + 1}.png"
                        page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(rendered)
                        derived = "source-pdf-" + hashlib.sha256((source["sha256"] + str(index)).encode()).hexdigest()[:20]
                        picture(derived, rendered, parentSourceId=source_id, pendingPath=str(rendered), kind="extracted_image", mimeType="image/png", locator={"row": index + 1})
                continue
            except (ImportError, OSError, ValueError):
                pass
        document(source_id, source["origin"].get("original_name") or "文档资料", "文档原件已保留。请补充钱币照片，或核对文档中的图片来源后继续。")
    return catalog, images, documents
