"""审核内容必须与决定一起持久化，且不能绕过来源差异与版本检查。"""
import json
import unittest
import test_tasks
from workspace_tasks import WorkspaceTasks, operations
from workspace_store import WorkspaceStore, WorkspaceError
from workspace_service import WorkspaceService

class ReviewTests(unittest.TestCase):
    setUp = test_tasks.TaskBridgeTests.setUp
    tearDown = test_tasks.TaskBridgeTests.tearDown
    ingest = test_tasks.TaskBridgeTests.ingest
    make_pair = test_tasks.TaskBridgeTests.make_pair
    def request(self, decision=None, details=None):
        current = self.tasks.snapshot(self.key)
        body = dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], localId=current['items'][0]['local_id'])
        if decision is not None: body['decision'] = decision
        if details is not None: body['details'] = details
        return WorkspaceService(self.store, background=False).mutate('/api/tasks/review', body, 'browser')

    def test_hold_persists_details_with_audited_clear_and_does_not_enter_collection(self):
        self.make_pair()
        self.request('exclude')
        self.request('hold', {'note':'待核对年份', 'weight':'6.38', 'condition':'边缘需补拍', 'checks':['identity']})
        reopened = WorkspaceTasks(WorkspaceStore(__import__("pathlib").Path(self.tmp.name))).snapshot(self.key)
        item = reopened['items'][0]
        self.assertIsNone(item['review_projection']['decision'])
        self.assertTrue(item['review_projection']['deferred'])
        self.assertEqual(item['reviewDetails']['weight'], '6.38')
        self.assertEqual(item['reviewHistory'][-1]['decision'], 'hold')
        self.assertTrue(reopened['health']['ok'])
        events = [json.loads(x) for x in (self.tasks.root/self.key/'review/decisions.jsonl').read_text().splitlines()]
        self.assertEqual(events[-1]['action'], 'clear')
        self.assertIsNone(events[-1]['decision'])

    def test_detail_only_save_keeps_existing_decision_and_rejects_stale_revision(self):
        self.make_pair()
        first = self.request('need_photo', {'note':'原备注'})
        self.request(details={'weight':'5.1'})
        item = self.tasks.snapshot(self.key)['items'][0]
        self.assertEqual(item['review_projection']['decision'], 'need_photo')
        self.assertEqual(item['reviewDetails']['note'], '原备注')
        with self.assertRaises(WorkspaceError):
            WorkspaceService(self.store, background=False).mutate('/api/tasks/review', dict(taskKey=self.key, expectedRevision=first['manifest']['revision'], localId=item['local_id'], decision='exclude'), 'browser')

    def test_invalid_measurement_and_unsupported_fields_never_write(self):
        self.make_pair()
        revision=self.tasks.snapshot(self.key)['manifest']['revision']
        for details in [{'weight':'-2'}, {'diameter':'nan'}, {'checks':['invented']}, {'account':'x'}]:
            with self.assertRaises(WorkspaceError): self.request('hold',details)
        self.assertEqual(self.tasks.snapshot(self.key)['manifest']['revision'],revision)

    def test_year_conflict_requires_current_snapshot_resolution_and_hold_revokes_plan(self):
        import argparse
        from pathlib import Path
        item=self.make_pair()
        item['resolved_fields']['year']={'value':'1944'}
        item['version'] += 1
        self.tasks._import_json(self.key,self.tasks.snapshot(self.key)['manifest']['revision'],'fixture',operations.import_items,[item],mode='merge')
        now=operations.now_iso()
        raw=Path(self.tmp.name)/'raw.json'; raw.write_text(json.dumps({'status':'completed','result':{'uri':'fixture','year':'1948','title':'Cameroon 1 franc 1948'}}))
        event=Path(self.tmp.name)/'event.json'; event.write_text(json.dumps({'schema_version':'heribase.recognition-attempt.v1','attempt_id':'fixture-attempt','task_key':self.key,'local_id':item['local_id'],'attempt_number':1,'operation_type':'identify','status':'succeeded','input':{'item_version':item['version'],'evidence':[]},'cli':{'command':'heribase identify','args':['--json']},'remote_task_id':'remote','started_at':now,'finished_at':now,'exit_code':0,'classification':'success','raw_response_ref':None,'raw_response_sha256':None,'error':None}))
        self.tasks._call(self.key,self.tasks.snapshot(self.key)['manifest']['revision'],'fixture',operations.record_recognition,event_json=str(event),raw_json=str(raw))
        with self.assertRaises(WorkspaceError) as error: self.request('collect')
        self.assertEqual(error.exception.code,'review_conflict')
        self.request('collect',{'resolution':'已对照原图核对，保留人工判断依据'})
        current=self.tasks.snapshot(self.key)
        operations.build_plan(argparse.Namespace(root=str(self.tasks.root),task_key=self.key,expected_revision=current['manifest']['revision'],actor='fixture',operation='collection_add',operations_json=None))
        self.request('hold')
        self.assertEqual(self.tasks.snapshot(self.key)['plan']['status'],'stale')
        current=self.tasks.snapshot(self.key)
        with self.assertRaisesRegex(operations.core.PackageError, '没有满足'):
            operations.build_plan(argparse.Namespace(root=str(self.tasks.root),task_key=self.key,expected_revision=current['manifest']['revision'],actor='fixture',operation='collection_add',operations_json=None))

    def test_ambiguous_source_years_do_not_create_a_false_conflict(self):
        from workspace_review import issues
        self.assertEqual(issues({'recognitionResult':{'year':'1948'},'field_claims':{'visible_text':[{'value':'1944 或 1948'}]}}),[])

    def test_editing_stale_details_does_not_reactivate_an_old_decision(self):
        item=self.make_pair()
        self.request('need_photo')
        current=self.tasks.snapshot(self.key)
        sources=current['sources']
        self.tasks.pair(self.key,current['manifest']['revision'],item['local_id'],'confirm_pair',
            [{'sourceId':sources[0]['source_id'],'role':'obverse'},{'sourceId':sources[1]['source_id'],'role':'reverse'}],'user:web')
        self.request(details={'condition':'补充观察'})
        item=self.tasks.snapshot(self.key)['items'][0]
        self.assertIsNone(item['review_projection']['decision'])
        self.assertEqual(item['reviewDetails']['condition'],'补充观察')

    def test_bulk_hold_uses_same_persistent_clear_and_history(self):
        item=self.make_pair()
        self.request('exclude')
        service=WorkspaceService(self.store,background=False)
        body=dict(taskKey=self.key,expectedRevision=self.tasks.snapshot(self.key)['manifest']['revision'],stage='review',action='hold',localIds=[item['local_id']])
        plan=service.mutate('/api/tasks/bulk-preview',body,'browser')
        service.mutate('/api/tasks/bulk-apply',{**body,'planHash':plan['planHash']},'browser')
        current=self.tasks.snapshot(self.key)
        self.assertIsNone(current['items'][0]['review_projection']['decision'])
        self.assertTrue(current['items'][0]['review_projection']['deferred'])
        self.assertEqual(current['batches'][0]['items'][0]['action'],'hold')
        self.assertTrue(current['health']['ok'])
