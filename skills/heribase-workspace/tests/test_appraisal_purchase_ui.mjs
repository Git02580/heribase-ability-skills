import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.location = { hash: '', pathname: '/', search: '' };
globalThis.sessionStorage = { getItem: () => '', setItem: () => {} };
const { appraisalPurchaseControl } = await import('../assets/workbench/views.js');
const service = { name: 'HeriBase', appraiserType: 1, appraiserId: 0 };

// 已有订单不能覆盖零次数的购买入口；订单恢复操作仍须可用。
for (const status of ['awaiting_payment', 'fulfillment_pending', 'closed']) {
  test(`zero credits keep the purchase entry alongside a ${status} order`, () => {
    const html = appraisalPurchaseControl(service, 0, [{ id: 'order-1', data: { service, status } }]);
    assert.match(html, /data-action="appraisal-purchase-guide"/);
    if (status === 'awaiting_payment') assert.match(html, /data-action="appraisal-purchase-resume"/);
    if (status === 'fulfillment_pending') assert.match(html, /data-action="appraisal-purchase-refresh"/);
  });
}

test('both numeric and string zero credits offer purchase', () => {
  for (const credits of [0, '0']) {
    assert.match(appraisalPurchaseControl(service, credits), /data-action="appraisal-purchase-guide"/);
  }
});

test('available or unknown credits do not become zero-credit purchase prompts', () => {
  for (const credits of [2, '2', null, undefined, '', 'unavailable']) {
    assert.doesNotMatch(appraisalPurchaseControl(service, credits), /data-action="appraisal-purchase-guide"/);
  }
});

test('purchase requires a selected service and keeps other services orders separate', () => {
  assert.doesNotMatch(appraisalPurchaseControl(null, 0), /data-action="appraisal-purchase-guide"/);
  const html = appraisalPurchaseControl(service, 0, [{
    id: 'different-service', data: { service: { appraiserType: 5, appraiserId: 0 }, status: 'awaiting_payment' },
  }]);
  assert.match(html, /data-action="appraisal-purchase-guide"/);
  assert.doesNotMatch(html, /different-service|appraisal-purchase-resume/);
});
