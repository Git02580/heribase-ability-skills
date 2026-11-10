#!/usr/bin/env python3
"""检查 HeriBase 环境，或显式安装 Python 依赖；随 skill 分发即可运行。"""
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
    if os.name != "nt":
        bundle.chmod(bundle.stat().st_mode | 0o100)
    # 使用相对脚本位置且保留引号，使中文/空格路径在 Windows 正常工作。
    wrapper = cli / "bin/heribase.cmd"
    if wrapper.is_symlink():
        raise RuntimeError("heribase.cmd 不能是符号链接")
    wrapper.write_bytes(b'@echo off\r\nnode "%~dp0heribase" %*\r\nexit /b %errorlevel%\r\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description="检查 HeriBase 环境；--install 安装私有 Python 依赖和 CLI 启动入口")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="只读检查（默认）")
    action.add_argument("--install", action="store_true", help="在 heribase-cli/.venv 安装依赖，然后检查")
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
        report = check_environment(skills)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
