import json
import tempfile
import unittest
from pathlib import Path
import test_tasks
from workspace_business import WorkspaceBusiness
from workspace_executor import WorkspaceExecutor
from workspace_store import WorkspaceError, WorkspaceStore
from workspace_backup import backup, restore


class BusinessTests(unittest.TestCase):
    tearDown = test_tasks.TaskBridgeTests.tearDown
    ingest = test_tasks.TaskBridgeTests.ingest
    make_pair = test_tasks.TaskBridgeTests.make_pair

    def setUp(self):
        test_tasks.TaskBridgeTests.setUp(self)
        self.make_pair()
        self.side = self.ingest('side.png', b'side')
        self.calls = []
        def runner(argv):
            self.calls.append(argv)
            if argv == ['status']:
                return json.dumps({'authenticated': True, 'accountSubject': 'fixture-account', 'api_base_url': 'https://example.invalid'}).encode()
            if argv[:2] == ['file', 'upload']:
                result = {'fileUrl': 'https://example.invalid/upload/' + str(len(self.calls))}
            elif argv[:2] == ['appraisals', 'submit']:
                result = {'uri': 'fixture-appraisal', 'status': 'processing'}
            elif argv[:2] == ['appraisals', 'detail']:
                result = {'uri': 'fixture-appraisal', 'status': 'finished', 'conclusion': 'fixture-report'}
            elif argv == ['appraisals', 'experts']:
                result = {'official': {'name': '测试官方鉴定', 'appraiserType': 0, 'appraiserId': 0,
                                       'realPersonProductArr': []}}
            else:
                result = {'fixture': True, 'remaining': 3}
            return json.dumps({'status': 'completed', 'accountSubject': 'fixture-account', 'result': result}).encode()
        self.executor = WorkspaceExecutor(self.store, self.tasks, runner, background=False)
        self.business = WorkspaceBusiness(self.store, self.tasks, self.executor)

    def draft(self):
        current = self.tasks.snapshot(self.key)
        return self.business.save_appraisal(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'],
            localId=current['items'][0]['local_id'], description='关注年份', sourceIds=dict(zip(['obverse', 'reverse', 'side'], [s['source_id'] for s in current['sources']])),
            appraiserType=0, appraiserId=0, draftRevision=0), 'user:web')

    def test_draft_confirm_submit_and_report_separate(self):
        draft = self.draft()
        self.assertFalse(self.calls)
        current = self.tasks.snapshot(self.key)
        plan = self.business.preview('appraisal', dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], localId=draft['id']), 'user:web')
        self.assertEqual(len(self.calls), 3)
        request = dict(planId=plan['id'], planHash=plan['hash'], commandId='submit-appraisal')
        operation = self.business.start('appraisal', request, 'user:web')
        self.assertEqual(operation['data']['status'], 'completed')
        saved = self.store.get_entity('appraisal-draft', draft['id'])
        self.assertEqual(saved['data']['status'], 'submitted')
        self.assertNotIn('detail', saved['data'])
        count = len(self.calls)
        self.business.start('appraisal', request, 'user:web')
        self.assertEqual(count, len(self.calls))
        detail = self.business.refresh('appraisal', draft['id'])
        self.assertEqual(detail['data']['detail']['conclusion'], 'fixture-report')

    def test_services_use_cli_expert_names_and_validate_the_selected_service(self):
        """网页展示服务名称；内部专家参数只能来自本次 CLI 目录。"""

        calls = []

        def runner(argv):
            calls.append(argv)
            if argv == ['appraisals', 'experts']:
                result = {
                    'official': {'name': 'HeriBase 官方鉴定', 'appraiserType': 0, 'appraiserId': 0,
                                 'durationTime': '3 Days', 'realPersonProductArr': [{'unitPrice': '29.99', 'unit': '$', 'default': True}]},
                    'recommendList': [{'name': '资深钱币专家', 'appraiserType': 10, 'appraiserId': 18,
                                       'durationTime': '7 Days', 'isRecommend': True,
                                       'realPersonProductArr': [{'unitPrice': '49.99', 'unit': '$', 'default': True}]}],
                }
            elif argv == ['appraisals', 'credits', '--appraiser-type', '10', '--appraiser-id', '18']:
                result = {'remainingTimes': 2, 'credits': []}
            else:
                raise AssertionError(argv)
            return json.dumps({'status': 'completed', 'accountSubject': 'fixture-account', 'result': result}).encode()

        self.executor.runner = runner
        directory = self.business.services()
        self.assertEqual([expert['name'] for expert in directory['experts']], ['HeriBase 官方鉴定', '资深钱币专家'])
        self.assertEqual(directory['experts'][1]['price'], '49.99')
        selected = self.business.services(10, 18)
        self.assertEqual(selected['selected']['name'], '资深钱币专家')
        self.assertEqual(selected['credits']['remainingTimes'], 2)
        with self.assertRaises(WorkspaceError):
            self.business.services(10, 999)

    def test_purchase_options_explain_when_server_catalog_is_empty(self):
        """旧 App 展示价格不能替代正式商品目录中的可结算 SKU。"""

        def response(result):
            return json.dumps({'status': 'completed', 'accountSubject': 'fixture-account', 'result': result}).encode()

        def runner(argv):
            if argv == ['appraisals', 'experts']:
                return response({'officialList': [{
                    'name': '官方标准鉴定', 'appraiserType': 1, 'appraiserId': 0,
                    # 此字段只供旧 App 展示；没有 sku/version，不能用于下单。
                    'realPersonProductArr': [{'productId': 'legacy-standard', 'unitPrice': '29.99'}],
                }]})
            if argv == ['appraisals', 'credits', '--appraiser-type', '1', '--appraiser-id', '0']:
                return response({'remainingTimes': 0})
            if argv == ['appraisals', 'products']:
                return response({'products': []})
            raise AssertionError(argv)

        self.executor.runner = runner
        with self.assertRaisesRegex(WorkspaceError, '尚未上架') as raised:
            self.business.purchase_options(1, 0)
        self.assertEqual(raised.exception.code, 'purchase_catalog_empty')
        self.assertEqual(raised.exception.status, 409)

    def test_purchase_uses_matched_product_then_confirms_paid_and_granted_before_credit(self):
        """购买必须选服务端匹配 SKU，支付页打开和次数到账是两个独立事实。"""

        purchase_uri = 'p' * 32
        calls = []

        def response(result):
            return json.dumps({'status': 'completed', 'accountSubject': 'fixture-account', 'result': result}).encode()

        def runner(argv):
            calls.append(argv)
            if argv == ['status']:
                return json.dumps({'authenticated': True, 'accountSubject': 'fixture-account', 'api_base_url': 'https://example.invalid'}).encode()
            if argv == ['appraisals', 'experts']:
                return response({'officialList': [{'name': '官方标准鉴定', 'appraiserType': 1, 'appraiserId': 0,
                                                   'durationTime': '7 Days',
                                                   'purchaseFilter': {'productType': 'appraisal_credit', 'appraiserType': 1, 'appraiserId': 0}}]})
            if argv == ['appraisals', 'products']:
                return response({'products': [
                    {'sku': 'wrong-service', 'version': 1, 'amount': 999, 'currency': 'USD', 'currencyExponent': 2,
                     'productType': 'appraisal_credit', 'entitlementSpec': {'appraiserType': 5, 'appraiserId': 0, 'times': 1}},
                    {'sku': 'official-standard', 'version': 3, 'amount': 1999, 'currency': 'USD', 'currencyExponent': 2,
                     'productType': 'appraisal_credit', 'entitlementSpec': {'appraiserType': 1, 'appraiserId': 0, 'times': 1}},
                ]})
            if argv[:2] == ['appraisals', 'credits']:
                return response({'remainingTimes': 1})
            if argv[:2] == ['appraisals', 'checkout']:
                return response({'purchaseUri': purchase_uri, 'paymentParameters': {'checkoutUrl': 'https://pay.example/checkout'}})
            if argv[:3] == ['appraisals', 'purchases', 'detail']:
                return response({'uri': purchase_uri, 'paymentState': 'paid', 'fulfillmentState': 'granted', 'purchaseConfirmed': True})
            raise AssertionError(argv)

        self.executor.runner = runner
        options = self.business.purchase_options(1, 0)
        self.assertEqual([product['sku'] for product in options['products']], ['official-standard'])
        plan = self.business.purchase_plan(1, 0, 'official-standard', 'user:web')
        checkout = self.business.checkout_purchase({'planId': plan['id'], 'planHash': plan['hash'], 'commandId': 'purchase-standard'}, 'user:web')
        self.assertEqual(checkout['checkoutUrl'], 'https://pay.example/checkout')
        self.assertEqual(checkout['purchase']['data']['status'], 'awaiting_payment')
        confirmed = self.business.refresh_purchase('purchase-standard')
        self.assertEqual(confirmed['data']['status'], 'granted')
        self.assertEqual(confirmed['data']['credits']['remainingTimes'], 1)
        operation = self.store.get_entity('operation', 'purchase-standard')['data']
        self.assertEqual(operation.get('paymentState'), 'paid')
        self.assertEqual(operation.get('fulfillmentState'), 'granted')
        self.assertEqual(operation.get('purchaseUri'), purchase_uri)
        self.assertIn('支付成功', operation['message'])
        self.assertNotIn('等待用户完成付款', operation['message'])
        self.assertIn(['appraisals', 'checkout', '--sku', 'official-standard', '--version', '3', '--request-id', 'purchase-standard'], calls)

    def test_purchase_refresh_keeps_payment_fulfillment_and_available_balance_distinct(self):
        """余额不能证明本订单付款；已付未发放和已发放但余额为零分别保留真实状态。"""
        account = self.executor.account()
        original = self.executor.runner
        for payment, fulfillment, balance, status, message in [
            ('unpaid', 'pending', 1, 'awaiting_payment', '等待用户完成付款'),
            ('paid', 'pending', 0, 'fulfillment_pending', '等待次数发放'),
            ('paid', 'granted', 0, 'granted', '支付成功'),
        ]:
            with self.subTest(payment=payment, fulfillment=fulfillment):
                purchase_id = 'refresh-' + payment + '-' + fulfillment
                uri = 'PO2611091144abcdef'
                self.store.save_entity('operation', purchase_id, {
                    'kind': 'appraisal_purchase', 'status': 'completed',
                    'message': '支付订单已创建，等待用户完成付款', 'calls': [],
                }, 0, 'user:web')
                self.store.save_entity('appraisal-purchase', purchase_id, {
                    'purchaseUri': uri, 'operationId': purchase_id, 'account': account,
                    'service': {'appraiserType': 10, 'appraiserId': 18},
                    'status': 'awaiting_payment',
                }, 0, 'user:web')

                def runner(argv):
                    if argv == ['status']:
                        return original(argv)
                    if argv == ['appraisals', 'purchases', 'detail', '--uri', uri, '--refresh', '1']:
                        result = {'uri': uri, 'paymentState': payment, 'fulfillmentState': fulfillment,
                                  'purchaseConfirmed': payment == 'paid' and fulfillment == 'granted'}
                    elif argv == ['appraisals', 'credits', '--appraiser-type', '10', '--appraiser-id', '18']:
                        result = {'remainingTimes': balance}
                    else:
                        raise AssertionError(argv)
                    return json.dumps({'status': 'completed', 'result': result}).encode()

                self.executor.runner = runner
                purchase = self.business.refresh_purchase(purchase_id)['data']
                operation = self.store.get_entity('operation', purchase_id)['data']
                self.assertEqual(purchase['status'], status)
                self.assertEqual(purchase['credits']['remainingTimes'], balance)
                self.assertEqual(operation.get('paymentState'), payment)
                self.assertEqual(operation.get('fulfillmentState'), fulfillment)
                self.assertIn(message, operation['message'])
                self.assertEqual(operation['calls'], [])

    def test_created_purchase_without_payment_link_is_recoverable_not_unknown(self):
        """缺支付链接只影响打开页面，不能抹掉已经确认成功的建单结果。"""
        from workspace_executor import digest
        plan = {'kind': 'appraisal_purchase', 'status': 'awaiting_confirmation',
                'account': self.executor.account(), 'service': {'name': '测试服务'},
                'product': {'sku': 'fixture-sku', 'version': 1}}
        plan['hash'] = digest(plan)
        self.store.save_entity('appraisal-purchase-plan', 'plan-no-link', plan, 0, 'user:web')
        original = self.executor.runner
        def runner(argv):
            if argv[:2] == ['appraisals', 'checkout']:
                return json.dumps({'id': 'cli-created', 'status': 'completed',
                                   'accountSubject': 'fixture-account',
                                   'result': {'purchaseUri': 'p' * 32, 'paymentParameters': {}}}).encode()
            return original(argv)
        self.executor.runner = runner
        body = {'planId': 'plan-no-link', 'planHash': plan['hash'], 'commandId': 'purchase-no-link'}
        result = self.business.checkout_purchase(body, 'user:web')
        self.assertEqual(result['purchase']['data']['status'], 'awaiting_payment')
        self.assertIsNone(result['checkoutUrl'])
        self.assertEqual(result['paymentError']['code'], 'payment_url_unavailable')
        self.assertEqual(self.store.get_entity('operation', 'purchase-no-link')['data']['status'], 'completed')
        self.assertTrue(self.business.checkout_purchase(body, 'user:web')['reused'])

    def test_purchase_accepts_cli_task_envelope_and_real_order_uri(self):
        """CLI task 的业务回执位于 result.result，PO 订单号也不固定为 16/32 位。"""
        from workspace_executor import digest

        purchase_uri = 'PO2610081445dtmkzuse'
        checkout_url = 'https://checkout.example/pay/session'
        plan = {
            'kind': 'appraisal_purchase',
            'status': 'awaiting_confirmation',
            'account': self.executor.account(),
            'service': {'name': '测试真人鉴定'},
            'product': {'sku': 'expert-credit', 'version': 1, 'times': 1},
        }
        plan['hash'] = digest(plan)
        self.store.save_entity('appraisal-purchase-plan', 'plan-cli-envelope', plan, 0, 'user:web')

        def runner(argv):
            if argv == ['appraisals', 'checkout', '--sku', 'expert-credit', '--version', '1', '--request-id', 'purchase-cli-envelope']:
                return json.dumps({
                    'id': 'task-checkout',
                    'operation': 'appraisals.checkout',
                    'status': 'completed',
                    'accountSubject': 'fixture-account',
                    'result': {
                        'uri': purchase_uri,
                        'orderType': 'appraisal_purchase',
                        'paymentState': 'unpaid',
                        'paymentParameters': {'data': {'h5Url': checkout_url}},
                    },
                }).encode()
            if argv == ['status']:
                return json.dumps({'authenticated': True, 'accountSubject': 'fixture-account', 'api_base_url': 'https://example.invalid'}).encode()
            raise AssertionError(argv)

        self.executor.runner = runner
        result = self.business.checkout_purchase({
            'planId': 'plan-cli-envelope',
            'planHash': plan['hash'],
            'commandId': 'purchase-cli-envelope',
        }, 'user:web')

        self.assertEqual(result['purchase']['data']['purchaseUri'], purchase_uri)
        self.assertEqual(result['checkoutUrl'], checkout_url)
        self.assertEqual(self.store.get_entity('operation', 'purchase-cli-envelope')['data']['status'], 'completed')

    def test_purchase_accepts_whitelisted_h5_payment_url(self):
        """Wpt 支付预下单返回 data.h5Url 时，也必须能让用户继续完成本订单支付。"""

        h5_url = 'https://checkout.example/pay/session'
        self.assertEqual(
            self.business.checkout_url(
                {'paymentParameters': {'data': {'h5Url': h5_url}}}
            ),
            h5_url,
        )

    def test_purchase_can_resume_existing_unpaid_order_without_creating_another(self):
        """继续支付只请求已有 purchaseUri，绝不能重放 checkout 创建新订单。"""

        purchase_id = 'existing-purchase'
        purchase_uri = 'p' * 32
        h5_url = 'https://checkout.example/pay/existing-session'
        self.store.save_entity(
            'appraisal-purchase',
            purchase_id,
            {
                'purchaseUri': purchase_uri,
                'account': {
                    'subject': 'fixture-account',
                    'apiBaseUrl': 'https://example.invalid',
                },
                'service': {'name': '官方标准鉴定'},
                'product': {'sku': 'official-standard'},
                'status': 'awaiting_payment',
            },
            0,
            'user:web',
        )

        def response(result):
            return json.dumps({
                'status': 'completed', 'accountSubject': 'fixture-account', 'result': result
            }).encode()

        def runner(argv):
            if argv == ['status']:
                return json.dumps({
                    'authenticated': True,
                    'accountSubject': 'fixture-account',
                    'api_base_url': 'https://example.invalid',
                }).encode()
            if argv == ['appraisals', 'purchases', 'pay', '--uri', purchase_uri]:
                return json.dumps({
                    'id': 'task-resume-payment',
                    'operation': 'appraisals.purchases.pay',
                    'status': 'completed',
                    'accountSubject': 'fixture-account',
                    'result': {'paymentParameters': {'payInfo': {'h5Url': h5_url}}},
                }).encode()
            raise AssertionError(argv)

        self.executor.runner = runner
        resumed = self.business.resume_purchase(purchase_id)
        self.assertEqual(resumed['checkoutUrl'], h5_url)
        self.assertTrue(resumed['reused'])
        self.assertEqual(
            self.calls,
            [],
            '继续支付不应使用初始测试 runner 或创建另一张订单',
        )

    def test_tracking_credit_purchase_uses_server_catalog_and_verifies_grant(self):
        """追踪位购买只用服务端 SKU 下单，付款与追踪位到账分开核验。"""
        from workspace_executor import digest

        purchase_uri = 't' * 32
        h5_url = 'https://checkout.example/tracking'
        base_plan = {
            'kind': 'tracking', 'status': 'awaiting_confirmation',
            'account': self.executor.account(), 'taskKey': self.key,
            'localId': self.tasks.snapshot(self.key)['items'][0]['local_id'],
            'collectUri': 'COL-1', 'title': '测试收藏',
            'eligibility': {'remainingTimes': 0},
        }
        base_plan['hash'] = digest(base_plan)
        self.store.save_entity('business-plan', 'tracking-base', base_plan, 0, 'user:web')

        def response(result):
            return json.dumps({
                'status': 'completed', 'accountSubject': 'fixture-account', 'result': result,
            }).encode()

        def runner(argv):
            if argv == ['status']:
                return json.dumps({'authenticated': True, 'accountSubject': 'fixture-account',
                                   'api_base_url': 'https://example.invalid'}).encode()
            if argv == ['tracking', 'products']:
                return response({'products': [
                    {'sku': 'tracking-month', 'version': 2, 'productType': 'tracking_credit',
                     'nameKey': 'tracking.month', 'amount': 1999, 'currency': 'usd',
                     'currencyExponent': 2, 'entitlementSpec': {'times': 10, 'durationUnit': 'month', 'durationCount': 1}},
                    {'sku': 'membership', 'version': 1, 'productType': 'membership',
                     'amount': 999, 'currency': 'usd', 'currencyExponent': 2,
                     'entitlementSpec': {'durationUnit': 'month', 'durationCount': 1}},
                ]})
            if argv == ['tracking', 'checkout', '--sku', 'tracking-month', '--version', '2',
                        '--request-id', 'tracking-purchase-1', '--source-type', 'collection', '--source-uri', 'COL-1']:
                return response({'uri': purchase_uri, 'paymentState': 'unpaid',
                                 'paymentParameters': {'data': {'h5Url': h5_url}}})
            if argv == ['tracking', 'purchases', 'pay', '--uri', purchase_uri]:
                return response({'paymentParameters': {'data': {'h5Url': h5_url}}})
            if argv == ['tracking', 'purchases', 'detail', '--uri', purchase_uri, '--refresh', '1']:
                return response({'uri': purchase_uri, 'paymentState': 'paid',
                                 'fulfillmentState': 'granted'})
            if argv == ['tracking', 'slots']:
                return response({'remainingTimes': 10, 'totalTimes': 20, 'usedTimes': 10})
            raise AssertionError(argv)

        self.executor.runner = runner
        options = self.business.tracking_purchase_options('tracking-base')
        self.assertEqual([product['sku'] for product in options['products']], ['tracking-month'])
        plan = self.business.tracking_purchase_plan('tracking-base', 'tracking-month', 'user:web')
        checkout = self.business.checkout_tracking_purchase({
            'planId': plan['id'], 'planHash': plan['hash'], 'commandId': 'tracking-purchase-1',
        }, 'user:web')
        self.assertEqual(checkout['checkoutUrl'], h5_url)
        self.assertEqual(checkout['purchase']['data']['status'], 'awaiting_payment')
        resumed = self.business.resume_tracking_purchase('tracking-purchase-1')
        self.assertEqual(resumed['checkoutUrl'], h5_url)
        verified = self.business.refresh_tracking_purchase('tracking-purchase-1')
        self.assertEqual(verified['data']['status'], 'granted')
        self.assertEqual(verified['data']['eligibility']['remainingTimes'], 10)

    def test_tracking_confirmation_rechecks_slots_before_consuming_one(self):
        """预览后额度可能变化；零追踪位时确认不会调用 tracking add。"""
        from workspace_executor import digest

        task = self.tasks.snapshot(self.key)
        plan = {
            'kind': 'tracking', 'status': 'awaiting_confirmation',
            'account': self.executor.account(), 'taskKey': self.key,
            'localId': task['items'][0]['local_id'], 'taskRevision': task['manifest']['revision'],
            'collectUri': 'COL-1', 'title': '测试收藏',
        }
        plan['hash'] = digest(plan)
        self.store.save_entity('business-plan', 'tracking-race-plan', plan, 0, 'user:web')

        def response(result):
            return json.dumps({
                'status': 'completed', 'accountSubject': 'fixture-account', 'result': result,
            }).encode()

        def runner(argv):
            if argv == ['status']:
                return json.dumps({'authenticated': True, 'accountSubject': 'fixture-account',
                                   'api_base_url': 'https://example.invalid'}).encode()
            if argv == ['tracking', 'slots']:
                return response({'totalSlots': 0, 'usedSlots': 0, 'availableSlots': 0})
            raise AssertionError(argv)

        self.executor.runner = runner
        with self.assertRaises(WorkspaceError) as raised:
            self.business.start('tracking', {
                'planId': 'tracking-race-plan', 'planHash': plan['hash'],
                'commandId': 'tracking-confirm-no-slot',
            }, 'user:web')
        self.assertEqual(raised.exception.code, 'tracking_slots_empty')

    def test_appraisal_materials_exclude_images_assigned_to_other_candidates(self):
        item = self.tasks.snapshot(self.key)['items'][0]
        front = self.ingest('other-front.png', b'other-front')
        back = self.ingest('other-back.png', b'other-back')
        current = self.tasks.snapshot(self.key)
        other = self.tasks.create_candidate(
            self.key, current['manifest']['revision'], [front['source']['source_id'], back['source']['source_id']], '另一枚钱币', 'user:web'
        )['items'][-1]
        current = self.tasks.snapshot(self.key)
        self.tasks.pair(self.key, current['manifest']['revision'], other['local_id'], 'confirm_pair',
                        [{'sourceId': front['source']['source_id'], 'role': 'obverse'}, {'sourceId': back['source']['source_id'], 'role': 'reverse'}], 'user:web')
        task = self.tasks.snapshot(self.key)
        available = self.business.appraisal_material_sources(task, next(value for value in task['items'] if value['local_id'] == item['local_id']))
        self.assertNotIn(front['source']['source_id'], available)
        self.assertNotIn(back['source']['source_id'], available)
        self.assertIn(self.side['source']['source_id'], available)

    def test_changed_materials_invalidate_confirmation(self):
        draft = self.draft()
        current = self.tasks.snapshot(self.key)
        plan = self.business.preview('appraisal', dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], localId=draft['id']), 'user:web')
        self.store.save_entity('appraisal-draft', draft['id'], {**draft['data'], 'description': '变化'}, draft['revision'], 'user:web')
        with self.assertRaises(WorkspaceError):
            self.business.start('appraisal', dict(planId=plan['id'], planHash=plan['hash'], commandId='stale'), 'user:web')
        self.assertFalse(any(a[:2] == ['appraisals', 'submit'] for a in self.calls))

    def test_backup_restore_preserves_tasks_database_without_credentials(self):
        self.draft()
        (self.store.directory / 'auth.json').write_text('not-in-backup')
        result = backup(self.store, self.tasks, self.executor)
        destination = Path(self.tmp.name) / 'recovered'
        restore(Path(result['path']), destination)
        reopened = WorkspaceStore(destination)
        self.assertEqual(len(reopened.list_entities('appraisal-draft')), 1)
        self.assertFalse((destination / '.heribase/auth.json').exists())
        self.assertTrue((destination / '.heribase/user-tasks' / self.key / 'manifest.json').is_file())
        with self.assertRaises(WorkspaceError):
            restore(Path(result['path']), destination)

    def test_successful_submission_recovers_local_archive_without_new_submit(self):
        draft = self.draft()
        current = self.tasks.snapshot(self.key)
        plan = self.business.preview('appraisal', dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], localId=draft['id']), 'user:web')
        original = self.store.save_entity
        fail_once = [True]
        def interrupt(kind, entity_id, data, revision, actor):
            if kind == 'appraisal-draft' and data.get('status') == 'submitted' and fail_once[0]:
                fail_once[0] = False
                raise OSError('fixture local interruption')
            return original(kind, entity_id, data, revision, actor)
        self.store.save_entity = interrupt
        result = self.business.start('appraisal', dict(planId=plan['id'], planHash=plan['hash'], commandId='recover-appraisal'), 'user:web')
        self.assertEqual(result['data']['status'], 'reconcile_required')
        writes = len([a for a in self.calls if a[:2] == ['appraisals', 'submit']])
        resumed = self.executor.resume(result['id'], self.business)
        self.assertEqual(resumed['data']['status'], 'completed')
        self.assertEqual(writes, len([a for a in self.calls if a[:2] == ['appraisals', 'submit']]))
        self.assertEqual(self.store.get_entity('appraisal-draft', draft['id'])['data']['uri'], 'fixture-appraisal')

    def collected_fixture(self):
        from test_executor import FakeCLI
        cli = FakeCLI()
        def runner(argv):
            if argv[:2] == ['tracking', 'slots']:
                return json.dumps({'status': 'completed', 'accountSubject': cli.account, 'result': {'totalSlots': 3, 'usedSlots': 0, 'availableSlots': 3}}).encode()
            if argv[:2] == ['tracking', 'add']:
                cli.calls.append(argv)
                return json.dumps({'status': 'completed', 'accountSubject': cli.account, 'result': {'uri': 'fixture-tracking'}}).encode()
            return cli(argv)
        executor = WorkspaceExecutor(self.store, self.tasks, runner, background=False)
        business = WorkspaceBusiness(self.store, self.tasks, executor)
        current = self.tasks.snapshot(self.key)
        item = current['items'][0]
        current = self.tasks.pair(self.key, current['manifest']['revision'], item['local_id'], 'confirm_pair',
            [{'sourceId': s['source_id'], 'role': role} for s, role in zip(current['sources'][:2], ['obverse', 'reverse'])], 'user:web')
        plan = executor.identification_plan(self.key, current['manifest']['revision'])
        executor.identify(dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], planHash=plan['hash'], localIds=[item['local_id']], commandId='id-for-tracking'), 'user:web')
        current = self.tasks.snapshot(self.key)
        current = self.tasks.review(self.key, current['manifest']['revision'], item['local_id'], 'collect', 'user:web')
        plan = executor.collection_plan(self.key, current['manifest']['revision'], [item['local_id']], 'user:web')
        executor.collect(dict(taskKey=self.key, expectedRevision=plan['revision'], planId=plan['plan_id'], planHash=plan['payload_sha256'], commandId='collect-for-tracking'), 'user:web')
        current = self.tasks.snapshot(self.key)
        return cli, business, dict(taskKey=self.key, expectedRevision=current['manifest']['revision'], localId=item['local_id'])

    def test_two_tracking_previews_cannot_consume_two_slots(self):
        cli, business, body = self.collected_fixture()
        first = business.preview('tracking', body, 'user:web')
        second = business.preview('tracking', body, 'user:web')
        self.assertEqual(business.start('tracking', dict(planId=first['id'], planHash=first['hash'], commandId='tracking-first'), 'user:web')['data']['status'], 'completed')
        with self.assertRaises(WorkspaceError):
            business.start('tracking', dict(planId=second['id'], planHash=second['hash'], commandId='tracking-second'), 'user:web')
        self.assertEqual(len([a for a in cli.calls if a[:2] == ['tracking', 'add']]), 1)

    def test_tracking_cannot_use_other_accounts_collection(self):
        cli, business, body = self.collected_fixture()
        cli.account = 'other-user'
        with self.assertRaises(WorkspaceError) as exc:
            business.preview('tracking', body, 'user:web')
        self.assertEqual(exc.exception.code, 'account_changed')
