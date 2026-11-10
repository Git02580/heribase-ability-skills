#!/usr/bin/env python3
"""Chat-first single-coin helper. All remote work belongs to the durable runtime.

Trusted local paths are read only here.  The existing archive endpoint receives
file bytes and a basename, and the connector APIs receive only task/source IDs.
No dashboard, inbox delivery or short-lived asynchronous executor is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from workspace_runtime import read_runtime, request_workspace, start_workspace
from workspace_store import WorkspaceError, safe_json
from workspace_tasks import IMAGE_EXTENSIONS, operations


def upload_source(home, task_key, revision, name, content):
    """Use the runtime's existing locked byte archive, without filesystem paths.

    request_workspace is the JSON transport; this companion uses the same
    verified runtime credentials, loopback target and disabled proxy policy for
    the existing /api/upload byte-stream contract.
    """
    runtime = read_runtime(home)
    if not runtime:
        raise WorkspaceError("workspace_offline", "工作空间未运行，请先启动", 503)
    url = runtime["url"] + "/api/upload?" + urlencode({"task": task_key, "revision": revision, "name": name})
    request = Request(url, content, {"Authorization": "Bearer " + runtime["hostKey"],
                                    "Content-Type": "application/octet-stream"})
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=35) as response:
            value = json.loads(response.read())
            safe_json(value)
            return value
    except HTTPError as exc:
        try:
            error = json.loads(exc.read()).get("error", {})
        finally:
            exc.close()
        raise WorkspaceError(error.get("code", "http_error"), error.get("message", "照片归档失败"), exc.code)


def read_photo(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise WorkspaceError("invalid_photo", "请提供现有的普通图片文件")
    with path.open("rb") as source:
        content = source.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024:
        raise WorkspaceError("invalid_photo", "单张照片应大于零且不超过 20 MiB")
    return path.name, content, hashlib.sha256(content).hexdigest()


def single_item(task):
    active = [item for item in task["items"] if item.get("status") == "active"]
    if len(active) != 1:
        raise WorkspaceError("invalid_scope", "此聊天入口需要任务中有且只有一枚活动钱币，请先核对原任务", 409)
    return active[0]


def describe(task, operations_list=(), operation=None):
    key = task["manifest"]["task_key"]
    active = [item for item in task["items"] if item.get("status") == "active"]
    item = active[0] if len(active) == 1 else {}
    recognition = item.get("active_identification") or {}
    collection = item.get("collection_projection") or {}
    current_result = bool(task.get("health", {}).get("ok") and recognition.get("status") == "succeeded")
    pending = [entry for entry in operations_list if entry["data"].get("taskKey") == key
               and entry["data"].get("status") in {"preparing", "queued", "running", "reconcile_required", "partial_failed"}]
    current_operation = operation or (pending[-1] if pending else None)
    stage, next_action = "photos_required", "prepare"
    if len(active) > 1:
        stage, next_action = "selection_required", "review_task_scope"
    elif item:
        if collection.get("status") == "succeeded" and collection.get("collection_uri"):
            stage, next_action = "collected", "complete"
        elif recognition.get("status") == "succeeded":
            stage, next_action = "identified", "accept_result_and_collect"
        elif recognition.get("status") == "failed_terminal":
            stage, next_action = "recognition_failed", "review_photos"
        elif operations.identification_eligible(item):
            stage, next_action = "prepared", "identification-plan"
        else:
            stage, next_action = "pairing_required", "prepare"
    if current_result and item.get("reviewIssues") and not item.get("reviewIssuesResolved"):
        next_action = "review_source_differences"
    if current_operation:
        status = current_operation["data"].get("status")
        if status in {"preparing", "queued", "running"}:
            stage = "identifying" if current_operation["data"].get("kind") == "identify" else "collecting"
            next_action = "status"
        elif status in {"reconcile_required", "partial_failed", "failed", "blocked"}:
            stage, next_action = status, "inspect_original_operation"
    if not task.get("health", {}).get("ok"):
        stage, next_action = "data_inconsistent", "inspect_task_integrity"
    indexed = {source["source_id"]: source for source in task["sources"]}
    roles = operations.identification_source_roles(item) if item else {}
    value = {"ok": True, "taskKey": key, "revision": task["manifest"]["revision"],
             "title": task["manifest"]["display_name"], "stage": stage, "nextAction": next_action,
             "localId": item.get("local_id"), "snapshotId": recognition.get("snapshot_id"),
             "result": item.get("recognitionResult") if current_result else None,
             "collectionUri": collection.get("collection_uri"),
             "sources": [{"role": role, "sourceId": source_id,
                          "name": (indexed.get(source_id, {}).get("origin") or {}).get("original_name")}
                         for role, source_id in roles.items()]}
    if current_result:
        value["reviewIssues"] = item.get("reviewIssues") or []
        value["reviewIssuesResolved"] = bool(item.get("reviewIssuesResolved"))
    if current_operation:
        value["operation"] = {"id": current_operation["id"],
                              "status": current_operation["data"]["status"],
                              "message": current_operation["data"].get("message")}
    return value


class ConnectorClient:
    def __init__(self, home, request=None, start=None, upload=None):
        self.home = Path(home)
        self.request = request or request_workspace
        self.start = start or start_workspace
        self.upload = upload or upload_source

    def ensure_runtime(self):
        # Do not construct WorkspaceService here: its daemon executor would die
        # as this command exits.  Start/reuse the official persistent process.
        self.start(self.home, open_browser=False)

    def task(self, key):
        return self.request(self.home, "/api/task?" + urlencode({"key": key}))

    def report(self, key, operation=None):
        state = self.request(self.home, "/api/snapshot")
        return describe(self.task(key), state.get("operations", []), operation)

    def prepare(self, obverse, reverse, task_key=None, title=None):
        photos = [read_photo(obverse), read_photo(reverse)]
        if photos[0][2] == photos[1][2]:
            raise WorkspaceError("incomplete_pair", "正反面不能使用同一份照片，请分别提供两面的照片")
        self.ensure_runtime()
        task = self.task(task_key) if task_key else self.request(self.home, "/api/connector/create",
            {"name": title or Path(photos[0][0]).stem[:100] or "我的钱币", "timezone": "Asia/Shanghai"})
        key, source_ids = task["manifest"]["task_key"], []
        for name, content, sha256 in photos:
            matches = [source for source in task["sources"] if source["sha256"] == sha256
                       and source["byte_size"] == len(content) and source["mime_type"].startswith("image/")]
            if len(matches) > 1:
                raise WorkspaceError("source_conflict", "同一照片在原任务中有多个来源，请先核对原任务", 409)
            if matches:
                source_ids.append(matches[0]["source_id"])
            else:
                archived = self.upload(self.home, key, task["manifest"]["revision"], name, content)
                source_ids.append(archived["source"]["source_id"])
                task = self.task(key)
        task = self.request(self.home, "/api/connector/prepare", {"taskKey": key,
            "expectedRevision": task["manifest"]["revision"], "obverseSourceId": source_ids[0], "reverseSourceId": source_ids[1]})
        return describe(task)

    def status(self, key):
        self.ensure_runtime()
        return self.report(key)

    def identification_plan(self, key):
        self.ensure_runtime()
        task = self.task(key)
        item = single_item(task)
        plan = self.request(self.home, "/api/connector/identification-plan", {"taskKey": key,
            "expectedRevision": task["manifest"]["revision"], "localIds": [item["local_id"]]})
        return {**describe(task), "stage": "awaiting_identification_confirmation", "nextAction": "identify",
                "plan": plan, "confirmation": "确认后将上传这两张已归档照片并请求识别，可能消耗当前账户识别额度；实际资格以服务端为准。"}

    def identify(self, key, revision, plan_hash, command_id, confirmed=False):
        if not confirmed:
            raise WorkspaceError("confirmation_required", "请先向用户展示识别计划并取得明确确认", 409)
        self.ensure_runtime()
        task = self.task(key)
        item = single_item(task)
        operation = self.request(self.home, "/api/connector/identify", {"taskKey": key,
            "expectedRevision": revision, "planHash": plan_hash, "localIds": [item["local_id"]], "commandId": command_id})
        return self.report(key, operation)

    def collect(self, key, revision, local_id, snapshot_id, command_id, confirmed=False):
        if not confirmed:
            raise WorkspaceError("confirmation_required", "请先展示该识别结果，并取得采纳且加入收藏的明确确认", 409)
        self.ensure_runtime()
        operation = self.request(self.home, "/api/connector/collect", {"taskKey": key,
            "expectedRevision": revision, "localId": local_id, "snapshotId": snapshot_id, "commandId": command_id})
        return self.report(key, operation)


def parser():
    root = argparse.ArgumentParser(description="HeriBase 单枚钱币聊天连接器")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("prepare", "status", "identification-plan", "identify", "collect"):
        command = commands.add_parser(name)
        command.add_argument("--home", type=Path, default=Path.home())
        command.add_argument("--task-key", required=name != "prepare")
        if name == "prepare":
            command.add_argument("--obverse", type=Path, required=True)
            command.add_argument("--reverse", type=Path, required=True)
            command.add_argument("--title")
        if name in {"identify", "collect"}:
            command.add_argument("--revision", type=int, required=True)
            command.add_argument("--command-id", required=True)
            command.add_argument("--confirmed", action="store_true")
        if name == "identify":
            command.add_argument("--plan-hash", required=True)
        if name == "collect":
            command.add_argument("--local-id", required=True)
            command.add_argument("--snapshot-id", required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        client = ConnectorClient(args.home)
        if args.command == "prepare":
            result = client.prepare(args.obverse, args.reverse, args.task_key, args.title)
        elif args.command == "status":
            result = client.status(args.task_key)
        elif args.command == "identification-plan":
            result = client.identification_plan(args.task_key)
        elif args.command == "identify":
            result = client.identify(args.task_key, args.revision, args.plan_hash, args.command_id, args.confirmed)
        else:
            result = client.collect(args.task_key, args.revision, args.local_id, args.snapshot_id, args.command_id, args.confirmed)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (WorkspaceError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": getattr(exc, "code", "local_error"),
              "message": str(exc), **(exc.details if isinstance(exc, WorkspaceError) else {})}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
