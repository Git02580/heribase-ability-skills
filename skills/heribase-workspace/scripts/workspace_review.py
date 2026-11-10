"""结果审核：沿用任务包锁、日志与版本校验，旧任务无需替换 Schema。"""
from __future__ import annotations
import json
import math
import re
from workspace_store import WorkspaceError

MARKER = 'heribase.review-details.v1'
TEXT_FIELDS = {'note', 'weight', 'diameter', 'thickness', 'metal', 'edge', 'variety', 'correction', 'condition', 'resolution'}


def validate_details(value):
    if not isinstance(value, dict) or set(value) - TEXT_FIELDS - {'checks'}:
        raise WorkspaceError('invalid_review_details', '审核记录字段无效')
    for key, text in value.items():
        if key == 'checks':
            if not isinstance(text, list) or any(v not in ['identity', 'catalog', 'motif'] for v in text):
                raise WorkspaceError('invalid_review_details', '核对清单无效')
        elif not isinstance(text, str) or len(text) > 10000:
            raise WorkspaceError('invalid_review_details', '审核文字不得超过 10000 字符')
        elif key in {'weight', 'diameter', 'thickness'} and text.strip():
            try:
                number = float(text)
                if not math.isfinite(number) or number <= 0: raise ValueError()
            except ValueError:
                raise WorkspaceError('invalid_measurement', '实测数值必须是大于零的有限数字')
    return value


def payload(event):
    try:
        data = json.loads(event.get('note') or '{}')
        return data if isinstance(data, dict) and data.get('schema') == MARKER else {}
    except (ValueError, TypeError):
        return {}


def issues(item):
    """仅比较可明确提取的来源值，不把整理描述当作真相或推断 AI 置信度。"""
    result = item.get('recognitionResult') or {}
    claims = item.get('field_claims') or {}
    values = []
    for key, value in (item.get('resolved_fields') or {}).items():
        if key in {'year', 'years'}:
            values.append(('来源年份', value.get('value') if isinstance(value, dict) else value))
    for claim in claims.get('visible_text', []):
        if isinstance(claim, dict): values.append(('整理文字', claim.get('value')))
    for row in claims.get('table_rows', []):
        fields = row.get('fields', {})
        values.extend(('导入表 '+key, fields.get(key)) for key in ['Year', 'year', 'Name'])
    year = str(result.get('year') or '').strip()
    found = []
    for source, value in values:
        years = set(re.findall(r'(?<!\d)(?:1[5-9]\d{2}|20\d{2})(?!\d)', str(value or '')))
        if year and len(years) == 1 and year not in years:
            found.append({'field':'年份', 'source':source, 'original':str(value), 'recognized':year})
    suffix = re.search(r'-(PR|PF|MS|AU|XF|EF|VF|F|VG|G)(?:\d+)?$', str(result.get('title') or ''))
    if suffix:
        for row in claims.get('table_rows', []):
            grade = row.get('fields', {}).get('Grade')
            if grade and str(grade).strip().upper() != suffix.group(1):
                found.append({'field':'品相 / 工艺资料', 'source':'导入表 Grade', 'original':str(grade), 'recognized':'识别标题后缀 '+suffix.group(1)+'（非结构化评级）'})
    return found


def decorate(items, events):
    """当前记录按事件 ID 与识别快照绑定；更新识别后撤销旧核对结论的有效性。"""
    grouped = {}
    for event in events:
        grouped.setdefault(event.get('local_id'), []).append(event)
    for item in items:
        history = grouped.get(item['local_id'], [])
        latest = history[-1] if history else {}
        data = payload(latest)
        if data.get('decision') == 'hold' and item.get('review_projection'):
            item['review_projection']['deferred'] = True
        # 导入旧版审核决定时可能没有详情，仍可回看最近一次有详情的记录。
        detail_event = next((e for e in reversed(history) if payload(e)), {})
        detail_data = payload(detail_event)
        based = detail_event.get('based_on') or {}
        active = item.get('active_identification') or {}
        stale = bool(detail_event) and (based.get('item_version') != item['version'] or based.get('identification_snapshot_id') != active.get('snapshot_id'))
        item['reviewDetails'] = detail_data.get('details', {})
        item['reviewDetailsStale'] = stale
        item['reviewIssues'] = issues(item)
        item['reviewIssuesResolved'] = bool(item['reviewDetails'].get('resolution', '').strip()) and not stale
        item['reviewHistory'] = [{'decision':payload(e).get('decision') or e.get('decision') or 'pending',
            'createdAt':e['created_at'], 'actor':e.get('actor', {}).get('name'),
            'details':payload(e).get('details', {}), 'note':e.get('note') if not payload(e) else None} for e in history]


def collect_reason(item):
    if item.get('reviewIssues') and not item.get('reviewIssuesResolved'):
        return '来源与识别资料存在差异，请先逐枚记录核对结论'
    return ''


def save(args):
    # 导入放在函数内，避免 WorkspaceTasks 与本适配器循环初始化。
    import task_package as core
    import task_operations as ops
    root = core.resolve_root(args.root)
    with ops.task_lock(root, args.task_key):
        _, task, manifest, sources_doc, items_doc = ops.open_task(args)
        events_path = task/'review/decisions.jsonl'
        events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
        # 仅在内存补充展示字段；持久快照保持原有 schema 和事实字段。
        decorated = json.loads(json.dumps(items_doc['items']))
        for item in decorated:
            ref = (item.get('active_identification') or {}).get('raw_response_ref')
            if ref and core.safe_relative_path(ref):
                raw = core.read_json(task/ref)
                item['recognitionResult'] = raw.get('result', raw)
        decorate(decorated, events)
        indexed = {i['local_id']:i for i in decorated}
        prepared = []
        for entry in args.entries:
            item = ops.find_item(items_doc, entry['localId'])
            current = indexed[item['local_id']]
            review = item.get('review_projection') or {}
            previous = 'hold' if review.get('deferred') else review.get('decision')
            decision = entry.get('decision', None if review.get('stale') else previous)
            if (decision is not None and not isinstance(decision, str)) or decision not in {None, 'collect', 'hold', 'need_photo', 'exclude'}:
                raise WorkspaceError('invalid_decision', '审核决定无效')
            details = dict(current['reviewDetails'])
            if current['reviewDetailsStale']:
                details.pop('resolution', None)
                details.pop('checks', None)
            details.update(validate_details(entry.get('details', {})))
            current['reviewIssuesResolved'] = bool(details.get('resolution', '').strip())
            if decision == 'collect':
                active = item.get('active_identification') or {}
                if active.get('status') != 'succeeded' or not active.get('identify_uri'):
                    raise WorkspaceError('identification_required', '先取得成功识别结果，再决定收藏', 409)
                if collect_reason(current):
                    raise WorkspaceError('review_conflict', collect_reason(current), 409)
            prepared.append((item, decision, details))
        for item, decision, details in prepared:
            previous = item.get('review_projection') or {}
            timestamp = ops.now_iso()
            deferred = decision == 'hold'
            canonical = None if deferred else decision
            event = {'schema_version':'heribase.review-decision.v1', 'decision_id':ops.new_id('decision'),
                'local_id':item['local_id'], 'action':'clear' if canonical is None else 'set', 'decision':canonical,
                'note':json.dumps({'schema':MARKER, 'decision':decision, 'details':details}, ensure_ascii=False),
                'actor':{'type':'user' if args.actor.startswith('user:') else 'agent', 'name':args.actor},
                'interaction':{'source':'bulk' if args.batch_id else 'single', 'batch_action_id':args.batch_id, 'import_ref':None},
                'based_on':{'item_version':item['version'], 'identification_snapshot_id':(item.get('active_identification') or {}).get('snapshot_id'),
                    'dataset_revision':manifest['dataset_revision'], 'dataset_fingerprint':manifest['dataset_fingerprint']},
                'supersedes':previous.get('decision_id'), 'reverts':None, 'created_at':timestamp}
            ops.append_log_line(task, 'review/decisions.jsonl', event, 'review-decision.schema.json')
            # hold 是撤回采纳后的本地待复核标记。旧 CLI 只看空决定，无法误入收藏。
            item['review_projection'] = {'decision_id':event['decision_id'], 'decision':canonical, 'deferred':deferred,
                'actor':args.actor, **event['based_on'], 'updated_at':timestamp, 'stale':False}
        plan_path = task/'collection/plan.json'
        plan = core.read_json(plan_path) if plan_path.exists() else None
        if plan and plan.get('status') not in {'consumed','cancelled','stale'}: plan['status']='stale'
        ops.append_audit(task, 'review_saved', 'task', args.task_key, 'user', args.actor, None,
            {'count':len(prepared)}, {'batch_action_id':args.batch_id})
        revision = ops.commit_snapshots(task, manifest, sources_doc, items_doc, dataset_changed=False, plan=plan)
        return {'revision':revision}
