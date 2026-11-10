"""鉴定与追踪复用工作空间的草稿、确认和执行记录，不引入第二套运行时。"""

import secrets
import re
from urllib.parse import urlparse
from workspace_executor import digest
from workspace_store import WorkspaceError, identifier, safe_json
from workspace_tasks import operations


class WorkspaceBusiness:
    def __init__(self, store, tasks, executor):
        self.store, self.tasks, self.executor = store, tasks, executor

    @staticmethod
    def appraisal_cli_result(result, operation):
        """取 CLI task 中对应鉴定业务的实际回执；旧版扁平回执继续兼容。"""

        if isinstance(result, dict) and result.get('operation') == operation and isinstance(result.get('result'), dict):
            return result['result']
        return result

    def item(self, key, revision, local_id):
        task = self.tasks._checked(key, revision)
        item = next((i for i in task['items'] if i['local_id'] == local_id), None)
        if not item:
            raise WorkspaceError('item_not_found', '未找到对应藏品', 404)
        return task, item

    @staticmethod
    def appraisal_experts(raw):
        """把 CLI 的专家目录投影为工作台可直接展示的服务卡片。

        服务端保留 appraiserType/appraiserId 作为提交参数，但浏览器只应看到专家和
        服务信息。这里不猜测 SKU 或收费规则，只展示 experts 接口实际返回的字段。
        """

        if not isinstance(raw, dict):
            raise WorkspaceError('invalid_experts', 'CLI 返回的鉴定服务目录格式无效', 502)
        entries = []
        official = raw.get('official')
        if isinstance(official, dict):
            entries.append((official, True))
        for group, recommended in (
            ('officialList', True),
            ('recommendList', True),
            ('normalList', False),
        ):
            values = raw.get(group, [])
            if isinstance(values, list):
                entries.extend((value, recommended) for value in values if isinstance(value, dict))

        experts, seen = [], set()
        for value, recommended in entries:
            appraiser_type, appraiser_id = value.get('appraiserType'), value.get('appraiserId')
            name = value.get('name')
            if (
                type(appraiser_type) is not int
                or appraiser_type not in {0, 1, 5, 10}
                or type(appraiser_id) is not int
                or appraiser_id < 0
                or not isinstance(name, str)
                or not name.strip()
            ):
                continue
            key = (appraiser_type, appraiser_id)
            if key in seen:
                continue
            seen.add(key)
            products = value.get('realPersonProductArr')
            products = products if isinstance(products, list) else []
            product = next(
                (p for p in products if isinstance(p, dict) and p.get('default') is True),
                None,
            )
            if product is None:
                product = next((p for p in products if isinstance(p, dict)), {})
            price = product.get('unitPrice') if isinstance(product.get('unitPrice'), str) else None
            currency = product.get('unit') if isinstance(product.get('unit'), str) else None
            experts.append(
                {
                    # 这两个值只留给本地服务提交时使用；前端不将其作为用户文案。
                    'appraiserType': appraiser_type,
                    'appraiserId': appraiser_id,
                    'name': name.strip(),
                    'avatar': value.get('transparentAvatar') or value.get('avatar'),
                    'duration': (value.get('durationTime') if isinstance(value.get('durationTime'), str) else None),
                    'introduction': (value.get('introduce') if isinstance(value.get('introduce'), str) else None),
                    'recommended': bool(value.get('isRecommend')) or recommended,
                    'experience': (value.get('identifiedCount') if isinstance(value.get('identifiedCount'), str) else None),
                    'price': price,
                    'currency': currency,
                    # 购买匹配仅在本机服务端使用；页面展示的是专家名称和商品信息。
                    'purchaseFilter': (value.get('purchaseFilter') if isinstance(value.get('purchaseFilter'), dict) else None),
                }
            )
        if not experts:
            raise WorkspaceError('no_experts', '当前服务没有返回可用的鉴定专家', 409)
        return experts

    @staticmethod
    def purchase_products(raw, expert):
        """仅接受服务端产品目录中与所选专家精确匹配的鉴定次数商品。"""

        if not isinstance(raw, dict) or not isinstance(raw.get('products'), list):
            raise WorkspaceError('invalid_products', 'CLI 返回的鉴定商品目录格式无效', 502)
        # 专家目录里的 realPersonProductArr 只有旧 App 的展示价格，缺少可审计的
        # sku/version，不能据此下单。正式目录为空说明部署环境尚未初始化或启用商品，
        # 需要把这类运营配置问题与“已有商品但不属于当前服务”分开提示。
        if not raw['products']:
            raise WorkspaceError(
                'purchase_catalog_empty',
                '当前环境尚未上架真人鉴定次数商品；请在服务端配置并启用商品后重试',
                409,
            )
        target = expert.get('purchaseFilter') or {
            'productType': 'appraisal_credit',
            'appraiserType': expert['appraiserType'],
            'appraiserId': expert['appraiserId'],
        }
        items = []
        for product in raw['products']:
            if not isinstance(product, dict):
                continue
            spec = product.get('entitlementSpec')
            if not isinstance(spec, dict):
                continue
            if (
                product.get('productType', target.get('productType')) != 'appraisal_credit'
                or spec.get('appraiserType') != target.get('appraiserType')
                or spec.get('appraiserId') != target.get('appraiserId')
            ):
                continue
            sku, version, amount = (
                product.get('sku'),
                product.get('version'),
                product.get('amount'),
            )
            exponent, currency, times = (
                product.get('currencyExponent'),
                product.get('currency'),
                spec.get('times'),
            )
            if (
                not isinstance(sku, str)
                or not sku
                or type(version) is not int
                or version < 1
                or type(amount) is not int
                or amount < 0
                or type(exponent) is not int
                or not 0 <= exponent <= 6
                or not isinstance(currency, str)
                or not currency
                or type(times) is not int
                or times < 1
            ):
                continue
            items.append(
                {
                    'sku': sku,
                    'version': version,
                    'amount': amount,
                    'currency': currency.upper(),
                    'currencyExponent': exponent,
                    'times': times,
                }
            )
        if not items:
            raise WorkspaceError('no_purchase_product', '当前服务没有可购买的鉴定次数商品', 409)
        return items

    @staticmethod
    def checkout_url(result):
        """仅从已约定的支付字段读取 URL，避免把任意 CLI 文本当成跳转地址。

        HeriBase 旧结算端返回 checkoutUrl，新版 Wpt 预下单则把同一用途的 H5
        地址放在 data.h5Url 或 payInfo.h5Url。支付参数可能还含有支付单号和签名，
        因此不能递归搜索，更不能持久化；这里只返回这些明确字段中的一个地址。
        """

        parameters = result.get('paymentParameters') if isinstance(result, dict) else None
        parameters = parameters if isinstance(parameters, dict) else {}
        data = parameters.get('data')
        pay_info = parameters.get('payInfo')
        candidates = (
            parameters.get('checkoutUrl'),
            parameters.get('paymentUrl'),
            data.get('h5Url') if isinstance(data, dict) else None,
            pay_info.get('h5Url') if isinstance(pay_info, dict) else None,
        )
        url = next((value for value in candidates if isinstance(value, str)), None)
        parsed = urlparse(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme not in {'https', 'http'} or not parsed.netloc or parsed.username or parsed.password:
            raise WorkspaceError(
                'payment_url_unavailable',
                '订单已创建，但服务未返回可安全打开的支付页面；请从 HeriBase 应用继续支付',
                409,
            )
        return url

    def appraisal_material_sources(self, task, item):
        """允许当前实物证据及本任务尚未归属任何其他实物的图片。"""

        own = {e.get('source_id') for e in item.get('evidence', []) if isinstance(e.get('source_id'), str)}
        occupied = {
            e.get('source_id') for other in task['items'] if other.get('local_id') != item.get('local_id') for e in other.get('evidence', []) if isinstance(e.get('source_id'), str)
        }
        return {
            source['source_id']
            for source in task['sources']
            if isinstance(source.get('source_id'), str)
            and str(source.get('mime_type', '')).startswith('image/')
            and (source['source_id'] in own or source['source_id'] not in occupied)
        }

    def save_appraisal(self, body, actor):
        task, item = self.item(body['taskKey'], body['expectedRevision'], body['localId'])
        if not isinstance(body['description'], str) or len(body['description']) > 5000:
            raise WorkspaceError('invalid_description', '鉴定说明不能超过 5000 字符')
        if type(body['appraiserType']) is not int or body['appraiserType'] not in {0, 1, 5, 10} or type(body['appraiserId']) is not int or body['appraiserId'] < 0:
            raise WorkspaceError('invalid_expert', '请选择服务实际提供的专家类型和 ID')
        source_ids = body['sourceIds']
        if not isinstance(source_ids, dict) or set(source_ids) != {
            'obverse',
            'reverse',
            'side',
        }:
            raise WorkspaceError('invalid_sources', '需要正面、反面、侧面材料选择')
        available = self.appraisal_material_sources(task, item)
        if any(v is not None and (not isinstance(v, str) or v not in available) for v in source_ids.values()):
            raise WorkspaceError(
                'invalid_sources',
                '鉴定材料必须是当前实物已关联或本任务尚未分配的归档图片',
            )
        old = self.store.get_entity('appraisal-draft', item['local_id'])
        if old and old['data'].get('status') not in {'draft', 'failed'}:
            raise WorkspaceError('already_submitted', '申请已提交或待核验，请先查看原申请', 409)
        return self.store.save_entity(
            'appraisal-draft',
            item['local_id'],
            {
                'taskKey': body['taskKey'],
                'localId': item['local_id'],
                'title': operations.display_for_item(item).get('title') or item['item_key'],
                'description': body['description'],
                'sourceIds': source_ids,
                'appraiserType': body['appraiserType'],
                'appraiserId': body['appraiserId'],
                'status': 'draft',
            },
            body['draftRevision'],
            actor,
        )

    def services(self, appraiser_type=None, appraiser_id=None):
        if (
            (appraiser_type is None) != (appraiser_id is None)
            or appraiser_type is not None
            and (type(appraiser_type) is not int or appraiser_type not in {0, 1, 5, 10} or type(appraiser_id) is not int or appraiser_id < 0)
        ):
            raise WorkspaceError('invalid_expert', '专家类型或 ID 无效')
        experts = self.appraisal_experts(self.executor.query(['appraisals', 'experts']))
        result = {'experts': experts, 'queriedAt': self.store.timestamp()}
        if appraiser_type is not None:
            matching = next(
                (expert for expert in experts if expert['appraiserType'] == appraiser_type and expert['appraiserId'] == appraiser_id),
                None,
            )
            if not matching:
                raise WorkspaceError('invalid_expert', '所选鉴定服务已不可用，请重新选择', 409)
            result['selected'] = matching
            result['credits'] = self.executor.query(
                [
                    'appraisals',
                    'credits',
                    '--appraiser-type',
                    str(appraiser_type),
                    '--appraiser-id',
                    str(appraiser_id),
                ]
            )
        return result

    def purchase_options(self, appraiser_type, appraiser_id):
        """读取本次服务可购买商品；金额和次数只来自 CLI 商品目录。"""

        services = self.services(appraiser_type, appraiser_id)
        products = self.purchase_products(self.executor.query(['appraisals', 'products']), services['selected'])
        return {
            'service': services['selected'],
            'products': products,
            'queriedAt': self.store.timestamp(),
        }

    def purchase_plan(self, appraiser_type, appraiser_id, sku, actor):
        options = self.purchase_options(appraiser_type, appraiser_id)
        product = next((item for item in options['products'] if item['sku'] == sku), None)
        if not product:
            raise WorkspaceError('invalid_product', '所选商品不属于当前鉴定服务，请重新选择', 409)
        plan = {
            'kind': 'appraisal_purchase',
            'service': options['service'],
            'product': product,
            'account': self.executor.account(),
            'status': 'awaiting_confirmation',
        }
        plan['hash'] = digest(plan)
        plan['id'] = 'purchase-' + secrets.token_hex(12)
        return self.store.save_entity('appraisal-purchase-plan', plan['id'], plan, 0, actor)['data']

    def checkout_purchase(self, body, actor):
        """用户确认后才建订单；支付 URL 只在本次响应返回，不长期写入本机库。"""

        with self.executor.lock:
            record = self.store.get_entity('appraisal-purchase-plan', body['planId'])
            if not record:
                raise WorkspaceError('plan_not_found', '未找到当前购买确认单', 404)
            plan = record['data']
            request = {
                'commandId': body['commandId'],
                'planId': body['planId'],
                'planHash': body['planHash'],
            }
            existing = self.executor._existing(request, 'appraisal_purchase')
            if existing:
                purchase = self.store.get_entity('appraisal-purchase', body['commandId'])
                return {'purchase': purchase, 'checkoutUrl': None, 'reused': True}
            if plan.get('kind') != 'appraisal_purchase' or plan.get('status') != 'awaiting_confirmation' or plan.get('hash') != body['planHash']:
                raise WorkspaceError('stale_plan', '购买商品或服务已变化，请重新查看', 409)
            if plan['account'] != self.executor.account():
                raise WorkspaceError('account_changed', '账户已变化，请重新查询服务和商品', 409)
            operation = self.store.save_entity(
                'operation',
                body['commandId'],
                {
                    'kind': 'appraisal_purchase',
                    'label': f"购买真人鉴定次数 · {plan['service']['name']}",
                    'requestHash': digest({'kind': 'appraisal_purchase', 'body': request}),
                    'request': request,
                    'account': plan['account'],
                    'status': 'running',
                    'actor': actor,
                    'calls': [],
                    'itemResults': [],
                    'scope': plan,
                    'message': '正在创建支付订单',
                },
                0,
                actor,
            )
            self.store.save_entity(
                'appraisal-purchase-plan',
                record['id'],
                {**plan, 'status': 'confirmed'},
                record['revision'],
                actor,
            )
            argv = [
                'appraisals',
                'checkout',
                '--sku',
                plan['product']['sku'],
                '--version',
                str(plan['product']['version']),
                '--request-id',
                body['commandId'],
            ]
            try:
                _, _, result = self.executor._invoke(operation['id'], argv)
                result = self.appraisal_cli_result(result, 'appraisals.checkout')
                uri = result.get('purchaseUri') or result.get('uri') if isinstance(result, dict) else None
                try:
                    identifier(uri, '购买订单标识')
                except WorkspaceError:
                    raise WorkspaceError(
                        'purchase_unverified',
                        '服务未返回可核验的购买订单标识，请先核验执行记录123',
                        409,
                    )
                purchase = self.store.save_entity(
                    'appraisal-purchase',
                    body['commandId'],
                    {
                        'purchaseUri': uri,
                        'operationId': operation['id'],
                        'account': plan['account'],
                        'service': plan['service'],
                        'product': plan['product'],
                        'status': 'awaiting_payment',
                        'createdAt': self.store.timestamp(),
                    },
                    0,
                    'system:executor',
                )
                self.executor.update(
                    operation['id'],
                    status='completed',
                    message='支付订单已创建，等待用户完成付款',
                )
                # 建单与打开支付页是两件事：缺少可用地址不能把已确认创建的订单
                # 改成未知结果。返回原订单，允许用户从“继续支付”恢复同一订单。
                payment_url, payment_error = None, None
                try:
                    payment_url = self.checkout_url(result)
                except WorkspaceError as exc:
                    if exc.code != 'payment_url_unavailable':
                        raise
                    payment_error = {'code': exc.code, 'message': str(exc)}
                return {
                    'purchase': purchase,
                    'checkoutUrl': payment_url,
                    'paymentError': payment_error,
                    'reused': False,
                }
            except Exception as exc:
                self.executor.update(
                    operation['id'],
                    status=('failed' if isinstance(exc, WorkspaceError) and exc.code == 'cli_definite_failure' else 'reconcile_required'),
                    message=(str(exc) if isinstance(exc, WorkspaceError) else '创建支付订单中断，请先核验执行记录'),
                )
                raise

    def resume_purchase(self, purchase_id):
        """为已有待付款订单重新获取支付页，不重放 checkout 创建新订单。

        该调用必须由浏览器中的“继续支付”按钮发起。只把 URL 留在本次 HTTP 响应，
        订单、支付参数和支付页中的会话信息都不会写入 heribase.sqlite。
        """

        purchase = self.store.get_entity('appraisal-purchase', purchase_id)
        if not purchase:
            raise WorkspaceError('purchase_not_found', '未找到购买记录', 404)
        data = purchase['data']
        if data.get('account') != self.executor.account():
            raise WorkspaceError('account_changed', '请切回购买时的账户和服务地址再继续支付', 409)
        if data.get('status') != 'awaiting_payment':
            raise WorkspaceError('purchase_not_payable', '此订单不处于待付款状态，无需继续支付', 409)
        uri = data.get('purchaseUri')
        try:
            identifier(uri, '购买订单标识')
        except WorkspaceError:
            raise WorkspaceError('purchase_unverified', '购买订单标识无效，请先核验执行记录', 409)
        result = self.executor.query(['appraisals', 'purchases', 'pay', '--uri', uri])
        result = self.appraisal_cli_result(result, 'appraisals.purchases.pay')
        return {
            'purchase': purchase,
            'checkoutUrl': self.checkout_url(result),
            'reused': True,
        }

    def refresh_purchase(self, purchase_id):
        purchase = self.store.get_entity('appraisal-purchase', purchase_id)
        if not purchase:
            raise WorkspaceError('purchase_not_found', '未找到购买记录', 404)
        data = purchase['data']
        if data.get('account') != self.executor.account():
            raise WorkspaceError('account_changed', '请切回购买时的账户和服务地址再核验', 409)
        detail = self.executor.query(
            [
                'appraisals',
                'purchases',
                'detail',
                '--uri',
                data['purchaseUri'],
                '--refresh',
                '1',
            ]
        )
        confirmed = detail.get('purchaseConfirmed') is True if isinstance(detail, dict) else False
        credits = self.executor.query(
            [
                'appraisals',
                'credits',
                '--appraiser-type',
                str(data['service']['appraiserType']),
                '--appraiser-id',
                str(data['service']['appraiserId']),
            ]
        )
        status = 'granted' if confirmed else ('fulfillment_pending' if isinstance(detail, dict) and detail.get('paymentState') == 'paid' else 'awaiting_payment')
        purchase = self.store.save_entity(
            'appraisal-purchase',
            purchase_id,
            {
                **data,
                'status': status,
                'detail': detail,
                'credits': credits,
                'checkedAt': self.store.timestamp(),
            },
            purchase['revision'],
            'system:query',
        )
        # checkout 的 completed 仅表示建单调用结束。查单成功后同步同一执行记录的
        # 支付/履约事实，避免购买已到账而历史记录永远提示“等待用户完成付款”。
        # 可用余额可能已被消耗，也可能暂时查询不到，不能据余额推断本订单支付状态。
        operation_id = data.get('operationId')
        if operation_id and self.store.get_entity('operation', operation_id):
            self.executor.update(
                operation_id,
                purchaseUri=data['purchaseUri'],
                paymentState=detail.get('paymentState') if isinstance(detail, dict) else None,
                fulfillmentState=detail.get('fulfillmentState') if isinstance(detail, dict) else None,
                purchaseCheckedAt=purchase['data']['checkedAt'],
                message={
                    'granted': '支付成功，鉴定次数已发放',
                    'fulfillment_pending': '支付成功，等待次数发放',
                    'awaiting_payment': '支付订单已创建，等待用户完成付款',
                }[status],
            )
        return purchase

    @staticmethod
    def tracking_products(raw):
        """只向工作台提供九表 Wpt 中真正可结算的追踪位商品。"""

        if not isinstance(raw, dict) or not isinstance(raw.get('products'), list):
            raise WorkspaceError('invalid_products', 'CLI 返回的追踪位商品目录格式无效', 502)
        products = []
        for product in raw['products']:
            if not isinstance(product, dict) or product.get('productType') != 'tracking_credit':
                continue
            spec = product.get('entitlementSpec') or {}
            sku, version, times = product.get('sku'), product.get('version'), spec.get('times')
            if not isinstance(sku, str) or not sku or type(version) is not int or version < 1 or type(times) is not int or times < 1:
                continue
            products.append(
                {
                    **product,
                    'times': times,
                    'durationUnit': spec.get('durationUnit'),
                    'durationCount': spec.get('durationCount'),
                }
            )
        if not products:
            raise WorkspaceError(
                'tracking_catalog_empty',
                '当前环境没有可购买的追踪位商品，请检查服务端商品目录后重试',
                409,
            )
        return products

    def tracking_purchase_base_plan(self, plan_id):
        """购买只能从当前账户下尚未确认的追踪预览发起，防止伪造收藏来源。"""

        record = self.store.get_entity('business-plan', plan_id)
        if not record or record['data'].get('kind') != 'tracking':
            raise WorkspaceError('plan_not_found', '未找到当前追踪确认单', 404)
        plan = record['data']
        if plan.get('status') != 'awaiting_confirmation':
            raise WorkspaceError('stale_plan', '追踪计划已确认或过期，请重新检查', 409)
        if plan.get('account') != self.executor.account():
            raise WorkspaceError('account_changed', '账户或服务地址已变化，请重新检查追踪位', 409)
        return plan

    @staticmethod
    def available_tracking_slots(value):
        """只接受 API 的 availableSlots 字段；缺值不能猜成有或没有额度。"""

        count = value.get('availableSlots') if isinstance(value, dict) else None
        return count if type(count) is int and count >= 0 else None

    def tracking_purchase_options(self, plan_id):
        plan = self.tracking_purchase_base_plan(plan_id)
        products = self.tracking_products(self.executor.query(['tracking', 'products']))
        return {
            'planId': plan_id,
            'title': plan['title'],
            'eligibility': plan.get('eligibility'),
            'products': products,
            'queriedAt': self.store.timestamp(),
        }

    def tracking_purchase_plan(self, plan_id, sku, actor):
        options = self.tracking_purchase_options(plan_id)
        product = next((value for value in options['products'] if value['sku'] == sku), None)
        if not product:
            raise WorkspaceError('invalid_product', '所选商品已不在当前可售目录中，请重新选择', 409)
        base = self.tracking_purchase_base_plan(plan_id)
        plan = {
            'kind': 'tracking_purchase',
            'basePlanId': plan_id,
            'taskKey': base['taskKey'],
            'localId': base['localId'],
            'collectUri': base['collectUri'],
            'title': base['title'],
            'product': product,
            'account': base['account'],
            'status': 'awaiting_confirmation',
        }
        plan['hash'] = digest(plan)
        plan['id'] = 'tracking-purchase-' + secrets.token_hex(12)
        return self.store.save_entity('tracking-purchase-plan', plan['id'], plan, 0, actor)['data']

    @staticmethod
    def tracking_cli_result(result, operation):
        """兼容 CLI task 包装层和旧版直接返回业务对象的格式。"""

        if isinstance(result, dict) and result.get('operation') == operation and isinstance(result.get('result'), dict):
            return result['result']
        return result

    def checkout_tracking_purchase(self, body, actor):
        """用户确认后幂等创建追踪位订单，并将支付地址限制在本次响应中。"""

        with self.executor.lock:
            record = self.store.get_entity('tracking-purchase-plan', body['planId'])
            if not record:
                raise WorkspaceError('plan_not_found', '未找到当前追踪位购买确认单', 404)
            plan = record['data']
            request = {'commandId': body['commandId'], 'planId': body['planId'], 'planHash': body['planHash']}
            existing = self.executor._existing(request, 'tracking_purchase')
            if existing:
                purchase = self.store.get_entity('tracking-purchase', body['commandId'])
                return {'purchase': purchase, 'checkoutUrl': None, 'reused': True}
            if plan.get('kind') != 'tracking_purchase' or plan.get('status') != 'awaiting_confirmation' or plan.get('hash') != body['planHash']:
                raise WorkspaceError('stale_plan', '购买商品已变化，请重新查看并确认', 409)
            self.tracking_purchase_base_plan(plan['basePlanId'])
            if plan['account'] != self.executor.account():
                raise WorkspaceError('account_changed', '账户已变化，请重新查询商品', 409)
            operation = self.store.save_entity(
                'operation',
                body['commandId'],
                {
                    'kind': 'tracking_purchase',
                    'label': f"购买追踪位 · {plan['product']['times']} 个追踪位",
                    'requestHash': digest({'kind': 'tracking_purchase', 'body': request}),
                    'request': request,
                    'account': plan['account'],
                    'status': 'running',
                    'actor': actor,
                    'calls': [],
                    'itemResults': [],
                    'scope': plan,
                    'message': '正在创建追踪位支付订单',
                },
                0,
                actor,
            )
            self.store.save_entity('tracking-purchase-plan', record['id'], {**plan, 'status': 'confirmed'}, record['revision'], actor)
            argv = [
                'tracking',
                'checkout',
                '--sku',
                plan['product']['sku'],
                '--version',
                str(plan['product']['version']),
                '--request-id',
                body['commandId'],
                '--source-type',
                'collection',
                '--source-uri',
                plan['collectUri'],
            ]
            try:
                _, _, result = self.executor._invoke(operation['id'], argv)
                result = self.tracking_cli_result(result, 'tracking.checkout')
                uri = result.get('purchaseUri') or result.get('uri') if isinstance(result, dict) else None
                if not isinstance(uri, str) or not re.fullmatch(r'[A-Za-z0-9]{18,}', uri):
                    raise WorkspaceError('purchase_unverified', '服务未返回可核验的购买订单标识，请先核验执行记录', 409)
                purchase = self.store.save_entity(
                    'tracking-purchase',
                    body['commandId'],
                    {
                        'purchaseUri': uri,
                        'operationId': operation['id'],
                        'account': plan['account'],
                        'product': plan['product'],
                        'basePlanId': plan['basePlanId'],
                        'taskKey': plan['taskKey'],
                        'localId': plan['localId'],
                        'collectUri': plan['collectUri'],
                        'title': plan['title'],
                        'status': 'awaiting_payment',
                        'createdAt': self.store.timestamp(),
                    },
                    0,
                    'system:executor',
                )
                self.executor.update(operation['id'], status='completed', message='订单已创建，等待用户完成付款')
                checkout_url, payment_error = None, None
                try:
                    checkout_url = self.checkout_url(result)
                except WorkspaceError as exc:
                    if exc.code != 'payment_url_unavailable':
                        raise
                    payment_error = {'code': exc.code, 'message': str(exc)}
                return {'purchase': purchase, 'checkoutUrl': checkout_url, 'paymentError': payment_error, 'reused': False}
            except Exception as exc:
                self.executor.update(
                    operation['id'],
                    status='failed' if isinstance(exc, WorkspaceError) and exc.code == 'cli_definite_failure' else 'reconcile_required',
                    message=str(exc) if isinstance(exc, WorkspaceError) else '创建订单中断，请先核验执行记录',
                )
                raise

    def resume_tracking_purchase(self, purchase_id):
        """只为原待付款订单恢复支付页，不会创建新订单。"""

        purchase = self.store.get_entity('tracking-purchase', purchase_id)
        if not purchase:
            raise WorkspaceError('purchase_not_found', '未找到追踪位购买记录', 404)
        data = purchase['data']
        if data.get('account') != self.executor.account():
            raise WorkspaceError('account_changed', '请切回购买时的账户和服务地址再继续支付', 409)
        if data.get('status') != 'awaiting_payment':
            raise WorkspaceError('purchase_not_payable', '此订单不处于待付款状态，无需继续支付', 409)
        uri = data.get('purchaseUri')
        if not isinstance(uri, str) or not re.fullmatch(r'[A-Za-z0-9]{18,}', uri):
            raise WorkspaceError('purchase_unverified', '购买订单标识无效，请先核验执行记录', 409)
        result = self.executor.query(['tracking', 'purchases', 'pay', '--uri', uri])
        result = self.tracking_cli_result(result, 'tracking.purchases.pay')
        return {'purchase': purchase, 'checkoutUrl': self.checkout_url(result), 'reused': True}

    def refresh_tracking_purchase(self, purchase_id):
        """刷新订单真实支付和履约状态，并再次读取追踪位余额。"""

        purchase = self.store.get_entity('tracking-purchase', purchase_id)
        if not purchase:
            raise WorkspaceError('purchase_not_found', '未找到追踪位购买记录', 404)
        data = purchase['data']
        if data.get('account') != self.executor.account():
            raise WorkspaceError('account_changed', '请切回购买时的账户和服务地址再核验', 409)
        detail = self.executor.query(['tracking', 'purchases', 'detail', '--uri', data['purchaseUri'], '--refresh', '1'])
        detail = self.tracking_cli_result(detail, 'tracking.purchases.detail')
        eligibility = self.executor.query(['tracking', 'slots'])
        paid = isinstance(detail, dict) and detail.get('paymentState') == 'paid'
        granted = isinstance(detail, dict) and (detail.get('fulfillmentState') == 'granted' or detail.get('purchaseConfirmed') is True)
        status = 'granted' if granted else ('fulfillment_pending' if paid else 'awaiting_payment')
        return self.store.save_entity(
            'tracking-purchase',
            purchase_id,
            {
                **data,
                'status': status,
                'detail': detail,
                'eligibility': eligibility,
                'checkedAt': self.store.timestamp(),
            },
            purchase['revision'],
            'system:query',
        )

    def preview(self, kind, body, actor):
        task, item = self.item(body['taskKey'], body['expectedRevision'], body['localId'])
        self.executor.assert_idle(body['taskKey'])
        if item['status'] != 'active' or 'identity_conflict' in item.get('attention_flags', []):
            raise WorkspaceError(
                'identity_conflict',
                '请先处理此候选的归属或身份冲突，再准备线上申请',
                409,
            )
        plan = {
            'kind': kind,
            'taskKey': body['taskKey'],
            'localId': item['local_id'],
            'itemVersion': item['version'],
            'taskRevision': body['expectedRevision'],
            'account': self.executor.account(),
            'title': operations.display_for_item(item).get('title') or item['item_key'],
        }
        projection = item.get('collection_projection') or {}
        collection = projection.get('collection_uri') if projection.get('status') == 'succeeded' else None
        binding = self.store.get_entity('task-account', body['taskKey'])
        if binding and binding['data'] != plan['account']:
            raise WorkspaceError('account_changed', '此藏品属于另一已绑定账户，请切回原账户', 409)
        if kind == 'tracking':
            if not collection:
                raise WorkspaceError('collection_required', '先取得已验证的本人收藏关联', 409)
            existing = self.store.get_entity('tracking-draft', item['local_id'])
            if existing and existing['data'].get('status') != 'failed':
                raise WorkspaceError('tracking_exists', '已存在此收藏的追踪记录，请查看或核验原记录', 409)
            plan.update(
                collectUri=collection,
                eligibility=self.executor.query(['tracking', 'slots']),
            )
        else:
            draft = self.store.get_entity('appraisal-draft', item['local_id'])
            if not draft or draft['data']['status'] != 'draft':
                raise WorkspaceError('draft_required', '先保存当前鉴定材料草稿', 409)
            data = draft['data']
            if not all(data['sourceIds'].values()) or len(set(data['sourceIds'].values())) != 3:
                raise WorkspaceError('incomplete_images', '请选择三张不同的正面、反面与侧面图片', 409)
            plan.update(
                draftId=draft['id'],
                draftRevision=draft['revision'],
                draft=data,
                eligibility=self.services(data['appraiserType'], data['appraiserId']),
            )
            if collection:
                plan['collectUri'] = collection
            elif (item.get('active_identification') or {}).get('status') == 'succeeded':
                plan['identifyUri'] = item['active_identification']['identify_uri']
        plan['hash'] = digest(plan)
        plan['id'] = 'business-' + secrets.token_hex(12)
        plan['status'] = 'awaiting_confirmation'
        self.store.save_entity('business-plan', plan['id'], plan, 0, actor)
        return plan

    def start(self, kind, body, actor):
        with self.executor.lock:
            record = self.store.get_entity('business-plan', body['planId'])
            if not record:
                raise WorkspaceError('plan_not_found', '未找到当前申请清单', 404)
            plan = record['data']
            request = {**body, 'taskKey': plan['taskKey']}
            existing = self.executor._existing(request, kind)
            if existing:
                return existing
            if plan['kind'] != kind or plan['hash'] != body['planHash'] or plan['status'] != 'awaiting_confirmation':
                raise WorkspaceError('stale_plan', '申请已确认或内容变化，请重新查看', 409)
            if plan['account'] != self.executor.account():
                raise WorkspaceError('account_changed', '账户已变化，请重新核对申请', 409)
            task, item = self.item(plan['taskKey'], plan['taskRevision'], plan['localId'])
            if kind == 'appraisal':
                draft = self.store.get_entity('appraisal-draft', plan['draftId'])
                if not draft or draft['revision'] != plan['draftRevision']:
                    raise WorkspaceError('stale_draft', '鉴定材料已变化，请重新检查', 409)
            elif kind == 'tracking':
                # 用户点确认时重新查额度，避免计划预览之后追踪位已被其他操作消耗。
                fresh_slots = self.executor.query(['tracking', 'slots'])
                available = self.available_tracking_slots(fresh_slots)
                if available is None:
                    raise WorkspaceError('tracking_slots_unknown', '服务没有返回可用追踪位数量，请重新检查', 409)
                if available < 1:
                    raise WorkspaceError('tracking_slots_empty', '当前没有可用追踪位，请购买并确认到账后再开启追踪', 409)
            tracking = self.store.get_entity('tracking-draft', plan['localId']) if kind == 'tracking' else None
            if tracking and tracking['data'].get('status') != 'failed':
                raise WorkspaceError('tracking_exists', '此收藏已有追踪申请，请核验原记录', 409)
            self.executor._reserve(request, kind, actor, plan['account'])
            self.store.save_entity(
                'business-plan',
                record['id'],
                {**plan, 'status': 'confirmed'},
                record['revision'],
                actor,
            )
            entity_kind = 'appraisal-draft' if kind == 'appraisal' else 'tracking-draft'
            old = self.store.get_entity(entity_kind, plan['localId'])
            data = {
                **(old['data'] if old else {}),
                'title': plan['title'],
                'taskKey': plan['taskKey'],
                'localId': plan['localId'],
                'status': 'submitting',
                'operationId': body['commandId'],
            }
            self.store.save_entity(entity_kind, plan['localId'], data, old['revision'] if old else 0, actor)
            self.executor.update(
                body['commandId'],
                status='queued',
                label='提交真人鉴定' if kind == 'appraisal' else '开启追踪',
                scope=plan,
            )
            return self.executor._dispatch(body['commandId'], lambda op: self._execute(op, plan, entity_kind))

    def _execute(self, operation_id, plan, entity_kind):
        try:
            task, _ = self.item(plan['taskKey'], plan['taskRevision'], plan['localId'])
            if plan['kind'] == 'tracking':
                argv = ['tracking', 'add', '--collect-uri', plan['collectUri']]
            else:
                data = plan['draft']
                argv = ['appraisals', 'submit']
                for role in ('obverse', 'reverse', 'side'):
                    url = self.executor._upload(operation_id, task, data['sourceIds'][role])
                    argv += ['--' + role + '-img', url]
                argv += [
                    '--desc',
                    data['description'],
                    '--appraiser-type',
                    str(data['appraiserType']),
                    '--appraiser-id',
                    str(data['appraiserId']),
                ]
                if plan.get('collectUri'):
                    argv += ['--collect-uri', plan['collectUri']]
                elif plan.get('identifyUri'):
                    argv += ['--uri', plan['identifyUri']]
                self.item(plan['taskKey'], plan['taskRevision'], plan['localId'])
            _, _, result = self.executor._invoke(operation_id, argv)
            uri_keys = ('trackingUri', 'tracking_uri', 'uri') if plan['kind'] == 'tracking' else ('appraisalUri', 'appraisal_uri', 'uri')
            uri = next(
                (result[k] for k in uri_keys if isinstance(result, dict) and isinstance(result.get(k), str) and result[k]),
                None,
            )
            if not uri:
                raise WorkspaceError(
                    'unverified_submission',
                    '服务未返回可核验的记录 URI，请查询原提交，勿重复提交',
                    409,
                )
            old = self.store.get_entity(entity_kind, plan['localId'])
            self.store.save_entity(
                entity_kind,
                old['id'],
                {
                    **old['data'],
                    'status': 'submitted',
                    'uri': uri,
                    'submittedAt': self.store.timestamp(),
                    'response': result,
                },
                old['revision'],
                'system:executor',
            )
        except Exception as exc:
            old = self.store.get_entity(entity_kind, plan['localId'])
            self.store.save_entity(
                entity_kind,
                old['id'],
                {
                    **old['data'],
                    'status': ('failed' if isinstance(exc, WorkspaceError) and exc.code == 'cli_definite_failure' else 'reconcile_required'),
                },
                old['revision'],
                'system:executor',
            )
            raise

    def refresh(self, kind, local_id):
        entity_kind = 'appraisal-draft' if kind == 'appraisal' else 'tracking-draft'
        old = self.store.get_entity(entity_kind, local_id)
        if not old or not old['data'].get('uri'):
            raise WorkspaceError('record_not_found', '尚无可查询的服务记录 URI，请先核验原提交', 409)
        operation = self.store.get_entity('operation', old['data'].get('operationId', ''))
        if not operation or operation['data']['account'] != self.executor.account():
            raise WorkspaceError('account_changed', '请切回申请时的账户和服务地址再查询', 409)
        uri = old['data']['uri']
        command = 'appraisals' if kind == 'appraisal' else 'tracking'
        detail = self.executor.query([command, 'detail', '--uri', uri])
        values = {'detail': detail, 'queriedAt': self.store.timestamp()}
        if kind == 'tracking':
            values['prices'] = self.executor.query(['prices', 'trends', '--source-type', 'tracking', '--source-uri', uri])
        return self.store.save_entity(
            entity_kind,
            local_id,
            {**old['data'], **values},
            old['revision'],
            'system:query',
        )
