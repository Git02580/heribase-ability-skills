"""工作台交易／会员适配：有限意图 → 服务端预览 → 本地确认 → 可核验 CLI 调用。

商品、金额和账户状态始终由 CLI 查询；浏览器不能指定命令、路径或支付金额。
写入沿用 operation/operation-call 审计。未知结果核对原 CLI 任务及原订单，绝不重放写入。
"""
import json
import re
import secrets
import hashlib
import os
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from workspace_business import WorkspaceBusiness
from workspace_executor import digest, result_value
from workspace_store import WorkspaceError, identifier, safe_json


PAGING = 'page pageNum'
# 每个意图明确登记参数范围。此接口并非通用 CLI 或 HTTP 代理。
QUERIES = {
    'trade.search': ('', PAGING + ' keyword area secCategory order minPrice maxPrice'),
    'trade.categories': ('', ''),
    'trade.goods.detail': ('uri', ''),
    'trade.favorites.list': ('', PAGING),
    'trade.seller.eligibility': ('', ''),
    'trade.seller.goods.list': ('type', PAGING + ' keyword'),
    'trade.seller.goods.detail': ('uri', ''),
    'trade.seller.identification': ('identUri', ''),
    'trade.seller.appraisal': ('appraiseUri', ''),
    'trade.addresses.countries': ('', 'scene'),
    'trade.addresses.list': ('', PAGING),
    'trade.addresses.detail': ('id', ''),
    'trade.orders.preview': ('uri', 'addressId'),
    'trade.orders.detail': ('orderUri', ''),
    'trade.orders.status': ('orderUri', ''),
    'trade.orders.buy': ('', PAGING + ' stateType'),
    'trade.orders.sell': ('', PAGING + ' stateType'),
    'trade.orders.delivery-options': ('', ''),
    'trade.orders.logistics': ('orderUri', ''),
    'trade.orders.feedback': ('orderUri', ''),
    'trade.seller.account': ('', ''),
    'trade.seller.bills': ('', PAGING),
    'trade.seller.bill': ('id', ''),
    'trade.seller.withdrawal-info': ('', ''),
    'trade.shop.info': ('shopUri', ''),
    'trade.shop.goods': ('shopUri', PAGING),
    'subscriptions.current': ('', ''),
    'memberships.products': ('', ''),
    'memberships.purchases.detail': ('uri', 'refresh'),
    'purchases.list': ('', 'page pageSize'),
    'purchases.entitlements': ('', ''),
}
ADDRESS = 'streetAddress postalCode addressState city phoneNumber phoneCountryCode countryCode'
ADDRESS_OPTIONAL = 'firstName lastName fullName additionalAddressInfo'
GOODS = 'title category imgs salePrice postage'
GOODS_OPTIONAL = 'description isGlobalShipping globalPostage collectUri identUri appraiseUri'
ACTIONS = {
    'file.upload': ('上传交易照片', 'mediaId', ''),
    'trade.favorites.add': ('关注商品', 'uri', ''),
    'trade.favorites.remove': ('取消关注商品', 'uri', ''),
    'trade.addresses.add': ('新增收货地址', ADDRESS, ADDRESS_OPTIONAL),
    'trade.addresses.update': ('修改收货地址', 'id ' + ADDRESS, ADDRESS_OPTIONAL),
    'trade.addresses.delete': ('删除收货地址', 'id', ''),
    'trade.addresses.default': ('设为默认地址', 'id', ''),
    # version 由预下单产生；不接受客户端的价格和商品版本。
    'trade.orders.create': ('购买商品', 'uri addressId payMethod', ''),
    'trade.orders.pay': ('继续支付交易订单', 'orderUri payMethod', ''),
    'trade.orders.cancel': ('取消未付款订单', 'orderUri', ''),
    'trade.orders.address': ('确认订单地址', 'orderUri addressId', ''),
    'trade.orders.deliver': ('确认发货', 'orderUri type deliveryCertificateImgs', 'logisticsCompany logisticsTrackingNumber email'),
    'trade.orders.receive': ('确认收货', 'orderUri', ''),
    'trade.orders.feedback-add': ('提交订单反馈', 'orderUri content', 'imgs'),
    'trade.seller.goods.create': ('发布商品', GOODS, GOODS_OPTIONAL),
    'trade.seller.goods.update': ('编辑商品', 'uri ' + GOODS, GOODS_OPTIONAL),
    'trade.seller.goods.up': ('上架商品', 'uri', ''),
    'trade.seller.goods.down': ('下架商品', 'uri', ''),
    'trade.seller.goods.delete': ('删除商品', 'uri', ''),
    'trade.seller.paypal': ('保存收款账户', 'paypalName paypalEmail', ''),
    'trade.seller.withdraw': ('申请提现', 'paypalName paypalEmail money', ''),
    'memberships.checkout': ('购买会员', 'sku', ''),
    'memberships.purchases.pay': ('继续支付会员订单', 'uri', ''),
}


def parameters(value, required, optional):
    required, optional = set(required.split()), set(optional.split())
    if not isinstance(value, dict) or required - value.keys() or value.keys() - required - optional:
        raise WorkspaceError('invalid_request', '请求字段缺失或包含未允许字段')
    for key, content in value.items():
        values = content if isinstance(content, list) else [content]
        if isinstance(content, list) and (key not in {'imgs', 'deliveryCertificateImgs'} or not 1 <= len(content) <= 9):
            raise WorkspaceError('invalid_request', '图片数量应为 1–9 张')
        for item in values:
            if type(item) not in (str, int, float) or len(str(item)) > 5000 or str(item).startswith('--'):
                raise WorkspaceError('invalid_request', '参数值无效')
    return dict(value)


def command(action, params):
    argv = action.split('.')
    for key, value in params.items():
        flag = '--' + re.sub(r'[A-Z]', lambda m: '-' + m[0].lower(), key)
        for item in value if isinstance(value, list) else [value]:
            argv.extend([flag, str(item)])
    return argv


class WorkspaceCommerce:
    def __init__(self, store, executor):
        self.store, self.executor = store, executor
        self.payment_return_base_url = None

    def set_payment_return_base_url(self, value):
        """由监听服务注入本次随机端口的 loopback 回流地址，不接受网页输入。"""
        parsed = urlparse(value or '')
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port:
            raise WorkspaceError('invalid_payment_return_url', '本地工作台回流地址无效')
        self.payment_return_base_url = 'http://127.0.0.1:' + str(parsed.port)

    def _payment_return_params(self, action, params):
        """把本机回流地址仅附加到创建/继续支付命令，绝不来自浏览器业务参数。"""
        if action not in {'trade.orders.create', 'trade.orders.pay'} or not self.payment_return_base_url:
            return params
        return {
            **params,
            'successUrl': self.payment_return_base_url + '/payment-return?result=success',
            'cancelUrl': self.payment_return_base_url + '/payment-return?result=cancel',
        }

    def _account(self, expected):
        if self.executor.account() != expected:
            raise WorkspaceError('account_changed', '账户或服务地址已变化，请重新查询并确认', 409)

    def _media_directory(self):
        directory = self.store.directory / 'commerce-media'
        if directory.is_symlink():
            raise WorkspaceError('unsafe_path', '图片目录不能是符号链接')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return directory

    def stage_file(self, name, content, actor):
        """先在本机暂存；只接收实际图片文件头，随后上传仍通过受审计的 CLI 执行。"""
        if not isinstance(name, str) or not name or len(name) > 255 or not 0 < len(content) <= 20 * 1024 * 1024:
            raise WorkspaceError('invalid_upload', '图片名称无效或文件超过 20 MiB')
        if content.startswith(b'\x89PNG\r\n\x1a\n'):
            suffix, mime = 'png', 'image/png'
        elif content.startswith(b'\xff\xd8\xff'):
            suffix, mime = 'jpg', 'image/jpeg'
        elif content.startswith(b'RIFF') and content[8:12] == b'WEBP':
            suffix, mime = 'webp', 'image/webp'
        else:
            raise WorkspaceError('invalid_image', '请选择 JPG、PNG 或 WebP 图片')
        account = self.executor.account()
        media_id = 'media-' + secrets.token_hex(12)
        path = self._media_directory() / (media_id + '.' + suffix)
        data = {'name': Path(name).name, 'suffix': suffix, 'mime': mime, 'account': account,
                'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content), 'status': 'local'}
        try:
            with path.open('xb') as handle:
                os.chmod(path, 0o600)
                handle.write(content)
            self.store.save_entity('commerce-media', media_id, data, 0, actor)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {'id': media_id, 'name': data['name'], 'mime': mime, 'bytes': len(content)}

    def _media(self, media_id):
        record = self.store.get_entity('commerce-media', identifier(media_id))
        if not record:
            raise WorkspaceError('media_not_found', '图片未找到，请重新选择', 404)
        self._account(record['data']['account'])
        suffix = record['data']['suffix']
        if suffix not in {'png', 'jpg', 'webp'}:
            raise WorkspaceError('invalid_image', '图片类型无效')
        path = self._media_directory() / (media_id + '.' + suffix)
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record['data']['sha256']:
            raise WorkspaceError('media_changed', '暂存图片已变化，请重新选择', 409)
        return record, path

    def media(self, media_id):
        record, path = self._media(media_id)
        return path.read_bytes(), record['data']['mime']

    def query(self, action, params):
        if action not in QUERIES:
            raise WorkspaceError('invalid_action', '不支持该查询')
        params = parameters(params, *QUERIES[action])
        account = self.executor.account()
        result = self.executor.query(command(action, params))
        self._account(account)
        return result

    def history(self):
        account = self.executor.account()
        return {'operations': [entry for entry in self.store.list_entities('operation')
                               if entry['data'].get('kind') == 'commerce' and entry['data'].get('account') == account]}

    @staticmethod
    def _target(action, params):
        # 同一商品的未知下单不能用新确认 ID 绕过；同一会员 SKU 也必须先核验。
        return [action, params.get('orderUri') or params.get('uri') or params.get('sku') or params.get('id') or digest(params)]

    def _assert_idle(self, action, params, account):
        target = self._target(action, params)
        for entry in self.store.list_entities('operation'):
            data = entry['data']
            if (data.get('kind') == 'commerce' and data.get('account') == account
                    and (data.get('status') in {'running', 'queued', 'reconcile_required'}
                         or (data.get('action') == 'memberships.checkout' and data.get('status') == 'failed'))
                    and data.get('target') == target):
                raise WorkspaceError('operation_pending', '该对象仍有执行中或待核验操作，请先检查原执行记录', 409, operationId=entry['id'])

    def _context(self, action, params):
        """生成用户可核对的摘要，并在执行前重读；易变化的查询时间不进入确认哈希。"""
        argv_params = dict(params)
        if action == 'file.upload':
            record, path = self._media(params['mediaId'])
            return {'file': str(path)}, {'mediaId': record['id'], 'name': record['data']['name'], 'sha256': record['data']['sha256']}
        if action == 'trade.orders.create':
            preview = self.query('trade.orders.preview', {'uri': params['uri'], 'addressId': params['addressId']})
            goods, price = preview.get('goodsInfo', {}), preview.get('priceInfo', {})
            if goods.get('uri') != params['uri'] or goods.get('saleState') != 1 or type(goods.get('version')) is not int:
                raise WorkspaceError('goods_unavailable', '商品已不可购买，请刷新商品详情', 409)
            # 当前交易实现拒绝 PayPal(24)；网页选择银行卡通道(23)，仍由 Wpt 创建支付。
            if params['payMethod'] != 23 or not any(method.get('code') == 23 for method in preview.get('payMethod', [])):
                raise WorkspaceError('payment_unavailable', '此订单暂未提供可用的网页支付方式', 409)
            if not all(key in price for key in ('salePrice', 'postage', 'totalPrice')):
                raise WorkspaceError('price_unavailable', '服务没有返回完整金额，请刷新后重试', 409)
            address = self.query('trade.addresses.detail', {'id': str(params['addressId'])}).get('detail', {})
            if str(address.get('id')) != str(params['addressId']):
                raise WorkspaceError('address_unavailable', '收货地址不匹配，请重新选择', 409)
            argv_params['version'] = goods['version']
            return argv_params, {'goods': goods, 'price': price, 'address': address, 'paymentMethod': 'wpt_center'}
        if action == 'memberships.checkout':
            catalog = self.query('memberships.products', {})
            product = next((p for p in catalog.get('products', []) if p.get('sku') == params['sku']), None)
            if (not product or product.get('productType') != 'membership' or catalog.get('paymentChannel') != 'wpt_pay_center'
                    or type(product.get('version')) is not int or product.get('eligible') is False
                    or (product.get('entitlementSpec', {}).get('offerType', 'standard') != 'standard' and product.get('eligible') is not True)):
                raise WorkspaceError('product_unavailable', '该会员商品暂不可购买，请重新选择', 409)
            argv_params['version'] = product['version']
            return argv_params, {'product': product, 'paymentMethod': 'wpt_center', 'autoRenew': False}
        if action.startswith('trade.orders.'):
            detail = self.query('trade.orders.detail', {'orderUri': params['orderUri']})
            # 只绑定业务状态，不绑定倒计时等随每次查询变化的展示字段。
            state = detail.get('stateDetail', {}).get('state')
            seller = detail.get('isSeller')
            if type(seller) is not bool or type(state) is not int:
                raise WorkspaceError('order_unverified', '订单身份或状态不完整，请刷新后重试', 409)
            if ((action.endswith('.pay') and (seller or state != 100 or params['payMethod'] != 23))
                    or (action.endswith('.cancel') and (seller or state != 100))
                    or (action.endswith('.address') and (seller or state != 105))
                    or (action.endswith('.receive') and (seller or state != 120))
                    or (action.endswith('.deliver') and (not seller or not detail.get('stateDetail', {}).get('canShip')))):
                raise WorkspaceError('order_action_unavailable', '当前身份或订单状态不支持此操作', 409)
            summary = {'orderUri': params['orderUri'], 'goods': detail.get('goodsInfo'),
                       'orderState': state, 'isSeller': seller, 'changes': params}
            if action.endswith('.address'):
                # 失败的地址同步必须继续已冻结快照，不能从后来编辑的地址簿换取新内容。
                address = detail.get('address') or self.query('trade.addresses.detail', {'id': str(params['addressId'])}).get('detail', {})
                if str(address.get('id')) != str(params['addressId']):
                    raise WorkspaceError('address_unavailable', '订单已选择其他地址或地址不匹配，请刷新后继续原地址', 409)
                summary['address'] = address
            return argv_params, summary
        if action == 'memberships.purchases.pay':
            detail = self.query('memberships.purchases.detail', {'uri': params['uri'], 'refresh': 1})
            if detail.get('paymentState') != 'unpaid':
                raise WorkspaceError('order_not_payable', '该订单已付款或不再待支付，请刷新订单状态', 409)
            return argv_params, {'product': detail.get('product'), 'uri': params['uri'], 'amount': detail.get('amount'),
                                 'currency': detail.get('currency'), 'currencyExponent': detail.get('currencyExponent')}
        if action.startswith('trade.seller.goods.'):
            if action.endswith('.create'):
                original = self.query('trade.seller.eligibility', {})
                if original.get('waitDeliveryOrderUri'):
                    raise WorkspaceError('seller_delivery_pending', '请先处理待发货订单，再发布新商品', 409,
                                         orderUri=original['waitDeliveryOrderUri'])
            else:
                original = self.query('trade.seller.goods.detail', {'uri': params['uri']})
            return argv_params, {'current': original, 'changes': params}
        if action.startswith('trade.addresses.') and 'id' in params:
            return argv_params, {'current': self.query('trade.addresses.detail', {'id': params['id']}).get('detail', {}), 'changes': params}
        if action == 'trade.seller.withdraw':
            account = self.query('trade.seller.withdrawal-info', {})
            if not re.fullmatch(r'\d+(\.\d{1,2})?', str(params['money'])):
                raise WorkspaceError('invalid_amount', '提现金额应为最多两位小数的美元金额')
            amount = Decimal(str(params['money']))
            if not Decimal(str(account['minMoney'])) <= amount <= Decimal(str(account['maxMoney'])):
                raise WorkspaceError('invalid_amount', '提现金额超出当前可提现范围', 409)
            # 网页以美元确认，存量 CLI/API 的 money 却是整数美分；用 Decimal 避免浮点误差。
            argv_params['money'] = int(amount * 100)
            return argv_params, {'account': account, 'changes': params}
        return argv_params, {'changes': params}

    def plan(self, action, params, actor):
        if action not in ACTIONS:
            raise WorkspaceError('invalid_action', '不支持该操作')
        label, required, optional = ACTIONS[action]
        params = parameters(params, required, optional)
        account = self.executor.account()
        self._assert_idle(action, params, account)
        argv_params, summary = self._context(action, params)
        self._account(account)
        if action == 'memberships.checkout' and summary['product'].get('entitlementSpec', {}).get('offerType') == 'trial':
            label = '领取会员试用'
        data = {'action': action, 'params': params, 'argvParams': argv_params, 'summary': summary,
                'account': account, 'label': label, 'status': 'awaiting_confirmation'}
        data['hash'] = digest(data)
        data['id'] = 'commerce-' + secrets.token_hex(12)
        self.store.save_entity('commerce-plan', data['id'], data, 0, actor)
        return data

    def execute(self, body, actor):
        identifier(body['commandId'])
        with self.executor.lock:
            record = self.store.get_entity('commerce-plan', body['planId'])
            if not record:
                raise WorkspaceError('plan_not_found', '确认单不存在，请重新检查范围', 404)
            plan = record['data']
            self._account(plan['account'])
            request_hash = digest(body)
            existing = self.store.get_entity('operation', body['commandId'])
            if existing:
                if existing['data'].get('kind') != 'commerce' or existing['data'].get('requestHash') != request_hash:
                    raise WorkspaceError('command_conflict', '该请求 ID 已用于另一项操作', 409)
                return self._response(existing)
            if plan['hash'] != body['planHash'] or plan['status'] != 'awaiting_confirmation':
                raise WorkspaceError('stale_plan', '确认范围已变化或已执行，请重新检查', 409)
            self._assert_idle(plan['action'], plan['params'], plan['account'])
            argv_params, summary = self._context(plan['action'], plan['params'])
            if digest([argv_params, summary]) != digest([plan['argvParams'], plan['summary']]):
                raise WorkspaceError('stale_plan', '商品、价格、地址或订单状态已变化，请重新确认', 409)
            self._account(plan['account'])
            if plan['action'] == 'memberships.checkout':
                argv_params['requestId'] = body['commandId']
            # 先持久化授权范围，后发 CLI。即使网页断线，同一个确认请求也不会重新执行。
            operation = self.store.save_entity('operation', body['commandId'], {
                'kind': 'commerce', 'action': plan['action'], 'label': plan['label'], 'request': body,
                'requestHash': request_hash, 'account': plan['account'], 'status': 'running',
                'scope': summary, 'params': argv_params, 'intentParams': plan['params'], 'target': self._target(plan['action'], plan['params']),
                'actor': actor, 'calls': [], 'itemResults': [], 'message': '正在执行已确认范围',
            }, 0, actor)
            self.store.save_entity('commerce-plan', record['id'], {**plan, 'status': 'consumed'}, record['revision'], actor)
            try:
                cli_params = self._payment_return_params(plan['action'], argv_params)
                _, _, result = self.executor._invoke(operation['id'], command(plan['action'], cli_params))
                return self._complete(operation['id'], result)
            except Exception as exc:
                return self._failed(operation['id'], exc)

    def replan(self, operation_id, actor):
        """明确失败只能生成新的确认单；重新读取价格／状态，不直接重发旧命令。"""
        operation = self.store.get_entity('operation', identifier(operation_id))
        if not operation or operation['data'].get('kind') != 'commerce':
            raise WorkspaceError('operation_not_found', '未找到交易执行记录', 404)
        data = operation['data']
        self._account(data['account'])
        if data['status'] != 'failed' or data['action'] == 'memberships.checkout':
            raise WorkspaceError('reconciliation_required', '只有明确失败的操作可重新确认；未知结果请先核验原任务', 409)
        action = data['action']
        _, required, optional = ACTIONS[action]
        allowed = set((required + ' ' + optional).split())
        # 兼容旧记录，只取原用户意图字段；version/requestId 等执行参数必须重新生成。
        params = data.get('intentParams') or {key: value for key, value in data['params'].items() if key in allowed}
        return self.plan(action, params, actor)

    def resume_membership(self, operation_id, actor):
        """用户确认后继续原购买意图；仅用于有后端 requestId 唯一约束的会员下单。

        不能改 SKU、版本或 requestId；不复用通用 replan，以免下单后的支付故障
        被误当作未落单。每次继续仍归档为同一操作的独立调用证据。
        """
        with self.executor.lock:
            operation = self.store.get_entity('operation', identifier(operation_id))
            if not operation or operation['data'].get('kind') != 'commerce':
                raise WorkspaceError('operation_not_found', '未找到原会员购买记录', 404)
            data = operation['data']
            self._account(data['account'])
            if data['action'] != 'memberships.checkout':
                raise WorkspaceError('invalid_action', '此继续入口仅适用于原会员购买请求', 409)
            if data['status'] == 'completed':
                return self._response(operation)
            if data['status'] not in {'failed', 'reconcile_required'}:
                raise WorkspaceError('operation_pending', '原请求仍在执行，请先核验任务状态', 409)
            params = dict(data['params'])
            # 旧版本在归档 params 后才添加 requestId；当时也固定使用 operationId。
            params.setdefault('requestId', operation_id)
            if set(params) != {'sku', 'version', 'requestId'} or params['requestId'] != operation_id:
                raise WorkspaceError('unmatched_call', '原会员请求证据不完整，不能继续提交', 409)
            attempt = max((call.get('attempt', 1) for call in data.get('calls', [])), default=0) + 1
            self.executor.update(operation_id, status='running', params=params, resumedBy=actor,
                                 message='正在继续原会员请求，沿用原商品版本与请求编号')
            try:
                _, _, result = self.executor._invoke(operation_id, command(data['action'], params), attempt)
                return self._complete(operation_id, result)
            except Exception as exc:
                return self._failed(operation_id, exc)

    def _failed(self, operation_id, exc):
        data = self.store.get_entity('operation', operation_id)['data']
        # checkout 的可重试只表示“同 requestId 幂等”，不表示后端没有建单。
        # 即使 CLI 返回 failed，支付网关也可能在购买单持久化后才失败。
        membership = data['action'] == 'memberships.checkout'
        definite = not membership and isinstance(exc, WorkspaceError) and exc.code in {'cli_definite_failure', 'cli_retryable_failure'}
        message = ('原会员购买结果待核验；可继续原请求，沿用原商品版本与请求编号，避免重复建单' if membership
                   else str(exc) if isinstance(exc, WorkspaceError) else '执行结果未知，请核验原 CLI 任务；未重复提交')
        operation = self.executor.update(operation_id, status='failed' if definite else 'reconcile_required', message=message)
        return self._response(operation)

    def _complete(self, operation_id, result):
        result = result if isinstance(result, dict) else {'value': result}
        operation_data = self.store.get_entity('operation', operation_id)['data']
        action = operation_data['action']
        if action == 'trade.orders.address':
            if (result.get('orderUri') != operation_data['params']['orderUri']
                    or result.get('addressId') != operation_data['params']['addressId']
                    or result.get('addressConfirmed') is not True):
                raise WorkspaceError('receipt_incomplete', '尚未确认原订单地址同步完成，请核验原任务', 409)
        if action == 'trade.orders.cancel':
            # 老接口仅上报取消支付日志，也返回 success。必须核对同一订单的明确
            # 关闭回执，才能告诉买家已经取消，避免订单仍可支付却被显示为已关闭。
            if result.get('orderUri') != operation_data['params']['orderUri'] or result.get('state') != 150:
                raise WorkspaceError('receipt_incomplete', '未确认订单已关闭，请核验原任务与订单状态', 409)
        if action == 'file.upload':
            parsed = urlparse(result.get('fileUrl', ''))
            if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
                raise WorkspaceError('upload_unverified', '上传未返回有效图片地址，请核验原任务', 409)
            media_id = self.store.get_entity('operation', operation_id)['data']['scope']['mediaId']
            record = self.store.get_entity('commerce-media', media_id)
            self.store.save_entity('commerce-media', media_id, {**record['data'], 'fileUrl': result['fileUrl'], 'status': 'uploaded'}, record['revision'], 'system:executor')
        receipt_key = {'trade.orders.create': 'orderUri', 'memberships.checkout': 'uri'}.get(action)
        if receipt_key and not isinstance(result.get(receipt_key), str):
            raise WorkspaceError('receipt_incomplete', '服务未返回订单编号，请核验原任务；不能重复创建订单', 409)
        checkout_url, payment_error = None, None
        if action in {'trade.orders.create', 'trade.orders.pay', 'memberships.checkout', 'memberships.purchases.pay'}:
            if result.get('paymentState') != 'paid':
                try:
                    checkout_url = WorkspaceBusiness.checkout_url({'paymentParameters': result.get('paymentParameters', result)})
                except WorkspaceError as exc:
                    payment_error = str(exc)
        # 支付签名仅留在受保护的原始 CLI 证据中，页面历史保存订单标识和业务结果。
        saved_result = {key: value for key, value in result.items() if key not in {'paymentParameters', 'data', 'payInfo', 'checkoutUrl', 'paymentUrl'}}
        operation = self.executor.update(operation_id, status='completed', result=saved_result, message='已完成本次操作；支付及权益状态以查单为准')
        return {**self._response(operation), 'result': result, 'checkoutUrl': checkout_url, 'paymentError': payment_error}

    @staticmethod
    def _response(operation):
        return {'operation': operation, 'result': operation['data'].get('result'), 'checkoutUrl': None}

    def _verify_order_outcome(self, operation):
        """CLI 网络中断后，只读核验具有明确终态的原订单操作。

        不根据“最新订单”推测结果，也不把未变化状态判作失败。下单、发货等
        没有唯一终态证据的动作继续保留待核验，不能借此重复写入或创建新单。
        """
        data = operation['data']
        expected = {'trade.orders.cancel': 150, 'trade.orders.receive': 140}.get(data['action'])
        if expected is None:
            return None
        order_uri = data['params']['orderUri']
        detail = self.query('trade.orders.detail', {'orderUri': order_uri})
        self._account(data['account'])
        if (detail.get('payInfo', {}).get('orderUri') != order_uri or detail.get('isSeller') is not False
                or detail.get('stateDetail', {}).get('state') != expected):
            return None
        response = self._complete(operation['id'], {'orderUri': order_uri, 'state': expected,
                                  'verifiedBy': 'remote_order', 'verifiedAt': self.store.timestamp()})
        outcome = '已关闭' if expected == 150 else '已完成收货'
        response['operation'] = self.executor.update(operation['id'], message=f'已只读核验原订单{outcome}；未重复提交操作')
        return response

    def recover(self, operation_id):
        with self.executor.lock:
            operation = self.store.get_entity('operation', operation_id)
            if not operation or operation['data'].get('kind') != 'commerce':
                raise WorkspaceError('operation_not_found', '未找到交易执行记录', 404)
            self._account(operation['data']['account'])
            if operation['data']['status'] in {'completed', 'failed'}:
                return self._response(operation)
            calls = operation['data'].get('calls', [])
            if not calls or not calls[-1].get('cliTaskId'):
                raise WorkspaceError('unmatched_call', '原请求未返回任务编号，请在执行记录中核对 CLI 任务与远端订单；不能自动重试', 409)
            call = calls[-1]
            # 精确查询已经记录的任务 ID，不能凭最新订单／商品名猜测执行结果。
            raw = self.executor.runner(['task', 'get', call['cliTaskId']])
            envelope = json.loads(raw)
            safe_json(envelope)
            self._account(operation['data']['account'])
            task_subject = envelope.get('accountSubject')
            if task_subject is not None and task_subject != operation['data']['account']['subject']:
                raise WorkspaceError('account_changed', 'CLI 结果账户与确认账户不符', 409)
            if task_subject is None and envelope.get('status') not in {'failed', 'interrupted', 'cancelled'}:
                # 旧版 CLI 只给成功任务写入 accountSubject。失败任务可以继续核对
                # 精确任务 ID 和原始请求以展示失败原因，但不能把无账户凭证的成功
                # 结果归入当前操作。
                raise WorkspaceError('account_unverified', '原 CLI 任务未记录执行账户，无法确认成功结果归属', 409)
            saved = self.store.get_entity('operation-call', call['id'])
            original = json.loads(saved['data']['stdout']) if saved else {}
            request = envelope.get('request') or {}
            # 同账户中也可能有多个相同业务任务。恢复必须同时匹配任务编号、操作、
            # 服务地址和原始输入；缺少旧证据时保留待核验，不能把另一笔订单归入本次。
            if (envelope.get('id') != call['cliTaskId'] or envelope.get('operation') != operation['data']['action']
                    or request.get('apiBaseUrl') != operation['data']['account']['apiBaseUrl']
                    or not isinstance(request.get('input'), dict)
                    or request != original.get('request')):
                raise WorkspaceError('unmatched_call', 'CLI 任务与原始请求不匹配，请核对执行证据；未重放操作', 409)
            self.store.save_entity('operation-call', call['id'], {'operationId': operation_id, 'argv': call['argv'], 'stdout': raw.decode()},
                                   saved['revision'] if saved else 0, 'system:executor')
            call.update(status=envelope.get('status', 'unknown'), observedAt=self.store.timestamp())
            self.executor.update(operation_id, calls=calls)
            try:
                _, result = result_value(raw)
                return self._complete(operation_id, result)
            except WorkspaceError as exc:
                # 原任务已经结束、但缺少成功回执时，再核对同一个订单的业务终态。
                # 明确拒绝及仍在运行的任务不走这条恢复路径。
                if exc.code in {'cli_not_completed', 'receipt_incomplete'} and envelope.get('status') in {'failed', 'interrupted', 'cancelled', 'completed'}:
                    verified = self._verify_order_outcome(operation)
                    if verified:
                        return verified
                return self._failed(operation_id, exc)
