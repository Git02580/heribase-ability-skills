"""启动/复用工作台服务，凭据仅保存在本机私有 runtime 文件中。"""
from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

from workspace_server import PROTOCOL_VERSION, create_server
from workspace_service import WorkspaceService
from workspace_store import WorkspaceError, WorkspaceStore

PAGES = {"add", "home", "tasks", "import", "task", "inputs", "pairing", "identify", "review", "confirm", "operations",
         "library", "coin", "appraisals", "appraisal", "report", "tracking", "reports", "settings",
         "market", "buying", "selling", "membership"}


def runtime_directory(home: Path) -> Path:
    directory = Path(home).expanduser() / ".heribase" / "workspace"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.is_symlink():
        raise WorkspaceError("unsafe_path", "运行目录不能是符号链接")
    os.chmod(directory, 0o700)
    return directory


def raw_runtime(home: Path) -> Optional[Dict[str, Any]]:
    path = Path(home).expanduser() / ".heribase" / "workspace" / "runtime.json"
    if path.is_symlink():
        raise WorkspaceError("unsafe_path", "运行信息不能是符号链接")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", data.get("url", "")):
            return None
        if any(not isinstance(data.get(key), str) for key in ("instanceId", "browserKey", "hostKey")):
            return None
        return data
    except (FileNotFoundError, ValueError, TypeError):
        return None


def http_json(url: str, key: Optional[str] = None, body: Any = None, timeout: float = 3) -> Any:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = Request(url, json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None, headers)
    # 本机桥接不能意外经过用户的 HTTP 代理，从而泄露本地连接凭据。
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("error", {})
        finally:
            exc.close()
        raise WorkspaceError(detail.get("code", "http_error"), detail.get("message", "工作空间请求失败"), exc.code,
                             **{name: value for name, value in detail.items() if name not in {"code", "message"}})


def read_runtime(home: Path) -> Optional[Dict[str, Any]]:
    data = raw_runtime(home)
    if not data:
        return None
    try:
        health = http_json(data["url"] + "/health", timeout=0.4)
    except (OSError, URLError, ValueError, WorkspaceError):
        return None
    if health.get("instanceId") != data["instanceId"]:
        return None
    if health.get("protocolVersion") != PROTOCOL_VERSION:
        raise WorkspaceError("incompatible_runtime", "工作空间版本不兼容，请关闭旧服务后重新启动", 409)
    return data


def request_workspace(home: Path, path: str, body: Any = None, role: str = "host") -> Any:
    runtime = read_runtime(home)
    if not runtime:
        raise WorkspaceError("workspace_offline", "工作空间未运行，请先启动", 503)
    if not path.startswith("/api/") or role not in {"host", "browser"}:
        raise WorkspaceError("invalid_request", "工作空间请求不合法")
    return http_json(runtime["url"] + path, runtime["hostKey" if role == "host" else "browserKey"], body, timeout=35)


@contextmanager
def runtime_lock(directory: Path):
    """操作系统持有锁，进程崩溃自动释放；不凭残留 PID/lock 文件判断服务存活。"""
    path = directory / "service.lock"
    if path.is_symlink():
        raise WorkspaceError("unsafe_path", "服务锁不能是符号链接")
    lock = path.open("a+b")
    os.chmod(path, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                lock.write(b"0"); lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except (BlockingIOError, PermissionError) as exc:
        raise WorkspaceError("already_running", "已有工作空间服务正在运行或启动", 409) from exc
    finally:
        if acquired:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def serve_workspace(home: Path, port: int = 0) -> None:
    store = WorkspaceStore(home)
    directory = runtime_directory(home)
    with runtime_lock(directory):
        browser_key, host_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        service = WorkspaceService(store)
        server = create_server(store, Path(__file__).resolve().parents[1] / "assets" / "workbench", browser_key, host_key, port, service)
        server.instance_id = secrets.token_hex(16)
        runtime = {"url": "http://127.0.0.1:" + str(server.server_address[1]), "pid": os.getpid(),
                   "protocolVersion": PROTOCOL_VERSION, "instanceId": server.instance_id,
                   "browserKey": browser_key, "hostKey": host_key}
        # 支付商会在用户浏览器中访问此 loopback 地址；API 不应猜测本地端口。
        service.commerce.set_payment_return_base_url(runtime["url"])
        # 原子替换避免另一个启动者看到半份 JSON；临时文件从创建时就是 0600。
        temporary = directory / (".runtime-" + secrets.token_hex(8))
        fd = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(runtime, output); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, directory / "runtime.json")
        # serve 以常驻前台进程运行；给人工启动者一个可见、且不包含浏览器密钥的反馈。
        print(json.dumps({"ok": True, "status": "serving", "url": runtime["url"],
                          "message": "工作台正在监听；请通过 workspace.py start 打开带授权的页面，按 Ctrl+C 停止服务。"}, ensure_ascii=False), flush=True)
        def shutdown(*_):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            server.server_close()
            saved = raw_runtime(home)
            if saved and saved.get("instanceId") == server.instance_id:
                (directory / "runtime.json").unlink(missing_ok=True)


def start_workspace(home: Path, open_browser: bool = True, page: str = "home", task_key: Optional[str] = None) -> Dict[str, Any]:
    if page not in PAGES:
        raise WorkspaceError("invalid_page", "工作空间页面不存在")
    if task_key is not None and not re.fullmatch(r"\d{8}-\d{4}-[a-z0-9][a-z0-9-]*", task_key):
        raise WorkspaceError("invalid_task", "任务标识无效")
    home = Path(home).expanduser().resolve()
    runtime = read_runtime(home)
    reused = runtime is not None
    if not runtime:
        directory = runtime_directory(home)
        log_path = directory / "service.log"
        if log_path.is_symlink():
            raise WorkspaceError("unsafe_path", "日志不能是符号链接")
        with os.fdopen(os.open(str(log_path), os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600), "ab") as log:
            options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            child = subprocess.Popen([sys.executable, str(Path(__file__).with_name("workspace.py")), "serve", "--home", str(home)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
        # 长驻宿主进程中及时回收退出的子进程；等待线程不阻止前台 CLI 退出。
        threading.Thread(target=child.wait, daemon=True).start()
        for _ in range(80):
            runtime = read_runtime(home)
            if runtime:
                break
            # 即使当前 child 由于并发锁退出，也等待另一个已经启动的实例就绪。
            time.sleep(0.1)
        if not runtime:
            child.poll()
            raise WorkspaceError("start_failed", "工作空间未成功启动，请检查 .heribase/workspace/service.log", 503)
    query = {"access": runtime["browserKey"], "page": page}
    if task_key:
        query["task"] = task_key
    url = runtime["url"] + "/#" + urlencode(query)
    settings = WorkspaceStore(home).get_entity("settings", "workspace")
    opened = False
    if open_browser and (not settings or settings["data"].get("autoOpen", True)):
        try:
            opened = webbrowser.open(url)
        except webbrowser.Error:
            pass
    return {"ok": True, "url": url, "reused": reused, "opened": opened,
            "page": page, "taskKey": task_key, "protocolVersion": PROTOCOL_VERSION}


def stop_workspace(home: Path) -> Dict[str, Any]:
    # 停止命令必须能处理协议已过期的旧服务；read_runtime 会有意拒绝旧协议，
    # 因此这里读取受权限保护的本机 runtime 信息，再通过 instanceId 确认服务身份。
    runtime = raw_runtime(home)
    if not runtime:
        return {"ok": True, "running": False}
    try:
        health = http_json(runtime["url"] + "/health", timeout=0.4)
    except (OSError, URLError, ValueError, WorkspaceError):
        return {"ok": True, "running": False}
    if health.get("instanceId") != runtime["instanceId"]:
        return {"ok": True, "running": False}
    http_json(runtime["url"] + "/api/bridge/shutdown", runtime["hostKey"], {})
    for _ in range(50):
        saved = raw_runtime(home)
        if not saved or saved.get("instanceId") != runtime["instanceId"]:
            return {"ok": True, "running": False}
        try:
            health = http_json(runtime["url"] + "/health", timeout=0.4)
        except (OSError, URLError, ValueError, WorkspaceError):
            return {"ok": True, "running": False}
        if health.get("instanceId") != runtime["instanceId"]:
            return {"ok": True, "running": False}
        time.sleep(0.1)
    raise WorkspaceError("stop_pending", "工作空间仍在结束当前服务", 409)
