"""HTTP 边界使用本机临时服务验证，不依赖浏览器模拟或真实业务 API。"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workspace_server import create_server
from workspace_store import WorkspaceStore, WorkspaceError
from workspace_service import WorkspaceService


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.tmp.name))
        self.assets = Path(self.tmp.name) / "assets"
        self.assets.mkdir()
        (self.assets / "index.html").write_text("<h1>工作空间</h1>", encoding="utf-8")
        self.service = WorkspaceService(self.store, background=False)
        self.server = create_server(self.store, self.assets, browser_key="browser-key", host_key="host-key", service=self.service)
        self.port = self.server.server_address[1]
        self.origin = "http://127.0.0.1:" + str(self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, body=None, key="browser-key", method=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json", "Origin": self.origin}
        request_headers.update(headers or {})
        connection.request(method or ("POST" if body is not None else "GET"), path,
                           body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None, request_headers)
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw.decode()
        status = response.status
        connection.close()
        return status, result

    def test_snapshot_has_real_empty_state_and_auth_is_required(self):
        self.assertEqual(self.request("/api/snapshot", key="wrong")[0], 401)
        status, data = self.request("/api/snapshot")
        self.assertEqual(status, 200)
        self.assertEqual(data["commands"], [])
        self.assertEqual(data["hosts"], [])
        self.assertEqual(data["queryLogs"], [])
        self.assertEqual(data["schemaVersion"], 1)

    def test_account_profile_is_browser_only_and_never_archived(self):
        calls = []

        def runner(argv):
            calls.append(argv)
            return json.dumps({"authenticated": True, "provider": "google", "nickname": " Carlos Puig ",
                               "avatarUrl": "https://lh3.googleusercontent.com/a/demo",
                               "email": "private@example.test", "accessToken": "private-token"})

        self.service.executor.runner = runner
        self.assertEqual(self.request("/api/account-profile", key="wrong")[0], 401)
        self.assertEqual(self.request("/api/account-profile", key="host-key")[0], 403)
        self.assertEqual(calls, [])
        self.assertEqual(self.request("/api/account-profile"), (200, {
            "authenticated": True, "provider": "google", "nickname": "Carlos Puig",
            "avatarUrl": "https://lh3.googleusercontent.com/a/demo",
        }))
        self.assertEqual(calls, [["api", "profile"]])
        self.assertEqual(self.store.list_entities("cli-query-log"), [])

    def test_account_profile_drops_untrusted_avatar_and_supports_older_cli(self):
        self.service.executor.runner = lambda argv: json.dumps({
            "authenticated": True, "provider": "apple", "avatarUrl": "https://untrusted.example/avatar.png",
        })
        self.assertEqual(self.request("/api/account-profile"), (200, {"authenticated": True, "provider": "apple"}))
        self.service.executor.runner = lambda argv: (json.dumps({"authenticated": False, "accountSubject": "private"})
                                                     if argv == ["status"] else "unsupported command")
        self.assertEqual(self.request("/api/account-profile"), (200, {"authenticated": False}))

    def test_foreign_origin_and_rebinding_host_are_rejected(self):
        self.assertEqual(self.request("/api/snapshot", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/health", headers={"Host": "evil.example"})[0], 403)

    def test_payment_return_is_a_local_read_only_landing_page(self):
        status, page = self.request("/payment-return?result=success", key="no-session")
        self.assertEqual(status, 200)
        self.assertIn("工作台会自动查询订单状态", page)
        status, cancelled = self.request("/payment-return?result=cancel", key="no-session")
        self.assertEqual(status, 200)
        self.assertIn("已离开支付流程", cancelled)

    def test_browser_cannot_call_host_tools_or_supply_actor(self):
        self.assertEqual(self.request("/api/bridge/bind", {"host": "codex", "conversation": "thread"})[0], 403)
        self.assertEqual(self.request("/api/entities", {"kind": "note", "id": "coin-1", "data": {"text": "fake"}, "expectedRevision": 0, "actor": "user:host"})[0], 400)
        self.assertEqual(self.store.list_entities("note"), [])

    def test_connector_host_uploads_only_local_task_bytes_with_host_provenance(self):
        _, task = self.request("/api/tasks/create", {"name": "宿主照片", "timezone": "Asia/Shanghai"})
        key = task["manifest"]["task_key"]
        revision = task["manifest"]["revision"]
        status, result = self.request(
            "/api/upload?" + urlencode({"task": key, "revision": revision, "name": "front.png"}),
            b"host-photo-bytes", key="host-key", headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["source"]["source_id"])
        _, snapshot = self.request("/api/task?" + urlencode({"key": key}))
        self.assertEqual(len(snapshot["sources"]), 1)
        self.assertTrue(snapshot["health"]["ok"])
        self.assertEqual(self.store.events(0)[-1]["actor"], "agent:connector")
        self.assertEqual(self.request("/api/commerce/upload?name=photo.png", b"bytes", key="host-key",
                                      headers={"Content-Type": "application/octet-stream"})[0], 403)
        self.assertEqual(self.request("/api/upload?" + urlencode({"task": key, "revision": snapshot["manifest"]["revision"], "name": "../auth.json"}),
                                      b"bytes", key="host-key", headers={"Content-Type": "application/octet-stream"})[0], 400)

    def test_saves_use_revision_guard_and_emit_an_event(self):
        body = {"kind": "note", "id": "coin-1", "data": {"text": "saved"}, "expectedRevision": 0}
        self.assertEqual(self.request("/api/entities", body)[0], 200)
        status, conflict = self.request("/api/entities", {**body, "data": {"text": "stale"}})
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"]["code"], "revision_conflict")
        self.assertEqual(self.request("/api/events?after=0")[1]["events"][0]["type"], "entity.updated")

    def test_missing_side_upload_is_bound_to_the_selected_coin_without_auto_organization(self):
        _, task = self.request("/api/tasks/create", {"name": "补图", "timezone": "Asia/Shanghai"})
        key = task["manifest"]["task_key"]
        _, source = self.request("/api/upload?" + urlencode({"task": key, "revision": task["manifest"]["revision"], "name": "front.png"}),
                                 b"front", key="host-key", headers={"Content-Type": "application/octet-stream"})
        _, task = self.request("/api/tasks/candidate", {"taskKey": key, "expectedRevision": source["revision"], "sourceIds": [source["source"]["source_id"]], "title": "待补图"})
        local_id = task["items"][0]["local_id"]
        _, task = self.request("/api/tasks/pair", {"taskKey": key, "expectedRevision": task["manifest"]["revision"], "localId": local_id,
                                                  "action": "need_photo", "assignments": [{"sourceId": source["source"]["source_id"], "role": "obverse"}]})
        path = "/api/connector/photo?" + urlencode({"task": key, "revision": task["manifest"]["revision"], "localId": local_id, "side": "reverse", "name": "back.png"})
        self.assertEqual(self.request(path, b"back", key="host-key", headers={"Content-Type": "application/octet-stream"})[0], 403)
        status, result = self.request(path, b"back", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200)
        self.assertEqual(result["revision"], task["manifest"]["revision"] + 1)
        current = self.service.tasks.snapshot(key)
        self.assertEqual(len(current["items"]), 1)
        self.assertEqual(current["items"][0]["organization"]["pairing_state"], "confirmed")
        self.assertTrue(current["health"]["ok"])
        self.assertIsNone(self.store.get_entity("organization", key))
        self.assertEqual(self.store.list_entities("operation"), [])
        self.assertEqual(self.request(path, b"back-again", headers={"Content-Type": "application/octet-stream"})[0], 409)
        self.assertEqual(len(self.service.tasks.snapshot(key)["sources"]), 2)

    def test_editor_stage_then_save_completes_unknown_single_photo_without_auto_organization(self):
        _, task = self.request("/api/tasks/create", {"name": "页内调整", "timezone": "Asia/Shanghai"})
        key = task["manifest"]["task_key"]
        _, initial = self.request("/api/upload?" + urlencode({"task": key, "revision": task["manifest"]["revision"], "name": "unknown.png"}),
            b"unknown-side", key="host-key", headers={"Content-Type": "application/octet-stream"})
        _, task = self.request("/api/tasks/candidate", {"taskKey": key, "expectedRevision": initial["revision"],
            "sourceIds": [initial["source"]["source_id"]], "title": "待选择方向"})
        local_id = task["items"][0]["local_id"]
        self.assertEqual(task["items"][0]["evidence"][0]["role"], "unknown")
        path = "/api/connector/photo?" + urlencode({"task": key, "revision": task["manifest"]["revision"],
            "localId": local_id, "mode": "stage", "name": "new-front.png"})
        status, staged = self.request(path, b"new-front", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200)
        self.assertEqual(staged["revision"], task["manifest"]["revision"] + 1)
        current = self.service.tasks.snapshot(key)
        self.assertEqual(current["items"][0]["evidence"], task["items"][0]["evidence"])
        self.assertIsNone(self.store.get_entity("organization", key))
        status, saved = self.request("/api/connector/photos", {"taskKey": key, "expectedRevision": staged["revision"],
            "localId": local_id, "obverseSourceId": staged["source"]["source_id"], "reverseSourceId": initial["source"]["source_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(saved["manifest"]["revision"], staged["revision"] + 1)
        self.assertEqual(saved["items"][0]["organization"]["source_assignment"], [
            {"source_id": staged["source"]["source_id"], "role": "obverse"},
            {"source_id": initial["source"]["source_id"], "role": "reverse"}])
        self.assertEqual(saved["items"][0]["organization"]["pairing_state"], "confirmed")
        self.assertTrue(saved["health"]["ok"])
        self.assertIsNone(self.store.get_entity("organization", key))
        self.assertEqual(self.store.list_entities("operation"), [])

    def test_editor_stage_rejects_host_mixed_mode_and_pending_organization_without_archiving(self):
        _, task = self.request("/api/tasks/create", {"name": "暂存边界", "timezone": "Asia/Shanghai"})
        key = task["manifest"]["task_key"]
        _, initial = self.request("/api/upload?" + urlencode({"task": key, "revision": task["manifest"]["revision"], "name": "one.png"}),
            b"one", key="host-key", headers={"Content-Type": "application/octet-stream"})
        _, task = self.request("/api/tasks/candidate", {"taskKey": key, "expectedRevision": initial["revision"],
            "sourceIds": [initial["source"]["source_id"]], "title": "暂存对象"})
        query = {"task": key, "revision": task["manifest"]["revision"], "localId": task["items"][0]["local_id"],
                 "mode": "stage", "name": "other.png"}
        path = "/api/connector/photo?" + urlencode(query)
        self.assertEqual(self.request(path, b"other", key="host-key", headers={"Content-Type": "application/octet-stream"})[0], 403)
        for extra in [{"side": "reverse"}, {"mode": "unknown"}]:
            self.assertEqual(self.request("/api/connector/photo?" + urlencode({**query, **extra}), b"other",
                headers={"Content-Type": "application/octet-stream"})[0], 400)
        self.store.save_entity("organization", key, {"status": "running"}, 0, "system:test")
        status, error = self.request(path, b"other", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "organization_pending")
        self.assertEqual(self.service.tasks.snapshot(key)["manifest"]["revision"], task["manifest"]["revision"])
        self.assertEqual(len(self.service.tasks.snapshot(key)["sources"]), 1)

    def test_browser_upload_is_durably_queued_and_a_queue_conflict_does_not_lose_the_upload_receipt(self):
        _, task = self.request("/api/tasks/create", {"name": "自动整理归档", "timezone": "Asia/Shanghai"})
        key = task["manifest"]["task_key"]
        path = "/api/upload?" + urlencode({"task": key, "revision": task["manifest"]["revision"], "name": "front.png"})
        status, result = self.request(path, b"original bytes", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200)
        job = self.store.get_entity("organization", key)
        self.assertEqual(job["data"]["status"], "queued")
        self.assertEqual(job["data"]["sourceIds"], [result["source"]["source_id"]])
        path = "/api/upload?" + urlencode({"task": key, "revision": result["revision"], "name": "back.png"})
        with patch.object(self.service.organizer, "enqueue", side_effect=WorkspaceError("revision_conflict", "资料已更新")):
            status, result = self.request(path, b"second original", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200)
        self.assertTrue(result["source"]["source_id"])
        self.assertEqual(result["organizationWarning"]["code"], "revision_conflict")
        self.assertEqual(len(self.service.tasks.snapshot(key)["sources"]), 2)

    def test_browser_can_append_during_analysis_and_obsolete_scope_never_commits(self):
        from test_organizer import photo, analysis
        started, release = threading.Event(), threading.Event()
        catalogs = []
        def runner(catalog, *_):
            catalogs.append([entry["sourceId"] for entry in catalog])
            if len(catalogs) == 1:
                started.set()
                release.wait(8)
            return analysis(catalogs[-1], len(catalog) == 1)
        self.service.organizer.runner = runner
        _, task = self.request("/api/tasks/create", {"name": "整理中追加", "timezone": "Asia/Shanghai"})
        key = task["manifest"]["task_key"]
        _, first = self.request("/api/upload?" + urlencode({"task": key, "revision": task["manifest"]["revision"], "name": "front.png"}),
            photo(), headers={"Content-Type": "application/octet-stream"})
        _, job = self.request("/api/connector/organize", {"taskKey": key, "expectedRevision": first["revision"]})
        worker = threading.Thread(target=self.service.organizer.run_job, args=(key,))
        worker.start()
        try:
            self.assertTrue(started.wait(5))
            current = self.service.tasks.snapshot(key)
            status, second = self.request("/api/upload?" + urlencode({"task": key, "revision": current["manifest"]["revision"], "name": "back.png"}),
                photo(), headers={"Content-Type": "application/octet-stream"})
            self.assertEqual(status, 200)
            self.assertNotEqual(second["source"]["source_id"], first["source"]["source_id"])
            queued = self.service.tasks.snapshot(key)
            self.assertEqual(queued["organization"]["status"], "queued")
            self.assertNotEqual(queued["organization"]["jobId"], job["data"]["jobId"])
            self.assertEqual(queued["organization"]["sourceIds"], [first["source"]["source_id"], second["source"]["source_id"]])
        finally:
            release.set()
            worker.join(8)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.service.tasks.snapshot(key)["items"], [])
        self.service.organizer.run_job(key)
        final = self.service.tasks.snapshot(key)
        self.assertEqual(final["organization"]["status"], "completed")
        self.assertEqual([len(catalog) for catalog in catalogs], [1, 2])
        self.assertEqual(len(final["items"]), 1)
        self.assertEqual(len(final["sources"]), 2)
        self.assertTrue(final["health"]["ok"])
        self.assertEqual(self.store.list_entities("operation"), [])

    def test_stale_append_conflict_precedes_archive_and_latest_revision_retry_adds_once(self):
        _, task = self.request("/api/tasks/create", {"name": "追加版本竞态", "timezone": "Asia/Shanghai"})
        key = task["manifest"]["task_key"]
        _, first = self.request("/api/upload?" + urlencode({"task": key, "revision": task["manifest"]["revision"], "name": "one.png"}),
            b"first", key="host-key", headers={"Content-Type": "application/octet-stream"})
        self.service.tasks.ingest(key, first["revision"], "other.png", b"other", "user:web")
        before = self.service.tasks.snapshot(key)
        status, error = self.request("/api/upload?" + urlencode({"task": key, "revision": first["revision"], "name": "append.png"}),
            b"new-photo", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "revision_conflict")
        current = self.service.tasks.snapshot(key)
        self.assertEqual(current["manifest"]["revision"], before["manifest"]["revision"])
        self.assertEqual(current["sources"], before["sources"])
        status, receipt = self.request("/api/upload?" + urlencode({"task": key, "revision": current["manifest"]["revision"], "name": "append.png"}),
            b"new-photo", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.service.tasks.snapshot(key)["sources"]), len(before["sources"]) + 1)
        self.assertEqual(self.service.tasks.source(key, receipt["source"]["source_id"])[0], b"new-photo")

    def test_bidirectional_request_and_reply_are_visible_in_the_same_snapshot(self):
        status, host = self.request("/api/bridge/bind", {
            "host": "codex", "conversation": "thread-1", "conversationTitle": "整理 batch_06 硬币资料",
        }, key="host-key")
        self.assertEqual(status, 200)
        self.assertEqual(host["conversationTitle"], "整理 batch_06 硬币资料")
        self.request("/api/requests", {"commandId": "req-1", "bindingId": host["id"], "taskId": None, "message": "请解释这枚钱币"})
        status, inbox = self.request("/api/bridge/inbox", {"bindingId": host["id"]}, key="host-key")
        self.assertEqual(status, 200)
        delivery = inbox["commands"][0]
        self.assertEqual(self.request("/api/bridge/reply", {"bindingId": host["id"], "commandId": "req-1", "deliveryToken": delivery["deliveryToken"], "message": "这是说明，没有执行写操作"}, key="host-key")[0], 200)
        command = self.request("/api/snapshot")[1]["commands"][0]
        self.assertEqual(command["reply"]["message"], "这是说明，没有执行写操作")
        self.assertNotIn("deliveryToken", command)

    def test_structured_continuation_can_report_progress_before_final_reply(self):
        status, host = self.request("/api/bridge/bind", {"host": "codex", "conversation": "thread-1"}, key="host-key")
        self.assertEqual(status, 200)
        request = {
            "commandId": "continue-1", "bindingId": host["id"], "taskId": "task-1",
            "intent": "task.continue", "message": "解析表格并停在配对审核",
            "payload": {"workflow": "collection.organize", "steps": ["parse_spreadsheet", "build_table_candidates", "associate_obverse_reverse_images"],
                        "stopAfter": "pairing_review", "expectedRevision": 2},
        }
        self.assertEqual(self.request("/api/requests", request)[0], 200)
        delivery = self.request("/api/bridge/inbox", {"bindingId": host["id"], "leaseSeconds": 60}, key="host-key")[1]["commands"][0]
        status, running = self.request("/api/bridge/progress", {
            "bindingId": host["id"], "commandId": delivery["id"], "deliveryToken": delivery["deliveryToken"],
            "status": "running", "step": "parse_spreadsheet", "message": "正在读取表格",
        }, key="host-key")
        self.assertEqual(status, 200)
        self.assertEqual(running["progress"]["step"], "parse_spreadsheet")
        status, done = self.request("/api/bridge/reply", {"bindingId": host["id"], "commandId": delivery["id"],
            "deliveryToken": delivery["deliveryToken"], "message": "已建立候选，停在配对审核"}, key="host-key")
        self.assertEqual(status, 200)
        self.assertEqual(done["status"], "completed")

    def test_browser_cannot_enqueue_arbitrary_continuation_steps(self):
        status, host = self.request("/api/bridge/bind", {"host": "codex", "conversation": "thread-1"}, key="host-key")
        self.assertEqual(status, 200)
        status, error = self.request("/api/requests", {
            "commandId": "continue-unsafe", "bindingId": host["id"], "taskId": "task-1", "intent": "task.continue", "message": "运行脚本",
            "payload": {"workflow": "collection.organize", "steps": ["run_shell"], "stopAfter": "pairing_review", "expectedRevision": 1},
        })
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "invalid_continuation")

    def test_only_workbench_can_request_retry_of_explicitly_failed_items(self):
        self.assertEqual(self.request("/api/operations/resume", {"operationId": "missing"}, key="host-key")[0], 403)
        status, error = self.request("/api/operations/resume", {"operationId": "missing"})
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "invalid_recovery")

    def test_static_allowlist_does_not_serve_symlinks_or_traversal(self):
        secret = Path(self.tmp.name) / "private.txt"
        secret.write_text("not-public")
        (self.assets / "app.js").symlink_to(secret)
        for path in ["/../private.txt", "/%2e%2e/private.txt", "/app.js", "/private.txt"]:
            self.assertIn(self.request(path)[0], [400, 403, 404])
        self.assertEqual(self.request("/")[0], 200)

    def test_bridge_contract_module_is_served_to_the_workbench(self):
        (self.assets / "bridge.js").write_text("export const bridge = true;", encoding="utf-8")
        status, source = self.request("/bridge.js")
        self.assertEqual(status, 200)
        self.assertIn("bridge", source)

    def test_http_task_upload_candidate_and_pairing_are_persisted(self):
        status, task = self.request("/api/tasks/create", {"name": "照片整理", "timezone": "Asia/Shanghai"})
        self.assertEqual(status, 200)
        key = task["manifest"]["task_key"]
        source_ids = []
        revision = 1
        for name in ["front.png", "back.png"]:
            status, result = self.request("/api/upload?" + urlencode({"task": key, "revision": revision, "name": name}),
                                          name.encode(), headers={"Content-Type": "application/octet-stream"})
            self.assertEqual(status, 200)
            source_ids.append(result["source"]["source_id"])
            revision = result["revision"]
        status, task = self.request("/api/tasks/candidate", {"taskKey": key, "expectedRevision": revision, "sourceIds": source_ids, "title": "待识别"})
        self.assertEqual(status, 200)
        item = task["items"][0]
        status, task = self.request("/api/tasks/pair", {"taskKey": key, "expectedRevision": task["manifest"]["revision"], "localId": item["local_id"],
            "action": "confirm_pair", "assignments": [{"sourceId": source_ids[0], "role": "obverse"}, {"sourceId": source_ids[1], "role": "reverse"}]})
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/task?" + urlencode({"key": key}))[1]["items"][0]["organization"]["pairing_state"], "confirmed")
        status, media = self.request("/api/media?" + urlencode({"task": key, "source": source_ids[0]}))
        self.assertEqual(status, 200)
        self.assertEqual(media, "front.png")

    def test_unknown_fields_and_large_json_fail_without_side_effects(self):
        self.assertEqual(self.request("/api/entities", {"kind": "arbitrary", "id": "x", "data": {}, "expectedRevision": 0})[0], 400)
        # 根据声明长度立即拒绝，不要求服务先把整个超限请求读入内存。
        self.assertEqual(self.request("/api/entities", method="POST", headers={"Content-Length": str(1024 * 1024 + 1)})[0], 413)
        self.assertEqual(self.store.events(0), [])


if __name__ == "__main__":
    unittest.main()
