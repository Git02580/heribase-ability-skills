import test from 'node:test';
import assert from 'node:assert/strict';
import { bridgeActionLabels, bridgeDeliveryHint, continuationSummary, continuationRequest, hostDisplayTitle, hostOptionLabel, INBOX_PROMPT, copyInboxPrompt } from '../assets/workbench/bridge.js';

test('bridge actions distinguish freeform requests from the fixed organization workflow without implying immediate delivery', () => {
  assert.deepEqual(bridgeActionLabels(), { request: '提交请求', continuation: '提交整理任务' });
  assert.match(bridgeDeliveryHint({ connected: true }), /保存到 inbox/);
  assert.match(bridgeDeliveryHint({ connected: false }), /保留在 inbox/);
  assert.match(continuationSummary, /停在配对审核/);
  assert.match(continuationSummary, /不会自动识别或收藏/);
});

test('inbox reminder copies the fixed prompt and reports clipboard failures safely', async () => {
  assert.equal(INBOX_PROMPT, '检查工作台 inbox，继续处理待办。');

  let copied;
  assert.equal(await copyInboxPrompt(async (text) => { copied = text; }), true);
  assert.equal(copied, INBOX_PROMPT);
  assert.equal(await copyInboxPrompt(undefined), false);
  assert.equal(await copyInboxPrompt(async () => { throw new Error('clipboard denied'); }), false);
});

test('host selector prefers the conversation title while retaining a short id and online state', () => {
  const host = {
    host: 'codex',
    conversation: '01a0ccf1-6af5-7d20-9610-c6a8ce93adc8',
    conversationTitle: '整理 batch_06 硬币资料',
    connected: true,
  };

  assert.equal(hostDisplayTitle(host), '整理 batch_06 硬币资料');
  assert.match(hostOptionLabel(host), /codex · 整理 batch_06 硬币资料 · 在线/);
  assert.match(hostOptionLabel(host), /01a0ccf1…ce93adc8/);
});

test('host selector falls back to the conversation id until a title is registered', () => {
  const host = { host: 'codex', conversation: 'thread-1', conversationTitle: '', connected: false };
  assert.equal(hostDisplayTitle(host), 'thread-1');
  assert.match(hostOptionLabel(host), /codex · thread-1 · 离线/);
});

test('continuation request is task-scoped and contains only the permitted organization workflow', () => {
  const request = continuationRequest(
    { manifest: { task_key: '20260924-1231-collection', revision: 7 } },
    { local_id: '20260924-1231-collection:local-001' },
    'host-current',
    '请解析当前表格，建立候选并停在配对审核。',
    'command-1',
  );
  assert.deepEqual(request, {
    commandId: 'command-1',
    bindingId: 'host-current',
    taskId: '20260924-1231-collection',
    objectId: '20260924-1231-collection:local-001',
    intent: 'task.continue',
    message: '请解析当前表格，建立候选并停在配对审核。',
    payload: {
      workflow: 'collection.organize',
      steps: ['parse_spreadsheet', 'build_table_candidates', 'associate_obverse_reverse_images'],
      stopAfter: 'pairing_review',
      expectedRevision: 7,
    },
  });
});

test('continuation refuses a task without a persisted revision', () => {
  assert.throws(() => continuationRequest({ manifest: { task_key: 'task' } }, null, 'host', '继续', 'command'), /任务版本/);
});
