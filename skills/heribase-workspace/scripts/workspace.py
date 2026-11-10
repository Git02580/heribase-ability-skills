#!/usr/bin/env python3
"""业务 Skill 与宿主 Agent 的工作空间工具入口。stdout 始终只有一个 JSON 文档。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workspace_runtime import read_runtime, request_workspace, serve_workspace, start_workspace, stop_workspace
from workspace_store import WorkspaceError
from workspace_backup import restore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="HeriBase 持久化工作空间与宿主交接工具")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("start", "serve", "status", "stop", "snapshot", "bridge", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--home", type=Path, default=Path.home(), help="测试时使用隔离 home；正式环境省略")
        if name == "restore":
            command.add_argument("--archive", type=Path, required=True)
            command.add_argument("--destination-home", type=Path, required=True)
        if name == "start":
            command.add_argument(
                "--no-open", "--no-default-browser", dest="no_open", action="store_true",
                help="只启动或复用工作台并返回 URL，不调用系统默认浏览器；Codex 桌面由宿主打开右侧浏览器",
            )
            command.add_argument("--page", default="add")
            command.add_argument("--task-key")
        if name == "serve":
            command.add_argument("--port", type=int, default=0)
        if name == "bridge":
            actions = command.add_subparsers(dest="action", required=True)
            bind = actions.add_parser("bind")
            bind.add_argument("--host", required=True)
            bind.add_argument("--conversation", required=True)
            bind.add_argument("--title", help="当前宿主会话标题，用于工作台中区分会话")
            inbox = actions.add_parser("inbox")
            inbox.add_argument("--binding-id", required=True)
            inbox.add_argument("--lease-seconds", type=int, default=60)
            progress = actions.add_parser("progress")
            progress.add_argument("--binding-id", required=True)
            progress.add_argument("--command-id", required=True)
            progress.add_argument("--delivery-token", required=True)
            progress.add_argument("--status", choices=("running", "awaiting_user"), required=True)
            progress.add_argument("--message", required=True)
            progress.add_argument("--step")
            progress.add_argument("--lease-seconds", type=int, default=60)
            for recovery_name in ("inspect", "reconcile", "resume", "resolve"):
                recovery = actions.add_parser(recovery_name)
                recovery.add_argument("--operation-id", required=True)
                if recovery_name == "reconcile":
                    recovery.add_argument("--matches-file", type=Path, required=True)
            action = actions.add_parser("action")
            action.add_argument("--binding-id", required=True)
            action.add_argument("--name", required=True)
            action.add_argument("--payload-file", type=Path, required=True)
            reply = actions.add_parser("reply")
            reply.add_argument("--binding-id", required=True)
            reply.add_argument("--command-id", required=True)
            reply.add_argument("--delivery-token", required=True)
            reply.add_argument("--message-file", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "serve":
            serve_workspace(args.home, args.port)
            return 0
        if args.command == "restore":
            value = restore(args.archive, args.destination_home)
        elif args.command == "start":
            value = start_workspace(args.home, not args.no_open, args.page, args.task_key)
        elif args.command == "status":
            runtime = read_runtime(args.home)
            value = {"ok": True, "running": runtime is not None, "url": runtime["url"] if runtime else None}
        elif args.command == "stop":
            value = stop_workspace(args.home)
        elif args.command == "snapshot":
            value = request_workspace(args.home, "/api/snapshot")
        elif args.action == "bind":
            payload = {"host": args.host, "conversation": args.conversation}
            if args.title:
                payload["conversationTitle"] = args.title
            value = request_workspace(args.home, "/api/bridge/bind", payload)
        elif args.action == "inbox":
            value = request_workspace(args.home, "/api/bridge/inbox", {"bindingId": args.binding_id, "leaseSeconds": args.lease_seconds})
        elif args.action == "progress":
            payload = {"bindingId": args.binding_id, "commandId": args.command_id, "deliveryToken": args.delivery_token,
                       "status": args.status, "message": args.message, "leaseSeconds": args.lease_seconds}
            if args.step:
                payload["step"] = args.step
            value = request_workspace(args.home, "/api/bridge/progress", payload)
        elif args.action in {"inspect", "reconcile", "resume", "resolve"}:
            payload = {"operationId": args.operation_id}
            if args.action == "reconcile":
                payload["matches"] = json.loads(args.matches_file.read_text(encoding="utf-8"))
            path = "/api/operations/inspect" if args.action == "inspect" else "/api/bridge/" + args.action
            value = request_workspace(args.home, path, payload)
        elif args.action == "action":
            value = request_workspace(args.home, "/api/bridge/action", {"bindingId": args.binding_id,
                "action": args.name, "payload": json.loads(args.payload_file.read_text(encoding="utf-8"))})
        else:
            value = request_workspace(args.home, "/api/bridge/reply", {"bindingId": args.binding_id, "commandId": args.command_id,
                                      "deliveryToken": args.delivery_token, "message": args.message_file.read_text(encoding="utf-8")})
        print(json.dumps(value, ensure_ascii=False))
        return 0
    except (WorkspaceError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": getattr(exc, "code", "local_error"), "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
