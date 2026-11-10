"""将 HTTP/宿主输入转成有限的业务意图，身份由服务传入，不信任 payload.actor。"""
from __future__ import annotations

from typing import Any, Dict
from workspace_store import WorkspaceError, WorkspaceStore, identifier
from workspace_tasks import WorkspaceTasks
from workspace_executor import WorkspaceExecutor
from workspace_business import WorkspaceBusiness
from workspace_backup import backup
from workspace_bulk import WorkspaceBulk
from workspace_commerce import WorkspaceCommerce
from workspace_connector import WorkspaceConnector
from workspace_organizer import WorkspaceOrganizer


def fields(body: Any, required=(), optional=()) -> Dict[str, Any]:
    if not isinstance(body, dict) or set(body) - set(required) - set(optional) or set(required) - set(body):
        raise WorkspaceError("invalid_request", "请求字段缺失或包含未允许字段")
    return body


def continuation(body: Dict[str, Any]) -> Dict[str, Any]:
    """验证网页可交办的整理范围，不能把对话文本升级成任意宿主指令。"""
    payload = body.get("payload")
    if not isinstance(payload, dict) or set(payload) != {"workflow", "steps", "stopAfter", "expectedRevision"}:
        raise WorkspaceError("invalid_continuation", "继续整理请求格式无效")
    steps = payload["steps"]
    allowed = {"parse_spreadsheet", "build_table_candidates", "associate_obverse_reverse_images"}
    if payload["workflow"] != "collection.organize" or payload["stopAfter"] != "pairing_review" or not isinstance(steps, list) or not steps or len(steps) != len(set(steps)) or set(steps) - allowed:
        raise WorkspaceError("invalid_continuation", "继续整理只能执行表格解析、候选建立和图片关联，并停在配对审核")
    if type(payload["expectedRevision"]) is not int or payload["expectedRevision"] < 0:
        raise WorkspaceError("invalid_continuation", "继续整理请求缺少有效任务版本")
    return payload


class WorkspaceService:
    def __init__(self, store: WorkspaceStore, runner=None, background=True, organizer_runner=None):
        self.store = store
        self.shutdown = None
        self.tasks = WorkspaceTasks(store)
        self.bulk = WorkspaceBulk(self.tasks)
        self.executor = WorkspaceExecutor(store, self.tasks, runner, background)
        self.connector = WorkspaceConnector(store, self.tasks, self.executor)
        self.organizer = WorkspaceOrganizer(store, self.tasks, self.executor, organizer_runner, background)
        self.business = WorkspaceBusiness(store, self.tasks, self.executor)
        self.commerce = WorkspaceCommerce(store, self.executor)

    def snapshot(self) -> Dict[str, Any]:
        # 先读游标再读取投影；期间的新事件最多被重放，不会因游标领先而漏掉。
        cursor = self.store.cursor()
        return {"schemaVersion": 1, "cursor": cursor, "recentEvents": self.store.events(max(0, cursor - 30), 30), "tasks": self.tasks.summaries(), "hosts": self.store.hosts(),
                "commands": self.store.list_commands(), "notes": self.store.list_entities("note"),
                "settings": self.store.get_entity("settings", "workspace"),
                "operations": self.store.list_entities("operation"),
                # 只读 CLI 查询失败不属于用户确认的执行操作，单独提供排障日志。
                "queryLogs": self.store.list_entities("cli-query-log"),
                "appraisals": self.store.list_entities("appraisal-draft"),
                "purchases": self.store.list_entities("appraisal-purchase"),
                "trackingPurchases": self.store.list_entities("tracking-purchase"),
                "tracking": self.store.list_entities("tracking-draft"),
                # 已收藏的全局索引来自 CLI 写入的 task_projection；详情仍由任务包补全。
                "collectionIndex": self.store.collection_index()}

    def mutate(self, path: str, body: Any, role: str, actor="user:web") -> Any:
        if path.startswith("/api/connector/"):
            if role not in {"browser", "host"}:
                raise WorkspaceError("forbidden", "此入口需要当前工作空间连接", 403)
            # The host key is the authenticated caller.  Payloads cannot claim a
            # user identity, local path, executable or a broader tool permission.
            connector_actor = "agent:connector" if role == "host" else actor
            common = ("taskKey", "expectedRevision")
            if path == "/api/connector/create":
                fields(body, ("name", "timezone"))
                return self.tasks.create(body["name"], body["timezone"], connector_actor)
            if path == "/api/connector/prepare":
                fields(body, common + ("obverseSourceId", "reverseSourceId"))
                return self.connector.prepare(body, connector_actor)
            if path == "/api/connector/photos":
                fields(body, common + ("localId", "obverseSourceId", "reverseSourceId"))
                return self.connector.photos(body, connector_actor)
            if path == "/api/connector/organize":
                fields(body, common, ("retry",))
                if "retry" in body and type(body["retry"]) is not bool:
                    raise WorkspaceError("invalid_request", "retry 必须为布尔值")
                return self.organizer.enqueue(body["taskKey"], body["expectedRevision"], immediate=True, retry=body.get("retry", False))
            if path == "/api/connector/identification-plan":
                fields(body, common + ("localIds",))
                return self.connector.identification_plan(body)
            if path == "/api/connector/identify":
                fields(body, common + ("planHash", "localIds", "commandId"))
                return self.connector.identify(body, connector_actor)
            if path == "/api/connector/collect-batch":
                fields(body, common + ("items", "commandId"))
                return self.connector.collect(body, connector_actor)
            if path == "/api/connector/collect":
                fields(body, common + ("localId", "snapshotId", "commandId"))
                return self.connector.collect(body, connector_actor)
            raise WorkspaceError("not_found", "未找到该连接器操作", 404)
        if isinstance(body, dict) and "commandId" in body:
            # A failed/interrupted connector preparation still owns its ID;
            # neither a legacy route nor another business intent may reuse it.
            self.connector.assert_unclaimed_command(body["commandId"])
        if path == "/api/api-check":
            if role != "browser":
                raise WorkspaceError("forbidden", "API 网络检查只供当前工作台使用", 403)
            fields(body)
            return self.executor.api_check()
        if path.startswith('/api/commerce/'):
            if role != 'browser':
                raise WorkspaceError('forbidden', '交易与支付须在当前工作台确认', 403)
            if path in {'/api/commerce/query', '/api/commerce/plan'}:
                fields(body, ('action', 'params'))
                return (self.commerce.query(body['action'], body['params']) if path.endswith('/query')
                        else self.commerce.plan(body['action'], body['params'], actor))
            if path == '/api/commerce/execute':
                fields(body, ('planId', 'planHash', 'commandId'))
                return self.commerce.execute(body, actor)
            if path == '/api/commerce/recover':
                fields(body, ('operationId',))
                return self.commerce.recover(body['operationId'])
            if path == '/api/commerce/resume-membership':
                fields(body, ('operationId',))
                return self.commerce.resume_membership(body['operationId'], actor)
            if path == '/api/commerce/replan':
                fields(body, ('operationId',))
                return self.commerce.replan(body['operationId'], actor)
            if path == '/api/commerce/history':
                fields(body)
                return self.commerce.history()
        if path == "/api/operations/inspect":
            fields(body, ("operationId",))
            return self.executor.inspect(body["operationId"])
        if path == "/api/operations/resume":
            if role != "browser":
                raise WorkspaceError("forbidden", "失败项重试需要当前工作台确认", 403)
            fields(body, ("operationId",))
            # 仅恢复本地归档为明确失败的原确认范围；未知结果仍需核验，不能重发。
            return self.executor.resume(body["operationId"], self.business)
        if path == "/api/operations/reconcile-identification":
            if role != "browser":
                raise WorkspaceError("forbidden", "远端结果核验须在当前工作台发起", 403)
            fields(body, ("operationId",))
            return self.executor.reconcile_identification(body["operationId"])
        if path == "/api/backup":
            fields(body)
            return backup(self.store, self.tasks, self.executor)
        if path.startswith("/api/business/"):
            if role != "browser":
                raise WorkspaceError("forbidden", "宿主使用结构化业务工具", 403)
            common = ("taskKey", "expectedRevision", "localId")
            if path == "/api/business/appraisal-save":
                fields(body, common + ("description", "sourceIds", "appraiserType", "appraiserId", "draftRevision"))
                return self.business.save_appraisal(body, actor)
            if path == "/api/business/appraisals-services":
                fields(body, (), ("appraiserType", "appraiserId"))
                # 首次进入鉴定页只读获取可用服务目录；选中一项后才查询该服务的
                # 实际剩余次数。两个内部值必须成对出现，不能由前端拼接默认值。
                return self.business.services(body.get("appraiserType"), body.get("appraiserId"))
            if path == "/api/business/appraisal-purchase-options":
                fields(body, ("appraiserType", "appraiserId"))
                return self.business.purchase_options(body["appraiserType"], body["appraiserId"])
            if path == "/api/business/appraisal-purchase-plan":
                fields(body, ("appraiserType", "appraiserId", "sku"))
                return self.business.purchase_plan(body["appraiserType"], body["appraiserId"], body["sku"], actor)
            if path == "/api/business/appraisal-purchase-checkout":
                fields(body, ("planId", "planHash", "commandId"))
                return self.business.checkout_purchase(body, actor)
            if path == "/api/business/appraisal-purchase-resume":
                # 只对已有待付款订单重新取回支付页，不会创建新的购买订单。
                fields(body, ("purchaseId",))
                return self.business.resume_purchase(body["purchaseId"])
            if path == "/api/business/appraisal-purchase-refresh":
                fields(body, ("purchaseId",))
                return self.business.refresh_purchase(body["purchaseId"])
            if path == "/api/business/tracking-purchase-options":
                fields(body, ("planId",))
                return self.business.tracking_purchase_options(body["planId"])
            if path == "/api/business/tracking-purchase-plan":
                fields(body, ("planId", "sku"))
                return self.business.tracking_purchase_plan(body["planId"], body["sku"], actor)
            if path == "/api/business/tracking-purchase-checkout":
                fields(body, ("planId", "planHash", "commandId"))
                return self.business.checkout_tracking_purchase(body, actor)
            if path == "/api/business/tracking-purchase-resume":
                fields(body, ("purchaseId",))
                return self.business.resume_tracking_purchase(body["purchaseId"])
            if path == "/api/business/tracking-purchase-refresh":
                fields(body, ("purchaseId",))
                return self.business.refresh_tracking_purchase(body["purchaseId"])
            if path == "/api/business/collection-edit-detail":
                fields(body, common)
                current = self.tasks._checked(body["taskKey"], body["expectedRevision"])
                item = next((value for value in current["items"] if value["local_id"] == body["localId"]), None)
                if not item:
                    raise WorkspaceError("invalid_selection", "未找到当前收藏档案", 404)
                projection = item.get("collection_projection") or {}
                if projection.get("status") != "succeeded" or not projection.get("collection_uri"):
                    raise WorkspaceError("collection_required", "仅已建立收藏关联的档案可以编辑", 409)
                return {"collectionUri": projection["collection_uri"], "detail": self.executor.query([
                    "collection", "edit-detail", "--collection-uri", projection["collection_uri"],
                    "--batch-id", body["taskKey"], "--candidate-id", item["item_key"],
                ])}
            if path == "/api/business/collection-mutation-plan":
                fields(body, common + ("action", "changes"))
                return self.executor.collection_mutation_plan(
                    body["taskKey"], body["expectedRevision"], body["localId"], body["action"], body["changes"], actor,
                )
            if path == "/api/business/collection-mutation-start":
                fields(body, ("taskKey", "expectedRevision", "planId", "planHash", "commandId", "action"))
                return self.executor.collection_mutation(body, actor)
            if path in {"/api/business/appraisal-plan", "/api/business/tracking-plan"}:
                fields(body, common)
                return self.business.preview("appraisal" if "appraisal" in path else "tracking", body, actor)
            if path in {"/api/business/appraisal-start", "/api/business/tracking-start"}:
                fields(body, ("planId", "planHash", "commandId"))
                return self.business.start("appraisal" if "appraisal" in path else "tracking", body, actor)
            if path == "/api/business/refresh":
                fields(body, ("kind", "localId"))
                if body["kind"] not in {"appraisal", "tracking"}:
                    raise WorkspaceError("invalid_kind", "只支持鉴定或追踪记录")
                return self.business.refresh(body["kind"], body["localId"])
        if path.startswith("/api/tasks/"):
            if role != "browser":
                raise WorkspaceError("forbidden", "宿主请通过业务工具提交结构化操作", 403)
            if path == "/api/tasks/create":
                fields(body, ("name", "timezone"))
                return self.tasks.create(body["name"], body["timezone"], actor)
            common = ("taskKey", "expectedRevision")
            if path == "/api/tasks/identification-plan":
                fields(body, common, ("localIds",))
                return self.connector.identification_plan(body)
            if path == "/api/tasks/identify":
                fields(body, common + ("planHash", "localIds", "commandId"))
                return self.executor.identify(body, actor)
            if path == "/api/tasks/collection-plan":
                fields(body, common + ("localIds",))
                self.executor.assert_idle(body["taskKey"])
                return self.executor.collection_plan(body["taskKey"], body["expectedRevision"], body["localIds"], actor)
            if path == "/api/tasks/collect":
                fields(body, common + ("planId", "planHash", "commandId"))
                return self.executor.collect(body, actor)
            if isinstance(body, dict) and "taskKey" in body:
                self.executor.assert_idle(body["taskKey"])
            if path in {"/api/tasks/bulk-preview", "/api/tasks/bulk-apply"}:
                fields(body, common + ("stage", "action", "localIds") + (("planHash",) if path.endswith("apply") else ()))
                with self.executor.lock:
                    self.executor.assert_idle(body["taskKey"])
                    return self.bulk.apply(body, actor) if path.endswith("apply") else self.bulk.preview(body)
            if path == "/api/tasks/candidate":
                fields(body, common + ("sourceIds", "title"))
                return self.tasks.create_candidate(body["taskKey"], body["expectedRevision"], body["sourceIds"], body["title"], actor)
            if path == "/api/tasks/merge-candidates":
                fields(body, common + ("targetLocalId", "sourceLocalId"))
                return self.tasks.merge_candidates(body["taskKey"], body["expectedRevision"], body["targetLocalId"], body["sourceLocalId"], actor)
            if path == "/api/tasks/pair":
                fields(body, common + ("localId", "action", "assignments"))
                return self.tasks.pair(body["taskKey"], body["expectedRevision"], body["localId"], body["action"], body["assignments"], actor)
            if path == "/api/tasks/review":
                fields(body, common + ("localId",), ("decision", "details"))
                return self.tasks.review(body["taskKey"], body["expectedRevision"], body["localId"], body.get("decision"), actor, body.get("details"))
        if path.startswith("/api/bridge/"):
            if role != "host":
                raise WorkspaceError("forbidden", "此接口只供已绑定的宿主工具调用", 403)
            if path == "/api/bridge/shutdown" and self.shutdown is not None:
                fields(body)
                self.shutdown()
                return {"ok": True, "status": "stopping"}
            if path == "/api/bridge/bind":
                fields(body, ("host", "conversation"), ("conversationTitle",))
                # 当前提供可靠取件能力，没有原生唤起适配器时不能宣称支持 push。
                return self.store.bind_host(body["host"], body["conversation"],
                    {"inbox": True, "progress": True, "push": False}, body.get("conversationTitle", ""))
            if path == "/api/bridge/reconcile":
                fields(body, ("operationId", "matches"))
                return self.executor.reconcile(body["operationId"], body["matches"])
            if path == "/api/bridge/resume":
                fields(body, ("operationId",))
                return self.executor.resume(body["operationId"], self.business)
            if path == "/api/bridge/resolve":
                fields(body, ("operationId",))
                return self.executor.resolve(body["operationId"])
            if path == "/api/bridge/action":
                fields(body, ("bindingId", "action", "payload"))
                binding = next((h for h in self.store.hosts() if h["id"] == body["bindingId"]), None)
                routes = {"task.create": "/api/tasks/create", "candidate.create": "/api/tasks/candidate",
                          "candidate.merge": "/api/tasks/merge-candidates",
                          "batch.preview": "/api/tasks/bulk-preview", "batch.apply": "/api/tasks/bulk-apply",
                          "pairing.save": "/api/tasks/pair", "review.save": "/api/tasks/review",
                          "identification.preview": "/api/tasks/identification-plan", "identification.confirm": "/api/tasks/identify",
                          "collection.preview": "/api/tasks/collection-plan", "collection.confirm": "/api/tasks/collect",
                          "note.save": "/api/entities", "appraisal.save": "/api/business/appraisal-save",
                          "appraisal.services": "/api/business/appraisals-services", "appraisal.preview": "/api/business/appraisal-plan",
                          "appraisal.confirm": "/api/business/appraisal-start", "tracking.preview": "/api/business/tracking-plan",
                          "tracking.confirm": "/api/business/tracking-start", "business.refresh": "/api/business/refresh"}
                if not binding or body["action"] not in routes:
                    raise WorkspaceError("invalid_action", "需要有效宿主绑定和允许的业务工具", 403)
                if body["action"] == "note.save" and (not isinstance(body["payload"], dict) or body["payload"].get("kind") != "note"):
                    raise WorkspaceError("invalid_action", "备注工具只能修改 note", 403)
                return self.mutate(routes[body["action"]], body["payload"], "browser", "agent:" + binding["id"])
            if path == "/api/bridge/inbox":
                fields(body, ("bindingId",), ("leaseSeconds",))
                return {"commands": self.store.claim(body["bindingId"], body.get("leaseSeconds", 60))}
            if path == "/api/bridge/progress":
                fields(body, ("bindingId", "commandId", "deliveryToken", "status", "message"), ("step", "leaseSeconds"))
                if not isinstance(body["message"], str) or not body["message"].strip() or len(body["message"]) > 20000:
                    raise WorkspaceError("invalid_message", "进度说明应为 1–20000 字符")
                if "step" in body and (not isinstance(body["step"], str) or not body["step"].strip() or len(body["step"]) > 100):
                    raise WorkspaceError("invalid_progress", "进度步骤无效")
                return self.store.update_command(body["bindingId"], body["commandId"], body["deliveryToken"], body["status"],
                                                 {"message": body["message"], **({"step": body["step"]} if "step" in body else {})},
                                                 body.get("leaseSeconds", 60))
            if path == "/api/bridge/reply":
                fields(body, ("bindingId", "commandId", "deliveryToken", "message"))
                if not isinstance(body["message"], str) or not body["message"].strip() or len(body["message"]) > 20000:
                    raise WorkspaceError("invalid_message", "回复应为 1–20000 字符")
                return self.store.reply(body["bindingId"], body["commandId"], body["deliveryToken"],
                                        {"message": body["message"], "type": "agent.response"})
        elif path == "/api/requests":
            if role != "browser":
                raise WorkspaceError("forbidden", "使用宿主工具回复网页请求", 403)
            fields(body, ("commandId", "bindingId", "taskId", "message"), ("objectId", "intent", "payload"))
            if not isinstance(body["message"], str) or not body["message"].strip() or len(body["message"]) > 20000:
                raise WorkspaceError("invalid_message", "请求应为 1–20000 字符")
            intent = body.get("intent", "agent.request")
            if intent == "task.continue":
                if not isinstance(body["taskId"], str):
                    raise WorkspaceError("invalid_continuation", "继续整理请求必须关联任务")
                payload = {"message": body["message"], "objectId": body.get("objectId"), **continuation(body)}
            elif intent == "agent.request" and "payload" not in body:
                payload = {"message": body["message"], "objectId": body.get("objectId")}
            else:
                raise WorkspaceError("invalid_intent", "不支持该协作请求")
            return self.store.enqueue(body["commandId"], body["bindingId"], body["taskId"], intent, payload, "user:web")
        elif path == "/api/entities":
            if role != "browser":
                raise WorkspaceError("forbidden", "宿主应使用有明确业务含义的工具修改记录", 403)
            fields(body, ("kind", "id", "data", "expectedRevision"))
            kind, data = body["kind"], body["data"]
            if kind == "note":
                fields(data, ("text",))
                if not isinstance(data["text"], str) or len(data["text"]) > 20000:
                    raise WorkspaceError("invalid_note", "备注不能超过 20000 字符")
            elif kind == "settings":
                fields(data, ("autoOpen",))
                if body["id"] != "workspace" or type(data["autoOpen"]) is not bool:
                    raise WorkspaceError("invalid_settings", "工作空间设置无效")
            else:
                raise WorkspaceError("invalid_kind", "不支持此类型的记录修改")
            return self.store.save_entity(kind, identifier(body["id"]), data, body["expectedRevision"], actor)
        raise WorkspaceError("not_found", "未找到该操作", 404)
