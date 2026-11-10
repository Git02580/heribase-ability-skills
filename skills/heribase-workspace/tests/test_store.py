"""用真实 SQLite 验证持久化、版本冲突和宿主请求交接，不触碰用户数据库。"""
import concurrent.futures
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from workspace_store import WorkspaceStore, WorkspaceError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.now = 1000.0
        self.store = WorkspaceStore(self.home, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def bind(self, name="thread-1"):
        return self.store.bind_host("codex", name, {"inbox": True, "push": False})

    def test_entity_and_events_survive_reopen(self):
        record = self.store.save_entity("note", "coin-1", {"text": "用户原始备注"}, 0, "user:web")
        self.assertEqual(record["revision"], 1)
        reopened = WorkspaceStore(self.home)
        self.assertEqual(reopened.get_entity("note", "coin-1")["data"]["text"], "用户原始备注")
        self.assertEqual(reopened.events(0)[0]["type"], "entity.updated")
        self.assertEqual(reopened.path.name, "heribase.sqlite")
        self.assertEqual(reopened.path.stat().st_mode & 0o777, 0o600)

    def test_host_binding_stores_and_refreshes_the_conversation_title(self):
        first = self.store.bind_host(
            'codex', 'thread-1', {'inbox': True}, conversation_title='整理 batch_06 硬币资料'
        )
        refreshed = self.store.bind_host(
            'codex', 'thread-1', {'inbox': True}, conversation_title='查看收藏情况'
        )

        self.assertEqual(refreshed['id'], first['id'])
        self.assertEqual(refreshed['conversationTitle'], '查看收藏情况')
        without_title = self.store.bind_host('codex', 'thread-1', {'inbox': True})
        self.assertEqual(without_title['conversationTitle'], '查看收藏情况')

    def test_existing_host_table_is_migrated_without_losing_bindings(self):
        legacy_home = self.home / 'legacy'
        legacy_db = legacy_home / '.heribase' / 'heribase.sqlite'
        legacy_db.parent.mkdir(parents=True)
        with sqlite3.connect(str(legacy_db)) as db:
            db.execute('CREATE TABLE workspace_hosts (id TEXT PRIMARY KEY, host TEXT NOT NULL, conversation TEXT NOT NULL, capabilities TEXT NOT NULL, last_seen REAL NOT NULL, UNIQUE(host,conversation))')
            db.execute('INSERT INTO workspace_hosts VALUES (?, ?, ?, ?, ?)', ('host-existing', 'codex', 'thread-existing', '{"inbox":true}', 999.0))
            db.execute('CREATE TABLE workspace_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute("INSERT INTO workspace_meta VALUES ('schema_version', '1')")

        migrated = WorkspaceStore(legacy_home)
        host = migrated.hosts()[0]

        self.assertEqual(host['id'], 'host-existing')
        self.assertEqual(host['conversation'], 'thread-existing')
        self.assertEqual(host['conversationTitle'], '')

    def test_revision_conflict_does_not_overwrite_or_emit_event(self):
        self.store.save_entity("note", "coin-1", {"text": "first"}, 0, "user:web")
        with self.assertRaises(WorkspaceError) as error:
            self.store.save_entity("note", "coin-1", {"text": "stale"}, 0, "user:host")
        self.assertEqual(error.exception.code, "revision_conflict")
        self.assertEqual(self.store.get_entity("note", "coin-1")["data"], {"text": "first"})
        self.assertEqual(len(self.store.events(0)), 1)

    def test_shared_database_does_not_modify_history_table(self):
        with sqlite3.connect(str(self.store.path)) as db:
            db.execute("CREATE TABLE task_projection (task_id TEXT PRIMARY KEY)")
            db.execute("INSERT INTO task_projection VALUES ('cli-task')")
        WorkspaceStore(self.home).save_entity("settings", "workspace", {"autoOpen": True}, 0, "user:web")
        with sqlite3.connect(str(self.store.path)) as db:
            self.assertEqual(db.execute("SELECT task_id FROM task_projection").fetchone()[0], "cli-task")

    def test_collection_index_reads_only_active_cli_collection_records(self):
        """索引表属于 CLI；工作台只读它，并忽略取消或不完整的历史行。"""
        with self.store.connection(write=True) as db:
            db.execute(
                """CREATE TABLE task_projection (
                    task_id TEXT PRIMARY KEY, account_subject TEXT, operation TEXT, task_status TEXT,
                    created_at TEXT, completed_at TEXT, batch_id TEXT, candidate_id TEXT, collection_uri TEXT,
                    title TEXT, year TEXT, mint_mark TEXT, collection_state TEXT
                )"""
            )
            db.executemany(
                "INSERT INTO task_projection VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    ("keep", "account-a", "collection.add", "completed", "2026-09-24T09:59:00Z", "2026-09-24T10:00:00Z", "batch-a", "coin-a", "collection-a", "Coin A", "1919", "D", "active"),
                    ("update", "account-a", "collection.update", "completed", "2026-09-24T10:29:00Z", "2026-09-24T10:30:00Z", "batch-a", "coin-a", "collection-a", "Coin A revised", "1920", "S", "active"),
                    ("cancel", "account-a", "collection.cancel", "completed", "2026-09-24T10:59:00Z", "2026-09-24T11:00:00Z", "batch-a", "coin-b", "collection-b", "Coin B", "1920", None, "cancelled"),
                    ("empty", "account-a", "collection.add", "completed", "2026-09-24T11:59:00Z", "2026-09-24T12:00:00Z", "batch-a", "coin-c", "", "Coin C", "1921", None, "active"),
                    ("identify", "account-a", "identify", "completed", "2026-09-24T12:59:00Z", "2026-09-24T13:00:00Z", "batch-a", "coin-d", "collection-d", "Coin D", "1922", None, "active"),
                ],
            )
        self.assertEqual(
            self.store.collection_index(),
            [{"taskId": "update", "accountSubject": "account-a", "operation": "collection.update", "createdAt": "2026-09-24T10:29:00Z", "completedAt": "2026-09-24T10:30:00Z", "batchId": "batch-a", "candidateId": "coin-a", "collectionUri": "collection-a", "title": "Coin A revised", "year": "1920", "mintMark": "S", "collectionState": "active"}],
        )

    def test_idempotent_request_rejects_reusing_id_with_different_intent(self):
        binding = self.bind()
        request = dict(command_id="req-1", binding_id=binding["id"], task_id="task-one", intent="agent.request", payload={"message": "解释年份"}, actor="user:web")
        first = self.store.enqueue(**request)
        self.assertEqual(self.store.enqueue(**request), first)
        with self.assertRaises(WorkspaceError):
            self.store.enqueue(**{**request, "payload": {"message": "替我收藏"}})
        self.assertEqual(len(self.store.list_commands()), 1)

    def test_two_receivers_cannot_claim_the_same_delivery(self):
        binding = self.bind()
        self.store.enqueue("req-1", binding["id"], "task-1", "agent.request", {"message": "解释"}, "user:web")
        def claim(_):
            return WorkspaceStore(self.home, clock=lambda: self.now).claim(binding["id"], 30)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(claim, range(2)))
        self.assertEqual(sum(len(items) for items in result), 1)
        self.assertEqual(self.store.list_commands()[0]["status"], "received")

    def test_expired_delivery_can_be_received_again_but_stale_reply_is_rejected(self):
        binding = self.bind()
        self.store.enqueue("req-1", binding["id"], "task-1", "agent.request", {"message": "解释"}, "user:web")
        old = self.store.claim(binding["id"], 10)[0]
        self.now += 11
        new = self.store.claim(binding["id"], 10)[0]
        self.assertNotEqual(old["deliveryToken"], new["deliveryToken"])
        with self.assertRaises(WorkspaceError):
            self.store.reply(binding["id"], "req-1", old["deliveryToken"], {"message": "过期回复"})
        done = self.store.reply(binding["id"], "req-1", new["deliveryToken"], {"message": "这是建议，不会写收藏"})
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.store.claim(binding["id"], 10), [])
        self.assertEqual(self.store.reply(binding["id"], "req-1", new["deliveryToken"], done["reply"]), done)

    def test_progress_renews_delivery_and_is_visible_after_reopen(self):
        binding = self.bind()
        self.store.enqueue("req-1", binding["id"], "task-1", "task.continue", {"workflow": "collection.organize"}, "user:web")
        delivery = self.store.claim(binding["id"], 10)[0]
        self.now += 9
        running = self.store.update_command(
            binding["id"], "req-1", delivery["deliveryToken"], "running",
            {"step": "parse_spreadsheet", "message": "正在读取表格"}, 30,
        )
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["progress"]["step"], "parse_spreadsheet")
        self.now += 2
        self.assertEqual(self.store.claim(binding["id"], 10), [])
        self.assertEqual(WorkspaceStore(self.home).list_commands()[0]["progress"]["message"], "正在读取表格")

    def test_only_current_delivery_can_update_progress_and_active_work_is_not_redelivered(self):
        binding = self.bind()
        self.store.enqueue("req-1", binding["id"], "task-1", "agent.request", {"message": "继续"}, "user:web")
        delivery = self.store.claim(binding["id"], 10)[0]
        with self.assertRaises(WorkspaceError) as error:
            self.store.update_command(binding["id"], "req-1", "wrong", "running", {"message": "x"}, 30)
        self.assertEqual(error.exception.code, "delivery_conflict")
        self.store.update_command(binding["id"], "req-1", delivery["deliveryToken"], "awaiting_user", {"message": "请确认配对"}, 30)
        self.now += 31
        self.assertEqual(self.store.claim(binding["id"], 10), [])

    def test_expired_running_command_is_redelivered_for_recovery(self):
        binding = self.bind()
        self.store.enqueue("req-1", binding["id"], "task-1", "agent.request", {"message": "继续"}, "user:web")
        old = self.store.claim(binding["id"], 10)[0]
        self.store.update_command(binding["id"], "req-1", old["deliveryToken"], "running", {"message": "处理中"}, 10)
        self.now += 11
        recovered = self.store.claim(binding["id"], 10)[0]
        self.assertEqual(recovered["id"], "req-1")
        self.assertNotEqual(recovered["deliveryToken"], old["deliveryToken"])

    def test_requests_are_scoped_to_the_bound_conversation(self):
        first, second = self.bind(), self.bind("thread-2")
        self.store.enqueue("req-1", first["id"], None, "agent.request", {"message": "当前任务"}, "user:web")
        self.assertEqual(self.store.claim(second["id"], 30), [])
        self.assertEqual(len(self.store.claim(first["id"], 30)), 1)

    def test_events_resume_strictly_after_cursor_and_bound_the_page(self):
        for i in range(3):
            self.store.save_entity("note", str(i), {"text": str(i)}, 0, "user:web")
        events = self.store.events(0, limit=2)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(self.store.events(events[-1]["sequence"])), 1)

    def test_credentials_and_nonfinite_numbers_cannot_enter_business_payload(self):
        for payload in [{"accessToken": "secret"}, {"nested": {"authorization": "secret"}}, {"value": float("nan")}]:
            with self.assertRaises(WorkspaceError):
                self.store.save_entity("note", "one", payload, 0, "user:web")
        self.assertEqual(self.store.events(0), [])


if __name__ == "__main__":
    unittest.main()
