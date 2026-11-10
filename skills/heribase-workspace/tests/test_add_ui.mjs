import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { createAddController, renderAdd, identificationNotice, friendlyAddError, hasPendingAdd, addItem, addWorkSummary, addBatchComplete, addActivity, availablePhotoSources, photoDraftProblem, editablePhotos, canConfirmPhotoPair } from '../assets/workbench/add.js';

const copy = (value) => JSON.parse(JSON.stringify(value));
const photo = (name) => ({ name, size: 42, type: 'image/jpeg' });
const memory = () => {
  const values = new Map();
  return { getItem: (key) => values.get(key) || null, setItem: (key, value) => values.set(key, value) };
};
function fixture({ storage = memory(), collectionFinished, changed } = {}) {
  let sequence = 0;
  const service = {
    task: { manifest: { task_key: 'coin-one', revision: 0 }, sources: [], items: [] },
    operations: [], calls: [], lastPlan: null, loseIdentify: false, loseCollect: false, keepUnknown: false, planFailure: null,
  };
  service.request = async (path, body, options) => {
    service.calls.push({ path, body: body && copy(body), options });
    if (path === '/api/tasks/create') return copy(service.task);
    if (path.startsWith('/api/connector/photo?')) {
      assert.equal(options.binary, true);
      const query = new URLSearchParams(path.split('?')[1]);
      assert.equal(Number(query.get('revision')), service.task.manifest.revision);
      const item = service.task.items.find((value) => value.local_id === query.get('localId'));
      if (query.get('mode') === 'stage') {
        const source = { source_id: `source-${service.task.sources.length + 1}`, origin: { original_name: body.name }, mime_type: 'image/jpeg', sha256: body.hash || body.name };
        service.task.sources.push(source);
        service.task.manifest.revision++;
        return { revision: service.task.manifest.revision, source };
      }
      const source = { source_id: `source-${service.task.sources.length + 1}`, origin: { original_name: body.name }, mime_type: 'image/jpeg' };
      service.task.sources.push(source);
      const roles = item.organization.source_assignment || item.evidence;
      item.organization = { ...item.organization, pairing_state: 'confirmed', source_assignment: [...roles, { source_id: source.source_id, role: query.get('side') }] };
      item.evidence.push({ source_id: source.source_id, role: query.get('side'), is_primary: true });
      item.status = 'active'; item.attention_flags = [];
      service.task.manifest.revision++;
      return { revision: service.task.manifest.revision, source };
    }
    if (path.startsWith('/api/upload?')) {
      assert.equal(options.binary, true);
      const query = new URLSearchParams(path.split('?')[1]);
      assert.equal(Number(query.get('revision')), service.task.manifest.revision);
      const source = { source_id: `source-${service.task.sources.length + 1}`, origin: { original_name: body.name }, mime_type: body.type || 'image/jpeg', sha256: body.hash || body.name };
      service.task.sources.push(source);
      service.task.manifest.revision++;
      return { revision: service.task.manifest.revision, source };
    }
    if (path.startsWith('/api/task?')) return copy(service.task);
    if (path === '/api/connector/organize') return { data: { taskKey: body.taskKey, status: 'queued' } };
    if (path === '/api/connector/prepare') {
      assert.equal(body.expectedRevision, service.task.manifest.revision);
      const assignment = [{ source_id: body.obverseSourceId, role: 'obverse' }, { source_id: body.reverseSourceId, role: 'reverse' }];
      if (JSON.stringify(service.task.items[0]?.organization.source_assignment) !== JSON.stringify(assignment)) {
        service.task.items = [{ local_id: 'coin-one:item', item_key: 'coin', status: 'active', organization: { pairing_state: 'confirmed', source_assignment: assignment }, evidence: assignment.map((entry) => ({ ...entry, is_primary: true })) }];
        service.task.manifest.revision++;
      }
      return copy(service.task);
    }
    if (path === '/api/connector/photos') {
      assert.equal(body.expectedRevision, service.task.manifest.revision);
      const item = service.task.items.find((value) => value.local_id === body.localId);
      const chosen = [body.obverseSourceId, body.reverseSourceId];
      const [front, back] = chosen.map((id) => service.task.sources.find((source) => source.source_id === id));
      assert.ok(front && back && front.source_id !== back.source_id && (!front.sha256 || front.sha256 !== back.sha256));
      const old = item.evidence.map((entry) => entry.source_id);
      for (const owner of service.task.items.filter((value) => value !== item)) {
        owner.evidence = owner.evidence.filter((entry) => !chosen.includes(entry.source_id));
        if (owner.organization?.source_assignment) owner.organization.source_assignment = owner.organization.source_assignment.filter((entry) => !chosen.includes(entry.source_id));
      }
      item.source_refs = [...new Set([...(item.source_refs || []), ...old, ...chosen])];
      item.evidence = [{ source_id: front.source_id, role: 'obverse', is_primary: true }, { source_id: back.source_id, role: 'reverse', is_primary: true }];
      item.organization = { ...item.organization, pairing_state: 'confirmed', source_assignment: copy(item.evidence) };
      item.status = 'active'; item.attention_flags = [];
      service.task.manifest.revision++;
      return copy(service.task);
    }
    if (path === '/api/connector/identification-plan') {
      if (service.planFailure) throw service.planFailure;
      service.lastPlan = { taskKey: 'coin-one', revision: body.expectedRevision, hash: `hash-${body.expectedRevision}`, items: body.localIds.map((localId) => ({ localId, title: '钱币' })), account: { subject: 'test-account' } };
      return service.lastPlan;
    }
    if (path === '/api/snapshot') return { operations: copy(service.operations) };
    if (path === '/api/connector/identify' || path === '/api/connector/collect' || path === '/api/connector/collect-batch') {
      const kind = path.endsWith('/identify') ? 'identify' : 'collect';
      assert.equal(body.expectedRevision, service.task.manifest.revision);
      if (kind === 'identify') assert.equal(body.planHash, `hash-${body.expectedRevision}`);
      else for (const value of body.items || [body]) assert.equal(value.snapshotId, service.task.items.find((item) => item.local_id === value.localId).active_identification.snapshot_id);
      const lose = kind === 'identify' ? service.loseIdentify : service.loseCollect;
      const operation = { id: body.commandId, revision: 2, data: { kind, taskKey: body.taskKey, request: copy(body), status: lose && service.keepUnknown ? 'reconcile_required' : 'completed', message: '' } };
      service.operations.unshift(operation);
      if (!(lose && service.keepUnknown)) {
        const ids = kind === 'identify' ? body.localIds : (body.items || [body]).map((value) => value.localId);
        for (const item of service.task.items.filter((item) => ids.includes(item.local_id))) {
        if (kind === 'identify') {
          item.active_identification = { status: 'succeeded', snapshot_id: item.local_id === 'coin-one:item' ? 'recognition-exact-1' : `snapshot-${item.local_id}` };
          item.recognitionResult = { title: 'One Franc <test>', year: '1968', mintMark: 'B', attributes: [{ name: 'Country', value: 'Switzerland' }, { name: 'Denomination', value: '1 Franc' }] };
        } else item.collection_projection = { status: 'succeeded', collection_uri: 'collection-exact-1' };
        }
        service.task.manifest.revision++;
      }
      if (lose) throw Object.assign(new Error('response lost'), { code: 'offline', status: 0 });
      return copy(operation);
    }
    throw new Error(`Unexpected request ${path}`);
  };
  const controller = createAddController({ request: service.request, storage, collectionFinished, changed, makeId: () => `intent-${++sequence}`, timezone: () => 'Asia/Shanghai', now: () => new Date('2026-10-19T03:00:00Z') });
  controller.sync(null, [], []);
  return { service, controller, storage };
}
const prepared = async (options) => {
  const result = fixture(options);
  await result.controller.pick('obverse', photo('front.jpg'));
  await result.controller.pick('reverse', photo('back.jpg'));
  return result;
};
const writes = (service) => service.calls.filter((call) => ['/api/connector/identify', '/api/connector/collect', '/api/connector/collect-batch'].includes(call.path));

test('the same upload archives one file or mixed files without requiring side assignment or calling recognition', async () => {
  for (const files of [[photo('one.jpg')], [photo('one.jpg'), photo('two.jpg'), { name: 'coins.xlsx', size: 42, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }]]) {
    const { controller, service, storage } = fixture();
    await controller.upload(files);
    assert.equal(service.calls.filter((call) => call.path === '/api/tasks/create').length, 1);
    assert.equal(service.task.sources.length, files.length);
    assert.equal(service.task.items.length, 0);
    assert.equal(service.calls.some((call) => call.path === '/api/connector/prepare'), false);
    assert.equal(writes(service).length, 0);
    assert.equal(controller.needsPlan, false);
    assert.deepEqual(controller.state.slots, {});
    const resumed = createAddController({ request: service.request, storage });
    resumed.sync('coin-one', [copy(service.task)], []);
    assert.equal(resumed.state.pendingSourceIds.length, files.length);
    const html = renderAdd(resumed.state);
    assert.match(html, new RegExp(`已保存 ${files.length} 份资料`));
    assert.equal((html.match(/type="file"/g) || []).length, 1);
    assert.doesNotMatch(html, /data-add-side|单枚快捷|href="#import"|data-action="add-identify"/);
  }
});

test('partial upload failure retains archived originals and the remaining names across reload without automatic replay', async () => {
  const { service, storage } = fixture();
  let uploads = 0;
  const request = (path, body, options) => {
    if (path.startsWith('/api/upload?') && ++uploads === 2) throw Object.assign(new Error('local connection lost'), { code: 'offline' });
    return service.request(path, body, options);
  };
  const controller = createAddController({ request, storage });
  controller.sync(null, [], []);
  await assert.rejects(controller.upload([photo('one.jpg'), photo('two.jpg'), photo('three.jpg')]));
  assert.equal(service.task.sources.length, 1);
  assert.deepEqual(controller.state.uploadRemainder, ['two.jpg', 'three.jpg']);
  const resumed = createAddController({ request, storage });
  resumed.sync('coin-one', [copy(service.task)], []);
  await resumed.refresh();
  assert.equal(uploads, 2);
  assert.deepEqual(resumed.state.uploadRemainder, ['two.jpg', 'three.jpg']);
  assert.match(renderAdd(resumed.state), /还有 2 份资料尚未确认保存/);
  assert.equal(writes(service).length, 0);
  await resumed.upload([photo('two.jpg')]);
  assert.deepEqual(resumed.state.uploadRemainder, ['three.jpg']);
  assert.equal(service.task.sources.length, 2);
});

test('a valid automatic pair is previewed without being rewritten as a human pairing decision', async () => {
  const { controller, service } = fixture();
  await controller.upload([photo('one.jpg'), photo('two.jpg')]);
  const roles = [{ source_id: 'source-1', role: 'obverse' }, { source_id: 'source-2', role: 'reverse' }];
  service.task.items = [{ local_id: 'coin-one:item', status: 'active', organization: { pairing_state: 'auto_ready', source_assignment: roles }, evidence: roles.map((role) => ({ ...role, is_primary: true, pair_confidence: 0.96 })) }];
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.equal(controller.needsPlan, true);
  await controller.preview();
  assert.equal(service.task.items[0].organization.pairing_state, 'auto_ready');
  assert.equal(service.calls.some((call) => call.path === '/api/connector/prepare'), false);
  assert.equal(writes(service).length, 0);
  service.task.items[0].organization.pairing_state = 'needs_review';
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.equal(controller.needsPlan, false);
  await assert.rejects(controller.preview(), /配对尚需核对/);
  assert.doesNotMatch(renderAdd(controller.state), /data-action="add-identify"/);
});

test('input cannot bypass an operation whose remote outcome is still unknown', async () => {
  const { controller, service } = await prepared();
  service.loseIdentify = true;
  service.keepUnknown = true;
  await assert.rejects(controller.identify());
  const count = service.calls.length;
  await assert.rejects(controller.upload([photo('new.jpg')]), /先核验/);
  assert.equal(service.calls.length, count);
});

test('agent organization appears in the same entry and only then enables the existing confirmed recognition path', async () => {
  const { controller, service } = fixture();
  await controller.upload([photo('one.jpg'), photo('two.jpg')]);
  assert.equal(controller.needsPlan, false);
  const roles = [{ source_id: 'source-1', role: 'obverse' }, { source_id: 'source-2', role: 'reverse' }];
  service.task.items = [{ local_id: 'coin-one:item', status: 'active', organization: { pairing_state: 'confirmed', source_assignment: roles }, evidence: roles.map((role) => ({ ...role, is_primary: true })) }];
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.deepEqual(controller.state.pendingSourceIds, []);
  assert.equal(controller.needsPlan, true);
  await controller.preview();
  assert.equal(writes(service).length, 0);
  assert.match(renderAdd(controller.state), /data-action="add-identify"\s*>识别这 1 枚/);
  await controller.identify();
  assert.equal(writes(service).length, 1);
  assert.match(renderAdd(controller.state), /data-action="add-collect"/);
});

test('new input after recognized work creates a fresh scope instead of changing the prior evidence', async () => {
  const { controller, service, storage } = await prepared();
  await controller.identify();
  const prior = copy(service.task);
  const next = createAddController({ storage, request: (path, body, options) => {
    if (path === '/api/tasks/create') service.task = { manifest: { task_key: 'coin-two', revision: 0 }, sources: [], items: [] };
    return service.request(path, body, options);
  } });
  next.sync('coin-one', [copy(service.task)], copy(service.operations));
  await next.upload([photo('another.jpg')]);
  assert.equal(next.state.taskKey, 'coin-two');
  assert.equal(service.task.sources.length, 1);
  assert.equal(service.task.items.length, 0);
  assert.equal(prior.items[0].active_identification.snapshot_id, 'recognition-exact-1');
  assert.equal(writes(service).length, 1);
});

test('completed multi-item collection checks the original scope projections instead of blocking on an absent single item', () => {
  const state = { task: { items: [{ local_id: 'a', status: 'active', collection_projection: { status: 'succeeded', collection_uri: 'a' } }, { local_id: 'b', status: 'active', collection_projection: { status: 'succeeded', collection_uri: 'b' } }] }, intents: { collect: { status: 'completed', operation: { data: { scope: [{ local_id: 'a' }, { local_id: 'b' }] } } } }, operations: [] };
  assert.equal(hasPendingAdd(state), false);
  delete state.task.items[1].collection_projection;
  assert.equal(hasPendingAdd(state), true);
});

test('multiple organized coins get an inline confirmation without leaving the intake', async () => {
  const { controller, service } = await prepared();
  const second = copy(service.task.items[0]);
  second.local_id = 'coin-one:second';
  second.item_key = 'internal-second-id';
  second.evidence = [{ source_id: 'source-3', role: 'obverse', is_primary: true }, { source_id: 'source-4', role: 'reverse', is_primary: true }];
  second.organization.source_assignment = [{ source_id: 'source-3', role: 'obverse' }, { source_id: 'source-4', role: 'reverse' }];
  service.task.items.push(second);
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.equal(controller.needsPlan, true);
  await controller.preview();
  const html = renderAdd(controller.state);
  assert.equal((html.match(/class="add-coin-card"/g) || []).length, 2);
  assert.match(html, /2 枚可识别/);
  assert.match(html, /data-action="add-identify"[^>]*>识别这 2 枚/);
  assert.doesNotMatch(html, /href="#identify/);
  assert.equal((html.match(/type="file"/g) || []).length, 1);
  assert.doesNotMatch(html, /internal-second-id|单枚快捷|批量上传|href="#import"/);
  assert.equal(writes(service).length, 0);
});

test('upload switches the main area to actual status and leaves one compact multi-file intake in the aside', async () => {
  const { controller, service } = fixture();
  assert.match(renderAdd(controller.state), /上传钱币照片/);
  await controller.upload([photo('one.jpg'), photo('two.jpg')]);
  const summary = addWorkSummary(controller.state);
  assert.equal(summary.phase, 'waiting');
  assert.equal(summary.uploaded, 2);
  assert.equal(summary.unorganized, 2);
  assert.match(summary.message, /等待整理/);
  const html = renderAdd(controller.state);
  const main = html.slice(html.indexOf('class="add-work-main"'), html.indexOf('<aside'));
  const aside = html.slice(html.indexOf('<aside'), html.indexOf('</aside>'));
  assert.match(main, /处理进度/);
  assert.match(main, /等待整理/);
  assert.doesNotMatch(main, /type="file"|正在整理|\d+%/);
  assert.match(aside, /add-intake-compact/);
  assert.match(aside, /type="file" multiple/);
  assert.doesNotMatch(html, /上传钱币照片/);
  assert.equal((html.match(/type="file"/g) || []).length, 1);
  assert.equal(writes(service).length, 0);
  const starts = service.calls.filter((call) => call.path === '/api/connector/organize');
  assert.equal(starts.length, 1);
  assert.equal(starts[0].body.expectedRevision, service.task.manifest.revision);
  service.task.organization = { status: 'running', stage: 'analyzing', message: '正在分析 2 张图片并匹配正反面' };
  controller.sync('coin-one', [copy(service.task)], []);
  assert.equal(addWorkSummary(controller.state).phase, 'organizing');
  assert.match(renderAdd(controller.state), /正在整理照片/);
  assert.doesNotMatch(renderAdd(controller.state), /当前聊天|data-action="add-organize"/);
  service.task.organization = { status: 'failed', message: '整理连接暂不可用，原件保留' };
  controller.sync('coin-one', [copy(service.task)], []);
  assert.equal(addWorkSummary(controller.state).phase, 'failed');
  assert.match(renderAdd(controller.state), /data-action="add-organize"/);
  await controller.organize();
  assert.equal(service.calls.filter((call) => call.path === '/api/connector/organize').at(-1).body.retry, true);
});

test('summary counts original uploads, complete pairs, missing sides and support material independently', () => {
  const sources = Array.from({ length: 5 }, (_, index) => ({ source_id: `source-${index + 1}`, mime_type: 'image/png' }));
  const pair = (id, parent) => {
    const roles = ['obverse', 'reverse'].map((role) => ({ source_id: `${id}-${role}`, role, is_primary: true }));
    sources.push(...roles.map((entry) => ({ source_id: entry.source_id, parent_source_id: parent, mime_type: 'image/png' })));
    return { local_id: id, status: 'active', organization: { pairing_state: 'auto_ready', source_assignment: roles }, evidence: roles };
  };
  const items = [pair('a', 'source-1'), pair('b', 'source-2'), ...['source-3', 'source-4'].map((source_id) => ({ local_id: source_id, status: 'source_incomplete', organization: { pairing_state: 'single_side' }, evidence: [{ source_id, role: 'obverse', is_primary: true }] })), { local_id: 'support', status: 'active', organization: { input_kind: 'promotional_material', pairing_state: 'needs_review' }, evidence: [{ source_id: 'source-5', role: 'other', is_primary: true }] }];
  const state = { taskKey: 'test', task: { sources, items }, slots: {}, intents: {}, operations: [] };
  const summary = addWorkSummary(state);
  assert.deepEqual([summary.phase, summary.uploaded, summary.ready, summary.missing, summary.attention, summary.coins, summary.unorganized], ['ready', 5, 2, 2, 1, 4, 0]);
  assert.equal((renderAdd(state).match(/class="add-coin-card"/g) || []).length, 5);
  sources.push({ source_id: 'new-upload' });
  const updated = addWorkSummary(state);
  assert.equal(updated.phase, 'waiting');
  assert.equal(updated.unorganized, 1);
  assert.doesNotMatch(updated.message, /6 份上传资料已整理/);
  assert.match(updated.message, /已有结果保留/);
  state.intents.identify = { status: 'unknown' };
  assert.equal(addWorkSummary(state).phase, 'reconcile');
  assert.match(renderAdd(state), /type="file" multiple[^>]+disabled/);
});

test('organization of incomplete sources clears their pending upload state without claiming a ready pair', async () => {
  const { controller, service } = fixture();
  await controller.upload([photo('front.jpg')]);
  service.task.items = [{ local_id: 'incomplete', status: 'source_incomplete', organization: { pairing_state: 'single_side' }, evidence: [{ source_id: 'source-1', role: 'obverse', is_primary: true }] }];
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.deepEqual(controller.state.pendingSourceIds, []);
  assert.equal(addWorkSummary(controller.state).phase, 'attention');
  assert.equal(controller.needsPlan, false);
  assert.match(renderAdd(controller.state), /补反面/);
});

async function singleSide(role = 'obverse') {
  const value = fixture();
  await value.controller.upload([photo('existing.jpg')]);
  const roles = [{ source_id: 'source-1', role, is_primary: true }];
  value.service.task.items = [{ local_id: 'coin-one:missing', status: 'source_incomplete', attention_flags: ['source_incomplete'], organization: { pairing_state: 'single_side', source_assignment: roles }, evidence: copy(roles) }];
  value.service.task.manifest.revision++;
  value.controller.sync('coin-one', [copy(value.service.task)], []);
  return value;
}

test('each missing side has a visible upload action and attaches only to its existing coin', async () => {
  for (const role of ['obverse', 'reverse']) {
    const { controller, service } = await singleSide(role);
    const side = role === 'obverse' ? 'reverse' : 'obverse';
    const label = side === 'obverse' ? '补正面' : '补反面';
    service.task.items[0].field_claims = { visual_analysis: { summary: '最初只有一面照片' } };
    const html = renderAdd(controller.state);
    assert.match(html, /<section class="add-result-group"><h3>待补图/);
    assert.ok(html.includes(label));
    assert.ok(html.includes(`data-add-supplement="${side}" data-id="coin-one:missing"`));
    assert.doesNotMatch(html, /可稍后处理|这批资料的处理情况|用“补充资料”/);
    const organizationCount = service.calls.filter((c) => c.path === '/api/connector/organize').length;
    await controller.supplement('coin-one:missing', side, photo('missing.jpg'));
    const call = service.calls.find((c) => c.path.startsWith('/api/connector/photo?'));
    assert.equal(new URLSearchParams(call.path.split('?')[1]).get('side'), side);
    assert.equal(new URLSearchParams(call.path.split('?')[1]).get('localId'), 'coin-one:missing');
    assert.equal(service.task.items.length, 1);
    assert.equal(service.task.items[0].evidence[0].source_id, 'source-1');
    assert.equal(service.calls.filter((c) => c.path === '/api/connector/organize').length, organizationCount);
    assert.equal(addWorkSummary(controller.state).ready, 1);
    assert.equal(addWorkSummary(controller.state).missing, 0);
    assert.match(renderAdd(controller.state), /已按你选择的正反面保存/);
    assert.doesNotMatch(renderAdd(controller.state), /最初只有一面照片/);
    assert.equal(controller.needsPlan, true);
    assert.equal(writes(service).length, 0);
    const resumed = createAddController({ request: service.request, storage: memory() });
    resumed.sync('coin-one', [copy(service.task)], []);
    assert.equal(addWorkSummary(resumed.state).ready, 1);
  }
});

test('lost local supplement reply is recovered by reading the card without another upload', async () => {
  const { service } = await singleSide();
  const controller = createAddController({ storage: memory(), request: async (path, body, options) => {
    const result = await service.request(path, body, options);
    if (path.startsWith('/api/connector/photo?')) throw Object.assign(new Error('reply lost'), { code: 'offline' });
    return result;
  } });
  controller.sync('coin-one', [copy(service.task)], []);
  await controller.supplement('coin-one:missing', 'reverse', photo('missing.jpg'));
  assert.equal(addWorkSummary(controller.state).ready, 1);
  await assert.rejects(controller.supplement('coin-one:missing', 'reverse', photo('another.jpg')), /照片已更新/);
  assert.equal(service.calls.filter((c) => c.path.startsWith('/api/connector/photo?')).length, 1);
  assert.equal(writes(service).length, 0);
});

test('a rejected duplicate stays beside its coin, and a valid retry shows the saved side and next step', async () => {
  const { service } = await singleSide('reverse');
  const storage = memory();
  const controller = createAddController({ storage, request: async (path, body, options) => {
    if (path.startsWith('/api/connector/photo?') && body.name === 'existing.jpg') {
      throw Object.assign(new Error('这张照片已在使用，请选择这枚钱币缺少的另一面'), { code: 'task_validation_failed' });
    }
    return service.request(path, body, options);
  } });
  controller.sync('coin-one', [copy(service.task)], []);
  await assert.rejects(controller.supplement('coin-one:missing', 'obverse', photo('existing.jpg')), /这张照片已在使用/);
  assert.equal(service.task.sources.length, 1);
  assert.equal(controller.state.error, '');
  assert.match(renderAdd(controller.state), /class="add-photo-feedback error" role="alert"><p>这张照片已上传过，请选择缺少的正面。/);
  await controller.refresh();
  assert.equal(controller.state.photoFeedback['coin-one:missing'].status, 'error');
  await controller.supplement('coin-one:missing', 'obverse', photo('missing.jpg'));
  const html = renderAdd(controller.state);
  assert.match(html, /class="add-photo-feedback success" role="status"><p>正面已补好/);
  assert.match(html, /data-action="add-next-step">去识别/);
  assert.doesNotMatch(html, /这张照片已上传过/);
  assert.equal(service.task.items.length, 1);
  assert.equal(controller.needsPlan, true);
  const resumed = createAddController({ storage, request: service.request });
  resumed.sync('coin-one', [copy(service.task)], []);
  assert.match(renderAdd(resumed.state), /正面已补好/);
  assert.equal(writes(service).length, 0);
});

test('supplement cannot overwrite the existing side or change a collected record', async () => {
  const { controller, service } = await singleSide();
  await assert.rejects(controller.supplement('coin-one:missing', 'obverse', photo('replacement.jpg')), /照片已更新/);
  await controller.refresh();
  assert.equal(controller.state.photoFeedback['coin-one:missing'].status, 'error');
  assert.doesNotMatch(renderAdd(controller.state), /正面已补好/);
  const value = service.task.items[0];
  value.collection_projection = { status: 'succeeded', collection_uri: 'existing-collection' };
  controller.sync('coin-one', [copy(service.task)], []);
  await assert.rejects(controller.supplement('coin-one:missing', 'reverse', photo('replacement.jpg')), /照片已更新/);
  assert.equal(service.calls.some((c) => c.path.startsWith('/api/connector/photo?')), false);
});

test('explicit photo roles auto-archive and prepare locally, freezing a read-only plan without remote writes', async () => {
  const { service, controller } = await prepared();
  assert.equal(service.calls.filter((call) => call.path === '/api/tasks/create').length, 1);
  assert.equal(service.task.sources.length, 2);
  assert.deepEqual(service.task.items[0].organization.source_assignment, [{ source_id: 'source-1', role: 'obverse' }, { source_id: 'source-2', role: 'reverse' }]);
  assert.equal(writes(service).length, 0);
  assert.equal(Object.isFrozen(controller.state.plan), true);
  service.lastPlan.items[0].localId = 'tampered-later';
  assert.equal(controller.state.plan.items[0].localId, 'coin-one:item');
  const html = renderAdd(controller.state);
  assert.match(html, /alt="正面"/);
  assert.match(html, /source=source-1/);
  assert.match(html, /alt="反面"/);
  assert.match(html, /source=source-2/);
  assert.match(html, /将上传 2 张照片到 HeriBase/);
  assert.match(html, /剩余次数未返回/);
  assert.match(html, /费用未返回/);
  assert.match(html, /data-action="add-identify"\s*>识别这 1 枚/);
  assert.doesNotMatch(html, /任务名称|建立候选|等待 Agent|inbox/i);
});

test('Start identification submits the frozen exact scope and Add to collection submits the displayed snapshot directly', async () => {
  const { controller, service } = await prepared();
  const revision = controller.state.plan.revision;
  await controller.identify();
  assert.deepEqual(writes(service)[0].body, { taskKey: 'coin-one', expectedRevision: revision, planHash: `hash-${revision}`, localIds: ['coin-one:item'], commandId: 'intent-1' });
  const html = renderAdd(controller.state);
  assert.match(html, /One Franc &lt;test&gt;/);
  assert.match(html, /Switzerland/);
  assert.match(html, /1 Franc/);
  assert.match(html, /1968/);
  assert.match(html, /核对(?:币种、年份和面额)?后加入收藏/);
  assert.match(html, /data-action="add-collect"\s*>加入收藏/);
  await controller.collect();
  assert.deepEqual(writes(service)[1].body, { taskKey: 'coin-one', expectedRevision: revision + 1, localId: 'coin-one:item', snapshotId: 'recognition-exact-1', commandId: 'intent-2' });
  assert.equal(controller.state.completion.count, 1);
  assert.match(renderAdd(controller.state), /上传钱币照片/);
  await controller.collect();
  assert.equal(writes(service).length, 2, 'already collected is never sent again');
  assert.equal(service.calls.some((call) => /tasks\/(review|collection-plan|collect)/.test(call.path)), false);
});

test('a changed revision invalidates a frozen confirmation instead of silently authorizing a newer pair', async () => {
  const { controller, service } = await prepared();
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.equal(controller.state.plan, null);
  await assert.rejects(controller.identify(), /查看本次识别范围/);
  assert.equal(writes(service).length, 0);
  assert.equal(controller.needsPlan, true);
});

test('swapping sides changes both exact media previews and frozen execution roles', async () => {
  const { controller, service } = await prepared();
  await controller.swap();
  assert.equal(controller.state.slots.obverse.sourceId, 'source-2');
  assert.equal(controller.state.slots.reverse.sourceId, 'source-1');
  assert.deepEqual(service.task.items[0].organization.source_assignment, [{ source_id: 'source-2', role: 'obverse' }, { source_id: 'source-1', role: 'reverse' }]);
  const html = renderAdd(controller.state);
  assert.match(html, /source=source-2[^>]+alt="正面"/);
  assert.match(html, /source=source-1[^>]+alt="反面"/);
  assert.equal(controller.state.plan.revision, service.task.manifest.revision);
  assert.equal(writes(service).length, 0);
});

for (const kind of ['identify', 'collect']) {
  test(`${kind} unknown results retain the same persisted command ID across refresh and reload, without replay`, async () => {
    const { controller, service, storage } = await prepared();
    if (kind === 'collect') await controller.identify();
    service[kind === 'identify' ? 'loseIdentify' : 'loseCollect'] = true;
    service.keepUnknown = true;
    await assert.rejects(controller[kind]());
    const original = copy(controller.state.intents[kind].body);
    assert.equal(hasPendingAdd(controller.state), true);
    await controller.refresh();
    const count = writes(service).length;
    const resumed = createAddController({ request: service.request, storage, makeId: () => 'must-never-be-used' });
    resumed.sync('coin-one', [copy(service.task)], copy(service.operations));
    assert.deepEqual(resumed.state.intents[kind].body, original);
    assert.equal(hasPendingAdd(resumed.state), true);
    await assert.rejects(resumed[kind]());
    await assert.rejects(resumed.pick('obverse', photo('replacement.jpg')), /结果尚未确认/);
    assert.equal(writes(service).length, count);
    assert.match(renderAdd(resumed.state), /结果待确认/);
  });
}

test('a lost response followed by exact persisted success is recovered by reads, without a second request', async () => {
  const { controller, service } = await prepared();
  service.loseIdentify = true;
  await controller.identify();
  assert.equal(writes(service).length, 1);
  assert.equal(controller.state.intents.identify.status, 'completed');
  assert.match(renderAdd(controller.state), /One Franc/);
  assert.equal(hasPendingAdd(controller.state), false);
});

test('unknown result with no operation in the latest read remains blocked and keeps its original intent', async () => {
  const { controller, service, storage } = await prepared();
  const request = service.request;
  service.request = request;
  // The proxy rejects the write before a readable receipt; its outcome stays ambiguous.
  const next = createAddController({ storage, request: (path, body, options) => {
    if (path === '/api/connector/identify') throw Object.assign(new Error('lost'), { code: 'offline' });
    return request(path, body, options);
  }, makeId: () => 'ambiguous-original' });
  next.sync('coin-one', [copy(service.task)], []);
  await next.preview();
  await assert.rejects(next.identify(), /请求结果尚未确认/);
  await next.refresh();
  assert.equal(next.state.intents.identify.status, 'unknown');
  assert.equal(next.state.intents.identify.body.commandId, 'ambiguous-original');
  assert.equal(writes(service).length, 0);
});

test('resume by task key reconstructs exact roles and a readable recognized result without names or candidate selection', async () => {
  const { controller, service } = await prepared();
  await controller.identify();
  const resumed = createAddController({ request: service.request, storage: memory() });
  resumed.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.equal(resumed.state.localId, 'coin-one:item');
  assert.equal(resumed.state.slots.reverse.sourceId, 'source-2');
  assert.match(renderAdd(resumed.state), /data-action="add-collect"/);
  assert.equal(writes(service).length, 1);
});

test('a persisted intent from an older draw cannot regress a newer acknowledged operation', async () => {
  const { controller, service } = await prepared();
  await controller.identify();
  const old = copy(service.operations[0]);
  old.revision = 1;
  old.data.status = 'running';
  controller.sync('coin-one', [copy(service.task)], [old]);
  assert.equal(controller.state.intents.identify.status, 'completed');
  assert.equal(hasPendingAdd(controller.state), false);
});

test('quota disclosure distinguishes returned zero credits, consumption, price and unknown fields', () => {
  const html = identificationNotice({ quota: { remainingTimes: 0, requiredTimes: 1 }, cost: { amount: 0, currency: 'USD' } });
  assert.match(html, /剩余 0 次/);
  assert.match(html, /本次使用 1 次/);
  assert.match(html, /费用 0 USD/);
  assert.doesNotMatch(html, /承诺免费/);
});

test('exhausted quota shows real counts and a safe guide instead of promising an upload', () => {
  const eligibility = { allowed: false, dailyLimit: 3, usedTimes: 3, remainingTimes: 0,
    guide: { guideUrl: '/agent/v1/app-guides/page?uri=fixture' } };
  const html = identificationNotice({ items: [{}], eligibility, account: { apiBaseUrl: 'https://api.example.test' } });
  assert.match(html, /今日识别额度已用完/);
  assert.match(html, /已用 3\/3 次/);
  assert.match(html, /https:\/\/api.example.test\/agent\/v1\/app-guides\/page/);
  assert.doesNotMatch(html, /将上传/);
  eligibility.guide.guideUrl = 'https://other.example/agent/v1/app-guides/page?uri=fixture';
  assert.doesNotMatch(identificationNotice({ eligibility, account: { apiBaseUrl: 'https://api.example.test' } }), /other.example/);
});

test('missing local intent persistence blocks a remote write before dispatch', async () => {
  const storage = { getItem: () => null, setItem: () => { throw new Error('blocked'); } };
  const { controller, service } = await prepared({ storage });
  await assert.rejects(controller.identify(), /尚未发送线上操作/);
  assert.equal(writes(service).length, 0);
});

test('account, revision and service errors have actionable user language and retain archived photos', async () => {
  const { controller, service } = await fixture();
  service.planFailure = Object.assign(new Error('raw CLI error'), { code: 'account_required' });
  await controller.pick('obverse', photo('front.jpg'));
  await assert.rejects(controller.pick('reverse', photo('back.jpg')));
  assert.match(controller.state.error, /重新登录 HeriBase/);
  assert.equal(controller.state.slots.obverse.sourceId, 'source-1');
  assert.equal(controller.state.slots.reverse.sourceId, 'source-2');
  assert.equal(controller.needsPlan, false, 'a failed read is not retried in a render loop');
  assert.match(renderAdd(controller.state), /data-action="add-preview"[^>]*>重新检查连接/);
  assert.match(renderAdd(controller.state), /错误详情/);
  assert.match(friendlyAddError({ code: 'revision_conflict' }), /刷新/);
  assert.match(friendlyAddError({ code: 'cli_invalid_output', message: 'raw output' }), /连接暂不可用/);
});

test('new coin clears the current surface while retaining the previous saved session', async () => {
  const { controller, service, storage } = await prepared();
  const previous = service.task.manifest.task_key;
  controller.newCoin();
  assert.equal(controller.state.taskKey, null);
  assert.deepEqual(controller.state.slots, {});
  assert.match(renderAdd(controller.state), /选择照片或表格/);
  const resumed = createAddController({ request: service.request, storage });
  resumed.sync(previous, [copy(service.task)], []);
  assert.equal(resumed.state.slots.obverse.sourceId, 'source-1');
});

test('legacy pairing defaults, preview and selector share the exact same source mapping', async () => {
  globalThis.location = { hash: '', pathname: '/', search: '' };
  globalThis.sessionStorage = { getItem: () => '', setItem: () => {} };
  const { render, pairingSources } = await import('../assets/workbench/views.js');
  const { controller, service } = await prepared();
  const task = copy(service.task);
  task.items[0].organization = { pairing_state: 'needs_review' };
  task.items[0].evidence.forEach((entry) => { entry.role = 'unknown'; });
  assert.deepEqual(pairingSources(task, task.items[0]), { obverse: 'source-1', reverse: 'source-2' });
  const html = render({ route: { page: 'pairing', task: 'coin-one' }, task, workspace: { operations: [] }, allTasks: [task] });
  assert.match(html, /data-pair-photo="reverse"[^]*?source=source-2/);
  assert.match(html, /id="reverse-source"[^]*?<option value="source-2" selected/);
  const source = await readFile(new URL('../assets/workbench/app.js', import.meta.url), 'utf8');
  const updateSource = source.slice(source.indexOf('function updatePairPreviews()'), source.indexOf('async function savePair('));
  const frames = Object.fromEntries(['obverse', 'reverse'].map((side) => [side, { classList: { toggle() {} }, innerHTML: '' }]));
  const ctx = vm.createContext({ model: { task }, esc: (v) => String(v), api: { media: (key, source) => `${key}/${source}` }, document: { querySelector: (selector) => selector.startsWith('#') ? { value: selector.includes('obverse') ? 'source-2' : 'source-1' } : frames[selector.includes('obverse') ? 'obverse' : 'reverse'] } });
  vm.runInContext(updateSource, ctx);
  ctx.updatePairPreviews();
  assert.match(frames.obverse.innerHTML, /coin-one\/source-2/);
  assert.match(frames.reverse.innerHTML, /coin-one\/source-1/);
});

test('one intake handles any number of files without asking users to choose single or batch mode', async () => {
  const source = await readFile(new URL('../assets/workbench/app.js', import.meta.url), 'utf8');
  const index = await readFile(new URL('../assets/workbench/index.html', import.meta.url), 'utf8');
  assert.match(source, /page: titles\[page\] \? page : 'add'/);
  assert.match(source, /\['add', '＋', '添加钱币'\]/);
  const primary = source.slice(source.indexOf('const primaryNav'), source.indexOf('const advancedNav'));
  assert.doesNotMatch(primary, /import|批量上传/);
  assert.doesNotMatch(source.slice(source.indexOf("document.querySelector('#mobile-navigation')"), source.indexOf('function route()')), /href="#import"/);
  assert.match(source, /<summary>更多<\/summary>/);
  assert.match(index, /href="#add">＋ 添加钱币/);
  assert.doesNotMatch(index, /Agent 待接收|新建任务|id="host-status"/);
  const { controller } = fixture();
  const html = renderAdd(controller.state);
  assert.equal((html.match(/type="file"/g) || []).length, 1);
  assert.match(html, /id="add-files"[^>]*multiple/);
  assert.match(html, /自动匹配正反面/);
  assert.doesNotMatch(html, /单枚快捷|批量上传|选择正面照片|选择反面照片|href="#import"/);
  const routeSource = source.slice(source.indexOf('function route()'), source.indexOf('function toast('));
  const context = vm.createContext({ location: { hash: '#import?task=legacy-task' }, URLSearchParams, history: { replaceState: (_, __, hash) => { context.updated = hash; } }, href: (page, task) => `#${page}?task=${task}`, titles: { add: '添加钱币' } });
  vm.runInContext(routeSource, context);
  assert.equal(context.route().page, 'add');
  assert.equal(context.route().task, 'legacy-task');
  assert.equal(context.updated, '#add?task=legacy-task');
});


test('completed collection dispatch cannot be resent before its exact collection projection is readable', async () => {
  const { controller, service } = await prepared();
  await controller.identify();
  await controller.collect();
  delete service.task.items[0].collection_projection;
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.equal(hasPendingAdd(controller.state), true);
  assert.match(renderAdd(controller.state), /正在更新收藏结果/);
  const count = writes(service).length;
  await assert.rejects(controller.collect(), /不会重复发送/);
  assert.equal(writes(service).length, count);
});

test('a completed low-confidence recognition shows an explicit readable outcome rather than a silent empty result', async () => {
  const { controller, service } = await prepared();
  await controller.identify();
  delete service.task.items[0].recognitionResult;
  service.task.items[0].active_identification.status = 'failed';
  service.task.manifest.revision++;
  service.operations[0].revision++;
  service.operations[0].data.itemResults = [{ status: 'recognition_failed' }];
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  const html = renderAdd(controller.state);
  assert.match(html, /这次未识别出具体币种/);
  assert.doesNotMatch(html, /data-action="add-collect"/);
  assert.equal(writes(service).length, 1);
});


test('failed local pairing cannot trigger an automatic preparation loop', async () => {
  const { service, storage } = fixture();
  const controller = createAddController({ storage, request: (path, body, options) => {
    if (path === '/api/connector/prepare') throw Object.assign(new Error('正反面不能使用同一份照片'), { code: 'incomplete_pair' });
    return service.request(path, body, options);
  } });
  controller.sync(null, [], []);
  await controller.pick('obverse', photo('front.jpg'));
  await assert.rejects(controller.pick('reverse', photo('same.jpg')));
  assert.equal(controller.needsPlan, false);
  assert.equal(controller.state.slots.reverse.sourceId, 'source-2');
  assert.match(renderAdd(controller.state), /已保存 2 份资料/);
  assert.doesNotMatch(renderAdd(controller.state), /data-action="add-identify"/);
});

test('an explicit no-write collection rejection stays recoverable without being mislabeled unknown', async () => {
  const { controller, service, storage } = await prepared();
  await controller.identify();
  const next = createAddController({ storage, request: (path, body, options) => {
    if (path === '/api/connector/collect') throw Object.assign(new Error('insufficient capacity'), { code: 'collection_not_allowed' });
    return service.request(path, body, options);
  }, makeId: () => 'rejected-collect' });
  next.sync('coin-one', [copy(service.task)], copy(service.operations));
  await assert.rejects(next.collect());
  assert.equal(next.state.intents.collect.status, 'rejected');
  assert.equal(hasPendingAdd(next.state), false);
  assert.match(next.state.error, /容量或权限不足/);
  assert.equal(next.state.intents.collect.body.commandId, 'rejected-collect');
});

test('a confirmed pre-write query failure stays recoverable, while a lost response remains blocked', async () => {
  const { service, storage } = await prepared();
  const next = createAddController({ storage, request: (path, body, options) => {
    if (path === '/api/connector/identify') throw Object.assign(new Error('invalid JSON'), {
      code: 'cli_invalid_output', detail: { remoteWriteStarted: false },
    });
    return service.request(path, body, options);
  } });
  next.sync('coin-one', [copy(service.task)], []);
  await next.preview();
  await assert.rejects(next.identify());
  assert.equal(next.state.intents.identify.status, 'rejected');
  assert.equal(hasPendingAdd(next.state), false);
  assert.equal(writes(service).length, 0);
  next.newCoin();
  assert.equal(next.state.taskKey, null);
});

test('single-coin resume selects the sole active item without replacing an explicit historical selection', () => {
  const current = { local_id: 'current', status: 'active' };
  const old = { local_id: 'old', status: 'superseded' };
  const task = { items: [old, current] };
  assert.equal(addItem({ task }), current);
  assert.equal(addItem({ task, localId: 'old' }), null);
  assert.equal(addItem({ task: { items: [old] } }), null);
  assert.equal(addItem({ task: { items: [current, { local_id: 'other', status: 'active' }] } }), null);
});

test('unresolved source differences are visible and block the direct collect action until reviewed', async () => {
  const { service, controller } = await prepared();
  await controller.identify();
  const item = service.task.items[0];
  item.reviewIssues = [{ field: '年份', source: '来源年份', original: '1969 <original>', recognized: '1968' }];
  item.reviewIssuesResolved = false;
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  const html = renderAdd(controller.state);
  assert.match(html, /来源资料与识别结果有差异/);
  assert.match(html, /1969 &lt;original&gt;/);
  assert.match(html, /data-action="add-collect" disabled/);
  await assert.rejects(controller.collect(), /差异/);
  assert.equal(writes(service).length, 1);
  item.reviewIssuesResolved = true;
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.doesNotMatch(renderAdd(controller.state), /data-action="add-collect" disabled/);
});

async function batchPrepared(options) {
  const value = await prepared(options);
  const second = copy(value.service.task.items[0]);
  second.local_id = 'coin-one:second';
  second.organization.source_assignment = [{source_id:'source-3',role:'obverse'},{source_id:'source-4',role:'reverse'}];
  second.evidence = second.organization.source_assignment.map((entry) => ({...entry,is_primary:true}));
  value.service.task.items.push(second);
  value.service.task.manifest.revision++;
  value.controller.sync('coin-one',[copy(value.service.task)],[]);
  await value.controller.preview();
  return value;
}

test('batch identification and collection stay inline and bind every selected displayed snapshot', async () => {
  const {controller,service} = await batchPrepared();
  assert.equal(writes(service).length,0);
  assert.equal(controller.state.plan.items.length,2);
  await controller.identify();
  const html = renderAdd(controller.state);
  assert.equal((html.match(/data-add-select="collect"/g)||[]).length,2);
  assert.match(html,/One Franc &lt;test&gt;/);
  assert.match(html,/加入收藏（2）/);
  assert.doesNotMatch(html,/href="#identify|>核对识别结果</);
  await controller.collect();
  const body = writes(service).at(-1).body;
  assert.equal(writes(service).at(-1).path,'/api/connector/collect-batch');
  assert.deepEqual(body.items,[{localId:'coin-one:item',snapshotId:'recognition-exact-1'},{localId:'coin-one:second',snapshotId:'snapshot-coin-one:second'}]);
  assert.equal(service.task.items.every((item)=>item.collection_projection?.status==='succeeded'),true);
});

test('changing inline selection invalidates the plan and only sends the newly confirmed subset', async () => {
  const {controller,service} = await batchPrepared();
  controller.toggle('identify','coin-one:item',false);
  assert.equal(controller.state.plan,null);
  await assert.rejects(controller.identify(),/检查连接/);
  await controller.preview();
  assert.deepEqual(controller.state.plan.items.map((item)=>item.localId),['coin-one:second']);
  await controller.identify();
  assert.deepEqual(writes(service)[0].body.localIds,['coin-one:second']);
  // The first record remains available for identification even with another result present.
  controller.toggle('identify','coin-one:item',true);
  await controller.preview();
  assert.equal(controller.state.plan.items[0].localId,'coin-one:item');
});

test('a batch preflight failure shows an inline retry once, with no upload or recognition write', async () => {
  const {controller,service} = await batchPrepared();
  controller.state.plan=null; controller.state.planAttempt=null;
  service.planFailure=Object.assign(new Error('Agent API response is not valid JSON'),{code:'service_invalid_response'});
  await assert.rejects(controller.preview());
  assert.equal(controller.needsPlan,false);
  const html=renderAdd(controller.state);
  assert.match(html,/重新检查连接/);
  assert.match(html,/照片无需重传/);
  assert.doesNotMatch(html.split('<details class="add-advanced"')[0],/data-action="add-identify"|Agent API response/);
  assert.equal(writes(service).length,0);
  service.planFailure=null;
  await controller.preview();
  assert.equal(controller.state.plan.items.length,2);
});

test('an explicit eligibility refusal cannot be submitted from the inline button', async () => {
  const {controller,service}=await batchPrepared();
  controller.state.plan={...controller.state.plan,eligibility:{allowed:false}};
  assert.doesNotMatch(renderAdd(controller.state),/data-action="add-identify"/);
  await assert.rejects(controller.identify(),/资格不足/);
  assert.equal(writes(service).length,0);
});


test('after collecting complete pairs, missing photos can be added to the same task without changing recognized evidence', async () => {
  const {controller,service}=await batchPrepared();
  await controller.identify();
  service.task.items.push({local_id:'coin-one:missing',status:'active',organization:{pairing_state:'single_side'},attention_flags:['source_incomplete'],evidence:[]});
  service.task.manifest.revision++;
  controller.sync('coin-one',[copy(service.task)],service.operations);
  await controller.collect();
  assert.match(renderAdd(controller.state),/1 枚待补图/);
  assert.doesNotMatch(renderAdd(controller.state),/data-coin-id="coin-one:item"|data-coin-id="coin-one:second"/);
  const recognized=copy(service.task.items.slice(0,2));
  const before=service.calls.filter((call)=>call.path==='/api/tasks/create').length;
  await controller.upload([photo('missing-back.jpg')]);
  assert.equal(service.calls.filter((call)=>call.path==='/api/tasks/create').length,before);
  assert.equal(controller.state.taskKey,'coin-one');
  assert.deepEqual(service.task.items.slice(0,2),recognized);
});

test('confirmed collection releases the intake and does not restore completed cards on reload', async () => {
  const { controller, service, storage } = await batchPrepared();
  await controller.identify();
  await controller.collect();
  const completedTask = copy(service.task);
  assert.equal(controller.state.taskKey, null);
  assert.equal(controller.state.completion.count, 2);
  assert.doesNotMatch(renderAdd(controller.state), /已收藏 2 枚/);
  assert.match(renderAdd(controller.state), /上传钱币照片/);
  assert.doesNotMatch(renderAdd(controller.state), /data-coin-id|继续添加|补好/);
  const saved = JSON.parse(storage.getItem('heribase.connector.add.v1'));
  assert.equal(saved.lastTaskKey, null);
  assert.equal(saved.sessions['coin-one'].intents.collect.status, 'completed');
  const resumed = createAddController({ request: service.request, storage });
  resumed.sync(null, [copy(service.task)], copy(service.operations));
  assert.equal(resumed.state.taskKey, null);
  assert.match(renderAdd(resumed.state), /上传钱币照片/);
  const count = writes(service).length;
  await controller.collect();
  assert.equal(writes(service).length, count);
  assert.deepEqual(service.task, completedTask);
});

test('restoring an old completed batch releases the entry but keeps mixed and uncertain work', async () => {
  const { controller, service } = await batchPrepared();
  await controller.identify();
  await controller.collect();
  const support = { local_id: 'coin-one:support', status: 'active', organization: { input_kind: 'promotional_material' }, evidence: [] };
  service.task.items.push(support);
  const changes = [];
  const restored = createAddController({ request: service.request, storage: memory(), taskChanged: (key) => changes.push(key) });
  restored.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.equal(restored.state.taskKey, null);
  assert.deepEqual(changes, [null]);
  const base = { task: copy(service.task), taskKey: 'coin-one', intents: {}, operations: [], pendingSourceIds: [], uploadRemainder: [] };
  assert.equal(addBatchComplete(base), true);
  for (const patch of [
    { uploadRemainder: ['not-saved.jpg'] },
    { pendingSourceIds: ['new-source'] },
    { operations: [{ data: { status: 'reconcile_required' } }] },
    { task: { ...copy(service.task), health: { ok: false } } },
    { task: { ...copy(service.task), organization: { status: 'running' } } },
    { task: { ...copy(service.task), sources: [...service.task.sources, { source_id: 'unorganized' }] } },
    { task: { ...copy(service.task), items: [...service.task.items, { local_id: 'missing', status: 'source_incomplete' }] } },
    { task: { ...copy(service.task), items: service.task.items.map((item) => ({ ...item, status: 'identity_conflict' })) } },
    { task: { ...copy(service.task), items: service.task.items.map((item) => ({ ...item, attention_flags: ['source_incomplete'] })) } },
    { task: { ...copy(service.task), items: service.task.items.map((item) => ({ ...item, reviewIssues: [{ field: 'year' }], reviewIssuesResolved: false })) } },
  ]) assert.equal(addBatchComplete({ ...base, ...patch }), false);
});


test('an authentication refusal names the actual same-page reconnect button and preserves the photos', () => {
  for (const code of ['account_required','UNAUTHENTICATED']) {
    const message = friendlyAddError({code});
    assert.match(message,/重新登录 HeriBase/);
    assert.match(message,/重新检查连接/);
    assert.match(message,/无需重传/);
    assert.doesNotMatch(message,/重新检查识别范围/);
  }
});

test('upload status is visible before the first file is saved and advances only after receipts', async () => {
  const { service, storage } = fixture();
  const observations = [];
  const controller = createAddController({
    request: service.request, storage,
    changed: () => {
      if (controller.state.uploadProgress) observations.push({
        progress: copy(controller.state.uploadProgress), html: renderAdd(controller.state),
      });
    },
  });
  controller.sync(null, [], []);
  await controller.upload([photo('one.jpg'), photo('two.jpg')]);
  assert.deepEqual(observations.map((entry) => entry.progress.completed), [0, 0, 1, 1, 2]);
  assert.match(observations[0].html, /0 \/ 2 份已保存/);
  assert.match(observations[0].html, /aria-label="处理结果"/);
  assert.equal(controller.state.uploadProgress, null);
});

test('organization shows its actual stage without inventing a per-image percentage', () => {
  for (const [stage, message] of [['reading', '读取照片与资料'], ['analyzing', '匹配正反面'], ['saving', '保存整理结果']]) {
    const state = { task: { sources: [{ source_id: 's1' }], items: [], organization: { status: 'running', stage, sourceIds: ['s1'] } }, intents: {}, operations: [] };
    const activity = addActivity(state);
    assert.equal(activity.percent, null);
    assert.equal(activity.stage, 1);
    assert.match(activity.message, new RegExp(message));
    const html = renderAdd(state);
    assert.match(html, /add-meter indeterminate/);
    assert.doesNotMatch(html, /aria-valuenow/);
  }
});

test('operation progress counts unique scoped successes and does not call old retry failures completed', () => {
  for (const kind of ['identify', 'collect']) {
    const operation = { data: {
      kind, status: 'running', scope: ['a', 'b', 'c', 'a'].map((id) => kind === 'collect' ? { local_id: id } : { localId: id }),
      itemResults: [
        { localId: 'a', status: 'succeeded' }, { localId: 'a', status: 'succeeded' },
        { localId: 'b', status: 'failed' }, { localId: 'c', status: 'recognition_failed' },
        { localId: 'outside', status: 'succeeded' },
      ], calls: Array(12).fill({ status: 'completed' }),
    } };
    const state = { task: { items: [], sources: [] }, intents: { [kind]: { status: 'running', operation } } };
    assert.match(addActivity(state).count, /1 \/ 3/);
    assert.ok(Math.abs(addActivity(state).percent - 100 / 3) < 1e-9);
    assert.equal(addActivity(state).state, 'working');
    state.intents[kind].status = 'reconcile_required';
    assert.equal(addActivity(state).state, 'error');
    assert.equal(addActivity(state).percent, null);
    state.intents[kind].status = 'running';
    operation.data.itemResults = ['a', 'b', 'c'].map((localId) => ({ localId, status: 'succeeded' }));
    assert.equal(addActivity(state).percent, null);
    assert.equal(addActivity(state).state, 'working');
  }
});

test('preflight and waiting-for-user states are distinct from running identification', async () => {
  const { controller } = await prepared();
  assert.equal(addActivity(controller.state).state, 'waiting');
  assert.match(addActivity(controller.state).title, /等待识别/);
  controller.state.busy = true;
  controller.state.progress = '正在检查识别范围…';
  assert.equal(addActivity(controller.state).title, '正在检查识别条件');
});

test('successful collection notifies once, then restores a blank add entry without redirecting history', async () => {
  const notices = [];
  const { controller, service, storage } = await batchPrepared({ collectionFinished: (notice) => notices.push(notice) });
  await controller.identify();
  await controller.collect();
  assert.equal(notices.length, 1);
  assert.equal(notices[0].count, 2);
  assert.equal(notices[0].remaining, 0);
  assert.equal(controller.state.taskKey, null);
  const resumed = createAddController({ request: service.request, storage, collectionFinished: (notice) => notices.push(notice) });
  resumed.sync('coin-one', [copy(service.task)], copy(service.operations));
  resumed.sync(null, [copy(service.task)], copy(service.operations));
  assert.equal(notices.length, 1);
});

test('collecting a subset opens its success result while preserving unfinished coins', async () => {
  const notices = [];
  const { controller, service } = await batchPrepared({ collectionFinished: (notice) => notices.push(notice) });
  await controller.identify();
  controller.toggle('collect', 'coin-one:second', false);
  await controller.collect();
  assert.equal(notices.length, 1);
  assert.equal(notices[0].count, 1);
  assert.equal(notices[0].remaining, 1);
  assert.equal(controller.state.taskKey, 'coin-one');
  assert.match(renderAdd(controller.state), /data-coin-id="coin-one:second"/);
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.equal(notices.length, 1);
});

test('unknown collection does not navigate; a persisted exact success after reload does once', async () => {
  const notices = [];
  const { controller, service, storage } = await prepared({ collectionFinished: (notice) => notices.push(notice) });
  await controller.identify();
  service.loseCollect = true;
  service.keepUnknown = true;
  await assert.rejects(controller.collect());
  assert.equal(notices.length, 0);
  const resumed = createAddController({ request: service.request, storage, collectionFinished: (notice) => notices.push(notice) });
  const op = service.operations.find((op) => op.data.kind === 'collect');
  op.data.status = 'completed'; op.revision++;
  // The operation receipt alone is insufficient.
  resumed.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.equal(notices.length, 0);
  service.task.items[0].collection_projection = { status: 'cancelled' };
  service.task.manifest.revision++;
  resumed.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.equal(notices.length, 0);
  service.task.items[0].collection_projection = { status: 'succeeded', collection_uri: 'verified' };
  service.task.manifest.revision++;
  resumed.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.equal(notices.length, 1);
  assert.equal(writes(service).filter((call) => call.path === '/api/connector/collect').length, 1);
});

test('event progress remains visible during a slow dispatch and cannot regress to an older reply', async () => {
  const { service, storage } = await batchPrepared();
  let release, started;
  const ready = new Promise((resolve) => { started = resolve; });
  const controller = createAddController({
    storage, request: async (path, body, options) => {
      const reply = await service.request(path, body, options);
      if (path === '/api/connector/identify') {
        reply.data.status = 'running';
        reply.data.scope = body.localIds.map((localId) => ({ localId }));
        started(reply);
        await new Promise((resolve) => { release = resolve; });
      }
      return reply;
    },
  });
  controller.sync('coin-one', [copy(service.task)], []);
  await controller.preview();
  const pending = controller.identify();
  const reply = await ready;
  const newer = copy(reply);
  newer.revision++;
  newer.data.itemResults = [{ localId: 'coin-one:item', status: 'succeeded' }];
  controller.sync('coin-one', [copy(service.task)], [newer]);
  assert.equal(controller.state.busy, true);
  assert.match(addActivity(controller.state).count, /1 \/ 2/);
  release();
  await pending;
  assert.equal(controller.state.intents.identify.operation.revision, newer.revision);
  assert.match(addActivity(controller.state).count, /1 \/ 2/);
});


test('inline photo editing changes a draft only, then its single save continues a read-only preview', async () => {
  const { controller, service } = await prepared();
  const revision = service.task.manifest.revision;
  controller.openPhotos('coin-one:item');
  assert.equal(controller.hasPhotoDraft, true);
  assert.equal(controller.photosDirty, false);
  assert.equal(controller.needsPlan, false);
  controller.swapPhotos();
  assert.equal(controller.photosDirty, true);
  assert.equal(controller.state.photoEditor.slots.obverse, 'source-2');
  assert.equal(service.task.items[0].organization.source_assignment[0].source_id, 'source-1');
  const html = renderAdd(controller.state);
  assert.match(html, /class="add-photo-editor"/);
  assert.match(html, /source=source-2[^>]*alt="我的钱币 · 正面"/);
  assert.match(html, /data-action="add-photo-save"\s*>保存并继续/);
  assert.doesNotMatch(html, /data-action="add-identify"/);
  await assert.rejects(controller.identify(), /先保存/);
  await controller.savePhotos();
  const saves = service.calls.filter((call) => call.path === '/api/connector/photos');
  assert.equal(saves.length, 1);
  assert.deepEqual(saves[0].body, { taskKey: 'coin-one', expectedRevision: revision, localId: 'coin-one:item', obverseSourceId: 'source-2', reverseSourceId: 'source-1' });
  assert.equal(controller.hasPhotoDraft, false);
  assert.equal(controller.state.plan.revision, service.task.manifest.revision);
  assert.match(renderAdd(controller.state), /data-action="add-identify"/);
  assert.equal(writes(service).length, 0);
});

test('poll adoption preserves a changed draft and disables stale saves until explicit refresh', async () => {
  const { controller, service } = await prepared();
  controller.openPhotos('coin-one:item');
  controller.swapPhotos();
  const draft = copy(controller.state.photoEditor.slots);
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.deepEqual(controller.state.photoEditor.slots, draft);
  assert.equal(controller.state.photoEditor.stale, true);
  assert.equal(controller.photosDirty, true);
  const html = renderAdd(controller.state);
  assert.match(html, /刷新并重新选择/);
  assert.match(html, /data-action="add-photo-save" disabled/);
  await assert.rejects(controller.savePhotos(), /已更新/);
  assert.equal(service.calls.some((call) => call.path === '/api/connector/photos'), false);
  await controller.refreshPhotos();
  assert.equal(controller.state.photoEditor.stale, false);
  assert.equal(controller.state.photoEditor.baseRevision, service.task.manifest.revision);
  assert.equal(controller.state.photoEditor.slots.obverse, 'source-1');
  assert.equal(controller.photosDirty, false);
  controller.cancelPhotos();
  assert.equal(controller.hasPhotoDraft, false);
  assert.equal(controller.needsPlan, true);
});

for (const role of ['obverse', 'reverse']) {
  test(`inline ${role}-only coin stages its missing photo without pairing until Save`, async () => {
    const { controller, service } = await singleSide(role);
    const missing = role === 'obverse' ? 'reverse' : 'obverse';
    controller.openPhotos('coin-one:missing');
    assert.match(photoDraftProblem(controller.state), new RegExp(`还缺${missing === 'obverse' ? '正面' : '反面'}`));
    assert.match(renderAdd(controller.state), /data-action="add-photo-save" disabled/);
    await controller.supplement('coin-one:missing', missing, photo('new-side.jpg'));
    const staged = service.calls.find((call) => call.path.includes('mode=stage'));
    assert.ok(staged);
    assert.equal(new URLSearchParams(staged.path.split('?')[1]).has('side'), false);
    assert.equal(service.task.items[0].evidence.length, 1);
    assert.equal(controller.state.photoEditor.slots[missing], 'source-2');
    assert.equal(controller.state.photoEditor.stale, false);
    assert.equal(controller.state.photoEditor.baseRevision, service.task.manifest.revision);
    assert.equal(photoDraftProblem(controller.state), '');
    await controller.savePhotos();
    assert.equal(controller.state.task.items[0].organization.pairing_state, 'confirmed');
    assert.equal(controller.state.plan.items[0].localId, 'coin-one:missing');
    assert.equal(writes(service).length, 0);
  });
}

for (const role of ['obverse', 'reverse']) {
  test(`an unknown single image can be explicitly assigned as ${role} before staging the other side`, async () => {
    const { controller, service } = await singleSide();
    const item = service.task.items[0];
    item.organization.source_assignment[0].role = 'unknown';
    item.evidence[0].role = 'unknown';
    service.task.manifest.revision++;
    controller.sync('coin-one', [copy(service.task)], []);
    controller.openPhotos(item.local_id);
    controller.photoSide(role);
    controller.choosePhoto('source-1');
    const other = role === 'obverse' ? 'reverse' : 'obverse';
    await controller.supplement(item.local_id, other, photo('unknown-other.jpg'));
    assert.equal(item.evidence[0].role, 'unknown', 'stage never rewrites existing unknown evidence');
    await controller.savePhotos();
    const roles = Object.fromEntries(service.task.items[0].evidence.map((entry) => [entry.role, entry.source_id]));
    assert.equal(roles[role], 'source-1');
    assert.equal(roles[other], 'source-2');
    assert.equal(controller.state.plan.items[0].localId, item.local_id);
    assert.equal(writes(service).length, 0);
  });
}

test('the picker and save prohibit equal source IDs and equal image hashes for two sides', async () => {
  const { controller, service } = await prepared();
  service.task.sources[1].sha256 = service.task.sources[0].sha256;
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  controller.openPhotos('coin-one:item');
  assert.match(photoDraftProblem(controller.state), /同一张照片/);
  assert.match(renderAdd(controller.state), /data-action="add-photo-save" disabled/);
  controller.photoSide('reverse');
  await assert.rejects(async () => controller.choosePhoto('source-1'), /同一张照片/);
  await assert.rejects(controller.savePhotos(), /同一张照片/);
  assert.equal(service.calls.some((call) => call.path === '/api/connector/photos'), false);
});

test('available batch photos use evidence and hash locks while source_refs retain nonexclusive provenance', async () => {
  const { controller, service } = await prepared();
  const addSource = (id, hash = id) => service.task.sources.push({ source_id: id, sha256: hash, mime_type: 'image/jpeg', origin: { original_name: `${id}.jpg` } });
  for (const id of ['free', 'donor', 'confirmed', 'identified', 'collected', 'conflict', 'promo', 'document', 'support']) addSource(id);
  addSource('confirmed-copy', 'confirmed');
  const owner = (id, extra = {}) => ({ local_id: id, status: 'active', evidence: [{ source_id: id, role: 'unknown', is_primary: true }], organization: { pairing_state: 'needs_review' }, ...extra });
  service.task.items.push(owner('donor'), owner('confirmed', { organization: { pairing_state: 'confirmed' } }), owner('identified', { active_identification: { status: 'failed' } }), owner('collected', { collection_projection: { status: 'cancelled' } }), owner('conflict', { status: 'identity_conflict' }), owner('promo', { organization: { input_kind: 'promotional_material' } }), owner('document', { organization: { input_kind: 'document' } }), owner('support', { organization: { input_kind: 'support' } }));
  service.task.items[0].source_refs = ['free', 'confirmed'];
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  const ids = availablePhotoSources(controller.state, 'coin-one:item').map((source) => source.source_id);
  for (const id of ['source-1', 'source-2', 'free', 'donor', 'support']) assert.ok(ids.includes(id), id);
  for (const id of ['confirmed', 'confirmed-copy', 'identified', 'collected', 'conflict', 'promo', 'document']) assert.equal(ids.includes(id), false, id);
  controller.openPhotos('coin-one:item'); controller.photoSide('reverse');
  controller.choosePhoto('donor');
  await controller.savePhotos();
  assert.equal(service.task.items.find((item) => item.local_id === 'donor').evidence.length, 0);
  assert.ok(service.task.items[0].source_refs.includes('source-2'), 'replaced original remains a processed source reference');
  assert.equal(writes(service).length, 0);
});

test('cancel preserves newly staged photos as available batch originals instead of swallowing them', async () => {
  const { controller, service } = await singleSide();
  controller.openPhotos('coin-one:missing');
  await controller.supplement('coin-one:missing', 'reverse', photo('cancelled-new.jpg'));
  controller.cancelPhotos();
  assert.equal(service.task.items[0].evidence.length, 1);
  assert.equal(service.task.sources.length, 2);
  assert.equal(addWorkSummary(controller.state).unorganized, 1);
  controller.openPhotos('coin-one:missing');
  assert.ok(availablePhotoSources(controller.state, 'coin-one:missing').some((source) => source.source_id === 'source-2'));
  controller.photoSide('reverse'); controller.choosePhoto('source-2');
  assert.equal(photoDraftProblem(controller.state), '');
});

test('a lost photo-save reply is recovered once by exact current roles without recognition or a repeated save', async () => {
  const { service, storage } = await prepared();
  const controller = createAddController({ storage, request: async (path, body, options) => {
    const value = await service.request(path, body, options);
    if (path === '/api/connector/photos') throw Object.assign(new Error('reply lost'), { code: 'offline' });
    return value;
  } });
  controller.sync('coin-one', [copy(service.task)], []);
  controller.openPhotos('coin-one:item'); controller.swapPhotos();
  await controller.savePhotos();
  assert.equal(controller.hasPhotoDraft, false);
  assert.equal(service.calls.filter((call) => call.path === '/api/connector/photos').length, 1);
  assert.equal(controller.state.plan.revision, service.task.manifest.revision);
  assert.equal(writes(service).length, 0);
});

test('pending confirmation is conspicuous, support photos only zoom, and Add never links to the old pairing screen', async () => {
  const { controller, service } = await prepared();
  service.task.items[0].organization.pairing_state = 'needs_review';
  service.task.items[0].attention_flags = ['pairing_needs_confirmation'];
  service.task.items.push({ local_id: 'support', status: 'active', organization: { input_kind: 'promotional_material' }, evidence: [{ source_id: 'source-1', role: 'unknown', is_primary: true }] });
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  const html = renderAdd(controller.state);
  assert.match(html, /<section class="add-result-group"><h3>待确认/);
  assert.match(html, /data-action="add-photos" data-id="coin-one:item"/);
  assert.doesNotMatch(html, /href="#pairing/);
  assert.doesNotMatch(html, /data-action="add-photos" data-id="support"/);
  assert.match(html, /data-action="zoom"/);
});

test('identified and collected coins cannot open the photo editor, including old failure projections', async () => {
  const { controller, service } = await prepared();
  for (const projection of [{ active_identification: { status: 'failed' } }, { collection_projection: { status: 'cancelled' } }]) {
    Object.assign(service.task.items[0], projection);
    service.task.manifest.revision++;
    controller.sync('coin-one', [copy(service.task)], []);
    assert.equal(editablePhotos(controller.state.task.items[0]), false);
    assert.throws(() => controller.openPhotos('coin-one:item'), /不能更改照片/);
  }
});


test('photo protection includes identity conflict flags and historical business evidence on inactive owners', async () => {
  const { controller, service } = await prepared();
  const target = service.task.items[0];
  target.attention_flags = ['identity_conflict'];
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  assert.equal(editablePhotos(controller.state.task.items[0]), false);
  assert.throws(() => controller.openPhotos(target.local_id), /不能更改照片/);
  target.attention_flags = [];
  for (const [id, status, projection] of [
    ['old-identification', 'superseded', { active_identification: { status: 'failed' } }],
    ['old-collection', 'archived', { collection_projection: { status: 'cancelled' } }],
    ['conflict-flag', 'active', { attention_flags: ['identity_conflict'] }],
    ['unused-old', 'archived', {}],
  ]) {
    service.task.sources.push({ source_id: id, sha256: id, mime_type: 'image/jpeg', origin: { original_name: `${id}.jpg` } });
    service.task.items.push({ local_id: id, status, organization: {}, evidence: [{ source_id: id, role: 'unknown', is_primary: true }], ...projection });
  }
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  const ids = availablePhotoSources(controller.state, target.local_id).map((source) => source.source_id);
  assert.equal(ids.includes('old-identification'), false);
  assert.equal(ids.includes('old-collection'), false);
  assert.equal(ids.includes('conflict-flag'), false);
  assert.equal(ids.includes('unused-old'), true);
});


test('editor reports early supplement validation failures beside the draft without making any request', async () => {
  const { controller, service } = await singleSide();
  controller.openPhotos('coin-one:missing');
  for (const file of [{ name: 'oversized.jpg', size: 21 * 1024 * 1024, type: 'image/jpeg' }, { name: 'wrong.txt', size: 42, type: 'text/plain' }]) {
    const count = service.calls.length;
    await assert.rejects(controller.supplement('coin-one:missing', 'reverse', file), /不超过 20 MiB/);
    assert.equal(service.calls.length, count);
    assert.match(controller.state.photoEditor.error, /不超过 20 MiB/);
    assert.equal(controller.state.photoFeedback['coin-one:missing'].status, 'error');
    assert.match(renderAdd(controller.state), /class="add-editor-error" role="alert">请选择一张不超过 20 MiB 的照片/);
  }
  await controller.supplement('coin-one:missing', 'reverse', photo('valid-retry.jpg'));
  assert.equal(controller.state.photoEditor.error, '');
  assert.equal(controller.state.photoFeedback['coin-one:missing'].status, 'success');
  assert.equal(writes(service).length, 0);
});

test('stale editor supplement failures are visible even when they happen before its run starts', async () => {
  const { controller, service } = await singleSide();
  controller.openPhotos('coin-one:missing');
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  const count = service.calls.length;
  await assert.rejects(controller.supplement('coin-one:missing', 'reverse', photo('valid.jpg')), /已更新/);
  assert.equal(service.calls.length, count);
  assert.match(controller.state.photoEditor.error, /当前草稿仍保留/);
  assert.match(renderAdd(controller.state), /class="add-editor-error" role="alert"/);
});

test('unconfirmed cards show both uploaded unknown images instead of claiming that both photos are missing', async () => {
  const { controller, service } = await prepared();
  service.task.items[0].organization.pairing_state = 'needs_review';
  service.task.items[0].organization.source_assignment.forEach((entry) => { entry.role = 'unknown'; });
  service.task.items[0].evidence.forEach((entry) => { entry.role = 'unknown'; });
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  const card = renderAdd(controller.state).match(/<article class="add-coin-card"[^]*?<\/article>/)[0];
  assert.match(card, /source=source-1/);
  assert.match(card, /source=source-2/);
  assert.equal((card.match(/<span>待确认方向<\/span>/g) || []).length, 2);
  assert.doesNotMatch(card, /缺少正面|缺少反面|补正面|补反面/);
  assert.match(card, /data-action="add-photos"/);
});

test('unconfirmed thumbnails retain an explicitly assigned side while showing the other existing unknown image', async () => {
  const { controller, service } = await prepared();
  service.task.items[0].organization.pairing_state = 'needs_review';
  service.task.items[0].organization.source_assignment[1].role = 'unknown';
  service.task.items[0].evidence[1].role = 'unknown';
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  const card = renderAdd(controller.state).match(/<article class="add-coin-card"[^]*?<\/article>/)[0];
  assert.match(card, /source=source-1[^]*?<span>正面<\/span>/);
  assert.match(card, /source=source-2[^]*?<span>待确认方向<\/span>/);
  assert.doesNotMatch(card, /缺少反面/);
});


test('editor slot and picker shorten generated hash names while keeping ordinary filenames and original tooltips', async () => {
  const { controller, service } = await prepared();
  const original = `${'a'.repeat(64)}.png`;
  service.task.sources[0].origin.original_name = original;
  service.task.sources[1].origin.original_name = 'front.jpg';
  service.task.sources.push({ source_id: 'plain-number', mime_type: 'image/jpeg', origin: { original_name: '1.png' } });
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  controller.openPhotos('coin-one:item'); controller.photoSide('obverse');
  const html = renderAdd(controller.state);
  assert.match(html, new RegExp(`class="add-editor-filename" title="${original}">照片 1<`));
  assert.match(html, /<span>照片 1<\/span>/);
  assert.match(html, /alt="照片 1"/);
  assert.match(html, /<span>front.jpg<\/span>/);
  assert.match(html, /<span>1.png<\/span>/);
  const editor = html.slice(html.indexOf('<section class="add-photo-editor"'), html.indexOf('</article>'));
  assert.doesNotMatch(editor, new RegExp(`>(?:${original})<`));
});


async function mixedWork() {
  const value = await prepared();
  const { controller, service } = value;
  await controller.identify();
  const source = (n) => ({ source_id: `mixed-${n}`, sha256: `mixed-hash-${n}`, mime_type: 'image/jpeg', origin: { original_name: `${n}.jpg` } });
  for (let n = 1; n <= 5; n++) service.task.sources.push(source(n));
  const coin = (id, front, back, pairing_state) => ({ local_id: id, status: back ? 'active' : 'source_incomplete', organization: { pairing_state, source_assignment: [{ source_id: front, role: 'obverse' }, ...(back ? [{ source_id: back, role: 'reverse' }] : [])] }, evidence: [{ source_id: front, role: 'obverse', is_primary: true }, ...(back ? [{ source_id: back, role: 'reverse', is_primary: true }] : [])] });
  service.task.items.push(coin('mixed-ready', 'mixed-1', 'mixed-2', 'auto_ready'), coin('mixed-pending', 'mixed-3', 'mixed-4', 'needs_review'), coin('mixed-missing', 'mixed-5', null, 'single_side'));
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  await controller.preview();
  return value;
}

test('mixed work leads with recognized coins and exposes collection and identification as independent group actions', async () => {
  const { controller, service, storage } = await mixedWork();
  const html = renderAdd(controller.state);
  const results = html.indexOf('add-review-group'), identify = html.indexOf('add-identify-group');
  assert.ok(results < identify);
  assert.ok(html.indexOf('data-action="add-collect"') < html.indexOf('data-action="add-identify"'));
  assert.match(html, /add-review-group[^]*?data-action="add-collect" >加入收藏（1）/);
  assert.match(html, /add-identify-group[^]*?data-action="add-identify" >识别这 1 枚/);
  assert.match(html, /class="add-activity-summary"/);
  assert.doesNotMatch(html, /class="add-stage-list"/);
  assert.match(html, /data-add-group="pending" ><summary>待确认 <span>1/);
  assert.match(html, /data-add-group="missing" ><summary>待补图 <span>1/);
  assert.ok(html.indexOf('data-add-group="missing"') > results);
  controller.setGroupOpen('missing', true);
  assert.match(renderAdd(controller.state), /data-add-group="missing" open/);
  const resumed = createAddController({ request: service.request, storage });
  resumed.sync('coin-one', [copy(service.task)], copy(service.operations));
  assert.match(renderAdd(resumed.state), /data-add-group="missing" open/);
  assert.equal(writes(service).length, 1);
});

test('working progress remains visible while a pending online operation keeps actions and local intake locked', async () => {
  const { controller, service } = await mixedWork();
  service.operations.unshift({ id: 'running-identification', revision: 1, data: { taskKey: 'coin-one', kind: 'identify', status: 'running', request: { localIds: ['mixed-ready'] }, scope: [{ localId: 'mixed-ready' }], itemResults: [] } });
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  const html = renderAdd(controller.state);
  assert.match(html, /class="add-stage-list"/);
  assert.match(html, /role="progressbar"/);
  assert.match(html, /data-action="add-collect" disabled/);
  assert.match(html, /data-action="add-choose" disabled/);
  const count = service.calls.length;
  await assert.rejects(controller.upload([photo('later.jpg')]), /先核验/);
  assert.equal(service.calls.length, count);
});

test('a directional two-photo suggestion confirms its exact displayed pair in one local action without opening an editor', async () => {
  const { controller, service } = await prepared();
  service.task.items[0].organization.pairing_state = 'needs_review';
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], []);
  const revision = service.task.manifest.revision;
  assert.equal(canConfirmPhotoPair(controller.state, controller.state.task.items[0]), true);
  assert.match(renderAdd(controller.state), /data-action="add-photo-confirm" data-id="coin-one:item" >确认这组照片/);
  await controller.confirmPhotos('coin-one:item');
  assert.equal(controller.hasPhotoDraft, false);
  assert.deepEqual(service.calls.find((call) => call.path === '/api/connector/photos').body, { taskKey: 'coin-one', expectedRevision: revision, localId: 'coin-one:item', obverseSourceId: 'source-1', reverseSourceId: 'source-2' });
  assert.equal(controller.state.task.items[0].organization.pairing_state, 'confirmed');
  assert.equal(writes(service).length, 0);
});

test('unknown directions, extra evidence and duplicate roles require explicit selection instead of one-click confirmation', async () => {
  for (const variant of ['unknown', 'extra', 'duplicate-role', 'duplicate-assignment']) {
    const { controller, service } = await prepared();
    const item = service.task.items[0];
    item.organization.pairing_state = 'needs_review';
    if (variant === 'unknown') {
      item.organization.source_assignment.forEach((entry) => { entry.role = 'unknown'; });
      item.evidence.forEach((entry) => { entry.role = 'unknown'; });
    } else if (variant === 'extra') {
      service.task.sources.push({ source_id: 'detail', sha256: 'detail', mime_type: 'image/jpeg' });
      item.evidence.push({ source_id: 'detail', role: 'detail', is_primary: false });
    } else if (variant === 'duplicate-role') item.evidence[1].role = 'obverse';
    else item.organization.source_assignment[1].role = 'obverse';
    service.task.manifest.revision++;
    controller.sync('coin-one', [copy(service.task)], []);
    assert.equal(canConfirmPhotoPair(controller.state, controller.state.task.items[0]), false, variant);
    const html = renderAdd(controller.state);
    assert.doesNotMatch(html, /data-action="add-photo-confirm"/);
    assert.match(html, /data-action="add-photos"[^>]*>选择正反面/);
    await assert.rejects(controller.confirmPhotos('coin-one:item'), /先选择/);
    assert.equal(service.calls.some((call) => call.path === '/api/connector/photos'), false);
  }
});

test('direct photo confirmation never announces success before a receipt or after a rejected write', async () => {
  const { service, storage } = await prepared();
  service.task.items[0].organization.pairing_state = 'needs_review'; service.task.manifest.revision++;
  let release, began;
  const gate = new Promise((resolve) => { release = resolve; });
  const started = new Promise((resolve) => { began = resolve; });
  const controller = createAddController({ storage, request: async (path, body, options) => {
    if (path === '/api/connector/photos') { began(); await gate; throw Object.assign(new Error('source locked'), { code: 'photo_source_locked', status: 409 }); }
    return service.request(path, body, options);
  } });
  controller.sync('coin-one', [copy(service.task)], []);
  const work = controller.confirmPhotos('coin-one:item');
  await started;
  assert.equal(controller.state.busy, true);
  assert.equal(controller.state.photoFeedback['coin-one:item'], undefined);
  assert.match(renderAdd(controller.state), /data-action="add-photo-confirm"[^>]+disabled/);
  release(); await assert.rejects(work, /source locked/);
  assert.equal(controller.state.photoFeedback['coin-one:item'], undefined);
  assert.equal(controller.state.task.items[0].organization.pairing_state, 'needs_review');
  assert.equal(writes(service).length, 0);
});

test('ongoing organization leaves upload enabled and one explicit revision conflict retries only the unaccepted file', async () => {
  const { service, storage } = await prepared();
  service.task.organization = { status: 'running', stage: 'analyzing' };
  const attempts = [];
  const controller = createAddController({ storage, request: async (path, body, options) => {
    if (path.startsWith('/api/upload?')) {
      attempts.push({ name: body.name, revision: Number(new URLSearchParams(path.split('?')[1]).get('revision')) });
      if (attempts.length === 1) { service.task.manifest.revision++; throw Object.assign(new Error('revision changed'), { code: 'revision_conflict', status: 409 }); }
    }
    const value = await service.request(path, body, options);
    if (path.startsWith('/api/upload?')) value.organizationWarning = { code: 'queue_updated' };
    return value;
  } });
  controller.sync('coin-one', [copy(service.task)], []);
  const html = renderAdd(controller.state);
  assert.match(html, /data-action="add-choose" >选择照片或表格/);
  await controller.upload([photo('during-work.jpg')]);
  assert.equal(attempts.length, 2);
  assert.equal(attempts[1].revision, attempts[0].revision + 1);
  assert.equal(service.task.sources.filter((source) => source.origin?.original_name === 'during-work.jpg').length, 1);
  assert.deepEqual(controller.state.uploadRemainder, []);
  assert.equal(writes(service).length, 0);
});

test('bounded revision retry preserves accepted files, remaining names and the saved count on failure', async () => {
  const { service, storage } = fixture();
  const attempts = [];
  const controller = createAddController({ storage, request: (path, body, options) => {
    if (path.startsWith('/api/upload?')) {
      attempts.push(body.name);
      if (body.name === 'second.jpg') throw Object.assign(new Error('revision changed twice'), { code: 'revision_conflict', status: 409 });
    }
    return service.request(path, body, options);
  } });
  controller.sync(null, [], []);
  await assert.rejects(controller.upload([photo('first.jpg'), photo('second.jpg'), photo('third.jpg')]));
  assert.deepEqual(attempts, ['first.jpg', 'second.jpg', 'second.jpg']);
  assert.equal(service.task.sources.length, 1);
  assert.deepEqual(controller.state.uploadRemainder, ['second.jpg', 'third.jpg']);
  assert.match(controller.state.error, /已保存 1\/3 份/);
  assert.match(renderAdd(controller.state), /还有 2 份资料尚未确认保存/);
});

test('unknown upload outcomes never retry, even during organization', async () => {
  const { service, storage } = await prepared();
  service.task.organization = { status: 'running' };
  let attempts = 0;
  const controller = createAddController({ storage, request: (path, body, options) => {
    if (path.startsWith('/api/upload?')) { attempts++; throw Object.assign(new Error('connection lost'), { code: 'offline', status: 0 }); }
    return service.request(path, body, options);
  } });
  controller.sync('coin-one', [copy(service.task)], []);
  await assert.rejects(controller.upload([photo('unknown.jpg')]));
  assert.equal(attempts, 1);
  assert.deepEqual(controller.state.uploadRemainder, ['unknown.jpg']);
  assert.match(controller.state.error, /已保存 0\/1 份/);
});

test('None mint markers render as an empty value and recognized badges distinguish collection from unresolved differences', async () => {
  const { controller, service } = await prepared();
  await controller.identify();
  service.task.items[0].recognitionResult.mintMark = 'None'; service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  let html = renderAdd(controller.state);
  assert.match(html, /<dt>造币标记<\/dt><dd>—<\/dd>/);
  assert.doesNotMatch(html, />None</);
  assert.match(html, />待收藏<\/span>/);
  service.task.items[0].reviewIssues = [{ field: 'year', original: '1967', recognized: '1968' }]; service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  html = renderAdd(controller.state);
  assert.match(html, />需核对差异<\/span>/);
  assert.match(html, /data-action="add-collect" disabled/);
});


test('continued upload stays in the current queued or running task even with recognized coins and no missing sides', async () => {
  for (const status of ['queued', 'running']) {
    const { controller, service } = await prepared();
    await controller.identify();
    const recognized = copy(service.task.items[0]);
    service.task.sources.push({ source_id: 'already-pending', sha256: 'pending-hash', mime_type: 'image/jpeg', origin: { original_name: 'pending.jpg' } });
    service.task.organization = { status, sourceIds: ['already-pending'], stage: 'analyzing' };
    service.task.manifest.revision++;
    controller.sync('coin-one', [copy(service.task)], copy(service.operations));
    const start = service.calls.length;
    await controller.upload([photo('continue-same-task.jpg')]);
    const calls = service.calls.slice(start);
    assert.equal(calls.some((call) => call.path === '/api/tasks/create'), false, status);
    const upload = calls.find((call) => call.path.startsWith('/api/upload?'));
    assert.equal(new URLSearchParams(upload.path.split('?')[1]).get('task'), 'coin-one');
    assert.equal(controller.state.taskKey, 'coin-one');
    assert.ok(controller.state.task.sources.some((source) => source.source_id === 'already-pending'));
    assert.deepEqual(controller.state.task.items[0], recognized);
    assert.equal(writes(service).length, 1, 'continued upload never re-identifies or collects the existing coin');
  }
});

const completeRecognitionResult = () => ({
  title: 'France 5 francs 1963', year: '1963', mintMark: 'None',
  price: { value: '$22.17', currency: 'USD' },
  attributes: [
    { name: 'Country', value: 'FRA' }, { name: 'Denomination', value: '5 francs' },
    { name: 'Krause number', value: 'KM# 926' }, { name: 'Metal', value: 'Silver 0.835' },
    { name: 'Mintage', value: '37,936,000' }, { name: 'weight', value: '12 g' },
    { name: 'diameter', value: '29 mm' }, { name: 'thickness', value: '2 mm' },
  ],
  obverseReverseInfo: {
    frontInfo: { img: 'https://cdn.heritcoin.com/qa/front.png' },
    backInfo: { img: 'https://cdn.heribase.com/qa/back.png' },
  },
  referenceImages: ['https://cdn.heritcoin.com/qa/front.png', 'https://cdn.heribase.com/qa/back.png'],
});
const recognizedCards = (html) => html.match(/<article\b(?=[^>]*\bclass="[^"]*\bis-recognized\b)[^>]*>[\s\S]*?<\/article>/g) || [];
const resultFacts = (card) => new Map([...card.matchAll(/<dt\b[^>]*>([\s\S]*?)<\/dt>\s*<dd\b[^>]*>([\s\S]*?)<\/dd>/g)].map(([, label, value]) => [label.replace(/<[^>]*>/g, '').trim(), value.replace(/<[^>]*>/g, '').trim()]));
async function recognizedResult(result) {
  const value = await prepared();
  await value.controller.identify();
  value.service.task.items[0].recognitionResult = copy(result);
  value.service.task.manifest.revision++;
  value.controller.sync('coin-one', [copy(value.service.task)], copy(value.service.operations));
  return value;
}

test('recognized cards directly show every returned core field, the reference price and two zoomable service images', async () => {
  const { controller, service } = await recognizedResult(completeRecognitionResult());
  const cards = recognizedCards(renderAdd(controller.state));
  assert.equal(cards.length, 1);
  const [card] = cards;
  assert.deepEqual(Object.fromEntries(resultFacts(card)), {
    '国家 / 地区': 'FRA', '面额': '5 francs', '年份': '1963', '造币标记': '—',
    '目录编号': 'KM# 926', '材质': 'Silver 0.835', '发行量': '37,936,000',
    '重量': '12 g', '直径': '29 mm', '厚度': '2 mm',
  });
  assert.match(card, /\$22\.17/);
  assert.match(card, /USD/);
  assert.match(card, /服务参考/);
  assert.match(card, /非本枚实物/);
  for (const url of ['https://cdn.heritcoin.com/qa/front.png', 'https://cdn.heribase.com/qa/back.png']) {
    assert.ok(card.includes(`src="${url}"`), 'the service image is visible without opening a disclosure');
    assert.ok(card.includes(`data-url="${url}"`), 'each service image opens the existing zoom action');
  }
  assert.equal((card.match(/data-action="zoom"/g) || []).length, 4, 'two originals and two service references remain independently zoomable');
  assert.equal((card.match(/data-image-kind="reference"/g) || []).length, 2, 'reference zooms keep their source category');
  assert.match(card, /<figcaption>参考正面<\/figcaption>/);
  assert.match(card, /<figcaption>参考反面<\/figcaption>/);
  assert.doesNotMatch(card, /<details\b|识别详情|查看服务参考图片/);
  assert.equal((card.match(/<h[1-6]\b[^>]*>France 5 francs 1963<\/h[1-6]>/g) || []).length, 1, 'the coin title has one visible heading');
  assert.equal(writes(service).length, 1, 'rendering a complete result never submits another operation');
});

test('missing recognition facts use explicit dashes and zero values are preserved without inventing coin details', async () => {
  for (const result of [
    { title: 'Unknown coin', attributes: [] },
    { title: 'Unknown coin', year: null, mintMark: 'None', attributes: null, price: null, obverseReverseInfo: null },
  ]) {
    const { controller } = await recognizedResult(result);
    const [card] = recognizedCards(renderAdd(controller.state));
    assert.ok(card);
    const facts = resultFacts(card);
    assert.equal(facts.size, 10);
    assert.ok([...facts.values()].every((value) => value === '—'));
    assert.doesNotMatch(card, /undefined|\bnull\b|>None</);
    assert.doesNotMatch(card, /<details\b|https:\/\/cdn\./);
  }
  const result = completeRecognitionResult();
  result.price = { value: 0, currency: 'USD' };
  result.attributes.find((attribute) => attribute.name === 'Mintage').value = 0;
  const { controller } = await recognizedResult(result);
  const [card] = recognizedCards(renderAdd(controller.state));
  assert.equal(resultFacts(card).get('发行量'), '0');
  assert.match(card, /参考价[\s\S]*?0[\s\S]*?USD/);
});

test('recognition text is escaped and only approved HTTPS reference images appear in zoomable previews', async () => {
  const result = completeRecognitionResult();
  result.title = 'Coin <img src=x onerror="alert(1)"> & reserve';
  result.attributes.find((attribute) => attribute.name === 'Metal').value = '<script>alert("metal")</script> & alloy';
  result.price = { value: '<svg onload="price()">', currency: 'USD & <x>' };
  result.obverseReverseInfo = { frontInfo: { img: 'https://user:password@cdn.heritcoin.com/front.png' }, backInfo: {} };
  const { controller, service } = await recognizedResult(result);
  let [card] = recognizedCards(renderAdd(controller.state));
  assert.match(card, /Coin &lt;img src=x onerror=&quot;alert\(1\)&quot;&gt; &amp; reserve/);
  assert.equal(resultFacts(card).get('材质'), '&lt;script&gt;alert(&quot;metal&quot;)&lt;/script&gt; &amp; alloy');
  assert.match(card, /&lt;svg onload=&quot;price\(\)&quot;&gt;/);
  assert.match(card, /USD &amp; &lt;x&gt;/);
  assert.doesNotMatch(card, /<script\b|<svg\b|<img src=x|src="https:\/\/user:/);
  for (const url of result.referenceImages) {
    assert.ok(card.includes(`src="${url}"`));
    assert.ok(card.includes(`data-url="${url}"`));
  }
  const rejected = [
    'http://cdn.heritcoin.com/front.png', 'javascript:alert(1)', 'data:image/png;base64,AA',
    'https://cdn.heritcoin.com.evil.example/front.png', 'https://cdn.heritcoin.com:8443/front.png',
    'https://user:password@cdn.heribase.com/front.png', '//cdn.heritcoin.com/front.png',
  ];
  for (const url of rejected) {
    service.task.items[0].recognitionResult = { ...completeRecognitionResult(),
      obverseReverseInfo: { frontInfo: { img: url }, backInfo: { img: url } }, referenceImages: [url, url] };
    service.task.manifest.revision++;
    controller.sync('coin-one', [copy(service.task)], copy(service.operations));
    [card] = recognizedCards(renderAdd(controller.state));
    const remoteImages = [...card.matchAll(/<img\b[^>]*\bsrc="([^"]+)"/g)].map(([, src]) => src).filter((src) => !src.startsWith('/api/media?'));
    assert.deepEqual(remoteImages, [], `unapproved image URL must never be fetched: ${url}`);
    assert.equal((card.match(/data-action="zoom"/g) || []).length, 2, 'unapproved references cannot expose a zoom URL');
  }
});

test('an unlabelled reference array preserves every safe unique image without guessing obverse or reverse', async () => {
  const result = completeRecognitionResult();
  delete result.obverseReverseInfo;
  const urls = [...result.referenceImages, 'https://cdn.heritcoin.com/qa/additional-detail.png'];
  result.referenceImages = [urls[0], urls[0], urls[1], urls[2], 'https://unapproved.example/coin.png'];
  const { controller, service } = await recognizedResult(result);
  const [card] = recognizedCards(renderAdd(controller.state));
  const captions = [...card.matchAll(/<figcaption>([^<]*)<\/figcaption>/g)].map(([, text]) => text);
  assert.equal(captions.length, 3);
  assert.ok(captions.every((caption) => caption.includes('面别未标明')));
  assert.doesNotMatch(card, /参考正面|参考反面|服务参考 · 正面|服务参考 · 反面/);
  for (const url of urls) {
    assert.equal(card.split(`src="${url}"`).length - 1, 1, 'a safe array image is kept exactly once');
    const zoom = (card.match(/<button\b[^>]*>/g) || []).find((tag) => tag.includes(`data-url="${url}"`));
    assert.ok(zoom?.includes('data-action="zoom"'));
    assert.ok(zoom?.includes('data-image-kind="reference"'), 'zoom must not relabel a service reference as an uploaded original');
  }
  assert.doesNotMatch(card, /unapproved\.example/);
  assert.equal(writes(service).length, 1);
});

test('explicit reference faces retain their labels while additional unlabelled array images are deduplicated and kept', async () => {
  const result = completeRecognitionResult();
  const extra = 'https://cdn.heribase.com/qa/edge-reference.png';
  result.referenceImages.push(extra, result.referenceImages[0], extra);
  const { controller } = await recognizedResult(result);
  const [card] = recognizedCards(renderAdd(controller.state));
  const captions = [...card.matchAll(/<figcaption>([^<]*)<\/figcaption>/g)].map(([, text]) => text);
  assert.equal(captions.length, 3);
  assert.equal(captions.filter((caption) => caption === '参考正面').length, 1);
  assert.equal(captions.filter((caption) => caption === '参考反面').length, 1);
  assert.equal(captions.filter((caption) => caption.includes('面别未标明')).length, 1);
  assert.equal(card.split(`src="${extra}"`).length - 1, 1);
  assert.equal((card.match(/data-image-kind="reference"/g) || []).length, 3);
});

test('long recognition values remain complete in each visible card while mixed identification and missing-photo work stays reachable', async () => {
  const { controller, service } = await mixedWork();
  const first = service.task.items[0];
  const longTitle = 'A very long coin title & provenance '.repeat(12);
  const longMetal = 'Silver with an unusually detailed service description '.repeat(14);
  first.recognitionResult = { ...completeRecognitionResult(), title: longTitle };
  first.recognitionResult.attributes.find((attribute) => attribute.name === 'Metal').value = longMetal;
  service.task.sources.push({ source_id: 'long-front', sha256: 'long-front', mime_type: 'image/jpeg' }, { source_id: 'long-back', sha256: 'long-back', mime_type: 'image/jpeg' });
  const second = copy(first);
  second.local_id = 'coin-one:second-recognized';
  second.active_identification.snapshot_id = 'second-snapshot';
  second.organization.source_assignment = [{ source_id: 'long-front', role: 'obverse' }, { source_id: 'long-back', role: 'reverse' }];
  second.evidence = second.organization.source_assignment.map((entry) => ({ ...entry, is_primary: true }));
  second.recognitionResult = { ...completeRecognitionResult(), title: 'Second returned coin' };
  service.task.items.push(second);
  service.task.manifest.revision++;
  controller.sync('coin-one', [copy(service.task)], copy(service.operations));
  await controller.preview();
  const html = renderAdd(controller.state), cards = recognizedCards(html);
  assert.equal(cards.length, 2);
  assert.ok(cards[0].includes(longTitle.replaceAll('&', '&amp;')));
  assert.equal(resultFacts(cards[0]).get('材质'), longMetal.trim());
  assert.equal((cards[1].match(/<h[1-6]\b[^>]*>Second returned coin<\/h[1-6]>/g) || []).length, 1);
  for (const card of cards) {
    assert.equal(resultFacts(card).size, 10);
    assert.doesNotMatch(card, /<details\b|识别详情|查看服务参考图片/);
  }
  assert.match(html, /data-action="add-collect"[^>]*>加入收藏（2）/);
  assert.match(html, /data-action="add-identify"[^>]*>识别这 1 枚/);
  assert.match(html, /data-add-group="missing"[^>]*><summary>待补图/);
  assert.match(html, /data-add-supplement="reverse" data-id="mixed-missing"/);
  assert.equal(writes(service).length, 1);
});
