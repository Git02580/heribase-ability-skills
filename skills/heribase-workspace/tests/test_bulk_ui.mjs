import test from 'node:test';
import assert from 'node:assert/strict';
import { selectionFor, filteredItems, eligibleForIdentification } from '../assets/workbench/bulk.js';
const items = [
  {
    local_id: 'a',
    status: 'active',
    resolved_fields: { name: { value: '澳大利亚' } },
    organization: { pairing_state: 'confirmed' },
    evidence: [
      { source_id: '1', role: 'obverse', is_primary: true },
      { source_id: '2', role: 'reverse', is_primary: true },
    ],
  },
  { local_id: 'b', status: 'active', organization: { pairing_state: 'needs_review' }, attention_flags: ['identity_conflict'], evidence: [] },
  { local_id: 'c', status: 'active', review_projection: { decision: 'exclude' }, evidence: [] },
];
test('selection survives focus and filter changes but cannot leak into another stage or task', () => {
  const m = { route: { page: 'pairing' }, task: { manifest: { task_key: 'one' }, items } };
  const s = selectionFor(m);
  s.ids.add('a');
  s.filter = 'issues';
  m.route.item = 'b';
  assert.deepEqual([...selectionFor(m).ids], ['a']);
  assert.deepEqual(
    filteredItems(m).map((i) => i.local_id),
    ['b', 'c'],
  );
  m.route.page = 'review';
  assert.equal(selectionFor(m).ids.size, 0);
  selectionFor(m).ids.add('b');
  m.task.manifest.task_key = 'two';
  assert.equal(selectionFor(m).ids.size, 0);
});
test('search and review filters preserve explicit selection and exclude stale collect decisions', () => {
  const m = {
    route: { page: 'review' },
    task: { manifest: { task_key: 'one' }, items: [...items, { local_id: 'd', evidence: [], review_projection: { decision: 'collect', stale: true } }] },
  };
  const s = selectionFor(m);
  s.ids.add('a');
  s.query = '澳大利亚';
  assert.deepEqual(
    filteredItems(m).map((i) => i.local_id),
    ['a'],
  );
  s.query = '';
  s.filter = 'collect';
  assert.deepEqual(filteredItems(m), []);
  assert.deepEqual([...s.ids], ['a']);
});
test('identification selection excludes incomplete evidence, excluded reviews, and successful results', () => {
  assert.equal(eligibleForIdentification(items[0]), true);
  assert.equal(eligibleForIdentification({ ...items[0], review_projection: { decision: 'exclude' } }), false);
  assert.equal(eligibleForIdentification({ ...items[0], active_identification: { status: 'succeeded' } }), false);
  assert.equal(eligibleForIdentification(items[1]), false);
});
test('non-active candidates and non-primary assignments never enter identification selection', () => {
  assert.equal(eligibleForIdentification({ ...items[0], status: 'identity_conflict' }), false);
  assert.equal(eligibleForIdentification({ ...items[0], status: 'source_incomplete' }), false);
  assert.equal(
    eligibleForIdentification({
      ...items[0],
      organization: {
        pairing_state: 'confirmed',
        source_assignment: [
          { source_id: 'missing', role: 'obverse' },
          { source_id: '2', role: 'reverse' },
        ],
      },
    }),
    false,
  );
});

// 执行应用中的真实异步刷新函数；延迟网络响应，模拟取件期间用户开始改方向。
// 删除响应后的草稿检查应使该测试失败，而不是通过模拟 draw 的行为掩盖刷新。
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
test('in-flight snapshot cannot redraw over newly edited pairing directions', async () => {
  const source = await readFile(new URL('../assets/workbench/app.js', import.meta.url), 'utf8');
  const refreshSource = source.slice(source.indexOf('async function refresh('), source.indexOf('async function change('));
  let deliver;
  const pending = new Promise((r) => {
    deliver = r;
  });
  const c = vm.createContext({
    dirty: false,
    pairDirty: false,
    deferredRefresh: false,
    refreshing: null,
    model: { cursor: 0 },
    bridge: { open: false },
    draws: 0,
    api: { snapshot: () => pending },
    document: { querySelector: () => ({ textContent: '' }) },
  });
  vm.runInContext('function draw(){draws++}' + refreshSource, c);
  const running = c.refresh();
  c.pairDirty = true;
  deliver({ tasks: [], cursor: 2 });
  await running;
  assert.equal(c.draws, 0);
  assert.equal(c.deferredRefresh, true);
});

test('empty identification selection offers ready visible items, explicit selection never expands', async () => {
  const { identificationSelection } = await import('../assets/workbench/bulk.js');
  const m = { route: { page: 'identify' }, task: { manifest: { task_key: 'one' }, items: [...items, { ...items[0], local_id: 'd' }] } };
  assert.deepEqual(identificationSelection(m), ['a', 'd']);
  selectionFor(m).ids.add('d');
  assert.deepEqual(identificationSelection(m), ['d']);
  selectionFor(m).ids.clear();
  selectionFor(m).query = 'not found';
  assert.deepEqual(identificationSelection(m), []);
});
test('pairing continuation selects only eligible items in the completed scope, once and for the same task', () => {
  const m = { route: { page: 'pairing' }, task: { manifest: { task_key: 'one' }, items: [...items, { ...items[0], local_id: 'd' }] } };
  selectionFor(m).ids.add('d');
  m.identificationHandoff = { taskKey: 'one', localIds: ['a', 'b'] };
  m.route.page = 'identify';
  assert.deepEqual([...selectionFor(m).ids], ['a']);
  selectionFor(m).ids.clear();
  assert.equal(selectionFor(m).ids.size, 0);
  m.identificationHandoff = { taskKey: 'one', localIds: ['a'] };
  m.task.manifest.task_key = 'two';
  assert.equal(selectionFor(m).ids.size, 0);
});
