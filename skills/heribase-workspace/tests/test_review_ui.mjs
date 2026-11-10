import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.location = { hash: '', pathname: '/', search: '' };
globalThis.sessionStorage = { getItem: () => '', setItem: () => {} };
const { render } = await import('../assets/workbench/views.js');
const item = {
  local_id: 't:a',
  item_key: 'local-01',
  version: 1,
  status: 'active',
  evidence: [
    { source_id: 'front', role: 'obverse' },
    { source_id: 'back', role: 'reverse' },
  ],
  organization: {},
  active_identification: { status: 'succeeded', snapshot_id: 's' },
  recognitionResult: {
    title: 'Finland 5 penniä 1898',
    year: '1898',
    mintMark: 'None',
    referenceImages: ['https://cdn.heritcoin.com/front.png', 'https://cdn.heritcoin.com/back.png'],
    obverseReverseInfo: { frontInfo: { img: 'https://cdn.heritcoin.com/front.png' }, backInfo: { img: 'https://cdn.heritcoin.com/back.png' } },
    attributes: [
      { name: 'weight', value: '6.4 g' },
      { name: 'Unknown catalog', value: '<script>unsafe</script>' },
    ],
  },
  reviewDetails: { weight: '6.38' },
  reviewIssues: [],
  reviewHistory: [],
};
function model(value = item) {
  return {
    route: { page: 'review', task: 't', item: 't:a' },
    workspace: { notes: [] },
    task: {
      manifest: { task_key: 't', display_name: 'test' },
      items: [value],
      sources: [
        { source_id: 'front', origin: { original_name: 'front.jpg' } },
        { source_id: 'back', origin: { original_name: 'back.jpg' } },
      ],
    },
    allTasks: [],
  };
}
test('review renders both sides with their face-specific references and escapes unknown attributes', () => {
  const html = render(model());
  assert.ok(html.includes('https://cdn.heritcoin.com/front.png'));
  assert.ok(html.includes('https://cdn.heritcoin.com/back.png'));
  assert.ok(html.includes('6.4 g'));
  assert.ok(html.includes('6.38'));
  assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
  assert.ok(!html.includes('<script>unsafe</script>'));
});
test('unknown-face references remain in a separate gallery, unsafe URLs never become image sources', () => {
  const value = {
    ...item,
    recognitionResult: {
      ...item.recognitionResult,
      obverseReverseInfo: null,
      referenceImages: ['https://cdn.heritcoin.com/unknown.png', 'javascript:alert(1)', 'http://127.0.0.1/internal'],
    },
  };
  const html = render(model(value));
  assert.ok(html.includes('面别未标明'));
  assert.ok(html.includes('https://cdn.heritcoin.com/unknown.png'));
  assert.ok(!html.includes('src="javascript:'));
  assert.ok(!html.includes('src="http://127.0.0.1'));
});

test('library cards, rows and search use the current recognition year without requiring resolved fields', () => {
  const task = model().task;
  const base = {
    ...model(), route: { page: 'library' }, allTasks: [task], filter: 'collected',
    workspace: { collectionIndex: [{ batchId: 't', candidateId: 'local-01', collectionUri: 'collection-1' }] },
  };
  for (const libraryView of ['cards', 'table']) {
    const html = render({ ...base, libraryView, query: '1898' });
    assert.ok(html.includes('Finland 5 penniä 1898'));
    assert.doesNotMatch(html, /年份待确认|这里暂时没有匹配记录/);
  }
});

test('library year prefers resolved facts, falls back to the collection index and never infers from a title', () => {
  const library = (value, index = []) => {
    const task = model(value).task;
    return render({ ...model(value), route: { page: 'library' }, allTasks: [task], workspace: { collectionIndex: index } });
  };
  assert.match(library({ ...item, resolved_fields: { year: { value: '1900' } } }), /<p>1900<\/p>/);
  assert.match(library({ ...item, active_identification: { status: 'stale' } }), /年份待确认/);
  assert.match(library({ ...item, active_identification: null }, [{ batchId: 't', candidateId: 'local-01', collectionUri: 'collection-1', year: '1899' }]), /<p>1899<\/p>/);
  assert.match(library({ ...item, recognitionResult: { title: 'Finland 5 penniä 1898' } }), /年份待确认/);
});

test('new task defaults to a local date-time name and keeps a user-edited name', () => {
  const base = {
    route: { page: 'import' },
    workspace: { notes: [] },
    files: [],
    allTasks: [],
  };
  const defaultHtml = render(base);
  assert.match(defaultHtml, /id="task-name"[^>]*value="\d{8}-\d{4}-钱币整理"/);

  const editedHtml = render({ ...base, importName: '家族旧币整理' });
  assert.match(editedHtml, /id="task-name"[^>]*value="家族旧币整理"/);
});

test('appraisal always offers purchase when the selected service has zero credits', () => {
  const html = render({
    route: { page: 'appraisal', task: 't', item: 't:a' },
    workspace: { notes: [], appraisals: [], purchases: [] },
    appraisalServices: {
      experts: [{ name: 'HeriBase', appraiserType: 1, appraiserId: 0, duration: '7 Days' }],
      selected: { name: 'HeriBase', appraiserType: 1, appraiserId: 0, duration: '7 Days' },
      // 服务端有时以字符串返回次数；界面必须与数字 0 一致处理。
      credits: { remainingTimes: '0' },
    },
    task: {
      manifest: { task_key: 't', display_name: 'test' },
      items: [{ ...item, active_identification: null, review_projection: null }],
      sources: [
        { source_id: 'front', mime_type: 'image/jpeg', origin: { original_name: 'front.jpg' } },
        { source_id: 'back', mime_type: 'image/jpeg', origin: { original_name: 'back.jpg' } },
      ],
    },
    allTasks: [],
  });
  assert.ok(html.includes('data-action="appraisal-purchase-guide"'));
  assert.ok(html.includes('暂时没有可用次数'));
});

test('tracking page keeps unpaid tracking-credit orders recoverable after navigation', () => {
  const html = render({
    route: { page: 'tracking' },
    workspace: {
      notes: [], tracking: [], trackingPurchases: [
        {
          id: 'tracking-order-1',
          data: { status: 'awaiting_payment', title: 'Finland 5 penniä 1898',
            product: { times: 10, amount: 1999, currency: 'usd', currencyExponent: 2 },
            taskKey: '20261009-test', localId: '20261009-test:coin-1' },
        },
        {
          id: 'tracking-order-2',
          data: { status: 'granted', title: 'USA 1 cent 1909',
            product: { times: 5 }, taskKey: '20261009-test', localId: '20261009-test:coin-2' },
        },
      ],
    },
    allTasks: [],
  });
  assert.ok(html.includes('追踪位订单待付款'));
  assert.ok(html.includes('data-action="tracking-purchase-resume"'));
  assert.ok(html.includes('data-action="tracking-purchase-refresh"'));
  assert.ok(html.includes('data-action="tracking-purchase-continue"'));
  assert.ok(html.includes('返回藏品'));
});

// 执行真实刷新函数，以两个交错响应验证切换服务的竞态，而不模拟刷新算法。
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
test('late appraisal credits cannot overwrite a newly selected service or its purchase controls', async () => {
  const source = await readFile(new URL('../assets/workbench/app.js', import.meta.url), 'utf8');
  const fn = source.slice(source.indexOf('async function refreshAppraisalCredits('), source.indexOf('async function refresh('));
  const responses = [];
  const status = { textContent: '' }, controls = { innerHTML: '' };
  const c = vm.createContext({
    model: { appraisalServices: null, workspace: { purchases: [] } },
    appraisalCreditRequest: 0, dirty: true,
    choice: { appraiserType: 1, appraiserId: 0 },
    route: () => ({ page: 'appraisal', task: 't', item: 't:a' }),
    api: { request: () => new Promise(resolve => responses.push(resolve)) },
    document: { querySelector: id => id === '#appraisal-credit-status' ? status : controls },
    creditStatusText: s => s.selected.name,
    appraisalPurchaseControl: s => s.name,
    hasNoAppraisalCredits: n => n === 0,
    draw: () => { throw new Error('Cannot redraw unsaved materials'); },
  });
  vm.runInContext('function selectedAppraisalService(){return choice;}' + fn, c);
  const first = c.refreshAppraisalCredits();
  c.choice = { appraiserType: 5, appraiserId: 0 };
  const second = c.refreshAppraisalCredits();
  responses[1]({selected:{...c.choice,name:'新服务'},credits:{remainingTimes:0}});
  await second;
  responses[0]({selected:{appraiserType:1,appraiserId:0,name:'旧服务'},credits:{remainingTimes:2}});
  await first;
  assert.equal(status.textContent, '新服务');
  assert.equal(controls.innerHTML, '新服务');
  assert.equal(c.model.appraisalServices.selected.appraiserType, 5);
});
