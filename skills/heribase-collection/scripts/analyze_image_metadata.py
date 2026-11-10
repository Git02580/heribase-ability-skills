#!/usr/bin/env python3
"""本地提取图片尺寸与有限 EXIF 线索，辅助发现值得人工复核的配对候选。"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

TASK_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "heribase-task-package" / "scripts"
sys.path.insert(0, str(TASK_PACKAGE_SCRIPTS))
import task_package as core  # noqa: E402


def _text(value: Any) -> Optional[str]:
    """清理 EXIF 字符串，拒绝空值并避免把任意对象写进报告。"""
    if value is None:
        return None
    result = str(value).replace("\x00", " ").strip()
    return result or None


def _rational(value: Any) -> Optional[float]:
    try:
        numerator, denominator = value
        denominator = float(denominator)
        return float(numerator) / denominator if denominator else None
    except (TypeError, ValueError, ZeroDivisionError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _dms_to_degrees(values: Any, reference: Any) -> Optional[float]:
    """将 EXIF 度分秒转十进制度；坐标只在内存中参与距离计算。"""
    try:
        degrees, minutes, seconds = (_rational(part) for part in values)
        if degrees is None or minutes is None or seconds is None:
            return None
        result = degrees + minutes / 60.0 + seconds / 3600.0
        if isinstance(reference, bytes):
            reference = reference.decode("ascii", errors="ignore")
        if str(reference).strip().upper() in {"S", "W"}:
            result = -result
        return result
    except (TypeError, ValueError):
        return None


def _gps_coordinates(exif: Any, exif_tags: Any) -> Optional[Tuple[float, float]]:
    """兼容 Pillow 新旧 EXIF GPS 访问方式，不将原始位置写盘。"""
    try:
        gps_raw = exif.get_ifd(exif_tags.IFD.GPSInfo)
    except Exception:
        gps_raw = exif.get(34853)
    if not isinstance(gps_raw, dict):
        return None
    gps = {exif_tags.GPSTAGS.get(key, key): value for key, value in gps_raw.items()}
    latitude = _dms_to_degrees(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
    longitude = _dms_to_degrees(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _capture_time(exif: Any, exif_tags: Any) -> Optional[datetime]:
    """只返回解析后的时间供内存比较；不同相机的时钟/时区可能不一致。"""
    try:
        fields = {exif_tags.TAGS.get(key, key): value for key, value in exif.items()}
    except (AttributeError, TypeError):
        return None
    # 原始拍摄时间优先；普通 DateTime 只在前者缺失时作为弱替代。
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        value = _text(fields.get(key))
        if not value:
            continue
        try:
            parsed = datetime.strptime(value[:19], "%Y:%m:%d %H:%M:%S")
            if 1900 <= parsed.year <= 2100:
                return parsed
        except ValueError:
            continue
    return None


def _distance_meters(first: Tuple[float, float], second: Tuple[float, float]) -> float:
    """使用 Haversine 距离，仅用于判断两张照片的拍摄位置是否接近。"""
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    arc = 2 * math.asin(math.sqrt(math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2))
    return 6_371_000 * arc


def _load_pillow_with_install() -> Tuple[Optional[Any], Optional[Any], Optional[str]]:
    """先复用当前 Python 的 Pillow；缺失时主动安装一次，失败则返回可跳过的原因。"""
    try:
        from PIL import ExifTags, Image
        return ExifTags, Image, None
    except Exception:
        pass

    # 用正在运行本脚本的解释器安装，确保 pip 和后续 EXIF 读取处于同一 Python 环境。
    # 安装可能因网络、权限或受管 Python 限制失败；这类可选依赖失败不阻断视觉配对。
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "Pillow"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, None, "自动安装 Pillow 超时（120 秒）；已跳过 EXIF 分析，可继续按照片视觉配对。"
    except OSError as error:
        return None, None, f"无法启动当前 Python 的 pip（{type(error).__name__}）；已跳过 EXIF 分析，可继续按照片视觉配对。"

    if result.returncode != 0:
        # 不回显 pip 原始日志，避免包索引地址或环境信息意外进入任务报告。
        return None, None, f"自动安装 Pillow 失败（pip 退出码 {result.returncode}）；已跳过 EXIF 分析，可继续按照片视觉配对。"

    importlib.invalidate_caches()
    try:
        from PIL import ExifTags, Image
        return ExifTags, Image, None
    except Exception as error:
        return None, None, f"pip 安装后 Pillow 仍不可用（{type(error).__name__}）；已跳过 EXIF 分析，可继续按照片视觉配对。"


def analyze_task(task_key: str, root_arg: Optional[str], time_window_minutes: int, gps_radius_meters: int) -> Dict[str, Any]:
    root = core.resolve_root(root_arg)
    task = core.resolve_task(root, task_key)
    checked = core.validate_package_structure(task, task_key, check_integrity=True)
    if not checked["ok"]:
        raise core.PackageError("任务未通过完整性校验，拒绝分析图片元数据：" + "; ".join(checked["errors"][:5]))

    exif_tags, image_module, install_error = _load_pillow_with_install()
    if install_error:
        # 依赖安装属于可选分析步骤：留下原因，供任务恢复时查看，但不阻断整理配对。
        report = {
            "schema_version": "heribase.image_metadata_analysis.v1",
            "task_key": task_key,
            "status": "skipped_dependency_install_failed",
            "error": install_error,
            "privacy": {"raw_gps_saved": False, "exact_capture_times_saved": False, "device_serial_numbers_extracted_or_saved": False},
            "sources": [],
            "candidate_pairs": [],
        }
        output = task / "derived" / "image-metadata-analysis.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        core.write_json_atomic(output, report)
        return {"ok": True, "available": False, "task_key": task_key, "output_path": str(output), "warning": install_error}

    sources_doc = core.read_json(task / "inputs" / "sources.json")
    sources: List[Dict[str, Any]] = []
    private_facts: Dict[str, Dict[str, Any]] = {}
    for source in sources_doc["sources"]:
        if source.get("kind") not in {"local_image", "remote_image", "extracted_image"}:
            continue
        image_path = task / source["stored_path"]
        if not image_path.is_file():
            continue
        try:
            with image_module.open(image_path) as image:
                width, height = image.size
                exif = image.getexif()
                tags = {exif_tags.TAGS.get(key, key): value for key, value in exif.items()}
                # 优先使用 EXIF 标准相机字段；清理厂商前后空格但不推断别名。
                make = _text(tags.get("Make"))
                model = _text(tags.get("Model"))
                if make:
                    make = re.sub(r"\s+", " ", make)
                if model:
                    model = re.sub(r"\s+", " ", model)
                capture = _capture_time(exif, exif_tags)
                coordinates = _gps_coordinates(exif, exif_tags)
        except Exception as error:  # 单张坏图不应阻止整批其他照片参与分析。
            sources.append({"source_id": source["source_id"], "status": "unreadable", "error_type": type(error).__name__})
            continue

        source_id = source["source_id"]
        sources.append({
            "source_id": source_id,
            "status": "read",
            "pixel_size": {"width": width, "height": height},
            "camera_make": make,
            "camera_model": model,
            "has_exif": bool(exif),
            "has_capture_time": capture is not None,
            "has_gps": coordinates is not None,
        })
        private_facts[source_id] = {"size": (width, height), "make": make, "model": model, "capture": capture, "gps": coordinates}

    candidate_pairs: List[Dict[str, Any]] = []
    ids = list(private_facts)
    for index, first_id in enumerate(ids):
        first = private_facts[first_id]
        for second_id in ids[index + 1:]:
            second = private_facts[second_id]
            signals: List[str] = []
            time_close = False
            gps_close = False
            if first["capture"] is not None and second["capture"] is not None:
                time_close = abs((first["capture"] - second["capture"]).total_seconds()) <= time_window_minutes * 60
                if time_close:
                    signals.append(f"EXIF 拍摄时间相差不超过 {time_window_minutes} 分钟")
            if first["gps"] is not None and second["gps"] is not None:
                gps_close = _distance_meters(first["gps"], second["gps"]) <= gps_radius_meters
                if gps_close:
                    signals.append(f"EXIF 拍摄位置相距不超过 {gps_radius_meters} 米")
            same_size = first["size"] == second["size"]
            if same_size:
                signals.append("像素尺寸完全一致")
            same_make = bool(first["make"] and second["make"] and first["make"].casefold() == second["make"].casefold())
            same_model = bool(first["model"] and second["model"] and first["model"].casefold() == second["model"].casefold())
            if same_make:
                signals.append("拍摄设备品牌相同")
            if same_model:
                signals.append("拍摄设备机型相同")

            # 品牌与机型属于同一设备类别；只有至少两类元数据吻合才召回，避免常见机型/尺寸制造海量假配对。
            categories = sum((time_close, gps_close, same_size, same_make or same_model))
            has_session_signal = time_close or gps_close
            if categories >= 2 and (has_session_signal or categories >= 3):
                candidate_pairs.append({
                    "source_ids": [first_id, second_id],
                    "metadata_category_count": categories,
                    "metadata_signals": signals,
                    "interpretation": "可能来自相近拍摄批次；必须结合背景、币种/版别和币面实物特征复核，不能据此认定为同一枚。",
                })

    candidate_pairs.sort(key=lambda pair: (-pair["metadata_category_count"], -len(pair["metadata_signals"]), pair["source_ids"]))
    report = {
        "schema_version": "heribase.image_metadata_analysis.v1",
        "task_key": task_key,
        "status": "completed",
        "privacy": {"raw_gps_saved": False, "exact_capture_times_saved": False, "device_serial_numbers_extracted_or_saved": False},
        "thresholds": {"time_window_minutes": time_window_minutes, "gps_radius_meters": gps_radius_meters},
        "sources": sources,
        "candidate_pairs": candidate_pairs,
    }
    readable_sources = [source for source in sources if source.get("status") == "read"]
    if readable_sources and not any(source.get("has_exif") for source in readable_sources):
        report["metadata_note"] = "可读取的图片中没有 EXIF。没有可安装的组件能恢复已缺失的拍摄时间、GPS 或设备信息；已保留像素尺寸分析并继续视觉配对。"
    elif sources and not readable_sources:
        report["metadata_note"] = "没有图片能由 Pillow 读取；请检查图片格式或原文件。已记录不可读项，且不影响按其他可查看图片继续配对。"
    output = task / "derived" / "image-metadata-analysis.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    core.write_json_atomic(output, report)
    return {"ok": True, "available": True, "task_key": task_key, "output_path": str(output), "image_count": len(sources), "candidate_pair_count": len(candidate_pairs)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="本地分析硬币照片尺寸与 EXIF 配对线索")
    parser.add_argument("--root", help="任务包根目录；默认 ~/.heribase/user-tasks")
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--time-window-minutes", type=int, default=15)
    parser.add_argument("--gps-radius-meters", type=int, default=100)
    args = parser.parse_args(argv)
    if args.time_window_minutes < 0 or args.gps_radius_meters < 0:
        parser.error("时间窗口和 GPS 半径必须为非负整数")
    try:
        result = analyze_task(args.task_key, args.root, args.time_window_minutes, args.gps_radius_meters)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # Pillow 安装失败是可选元数据步骤的降级，不让自动化误认为整理任务失败。
        return 0 if result["ok"] else 2
    except core.PackageError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
