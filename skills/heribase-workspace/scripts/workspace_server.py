"""仅监听 loopback 的工作空间 HTTP 服务；网页和宿主工具使用不同凭据。

不提供目录浏览、任意路径读取或通用命令执行接口。事件采用携带鉴权头的
长轮询，游标保存在 SQLite，浏览器断线后可补读而无需重做业务操作。
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from workspace_service import WorkspaceService
from workspace_executor import PROFILE_AVATAR_HOSTS
from workspace_store import WorkspaceError, WorkspaceStore

# 页面资源可在服务进程启动后更新；协议号变化时禁止新版页面继续调用旧进程。
PROTOCOL_VERSION = 5
MAX_JSON_BYTES = 1024 * 1024
STATIC_FILES = {"add.js": "text/javascript; charset=utf-8", "add.css": "text/css; charset=utf-8",
                "review.js": "text/javascript; charset=utf-8","index.html": "text/html; charset=utf-8", "styles.css": "text/css; charset=utf-8",
                "app.js": "text/javascript; charset=utf-8", "api.js": "text/javascript; charset=utf-8", "bridge.js": "text/javascript; charset=utf-8",
                "bulk.js": "text/javascript; charset=utf-8", "views.js": "text/javascript; charset=utf-8", "router.js": "text/javascript; charset=utf-8",
                "commerce.js": "text/javascript; charset=utf-8"}
PROFILE_IMAGE_SOURCES = " ".join("https://" + host for host in PROFILE_AVATAR_HOSTS)


def create_server(store: WorkspaceStore, assets: Path, browser_key: str, host_key: str,
                  port: int = 0, service: Optional[WorkspaceService] = None) -> ThreadingHTTPServer:
    service = service or WorkspaceService(store)
    changed = threading.Condition()
    assets = assets.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "HeriBaseWorkspace/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, format, *args):
            # HTTP URL 和鉴权头不写日志，启动链接可能携带短期浏览器凭据。
            return

        def reply(self, status: int, body: Any, mime: str = "application/json; charset=utf-8") -> None:
            content = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            if getattr(self, "set_browser_cookie", False):
                self.send_header("Set-Cookie", "heribase_session=" + browser_key + "; Path=/api/media; HttpOnly; SameSite=Strict")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                             f"img-src 'self' data: blob: {PROFILE_IMAGE_SOURCES}; connect-src 'self'; object-src 'none'; "
                             "base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def boundary(self) -> str:
            authority = "127.0.0.1:" + str(self.server.server_address[1])
            if self.headers.get("Host") != authority:
                raise WorkspaceError("invalid_host", "仅接受当前本机工作空间地址", 403)
            origin = self.headers.get("Origin")
            if origin is not None and origin != "http://" + authority:
                raise WorkspaceError("invalid_origin", "拒绝其他网页来源", 403)
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc:
                raise WorkspaceError("invalid_path", "不接受绝对请求地址", 400)
            return unquote(parsed.path)

        def identity(self, media: bool = False) -> str:
            token = self.headers.get("Authorization", "")
            if secrets.compare_digest(token, "Bearer " + host_key):
                return "host"
            if secrets.compare_digest(token, "Bearer " + browser_key):
                return "browser"
            if media:
                cookie = SimpleCookie()
                cookie.load(self.headers.get("Cookie", ""))
                session = cookie.get("heribase_session")
                if session and secrets.compare_digest(session.value, browser_key):
                    return "browser"
            raise WorkspaceError("unauthorized", "工作空间连接已失效，请从业务入口重新打开", 401)

        def json_body(self) -> Any:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise WorkspaceError("invalid_length", "请求长度无效")
            if length > MAX_JSON_BYTES:
                raise WorkspaceError("payload_too_large", "请求超过 1 MiB", 413)
            if length <= 0 or self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                raise WorkspaceError("invalid_body", "需要明确长度的 JSON 请求")

            def unique(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("duplicate key")
                    value[key] = item
                return value
            try:
                return json.loads(self.rfile.read(length), object_pairs_hook=unique,
                                  parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise WorkspaceError("invalid_json", "请求不是有效的 JSON")

        def handle_request(self, mutation: bool) -> None:
            try:
                path = self.boundary()
                query = parse_qs(urlsplit(self.path).query)
                if not mutation and path == "/health":
                    self.reply(200, {"ok": True, "protocolVersion": PROTOCOL_VERSION, "instanceId": getattr(self.server, "instance_id", None)})
                    return
                if not mutation and path == "/payment-return":
                    # 付款页面只展示回流提示；实际支付状态由重新获得焦点的工作台查单。
                    # 不接受任意跳转目标，也不依赖此无凭据 GET 请求修改本地或远端状态。
                    result = query.get("result", [""])[0]
                    message = ("你已离开支付流程。回到原工作台窗口后，可继续支付或刷新订单。"
                               if result == "cancel" else
                               "请关闭此页并返回原工作台窗口，工作台会自动查询订单状态。")
                    html = ("<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
                            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                            "<title>返回 HeriBase 工作台</title><body style=\"font:16px/1.7 system-ui;max-width:620px;margin:12vh auto;padding:32px;background:#f3f0e7;color:#26332d\">"
                            "<small>HERIBASE · WORKSPACE</small><h1>支付流程已返回</h1><p>" + message + "</p>"
                            "<p>支付结果以工作台查询到的服务端订单状态为准。</p></body></html>")
                    self.reply(200, html, "text/html; charset=utf-8")
                    return
                if path.startswith("/api/"):
                    role = self.identity(media=not mutation and path in {"/api/media", "/api/commerce/media"})
                    if mutation and path == "/api/session":
                        if role != "browser":
                            raise WorkspaceError("forbidden", "此入口只供网页连接", 403)
                        if self.json_body() != {}:
                            raise WorkspaceError("invalid_request", "会话初始化不接受业务数据")
                        self.set_browser_cookie = True
                        self.reply(200, {"ok": True})
                    elif mutation and path in {"/api/upload", "/api/commerce/upload", "/api/connector/photo"}:
                        if role != "browser" and path != "/api/upload":
                            raise WorkspaceError("forbidden", "此入口只供网页上传", 403)
                        upload_actor = "user:web" if role == "browser" else "agent:connector"
                        try:
                            length = int(self.headers.get("Content-Length", "0"))
                            revision = int(query.get("revision", ["0"])[0])
                        except ValueError:
                            raise WorkspaceError("invalid_upload", "上传长度或任务版本无效")
                        if not 0 < length <= 20 * 1024 * 1024:
                            raise WorkspaceError("upload_too_large", "单个文件不超过 20 MiB", 413)
                        if self.headers.get_content_type() != "application/octet-stream" or self.headers.get("Transfer-Encoding"):
                            raise WorkspaceError("invalid_upload", "需要明确长度的文件字节流")
                        content = self.rfile.read(length)
                        if len(content) != length:
                            raise WorkspaceError("truncated_upload", "上传中断，未归档不完整文件")
                        with service.executor.lock:
                            if path == "/api/commerce/upload":
                                result = service.commerce.stage_file(query.get("name", [""])[0], content, "user:web")
                            elif path == "/api/connector/photo":
                                key = query.get("task", [""])[0]
                                mode = query.get("mode", [""])[0]
                                if mode == "stage":
                                    if "side" in query:
                                        raise WorkspaceError("invalid_request", "暂存照片请在保存时明确分配正反面")
                                    result = service.connector.stage_photo(key, revision, query.get("localId", [""])[0],
                                        query.get("name", [""])[0], content, upload_actor)
                                elif mode == "":
                                    service.executor.assert_idle(key)
                                    job = service.store.get_entity("organization", key)
                                    if job and job["data"].get("status") in {"queued", "running"}:
                                        raise WorkspaceError("organization_pending", "正在整理照片，请稍后补图", 409)
                                    result = service.tasks.ingest(key, revision, query.get("name", [""])[0], content, upload_actor,
                                        supplement_local_id=query.get("localId", [""])[0], supplement_side=query.get("side", [""])[0])
                                else:
                                    raise WorkspaceError("invalid_request", "照片上传模式无效")
                            else:
                                result = service.organizer.archive_upload(query.get("task", [""])[0], revision,
                                    query.get("name", [""])[0], content, upload_actor, schedule=role == "browser")
                        with changed:
                            changed.notify_all()
                        self.reply(200, result)
                    elif mutation:
                        result = service.mutate(path, self.json_body(), role)
                        with changed:
                            changed.notify_all()
                        self.reply(200, result)
                    elif path == "/api/snapshot":
                        self.reply(200, service.snapshot())
                    elif path == "/api/account-profile":
                        if role != "browser":
                            raise WorkspaceError("forbidden", "此入口只供网页显示账号资料", 403)
                        self.reply(200, service.executor.account_profile())
                    elif path == "/api/task":
                        self.reply(200, service.tasks.snapshot(query.get("key", [""])[0]))
                    elif path == "/api/media":
                        content, mime = service.tasks.source(query.get("task", [""])[0], query.get("source", [""])[0])
                        # 不把用户上传的 HTML/SVG 变成同源可执行页面。
                        safe_mime = mime if mime in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"} else "application/octet-stream"
                        self.reply(200, content, safe_mime)
                    elif path == "/api/commerce/media":
                        content, mime = service.commerce.media(query.get("id", [""])[0])
                        self.reply(200, content, mime)
                    elif path == "/api/events":
                        try:
                            after = int(query.get("after", ["0"])[0])
                            wait = float(query.get("wait", ["0"])[0])
                        except (ValueError, TypeError):
                            raise WorkspaceError("invalid_cursor", "事件查询参数无效")
                        if not 0 <= wait <= 25:
                            raise WorkspaceError("invalid_wait", "事件等待时间必须在 0–25 秒之间")
                        deadline = time.monotonic() + wait
                        service.tasks.refresh_external_changes()
                        events = store.events(after)
                        while not events and time.monotonic() < deadline:
                            with changed:
                                changed.wait(min(1, max(0, deadline - time.monotonic())))
                            service.tasks.refresh_external_changes()
                            events = store.events(after)
                        self.reply(200, {"events": events, "cursor": events[-1]["sequence"] if events else after})
                    else:
                        raise WorkspaceError("not_found", "未找到该接口", 404)
                    return
                if mutation:
                    raise WorkspaceError("not_found", "未找到该操作", 404)
                name = path[1:] or "index.html"
                if name not in STATIC_FILES:
                    raise WorkspaceError("not_found", "未找到该资源", 404)
                target = assets / name
                if target.is_symlink() or not target.is_file():
                    raise WorkspaceError("not_found", "资源不可用", 404)
                self.reply(200, target.read_bytes(), STATIC_FILES[name])
            except WorkspaceError as exc:
                self.reply(exc.status, {"error": {"code": exc.code, "message": str(exc), **exc.details}})
            except Exception:
                self.reply(500, {"error": {"code": "internal_error", "message": "本地操作失败，原有记录已保留。请检查工作空间状态。"}})

        def do_GET(self):
            self.handle_request(False)

        def do_POST(self):
            self.handle_request(True)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    original_close = server.server_close
    def close():
        service.organizer.close()
        original_close()
    server.server_close = close
    service.shutdown = lambda: threading.Timer(0.1, server.shutdown).start()
    return server
