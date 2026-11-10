#!/usr/bin/env python3
"""检查、补齐 HeriBase 环境并初始化；随 skill 分发，从实际安装目录运行。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import venv

SKILLS = ("heribase-cli", "heribase-collection", "heribase-task-package",
          "heribase-workspace", "heribase-appraisal", "heribase-tracking")
DEPENDENCY_PROBE = """
import importlib, json, sys
packages = {'PIL': 'Pillow', 'openpyxl': 'openpyxl', 'defusedxml': 'defusedxml'}
missing = []
for module, name in packages.items():
    try:
        importlib.import_module(module)
    except Exception:
        missing.append(name)
print(json.dumps({'python': '.'.join(map(str, sys.version_info[:3])),
                  'missing': missing}))
"""


def venv_python(cli, windows=None):
    windows = os.name == "nt" if windows is None else windows
    return cli / ".venv" / ("Scripts/python.exe" if windows else "bin/python")


def _run(argv, timeout=20):
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False)


def check_environment(skills):
    """只读检查，不初始化账户，不调用真实业务接口，也不偷偷安装依赖。"""
    cli = skills / "heribase-cli"
    python = venv_python(cli)
    if not python.is_file():
        python = Path(sys.executable)
    checks = []
    missing = [name for name in SKILLS if not (skills / name / "SKILL.md").is_file()]
    checks.append({"name": "skills", "ok": not missing,
                   "detail": "缺少同级技能：" + ", ".join(missing) if missing else "六个技能均已安装"})
    try:
        result = _run([str(python), "-c", DEPENDENCY_PROBE])
        if result.returncode:
            raise ValueError("Python 探测失败")
        info = json.loads(result.stdout)
        supported = tuple(int(part) for part in info["python"].split(".")[:2]) >= (3, 9)
        checks.append({"name": "python", "ok": supported,
                       "detail": info["python"] if supported else "需要 Python 3.9+"})
        checks.append({"name": "dependencies", "ok": not info["missing"],
                       "detail": "缺少 " + ", ".join(info["missing"]) + "；运行本脚本 --install" if info["missing"] else "Python 依赖齐全"})
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        checks.append({"name": "python", "ok": False, "detail": "无法运行 Python；请重新安装 Python 3.9+ 或运行 --install 修复私有环境"})

    node = shutil.which("node")
    try:
        version = _run([node, "--version"]) if node else None
        match = re.fullmatch(r"v?(\d+)\.\d+\.\d+", version.stdout.strip()) if version and version.returncode == 0 else None
        supported = bool(match and int(match.group(1)) >= 24)
        checks.append({"name": "node", "ok": supported,
                       "detail": version.stdout.strip() if supported else "需要 Node.js 24+；安装后重新打开终端和 Agent"})
        if supported:
            bundle = cli / "bin/heribase"
            result = _run([node, str(bundle), "version", "--json"])
            info = json.loads(result.stdout) if result.returncode == 0 else {}
            checks.append({"name": "cli", "ok": bool(info.get("version")),
                           "detail": str(info.get("version", "CLI 不可运行；请重新安装完整 skills"))})
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        checks.append({"name": "cli", "ok": False, "detail": "无法启动 Node.js 或随附 CLI；请确认 Node.js 24+ 和 bin/heribase 完整"})
    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "python": str(python), "cli": [node or "node", str(cli / "bin/heribase")],
            "webOrganizer": {"codexInstalled": bool(shutil.which("codex")),
                "note": "网页上传后的自动整理还需要已安装并登录的 Codex CLI；本检查不验证登录。"}}


def install_dependencies(cli):
    """只写入 skill 自己的 .venv，不修改系统 Python 或自动获取管理员权限。"""
    if sys.version_info < (3, 9):
        raise RuntimeError("请先安装 Python 3.9+")
    directory = cli / ".venv"
    if directory.is_symlink():
        raise RuntimeError(".venv 是符号链接，请改用独立目录后安装")
    python = venv_python(cli)
    usable = False
    if python.is_file():
        try:
            usable = _run([str(python), "-m", "pip", "--version"]).returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    if not usable:
        try:
            # 与 python -m venv 的平台默认一致：POSIX 使用链接，避免复制 uv 等
            # 可搬运解释器后丢失标准库定位；Windows 使用副本，无需链接权限。
            venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt", clear=True).create(directory)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("无法创建虚拟环境；Linux 请安装 python3-venv，并确认技能目录可写") from exc
    result = _run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                   "-r", str(cli / "requirements.txt")], timeout=300)
    if result.returncode:
        # 包源错误可能包含配置凭据；不给业务对话转储完整的 pip 输出。
        raise RuntimeError("Python 依赖安装失败；请检查网络、包源设置和 Python 版本，再运行 --install")


def prepare_cli(cli):
    bundle = cli / "bin/heribase"
    if not bundle.is_file() or bundle.is_symlink():
        raise RuntimeError("缺少普通文件 bin/heribase，请重新安装完整 skills")
    # CLI 由维护方独立打包，安装过程保留其内容和权限；各平台均通过 Node
    # 运行该文件，无需为它补执行权限，也不在这里重建或修补产物。
    # 使用相对脚本位置且保留引号，使中文/空格路径在 Windows 正常工作。
    wrapper = cli / "bin/heribase.cmd"
    if wrapper.is_symlink():
        raise RuntimeError("heribase.cmd 不能是符号链接")
    wrapper.write_bytes(b'@echo off\r\nnode "%~dp0heribase" %*\r\nexit /b %errorlevel%\r\n')


def initialize(skills):
    """完成本地准备；登录留给用户选择，不把未登录视作安装失败。"""
    report = check_environment(skills)
    # 先确认整套技能与 Node 可用，避免在不完整的安装中反复下载 Python 依赖。
    if any(not item["ok"] for item in report["checks"]
           if item["name"] not in ("python", "dependencies")):
        return report
    if not report["ok"]:
        install_dependencies(skills / "heribase-cli")
        report = check_environment(skills)
        if not report["ok"]:
            return report
    prepare_cli(skills / "heribase-cli")
    try:
        # 仅使用随附 CLI 的公开命令，不直接读写 .heribase。支持 CLI 自行初始化，
        # 也兼容返回明确“未配置”的既有产物；其他错误绝不能当作配置缺失。
        result = _run([*report["cli"], "status", "--json"])
        if (result.returncode and result.stderr.strip()
                == "HeriBase CLI is not configured. Run heribase configure --api-base-url <url>."):
            # 不无条件 configure，以免覆盖用户已有的自定义地址。
            configured = _run([*report["cli"], "configure", "--api-base-url", "https://api.heribase.com"])
            if configured.returncode:
                raise ValueError("configure failed")
            result = _run([*report["cli"], "status", "--json"])
        if result.returncode:
            raise ValueError("status failed")
        status = json.loads(result.stdout)
        if (not isinstance(status, dict)
                or not isinstance(status.get("api_base_url"), str)
                or not status["api_base_url"].strip()
                or not isinstance(status.get("authenticated"), bool)):
            raise ValueError("invalid status")
    except (OSError, subprocess.SubprocessError, ValueError):
        report["ok"] = False
        # 不转储 CLI 输出或认证文件；保留独立的环境检查结果，便于 Agent 定位失败阶段。
        report["initialization"] = {"ok": False, "error": "环境检查已通过，但 CLI 状态读取失败；请检查 CLI 配置或本地 daemon 后重跑 --init"}
        return report

    authenticated = status["authenticated"]
    report["initialization"] = {"ok": True, "apiBaseUrl": status["api_base_url"],
                                "authenticated": authenticated}
    report["onboarding"] = {
        "message": "HeriBase 已安装并完成本地初始化。"
                   + ("已检测到保存的登录状态，可以开始使用。" if authenticated else
                      "你可以先整理钱币照片；在线识别、收藏、鉴定和行情查询需要登录。"),
        "examples": ["帮我整理这些钱币照片，先让我核对正反面。",
                     "识别这枚钱币，结果确认后再加入收藏。",
                     "查看我的真人鉴定进度。",
                     "查看我正在追踪的钱币行情。"],
        "loginPrompt": None if authenticated else "要现在登录吗？也可以先发照片，体验本地整理。",
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="HeriBase 环境准备；安装后用 --init 完成依赖、默认配置和入门引导")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="只读检查（默认）")
    action.add_argument("--install", action="store_true", help="在 heribase-cli/.venv 安装依赖，然后检查")
    action.add_argument("--init", action="store_true", help="检查并补齐依赖，初始化 CLI 配置，返回登录状态和入门引导")
    args = parser.parse_args(argv)
    # 从安装后的实际位置定位同级 skills，不能依赖仓库路径或调用者的 cwd。
    skills = Path(__file__).resolve().parents[2]
    try:
        if args.install:
            missing = [name for name in SKILLS if not (skills / name / "SKILL.md").is_file()]
            if missing:
                raise RuntimeError("请先同级安装六个 skills，缺少：" + ", ".join(missing))
            install_dependencies(skills / "heribase-cli")
            prepare_cli(skills / "heribase-cli")
        report = initialize(skills) if args.init else check_environment(skills)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
