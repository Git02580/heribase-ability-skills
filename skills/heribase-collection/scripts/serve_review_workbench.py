#!/usr/bin/env python3
"""在 127.0.0.1 上以 Origin-Agent-Cluster 响应头提供只读审核台。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import unquote, urlparse


TASK_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "heribase-task-package" / "scripts"
sys.path.insert(0, str(TASK_PACKAGE_SCRIPTS))
import task_package as core  # noqa: E402


def make_handler(document_root: Path):
    class ReviewHandler(BaseHTTPRequestHandler):
        server_version = "HeriBaseReview/1.0"

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            relative = unquote(parsed.path).lstrip("/") or "index.html"
            if not core.safe_relative_path(relative):
                self.send_error(400, "invalid path")
                return
            target = (document_root / relative).resolve(strict=False)
            try:
                target.relative_to(document_root)
            except ValueError:
                self.send_error(403)
                return
            if target.is_symlink() or not target.is_file():
                self.send_error(404)
                return
            content = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Origin-Agent-Cluster", "?1")
            self.send_header("Permissions-Policy", "tools=(self)")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):  # noqa: A003
            return

    return ReviewHandler


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="启动 HeriBase 只读硬币审核台")
    parser.add_argument("--root", help="测试/隔离任务根目录；生产环境省略")
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--output-name", default="review-workbench")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        root = core.resolve_root(args.root)
        task = core.resolve_task(root, args.task_key)
        document_root = (task / "derived" / args.output_name).resolve()
        document_root.relative_to(task / "derived")
        if not (document_root / "index.html").is_file():
            raise core.PackageError("审核台尚未生成，请先运行 build_review_workbench.py")
    except (core.PackageError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(document_root))
    port = server.server_address[1]
    print(json.dumps({"ok": True, "url": f"http://127.0.0.1:{port}/", "task_key": args.task_key}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

