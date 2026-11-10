"""工作空间持久层：SQLite 事实、乐观版本、事件游标与宿主交接队列。

本模块不执行 CLI，也不授予线上写权限。队列租约只保证一条请求在某段时间
交给一个宿主接收；远端执行另有计划和核验记录，不能因租约过期自动重做。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional


class WorkspaceError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400, **details: Any):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details


def safe_json(value: Any) -> str:
    """禁止在业务快照保存凭据；拒绝 NaN 等不能跨 Python/JS 稳定哈希的值。"""
    sensitive = {"authorization", "cookie", "setcookie", "accesstoken", "refreshtoken", "password", "secret", "privatekey"}

    def check(item: Any, depth: int = 0) -> None:
        if depth > 40:
            raise WorkspaceError("invalid_payload", "数据层级过深")
        if isinstance(item, dict):
            for key, val in item.items():
                if not isinstance(key, str) or re.sub(r"[^a-z]", "", key.lower()) in sensitive:
                    raise WorkspaceError("sensitive_payload", "业务数据不能包含认证凭据")
                check(val, depth + 1)
        elif isinstance(item, list):
            for val in item:
                check(val, depth + 1)

    check(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise WorkspaceError("invalid_payload", "数据必须是有效 JSON") from exc
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise WorkspaceError("payload_too_large", "单条业务数据不能超过 1 MiB", 413)
    return encoded


def identifier(value: Any, label: str = "标识") -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise WorkspaceError("invalid_identifier", label + "无效")
    return value


class WorkspaceStore:
    def __init__(self, home: Path, clock: Callable[[], float] = time.time):
        self.directory = Path(home).expanduser() / ".heribase"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise WorkspaceError("unsafe_path", "工作空间目录不能是符号链接")
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "heribase.sqlite"
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise WorkspaceError("unsafe_path", "数据库必须是普通文件")
        self.clock = clock
        # 每次请求独立连接；不在 HTTP 线程之间共享 sqlite connection。
        with self.connection() as db:
            os.chmod(self.path, 0o600)
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspace_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_entities (
                    kind TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                    data TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS workspace_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,
                    entity_kind TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER,
                    actor TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_hosts (
                    id TEXT PRIMARY KEY, host TEXT NOT NULL, conversation TEXT NOT NULL,
                    conversation_title TEXT NOT NULL DEFAULT '',
                    capabilities TEXT NOT NULL, last_seen REAL NOT NULL,
                    UNIQUE(host,conversation));
                CREATE TABLE IF NOT EXISTS workspace_commands (
                    id TEXT PRIMARY KEY, binding_id TEXT NOT NULL REFERENCES workspace_hosts(id),
                    task_id TEXT, intent TEXT NOT NULL, payload TEXT NOT NULL, actor TEXT NOT NULL,
                    digest TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, lease_until REAL, delivery_token TEXT,
                    deliveries INTEGER NOT NULL DEFAULT 0, reply TEXT, progress TEXT);
                CREATE INDEX IF NOT EXISTS workspace_commands_inbox ON workspace_commands(binding_id,status,lease_until);
            """
            )
            # 工作空间在用户目录中长期保留。这里仅做可逆的追加列迁移，不能因
            # 交接状态升级要求用户删除既有任务或重新导入资料。
            columns = {row["name"] for row in db.execute("PRAGMA table_info(workspace_commands)")}
            if "progress" not in columns:
                db.execute("ALTER TABLE workspace_commands ADD COLUMN progress TEXT")
            # 会话标题仅用于工作台中区分宿主会话；旧绑定保留原 ID，并以空标题兼容迁移。
            host_columns = {row["name"] for row in db.execute("PRAGMA table_info(workspace_hosts)")}
            if "conversation_title" not in host_columns:
                db.execute("ALTER TABLE workspace_hosts ADD COLUMN conversation_title TEXT NOT NULL DEFAULT ''")
            version = db.execute("SELECT value FROM workspace_meta WHERE key='schema_version'").fetchone()
            if version is not None and version[0] != "1":
                raise WorkspaceError("unsupported_schema", "工作空间由更新版本创建，请升级工作台", 409)
            db.execute("INSERT OR IGNORE INTO workspace_meta VALUES ('schema_version','1')")
            db.commit()

    @contextmanager
    def connection(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()

    def _event(self, db: sqlite3.Connection, event_type: str, kind: str, entity_id: str, revision: Optional[int], actor: str, data: Any) -> None:
        db.execute(
            "INSERT INTO workspace_events(type,entity_kind,entity_id,revision,actor,data,created_at) VALUES (?,?,?,?,?,?,?)",
            (event_type, kind, entity_id, revision, actor, safe_json(data), self.timestamp()),
        )

    def emit(self, event_type: str, kind: str, entity_id: str, actor: str, data: Any) -> None:
        with self.connection(write=True) as db:
            self._event(db, identifier(event_type), identifier(kind), identifier(entity_id), None, identifier(actor), data)

    @staticmethod
    def _entity(row: sqlite3.Row) -> Dict[str, Any]:
        return {"kind": row["kind"], "id": row["id"], "revision": row["revision"], "data": json.loads(row["data"]), "updatedAt": row["updated_at"]}

    def get_entity(self, kind: str, entity_id: str) -> Optional[Dict[str, Any]]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM workspace_entities WHERE kind=? AND id=?", (kind, entity_id)).fetchone()
            return self._entity(row) if row else None

    def list_entities(self, kind: str) -> List[Dict[str, Any]]:
        with self.connection() as db:
            return [self._entity(row) for row in db.execute("SELECT * FROM workspace_entities WHERE kind=? ORDER BY updated_at DESC,id", (kind,))]

    def collection_index(self) -> List[Dict[str, Any]]:
        """读取 CLI 维护的收藏投影，但绝不由工作台创建或修改这张表。

        ``task_projection`` 是 CLI 对已完成远程动作的可重建索引；任务包仍是图片、
        审核和原始回执的事实来源。旧工作空间或独立测试库可能没有该表，此时返回
        空列表，让藏品库安全回退到任务包里的已验证收藏投影。
        """
        required = {
            "task_id",
            "account_subject",
            "operation",
            "task_status",
            "created_at",
            "completed_at",
            "batch_id",
            "candidate_id",
            "collection_uri",
            "title",
            "year",
            "mint_mark",
            "collection_state",
        }
        with self.connection() as db:
            table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_projection'").fetchone()
            if table is None:
                return []
            columns = {row["name"] for row in db.execute("PRAGMA table_info(task_projection)")}
            if not required.issubset(columns):
                return []
            rows = db.execute(
                """
                SELECT task_id AS taskId, account_subject AS accountSubject, operation, created_at AS createdAt, completed_at AS completedAt,
                       batch_id AS batchId, candidate_id AS candidateId, collection_uri AS collectionUri,
                       title, year, mint_mark AS mintMark, collection_state AS collectionState
                  FROM task_projection
                 WHERE operation IN ('collection.add', 'collection.update', 'collection.cancel')
                   AND task_status='completed'
                   AND collection_uri IS NOT NULL
                   AND trim(collection_uri) <> ''
                 ORDER BY COALESCE(completed_at, created_at) DESC, task_id DESC
                """
            ).fetchall()
        # 同一 collection URI 的后续 update / cancel 会产生新的 CLI task。先按账户和
        # URI 收敛到最新投影，再只返回 active，避免取消后仍被早期 add 行“复活”。
        newest = {}
        for row in rows:
            value = {key: row[key] for key in row.keys()}
            newest.setdefault((value["accountSubject"], value["collectionUri"]), value)
        return [value for value in newest.values() if value["collectionState"] == "active"]

    def save_entity(self, kind: str, entity_id: str, data: Any, expected_revision: int, actor: str) -> Dict[str, Any]:
        identifier(kind)
        identifier(entity_id)
        identifier(actor)
        if type(expected_revision) is not int or expected_revision < 0:
            raise WorkspaceError("invalid_revision", "必须提供当前版本")
        encoded = safe_json(data)
        with self.connection(write=True) as db:
            old = db.execute("SELECT * FROM workspace_entities WHERE kind=? AND id=?", (kind, entity_id)).fetchone()
            revision = old["revision"] if old else 0
            if revision != expected_revision:
                raise WorkspaceError("revision_conflict", "记录已在其他页面或聊天更新，请检查差异后再保存", 409, current=self._entity(old) if old else None)
            db.execute(
                "INSERT INTO workspace_entities VALUES (?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET revision=excluded.revision,data=excluded.data,updated_at=excluded.updated_at",
                (kind, entity_id, revision + 1, encoded, self.timestamp()),
            )
            self._event(db, "entity.updated", kind, entity_id, revision + 1, actor, {"previousRevision": revision})
            return self._entity(db.execute("SELECT * FROM workspace_entities WHERE kind=? AND id=?", (kind, entity_id)).fetchone())

    def events(self, after: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise WorkspaceError("invalid_cursor", "事件游标或页大小无效")
        with self.connection() as db:
            return [
                {
                    "sequence": row["sequence"],
                    "type": row["type"],
                    "entityKind": row["entity_kind"],
                    "entityId": row["entity_id"],
                    "revision": row["revision"],
                    "actor": row["actor"],
                    "data": json.loads(row["data"]),
                    "createdAt": row["created_at"],
                }
                for row in db.execute("SELECT * FROM workspace_events WHERE sequence>? ORDER BY sequence LIMIT ?", (after, limit))
            ]

    def cursor(self) -> int:
        with self.connection() as db:
            return db.execute("SELECT COALESCE(MAX(sequence),0) FROM workspace_events").fetchone()[0]

    def _host(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "host": row["host"],
            "conversation": row["conversation"],
            "conversationTitle": row["conversation_title"],
            "capabilities": json.loads(row["capabilities"]),
            "lastSeen": row["last_seen"],
            "connected": self.clock() - row["last_seen"] < 90,
        }

    def bind_host(self, host: str, conversation: str, capabilities: Dict[str, Any], conversation_title: str = "") -> Dict[str, Any]:
        identifier(host)
        identifier(conversation)
        if not isinstance(conversation_title, str) or len(conversation_title) > 200:
            raise WorkspaceError("invalid_title", "会话标题无效")
        conversation_title = conversation_title.strip()
        encoded = safe_json(capabilities)
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO workspace_hosts (id,host,conversation,conversation_title,capabilities,last_seen) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(host,conversation) DO UPDATE SET "
                "conversation_title=CASE WHEN excluded.conversation_title='' THEN workspace_hosts.conversation_title ELSE excluded.conversation_title END,"
                "capabilities=excluded.capabilities,last_seen=excluded.last_seen",
                ("host_" + secrets.token_hex(12), host, conversation, conversation_title, encoded, self.clock()),
            )
            row = db.execute("SELECT * FROM workspace_hosts WHERE host=? AND conversation=?", (host, conversation)).fetchone()
            self._event(db, "host.bound", "host", row["id"], None, "host:" + host, {"conversation": conversation, "conversationTitle": conversation_title})
            return self._host(row)

    def hosts(self) -> List[Dict[str, Any]]:
        with self.connection() as db:
            return [self._host(row) for row in db.execute("SELECT * FROM workspace_hosts ORDER BY last_seen DESC")]

    @staticmethod
    def _command(row: sqlite3.Row, delivery: bool = False) -> Dict[str, Any]:
        value = {
            "id": row["id"],
            "bindingId": row["binding_id"],
            "taskId": row["task_id"],
            "intent": row["intent"],
            "payload": json.loads(row["payload"]),
            "actor": row["actor"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "deliveries": row["deliveries"],
            "reply": json.loads(row["reply"]) if row["reply"] else None,
            "progress": json.loads(row["progress"]) if row["progress"] else None,
        }
        if delivery:
            value.update(deliveryToken=row["delivery_token"], leaseUntil=row["lease_until"])
        return value

    def enqueue(self, command_id: str, binding_id: str, task_id: Optional[str], intent: str, payload: Any, actor: str) -> Dict[str, Any]:
        for value in (command_id, binding_id, intent, actor):
            identifier(value)
        if task_id is not None:
            identifier(task_id)
        encoded = safe_json(payload)
        digest = hashlib.sha256(safe_json([binding_id, task_id, intent, payload, actor]).encode("utf-8")).hexdigest()
        with self.connection(write=True) as db:
            old = db.execute("SELECT * FROM workspace_commands WHERE id=?", (command_id,)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise WorkspaceError("idempotency_conflict", "请求标识已被不同内容使用", 409)
                return self._command(old)
            if not db.execute("SELECT 1 FROM workspace_hosts WHERE id=?", (binding_id,)).fetchone():
                raise WorkspaceError("host_not_found", "先连接一个宿主会话", 404)
            now = self.timestamp()
            db.execute(
                "INSERT INTO workspace_commands(id,binding_id,task_id,intent,payload,actor,digest,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'pending',?,?)",
                (command_id, binding_id, task_id, intent, encoded, actor, digest, now, now),
            )
            self._event(db, "command.pending", "command", command_id, None, actor, {"bindingId": binding_id})
            return self._command(db.execute("SELECT * FROM workspace_commands WHERE id=?", (command_id,)).fetchone())

    def list_commands(self, limit: int = 100) -> List[Dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise WorkspaceError("invalid_limit", "请求列表页大小无效")
        with self.connection() as db:
            return [self._command(row) for row in db.execute("SELECT * FROM workspace_commands ORDER BY created_at DESC,id LIMIT ?", (limit,))]

    def claim(self, binding_id: str, lease_seconds: int = 60) -> List[Dict[str, Any]]:
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise WorkspaceError("invalid_lease", "接收租约必须在 1–300 秒之间")
        with self.connection(write=True) as db:
            if not db.execute("SELECT 1 FROM workspace_hosts WHERE id=?", (binding_id,)).fetchone():
                raise WorkspaceError("host_not_found", "宿主绑定不存在", 404)
            db.execute("UPDATE workspace_hosts SET last_seen=? WHERE id=?", (self.clock(), binding_id))
            # `running` 也可能因宿主崩溃失去续租；到期后应交由同一绑定恢复。
            # `awaiting_user` 没有租约，代表明确的人工停靠点，不能自动重投。
            rows = db.execute(
                "SELECT id FROM workspace_commands WHERE binding_id=? AND (status='pending' OR (status IN ('received','running') AND lease_until<=?)) ORDER BY created_at,id LIMIT 10",
                (binding_id, self.clock()),
            ).fetchall()
            result = []
            for row in rows:
                token = secrets.token_urlsafe(24)
                db.execute(
                    "UPDATE workspace_commands SET status='received',lease_until=?,delivery_token=?,deliveries=deliveries+1,updated_at=? WHERE id=?",
                    (self.clock() + lease_seconds, token, self.timestamp(), row["id"]),
                )
                self._event(db, "command.received", "command", row["id"], None, "host:" + binding_id, {})
                result.append(self._command(db.execute("SELECT * FROM workspace_commands WHERE id=?", (row["id"],)).fetchone(), delivery=True))
            return result

    def update_command(self, binding_id: str, command_id: str, delivery_token: str, status: str, progress: Dict[str, Any], lease_seconds: int = 60) -> Dict[str, Any]:
        """记录宿主可见进度，并在处理期间续租避免同一命令被重复领取。

        `awaiting_user` 表示本次处理已停在人工决策点，因此移除租约；它不是
        “宿主离线”，也不会在超时后被另一执行器重新投递。
        """
        if status not in {"running", "awaiting_user"}:
            raise WorkspaceError("invalid_command_status", "进度状态只能是处理中或等待用户确认")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise WorkspaceError("invalid_lease", "接收租约必须在 1–300 秒之间")
        encoded = safe_json(progress)
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM workspace_commands WHERE id=? AND binding_id=?", (command_id, binding_id)).fetchone()
            if not row:
                raise WorkspaceError("request_not_found", "请求不属于当前宿主会话", 404)
            if not isinstance(delivery_token, str) or not secrets.compare_digest(row["delivery_token"] or "", delivery_token):
                raise WorkspaceError("delivery_conflict", "接收凭据已过期或不匹配", 409)
            if row["status"] not in {"received", "running"} or row["lease_until"] is None or row["lease_until"] <= self.clock():
                raise WorkspaceError("delivery_conflict", "请求不在当前有效接收租约中", 409)
            lease_until = self.clock() + lease_seconds if status == "running" else None
            db.execute("UPDATE workspace_commands SET status=?,progress=?,lease_until=?,updated_at=? WHERE id=?", (status, encoded, lease_until, self.timestamp(), command_id))
            db.execute("UPDATE workspace_hosts SET last_seen=? WHERE id=?", (self.clock(), binding_id))
            self._event(db, "command." + status, "command", command_id, None, "host:" + binding_id, progress)
            return self._command(db.execute("SELECT * FROM workspace_commands WHERE id=?", (command_id,)).fetchone())

    def reply(self, binding_id: str, command_id: str, delivery_token: str, response: Any) -> Dict[str, Any]:
        encoded = safe_json(response)
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM workspace_commands WHERE id=? AND binding_id=?", (command_id, binding_id)).fetchone()
            if not row:
                raise WorkspaceError("request_not_found", "请求不属于当前宿主会话", 404)
            if not isinstance(delivery_token, str) or not secrets.compare_digest(row["delivery_token"] or "", delivery_token):
                raise WorkspaceError("delivery_conflict", "接收凭据已过期或不匹配", 409)
            if row["status"] == "completed" and row["reply"] == encoded:
                return self._command(row)
            if row["status"] not in {"received", "running"} or row["lease_until"] is None or row["lease_until"] <= self.clock():
                raise WorkspaceError("delivery_conflict", "请求不在当前有效接收租约中", 409)
            db.execute("UPDATE workspace_commands SET status='completed',reply=?,updated_at=? WHERE id=?", (encoded, self.timestamp(), command_id))
            db.execute("UPDATE workspace_hosts SET last_seen=? WHERE id=?", (self.clock(), binding_id))
            self._event(db, "command.replied", "command", command_id, None, "host:" + binding_id, {})
            return self._command(db.execute("SELECT * FROM workspace_commands WHERE id=?", (command_id,)).fetchone())
