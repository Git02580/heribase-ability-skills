import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const app = await readFile(new URL('../assets/workbench/app.js', import.meta.url), 'utf8');
const routeFunction = app.slice(app.indexOf('function route() {'), app.indexOf('\nfunction toast('));

function resolve(hash) {
  const replacements = [];
  const context = {
    location: { hash },
    history: { replaceState: (_state, _title, target) => replacements.push(target) },
    URLSearchParams,
    titles: { add: '添加钱币', pairing: '整理配对', library: '我的收藏', operations: '执行记录' },
    href: (page, task, item) => `#${page}${task ? `?${new URLSearchParams({ task, ...(item ? { item } : {}) })}` : ''}`,
  };
  const route = vm.runInNewContext(`${routeFunction}\nroute()`, context);
  return { route: JSON.parse(JSON.stringify(route)), replacements };
}

test('saved pairing link opens the same coin in the add flow without another legacy step', () => {
  const result = resolve('#pairing?task=collection-1&item=collection-1%3Alocal-001');
  assert.deepEqual(result.route, { page: 'add', task: 'collection-1', item: 'collection-1:local-001' });
  assert.deepEqual(result.replacements, ['#add?task=collection-1&item=collection-1%3Alocal-001']);
});

test('task-level pairing and old import links both use the single intake', () => {
  for (const page of ['pairing', 'import']) {
    assert.deepEqual(resolve(`#${page}?task=collection-1`), {
      route: { page: 'add', task: 'collection-1', item: null },
      replacements: ['#add?task=collection-1'],
    });
  }
});

test('ordinary add, collection and operation routes retain their existing target', () => {
  for (const page of ['add', 'library', 'operations']) {
    const result = resolve(`#${page}?task=collection-1`);
    assert.equal(result.route.page, page);
    assert.deepEqual(result.replacements, []);
  }
});

test('an in-flight preflight defers opening the linked coin without consuming the link', () => {
  const start = app.indexOf('queueMicrotask(() => {', app.indexOf('function draw()'));
  const end = app.indexOf('\n    });', start);
  const callback = app.slice(start + 'queueMicrotask(() => {'.length, end);
  let opened = 0;
  const item = { local_id: 'task:coin', status: 'active' };
  const state = { busy: true, task: { manifest: { task_key: 'task' }, items: [item] } };
  const context = vm.createContext({
    route: () => ({ page: 'add', task: 'task', item: 'task:coin' }),
    add: { state, needsPlan: false, openPhotos: () => { assert.equal(state.busy, false); opened++; } },
    editablePhotos: (value) => value === item,
    hasPendingAdd: () => false,
    document: { querySelector: () => null },
  });
  vm.runInContext(`let addPhotoRoute = null; function openLinkedPhoto() { ${callback} }`, context);
  vm.runInContext('openLinkedPhoto()', context);
  assert.equal(opened, 0);
  assert.equal(vm.runInContext('addPhotoRoute', context), null);
  state.busy = false;
  vm.runInContext('openLinkedPhoto()', context);
  assert.equal(opened, 1);
  vm.runInContext('openLinkedPhoto()', context);
  assert.equal(opened, 1);
});
