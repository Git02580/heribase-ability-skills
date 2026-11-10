import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.location = { hash: '', pathname: '/', search: '' };
globalThis.sessionStorage = { getItem: () => '', setItem: () => {} };
const { render } = await import('../assets/workbench/views.js');

const operation = (id, taskKey, label) => ({
  id,
  data: { kind: 'identify', taskKey, label, status: 'completed', message: `${label}已完成`, itemResults: [] },
});
const model = (pageTask) => ({
  route: { page: 'operations', ...(pageTask ? { task: pageTask } : {}) },
  task: pageTask ? { manifest: { task_key: pageTask, display_name: `${pageTask} 整理` } } : null,
  workspace: {
    tasks: [],
    operations: [operation('op-current', 'task-current', '当前任务识别'), operation('op-other', 'task-other', '其他任务识别')],
    queryLogs: [{ id: 'query-error', data: { argv: ['trade', 'seller', 'account'], status: 'failed', error: { code: 'API_ERROR', message: '查询失败' } } }],
  },
});

test('task execution history filters by task and links back to the global list', () => {
  const html = render(model('task-current'));
  assert.match(html, /task-current 整理 · 执行记录/);
  assert.match(html, /当前任务识别/);
  assert.doesNotMatch(html, /其他任务识别/);
  assert.doesNotMatch(html, /CLI 查询异常日志/);
  assert.match(html, /href="#operations"[^>]*>查看全部执行记录/);
});

test('global execution history continues to show all tasks and CLI query failures', () => {
  const html = render(model(null));
  assert.match(html, /当前任务识别/);
  assert.match(html, /其他任务识别/);
  assert.match(html, /CLI 查询异常日志/);
});

test('reconciliation history shows the blocked and not-yet-submitted items with a safe continuation action', () => {
  const view = model('task-current');
  view.workspace.operations = [operation('op-current', 'task-current', '当前任务识别')];
  Object.assign(view.workspace.operations[0].data, {
    status: 'reconcile_required',
    scope: [{ localId: 'local-002' }, { localId: 'local-003' }],
    itemResults: [{ localId: 'local-002', status: 'reconcile_required', attempts: 1, error: { code: 'cli_not_completed' } }],
  });

  const html = render(view);

  assert.match(html, /local-002/);
  assert.match(html, /结果待核验/);
  assert.match(html, /local-003/);
  assert.match(html, /尚未执行/);
  assert.match(html, /data-action="operation-inspect"/);
  assert.match(html, /data-action="operation-reconcile-identification"/);
  assert.doesNotMatch(html, /data-action="operation-resume"/);
});
