"""批量本地决定：预览固定范围，确认重验版本，一次受控导入逐项事件。"""
from __future__ import annotations
import hashlib
import secrets
from workspace_store import WorkspaceError, safe_json
from workspace_tasks import operations, core
import workspace_review


def source_assignments(item):
    # 已有用户方向优先。未知图片保持 unknown，绝不能用数组顺序猜正反面。
    saved = item.get('organization', {}).get('source_assignment')
    values = saved if saved is not None else item.get('evidence', [])
    return [{'sourceId': e['source_id'], 'role': e['role']} for e in values]


class WorkspaceBulk:
    def __init__(self, tasks):
        self.tasks = tasks

    def preview(self, body):
        stage, action, ids = body['stage'], body['action'], body['localIds']
        allowed = {'pairing': {'confirm_pair', 'need_photo', 'exclude'}, 'review': {'collect', 'hold', 'need_photo', 'exclude'}}
        if not isinstance(stage, str) or not isinstance(action, str) or action not in allowed.get(stage, set()):
            raise WorkspaceError('invalid_action', '只支持配对或结果审核的批量决定')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise WorkspaceError('invalid_scope', '每次选择 1–500 枚不重复候选')
        task = self.tasks._checked(body['taskKey'], body['expectedRevision'])
        indexed = {i['local_id']: i for i in task['items']}
        if any(i not in indexed for i in ids):
            raise WorkspaceError('invalid_scope', '所选对象不属于当前任务')
        source_map = {s['source_id']: s for s in task['sources']}
        owners = {}
        for item in task['items']:
            if item['status'] in core.ACTIVE_ITEM_STATUSES:
                for evidence in item['evidence']:
                    owners.setdefault(evidence['source_id'], set()).add(item['local_id'])
        entries = []
        for local_id in ids:
            item = indexed[local_id]
            organization = item.get('organization') or {}
            review = item.get('review_projection') or {}
            identification = item.get('active_identification') or {}
            old = organization.get('pairing_state') if stage == 'pairing' else ('hold' if review.get('deferred') else review.get('decision'))
            target = {'confirm_pair': 'confirmed', 'need_photo': 'single_side', 'exclude': 'excluded'}[action] if stage == 'pairing' else action
            stale = review.get('stale') if stage == 'review' else False
            assignments = source_assignments(item)
            reason = ''
            if item['status'] not in core.ACTIVE_ITEM_STATUSES:
                reason = '候选已归档或被替代，请逐枚查看'
            elif stage == 'pairing' and (not assignments or any(
                    a['role'] not in {'obverse', 'reverse', 'unknown'} or a['sourceId'] not in source_map
                    or a['sourceId'] not in {e['source_id'] for e in item['evidence']} for a in assignments)):
                reason = '当前图片来源或角色不支持批量配对决定，请逐枚核对'
            elif stage == 'pairing' and (any(len(owners.get(a['sourceId'], set())) > 1 for a in assignments) or len({a['sourceId'] for a in assignments}) != len(assignments)):
                reason = '图片归属重复，请逐枚处理；本批其他候选可继续'
            elif (stage == 'pairing' and action == 'confirm_pair') or (stage == 'review' and action == 'collect'):
                flags = set(item.get('attention_flags', []))
                if item['status'] == 'identity_conflict' or 'identity_conflict' in flags:
                    reason = '存在身份冲突，需逐枚核对'
                elif any(len(owners.get(e['source_id'], set())) > 1 for e in item['evidence']):
                    reason = '图片被其他候选重复引用'
                elif stage == 'pairing':
                    roles = [a['role'] for a in assignments]
                    sources = [a['sourceId'] for a in assignments]
                    if (roles.count('obverse') != 1 or roles.count('reverse') != 1 or len(sources) != len(set(sources))
                            or any(s not in source_map or not source_map[s]['mime_type'].startswith('image/') for s in sources)):
                        reason = '缺少已明确方向的正反面图片，请逐枚指定'
                    elif 'source_incomplete' in flags or item['status'] == 'source_incomplete':
                        reason = '来源资料不完整'
                elif identification.get('status') != 'succeeded' or not identification.get('identify_uri'):
                    reason = '没有有效的成功识别结果'
                elif not operations.identification_eligible(item):
                    reason = '配对或来源尚待确认'
                elif workspace_review.collect_reason(item):
                    reason = workspace_review.collect_reason(item)
                elif (item.get('collection_projection') or {}).get('collection_uri'):
                    reason = '已有收藏关联，请从档案核对'
            status = 'blocked' if reason else 'unchanged' if old == target and not stale else 'ready'
            entries.append({'localId': local_id, 'title': operations.display_for_item(item).get('title') or item['item_key'],
                            'version': item['version'], 'status': status, 'reason': reason or ('已有相同决定' if status == 'unchanged' else '可以处理'),
                            'overwrite': status == 'ready' and bool(old) and (stage == 'review' or old in {'confirmed', 'single_side', 'excluded'}),
                            'previous': old, 'assignments': assignments if stage == 'pairing' else []})
        plan = {k: body[k] for k in ('taskKey', 'expectedRevision', 'stage', 'action', 'localIds')}
        plan.update(items=entries, fingerprint=task['manifest']['dataset_fingerprint'])
        return {**plan, 'planHash': hashlib.sha256(safe_json(plan).encode()).hexdigest()}

    def apply(self, body, actor):
        # 摘要由当前事实重算；既不接受客户端资格判断，也不悄悄缩小/扩大确认范围。
        plan = self.preview(body)
        if body['planHash'] != plan['planHash']:
            raise WorkspaceError('stale_plan', '批量范围已变化，请重新预览', 409)
        ready = [i for i in plan['items'] if i['status'] == 'ready']
        if not ready:
            raise WorkspaceError('no_eligible_items', '没有需要写入的新决定', 409)
        batch_id = 'batch-' + secrets.token_hex(16)
        timestamp = operations.now_iso()
        action = body['action']
        package = {'datasetFingerprint': plan['fingerprint'], 'exportedAt': timestamp}
        if body['stage'] == 'pairing':
            package.update(schemaVersion=1, taskKey=body['taskKey'], summary={action: len(ready)}, decisions=[
                {'localId': i['localId'], 'action': action, 'sourceAssignments': i['assignments'], 'updatedAt': timestamp, 'batchActionId': batch_id} for i in ready])
            function, options = operations.import_pairing, {}
        else:
            package.update(schemaVersion=2, summary={'collect': len(ready) if action == 'collect' else 0,
                'needPhoto': len(ready) if action == 'need_photo' else 0, 'excluded': len(ready) if action == 'exclude' else 0}, decisions=[
                {'recordId': i['localId'], 'sourceRows': [], 'decision': 'need-photo' if action == 'need_photo' else action,
                 'updatedAt': timestamp, 'source': 'bulk', 'batchActionId': batch_id} for i in ready])
            function, options = operations.import_review, {'mode': 'merge', 'allow_legacy': False}
        # 任务包在同一锁内检查 expected_revision，再统一验证、逐项追加并提交快照。
        # 即使响应丢失，重放旧 revision 也无法写入第二次；批次历史从任务日志重建。
        # 先保存范围说明，但它不是决定事实。历史仅在任务日志出现同批事件后展示；
        # 若导入失败，这份上下文不会被误报为已执行。崩溃恢复仍以逐项日志为准。
        self.tasks.store.save_entity('batch-context', batch_id, {'items': plan['items'], 'action': action}, 0, actor)
        if body['stage'] == 'review':
            result = self.tasks._call(body['taskKey'], body['expectedRevision'], actor, workspace_review.save,
                entries=[{'localId': i['localId'], 'decision': action} for i in ready], batch_id=batch_id)
        else:
            result = self.tasks._import_json(body['taskKey'], body['expectedRevision'], actor, function, package, **options)
        return {'batchActionId': batch_id, 'revision': result['revision'], 'appliedIds': [i['localId'] for i in ready],
                'items': [{**i, 'status': 'applied' if i['status'] == 'ready' else i['status']} for i in plan['items']]}
