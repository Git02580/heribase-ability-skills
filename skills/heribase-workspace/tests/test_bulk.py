"""批量操作必须真的落入任务包；不以模拟方法替代决定、版本和事件。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workspace_service import WorkspaceService
from workspace_store import WorkspaceStore, WorkspaceError


class BulkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = WorkspaceService(WorkspaceStore(Path(self.tmp.name)), background=False)
        self.tasks = self.service.tasks
        self.key = self.tasks.create('批量验收', 'Asia/Shanghai', 'user:web')['manifest']['task_key']
        for n in range(3):
            ids = []
            for side in range(2):
                result = self.tasks.ingest(self.key, self.revision(), f'{n}-{side}.png', f'image-{n}-{side}'.encode(), 'user:web')
                ids.append(result['source']['source_id'])
            self.tasks.create_candidate(self.key, self.revision(), ids, f'钱币 {n + 1}', 'user:web')
        self.ids = [i['local_id'] for i in self.snapshot()['items']]

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self):
        return self.tasks.snapshot(self.key)

    def revision(self):
        return self.snapshot()['manifest']['revision']

    def body(self, stage='review', action='need_photo', ids=None):
        return dict(taskKey=self.key, expectedRevision=self.revision(), stage=stage, action=action, localIds=self.ids if ids is None else ids)

    def preview(self, body):
        return self.service.mutate('/api/tasks/bulk-preview', body, 'browser')

    def apply(self, body, plan):
        return self.service.mutate('/api/tasks/bulk-apply', {**body, 'planHash': plan['planHash']}, 'browser')

    def test_review_batch_persists_per_item_events_and_unselected_item_unchanged(self):
        body = self.body(ids=self.ids[:2])
        plan = self.preview(body)
        self.assertEqual([i['status'] for i in plan['items']], ['ready', 'ready'])
        self.assertIsNone(self.snapshot()['items'][0]['review_projection'])
        result = self.apply(body, plan)
        reopened = self.snapshot()
        self.assertEqual([i['review_projection']['decision'] for i in reopened['items'][:2]], ['need_photo', 'need_photo'])
        self.assertIsNone(reopened['items'][2]['review_projection'])
        events = [json.loads(line) for line in (self.tasks.root / self.key / 'review/decisions.jsonl').read_text().splitlines()]
        self.assertEqual(len(events), 2)
        self.assertEqual({e['interaction']['batch_action_id'] for e in events}, {result['batchActionId']})
        self.assertEqual(len(reopened['batches'][0]['items']), 2)
        with self.assertRaises(WorkspaceError):
            self.apply(body, plan)
        self.assertEqual(len((self.tasks.root / self.key / 'review/decisions.jsonl').read_text().splitlines()), 2)

    def test_pairing_does_not_guess_roles_and_preserves_already_confirmed_items(self):
        item = self.snapshot()['items'][0]
        self.tasks.pair(self.key, self.revision(), item['local_id'], 'confirm_pair', [
            {'sourceId': item['evidence'][0]['source_id'], 'role': 'reverse'},
            {'sourceId': item['evidence'][1]['source_id'], 'role': 'obverse'}], 'user:web')
        body = self.body('pairing', 'confirm_pair')
        plan = self.preview(body)
        self.assertEqual([i['status'] for i in plan['items']], ['unchanged', 'blocked', 'blocked'])
        with self.assertRaises(WorkspaceError):
            self.apply(body, plan)
        self.assertEqual(self.snapshot()['items'][0]['organization']['source_assignment'][0]['role'], 'reverse')

    def test_changed_revision_and_forged_hash_never_overwrite(self):
        body = self.body()
        plan = self.preview(body)
        with self.assertRaises(WorkspaceError):
            self.apply(body, {'planHash': '0' * 64})
        self.tasks.review(self.key, self.revision(), self.ids[0], 'exclude', 'agent:test')
        with self.assertRaises(WorkspaceError):
            self.apply(body, plan)
        self.assertEqual(self.snapshot()['items'][0]['review_projection']['decision'], 'exclude')
        self.assertIsNone(self.snapshot()['items'][1]['review_projection'])

    def test_overwrite_and_unchanged_are_reported_without_changing_other_decisions(self):
        self.tasks.review(self.key, self.revision(), self.ids[0], 'exclude', 'user:web')
        self.tasks.review(self.key, self.revision(), self.ids[1], 'need_photo', 'user:web')
        body = self.body()
        plan = self.preview(body)
        self.assertEqual([i['status'] for i in plan['items']], ['ready', 'unchanged', 'ready'])
        self.assertEqual([i['overwrite'] for i in plan['items']], [True, False, False])
        self.apply(body, plan)
        self.assertEqual(len((self.tasks.root / self.key / 'review/decisions.jsonl').read_text().splitlines()), 4)

    def test_invalid_scope_and_unidentified_collect_are_blocked(self):
        for ids in [[], self.ids[:1] * 2, ['unknown'], [None]]:
            with self.assertRaises(WorkspaceError):
                self.preview(self.body(ids=ids))
        plan = self.preview(self.body(action='collect'))
        self.assertEqual([i['status'] for i in plan['items']], ['blocked'] * 3)

    def test_bound_host_uses_same_batch_contract_and_actor(self):
        binding = self.service.store.bind_host('test', 'bulk-test', {'inbox': True})
        body = self.body('pairing', 'need_photo')
        plan = self.service.mutate('/api/bridge/action', {'bindingId': binding['id'], 'action': 'batch.preview', 'payload': body}, 'host')
        result = self.service.mutate('/api/bridge/action', {'bindingId': binding['id'], 'action': 'batch.apply', 'payload': {**body, 'planHash': plan['planHash']}}, 'host')
        self.assertEqual(len(result['appliedIds']), 3)
        self.assertEqual(self.snapshot()['batches'][0]['actor'], 'agent:' + binding['id'])

    def test_pairing_confirm_ready_subset_and_review_collect_only_valid_identification(self):
        from workspace_tasks import operations
        items = self.snapshot()['items'][:2]
        for item in items:
            item['version'] += 1
            item.pop('recognitionResult', None)
            item['evidence'][0]['role'] = 'reverse'
            item['evidence'][1]['role'] = 'obverse'
        self.tasks._import_json(self.key, self.revision(), 'agent:test', operations.import_items, items, mode='merge')
        body = self.body('pairing', 'confirm_pair')
        plan = self.preview(body)
        self.assertEqual([i['status'] for i in plan['items']], ['ready', 'ready', 'blocked'])
        self.apply(body, plan)
        self.assertEqual([i['organization']['pairing_state'] for i in self.snapshot()['items']], ['confirmed', 'confirmed', 'needs_review'])
        from test_executor import FakeCLI
        self.service.executor.runner = FakeCLI()
        request = dict(taskKey=self.key, expectedRevision=self.revision(), localIds=[self.ids[1]])
        selected = self.service.mutate('/api/tasks/identification-plan', request, 'browser')
        self.assertEqual([i['localId'] for i in selected['items']], [self.ids[1]])
        with self.assertRaises(WorkspaceError):
            self.service.executor.identify({**request, 'localIds': self.ids[:2], 'planHash': selected['hash'], 'commandId': 'expanded'}, 'user:web')
        self.service.executor.identify({**request, 'planHash': selected['hash'], 'commandId': 'subset'}, 'user:web')
        body = self.body(action='collect')
        plan = self.preview(body)
        self.assertEqual([i['status'] for i in plan['items']], ['blocked', 'ready', 'blocked'])
        self.apply(body, plan)
        self.assertIsNone(self.snapshot()['items'][0]['review_projection'])
        self.assertEqual(self.snapshot()['items'][1]['review_projection']['decision'], 'collect')
        self.assertIsNone(self.snapshot()['items'][1]['collection_projection'])

    def test_batch_history_retains_skipped_scope_after_reopen(self):
        body = self.body('pairing', 'need_photo', self.ids[:1])
        self.apply(body, self.preview(body))
        body = self.body('pairing', 'need_photo')
        result = self.apply(body, self.preview(body))
        batch = next(b for b in self.snapshot()['batches'] if b['batchActionId'] == result['batchActionId'])
        self.assertEqual([i['status'] for i in batch['items']], ['unchanged', 'applied', 'applied'])

    def test_shared_pairing_sources_are_blocked_without_losing_safe_items(self):
        from workspace_tasks import operations
        items = self.snapshot()['items'][:2]
        items[1]['evidence'] = items[0]['evidence']
        items[1]['source_refs'] = items[0]['source_refs']
        for item in items:
            item['version'] += 1
        self.tasks._import_json(self.key, self.revision(), 'agent:test', operations.import_items, items, mode='merge')
        body = self.body('pairing', 'exclude')
        plan = self.preview(body)
        self.assertEqual([i['status'] for i in plan['items']], ['blocked', 'blocked', 'ready'])
        self.apply(body, plan)
        self.assertEqual(self.snapshot()['items'][2]['organization']['pairing_state'], 'excluded')

    def test_missing_pairing_evidence_does_not_block_other_candidates(self):
        from workspace_tasks import operations
        item = self.snapshot()['items'][0]
        item['version'] += 1
        item['evidence'] = []
        item['status'] = 'source_incomplete'
        self.tasks._import_json(self.key, self.revision(), 'agent:test', operations.import_items, [item], mode='merge')
        body = self.body('pairing', 'need_photo')
        plan = self.preview(body)
        self.assertEqual([i['status'] for i in plan['items']], ['blocked', 'ready', 'ready'])
        result = self.apply(body, plan)
        self.assertEqual(result['appliedIds'], self.ids[1:])
