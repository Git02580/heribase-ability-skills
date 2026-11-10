"""真实任务事务 + 替代远端 CLI；测试绝不读取实际账户或上传图片。"""
import json
import sys
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_tasks
from workspace_executor import WorkspaceExecutor
from workspace_store import WorkspaceError


class FakeCLI:
    def __init__(self):
        self.calls = []
        self.unknown = False
        self.account = 'fixture-account'
        self.responses = {}
        self.last_id = None
        self.identify_count = 0
        # 以 candidate-id 为键模拟服务已明确返回、可安全重试的失败。
        self.retryable_failures = {}
        # CLI may report an ambiguous downstream failure after the remote
        # identification was created and later archived by the host.
        self.reconciliation_failures = set()
        self.api_error = None
        # 收藏编辑 / 取消是远端写入；服务明确拒绝时不能由工作台自动重放。
        self.definite_failures = set()

    def __call__(self, argv):
        self.calls.append(argv)
        if argv == ['status']:
            return json.dumps({'authenticated': True, 'accountSubject': self.account, 'api_base_url': 'https://example.invalid'}).encode()
        if argv[:2] == ['task', 'get']:
            return self.responses[argv[2]]
        if argv[:2] == ['task', 'list']:
            return json.dumps([json.loads(v) for v in self.responses.values()]).encode()
        if argv[:2] == ['file', 'upload']:
            result = {'fileUrl': 'https://example.invalid/upload/' + str(len(self.calls))}
        elif argv[:2] == ['identify', 'eligibility']:
            result = {'allowed': True}
        elif argv[:2] == ['collection', 'capacity']:
            result = {'allowed': True}
        elif argv[0] == 'identify':
            self.identify_count += 1
            result = {'uri': 'fixture-identify-' + str(self.identify_count), 'title': '真实返回标题',
                      'userUniqUri': 'fixture-user-' + str(self.identify_count)}
        elif argv[:2] == ['collection', 'add']:
            suffix = argv[3].removeprefix('fixture-identify-')
            result = {'collectionUri': 'fixture-collection', 'userUniqUri': 'fixture-user-' + suffix}
        elif argv[:2] == ['collection', 'edit-detail']:
            result = {'title': 'Fixture coin', 'years': '1919', 'notes': 'before edit'}
        elif argv[:2] == ['collection', 'update']:
            result = {'collectionUri': argv[3], 'userUniqUri': 'fixture-user-1'}
        elif argv[:2] == ['collection', 'cancel']:
            result = {'collectionUri': argv[3]}
        else:
            raise AssertionError(argv)
        self.last_id = 'fixture-task-' + str(len(self.calls))
        if argv in [['identify', 'eligibility'], ['collection', 'capacity']]:
            operation, request, context = '.'.join(argv), {}, {}
        else:
            operation, request, context = WorkspaceExecutor.expected_request(argv)
        retryable = '--candidate-id' in argv and (argv[0] == 'identify' or argv[:2] == ['collection', 'add']) and self.retryable_failures.get(argv[argv.index('--candidate-id') + 1], 0) > 0
        if retryable:
            candidate = argv[argv.index('--candidate-id') + 1]
            self.retryable_failures[candidate] -= 1
        definite = '.'.join(argv[:2]) in self.definite_failures
        candidate = argv[argv.index('--candidate-id') + 1] if '--candidate-id' in argv else None
        ambiguous = operation == 'identify' and candidate in self.reconciliation_failures
        api_error = self.api_error if operation == 'identify' else None
        raw = json.dumps({'id': self.last_id, 'createdAt': datetime.now(timezone.utc).isoformat(), 'operation': operation, 'request': {'input': request, 'apiBaseUrl': 'https://example.invalid'}, 'context': context, 'accountSubject': self.account,
                          'status': 'failed' if retryable or definite or ambiguous or api_error else 'completed', 'result': result,
                          'error': api_error if api_error else {'code': 'DOWNSTREAM_UNAVAILABLE', 'reconciliationRequired': True} if ambiguous else {'code': 'DOWNSTREAM_UNAVAILABLE'} if retryable else {'code': 'INVALID_ARGUMENT'} if definite else None}).encode()
        self.responses[self.last_id] = raw
        if self.unknown and operation == 'identify':
            raise WorkspaceError('cli_timeout', '终态未知', 409)
        return raw


class ExecutorTests(unittest.TestCase):
    tearDown = test_tasks.TaskBridgeTests.tearDown
    ingest = test_tasks.TaskBridgeTests.ingest
    make_pair = test_tasks.TaskBridgeTests.make_pair
    def setUp(self):
        test_tasks.TaskBridgeTests.setUp(self)
        item = self.make_pair()
        current = self.tasks.snapshot(self.key)
        self.tasks.pair(self.key, current['manifest']['revision'], item['local_id'], 'confirm_pair',
                        [{'sourceId': s['source_id'], 'role': role} for s, role in zip(current['sources'], ['obverse', 'reverse'])], 'user:web')
        self.cli = FakeCLI()
        self.executor = WorkspaceExecutor(self.store, self.tasks, self.cli, background=False)

    def add_second_quota_candidate(self):
        front = self.ingest('quota-front.png', b'quota-front-image')
        back = self.ingest('quota-back.png', b'quota-back-image')
        current = self.tasks.snapshot(self.key)
        pair = [{'sourceId': front['source']['source_id'], 'role': 'obverse'},
                {'sourceId': back['source']['source_id'], 'role': 'reverse'}]
        current = self.tasks.create_candidate(self.key, current['manifest']['revision'], [side['sourceId'] for side in pair],
                                              '另一枚钱币', 'user:web')
        self.tasks.pair(self.key, current['manifest']['revision'], current['items'][-1]['local_id'], 'confirm_pair', pair, 'user:web')

    def test_known_quota_blocks_upload_before_confirmation(self):
        self.add_second_quota_candidate()
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.executor.query = lambda argv: {'allowed': True, 'dailyLimit': 3, 'usedTimes': 2, 'remainingTimes': 1}
        with self.assertRaises(WorkspaceError) as caught:
            self.executor.identify(dict(taskKey=self.key, expectedRevision=plan['revision'], planHash=plan['hash'],
                                        localIds=[i['localId'] for i in plan['items']], commandId='over-quota'), 'user:web')
        self.assertEqual(caught.exception.code, 'identify_quota_insufficient')
        self.assertFalse(any(call[:2] == ['file', 'upload'] for call in self.cli.calls))

    def test_remote_quota_rejection_blocks_batch_without_reconciliation_or_retry(self):
        self.add_second_quota_candidate()
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        quota = {'reason': 'identify_limit', 'allowed': False, 'dailyLimit': 3, 'usedTimes': 3, 'remainingTimes': 0}
        self.cli.api_error = {'code': 'API_ERROR', 'businessCode': 409, 'message': 'identify_limit', 'data': quota}
        op = self.executor.identify(dict(taskKey=self.key, expectedRevision=plan['revision'], planHash=plan['hash'],
                                         localIds=[i['localId'] for i in plan['items']], commandId='remote-quota'), 'user:web')
        self.assertEqual(op['data']['status'], 'blocked')
        self.assertEqual(op['data']['eligibility'], quota)
        self.assertEqual(self.cli.identify_count, 1)
        self.assertEqual(sum(call[:2] == ['file', 'upload'] for call in self.cli.calls), 2)

    def test_confirm_identify_review_collect_and_reopen(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        request = dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[i['localId'] for i in plan['items']], commandId='identify-1')
        op = self.executor.identify(request, 'user:web')
        self.assertEqual(op['data']['status'], 'completed')
        count = len(self.cli.calls)
        self.assertEqual(self.executor.identify(request, 'user:web')['id'], op['id'])
        self.assertEqual(count, len(self.cli.calls))
        current = self.tasks.snapshot(self.key)
        self.assertTrue(current['health']['ok'])
        item = current['items'][0]
        current = self.tasks.review(self.key, current['manifest']['revision'], item['local_id'], 'collect', 'user:web')
        plan = self.executor.collection_plan(self.key, current['manifest']['revision'], [item['local_id']], 'user:web')
        request = dict(taskKey=self.key, expectedRevision=plan['revision'], planId=plan['plan_id'], planHash=plan['payload_sha256'], commandId='collect-1')
        result = self.executor.collect(request, 'user:web')
        self.assertEqual(result['data']['status'], 'completed')
        current = self.tasks.snapshot(self.key)
        self.assertTrue(current['health']['ok'])
        self.assertEqual(current['items'][0]['collection_projection']['collection_uri'], 'fixture-collection')
        with self.assertRaises(WorkspaceError):
            self.executor.collection_plan(self.key, current['manifest']['revision'], [item['local_id']], 'user:web')

    def test_failed_readonly_cli_query_is_saved_as_a_separate_log(self):
        """只读查询被 CLI 拒绝时，应保留命令、原始返回和可见错误供排障。"""

        raw = json.dumps({
            'id': 'query-task-1',
            'accountSubject': 'fixture-account',
            'status': 'failed',
            'error': {'code': 'DOWNSTREAM_UNAVAILABLE', 'message': 'temporary outage'},
        }).encode()
        self.executor.runner = lambda argv: raw

        with self.assertRaisesRegex(WorkspaceError, '可重试错误'):
            self.executor.query(['appraisals', 'products'])

        logs = self.store.list_entities('cli-query-log')
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['data']['argv'], ['appraisals', 'products'])
        self.assertEqual(logs[0]['data']['cliTaskId'], 'query-task-1')
        self.assertEqual(logs[0]['data']['status'], 'failed')
        self.assertEqual(logs[0]['data']['stdout'], raw.decode())
        self.assertEqual(logs[0]['data']['error']['code'], 'cli_retryable_failure')

    def test_identification_history_preserves_the_api_error_code(self):
        current = self.tasks.snapshot(self.key)
        local_id = current['items'][0]['local_id']
        self.cli.api_error = {
            'code': 'API_ERROR', 'apiCode': 'IDENTIFY_BACKEND_BUSY', 'source': 'api',
            'message': '识别服务暂不可用', 'httpStatus': 503, 'reconciliationRequired': True,
        }
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])

        operation = self.executor.identify(
            dict(taskKey=self.key, expectedRevision=plan['revision'], planHash=plan['hash'],
                 localIds=[local_id], commandId='api-error-code-visible'), 'user:web'
        )

        self.assertEqual(operation['data']['status'], 'reconcile_required')
        self.assertEqual(operation['data']['itemResults'][0]['error']['remoteCode'], 'IDENTIFY_BACKEND_BUSY')

    def test_collection_update_and_cancel_are_planned_and_archived(self):
        """编辑与取消必须先读取基线、授权计划，再写入任务包历史。"""
        current = self.tasks.snapshot(self.key)
        identify = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.executor.identify(
            dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=identify['hash'],
                 localIds=[entry['localId'] for entry in identify['items']], commandId='identify-for-edit'), 'user:web'
        )
        current = self.tasks.snapshot(self.key)
        item = current['items'][0]
        current = self.tasks.review(self.key, current['manifest']['revision'], item['local_id'], 'collect', 'user:web')
        add = self.executor.collection_plan(self.key, current['manifest']['revision'], [item['local_id']], 'user:web')
        self.executor.collect(
            dict(taskKey=self.key, expectedRevision=add['revision'], planId=add['plan_id'], planHash=add['payload_sha256'], commandId='collect-for-edit'), 'user:web'
        )
        current = self.tasks.snapshot(self.key)
        image_source_ids = [entry['source_id'] for entry in current['items'][0]['evidence']]
        update = self.executor.collection_mutation_plan(
            self.key, current['manifest']['revision'], item['local_id'], 'update', {
                'notes': 'after edit',
                'title': 'Updated title',
                # 浏览器只提交当前任务证据的 ID；执行器在最终确认后自行上传。
                'collectImageSourceIds': image_source_ids,
            }, 'user:web'
        )
        self.assertEqual(update['items'][0]['changes']['notes'], 'after edit')
        changed = self.executor.collection_mutation(
            dict(taskKey=self.key, expectedRevision=update['revision'], planId=update['plan_id'],
                 planHash=update['payload_sha256'], commandId='update-collection', action='update'), 'user:web'
        )
        self.assertEqual(changed['data']['status'], 'completed')
        current = self.tasks.snapshot(self.key)
        self.assertEqual(current['items'][0]['collection_projection']['status'], 'succeeded')
        self.assertEqual(current['items'][0]['collection_projection']['applied_changes']['title'], 'Updated title')
        update_call = next(call for call in self.cli.calls if call[:2] == ['collection', 'update'])
        self.assertEqual(update_call.count('--collect-img'), 2)
        cancel = self.executor.collection_mutation_plan(
            self.key, current['manifest']['revision'], item['local_id'], 'cancel', {}, 'user:web'
        )
        cancelled = self.executor.collection_mutation(
            dict(taskKey=self.key, expectedRevision=cancel['revision'], planId=cancel['plan_id'],
                 planHash=cancel['payload_sha256'], commandId='cancel-collection', action='cancel'), 'user:web'
        )
        self.assertEqual(cancelled['data']['status'], 'completed')
        self.assertEqual(self.tasks.snapshot(self.key)['items'][0]['collection_projection']['status'], 'cancelled')

    def test_definite_collection_edit_failure_does_not_block_a_new_confirmation(self):
        """编辑被服务端明确拒绝后，应结束旧操作而非伪装为可重试的批处理失败。"""
        current = self.tasks.snapshot(self.key)
        identify = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.executor.identify(
            dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=identify['hash'],
                 localIds=[entry['localId'] for entry in identify['items']], commandId='identify-for-failed-edit'), 'user:web'
        )
        current = self.tasks.snapshot(self.key)
        item = current['items'][0]
        current = self.tasks.review(self.key, current['manifest']['revision'], item['local_id'], 'collect', 'user:web')
        add = self.executor.collection_plan(self.key, current['manifest']['revision'], [item['local_id']], 'user:web')
        self.executor.collect(
            dict(taskKey=self.key, expectedRevision=add['revision'], planId=add['plan_id'], planHash=add['payload_sha256'], commandId='collect-for-failed-edit'), 'user:web'
        )
        current = self.tasks.snapshot(self.key)
        plan = self.executor.collection_mutation_plan(
            self.key, current['manifest']['revision'], item['local_id'], 'update', {'years': '1909'}, 'user:web'
        )
        self.cli.definite_failures.add('collection.update')
        failed = self.executor.collection_mutation(
            dict(taskKey=self.key, expectedRevision=plan['revision'], planId=plan['plan_id'],
                 planHash=plan['payload_sha256'], commandId='failed-collection-edit', action='update'), 'user:web'
        )
        self.assertEqual(failed['data']['status'], 'failed')

        # 模拟旧版本留下的 partial_failed：启动恢复时仅依据已归档的明确失败回执关闭它。
        self.executor.update(failed['id'], status='partial_failed')
        recovered = WorkspaceExecutor(self.store, self.tasks, self.cli, background=False)
        self.assertEqual(recovered.store.get_entity('operation', failed['id'])['data']['status'], 'failed')
        self.cli.definite_failures.clear()
        current = self.tasks.snapshot(self.key)
        retry_plan = recovered.collection_mutation_plan(
            self.key, current['manifest']['revision'], item['local_id'], 'update', {'years': '1909'}, 'user:web'
        )
        self.assertEqual(retry_plan['items'][0]['changes']['years'], '1909')

    def test_collection_continues_after_recording_the_first_item(self):
        """计划已进入 executing 后，后续已授权条目仍应按原范围执行。"""
        first = self.tasks.snapshot(self.key)['items'][0]
        front = self.ingest('second-front.png', b'second-front-image')
        back = self.ingest('second-back.png', b'second-back-image')
        current = self.tasks.snapshot(self.key)
        created = self.tasks.create_candidate(
            self.key, current['manifest']['revision'], [front['source']['source_id'], back['source']['source_id']], '第二枚钱币', 'user:web'
        )
        second = created['items'][-1]
        current = self.tasks.snapshot(self.key)
        self.tasks.pair(
            self.key, current['manifest']['revision'], second['local_id'], 'confirm_pair',
            [{'sourceId': front['source']['source_id'], 'role': 'obverse'}, {'sourceId': back['source']['source_id'], 'role': 'reverse'}], 'user:web'
        )
        current = self.tasks.snapshot(self.key)
        identification = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.executor.identify(
            dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=identification['hash'],
                 localIds=[entry['localId'] for entry in identification['items']], commandId='identify-two-items'), 'user:web'
        )
        current = self.tasks.snapshot(self.key)
        for item in current['items']:
            current = self.tasks.review(self.key, current['manifest']['revision'], item['local_id'], 'collect', 'user:web')
        collection = self.executor.collection_plan(
            self.key, current['manifest']['revision'], [first['local_id'], second['local_id']], 'user:web'
        )
        result = self.executor.collect(
            dict(taskKey=self.key, expectedRevision=collection['revision'], planId=collection['plan_id'],
                 planHash=collection['payload_sha256'], commandId='collect-two-items'), 'user:web'
        )
        self.assertEqual(result['data']['status'], 'completed')
        projections = [item['collection_projection'] for item in self.tasks.snapshot(self.key)['items']]
        self.assertEqual([projection['status'] for projection in projections], ['succeeded', 'succeeded'])

    def test_retryable_item_failure_is_retried_then_skipped_without_blocking_later_items(self):
        first = self.tasks.snapshot(self.key)['items'][0]
        front = self.ingest('second-front.png', b'second-front-image')
        back = self.ingest('second-back.png', b'second-back-image')
        current = self.tasks.snapshot(self.key)
        second = self.tasks.create_candidate(self.key, current['manifest']['revision'], [front['source']['source_id'], back['source']['source_id']], '第二枚钱币', 'user:web')['items'][-1]
        current = self.tasks.snapshot(self.key)
        self.tasks.pair(self.key, current['manifest']['revision'], second['local_id'], 'confirm_pair',
                        [{'sourceId': front['source']['source_id'], 'role': 'obverse'}, {'sourceId': back['source']['source_id'], 'role': 'reverse'}], 'user:web')
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.retryable_failures[second['item_key']] = 3
        result = self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'],
                                             localIds=[entry['localId'] for entry in plan['items']], commandId='retry-items'), 'user:web')
        self.assertEqual(result['data']['status'], 'partial_failed')
        self.assertTrue(result['data']['label'].startswith('上传与识别 · '))
        outcomes = {value['localId']: value for value in result['data']['itemResults']}
        self.assertEqual(outcomes[first['local_id']]['status'], 'succeeded')
        self.assertEqual(outcomes[second['local_id']]['status'], 'failed')
        self.assertEqual(outcomes[second['local_id']]['attempts'], 3)
        # 第一枚成功一次，第二枚明确失败后发送三次识别请求；失败响应已被归档，
        # 重试次数不能只停留在操作摘要中。
        self.assertEqual(len([call for call in self.cli.calls if call[:1] == ['identify'] and '--front-img' in call]), 4, self.cli.calls)

    def test_retry_failed_items_uses_original_scope_after_a_partial_completion(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        item = current['items'][0]
        self.cli.retryable_failures[item['item_key']] = 3
        failed = self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'],
                                              localIds=[item['local_id']], commandId='retry-later'), 'user:web')
        self.assertEqual(failed['data']['status'], 'partial_failed')
        resumed = self.executor.resume('retry-later')
        self.assertEqual(resumed['data']['status'], 'completed')
        self.assertEqual(self.tasks.snapshot(self.key)['items'][0]['active_identification']['status'], 'succeeded')

    def test_upload_accepts_https_and_rejects_non_http_file_urls(self):
        current = self.tasks.snapshot(self.key)
        source_id = current['items'][0]['evidence'][0]['source_id']
        self.executor._invoke = lambda *_args, **_kwargs: (b'{}', {}, {'fileUrl': 'https://example.invalid/uploaded.jpg'})

        self.assertEqual(
            self.executor._upload('upload-url-check', current, source_id),
            'https://example.invalid/uploaded.jpg',
        )

        self.executor._invoke = lambda *_args, **_kwargs: (b'{}', {}, {'fileUrl': 'file:///tmp/uploaded.jpg'})
        with self.assertRaises(WorkspaceError) as error:
            self.executor._upload('upload-url-check', current, source_id)
        self.assertEqual(error.exception.code, 'upload_unverified')

    def test_retry_failed_items_never_starts_unattempted_scope_members(self):
        """中断前尚未执行的候选不属于“重试失败项”的范围。"""

        first = self.tasks.snapshot(self.key)['items'][0]
        front = self.ingest('second-front.png', b'second-front-image')
        back = self.ingest('second-back.png', b'second-back-image')
        current = self.tasks.snapshot(self.key)
        second = self.tasks.create_candidate(
            self.key, current['manifest']['revision'], [front['source']['source_id'], back['source']['source_id']], '第二枚钱币', 'user:web'
        )['items'][-1]
        current = self.tasks.snapshot(self.key)
        self.tasks.pair(self.key, current['manifest']['revision'], second['local_id'], 'confirm_pair',
                        [{'sourceId': front['source']['source_id'], 'role': 'obverse'}, {'sourceId': back['source']['source_id'], 'role': 'reverse'}], 'user:web')
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'], [first['local_id']])
        full_plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.retryable_failures[first['item_key']] = 3
        failed = self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'],
                                              localIds=[first['local_id']], commandId='retry-only-failed'), 'user:web')
        # 模拟首枚失败后任务包变化导致批次中断：原授权范围含第二枚，但第二枚从未实际执行。
        self.executor.update(failed['id'], status='partial_failed', scope=full_plan['items'])

        resumed = self.executor.resume(failed['id'])

        self.assertEqual(resumed['data']['status'], 'completed')
        self.assertEqual(self.tasks.snapshot(self.key)['items'][0]['active_identification']['status'], 'succeeded')
        self.assertIsNone(self.tasks.snapshot(self.key)['items'][1]['active_identification'])
        second_identifies = [
            call for call in self.cli.calls
            if call[:1] == ['identify'] and '--candidate-id' in call
            and call[call.index('--candidate-id') + 1] == second['item_key']
        ]
        self.assertEqual(second_identifies, [])

    def test_reconcile_record_with_only_explicit_retryable_failures_can_retry_failed_items(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        item = current['items'][0]
        self.cli.retryable_failures[item['item_key']] = 3
        failed = self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'],
                                              localIds=[item['local_id']], commandId='reconcile-retry'), 'user:web')
        self.executor.update(failed['id'], status='reconcile_required', message='任务检查在收尾时中断')
        resumed = self.executor.resume(failed['id'])
        self.assertEqual(resumed['data']['status'], 'completed')
        self.assertEqual(self.tasks.snapshot(self.key)['items'][0]['active_identification']['status'], 'succeeded')

    def test_changed_pairing_invalidates_preview_before_any_upload(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        item = current['items'][0]
        self.tasks.review(self.key, current['manifest']['revision'], item['local_id'], 'exclude', 'user:web')
        count = len(self.cli.calls)
        with self.assertRaises(WorkspaceError):
            self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[item['local_id']], commandId='stale'), 'user:web')
        self.assertEqual(len(self.cli.calls), count)

    def test_unknown_write_not_replayed_by_restart_or_new_command_id(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.unknown = True
        request = dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[i['localId'] for i in plan['items']], commandId='uncertain')
        result = self.executor.identify(request, 'user:web')
        self.assertEqual(result['data']['status'], 'reconcile_required')
        count = len(self.cli.calls)
        second = WorkspaceExecutor(self.store, self.tasks, self.cli, background=False)
        request['commandId'] = 'another-click'
        with self.assertRaises(WorkspaceError):
            second.identify(request, 'user:web')
        self.assertEqual(len(self.cli.calls), count)

    def test_account_switch_invalidates_confirmed_scope(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.account = 'different-account'
        with self.assertRaises(WorkspaceError):
            self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[i['localId'] for i in plan['items']], commandId='switched'), 'user:web')
        self.assertFalse(any(a[:2] == ['file', 'upload'] for a in self.cli.calls))

    def test_account_switch_during_eligibility_cannot_rebind_reservation(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        original = self.executor.runner
        def switch(argv):
            raw = original(argv)
            if argv == ['identify', 'eligibility']:
                self.cli.account = 'switched-after-preview'
            return raw
        self.executor.runner = switch
        with self.assertRaises(WorkspaceError):
            self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[i['localId'] for i in plan['items']], commandId='mid-switch'), 'user:web')
        self.assertFalse(any(a[:2] == ['file', 'upload'] for a in self.cli.calls))

    def test_reconcile_lost_identification_response_without_reissuing_write(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.unknown = True
        result = self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[i['localId'] for i in plan['items']], commandId='recover-write'), 'user:web')
        unknown_call = result['data']['calls'][-1]
        task_id = self.cli.last_id
        inspection = self.executor.inspect(result['id'])
        self.assertTrue(any('unmatchedLocalTasks' in r for r in inspection['data']['inspection']['results']))
        writes_before_resume = len([a for a in self.cli.calls if a[0] == 'identify' and '--front-img' in a])
        still_pending = self.executor.resume(result['id'])
        self.assertEqual(still_pending['data']['status'], 'reconcile_required')
        self.assertEqual(writes_before_resume, len([a for a in self.cli.calls if a[0] == 'identify' and '--front-img' in a]))
        self.executor.reconcile(result['id'], [{'callId': unknown_call['id'], 'taskId': task_id}])
        writes_before = len([a for a in self.cli.calls if a[0] == 'identify' and '--front-img' in a])
        restored = self.executor.resume(result['id'])
        self.assertEqual(restored['data']['status'], 'completed')
        self.assertEqual(writes_before, len([a for a in self.cli.calls if a[0] == 'identify' and '--front-img' in a]))
        self.assertEqual(self.tasks.snapshot(self.key)['items'][0]['active_identification']['status'], 'succeeded')

    def test_resume_reconciles_archived_identification_then_continues_unsubmitted_scope(self):
        """已归档的模糊识别不重发；恢复后继续原授权范围中尚未发出的候选。"""
        first = self.tasks.snapshot(self.key)['items'][0]
        front = self.ingest('second-front.png', b'second-front-image')
        back = self.ingest('second-back.png', b'second-back-image')
        current = self.tasks.snapshot(self.key)
        second = self.tasks.create_candidate(
            self.key, current['manifest']['revision'], [front['source']['source_id'], back['source']['source_id']], '第二枚钱币', 'user:web'
        )['items'][-1]
        current = self.tasks.snapshot(self.key)
        self.tasks.pair(
            self.key, current['manifest']['revision'], second['local_id'], 'confirm_pair',
            [{'sourceId': front['source']['source_id'], 'role': 'obverse'}, {'sourceId': back['source']['source_id'], 'role': 'reverse'}], 'user:web'
        )
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.reconciliation_failures.add(first['item_key'])
        operation = self.executor.identify(
            dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'],
                 localIds=[entry['localId'] for entry in plan['items']], commandId='ambiguous-first-identification'), 'user:web'
        )
        self.assertEqual(operation['data']['status'], 'reconcile_required')
        first_identify = next(call for call in operation['data']['calls'] if call['argv'][0] == 'identify')
        initial_outcomes = {entry['localId']: entry for entry in operation['data']['itemResults']}
        self.assertEqual(initial_outcomes[first['local_id']]['status'], 'reconcile_required')
        self.assertEqual(initial_outcomes[second['local_id']]['status'], 'succeeded')
        writes_before_unverified_resume = [
            call for call in self.cli.calls if call[:2] == ['file', 'upload'] or call[:1] == ['identify']
        ]
        resumed_before_reconciling_first = self.executor.resume(operation['id'])
        self.assertEqual(resumed_before_reconciling_first['data']['status'], 'reconcile_required')
        outcomes = {entry['localId']: entry for entry in resumed_before_reconciling_first['data']['itemResults']}
        self.assertEqual(outcomes[first['local_id']]['status'], 'reconcile_required')
        self.assertEqual(outcomes[second['local_id']]['status'], 'succeeded')
        writes_after_unverified_resume = [
            call for call in self.cli.calls if call[:2] == ['file', 'upload'] or call[:1] == ['identify']
        ]
        self.assertEqual(writes_after_unverified_resume, writes_before_unverified_resume)

        # 模拟宿主只读查到与原识别调用完全同图的远端结果，并已将原始回执归档到任务包。
        snapshot = self.tasks.snapshot(self.key)
        current_first = next(item for item in snapshot['items'] if item['local_id'] == first['local_id'])
        source_hashes = {source['source_id']: source['sha256'] for source in snapshot['sources']}
        evidence = [
            {'evidence_id': value['evidence_id'], 'sha256': source_hashes[value['source_id']]}
            for value in current_first['evidence']
        ]
        identify_args = first_identify['argv'][1:]
        front_url = identify_args[identify_args.index('--front-img') + 1]
        back_url = identify_args[identify_args.index('--back-img') + 1]
        raw_response = json.dumps({
            'identifyUri': 'remote-identify-result',
            'userUniqUri': 'remote-user-result',
            'images': [front_url, back_url],
        }).encode()
        timestamp = test_tasks.operations.now_iso()
        event = {
            'schema_version': 'heribase.recognition-attempt.v1',
            'attempt_id': 'recovered-identification-attempt',
            'task_key': self.key,
            'local_id': first['local_id'],
            'attempt_number': 1,
            'operation_type': 'identify',
            'status': 'succeeded',
            'input': {'item_version': current_first['version'], 'evidence': evidence},
            'cli': {'command': 'heribase identify', 'args': identify_args + ['--json']},
            'remote_task_id': 'remote-identify-result',
            'started_at': timestamp,
            'finished_at': timestamp,
            'exit_code': 0,
            'classification': 'success',
            'raw_response_ref': None,
            'raw_response_sha256': None,
            'error': None,
        }
        self.executor._record(operation['id'], snapshot, event, raw_response)

        resumed = self.executor.resume(operation['id'])

        self.assertEqual(resumed['data']['status'], 'completed')
        self.assertEqual(resumed['data']['itemResults'][0]['status'], 'succeeded')
        first_identifies = [
            call for call in self.cli.calls
            if call[0] == 'identify' and '--candidate-id' in call
            and call[call.index('--candidate-id') + 1] == first['item_key']
        ]
        second_identifies = [
            call for call in self.cli.calls
            if call[0] == 'identify' and '--candidate-id' in call
            and call[call.index('--candidate-id') + 1] == second['item_key']
        ]
        self.assertEqual(len(first_identifies), 1)
        self.assertEqual(len(second_identifies), 1)

    def test_resume_continues_other_candidates_after_a_new_unknown_identification(self):
        """恢复中再次遇到未知结果时，隔离该枚并继续其后的未提交候选。"""
        candidates = [self.tasks.snapshot(self.key)['items'][0]]
        for index in (2, 3):
            front = self.ingest(f'candidate-{index}-front.png', f'front-{index}'.encode())
            back = self.ingest(f'candidate-{index}-back.png', f'back-{index}'.encode())
            current = self.tasks.snapshot(self.key)
            created = self.tasks.create_candidate(
                self.key,
                current['manifest']['revision'],
                [front['source']['source_id'], back['source']['source_id']],
                f'钱币 {index}',
                'user:web',
            )['items'][-1]
            current = self.tasks.snapshot(self.key)
            self.tasks.pair(
                self.key,
                current['manifest']['revision'],
                created['local_id'],
                'confirm_pair',
                [
                    {'sourceId': front['source']['source_id'], 'role': 'obverse'},
                    {'sourceId': back['source']['source_id'], 'role': 'reverse'},
                ],
                'user:web',
            )
            candidates.append(created)

        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.reconciliation_failures.update({candidates[0]['item_key'], candidates[1]['item_key']})
        operation = self.executor.identify(
            dict(
                taskKey=self.key,
                expectedRevision=current['manifest']['revision'],
                planHash=plan['hash'],
                localIds=[entry['localId'] for entry in plan['items']],
                commandId='unknown-then-continue',
            ),
            'user:web',
        )
        self.assertEqual(operation['data']['status'], 'reconcile_required')

        resumed = self.executor.resume(operation['id'])

        self.assertEqual(resumed['data']['status'], 'reconcile_required')
        outcomes = {entry['localId']: entry for entry in resumed['data']['itemResults']}
        self.assertEqual(outcomes[candidates[0]['local_id']]['status'], 'reconcile_required')
        self.assertEqual(outcomes[candidates[1]['local_id']]['status'], 'reconcile_required')
        self.assertEqual(outcomes[candidates[2]['local_id']]['status'], 'succeeded')
        for candidate in candidates:
            identify_calls = [
                call for call in self.cli.calls
                if call[0] == 'identify' and '--candidate-id' in call
                and call[call.index('--candidate-id') + 1] == candidate['item_key']
            ]
            self.assertEqual(len(identify_calls), 1)

    def test_preparing_crash_without_calls_is_closed_without_replay(self):
        account = self.executor.account()
        self.executor._reserve(dict(taskKey=self.key, commandId='preparing-crash'), 'identify', 'user:web', account)
        recovered = WorkspaceExecutor(self.store, self.tasks, self.cli, background=False)
        self.assertEqual(self.store.get_entity('operation', 'preparing-crash')['data']['status'], 'failed')
        recovered.assert_idle(self.key)
        self.assertFalse(any(a[:2] == ['file', 'upload'] for a in self.cli.calls))

    def test_reconcile_cannot_replace_success_or_skip_unknown_later_call(self):
        current = self.tasks.snapshot(self.key)
        plan = self.executor.identification_plan(self.key, current['manifest']['revision'])
        self.cli.unknown = True
        result = self.executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[i['localId'] for i in plan['items']], commandId='mixed'), 'user:web')
        first = result['data']['calls'][0]
        with self.assertRaises(WorkspaceError):
            self.executor.reconcile('mixed', [{'callId': first['id'], 'taskId': 'history-task'}])
        # 模拟某调用的明确拒绝，但其后的 identify 仍未知；不得提前结束整个操作。
        saved = self.store.get_entity('operation-call', first['id'])
        envelope = json.loads(saved['data']['stdout'])
        envelope.update(status='failed', error={'code': 'UNAUTHENTICATED'})
        self.store.save_entity('operation-call', first['id'], {**saved['data'], 'stdout': json.dumps(envelope)}, saved['revision'], 'fixture')
        writes_before_resume = len([a for a in self.cli.calls if a[:2] == ['file', 'upload'] or a[0] == 'identify'])
        resumed = self.executor.resume('mixed')
        self.assertEqual(resumed['data']['status'], 'reconcile_required')
        self.assertEqual(writes_before_resume, len([a for a in self.cli.calls if a[:2] == ['file', 'upload'] or a[0] == 'identify']))
