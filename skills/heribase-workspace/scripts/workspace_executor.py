"""有限业务执行器：先持久化授权，再逐条执行固定 CLI argv。

本机事务无法与远端 HTTP 原子提交。每次 CLI 调用前记录意图、返回后保留精确
stdout；重启时把进行中任务转为待核验，绝不自动重放可能消耗额度的写命令。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit

from workspace_store import WorkspaceError, identifier, safe_json
from workspace_tasks import core, operations


# 服务已经明确拒绝、且不会产生远端写入的临时故障，才允许在同一授权范围内重试。
# 网络超时、缺失 stdout 和任何带 reconciliationRequired 的响应仍属于“结果未知”。
RETRYABLE_FAILURE_CODES = {'DOWNSTREAM_UNAVAILABLE'}
MAX_ITEM_ATTEMPTS = 3

# 与工作台 CSP 保持一致：HeriBase 头像 CDN 和 Google 登录头像源。
PROFILE_AVATAR_HOSTS = ('cdn.heritcoin.com', 'cdn.heribase.com', 'lh3.googleusercontent.com')
RECOGNITION_NO_MATCH_CODE = 'recognition_low_cls_score'
RECOGNITION_NO_MATCH_BUSINESS_CODE = 80004

# 工作台只暴露 CLI 明确支持、且不涉及资产身份关联的收藏字段。省略字段就是保留
# 服务端现值；不能把浏览器传来的任意 key 拼进 CLI argv。
COLLECTION_UPDATE_FLAGS = {
    'years': '--years',
    'mint': '--mint',
    'priceLevel': '--price-level',
    'priceGrade': '--price-grade',
    'value': '--value',
    'dateAcquired': '--date-acquired',
    'notes': '--notes',
    'setUri': '--set-uri',
    'title': '--title',
    'customWeight': '--custom-weight',
    'customSize': '--custom-size',
    'customSerialNumber': '--custom-serial-number',
    'customDenomination': '--custom-denomination',
}
COLLECTION_IMAGE_SOURCE_IDS = 'collectImageSourceIds'


def digest(value):
    return hashlib.sha256(safe_json(value).encode()).hexdigest()


def cli_runner(home):
    def run(argv):
        # 路径只取安装布局和可信 PATH，HTTP 端没有 executable/shell 参数。
        installed = Path(__file__).resolve().parents[2] / 'heribase-cli' / 'bin' / 'heribase'
        node = shutil.which('node')
        executable = shutil.which('heribase') if not installed.is_file() else None
        if installed.is_file() and not node:
            raise WorkspaceError('cli_missing', '请安装 Node.js 24+ 后重新打开 Agent', 409)
        if not installed.is_file() and not executable:
            raise WorkspaceError('cli_missing', '请按安装说明安装 heribase CLI 并加入 PATH', 409)
        # 随附文件是 JavaScript；显式调用 Node，Windows 无需执行 Unix shebang。
        command = [node, str(installed)] if installed.is_file() else [executable]
        env = dict(os.environ)
        env['HOME'] = str(home)
        # Node 在 Windows 使用 USERPROFILE 解析用户目录，隔离测试须同时设置。
        env['USERPROFILE'] = str(home)
        try:
            result = subprocess.run([*command, *argv, '--json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise WorkspaceError('cli_timeout', 'CLI 等待超时，请核验本地任务和远端结果', 409) from exc
        except OSError as exc:
            raise WorkspaceError('cli_unavailable', '无法启动已安装的 heribase CLI', 409) from exc
        # stderr 不能作为业务事实，也不回显可能包含本机凭据的诊断内容。
        if not result.stdout or len(result.stdout) > 1024 * 1024:
            raise WorkspaceError('cli_invalid_output', 'CLI 未返回可归档的 JSON 结果，请核验任务状态', 409)
        return result.stdout

    return run


def is_recognition_no_match(value):
    """识别服务明确完成请求但未达到硬币类别阈值，属于业务识别失败而非执行失败。"""
    error = value.get('error') or {}
    # CLI 当前把识别业务码放在 message 中；部分服务版本才会单独返回 apiCode。
    api_code = error.get('apiCode') or error.get('message')
    return (
        value.get('status') == 'failed'
        and error.get('code') == 'API_ERROR'
        and api_code == RECOGNITION_NO_MATCH_CODE
        and error.get('businessCode') == RECOGNITION_NO_MATCH_BUSINESS_CODE
        and error.get('httpStatus') == 200
    )


def result_value(raw, allow_recognition_no_match=False):
    try:
        value = json.loads(raw)
        safe_json(value)
    except (ValueError, TypeError) as exc:
        raise WorkspaceError('cli_invalid_output', 'CLI 未返回合法 JSON', 409) from exc
    if not isinstance(value, dict):
        raise WorkspaceError('cli_invalid_output', 'CLI 结果必须是对象', 409)
    error = value.get('error') or {}
    failure_code = error.get('apiCode') or error.get('code') or error.get('businessCode')
    if value.get('status') == 'failed' and not error.get('reconciliationRequired'):
        detail = error.get('data')
        detail = detail if isinstance(detail, dict) else {}
        if ('identify_limit' in (detail.get('reason'), error.get('apiCode'), error.get('message'))
                and (error.get('businessCode') == 409 or error.get('apiCode') == 'identify_limit')):
            raise WorkspaceError('identify_limit', '今日识别额度已用完，已暂停剩余识别。', 409,
                                 eligibility={**detail, 'allowed': False})
    # 仅识别命令可把这个精确业务错误视作一次已完成的识别尝试；其它命令仍按失败处理。
    if allow_recognition_no_match and is_recognition_no_match(value):
        return value, None
    # CLI 的原始 stdout 已单独归档；这里把服务端给出的可读原因带回工作台，
    # 避免用户只看到“明确失败”却无法判断是参数、权限还是服务故障。
    failure_reason = error.get('message')
    if not isinstance(failure_reason, str) or not failure_reason.strip():
        failure_reason = str(failure_code) if failure_code else '服务未提供具体错误原因'
    if value.get('status') == 'failed' and not error.get('reconciliationRequired') and failure_code in RETRYABLE_FAILURE_CODES:
        raise WorkspaceError(
            'cli_retryable_failure',
            f'CLI 返回可重试错误（{failure_code}）：{failure_reason}',
            409,
        )
    if value.get('status') == 'failed' and not error.get('reconciliationRequired'):
        raise WorkspaceError(
            'cli_definite_failure',
            f'CLI 操作失败（{failure_code or "未知错误"}）：{failure_reason}。'
            '已成功的项目保留；未完成项没有自动重放。请查看执行记录中的 CLI 错误详情，'
            '确认原因后再决定是否重新确认。',
            409,
        )
    if value.get('status') != 'completed' or value.get('error'):
        raise WorkspaceError('cli_not_completed', 'CLI 未确认成功；请查看执行记录并核验结果', 409)
    return value, value.get('result')


class WorkspaceExecutor:
    def __init__(self, store, tasks, runner=None, background=True):
        self.store, self.tasks = store, tasks
        self.runner = runner or cli_runner(store.directory.parent)
        self.background = background
        self.lock = threading.RLock()
        self.threads = []
        # 只在进程初始化恢复记录。不同 command ID 也不能绕过待核验任务重新执行。
        for entry in store.list_entities('operation'):
            data = entry['data']
            if self._reclassify_recognition_no_match(entry):
                # 历史记录中只有这类已收到 HTTP 200 的低置信度结果时，识别任务已经终止完成，
                # 不应继续占用“执行中/待核验/可重试”闸门。
                continue
            # 旧版本把收藏编辑 / 取消的明确失败误标成 partial_failed。它们不是可
            # 自动重试的批处理动作；每条结果都已归档且没有未知调用时，应结束记录，
            # 让用户生成一份新的计划，而不是永久阻断整个整理任务。
            if data.get('status') == 'partial_failed' and data.get('kind') in {'collection_update', 'collection_cancel'}:
                outcomes = data.get('itemResults', [])
                resolved = bool(outcomes) and all(
                    result.get('status') == 'succeeded' or (result.get('status') == 'failed' and (result.get('error') or {}).get('code') == 'cli_definite_failure')
                    for result in outcomes
                )
                if resolved:
                    self.update(entry['id'], status='failed', message='收藏编辑请求已明确失败；未成功的条目可重新生成计划并确认')
                    continue
            if data['status'] in {'preparing', 'queued', 'running'}:
                if not entry['data'].get('scope') and not entry['data']['calls']:
                    self.update(entry['id'], status='failed', message='确认准备阶段中断，尚未发出上传或写入调用，可重新确认')
                    for kind in ('appraisal-draft', 'tracking-draft'):
                        for draft in store.list_entities(kind):
                            if draft['data'].get('operationId') == entry['id']:
                                store.save_entity(kind, draft['id'], {**draft['data'], 'status': 'failed'}, draft['revision'], 'system:recovery')
                else:
                    self.update(entry['id'], status='reconcile_required', recoveryCutoff=store.timestamp(), message='工作空间曾中断，请核验已提交的 CLI 任务；未自动重做。')

            # 远端核验只读；若工作台进程在查询中退出，将遗留的 running 尝试标记为
            # 可重试的查询异常。它不会改变原识别状态，也不会重新提交上传或识别。
            attempts = data.get('remoteReconciliationAttempts', [])
            if any(attempt.get('status') == 'running' for attempt in attempts):
                self.update(entry['id'], remoteReconciliationAttempts=[
                    {**attempt, 'status': 'query_failed', 'finishedAt': store.timestamp(),
                     'error': {'code': 'workspace_restarted', 'message': '工作台在核验过程中重启；可重新执行只读核验'}}
                    if attempt.get('status') == 'running' else attempt
                    for attempt in attempts
                ])

    def _reclassify_recognition_no_match(self, entry):
        """用已有 CLI 原始回执修复旧版误标的低置信度识别失败。

        只检查 partial_failed 的识别操作，只接受 HTTP 200 + API_ERROR + 80004，
        原始 stdout 必须仍在 operation-call 中；绝不重新请求识别 API。
        """
        data = entry['data']
        if data.get('status') != 'partial_failed' or data.get('kind') != 'identify':
            return False
        failed_items = [item for item in data.get('itemResults', []) if item.get('status') == 'failed']
        if not failed_items:
            return False
        try:
            task = self.tasks.snapshot(data['taskKey'])
        except (WorkspaceError, KeyError, TypeError):
            return False
        items_by_key = {item.get('item_key'): item for item in task.get('items', [])}
        changed = False
        for outcome in failed_items:
            local_id = outcome.get('localId')
            item = next((value for value in items_by_key.values() if value.get('local_id') == local_id), None)
            if item is None:
                continue
            matching_call = None
            for call in reversed(data.get('calls', [])):
                argv = call.get('argv') or []
                if not argv or argv[0] != 'identify' or '--candidate-id' not in argv:
                    continue
                try:
                    candidate_id = argv[argv.index('--candidate-id') + 1]
                except IndexError:
                    continue
                if candidate_id == item.get('item_key'):
                    matching_call = call
                    break
            if matching_call is None:
                continue
            saved = self.store.get_entity('operation-call', matching_call.get('id', ''))
            if not saved:
                continue
            try:
                raw = saved['data']['stdout'].encode('utf-8')
                envelope = json.loads(raw)
            except (KeyError, TypeError, ValueError):
                continue
            if not is_recognition_no_match(envelope):
                continue

            remote_error = envelope.get('error') or {}
            recognition_error = {
                'code': RECOGNITION_NO_MATCH_CODE,
                'businessCode': RECOGNITION_NO_MATCH_BUSINESS_CODE,
                'httpStatus': 200,
                'message': remote_error.get('message') or '服务已处理请求，但未能识别出硬币版本',
            }
            # 将之前只保存在 operation-call 的精确响应补入识别尝试日志，便于后续审计。
            event = {
                'schema_version': 'heribase.recognition-attempt.v1',
                'attempt_id': 'recognition-' + secrets.token_hex(12),
                'task_key': data['taskKey'],
                'local_id': local_id,
                'attempt_number': max(1, int(outcome.get('attempts') or 1)),
                'operation_type': 'identify',
                'status': 'failed_terminal',
                'input': {
                    'item_version': item['version'],
                    'evidence': [
                        {'evidence_id': evidence['evidence_id'],
                         'sha256': next(source['sha256'] for source in task['sources'] if source['source_id'] == evidence['source_id'])}
                        for evidence in item['evidence']
                    ],
                },
                'cli': {'command': 'heribase identify', 'args': (matching_call.get('argv') or [])[1:] + ['--json']},
                'remote_task_id': envelope.get('id') or envelope.get('taskId'),
                'started_at': matching_call.get('startedAt') or operations.now_iso(),
                'finished_at': matching_call.get('finishedAt') or operations.now_iso(),
                'exit_code': 0,
                'classification': RECOGNITION_NO_MATCH_CODE,
                'raw_response_ref': None,
                'raw_response_sha256': None,
                'error': recognition_error,
            }
            try:
                self._record(entry['id'], task, event, raw)
            except (WorkspaceError, OSError, KeyError, TypeError, ValueError):
                # 若历史任务包无法接受迁移，保留 operation-call 原始回执，继续保守阻断。
                continue
            outcome.update({'status': 'recognition_failed', 'error': recognition_error})
            changed = True
            # _record 会增加任务数据版本；刷新快照，使同一批次后续候选基于最新 revision。
            try:
                task = self.tasks.snapshot(data['taskKey'])
                items_by_key = {value.get('item_key'): value for value in task.get('items', [])}
            except (WorkspaceError, KeyError, TypeError):
                break

        if changed:
            remaining_failed = any(item.get('status') == 'failed' for item in data.get('itemResults', []))
            unresolved = any(item.get('status') == 'reconcile_required' for item in data.get('itemResults', []))
            completed_scope = all(
                any(item.get('localId') == (scope.get('localId') or scope.get('local_id')) for item in data.get('itemResults', []))
                for scope in data.get('scope', [])
            )
            if not remaining_failed and not unresolved and completed_scope:
                self.update(entry['id'], status='completed', itemResults=data['itemResults'],
                            message='识别请求已完成；部分候选未能识别出硬币版本，结果已保留供审核')
            else:
                self.update(entry['id'], itemResults=data['itemResults'])
        return changed

    def update(self, operation_id, **values):
        entry = self.store.get_entity('operation', operation_id)
        return self.store.save_entity('operation', operation_id, {**entry['data'], **values}, entry['revision'], 'system:executor')

    def account(self):
        status = json.loads(self.runner(['status']))
        safe_json(status)
        if not status.get('authenticated') or not status.get('accountSubject') or not status.get('api_base_url'):
            raise WorkspaceError('account_required', '线上操作需要已登录且提供稳定账户标识的新版 CLI；请检查 status 或重新登录', 409)
        return {'subject': status['accountSubject'], 'apiBaseUrl': status['api_base_url']}

    def account_profile(self):
        """账号展示资料只给本次页面请求，不走归档或查询诊断日志。"""
        for argv in (['api', 'profile'], ['status']):
            try:
                value = json.loads(self.runner(argv))
            except (WorkspaceError, ValueError, TypeError):
                continue
            if not isinstance(value, dict) or type(value.get('authenticated')) is not bool:
                continue
            if not value['authenticated']:
                return {'authenticated': False}
            profile = {'authenticated': True}
            if value.get('provider') in ('google', 'apple'):
                profile['provider'] = value['provider']
            if argv == ['status']:
                # 兼容尚未支持资料读取的 CLI，忽略 status 里的账户标识和其他字段。
                return profile
            nickname, avatar = value.get('nickname'), value.get('avatarUrl')
            if isinstance(nickname, str) and nickname.strip():
                profile['nickname'] = nickname.strip()
            if isinstance(avatar, str) and avatar.isascii() and not any(ch.isspace() or ord(ch) < 32 for ch in avatar):
                try:
                    url = urlsplit(avatar)
                    if url.scheme == 'https' and url.netloc.lower() in PROFILE_AVATAR_HOSTS:
                        profile['avatarUrl'] = avatar
                except ValueError:
                    pass
            return profile
        return {}

    def api_check(self):
        """经已安装 CLI 检查当前 API host；结果仅返回页面，不创建操作或修改工作区数据。"""
        argv = ['api', 'check']
        raw = None
        try:
            raw = self.runner(argv)
            value = json.loads(raw)
            safe_json(value)
            if (not isinstance(value, dict) or not isinstance(value.get('host'), dict)
                    or not isinstance(value.get('api'), dict) or type(value['api'].get('ok')) is not bool):
                raise WorkspaceError('cli_invalid_output', 'CLI 未返回 API 网络检查结果', 409)
            return value
        except Exception as exc:
            self._record_query_failure(argv, raw, exc)
            raise

    def query(self, argv):
        """执行只读 CLI 查询；异常时留下独立日志，便于排查页面数据来源。

        写操作已有 operation / operation-call 的完整审计链。只读调用不属于执行
        计划，因此在这里单独归档失败；成功查询不额外落库，避免服务目录等高频刷新
        让 heribase.sqlite 无意义增长。
        """

        raw = None
        try:
            raw = self.runner(argv)
            _, result = result_value(raw)
            return result
        except Exception as exc:
            self._record_query_failure(argv, raw, exc)
            try:
                envelope = json.loads(raw) if isinstance(raw, (str, bytes)) else {}
                error = (envelope.get('error') or {}) if isinstance(envelope, dict) else {}
            except (ValueError, TypeError):
                envelope, error = {}, {}
            if (isinstance(envelope, dict) and envelope.get('status') == 'failed'
                    and isinstance(error, dict) and error.get('code') in {'UNAUTHENTICATED', 'AUTH_REQUIRED'}):
                raise WorkspaceError('account_required',
                    'HeriBase 未接受当前登录凭据，请重新登录后检查连接。照片已保存在本机。', 401) from exc
            # A typed business error for known read-only service contract failures.
            # Write outcomes retain their original reconciliation semantics.
            if "Agent API response is not valid JSON" in str(exc):
                raise WorkspaceError("service_invalid_response",
                    "HeriBase 线上服务暂未返回可用结果，请稍后重新检查连接。照片已保存在本机。", 502) from exc
            raise

    def _record_query_failure(self, argv, raw, exc):
        """尽最大努力归档查询异常，日志写入失败不能掩盖原始 CLI 错误。"""

        parsed = None
        if isinstance(raw, bytes):
            try:
                value = json.loads(raw)
                parsed = value if isinstance(value, dict) else None
            except (TypeError, ValueError):
                pass
        error = {
            'code': exc.code if isinstance(exc, WorkspaceError) else 'cli_query_exception',
            'message': str(exc),
        }
        try:
            self.store.save_entity(
                'cli-query-log',
                'query-' + secrets.token_hex(12),
                {
                    'argv': argv,
                    'queriedAt': self.store.timestamp(),
                    'status': parsed.get('status', 'exception') if parsed else 'exception',
                    'cliTaskId': (parsed.get('id') or parsed.get('taskId') if parsed else None),
                    # 用户当前需要保留排障上下文，原始 stdout 暂不做摘要化处理。
                    'stdout': raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else None,
                    'error': error,
                },
                0,
                'system:executor',
            )
        except Exception:
            # 例如磁盘满或数据库暂时不可写时，仍优先把 CLI 的原始异常返回给页面。
            pass

    def identification_plan(self, key, revision, local_ids=None):
        current = self.tasks._checked(key, revision)
        items = []
        for item in current['items']:
            active = item.get('active_identification') or {}
            review = item.get('review_projection') or {}
            if (
                operations.identification_eligible(item)
                and active.get('status') != 'succeeded'
                and not (review.get('decision') in {'exclude', 'need_photo'} and not review.get('stale'))
            ):
                items.append(
                    {
                        'localId': item['local_id'],
                        'version': item['version'],
                        'roles': operations.identification_source_roles(item),
                        'title': operations.display_for_item(item).get('title') or item['item_key'],
                    }
                )
        if local_ids is not None:
            if not isinstance(local_ids, list) or not local_ids or any(not isinstance(i, str) for i in local_ids) or len(set(local_ids)) != len(local_ids):
                raise WorkspaceError('invalid_scope', '请选择不重复的识别对象')
            indexed = {i['localId']: i for i in items}
            if any(i not in indexed for i in local_ids):
                raise WorkspaceError('invalid_scope', '选中对象包含未准备好或已识别的候选', 409)
            items = [indexed[i] for i in local_ids]
        if not items:
            raise WorkspaceError('no_eligible_items', '没有已确认配对、尚未成功识别的条目', 409)
        scope = {'taskKey': key, 'revision': revision, 'fingerprint': current['manifest']['dataset_fingerprint'], 'items': items, 'account': self.account()}
        return {**scope, 'hash': digest(scope)}

    def collection_plan(self, key, revision, ids, actor):
        current = self.tasks._checked(key, revision)
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise WorkspaceError('invalid_selection', '请选择不重复的收藏条目')
        from workspace_review import collect_reason

        if any(collect_reason(i) for i in current['items'] if i['local_id'] in ids):
            raise WorkspaceError('review_conflict', '所选候选仍有未核对的资料差异', 409)
        # 容量查询失败则不生成可确认计划；不自行推断已有容量。
        account = self.account()
        binding = self.store.get_entity('task-account', key)
        if binding and binding['data'] != account:
            raise WorkspaceError('account_changed', '当前账户与此任务的识别账户不同', 409)
        capacity = self.query(['collection', 'capacity'])
        plan = self.tasks._call(key, revision, actor, operations.build_plan, operation='collection_add', operations_json=None, local_ids=ids)
        self.store.save_entity('plan-account', plan['plan_id'], account, 0, actor)
        return {**plan, 'capacity': capacity, 'account': account}

    @staticmethod
    def _collection_changes(changes):
        if not isinstance(changes, dict) or not changes:
            raise WorkspaceError('invalid_changes', '请至少修改一个收藏字段')
        if set(changes) - set(COLLECTION_UPDATE_FLAGS) - {COLLECTION_IMAGE_SOURCE_IDS}:
            raise WorkspaceError('invalid_changes', '包含不支持的收藏字段')
        clean = {}
        for key, value in changes.items():
            if key == COLLECTION_IMAGE_SOURCE_IDS:
                if (
                    not isinstance(value, list)
                    or not 1 <= len(value) <= 3
                    or len(set(value)) != len(value)
                    or any(not isinstance(source_id, str) or not source_id for source_id in value)
                ):
                    raise WorkspaceError('invalid_changes', '收藏图片必须是 1–3 张不同的已归档照片')
                clean[key] = value
                continue
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise WorkspaceError('invalid_changes', f'{key} 的值无效')
            if isinstance(value, float) and (value != value or value in {float('inf'), float('-inf')}):
                raise WorkspaceError('invalid_changes', f'{key} 不能是非有限数值')
            text = str(value)
            if len(text) > 5000:
                raise WorkspaceError('invalid_changes', f'{key} 过长')
            # 空值只对 CLI 明确支持的 notes / setUri 表示“主动清空”；其余字段省略。
            if text == '' and key not in {'notes', 'setUri'}:
                raise WorkspaceError('invalid_changes', f'{key} 不能为空')
            clean[key] = value
        return clean

    def collection_mutation_plan(self, key, revision, local_id, action, changes, actor):
        """先读取 edit-detail，再把一个精确的 update/cancel 意图写为任务包计划。"""
        if action not in {'update', 'cancel'}:
            raise WorkspaceError('invalid_operation', '只支持编辑或取消收藏')
        current = self.tasks._checked(key, revision)
        item = next((value for value in current['items'] if value['local_id'] == local_id), None)
        if not item:
            raise WorkspaceError('invalid_selection', '未找到当前收藏档案', 404)
        projection = item.get('collection_projection') or {}
        if projection.get('status') != 'succeeded' or not projection.get('collection_uri'):
            raise WorkspaceError('collection_required', '仅已建立收藏关联的档案可以编辑或取消', 409)
        clean_changes = self._collection_changes(changes) if action == 'update' else {}
        image_sources = clean_changes.get(COLLECTION_IMAGE_SOURCE_IDS, [])
        evidence_sources = {e.get('source_id') for e in item.get('evidence', [])}
        if any(source_id not in evidence_sources for source_id in image_sources):
            raise WorkspaceError('invalid_changes', '收藏图片必须来自当前藏品已关联的证据')
        if action == 'cancel' and changes not in ({}, None):
            raise WorkspaceError('invalid_changes', '取消收藏不接受字段修改')
        account = self.account()
        binding = self.store.get_entity('task-account', key)
        if binding and binding['data'] != account:
            raise WorkspaceError('account_changed', '当前账户与收藏档案的执行账户不同', 409)
        # edit-detail 是只读基线，既给用户核对，也作为本地历史的编辑前快照。
        before = self.query(['collection', 'edit-detail', '--collection-uri', projection['collection_uri'], '--batch-id', key, '--candidate-id', item['item_key']])
        intent = {'operations': [{'local_id': local_id, 'changes': clean_changes}]}
        with tempfile.TemporaryDirectory(prefix='collection-intent-', dir=str(self.store.directory)) as temporary:
            path = Path(temporary) / 'intent.json'
            path.write_text(safe_json(intent), encoding='utf-8')
            plan = self.tasks._call(
                key,
                revision,
                actor,
                operations.build_plan,
                operation='collection_update' if action == 'update' else 'collection_cancel',
                operations_json=str(path),
                local_ids=[local_id],
                remote_before=before,
            )
        self.store.save_entity('plan-account', plan['plan_id'], account, 0, actor)
        return {**plan, 'account': account, 'remoteBefore': before}

    def _existing(self, body, kind):
        identifier(body['commandId'])
        entry = self.store.get_entity('operation', body['commandId'])
        if entry:
            if entry['data']['requestHash'] != digest({'kind': kind, 'body': body}):
                raise WorkspaceError('idempotency_conflict', '同一操作 ID 不能用于不同内容', 409)
            return entry
        return None

    def assert_idle(self, key):
        for entry in self.store.list_entities('operation'):
            data = entry['data']
            if data.get('taskKey') == key and data['status'] in {'preparing', 'queued', 'running', 'reconcile_required', 'partial_failed'}:
                raise WorkspaceError('operation_pending', '此任务有执行中或待核验操作，请先处理执行记录', 409)

    def _reserve(self, body, kind, actor, expected_account):
        self.assert_idle(body['taskKey'])
        if self.account() != expected_account:
            raise WorkspaceError('account_changed', '账户在确认过程中变化，请重新检查范围', 409)
        task = self.tasks.snapshot(body['taskKey'])
        operation_name = {
            'identify': '上传与识别',
            'collect': '逐条加入收藏',
            'collection_update': '编辑收藏资料',
            'collection_cancel': '取消收藏',
        }.get(kind, kind)
        started = datetime.now().strftime('%Y-%m-%d %H:%M')
        return self.store.save_entity(
            'operation',
            body['commandId'],
            {
                'kind': kind,
                'label': f"{operation_name} · {task['manifest']['display_name']} · {started}",
                'taskKey': body['taskKey'],
                'requestHash': digest({'kind': kind, 'body': body}),
                'request': body,
                'account': expected_account,
                'status': 'preparing',
                'actor': actor,
                'calls': [],
                'itemResults': [],
                'message': '正在保存本次确认范围',
            },
            0,
            actor,
        )

    def identify(self, body, actor):
        with self.lock:
            existing = self._existing(body, 'identify')
            if existing:
                return existing
            self.assert_idle(body['taskKey'])
            plan = self.identification_plan(body['taskKey'], body['expectedRevision'], body['localIds'])
            if body['planHash'] != plan['hash'] or body['localIds'] != [i['localId'] for i in plan['items']]:
                raise WorkspaceError('stale_plan', '识别清单已变化，请重新检查范围', 409)
            eligibility = self.query(['identify', 'eligibility'])
            if isinstance(eligibility, dict):
                if eligibility.get('allowed') is False:
                    raise WorkspaceError('not_eligible', '今日识别额度已用完。', 409, eligibility=eligibility)
                remaining = eligibility.get('remainingTimes')
                # 缺值表示服务未给出数值。只有明确余量不足才阻止整个已确认范围。
                if type(remaining) is int and 0 <= remaining < len(plan['items']):
                    raise WorkspaceError('identify_quota_insufficient', f'今日还可识别 {remaining} 枚，请减少勾选后再确认。', 409,
                                         eligibility=eligibility)
            binding = self.store.get_entity('task-account', body['taskKey'])
            if binding and binding['data'] != plan['account']:
                raise WorkspaceError('account_changed', '当前账户与此任务已有账户绑定不同', 409)
            if not binding:
                self.store.save_entity('task-account', body['taskKey'], plan['account'], 0, actor)
            self._reserve(body, 'identify', actor, plan['account'])
            try:
                authorization = self.tasks._call(
                    body['taskKey'], body['expectedRevision'], actor, operations.authorize_identification, local_ids=body['localIds'], confirmed_by=actor
                )
            except Exception:
                self.update(body['commandId'], status='blocked', message='授权未完成，未开始执行')
                raise
            self.update(body['commandId'], status='queued', confirmation=authorization, scope=plan['items'])
            return self._dispatch(body['commandId'], self._identify_items)

    def collect(self, body, actor):
        with self.lock:
            existing = self._existing(body, 'collect')
            if existing:
                return existing
            self.assert_idle(body['taskKey'])
            current = self.tasks._checked(body['taskKey'], body['expectedRevision'])
            if not current['plan'] or current['plan']['plan_id'] != body['planId'] or current['plan']['payload_sha256'] != body['planHash']:
                raise WorkspaceError('stale_plan', '收藏计划已变化', 409)
            from workspace_review import collect_reason

            planned_ids = {i['local_id'] for i in current['plan']['items']}
            if any(collect_reason(i) for i in current['items'] if i['local_id'] in planned_ids):
                raise WorkspaceError('review_conflict', '收藏范围仍有未核对的资料差异，请重新审核', 409)
            binding = self.store.get_entity('plan-account', body['planId'])
            if not binding or binding['data'] != self.account():
                raise WorkspaceError('account_changed', '收藏账户已变化，请重新检查计划', 409)
            self._reserve(body, 'collect', actor, binding['data'])
            try:
                authorization = self.tasks._call(
                    body['taskKey'],
                    body['expectedRevision'],
                    actor,
                    operations.authorize_plan,
                    plan_id=body['planId'],
                    confirmed_payload_sha256=body['planHash'],
                    confirmed_by=actor,
                )
            except Exception:
                self.update(body['commandId'], status='blocked', message='收藏授权未完成，未开始执行')
                raise
            self.update(body['commandId'], status='queued', confirmation=authorization, scope=current['plan']['items'])
            return self._dispatch(body['commandId'], self._collect_items)

    def collection_mutation(self, body, actor):
        """执行已绑定摘要的单枚编辑或取消；不复用新增收藏的审核前置条件。"""
        with self.lock:
            action = body.get('action')
            kind = 'collection_update' if action == 'update' else 'collection_cancel' if action == 'cancel' else None
            if kind is None:
                raise WorkspaceError('invalid_operation', '只支持编辑或取消收藏')
            existing = self._existing(body, kind)
            if existing:
                return existing
            self.assert_idle(body['taskKey'])
            current = self.tasks._checked(body['taskKey'], body['expectedRevision'])
            plan = current.get('plan') or {}
            if plan.get('plan_id') != body['planId'] or plan.get('payload_sha256') != body['planHash'] or plan.get('operation_type') != kind:
                raise WorkspaceError('stale_plan', '收藏编辑计划已变化，请重新读取并确认', 409)
            binding = self.store.get_entity('plan-account', body['planId'])
            if not binding or binding['data'] != self.account():
                raise WorkspaceError('account_changed', '账户已变化，请重新检查编辑范围', 409)
            self._reserve(body, kind, actor, binding['data'])
            try:
                authorization = self.tasks._call(
                    body['taskKey'],
                    body['expectedRevision'],
                    actor,
                    operations.authorize_plan,
                    plan_id=body['planId'],
                    confirmed_payload_sha256=body['planHash'],
                    confirmed_by=actor,
                )
            except Exception:
                self.update(body['commandId'], status='blocked', message='编辑授权未完成，未发出远程请求')
                raise
            self.update(body['commandId'], status='queued', confirmation=authorization, scope=plan['items'])
            return self._dispatch(body['commandId'], self._mutate_collection_items)

    def inspect(self, operation_id):
        entry = self.store.get_entity('operation', operation_id)
        if not entry:
            raise WorkspaceError('operation_not_found', '执行记录不存在', 404)
        if entry['data']['account'] != self.account():
            raise WorkspaceError('account_changed', '请切回执行时的账户和服务地址再核验', 409)
        results = []
        unmatched = []
        for call in entry['data']['calls']:
            saved = self.store.get_entity('operation-call', call.get('id', ''))
            stdout = saved['data'].get('stdout') if saved else call.get('stdout')
            envelope = json.loads(stdout) if stdout else {}
            task_id = envelope.get('id') or envelope.get('taskId')
            if task_id:
                raw = self.runner(['task', 'get', task_id])
                value = json.loads(raw)
                safe_json(value)
                results.append({'taskId': task_id, 'task': value})
            else:
                unmatched.append({'id': call.get('id'), 'argv': call['argv']})
        if unmatched:
            # 提交超时而没有 taskId 时只查询列表，不能自动按“最近一条”猜归属。
            value = json.loads(self.runner(['task', 'list']))
            safe_json(value)
            results.append({'unmatchedCalls': unmatched, 'unmatchedLocalTasks': value})
        return self.update(
            operation_id, inspection={'queriedAt': self.store.timestamp(), 'results': results}, message='已查询原 CLI 任务；由宿主核对对象、归档真实结果后完成恢复。'
        )

    @staticmethod
    def expected_request(argv):
        # 仅覆盖执行器确实能创建的命令；不接受宿主任意 CLI 输入。
        if argv[0] == 'identify':
            operation, offset = 'identify', 1
        else:
            operation, offset = '.'.join(argv[:2]), 2
        if operation not in {
            'identify',
            'file.upload',
            'collection.add',
            'collection.update',
            'collection.cancel',
            'collection.edit-detail',
            'appraisals.submit',
            'appraisals.checkout',
            'tracking.checkout',
            'tracking.add',
        }:
            raise WorkspaceError('invalid_recovery', '不支持此调用的恢复')
        fields, context = {}, {}
        for index in range(offset, len(argv), 2):
            flag, value = argv[index], argv[index + 1]
            if flag in {'--batch-id', '--candidate-id'}:
                context['batchId' if flag == '--batch-id' else 'candidateId'] = value
            else:
                words = flag[2:].split('-')
                key = words[0] + ''.join(word.title() for word in words[1:])
                fields[key] = int(value) if flag in {'--appraiser-type', '--appraiser-id'} else value
        return operation, fields, context

    def reconcile_identification(self, operation_id):
        """为待核验识别执行只读远端查询；只有图片顺序唯一匹配才归档并恢复。

        浏览器只传 operation ID。CLI task ID、候选和图片均从已持久化的原调用中
        读取，避免把核验入口变成可查询任意远端识别记录的通用接口。
        """
        with self.lock:
            entry = self.store.get_entity('operation', operation_id)
            if not entry or entry['data'].get('status') != 'reconcile_required' or entry['data'].get('kind') != 'identify':
                raise WorkspaceError('invalid_reconciliation', '仅待核验的识别执行记录可执行远端核验', 409)
            data = entry['data']
            task = self.tasks.snapshot(data['taskKey'])
            item_by_key = {item.get('item_key'): item for item in task.get('items', [])}
            scoped_local_ids = {item.get('localId') for item in data.get('scope', [])}
            pending = {
                item.get('localId') for item in data.get('itemResults', [])
                if item.get('status') == 'reconcile_required'
            }
            calls = []
            for call in data.get('calls', []):
                argv = call.get('argv') or []
                if not argv or argv[0] != 'identify' or '--candidate-id' not in argv:
                    continue
                candidate_index = argv.index('--candidate-id') + 1
                candidate_key = argv[candidate_index] if candidate_index < len(argv) else None
                item = item_by_key.get(candidate_key)
                local_id = item.get('local_id') if item else None
                if local_id in pending and local_id in scoped_local_ids:
                    calls.append((call, item, local_id))
            # Older records may not have itemResults yet. A saved identify call with no
            # terminal CLI response is still explicitly unresolved and safe to query.
            if not calls:
                for call in data.get('calls', []):
                    argv = call.get('argv') or []
                    if argv and argv[0] == 'identify' and call.get('status') != 'completed':
                        candidate_key = self.expected_request(argv)[2].get('candidateId')
                        item = item_by_key.get(candidate_key)
                        if item and item.get('local_id') in scoped_local_ids:
                            calls.append((call, item, item['local_id']))
            if not calls:
                raise WorkspaceError('no_reconciliation_target', '执行记录中没有可核验的待处理识别调用', 409)

            attempts = list(data.get('remoteReconciliationAttempts', []))
            if any(attempt.get('status') == 'running' for attempt in attempts):
                raise WorkspaceError('reconciliation_in_progress', '此执行记录已有远端核验正在进行', 409)
            # 归档成功但尚未更新工作台时，直接走原恢复流程，避免重复保存识别事实。
            if any(self._recovered_identification(data, call, task) for call, _, _ in calls):
                return self.resume(operation_id)
            try:
                account_matches = self.account() == data.get('account')
                account_error = None if account_matches else {
                    'code': 'account_changed', 'message': '当前账户或服务地址与原执行记录不一致；请切回原账户后重试',
                }
            except Exception as exc:
                account_matches = False
                account_error = {
                    'code': exc.code if isinstance(exc, WorkspaceError) else 'account_unavailable',
                    'message': '当前账户状态不可用；请恢复登录状态后重新核验',
                }
            now = self.store.timestamp()
            verification_ids = []
            for call, _, local_id in calls:
                verification_id = 'reconcile-' + secrets.token_hex(12)
                verification_ids.append(verification_id)
                attempt = {
                    'verificationId': verification_id,
                    'callId': call['id'],
                    'cliTaskId': call.get('cliTaskId'),
                    'localId': local_id,
                    'startedAt': now,
                    'status': 'running' if account_matches else 'query_failed',
                    'searchComplete': False,
                    'candidateCount': 0,
                    'matchEvidence': {'accountMatched': account_matches, 'cliTaskMatched': False, 'imagesMatched': False},
                }
                if not account_matches:
                    attempt.update({'finishedAt': now, 'error': account_error})
                attempts.append(attempt)
            self.update(
                operation_id,
                remoteReconciliationAttempts=attempts,
                message=('正在只读核验远端识别结果；不会重新上传或发起识别' if account_matches
                         else '当前账户与原执行账户不符或不可用；核验已停止，原结果仍待核验'),
            )
            if not account_matches:
                return self.store.get_entity('operation', operation_id)

        def run_reconciliation():
            matched_any = False
            for verification_id, (call, item, local_id) in zip(verification_ids, calls):
                try:
                    attempt = next(
                        value for value in self.store.get_entity('operation', operation_id)['data'].get('remoteReconciliationAttempts', [])
                        if value.get('verificationId') == verification_id
                    )
                    result = self._reconcile_identification_call(
                        operation_id, call, item, local_id, attempt['startedAt'], verification_id,
                    )
                    self._update_reconciliation_attempt(operation_id, verification_id, **result)
                    matched_any = matched_any or result.get('status') == 'matched'
                except Exception as exc:
                    code = exc.code if isinstance(exc, WorkspaceError) else 'remote_query_failed'
                    message = str(exc) if isinstance(exc, WorkspaceError) else '远端只读查询或归档失败；原结果仍待核验'
                    self._update_reconciliation_attempt(
                        operation_id, verification_id,
                        status='query_failed', finishedAt=self.store.timestamp(),
                        searchComplete=False,
                        error={'code': code, 'message': message},
                    )
            if matched_any:
                try:
                    # resume 只复用刚归档的原始详情并处理原授权范围内安全的未执行项。
                    self.resume(operation_id)
                except Exception as exc:
                    latest = self.store.get_entity('operation', operation_id)['data']
                    self.update(operation_id, message='远端结果已归档；恢复执行记录未完成，请查看核验记录后重试',
                                remoteReconciliationAttempts=[
                                    {**attempt, 'resumeErrorCode': exc.code if isinstance(exc, WorkspaceError) else 'resume_failed'}
                                    if attempt.get('status') == 'matched' else attempt
                                    for attempt in latest.get('remoteReconciliationAttempts', [])
                                ])
            else:
                latest = self.store.get_entity('operation', operation_id)['data']
                outcomes = {attempt.get('status') for attempt in latest.get('remoteReconciliationAttempts', [])}
                message = (
                    '远端查询已完成，但没有唯一精确匹配；结果仍待核验，未重试上传或识别'
                    if outcomes and outcomes <= {'no_match'}
                    else '远端核验未能唯一确认结果；执行记录仍待核验，未重试上传或识别'
                )
                self.update(operation_id, message=message)

        thread = threading.Thread(target=run_reconciliation, daemon=True)
        self.threads.append(thread)
        thread.start()
        return self.store.get_entity('operation', operation_id)

    def _update_reconciliation_attempt(self, operation_id, verification_id, **changes):
        with self.lock:
            entry = self.store.get_entity('operation', operation_id)
            attempts = []
            found = False
            for attempt in entry['data'].get('remoteReconciliationAttempts', []):
                if attempt.get('verificationId') == verification_id:
                    attempts.append({**attempt, **changes})
                    found = True
                else:
                    attempts.append(attempt)
            if found:
                return self.update(operation_id, remoteReconciliationAttempts=attempts)
            return entry

    @staticmethod
    def _timestamp_seconds(value):
        """把远端/CLI 时间规范为 epoch 秒；无法解析时由调用方判定搜索不完整。"""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value) / 1000 if value > 10_000_000_000 else float(value)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    return None
                return parsed.timestamp()
            except ValueError:
                return None
        return None

    def _reconcile_identification_call(self, operation_id, call, item, local_id, reconciliation_started_at, verification_id):
        """校验原 CLI 任务，完整扫描远端识别分页，并归档唯一图片精确匹配。"""
        operation = self.store.get_entity('operation', operation_id)['data']
        account = operation['account']
        if self.account() != account:
            raise WorkspaceError('account_changed', '核验账户与原执行账户不一致', 409)
        self._update_reconciliation_attempt(
            operation_id, verification_id,
            matchEvidence={'accountMatched': True, 'cliTaskMatched': False, 'imagesMatched': False},
        )

        task_id = call.get('cliTaskId')
        if not isinstance(task_id, str) or not task_id:
            raise WorkspaceError('missing_cli_task', '原调用没有 CLI task ID，无法确认请求上下文', 409)
        task_raw = self.runner(['task', 'get', identifier(task_id)])
        try:
            cli_task = json.loads(task_raw)
            safe_json(cli_task)
        except (ValueError, TypeError) as exc:
            raise WorkspaceError('invalid_cli_task', '原 CLI task 查询没有返回有效 JSON', 409) from exc
        expected_operation, expected_input, expected_context = self.expected_request(call.get('argv') or [])
        cli_request = cli_task.get('request') or {}
        cli_context = cli_task.get('context') or {}
        if (
            cli_task.get('id') != task_id
            or cli_task.get('operation') != expected_operation
            or cli_request.get('input') != expected_input
            or cli_request.get('apiBaseUrl') != account['apiBaseUrl']
            or cli_task.get('accountSubject') != account['subject']
            or cli_context != expected_context
            or expected_context.get('batchId') != operation['taskKey']
            or expected_context.get('candidateId') != item.get('item_key')
        ):
            raise WorkspaceError('cli_task_mismatch', '原 CLI task 的操作、输入、账户或候选上下文不匹配', 409)
        self._update_reconciliation_attempt(
            operation_id, verification_id,
            matchEvidence={'accountMatched': True, 'cliTaskMatched': True, 'imagesMatched': False},
        )

        argv = call.get('argv') or []
        try:
            front_url = argv[argv.index('--front-img') + 1]
            back_url = argv[argv.index('--back-img') + 1]
        except (ValueError, IndexError) as exc:
            raise WorkspaceError('invalid_original_request', '原识别调用缺少正反面图片地址', 409) from exc
        started_at = self._timestamp_seconds(call.get('startedAt'))
        if started_at is None:
            raise WorkspaceError('invalid_original_request', '原识别调用缺少可核验的开始时间', 409)
        # 允许远端和本机时钟有最多五分钟偏差；图片顺序仍须精确相同，且查询遍历全部页。
        earliest = started_at - 300
        latest = self._timestamp_seconds(self.store.timestamp()) or datetime.now().timestamp()

        list_records = []
        search_complete = False
        first_page_signature = None
        for page_number in range(1, 1001):
            if self.account() != account:
                raise WorkspaceError('account_changed', '分页查询期间账户或服务地址已变化，停止核验', 409)
            raw = self.runner(['identify', 'list', '--page', str(page_number), '--page-size', '100'])
            _, page = result_value(raw)
            if not isinstance(page, dict) or page.get('page') != page_number or not isinstance(page.get('isEnd'), bool) or not isinstance(page.get('list'), list):
                raise WorkspaceError('invalid_identify_list', '远端识别列表分页响应不完整', 409)
            if page_number == 1:
                first_page_signature = [record.get('uri') for record in page['list'] if isinstance(record, dict)]
            for record in page['list']:
                if not isinstance(record, dict) or not isinstance(record.get('uri'), str):
                    raise WorkspaceError('invalid_identify_list', '远端识别列表包含无效记录', 409)
                created_at = self._timestamp_seconds(record.get('createdAt'))
                if created_at is None:
                    raise WorkspaceError('invalid_identify_timestamp', '远端识别列表缺少可核验的创建时间；搜索范围不完整', 409)
                if earliest <= created_at <= latest:
                    list_records.append(record)
            if page['isEnd']:
                search_complete = True
                break
        if search_complete:
            # 页码列表在读取期间可能因新识别插入而移动。复查首页能发现明显漂移，
            # 有漂移时不把本轮扫描当成完整证据，用户可以稍后再发起只读核验。
            if self.account() != account:
                raise WorkspaceError('account_changed', '分页复查期间账户或服务地址已变化，停止核验', 409)
            _, first_page_again = result_value(self.runner(['identify', 'list', '--page', '1', '--page-size', '100']))
            if not isinstance(first_page_again, dict) or not isinstance(first_page_again.get('list'), list):
                search_complete = False
            else:
                current_signature = [record.get('uri') for record in first_page_again['list'] if isinstance(record, dict)]
                search_complete = current_signature == first_page_signature
        if not search_complete:
            return {
                'status': 'no_match', 'finishedAt': self.store.timestamp(), 'searchComplete': False,
                'candidateCount': 0, 'detailsChecked': 0,
                'matchEvidence': {'accountMatched': True, 'cliTaskMatched': True, 'imagesMatched': False},
                'error': {'code': 'identify_list_incomplete', 'message': '识别列表分页未到终点或查询期间列表发生变化；未据此判断远端无结果'},
            }

        exact_matches = []
        for record in list_records:
            if self.account() != account:
                raise WorkspaceError('account_changed', '查询详情期间账户或服务地址已变化，停止核验', 409)
            raw = self.runner([
                'identify', 'detail', '--uri', record['uri'],
                '--batch-id', operation['taskKey'], '--candidate-id', item['item_key'],
            ])
            _, detail = result_value(raw)
            images = detail.get('images') if isinstance(detail, dict) else None
            if images == [front_url, back_url]:
                exact_matches.append((record, raw))

        evidence = {'accountMatched': True, 'cliTaskMatched': True, 'imagesMatched': bool(exact_matches)}
        self._update_reconciliation_attempt(operation_id, verification_id, matchEvidence=evidence)
        if len(exact_matches) != 1:
            return {
                'status': 'no_match' if not exact_matches else 'ambiguous',
                'finishedAt': self.store.timestamp(), 'searchComplete': True,
                'candidateCount': len(exact_matches), 'detailsChecked': len(list_records), 'matchEvidence': evidence,
                'error': None if not exact_matches else {'code': 'multiple_exact_matches', 'message': '找到多条正反面图片完全相同的远端记录，未自动归档'},
            }

        record, raw = exact_matches[0]
        current = self.tasks.snapshot(operation['taskKey'])
        current_item = next((value for value in current.get('items', []) if value.get('local_id') == local_id), None)
        if not current_item or current_item.get('item_key') != item.get('item_key'):
            raise WorkspaceError('candidate_changed', '核验期间候选已变化，未归档远端结果', 409)
        existing = self._recovered_identification(operation, call, current)
        if existing:
            return {
                'status': 'matched', 'finishedAt': self.store.timestamp(), 'searchComplete': True,
                'candidateCount': 1, 'detailsChecked': len(list_records), 'matchEvidence': evidence,
                'identifyUri': existing['identifyUri'], 'recognitionAttemptId': existing['attemptId'],
            }

        remote_task_id = cli_task.get('id') or cli_task.get('taskId')
        attempt_id = 'recognition-reconcile-' + secrets.token_hex(12)
        evidence_hashes = [
            {'evidence_id': evidence_item['evidence_id'],
             'sha256': next(source['sha256'] for source in current['sources'] if source['source_id'] == evidence_item['source_id'])}
            for evidence_item in current_item.get('evidence', [])
        ]
        event = {
            'schema_version': 'heribase.recognition-attempt.v1',
            'attempt_id': attempt_id,
            'task_key': operation['taskKey'],
            'local_id': local_id,
            'attempt_number': int(call.get('attempt', 1)),
            'operation_type': 'reconcile',
            'status': 'succeeded',
            'input': {'item_version': current_item['version'], 'evidence': evidence_hashes},
            'cli': {'command': 'heribase identify detail', 'args': ['--uri', record['uri'], '--batch-id', operation['taskKey'], '--candidate-id', item['item_key'], '--json']},
            'remote_task_id': remote_task_id,
            'started_at': reconciliation_started_at,
            'finished_at': operations.now_iso(),
            'exit_code': 0,
            'classification': 'success',
            'raw_response_ref': None,
            'raw_response_sha256': None,
            'error': None,
        }
        archived = self._record(operation_id, current, event, raw)
        if archived.get('status') != 'succeeded' or archived.get('attempt_id') != attempt_id:
            raise WorkspaceError('reconciliation_archive_failed', '任务包没有确认远端识别结果归档成功', 409)
        return {
            'status': 'matched', 'finishedAt': self.store.timestamp(), 'searchComplete': True,
            'candidateCount': 1, 'detailsChecked': len(list_records), 'matchEvidence': evidence,
            'identifyUri': record['uri'], 'recognitionAttemptId': attempt_id,
            'error': None,
        }

    def reconcile(self, operation_id, matches):
        with self.lock:
            entry = self.store.get_entity('operation', operation_id)
            if not entry or entry['data']['status'] != 'reconcile_required' or not isinstance(matches, list):
                raise WorkspaceError('invalid_recovery', '需要待核验执行记录和调用对应关系', 409)
            account = entry['data']['account']
            if self.account() != account:
                raise WorkspaceError('account_changed', '请切回执行时的账户', 409)
            calls = entry['data']['calls']
            for match in matches:
                if not isinstance(match, dict) or set(match) != {'callId', 'taskId'}:
                    raise WorkspaceError('invalid_recovery', '每项对应关系必须为 callId/taskId')
                call = next((c for c in calls if c['id'] == match['callId']), None)
                if not call:
                    raise WorkspaceError('invalid_recovery', '调用不属于此执行记录')
                saved = self.store.get_entity('operation-call', call['id'])
                existing = json.loads(saved['data']['stdout']) if saved else {}
                known_id = call.get('cliTaskId') or existing.get('id') or existing.get('taskId')
                if existing.get('status') == 'completed':
                    raise WorkspaceError('already_archived', '已归档的成功响应不能被替换；直接恢复本地归档即可', 409)
                if known_id and known_id != match['taskId']:
                    raise WorkspaceError('recovery_mismatch', '只能刷新已保存的同一 CLI 任务 ID', 409)
                raw = self.runner(['task', 'get', identifier(match['taskId'])])
                envelope = json.loads(raw)
                safe_json(envelope)
                operation, expected, context = self.expected_request(call['argv'])
                request = envelope.get('request') or {}

                def same_request(candidate):
                    request = candidate.get('request') or {}
                    return (
                        candidate.get('operation') == operation
                        and request.get('input') == expected
                        and request.get('apiBaseUrl') == account['apiBaseUrl']
                        and all((candidate.get('context') or {}).get(k) == v for k, v in context.items())
                        and candidate.get('accountSubject') in {None, account['subject']}
                        and (candidate.get('status') != 'completed' or candidate.get('accountSubject') == account['subject'])
                    )

                if envelope.get('id') != match['taskId'] or not same_request(envelope):
                    raise WorkspaceError('recovery_mismatch', 'CLI 任务与原对象、输入、环境或账户不一致', 409)
                if not known_id:
                    # 没拿到任务 ID 时，不能把更早的相同请求当作本次结果；也不能在
                    # 多个相同候选里猜一个成功/失败来解除未知写入的保护。
                    def instant(value):
                        try:
                            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            if parsed.tzinfo is None:
                                raise ValueError()
                            return parsed.timestamp()
                        except (ValueError, AttributeError):
                            raise WorkspaceError('recovery_mismatch', '缺少可核验的调用时间', 409)

                    lower = instant(call['startedAt'])
                    upper = instant(call.get('observedAt') or entry['data'].get('recoveryCutoff'))
                    listing = json.loads(self.runner(['task', 'list']))
                    if not isinstance(listing, list):
                        raise WorkspaceError('recovery_mismatch', 'CLI 任务列表格式不支持自动关联', 409)
                    candidates = [c for c in listing if isinstance(c, dict) and same_request(c) and lower <= instant(c.get('createdAt')) <= upper]
                    if len(candidates) != 1 or candidates[0].get('id') != match['taskId']:
                        raise WorkspaceError('recovery_mismatch', '缺失 ID 的调用必须在本次提交时间内唯一匹配，不能借用历史结果', 409)
                saved = self.store.get_entity('operation-call', call['id'])
                self.store.save_entity(
                    'operation-call',
                    call['id'],
                    {'operationId': operation_id, 'argv': call['argv'], 'stdout': raw.decode('utf-8')},
                    saved['revision'] if saved else 0,
                    'agent:reconcile',
                )
                call.update(status=envelope.get('status', 'unknown'), cliTaskId=envelope.get('id'))
            return self.update(operation_id, calls=calls, message='已保存核验结果；恢复只复用已完成调用，不会重放未知请求')

    def resume(self, operation_id, business=None):
        with self.lock:
            entry = self.store.get_entity('operation', operation_id)
            if not entry or entry['data']['status'] not in {'reconcile_required', 'partial_failed'}:
                raise WorkspaceError('invalid_recovery', '需要待核验或部分完成操作', 409)
            data = entry['data']
            if self.account() != data['account']:
                raise WorkspaceError('account_changed', '请切回执行账户后恢复', 409)
            if data['status'] == 'partial_failed':
                if data['kind'] not in {'identify', 'collect'}:
                    raise WorkspaceError('invalid_recovery', '该操作不支持按条重试', 409)
                failed_local_ids = {item.get('localId') for item in data.get('itemResults', []) if item.get('status') == 'failed' and isinstance(item.get('localId'), str)}
                if not failed_local_ids:
                    raise WorkspaceError('invalid_recovery', '没有可重试的失败条目', 409)
                # 失败项的远端结果虽已明确，但当前任务包必须仍可完整读取；否则
                # 无法安全确认图片、候选版本和原授权范围，不能把“重试”变成写入。
                self.tasks.snapshot(data['taskKey'])
                function = self._identify_items if data['kind'] == 'identify' else self._collect_items
                self.update(operation_id, status='queued', message='正在重试此前明确失败的条目')
                return self._dispatch(
                    operation_id,
                    lambda op: function(op, failed_local_ids),
                    completion_message=f'已仅重试 {len(failed_local_ids)} 个此前失败项并归档；未执行条目保持不变',
                )
            # 先校验每个已发 CLI 调用。未知的识别只有在任务包中找到同一候选、同一
            # 正反图片的成功归档时才可解除；其余未知调用仍阻断，绝不能靠重试碰运气。
            task = self.tasks.snapshot(data['taskKey'])
            calls = [dict(call) for call in data.get('calls', [])]
            item_results = {item['localId']: dict(item) for item in data.get('itemResults', []) if item.get('localId')}
            original_item_results = {local_id: dict(item) for local_id, item in item_results.items()}
            # 不确定结果只阻断对应候选。其余从未提交的候选仍在原确认范围内，
            # 可以继续；这个集合也会传给逐项执行器，确保未知请求绝不会被重发。
            unresolved_local_ids = {
                local_id for local_id, item in item_results.items()
                if item.get('status') == 'reconcile_required'
            }
            retryable_failure = False
            definite_failure = False
            recovered_any = False

            def local_id_for_call(call):
                argv = call.get('argv') or []
                if '--candidate-id' not in argv:
                    return None
                index = argv.index('--candidate-id') + 1
                candidate_id = argv[index] if index < len(argv) else None
                scoped_item = next((item for item in task['items'] if item.get('item_key') == candidate_id), None)
                local_id = scoped_item.get('local_id') if scoped_item else None
                return local_id if any(value.get('localId') == local_id for value in data.get('scope', [])) else None

            for call in calls:
                saved = self.store.get_entity('operation-call', call.get('id', ''))
                envelope = json.loads(saved['data']['stdout']) if saved else None
                if envelope and envelope.get('accountSubject') not in {None, data['account']['subject']}:
                    raise WorkspaceError('account_changed', '核验结果的账户不符', 409)

                recovered = self._recovered_identification(data, call, task)
                if recovered:
                    # 即便原 CLI stdout 缺失或带 reconciliationRequired，只要完整任务包
                    # 保存了该候选本次实际输入图片的原始成功响应，就可跳过该枚，不重发。
                    call['status'] = 'reconciled'
                    call['reconciledResult'] = recovered
                    item_results[recovered['localId']] = {
                        'localId': recovered['localId'],
                        'status': 'succeeded',
                        'attempts': int(call.get('attempt', 1)),
                        'recovered': True,
                        'updatedAt': self.store.timestamp(),
                    }
                    unresolved_local_ids.discard(recovered['localId'])
                    recovered_any = True
                    continue

                if not saved:
                    local_id = local_id_for_call(call)
                    if data['kind'] == 'identify' and local_id:
                        # CLI 任务还没有可核验终态时，只隔离这枚候选；后续未提交项可继续。
                        unresolved_local_ids.add(local_id)
                        item_results[local_id] = {
                            'localId': local_id, 'status': 'reconcile_required',
                            'attempts': int(call.get('attempt', 1)),
                            'error': {'code': 'cli_not_completed', 'message': 'CLI 任务尚无可核验终态'},
                            'updatedAt': self.store.timestamp(),
                        }
                        continue
                    raise WorkspaceError('recovery_incomplete', '仍有未匹配 CLI 任务的请求；未重新上传或识别', 409)

                try:
                    terminal, _ = result_value(saved['data']['stdout'])
                    if data['kind'] == 'identify' and terminal.get('status') == 'completed':
                        local_id = local_id_for_call(call)
                        if local_id in unresolved_local_ids:
                            # CLI 终态成功但任务包尚未回写时，清除阻断标记；随后执行器
                            # 会复用这份已保存 stdout 完成本地归档，不会再次发送远端请求。
                            unresolved_local_ids.discard(local_id)
                            item_results.pop(local_id, None)
                except WorkspaceError as exc:
                    local_id = local_id_for_call(call)

                    if exc.code == 'cli_retryable_failure':
                        retryable_failure = True
                        unresolved_local_ids.discard(local_id)
                        if local_id and local_id not in item_results:
                            item_results[local_id] = {
                                'localId': local_id, 'status': 'failed', 'attempts': int(call.get('attempt', 1)),
                                'error': {'code': exc.code, 'message': str(exc)}, 'updatedAt': self.store.timestamp(),
                            }
                        continue
                    if exc.code == 'cli_definite_failure':
                        definite_failure = True
                        unresolved_local_ids.discard(local_id)
                        if local_id and local_id not in item_results:
                            item_results[local_id] = {
                                'localId': local_id, 'status': 'failed', 'attempts': int(call.get('attempt', 1)),
                                'error': {'code': exc.code, 'message': str(exc)}, 'updatedAt': self.store.timestamp(),
                            }
                        continue
                    if exc.code == 'identify_limit' and data.get('eligibility'):
                        # 已知额度拒绝不会产生远端识别。这里仅恢复本批其他已提交的记录。
                        unresolved_local_ids.discard(local_id)
                        continue
                    if exc.code == 'cli_not_completed':
                        if data['kind'] == 'identify' and local_id:
                            # 当前候选保持待核验，继续处理其他安全的未提交候选。
                            # reconciliationRequired 仍然禁止再次上传/识别这一枚。
                            unresolved_local_ids.add(local_id)
                            remote_error = envelope.get('error') or {}
                            item_results[local_id] = {
                                'localId': local_id,
                                'status': 'reconcile_required',
                                'attempts': int(call.get('attempt', 1)),
                                'error': {
                                    'code': exc.code,
                                    'message': str(exc),
                                    **({'remoteCode': remote_error['code']} if remote_error.get('code') else {}),
                                    'reconciliationRequired': bool(remote_error.get('reconciliationRequired')),
                                },
                                'updatedAt': self.store.timestamp(),
                            }
                            continue
                        raise WorkspaceError(
                            'reconciliation_required',
                            '仍有识别结果无法与已归档的同候选正反面图片匹配；先核验远端结果，未重试任何条目',
                            409,
                        ) from exc
                    raise

            if recovered_any or item_results != original_item_results or calls != data.get('calls', []):
                self.update(
                    operation_id,
                    calls=calls,
                    itemResults=list(item_results.values()),
                    message='已核验归档结果；正在按原确认范围继续未完成条目',
                )
                data = self.store.get_entity('operation', operation_id)['data']

            if data['kind'] == 'identify' and data.get('eligibility'):
                if unresolved_local_ids:
                    return self.update(operation_id, message='额度已用完，仍有已提交的结果待核验。')
                return self.update(operation_id, status='blocked', message='已核验已提交的结果；额度恢复后请重新确认待识别条目。')

            if (
                (retryable_failure or definite_failure or unresolved_local_ids)
                and data['kind'] in {'identify', 'collect'}
            ):
                self.tasks.snapshot(data['taskKey'])
                function = self._identify_items if data['kind'] == 'identify' else self._collect_items
                # 识别恢复会跳过待核验项，只重试明确失败、处理从未发出的已授权条目。
                resume_message = (
                    '已隔离结果待核验的条目；正在继续其他未执行项，待核验项不会重发'
                    if unresolved_local_ids
                    else '已核验已发出的调用；正在重试明确失败项并继续未执行项'
                )
                self.update(operation_id, status='queued', message=resume_message)
                return self._dispatch(
                    operation_id,
                    lambda op: function(op),
                    completion_message='原确认范围中的安全可恢复条目已继续处理；未知结果未重发',
                )
            if definite_failure and data['kind'] in {'appraisal', 'tracking'}:
                kind = 'appraisal-draft' if data['kind'] == 'appraisal' else 'tracking-draft'
                draft = self.store.get_entity(kind, data['scope']['localId'])
                self.store.save_entity(kind, draft['id'], {**draft['data'], 'status': 'failed'}, draft['revision'], 'system:recovery')
                return self.update(operation_id, status='failed', message='已核验原调用明确失败；未重发未知请求')
            if data['kind'] in {'identify', 'collect'}:
                function = self._identify_items if data['kind'] == 'identify' else self._collect_items
            elif data['kind'] in {'collection_update', 'collection_cancel'}:
                function = self._mutate_collection_items
            else:
                if business is None:
                    raise WorkspaceError('invalid_recovery', '缺少对应业务恢复器')
                function = lambda op: business._execute(op, data['scope'], 'appraisal-draft' if data['kind'] == 'appraisal' else 'tracking-draft')
            self.update(operation_id, status='queued', message='复用已完成结果，继续原授权范围的未提交项')
            return self._dispatch(operation_id, function)

    def resolve(self, operation_id):
        entry = self.store.get_entity('operation', operation_id)
        if not entry or entry['data']['status'] != 'reconcile_required':
            raise WorkspaceError('invalid_recovery', '此操作不在待核验状态', 409)
        data = entry['data']
        if self.account() != data['account']:
            raise WorkspaceError('account_changed', '请切回执行时的账户', 409)
        for call in data['calls']:
            saved = self.store.get_entity('operation-call', call['id'])
            if not saved:
                raise WorkspaceError('recovery_incomplete', '仍有未知调用，不能结束核验', 409)
            result_value(saved['data']['stdout'])
        task = self.tasks.snapshot(data['taskKey'])
        items = {i['local_id']: i for i in task['items']}
        if data['kind'] == 'identify':
            own_ids = {c.get('cliTaskId') for c in data['calls'] if c['argv'][0] == 'identify'}
            ready = all(
                (items.get(i['localId'], {}).get('active_identification') or {}).get('status') == 'succeeded'
                and (items[i['localId']]['active_identification'].get('snapshot_id') in own_ids)
                for i in data['scope']
            )
        elif data['kind'] == 'collect':
            ready = all(
                (items.get(i['local_id'], {}).get('collection_projection') or {}).get('status') == 'succeeded'
                and (items[i['local_id']]['collection_projection'].get('operation_id') == operation_id)
                for i in data['scope']
            )
        elif data['kind'] in {'collection_update', 'collection_cancel'}:
            expected = 'cancelled' if data['kind'] == 'collection_cancel' else 'succeeded'
            ready = all(
                (items.get(i['local_id'], {}).get('collection_projection') or {}).get('status') == expected
                and items[i['local_id']]['collection_projection'].get('operation_id') == operation_id
                for i in data['scope']
            )
        else:
            kind = 'appraisal-draft' if data['kind'] == 'appraisal' else 'tracking-draft'
            record = self.store.get_entity(kind, data['scope']['localId'])
            ready = bool(record and record['data'].get('uri') and record['data'].get('status') == 'submitted')
        if not ready:
            raise WorkspaceError('recovery_incomplete', '尚有未归档的真实结果，不能清除待核验状态', 409)
        return self.update(operation_id, status='completed', message='宿主已核验并经受控工具归档本次全部结果')

    def _dispatch(self, operation_id, function, completion_message=None):
        def execute():
            self.update(operation_id, status='running', message='正在逐条执行，结果会自动保存')
            try:
                function(operation_id)
                data = self.store.get_entity('operation', operation_id)['data']
                unresolved = [item for item in data.get('itemResults', []) if item.get('status') == 'reconcile_required']
                failed = [item for item in data.get('itemResults', []) if item.get('status') == 'failed']
                if unresolved:
                    self.update(
                        operation_id,
                        status='reconcile_required',
                        message=f'{len(unresolved)} 条结果仍待核验；其他安全条目已继续，待核验项未重发',
                    )
                elif failed:
                    if data.get('kind') in {'collection_update', 'collection_cancel'}:
                        # 编辑 / 取消是单枚确认写入。服务端明确拒绝时没有待核验
                        # 结果，也不得沿用旧计划自动重发；结束此记录后用户可重新确认。
                        self.update(operation_id, status='failed', message=f"{len(failed)} 条收藏编辑明确失败；未成功的条目可重新生成计划并确认")
                    else:
                        self.update(operation_id, status='partial_failed', message=f"{len(failed)} 条明确失败，已跳过并完成其余条目；可重试失败项")
                else:
                    self.update(operation_id, status='completed', message=completion_message or '本次范围已执行并归档')
            except WorkspaceError as exc:
                if exc.code == 'identify_limit':
                    data = self.store.get_entity('operation', operation_id)['data']
                    unresolved = any(item.get('status') == 'reconcile_required' for item in data.get('itemResults', []))
                    # 额度拒绝没有产生识别结果。结束剩余范围，同时保留前面真正待核验的条目。
                    self.update(operation_id, status='reconcile_required' if unresolved else 'blocked',
                                message=str(exc), eligibility=exc.details['eligibility'])
                else:
                    self.update(operation_id, status='failed' if exc.code == 'cli_definite_failure' else 'reconcile_required',
                                message=str(exc))
            except Exception:
                # 包括成功响应之后、本地写入之前的崩溃窗口。保留 stdout 和计划，
                # 由只读核验确认后再归档；绝不能据此把请求作为确定失败重发。
                self.update(
                    operation_id,
                    status='reconcile_required',
                    message='执行或本地归档中断，请先核验；未重做请求。',
                )

        if self.background:
            thread = threading.Thread(target=execute, daemon=True)
            self.threads.append(thread)
            thread.start()
        else:
            execute()
        return self.store.get_entity('operation', operation_id)

    def _invoke(self, operation_id, argv, attempt=1):
        entry = self.store.get_entity('operation', operation_id)
        if entry['data']['account'] != self.account():
            raise WorkspaceError('account_changed', '账户或服务地址已变化，剩余执行已停止', 409)
        # 恢复时只复用逐调用保存的结果。已发出但无终态的同一 argv 绝不重放。
        previous = next((c for c in reversed(entry['data']['calls']) if c['argv'] == argv and c.get('attempt', 1) == attempt), None)
        if previous:
            saved = self.store.get_entity('operation-call', previous.get('id', ''))
            if not saved:
                raise WorkspaceError('unmatched_call', '这条请求已发出但终态未核验，不能再次提交', 409)
            raw = saved['data']['stdout'].encode('utf-8')
            parsed, value = result_value(raw, allow_recognition_no_match=argv[0] == 'identify')
            if parsed.get('accountSubject') != entry['data']['account']['subject']:
                raise WorkspaceError('account_changed', '已归档结果账户不符', 409)
            return raw, parsed, value
        call_id = 'call-' + secrets.token_hex(12)
        calls = entry['data']['calls'] + [{'id': call_id, 'argv': argv, 'attempt': attempt, 'startedAt': self.store.timestamp(), 'status': 'requested'}]
        self.update(operation_id, calls=calls)
        try:
            raw = self.runner(argv)
        except Exception:
            calls[-1]['observedAt'] = self.store.timestamp()
            self.update(operation_id, calls=calls)
            raise
        # 先进行敏感字段扫描，再保存精确 stdout；解析并不改变原始响应字节。
        parsed = json.loads(raw)
        safe_json(parsed)
        self.store.save_entity('operation-call', call_id, {'operationId': operation_id, 'argv': argv, 'stdout': raw.decode('utf-8')}, 0, 'system:executor')
        error = parsed.get('error') or {}
        calls[-1].update(
            status=parsed.get('status', 'unknown'),
            cliTaskId=parsed.get('id') or parsed.get('taskId'),
            finishedAt=self.store.timestamp(),
            # CLI 通用包装码下还可能包含 API 原始码；执行记录优先留具体来源码。
            failureCode=error.get('apiCode') or error.get('code') or error.get('businessCode'),
            reconciliationRequired=bool(error.get('reconciliationRequired')),
        )
        self.update(operation_id, calls=calls)
        _, value = result_value(raw, allow_recognition_no_match=bool(argv and argv[0] == 'identify'))
        if parsed.get('accountSubject') != entry['data']['account']['subject']:
            raise WorkspaceError('account_changed', '返回结果账户与确认账户不符，请核验', 409)
        return raw, parsed, value

    def _upload(self, operation_id, current, source_id, attempt=1):
        source = next(s for s in current['sources'] if s['source_id'] == source_id)
        # 复用证据边界检查；从校验过的路径构造 CLI argv，不允许网页指定文件系统路径。
        self.tasks.source(current['manifest']['task_key'], source_id)
        path = self.tasks.resolve(current['manifest']['task_key']) / source['stored_path']
        candidate = next((i['item_key'] for i in current['items'] if any(e['source_id'] == source_id for e in i['evidence'])), 'material')
        _, _, result = self._invoke(operation_id, ['file', 'upload', '--file', str(path), '--batch-id', current['manifest']['task_key'], '--candidate-id', candidate], attempt)
        url = result.get('fileUrl') if isinstance(result, dict) else None
        if not isinstance(url, str) or not (url.startswith('https://') or url.startswith('http://')):
            raise WorkspaceError('upload_unverified', '上传未返回有效 fileUrl，请核验', 409)
        return url

    def _record(self, operation_id, current, event, raw, collection=False):
        with tempfile.TemporaryDirectory(prefix='execution-', dir=str(self.store.directory)) as temporary:
            folder = Path(temporary)
            (folder / 'event.json').write_text(safe_json(event), encoding='utf-8')
            (folder / 'raw.json').write_bytes(raw)
            return self.tasks._call(
                current['manifest']['task_key'],
                current['manifest']['revision'],
                'system:executor',
                operations.record_collection if collection else operations.record_recognition,
                event_json=str(folder / 'event.json'),
                raw_json=str(folder / 'raw.json'),
            )

    def _item_result(self, operation_id, local_id, status, attempts, error=None):
        """按候选保存最终可见结果；调用级 stdout 仍单独不可变归档。"""
        operation = self.store.get_entity('operation', operation_id)
        results = [entry for entry in operation['data'].get('itemResults', []) if entry.get('localId') != local_id]
        results.append({'localId': local_id, 'status': status, 'attempts': attempts, 'error': error, 'updatedAt': self.store.timestamp()})
        return self.update(operation_id, itemResults=results)

    def _recovered_identification(self, operation, call, task):
        """只接受任务包已归档、且正反图片 URL 与原 CLI 请求完全一致的识别结果。

        CLI 的 reconciliationRequired 表示请求可能已写入远端。恢复时用原识别调用的
        candidateId 和图片 URL 对照已归档响应；两面都一致才把该条视为已完成，避免
        将同一枚硬币再次上传、识别，或把同批其他候选的结果误关联过来。
        """
        argv = call.get('argv') or []
        if not argv or argv[0] != 'identify':
            return None

        def option(name):
            try:
                return argv[argv.index(name) + 1]
            except (ValueError, IndexError):
                return None

        candidate_id = option('--candidate-id')
        batch_id = option('--batch-id')
        front_url = option('--front-img')
        back_url = option('--back-img')
        if batch_id != operation.get('taskKey') or not all((candidate_id, front_url, back_url)):
            return None

        current = next(
            (item for item in task.get('items', [])
             if item.get('item_key') == candidate_id
             and any(entry.get('localId') == item.get('local_id') for entry in operation.get('scope', []))),
            None,
        )
        if current is None:
            return None

        # snapshot() 先做完整性校验，再从 active_identification 的不可变 raw 响应派生
        # recognitionResult；因此这里只比较已校验的归档资料，不采信页面传入的识别字段。
        identification = current.get('active_identification') or {}
        result = current.get('recognitionResult') or {}
        images = result.get('images') if isinstance(result, dict) else None
        result_uri = (result.get('uri') or result.get('identifyUri')) if isinstance(result, dict) else None
        if (
            identification.get('status') != 'succeeded'
            or not identification.get('attempt_id')
            or not identification.get('raw_response_ref')
            or not identification.get('raw_response_sha256')
            or identification.get('identify_uri') != result_uri
            or images != [front_url, back_url]
        ):
            return None

        return {
            'localId': current['local_id'],
            'attemptId': identification['attempt_id'],
            'identifyUri': identification['identify_uri'],
            'snapshotId': identification.get('snapshot_id'),
        }

    def _run_item(self, operation_id, local_id, execute):
        """仅隔离服务已明确失败的单条；任何未知结果继续升级到批次核验。"""
        operation = self.store.get_entity('operation', operation_id)['data']
        previous = next((entry for entry in operation.get('itemResults', []) if entry.get('localId') == local_id), None)
        if previous and previous.get('status') in {'succeeded', 'recognition_failed'}:
            return True
        first_attempt = int(previous.get('attempts', 0)) + 1 if previous else 1
        for attempt in range(first_attempt, first_attempt + MAX_ITEM_ATTEMPTS):
            try:
                outcome = execute(attempt)
            except WorkspaceError as exc:
                if exc.code == 'cli_retryable_failure' and attempt < first_attempt + MAX_ITEM_ATTEMPTS - 1:
                    continue
                if exc.code in {'cli_retryable_failure', 'cli_definite_failure'}:
                    self._item_result(operation_id, local_id, 'failed', attempt, {'code': exc.code, 'message': str(exc)})
                    return False
                if exc.code == 'cli_not_completed':
                    operation = self.store.get_entity('operation', operation_id)['data']
                    call = next((value for value in reversed(operation.get('calls', []))
                                 if value.get('argv', [None])[0] in {'identify', 'collection'}), None)
                    error = {'code': exc.code, 'message': str(exc)}
                    if call and call.get('failureCode'):
                        error['remoteCode'] = call['failureCode']
                        error['reconciliationRequired'] = call.get('reconciliationRequired', False)
                    self._item_result(operation_id, local_id, 'reconcile_required', attempt, error)
                raise
            if isinstance(outcome, dict) and outcome.get('status') == 'recognition_failed':
                self._item_result(operation_id, local_id, 'recognition_failed', attempt, outcome.get('error'))
                return True
            self._item_result(operation_id, local_id, 'succeeded', attempt)
            return True
        raise AssertionError('单条重试循环必须在成功或明确失败时结束')

    def _identify_items(self, operation_id, only_local_ids=None):
        operation = self.store.get_entity('operation', operation_id)['data']
        previous_results = {entry.get('localId'): entry for entry in operation.get('itemResults', [])}
        for scoped in operation['scope']:
            local_id = scoped['localId']
            # 恢复操作只允许重放 itemResults 中明确失败的候选，绝不把未执行范围
            # 视为失败项。用户若要处理未执行项，应在识别台重新确认范围。
            if only_local_ids is not None and local_id not in only_local_ids:
                continue
            if previous_results.get(local_id, {}).get('status') == 'reconcile_required':
                # 结果未知的候选必须留待核验，不能因为恢复整批而重新上传或识别。
                continue

            def identify_one(attempt):
                current = self.tasks.snapshot(operation['taskKey'])
                item = next(i for i in current['items'] if i['local_id'] == local_id)
                active = item.get('active_identification') or {}
                own_ids = {c.get('cliTaskId') for c in self.store.get_entity('operation', operation_id)['data']['calls'] if c['argv'][0] == 'identify'}
                if active.get('status') == 'succeeded' and active.get('snapshot_id') in own_ids:
                    return
                review = item.get('review_projection') or {}
                if (
                    item['version'] != scoped['version']
                    or not operations.identification_eligible(item)
                    or (review.get('decision') in {'exclude', 'need_photo'} and not review.get('stale'))
                ):
                    raise WorkspaceError('stale_scope', '候选已变化，剩余识别已停止', 409)
                front = self._upload(operation_id, current, scoped['roles']['obverse'], attempt)
                back = self._upload(operation_id, current, scoped['roles']['reverse'], attempt)
                latest = self.tasks.snapshot(operation['taskKey'])
                if latest['manifest']['revision'] != current['manifest']['revision']:
                    raise WorkspaceError('revision_conflict', '资料在上传期间变化，尚未执行这枚识别', 409)
                argv = ['identify', '--front-img', front, '--back-img', back, '--batch-id', operation['taskKey'], '--candidate-id', item['item_key']]
                started = operations.now_iso()
                raw, envelope, _ = self._invoke(operation_id, argv, attempt)
                if is_recognition_no_match(envelope):
                    error = envelope.get('error') or {}
                    recognition_error = {
                        'code': RECOGNITION_NO_MATCH_CODE,
                        'businessCode': RECOGNITION_NO_MATCH_BUSINESS_CODE,
                        'httpStatus': 200,
                        'message': error.get('message') or '服务已处理请求，但未能识别出硬币版本',
                    }
                    # 保留 HTTP 200 的业务识别结果和原始响应；此状态表示已完成识别，
                    # 后续重试汇总不会把它当成执行失败，也不会自动再次消耗识别额度。
                    event = {
                        'schema_version': 'heribase.recognition-attempt.v1',
                        'attempt_id': 'recognition-' + secrets.token_hex(12),
                        'task_key': operation['taskKey'],
                        'local_id': item['local_id'],
                        'attempt_number': attempt,
                        'operation_type': 'identify',
                        'status': 'failed_terminal',
                        'input': {
                            'item_version': item['version'],
                            'evidence': [
                                {'evidence_id': e['evidence_id'], 'sha256': next(s['sha256'] for s in current['sources'] if s['source_id'] == e['source_id'])}
                                for e in item['evidence']
                            ],
                        },
                        'cli': {'command': 'heribase identify', 'args': argv[1:] + ['--json']},
                        'remote_task_id': envelope.get('id'),
                        'started_at': started,
                        'finished_at': operations.now_iso(),
                        'exit_code': 0,
                        'classification': RECOGNITION_NO_MATCH_CODE,
                        'raw_response_ref': None,
                        'raw_response_sha256': None,
                        'error': recognition_error,
                    }
                    self._record(operation_id, current, event, raw)
                    return {'status': 'recognition_failed', 'error': recognition_error}
                evidence = [
                    {'evidence_id': e['evidence_id'], 'sha256': next(s['sha256'] for s in current['sources'] if s['source_id'] == e['source_id'])} for e in item['evidence']
                ]
                event = {
                    'schema_version': 'heribase.recognition-attempt.v1',
                    'attempt_id': 'recognition-' + secrets.token_hex(12),
                    'task_key': operation['taskKey'],
                    'local_id': item['local_id'],
                    'attempt_number': attempt,
                    'operation_type': 'identify',
                    'status': 'succeeded',
                    'input': {'item_version': item['version'], 'evidence': evidence},
                    'cli': {'command': 'heribase identify', 'args': argv[1:] + ['--json']},
                    'remote_task_id': envelope.get('id'),
                    'started_at': started,
                    'finished_at': operations.now_iso(),
                    'exit_code': 0,
                    'classification': 'success',
                    'raw_response_ref': None,
                    'raw_response_sha256': None,
                    'error': None,
                }
                self._record(operation_id, current, event, raw)

            try:
                self._run_item(operation_id, local_id, identify_one)
            except WorkspaceError as exc:
                if exc.code == 'cli_not_completed':
                    # 单枚识别结果未知时由 _run_item 留下待核验状态；该枚不重发，
                    # 但同一已确认范围内其他相互独立的候选仍可继续执行。
                    continue
                raise

    def _collect_items(self, operation_id, only_local_ids=None):
        operation = self.store.get_entity('operation', operation_id)['data']
        for scoped in operation['scope']:
            local_id = scoped['local_id']
            if only_local_ids is not None and local_id not in only_local_ids:
                continue

            def collect_one(attempt):
                current = self.tasks.snapshot(operation['taskKey'])
                plan = current['plan']
                item = next(i for i in current['items'] if i['local_id'] == local_id)
                if (item.get('collection_projection') or {}).get('operation_id') == operation_id and (item.get('collection_projection') or {}).get('status') == 'succeeded':
                    return
                check = operations.preflight_plan(argparse.Namespace(root=str(self.tasks.root), task_key=operation['taskKey']))
                if check['errors'] or check['warnings'] or plan.get('status') not in {'authorized', 'executing'} or plan['plan_id'] != operation['request']['planId']:
                    raise WorkspaceError('stale_plan', '收藏计划已过期或未通过完整性检查', 409)
                if (item.get('collection_projection') or {}).get('collection_uri'):
                    return
                argv = ['collection', 'add', '--uri', scoped['identify_uri'], '--batch-id', operation['taskKey'], '--candidate-id', item['item_key']]
                started = operations.now_iso()
                raw, _, _ = self._invoke(operation_id, argv, attempt)
                event = {
                    'schema_version': 'heribase.collection-operation.v1',
                    'operation_id': operation_id,
                    'attempt_id': 'collection-' + secrets.token_hex(12),
                    'plan_id': plan['plan_id'],
                    'task_key': operation['taskKey'],
                    'local_id': item['local_id'],
                    'attempt_number': attempt,
                    'operation_type': 'collection_add',
                    'status': 'succeeded',
                    'expected': {'item_version': item['version'], 'identify_uri': scoped['identify_uri'], 'user_uniq_uri': scoped['user_uniq_uri']},
                    'cli': {'command': 'heribase collection add', 'args': argv[2:] + ['--json']},
                    'started_at': started,
                    'finished_at': operations.now_iso(),
                    'exit_code': 0,
                    'classification': 'success',
                    'raw_response_ref': None,
                    'raw_response_sha256': None,
                    'result': None,
                    'error': None,
                }
                recorded = self._record(operation_id, current, event, raw, collection=True)
                if recorded['status'] != 'succeeded':
                    raise WorkspaceError('unverified_collection', '收藏结果缺少可验证关联，请先核验', 409)

            self._run_item(operation_id, local_id, collect_one)

    def _mutate_collection_items(self, operation_id, only_local_ids=None):
        """按已授权计划执行 collection update/cancel，并把每次结果归档到同一任务包。"""
        operation = self.store.get_entity('operation', operation_id)['data']
        for scoped in operation['scope']:
            local_id = scoped['local_id']
            if only_local_ids is not None and local_id not in only_local_ids:
                continue

            def mutate_one(attempt):
                current = self.tasks.snapshot(operation['taskKey'])
                plan = current.get('plan') or {}
                item = next(value for value in current['items'] if value['local_id'] == local_id)
                action = scoped['operation_type']
                expected_status = 'cancelled' if action == 'collection_cancel' else 'succeeded'
                projection = item.get('collection_projection') or {}
                if projection.get('operation_id') == operation_id and projection.get('status') == expected_status:
                    return
                check = operations.preflight_plan(argparse.Namespace(root=str(self.tasks.root), task_key=operation['taskKey']))
                if check['errors'] or check['warnings'] or plan.get('status') not in {'authorized', 'executing'} or plan.get('plan_id') != operation['request']['planId']:
                    raise WorkspaceError('stale_plan', '收藏编辑计划已过期或未通过完整性检查', 409)
                if projection.get('collection_uri') != scoped.get('collection_uri') or projection.get('status') != 'succeeded':
                    raise WorkspaceError('stale_scope', '收藏关联已变化，请重新读取远程资料后再操作', 409)
                if action == 'collection_update':
                    argv = ['collection', 'update', '--collection-uri', scoped['collection_uri']]
                    for key, flag in COLLECTION_UPDATE_FLAGS.items():
                        if key in scoped.get('changes', {}):
                            argv.extend([flag, str(scoped['changes'][key])])
                    # 上传只发生在计划确认之后；source_id 来自任务包证据，浏览器不能传路径或 URL。
                    for source_id in scoped.get('changes', {}).get(COLLECTION_IMAGE_SOURCE_IDS, []):
                        argv.extend(['--collect-img', self._upload(operation_id, current, source_id, attempt)])
                else:
                    argv = ['collection', 'cancel', '--collection-uri', scoped['collection_uri']]
                argv.extend(['--batch-id', operation['taskKey'], '--candidate-id', item['item_key']])
                started = operations.now_iso()
                raw, _, _ = self._invoke(operation_id, argv, attempt)
                event = {
                    'schema_version': 'heribase.collection-operation.v1',
                    'operation_id': operation_id,
                    'attempt_id': 'collection-' + secrets.token_hex(12),
                    'plan_id': plan['plan_id'],
                    'task_key': operation['taskKey'],
                    'local_id': item['local_id'],
                    'attempt_number': attempt,
                    'operation_type': action,
                    'status': 'succeeded',
                    'expected': {'item_version': item['version'], 'identify_uri': scoped['identify_uri'], 'user_uniq_uri': scoped['user_uniq_uri']},
                    'cli': {'command': 'heribase ' + ' '.join(argv[:2]), 'args': argv[2:] + ['--json']},
                    'started_at': started,
                    'finished_at': operations.now_iso(),
                    'exit_code': 0,
                    'classification': 'success',
                    'raw_response_ref': None,
                    'raw_response_sha256': None,
                    'result': None,
                    'error': None,
                }
                recorded = self._record(operation_id, current, event, raw, collection=True)
                # record_collection 的 event 状态仍是“CLI 调用成功”；取消的业务投影
                # 才会转换为 cancelled，因此必须核对返回的 collection_projection。
                if (recorded.get('collection_projection') or {}).get('status') != expected_status:
                    raise WorkspaceError('unverified_collection', '收藏编辑结果缺少可验证关联，请先核验', 409)

            self._run_item(operation_id, local_id, mutate_one)
