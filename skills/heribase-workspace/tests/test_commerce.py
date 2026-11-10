"""真实 WorkspaceService/SQLite + 假 CLI：验证确认、状态核验和账户边界，无真实支付。"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workspace_service import WorkspaceService
from workspace_store import WorkspaceStore, WorkspaceError


class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = WorkspaceStore(Path(self.tmp.name))
        self.calls = []
        self.subject = 'buyer-a'
        self.unknown = False
        self.definite_failure = False
        self.address = dict(id=12, fullName='Ada L', streetAddress='1 Main', city='SF', countryCode='US')
        self.preview = dict(goodsInfo=dict(uri='G1', title='Morgan Dollar', version=3, saleState=1),
                            priceInfo=dict(salePrice='19.99', postage='1.00', totalPrice='20.99'),
                            addressList=[self.address], payMethod=[dict(code=23, name='Stripe')])
        self.product = dict(sku='membership.year', version=1, productType='membership', amount=3999,
                            currency='USD', currencyExponent=2, billingMode='payment',
                            entitlementSpec=dict(durationUnit='year', durationCount=1, offerType='standard'))
        self.service = WorkspaceService(self.store, self.runner, background=False)

    def runner(self, argv):
        self.calls.append(argv)
        if argv == ['status']:
            return json.dumps(dict(authenticated=True, accountSubject=self.subject, api_base_url='https://fixture.invalid')).encode()
        head = tuple(argv[:3])
        if head == ('trade', 'orders', 'preview'):
            result = copy.deepcopy(self.preview)
        elif head == ('trade', 'addresses', 'detail'):
            result = {'detail': copy.deepcopy(self.address)}
        elif argv == ['memberships', 'products']:
            result = dict(products=[self.product], paymentChannel='wpt_pay_center')
        elif argv[:2] == ['memberships', 'checkout']:
            result = dict(uri='m' * 32, paymentState='unpaid', fulfillmentState='pending',
                          product=self.product, paymentParameters={'data': {'h5Url': 'https://pay.example/member'}})
        elif head == ('trade', 'orders', 'create'):
            if self.unknown:
                return json.dumps(self.order_task(status='running')).encode()
            if self.definite_failure:
                return json.dumps(dict(id='task-create', status='failed', accountSubject=self.subject,
                                       error=dict(code='INVALID_STATE', reconciliationRequired=False))).encode()
            result = dict(orderUri='O1', data={'h5Url': 'https://pay.example/order'})
        elif argv == ['task', 'get', 'task-create']:
            result = dict(orderUri='O1', data={'h5Url': 'https://pay.example/order'})
            return json.dumps(self.order_task(status='completed', result=result)).encode()
        elif head == ('trade', 'orders', 'detail'):
            result = dict(goodsInfo={'title': 'Morgan Dollar'}, payInfo={'orderUri': 'O1'}, isSeller=False,
                          stateDetail={'state': 100, 'canShip': False})
        elif head == ('trade', 'orders', 'pay'):
            result = dict(orderUri='O1', payInfo={'h5Url': 'https://pay.example/resume'})
        elif head == ('trade', 'seller', 'withdrawal-info'):
            result = dict(minMoney=1, maxMoney='50.00', paypalName='Ada', paypalEmail='ada@example.com')
        elif argv[:2] == ['file', 'upload']:
            self.assertTrue(Path(argv[argv.index('--file') + 1]).is_file())
            result = {'fileUrl': 'https://cdn.example/upload.png'}
        else:
            result = dict(list=[], isEnd=True, page=2)
        return json.dumps(dict(id='task-create', status='completed', accountSubject=self.subject, result=result)).encode()

    def order_task(self, **values):
        return dict(id='task-create', operation='trade.orders.create', accountSubject=self.subject,
                    request=dict(apiBaseUrl='https://fixture.invalid', input=dict(uri='G1', addressId=12, payMethod=23, version=3)), **values)

    def call(self, path, body, role='browser'):
        return self.service.mutate('/api/commerce/' + path, body, role)

    def plan(self, action='trade.orders.create', params=None):
        return self.call('plan', dict(action=action, params=params or dict(uri='G1', addressId=12, payMethod=23)))

    def execute(self, plan, command='confirm-1'):
        return self.call('execute', dict(planId=plan['id'], planHash=plan['hash'], commandId=command))

    def writes(self):
        return [call for call in self.calls if call[:3] == ['trade', 'orders', 'create'] or call[:2] == ['memberships', 'checkout']]

    def test_address_update_preserves_apartment_through_confirmation_and_cli(self):
        params = dict(id='12', firstName='Ada', lastName='L', streetAddress='1 Main',
                      additionalAddressInfo='Apt 2', postalCode='94105', addressState='CA',
                      city='SF', phoneNumber='1234', phoneCountryCode='+1', countryCode='US')
        plan = self.plan('trade.addresses.update', params)
        self.assertEqual(plan['summary']['changes']['additionalAddressInfo'], 'Apt 2')
        self.execute(plan)
        write = next(c for c in self.calls if c[:3] == ['trade', 'addresses', 'update'])
        self.assertEqual(write[write.index('--additional-address-info') + 1], 'Apt 2')

    def test_confirmed_trade_uses_current_server_version_and_is_idempotent(self):
        plan = self.plan()
        self.assertEqual(plan['summary']['price']['totalPrice'], '20.99')
        self.assertEqual(plan['summary']['address']['streetAddress'], '1 Main')
        self.assertEqual(self.writes(), [])
        result = self.execute(plan)
        self.assertEqual(result['checkoutUrl'], 'https://pay.example/order')
        self.assertEqual(result['operation']['data']['status'], 'completed')
        self.assertIn('--version', self.writes()[0])
        self.assertEqual(self.writes()[0][self.writes()[0].index('--version') + 1], '3')
        self.execute(plan)
        self.assertEqual(len(self.writes()), 1)
        with self.assertRaises(WorkspaceError):
            self.execute(plan, 'different-confirmation')

    def test_create_and_resume_payment_send_the_current_local_return_urls_to_cli(self):
        self.service.commerce.set_payment_return_base_url('http://127.0.0.1:58483')
        create_plan = self.plan()
        self.execute(create_plan, 'create-with-return')
        create_call = next(call for call in self.calls if call[:3] == ['trade', 'orders', 'create'])
        self.assertIn('--success-url', create_call)
        self.assertEqual(create_call[create_call.index('--success-url') + 1], 'http://127.0.0.1:58483/payment-return?result=success')
        self.assertEqual(create_call[create_call.index('--cancel-url') + 1], 'http://127.0.0.1:58483/payment-return?result=cancel')

        pay_plan = self.plan('trade.orders.pay', dict(orderUri='O1', payMethod=23))
        self.execute(pay_plan, 'resume-with-return')
        pay_call = next(call for call in self.calls if call[:3] == ['trade', 'orders', 'pay'])
        self.assertEqual(pay_call[pay_call.index('--success-url') + 1], 'http://127.0.0.1:58483/payment-return?result=success')
        self.assertEqual(pay_call[pay_call.index('--cancel-url') + 1], 'http://127.0.0.1:58483/payment-return?result=cancel')

    def test_pending_order_address_uses_owned_address_and_requires_an_explicit_matching_receipt(self):
        original = self.service.executor.runner
        state, seller, confirmed = 105, False, False
        def runner(argv):
            result = json.loads(original(argv))
            if argv[:3] == ['trade', 'orders', 'detail']:
                result['result'].update(isSeller=seller, stateDetail=dict(state=state))
            if argv[:3] == ['trade', 'orders', 'address']:
                result['result'] = dict(orderUri='O1', addressId=12, addressConfirmed=confirmed, state=110)
            return json.dumps(result).encode()
        self.service.executor.runner = runner
        params=dict(orderUri='O1',addressId=12)
        for state,seller in [(100,False),(110,False),(105,True)]:
            with self.assertRaises(WorkspaceError): self.plan('trade.orders.address',params)
        state,seller=105,False
        plan=self.plan('trade.orders.address',params)
        self.assertEqual(plan['summary']['address']['streetAddress'],'1 Main')
        self.assertEqual(self.execute(plan)['operation']['data']['status'],'reconcile_required')
        self.subject='another-buyer'; confirmed=True
        self.assertEqual(self.execute(self.plan('trade.orders.address',params),'address-confirmed')['operation']['data']['status'],'completed')

    def test_price_and_address_changes_require_a_new_confirmation(self):
        for change in ('price', 'address'):
            with self.subTest(change=change):
                plan = self.plan()
                if change == 'price':
                    self.preview['priceInfo']['totalPrice'] = '30.99'
                else:
                    self.address['streetAddress'] = '2 Other'
                with self.assertRaises(WorkspaceError) as failure:
                    self.execute(plan)
                self.assertEqual(failure.exception.code, 'stale_plan')
                self.assertEqual(self.writes(), [])

    def test_account_switch_cannot_execute_or_recover_another_accounts_order(self):
        plan = self.plan()
        self.subject = 'buyer-b'
        with self.assertRaises(WorkspaceError) as failure:
            self.execute(plan)
        self.assertEqual(failure.exception.code, 'account_changed')
        self.assertEqual(self.writes(), [])

    def test_unknown_result_blocks_duplicate_plans_and_recovers_only_original_task(self):
        self.unknown = True
        plan = self.plan()
        result = self.execute(plan)
        self.assertEqual(result['operation']['data']['status'], 'reconcile_required')
        with self.assertRaises(WorkspaceError):
            self.plan()
        recovered = self.call('recover', dict(operationId='confirm-1'))
        self.assertEqual(recovered['operation']['data']['status'], 'completed')
        self.assertEqual(recovered['result']['orderUri'], 'O1')
        self.assertEqual(len(self.writes()), 1)

    def test_definite_failure_allows_new_confirmation_without_automatic_resubmission(self):
        self.definite_failure = True
        result = self.execute(self.plan())
        self.assertEqual(result['operation']['data']['status'], 'failed')
        self.assertEqual(len(self.writes()), 1)
        self.definite_failure = False
        self.execute(self.plan(), 'confirm-2')
        self.assertEqual(len(self.writes()), 2)

    def test_failed_history_can_create_a_fresh_confirmation_but_unknown_or_other_account_cannot(self):
        self.definite_failure = True
        self.execute(self.plan())
        self.preview['priceInfo']['totalPrice']='25.99'
        plan=self.call('replan',dict(operationId='confirm-1'))
        self.assertEqual(plan['summary']['price']['totalPrice'],'25.99')
        self.assertEqual(len(self.writes()),1)
        self.subject='another-buyer'
        with self.assertRaises(WorkspaceError): self.call('replan',dict(operationId='confirm-1'))
        self.subject='buyer-a'; self.definite_failure=False; self.unknown=True
        self.execute(plan,'confirm-2')
        with self.assertRaises(WorkspaceError): self.call('replan',dict(operationId='confirm-2'))
        self.assertEqual(len(self.writes()),2)

    def test_recovery_rejects_mismatched_task_identity_endpoint_and_input(self):
        self.unknown = True
        self.execute(self.plan())
        original = self.service.executor.runner
        for change in ('id', 'operation', 'endpoint', 'input'):
            def runner(argv):
                value = json.loads(original(argv))
                if argv[:2] == ['task', 'get']:
                    if change in ('id', 'operation'):
                        value[change] = 'unrelated-task'
                    elif change == 'endpoint':
                        value['request']['apiBaseUrl'] = 'https://other.invalid'
                    else:
                        value['request']['input']['uri'] = 'another-goods'
                return json.dumps(value).encode()
            self.service.executor.runner = runner
            with self.subTest(change=change), self.assertRaises(WorkspaceError):
                self.call('recover', dict(operationId='confirm-1'))
            self.assertEqual(self.store.get_entity('operation', 'confirm-1')['data']['status'], 'reconcile_required')
        self.assertEqual(len(self.writes()), 1)

    def test_membership_failure_retains_original_request_and_version_for_explicit_resume(self):
        original = self.runner
        requests = []
        def checkout_runner(argv):
            if argv[:2] == ['memberships', 'checkout']:
                requests.append(list(argv))
                if len(requests) == 1:
                    return json.dumps(dict(id='member-task', status='failed', accountSubject=self.subject,
                        error=dict(code='DOWNSTREAM_UNAVAILABLE', reconciliationRequired=False))).encode()
            return original(argv)
        self.service.executor.runner = checkout_runner
        plan = self.plan('memberships.checkout', dict(sku='membership.year'))
        response = self.execute(plan)
        self.assertEqual(response['operation']['data']['status'], 'reconcile_required')
        with self.assertRaises(WorkspaceError):
            self.call('replan', {'operationId': 'confirm-1'})
        with self.assertRaises(WorkspaceError):
            self.plan('memberships.checkout', dict(sku='membership.year'))
        self.product['version'] = 2
        self.product['amount'] = 5999
        self.subject = 'other'
        with self.assertRaises(WorkspaceError):
            self.call('resume-membership', {'operationId': 'confirm-1'})
        self.subject = 'buyer-a'
        with self.assertRaises(WorkspaceError):
            self.call('resume-membership', {'operationId': 'confirm-1'}, 'host')
        resumed = self.call('resume-membership', {'operationId': 'confirm-1'})
        self.assertEqual(resumed['operation']['data']['status'], 'completed')
        flags = lambda argv: dict(zip(argv[2::2], argv[3::2]))
        self.assertEqual(flags(requests[0]), flags(requests[1]))
        self.assertEqual(requests[1][requests[1].index('--request-id') + 1], 'confirm-1')
        self.assertEqual(requests[1][requests[1].index('--version') + 1], '1')
        self.call('resume-membership', {'operationId': 'confirm-1'})
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(resumed['operation']['data']['calls']), 2)

    def test_legacy_failed_membership_cannot_start_a_second_purchase_intent(self):
        plan = self.plan('memberships.checkout', dict(sku='membership.year'))
        self.execute(plan)
        self.service.executor.update('confirm-1', status='failed')
        with self.assertRaisesRegex(WorkspaceError, '待核验'):
            self.plan('memberships.checkout', dict(sku='membership.year'))

    def test_membership_price_is_server_owned_and_request_id_survives_duplicate_confirmation(self):
        plan = self.plan('memberships.checkout', dict(sku='membership.year'))
        self.assertEqual(plan['summary']['product']['amount'], 3999)
        result = self.execute(plan)
        self.assertEqual(result['checkoutUrl'], 'https://pay.example/member')
        self.execute(plan)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0][-2:], ['--request-id', 'confirm-1'])
        with self.assertRaises(WorkspaceError):
            self.plan('memberships.checkout', dict(sku='membership.year', amount=1))

    def test_unknown_cancel_and_receipt_can_reconcile_the_exact_remote_order_without_replaying(self):
        for action, initial, terminal in [('trade.orders.cancel', 100, 150), ('trade.orders.receive', 120, 140)]:
            with self.subTest(action=action):
                remote = dict(state=initial, orderUri='O1', isSeller=False)
                task = dict(id='task-create', operation=action, accountSubject=self.subject, status='failed',
                    request=dict(apiBaseUrl='https://fixture.invalid', input=dict(orderUri='O1')),
                    error=dict(code='DOWNSTREAM_UNAVAILABLE', reconciliationRequired=True))
                def runner(argv):
                    if argv[:3] == action.split('.') or argv[:2] == ['task', 'get']:
                        self.calls.append(argv)
                        return json.dumps(task).encode()
                    result = json.loads(self.runner(argv))
                    if argv[:3] == ['trade', 'orders', 'detail']:
                        result['result'].update(payInfo=dict(orderUri=remote['orderUri']), isSeller=remote['isSeller'],
                                                stateDetail=dict(state=remote['state']))
                    return json.dumps(result).encode()
                self.service.executor.runner = runner
                command_id = action.rsplit('.', 1)[1] + '-unknown'
                operation = self.execute(self.plan(action, dict(orderUri='O1')), command_id)
                self.assertEqual(operation['operation']['data']['status'], 'reconcile_required')
                # 状态尚未到达、其他订单或卖家视角均不能解除买家操作的待核验。
                for change in [dict(state=initial), dict(state=terminal, orderUri='OTHER'),
                               dict(state=terminal, orderUri='O1', isSeller=True)]:
                    remote.update(change)
                    result = self.call('recover', dict(operationId=command_id))
                    self.assertEqual(result['operation']['data']['status'], 'reconcile_required')
                remote.update(state=terminal, orderUri='O1', isSeller=False)
                result = self.call('recover', dict(operationId=command_id))
                self.assertEqual(result['operation']['data']['status'], 'completed')
                self.assertEqual(result['result']['verifiedBy'], 'remote_order')
                self.assertEqual(result['result']['state'], terminal)
                self.assertEqual(sum(call[:3] == action.split('.') for call in self.calls), 1)

    def test_missing_payment_url_preserves_successful_order_for_resume(self):
        original = self.service.executor.runner
        def runner(argv):
            envelope = json.loads(original(argv))
            if argv[:3] == ['trade', 'orders', 'create']:
                envelope['result'] = dict(orderUri='O1')
            return json.dumps(envelope).encode()
        self.service.executor.runner = runner
        result = self.execute(self.plan())
        self.assertEqual(result['operation']['data']['status'], 'completed')
        self.assertIsNone(result['checkoutUrl'])
        self.assertEqual(result['result']['orderUri'], 'O1')
        resumed = self.execute(self.plan('trade.orders.pay', dict(orderUri='O1', payMethod=23)), 'resume-1')
        self.assertEqual(resumed['checkoutUrl'], 'https://pay.example/resume')
        self.assertEqual(len(self.writes()), 1)

    def test_web_boundary_rejects_arbitrary_commands_and_host_payment(self):
        for path, body, role in [
            ('query', dict(action='memberships.checkout', params={}), 'browser'),
            ('query', dict(action='shell', params={'command': 'touch /tmp/x'}), 'browser'),
            ('query', dict(action='trade.search', params={'unexpected': 1}), 'browser'),
            ('plan', dict(action='trade.orders.create', params={}), 'host'),
        ]:
            with self.subTest(path=path, action=body['action']), self.assertRaises(WorkspaceError):
                self.call(path, body, role)
        self.assertEqual(self.writes(), [])

    def test_history_is_scoped_to_the_logged_in_account(self):
        self.execute(self.plan())
        self.assertEqual(len(self.call('history', {})['operations']), 1)
        self.subject = 'buyer-b'
        self.assertEqual(self.call('history', {})['operations'], [])

    def test_cancellation_requires_a_closed_order_receipt_not_a_legacy_success_ack(self):
        original = self.service.executor.runner
        closed = False
        def runner(argv):
            result = json.loads(original(argv))
            if argv[:3] == ['trade', 'orders', 'cancel']:
                result['result'] = dict(orderUri='O1', state=150) if closed else dict(ret='success')
            return json.dumps(result).encode()
        self.service.executor.runner = runner
        plan = self.plan('trade.orders.cancel', dict(orderUri='O1'))
        first = self.execute(plan)
        self.assertEqual(first['operation']['data']['status'], 'reconcile_required')
        # 未知请求必须核验，不能换 commandId 绕过；另一用户的明确关闭回执另行验证。
        self.subject = 'buyer-b'
        closed = True
        result = self.execute(self.plan('trade.orders.cancel', dict(orderUri='O1')), 'cancel-confirmed')
        self.assertEqual(result['operation']['data']['status'], 'completed')
        self.assertEqual(result['result']['state'], 150)

    def test_free_trial_uses_the_same_confirmed_cli_flow_without_a_payment_link(self):
        self.product.update(amount=0, eligible=True, entitlementSpec=dict(durationUnit='day', durationCount=3, offerType='trial'))
        original = self.service.executor.runner
        def runner(argv):
            result = json.loads(original(argv))
            if argv[:2] == ['memberships', 'checkout']:
                result['result'].update(paymentState='paid', fulfillmentState='granted', paymentRequired=False)
                result['result'].pop('paymentParameters')
            return json.dumps(result).encode()
        self.service.executor.runner = runner
        plan = self.plan('memberships.checkout', dict(sku='membership.year'))
        self.assertEqual(plan['label'], '领取会员试用')
        response = self.execute(plan)
        self.assertEqual(response['operation']['data']['status'], 'completed')
        self.assertEqual(response['result']['fulfillmentState'], 'granted')
        self.assertIsNone(response['checkoutUrl'])
        self.assertIsNone(response['paymentError'])
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('--amount', self.writes()[0])

    def test_offer_without_confirmed_eligibility_cannot_be_claimed(self):
        self.product.update(entitlementSpec=dict(durationUnit='month', durationCount=1, offerType='introductory'))
        for eligible in (None, False):
            if eligible is None:
                self.product.pop('eligible', None)
            else:
                self.product['eligible'] = eligible
            with self.subTest(eligible=eligible), self.assertRaises(WorkspaceError):
                self.plan('memberships.checkout', dict(sku='membership.year'))
        self.assertEqual(self.writes(), [])

    def test_withdrawal_converts_the_confirmed_dollars_to_integer_cents(self):
        plan = self.plan('trade.seller.withdraw', dict(paypalName='Ada', paypalEmail='ada@example.com', money='10.25'))
        self.assertEqual(plan['summary']['changes']['money'], '10.25')
        self.execute(plan)
        argv = next(call for call in self.calls if call[:3] == ['trade', 'seller', 'withdraw'])
        self.assertEqual(argv[argv.index('--money') + 1], '1025')

    def test_seller_pending_delivery_cannot_be_bypassed_by_direct_plan_requests(self):
        original = self.service.executor.runner
        def runner(argv):
            envelope = json.loads(original(argv))
            if argv[:3] == ['trade', 'seller', 'eligibility']:
                envelope['result'] = dict(waitDeliveryOrderUri='delivery-1')
            return json.dumps(envelope).encode()
        self.service.executor.runner = runner
        with self.assertRaises(WorkspaceError) as failure:
            self.plan('trade.seller.goods.create', dict(title='Morgan', category=10, salePrice=10, postage=0,
                                                      imgs=['https://cdn.example/front.png']))
        self.assertEqual(failure.exception.code, 'seller_delivery_pending')

    def test_local_photos_can_be_staged_previewed_and_uploaded_without_a_collection_task(self):
        image = b'\x89PNG\r\n\x1a\nfixture-image'
        media = self.service.commerce.stage_file('front.png', image, 'user:web')
        self.assertEqual(self.service.commerce.media(media['id']), (image, 'image/png'))
        self.assertFalse(any(call[:2] == ['file', 'upload'] for call in self.calls))
        result = self.execute(self.plan('file.upload', {'mediaId': media['id']}))
        self.assertEqual(result['result']['fileUrl'], 'https://cdn.example/upload.png')
        self.execute(self.plan('trade.seller.goods.create', dict(title='Morgan', category=10,
                     imgs=[result['result']['fileUrl']], salePrice=19.99, postage=1.00)), 'publish-1')
        self.assertTrue(any(call[:4] == ['trade', 'seller', 'goods', 'create'] for call in self.calls))
        self.subject = 'another-user'
        with self.assertRaises(WorkspaceError):
            self.service.commerce.media(media['id'])

    def test_image_staging_rejects_html_and_arbitrary_filesystem_paths(self):
        with self.assertRaises(WorkspaceError):
            self.service.commerce.stage_file('front.png', b'<script>alert(1)</script>', 'user:web')
        with self.assertRaises(WorkspaceError):
            self.plan('file.upload', {'file': '/etc/passwd'})


if __name__ == '__main__':
    unittest.main()
