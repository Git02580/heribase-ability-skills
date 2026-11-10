import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.location = { hash: '', pathname: '/', search: '' };
globalThis.sessionStorage = { getItem: () => '', setItem: () => {} };
const { renderCommercePage, commerceSummary, createCommerceController } = await import('../assets/workbench/commerce.js');

test('market preserves major-unit prices and escapes remote titles and image URLs', () => {
  const html = renderCommercePage({ page: 'market' }, { data: { list: [{ uri: 'G1', title: '<script>bad</script>', salePrice: '19.99', coverImg: 'javascript:alert(1)' }] } });
  assert.match(html, /19\.99/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /src="javascript:|<script>/);
});

test('buyer and seller order actions follow the remote identity and current state', () => {
  const render = (isSeller, state, canShip = false) => renderCommercePage({ page: isSeller ? 'selling' : 'buying', item: 'O1' }, {
    data: { goodsInfo: { title: 'Morgan' }, payInfo: { orderUri: 'O1' }, isSeller, stateDetail: { state, canShip } }, tab: 'orders',
  });
  assert.match(render(false, 100), /data-action="commerce-order-pay"/);
  assert.match(render(false, 100), /data-action="commerce-order-cancel"/);
  assert.doesNotMatch(render(true, 100), /data-action="commerce-order-cancel"/);
  assert.doesNotMatch(render(false, 120), /data-action="commerce-order-cancel"/);
  assert.doesNotMatch(render(false, 100), /data-action="commerce-order-receive"/);
  assert.match(render(false, 120), /data-action="commerce-order-receive"/);
  assert.match(render(false, 105), /data-action="commerce-order-address"/);
  assert.doesNotMatch(render(true, 105), /data-action="commerce-order-address"/);
  assert.match(render(true, 110, true), /data-action="commerce-order-deliver"/);
  assert.doesNotMatch(render(true, 110, true), /data-action="commerce-order-pay"|data-action="commerce-order-receive"/);
  assert.doesNotMatch(render(false, 150), /data-action="commerce-order-pay"|data-action="commerce-order-receive"/);
});

test('pending address sync offers the same saved address instead of silently choosing a new one', async () => {
  const plans = [];
  const detail = { payInfo: { orderUri: 'O1' }, isSeller: false, stateDetail: { state: 105 }, address: { id: 12, fullName: 'Ada', streetAddress: '1 Main' } };
  const html = renderCommercePage({ page: 'buying', item: 'O1' }, { data: detail });
  assert.match(html, /继续确认原地址/);
  assert.match(html, /data-address-id="12"/);
  const controller = createCommerceController({ request: async (_path, body) => {
    plans.push(body); return { label: '确认订单地址', id: 'p', hash: 'h', summary: { address: detail.address } };
  }, dialog: () => {}, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.handle('commerce-order-address', { dataset: { id: 'O1', addressId: '12' } });
  assert.deepEqual(plans, [{ action: 'trade.orders.address', params: { orderUri: 'O1', addressId: 12 } }]);
});

test('membership renders exact minor-unit price and duration without inventing renewal', () => {
  const product = { sku: 'year', version: 1, amount: 3999, currency: 'usd', currencyExponent: 2,
    entitlementSpec: { durationUnit: 'year', durationCount: 1, offerType: 'standard' } };
  const html = renderCommercePage({ page: 'membership' }, { data: {
    catalog: { products: [product] }, entitlements: { membership: { active: false } }, purchases: { list: [] },
  } });
  assert.match(html, /39\.99/);
  assert.match(html, /1 年/);
  assert.match(html, /不会自动续费/);
  assert.match(html, /data-sku="year"/);
  assert.doesNotMatch(html, /3999\.00|3 天免费/);
});

test('membership separates free trials, first-month offers and pending-order eligibility', () => {
  const year = { sku: 'year', amount: 3999, currency: 'usd', currencyExponent: 2,
    entitlementSpec: { durationUnit: 'year', durationCount: 1, offerType: 'standard' } };
  const html = renderCommercePage({ page: 'membership' }, { data: { catalog: { products: [
    { ...year, sku: 'trial', amount: 0, eligible: true, entitlementSpec: { durationUnit: 'day', durationCount: 3, offerType: 'trial' }, followupProduct: year },
    { ...year, sku: 'intro', amount: 299, eligible: false, existingPurchaseUri: 'original-order', eligibilityReason: 'membership_offer_pending',
      entitlementSpec: { durationUnit: 'month', durationCount: 1, offerType: 'introductory' }, followupProduct: year },
  ] } } });
  assert.match(html, /免费试用/);
  assert.match(html, /无需付款/);
  assert.match(html, /data-sku="trial"/);
  assert.doesNotMatch(html, /data-sku="intro"/);
  assert.match(html, /data-id="original-order"/);
  assert.match(html, /首月优惠/);
  assert.match(html, /到期后.*39\.99/);
});

test('checkout summary shows item, full address, postage and final total', () => {
  const html = commerceSummary({ goods: { title: 'Morgan' }, price: { salePrice: '19.99', postage: '1.00', totalPrice: '20.99' },
    address: { fullName: 'Ada', streetAddress: '1 Main', city: 'SF', countryCode: 'US' } });
  for (const text of ['Morgan', 'Ada', '1 Main', 'SF', '20.99', '1.00']) assert.ok(html.includes(text));
});

test('loading and failed reads are not presented as an empty collection', () => {
  assert.match(renderCommercePage({ page: 'market' }, { loading: true }), /正在读取/);
  assert.match(renderCommercePage({ page: 'market' }, { error: '网络不可用' }), /网络不可用/);
  assert.match(renderCommercePage({ page: 'market' }, { error: '网络不可用' }), /commerce-refresh/);
});

test('definite failures offer a new preview while unknown writes keep their verification action', () => {
  const html=renderCommercePage({page:'buying'}, {tab:'history',data:{operations:[
    {id:'failed-1',data:{label:'购买商品',status:'failed',message:'明确失败'}},
    {id:'unknown-1',data:{label:'购买商品',status:'reconcile_required',message:'待核验'}},
  ]}});
  assert.match(html,/data-action="commerce-replan" data-id="failed-1"/);
  assert.doesNotMatch(html,/data-action="commerce-replan" data-id="unknown-1"/);
  assert.match(html,/data-action="commerce-recover" data-id="unknown-1"/);
});

test('seller publication provides a local photo picker instead of requiring image URLs', async () => {
  let body;
  const controller = createCommerceController({ request: async () => ({ waitDeliveryOrderUri: '' }),
    dialog: (_title, content) => { body = content; }, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.handle('commerce-goods-edit', { dataset: {} });
  assert.match(body, /type="file"/);
  assert.match(body, /data-commerce-upload="imgs"/);
  assert.doesNotMatch(body, /<textarea name="imgs"/);
});

test('delivery omits an empty optional email and preserves a supplied email in CLI plans', async () => {
  const originalDocument = globalThis.document, originalFormData = globalThis.FormData;
  const calls = [];
  const form = { reportValidity: () => true, values: {} };
  globalThis.document = { querySelector: () => form };
  globalThis.FormData = class { constructor(value) { return Object.entries(value.values); } };
  try {
    const controller = createCommerceController({ request: async (_path, body) => {
      calls.push(body); return { id: 'plan', hash: 'hash', label: '确认发货', summary: {} };
    }, dialog: () => {}, redraw: () => {}, toast: () => {}, setDirty: () => {} });
    await controller.handle('commerce-order-deliver', { dataset: { id: 'O1' } });
    for (const email of ['', '  ', 'seller@example.com']) {
      form.values = { type: '1', logisticsCompany: 'USPS', logisticsTrackingNumber: 'TRACK-1',
        email, deliveryCertificateImgs: 'https://images.example/proof.jpg' };
      await controller.handle('commerce-form-preview', { dataset: {} });
      const params = calls.at(-1).params;
      assert.equal(params.orderUri, 'O1');
      if (email.trim()) assert.equal(params.email, email);
      else assert.equal(Object.hasOwn(params, 'email'), false);
    }
  } finally { globalThis.document = originalDocument; globalThis.FormData = originalFormData; }
});

test('receipt confirmation labels do not repeat the confirmation verb', async () => {
  let title, footer;
  const controller = createCommerceController({ request: async () => ({ id: 'p', hash: 'h', label: '确认收货', summary: {} }),
    dialog: (heading, _body, actions) => { title = heading; footer = actions; }, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.handle('commerce-order-receive', { dataset: { id: 'O1' } });
  assert.equal(title, '确认收货');
  assert.doesNotMatch(footer, /确认确认/);
});

test('seller publication directs pending deliveries to their order before opening an editor', async () => {
  let body;
  const controller = createCommerceController({ request: async () => ({ waitDeliveryOrderUri: 'delivery-1' }),
    dialog: (_title, content) => { body = content; }, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.handle('commerce-goods-edit', { dataset: {} });
  assert.match(body, /#selling\?item=delivery-1/);
  assert.doesNotMatch(body, /id="commerce-edit-form"/);
});

test('membership history loads subsequent pages instead of truncating all history to the first hundred', async () => {
  const reads = [];
  const controller = createCommerceController({ request: async (_path, body) => {
    reads.push(body);
    return body.action === 'purchases.list' ? { list: [], isEnd: false } : {};
  }, dialog: () => {}, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.load({ page: 'membership' });
  assert.match(controller.render({ page: 'membership' }), /data-action="commerce-page"/);
  await controller.handle('commerce-page', { dataset: { page: '2' } });
  assert.deepEqual(reads.filter(call => call.action === 'purchases.list').map(call => call.params), [
    { page: 1, pageSize: 20 }, { page: 2, pageSize: 20 },
  ]);
});

test('membership shows current benefits from the CLI and keeps a failed benefits read visible', async () => {
  const data = { entitlements: { membership: { active: true, endTimeMs: 1800000000000 } },
    subscription: { benefitsList: [{ title: '无限识别' }, { title: '<script>bad</script>' }] } };
  const html = renderCommercePage({ page: 'membership' }, { data });
  assert.match(html, /无限识别/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  data.subscription = { error: '权益说明查询失败' };
  assert.match(renderCommercePage({ page: 'membership' }, { data }), /权益说明查询失败/);
});

test('late market data cannot overwrite the buyer page or leave it stuck loading', async () => {
  const responses = [];
  const controller = createCommerceController({ request: () => new Promise(resolve => responses.push(resolve)),
    dialog: () => {}, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  const first = controller.load({ page: 'market' });
  const second = controller.load({ page: 'buying' });
  assert.equal(responses.length, 2);
  responses[1]({ list: [{ uri: 'O1', goodsInfo: { title: 'My order' } }], isEnd: true });
  await second;
  responses[0]({ list: [{ uri: 'G1', title: 'Old market result' }], isEnd: true });
  await first;
  const html = controller.render({ page: 'buying' });
  assert.match(html, /My order/);
  assert.doesNotMatch(html, /Old market result|正在读取/);
});

// 浏览器端只替换外部 HTTP 和必要 DOM 边界，上传、确认和表单更新均执行真实控制器。
test('photos pass through staging and audited upload, preserving successful photos on a partial failure', async () => {
  const value = { value: '' }, status = {}, gallery = {};
  const form = { isConnected: true, elements: { namedItem: () => value },
    querySelector: selector => selector.includes('upload-status') ? status : gallery };
  const picker = { closest: () => form, dataset: { commerceUpload: 'imgs' }, value: 'files', disabled: false };
  const calls = [];
  const controller = createCommerceController({ request: async (path, body, options) => {
    calls.push({ path, body, options });
    if (path === '/api/commerce/query') return {};
    if (path.startsWith('/api/commerce/upload?')) return { id: body.name };
    if (path === '/api/commerce/plan') return { id: body.params.mediaId, hash: 'h' };
    if (body.planId === 'bad.png') return { operation: { data: { status: 'reconcile_required', message: '上传结果未知' } } };
    return { operation: { data: { status: 'completed' } }, result: { fileUrl: 'https://images.example/good.png' } };
  }, dialog: () => {}, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.handle('commerce-goods-edit', { dataset: {} });
  await assert.rejects(controller.upload([new File(['png'], 'good.png', { type: 'image/png' }),
    new File(['png'], 'bad.png', { type: 'image/png' })], picker), /bad.png.*上传结果未知/);
  assert.equal(value.value, 'https://images.example/good.png');
  assert.match(gallery.innerHTML, /good\.png/);
  assert.match(status.textContent, /已选 1 张照片，1 张上传未完成/);
  assert.equal(picker.disabled, false);
  assert.equal(calls.filter(call => call.path.startsWith('/api/commerce/upload?')).every(call => call.options.binary), true);
  assert.equal(calls.filter(call => call.path === '/api/commerce/execute').length, 2);
  await controller.handle('commerce-photo-remove', { closest: () => form, dataset: { field: 'imgs', index: '0' } });
  assert.equal(value.value, '');
  assert.equal(gallery.innerHTML, '');
});

test('closing the photo form during staging stops remote upload and leaves the new editor untouched', async () => {
  let resolveStage;
  let dirty = false;
  const calls = [], value = { value: '' }, status = {};
  const form = { isConnected: true, elements: { namedItem: () => value }, querySelector: () => status };
  const picker = { closest: () => form, dataset: { commerceUpload: 'imgs' } };
  const controller = createCommerceController({ request: async (path) => {
    calls.push(path);
    if (path === '/api/commerce/query') return {};
    return new Promise(resolve => { resolveStage = resolve; });
  }, dialog: () => {}, redraw: () => {}, toast: () => {}, setDirty: value => { dirty = value; } });
  await controller.handle('commerce-goods-edit', { dataset: {} });
  const upload = controller.upload([new File(['png'], 'coin.png', { type: 'image/png' })], picker);
  // 原生 dialog 关闭后仍连接 DOM；必须作废编辑上下文并解除离开页面的阻挡。
  assert.equal(dirty, true);
  controller.cancelEdit();
  assert.equal(dirty, false);
  resolveStage({ id: 'media-1' });
  await upload;
  assert.equal(value.value, '');
  assert.equal(calls.includes('/api/commerce/plan'), false);
});


test('address edits retain and expose the apartment information in the form and confirmation', async () => {
  let content;
  const controller = createCommerceController({ request: async (_path, body) => body.action === 'trade.addresses.detail'
    ? { detail: { firstName: 'Ada', lastName: 'L', additionalAddressInfo: 'Apt 2', countryCode: 'US' } }
    : { list: [{ code: 'US', name: 'United States' }] },
    dialog: (_title, body) => { content = body; }, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.handle('commerce-address-edit', { dataset: { id: '12' } });
  assert.match(content, /name="additionalAddressInfo"[^>]*value="Apt 2"/);
  assert.match(commerceSummary({ changes: { additionalAddressInfo: 'Apt 2' } }), /补充地址.*Apt 2/);
});


test('unknown membership checkout offers only an explicit continuation of the original request', async () => {
  const operation = { id: 'member-op', data: { action: 'memberships.checkout', status: 'reconcile_required',
    scope: { product: { amount: 3999, currency: 'usd', currencyExponent: 2, entitlementSpec: { durationUnit: 'year', durationCount: 1 } } } } };
  const html = renderCommercePage({ page: 'membership' }, { tab: 'history', data: { operations: [operation] } });
  assert.match(html, /commerce-resume-membership/);
  assert.doesNotMatch(html, /commerce-replan/);
  const writes = [];
  let content, actions;
  const controller = createCommerceController({ request: async (path, body) => {
    writes.push({ path, body });
    if (path.endsWith('/history')) return { operations: [operation] };
    return { operation: { ...operation, data: { ...operation.data, status: 'completed' } } };
  }, dialog: (_title, body, buttons) => { content = body; actions = buttons; }, redraw: () => {}, toast: () => {}, setDirty: () => {} });
  await controller.handle('commerce-resume-membership', { dataset: { id: 'member-op' } });
  assert.match(content, /39\.99/);
  assert.match(actions, /commerce-confirm-resume-membership/);
  assert.equal(writes.some(w => w.path.endsWith('/resume-membership')), false);
  await controller.handle('commerce-confirm-resume-membership', { dataset: {} });
  assert.deepEqual(writes.at(-1), { path: '/api/commerce/resume-membership', body: { operationId: 'member-op' } });
});
