/* One intake for photos and documents. Remote writes require a frozen confirmation and a persisted intent.
 * A lost response is reconciled by reading state; it is never automatically resent. */
import { eligibleForIdentification } from './bulk.js';

const STORAGE_KEY = 'heribase.connector.add.v1';
const SIDES = ['obverse', 'reverse'];
const pendingStatuses = new Set(['sending', 'unknown', 'preparing', 'queued', 'running', 'reconcile_required', 'partial_failed']);
const rejectedCodes = new Set(['stale_revision', 'revision_conflict', 'stale_plan', 'stale_snapshot', 'invalid_scope', 'invalid_selection', 'account_changed', 'account_required', 'not_eligible', 'identify_quota_insufficient', 'review_conflict', 'operation_pending', 'connection_required', 'revision_mismatch', 'unauthenticated', 'collection_not_allowed', 'already_collected', 'confirmation_interrupted']);
const e = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const clone = (value) => JSON.parse(JSON.stringify(value));
const freeze = (value) => {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
};
const media = (key, source) => `/api/media?${new URLSearchParams({ task: key, source })}`;
const route = (page, key, id) => `#${page}${key ? `?${new URLSearchParams({ task: key, ...(id ? { item: id } : {}) })}` : ''}`;
const control = (label, action, disabled = false, style = 'primary') => `<button class="button ${style}" data-action="add-${action}" ${disabled ? 'disabled' : ''}>${e(label)}</button>`;
const scalar = (value) => ['string', 'number'].includes(typeof value) ? String(value) : '';
const readyForIdentification = (item) => Boolean(item && eligibleForIdentification(item));
export const identificationItems = (state) => (state.task?.items || []).filter((item) => readyForIdentification(item) && !addIdentified(item) && !addCollected(item));
export const collectionItems = (state) => (state.task?.items || []).filter((item) => item.status === 'active' && addIdentified(item) && !addCollected(item) && !unresolvedIssues(item));
const selectedItems = (state, kind) => (kind === 'identify' ? identificationItems(state) : collectionItems(state)).filter((item) => !(state.deselected?.[kind] || []).includes(item.local_id)).slice(0, 500);
const planKey = (state) => `${state.taskKey}:${state.task?.manifest.revision}:${selectedItems(state, 'identify').map((item) => item.local_id).join(',')}`;
const organizing = (state) => ['queued', 'running'].includes(state.task?.organization?.status);

export function addItem(state) {
  const items = state.task?.items || [];
  const active = items.filter((item) => item.status === 'active');
  if (state.localId) return active.find((item) => item.local_id === state.localId) || null;
  return active.length === 1 ? active[0] : null;
}
const unresolvedIssues = (item) => Boolean(item?.reviewIssues?.length && !item.reviewIssuesResolved);
export const addCollected = (item) => item?.collection_projection?.status === 'succeeded' && Boolean(item.collection_projection.collection_uri);
export const addIdentified = (item) => item?.active_identification?.status === 'succeeded' && Boolean(item.active_identification.snapshot_id) && Boolean(item.recognitionResult);
const evidenceIds = (item) => new Set((item?.evidence || []).map((entry) => entry.source_id));
const protectedPhotoOwner = (item) => {
  if (item?.active_identification != null || item?.collection_projection != null) return true;
  if (['superseded', 'archived'].includes(item?.status)) return false;
  return !['active', 'source_incomplete'].includes(item?.status) || item?.organization?.pairing_state === 'confirmed' || item?.attention_flags?.includes('identity_conflict') || isSupportMaterial(item);
};
export const editablePhotos = (item) => Boolean(item && ['active', 'source_incomplete'].includes(item.status) && item.active_identification == null && item.collection_projection == null && !item.attention_flags?.includes('identity_conflict') && !isSupportMaterial(item));
// Source references retain provenance. Only evidence ownership and equal hashes lock photos.
export function availablePhotoSources(state, localId) {
  const target = state.task?.items.find((item) => item.local_id === localId);
  if (!editablePhotos(target)) return [];
  const sources = state.task?.sources || [];
  const protectedIds = new Set((state.task.items || []).filter((item) => item.local_id !== localId && protectedPhotoOwner(item)).flatMap((item) => [...evidenceIds(item)]));
  const protectedHashes = new Set(sources.filter((source) => protectedIds.has(source.source_id) && source.sha256).map((source) => source.sha256));
  return sources.filter((source) => source.mime_type?.startsWith('image/') && !protectedIds.has(source.source_id) && !(source.sha256 && protectedHashes.has(source.sha256)));
}
export function photoDraftProblem(state) {
  const draft = state.photoEditor;
  if (!draft) return '请先打开照片调整。';
  if (draft.stale || draft.baseRevision !== state.task?.manifest.revision) return '照片或记录已更新。请刷新后重新选择，当前草稿仍保留。';
  const item = state.task?.items.find((item) => item.local_id === draft.localId);
  if (!editablePhotos(item)) return '这枚钱币的照片已锁定，请查看当前结果。';
  const missing = SIDES.filter((side) => !draft.slots[side]);
  if (missing.length) return missing.length === 2 ? '还缺正面和反面照片，请先从本批照片选择已有图片。' : `还缺${missing[0] === 'obverse' ? '正面' : '反面'}照片，请选择或补图。`;
  const [front, back] = SIDES.map((side) => state.task.sources.find((source) => source.source_id === draft.slots[side]));
  if (!front || !back) return '所选照片暂不可用，请刷新后重新选择。';
  if (front.source_id === back.source_id || (front.sha256 && front.sha256 === back.sha256)) return '正反面不能使用同一张照片，请选择不同的两面。';
  const allowed = new Set(availablePhotoSources(state, draft.localId).map((source) => source.source_id));
  if (![front, back].every((source) => allowed.has(source.source_id))) return '所选照片已属于其他已确认或已识别的钱币，请重新选择。';
  return '';
}
export function canConfirmPhotoPair(state, item) {
  if (!editablePhotos(item) || eligibleForIdentification(item)) return false;
  const evidence = item.evidence || [];
  const assignment = item.organization?.source_assignment?.length ? item.organization.source_assignment : evidence;
  if (evidence.length !== 2 || assignment.length !== 2 || evidence.some((entry) => !entry.is_primary)) return false;
  const evidenceSet = new Set(evidence.map((entry) => entry.source_id));
  if (evidenceSet.size !== 2 || assignment.some((entry) => !evidenceSet.has(entry.source_id))) return false;
  if (SIDES.some((side) => assignment.filter((entry) => entry.role === side).length !== 1 || evidence.filter((entry) => entry.role === side).length > 1)) return false;
  const roles = photoRoles(item);
  if (!SIDES.every((side) => roles[side])) return false;
  const sources = SIDES.map((side) => state.task?.sources.find((source) => source.source_id === roles[side]));
  if (sources.some((source) => !source?.mime_type?.startsWith('image/')) || sources[0].source_id === sources[1].source_id || (sources[0].sha256 && sources[0].sha256 === sources[1].sha256)) return false;
  const available = new Set(availablePhotoSources(state, item.local_id).map((source) => source.source_id));
  return sources.every((source) => available.has(source.source_id));
}
const hasRecognitionAttempt = (state) => Boolean(state.intents?.identify && state.intents.identify.status !== 'rejected');
const operationIds = (intent) => {
  const request = intent?.body || intent?.operation?.data?.request || {};
  const scope = intent?.operation?.data?.scope;
  return [...new Set((scope?.length ? scope.map((entry) => entry.local_id || entry.localId) : request.localIds || (request.items || (request.localId ? [request] : [])).map((entry) => entry.localId)).filter(Boolean))];
};
const awaitingCollectionProjection = (state) => {
  if (state.intents?.collect?.status !== 'completed') return false;
  const intent = state.intents.collect;
  const request = intent.body || intent.operation?.data?.request || {};
  const scope = intent.operation?.data?.scope;
  const ids = (scope?.length ? scope : request.items || (request.localId ? [request] : [])).map((entry) => entry.local_id || entry.localId).filter(Boolean);
  const scoped = ids.length ? ids.map((id) => state.task?.items.find((item) => item.local_id === id)) : [addItem(state)];
  return scoped.some((item) => !addCollected(item) && item?.collection_projection?.status !== 'cancelled');
};
export const hasPendingAdd = (state) => awaitingCollectionProjection(state) || Object.values(state.intents || {}).some((intent) => pendingStatuses.has(intent.status)) || (state.operations || []).some((op) => pendingStatuses.has(op.data?.status));

export function friendlyAddError(error) {
  if (error?.uploadProgress) {
    const { completed, total } = error.uploadProgress;
    return `本次已保存 ${completed}/${total} 份。${friendlyAddError({ ...error, name: error.name, message: error.message, uploadProgress: null })}`;
  }
  const code = error?.code || error?.detail?.code;
  if (error?.name === 'SyntaxError') return '结果暂时无法读取，请刷新。照片无需重传。';
  if (['stale_revision', 'revision_conflict', 'stale_plan', 'stale_snapshot', 'revision_mismatch'].includes(code)) return '照片或结果已更新，请刷新后再确认。';
  if (['account_required', 'unauthenticated', 'UNAUTHENTICATED', 'AUTH_REQUIRED'].includes(code)) return '请重新登录 HeriBase，再点“重新检查连接”。照片无需重传。';
  if (['service_invalid_response', 'offline', 'cli_unavailable', 'cli_invalid_output', 'cli_query_exception', 'API_ERROR'].includes(code)) return '连接暂不可用。请点“重新检查连接”，照片无需重传。';
  if (code === 'account_changed') return '账户已切换，请重新检查连接。';
  if (code === 'photo_source_locked') return '这张照片已属于其他已确认或已识别的钱币，请选择其他图片。';
  if (code === 'photo_target_locked') return '这枚钱币已有识别或收藏记录，不能更改照片。';
  if (code === 'photo_replacement_requires_new_task') return '这枚已有识别记录，请用“继续添加”上传新钱币。';
  if (code === 'operation_pending') return '正在确认上次结果，请刷新进度。';
  if (code === 'collection_not_allowed') return '收藏容量或权限不足，请在 HeriBase 中处理后重试。';
  if (code === 'review_conflict') return '资料与识别结果有差异，请先核对。';
  if (code === 'confirmation_interrupted') return '上次收藏未提交，请核对后重新加入收藏。';
  if (code === 'not_eligible') return identificationQuotaIssue(error.detail?.eligibility) || '当前账号识别资格不足。';
  if (code === 'identify_quota_insufficient') return '本次选择超过今日剩余额度，请减少勾选后再确认。';
  if (typeof code === 'string' && /^(cli_|connector_|API_)/.test(code)) return '操作未完成，请刷新进度。原因可在“更多”查看。';
  return error?.message || '操作未完成，请刷新进度。';
}

export function createAddController({ request, storage, makeId = () => crypto.randomUUID(), changed = () => {}, taskChanged = () => {}, collectionFinished = () => {}, timezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', now = () => new Date() }) {
  let saved = { lastTaskKey: null, sessions: {} };
  try {
    const value = JSON.parse(storage?.getItem(STORAGE_KEY) || 'null');
    if (value?.sessions && typeof value.sessions === 'object') saved = value;
  } catch { /* A damaged draft never becomes remote authority. */ }
  const state = { taskKey: null, task: null, localId: null, slots: {}, intents: {}, photoFeedback: {}, pendingSourceIds: [], uploadRemainder: [], uploadProgress: null, plan: null, busy: false, progress: '', error: '', persistenceError: false, missing: false, completion: null, planAttempt: null, diagnostic: null, operations: [], deselected: { identify: [], collect: [] }, photoEditor: null, groupOpen: {} };
  let selected = false;

  function persist() {
    if (state.taskKey) saved.sessions[state.taskKey] = { localId: state.localId, slots: clone(state.slots), intents: clone(state.intents), photoFeedback: clone(state.photoFeedback), pendingSourceIds: clone(state.pendingSourceIds), uploadRemainder: clone(state.uploadRemainder), deselected: clone(state.deselected), photoEditor: state.photoEditor ? clone(state.photoEditor) : null, groupOpen: clone(state.groupOpen) };
    saved.lastTaskKey = state.taskKey;
    try {
      if (!storage) throw new Error('storage unavailable');
      storage.setItem(STORAGE_KEY, JSON.stringify(saved));
      state.persistenceError = false;
    } catch { state.persistenceError = true; }
  }
  function select(key) {
    const session = saved.sessions[key] || {};
    Object.assign(state, { taskKey: key || null, task: null, localId: session.localId || null, slots: clone(session.slots || {}), intents: clone(session.intents || {}), pendingSourceIds: clone(session.pendingSourceIds || []), uploadRemainder: clone(session.uploadRemainder || []), deselected: clone(session.deselected || { identify: [], collect: [] }), plan: null, planAttempt: null, diagnostic: null, operations: [], error: '', missing: false, completion: null, photoEditor: session.photoEditor?.localId && session.photoEditor.slots ? clone(session.photoEditor) : null, groupOpen: clone(session.groupOpen || {}) });
    state.photoFeedback = clone(session.photoFeedback || {});
    for (const feedback of Object.values(state.photoFeedback)) {
      if (feedback.status === 'saving') Object.assign(feedback, { status: 'unknown', message: '尚未确认补图结果，请刷新查看。' });
    }
    // The prior page may have disappeared between dispatch and response.
    for (const [kind, intent] of Object.entries(state.intents)) {
      if (!intent?.body?.commandId) { delete state.intents[kind]; continue; }
      if (intent.status === 'sending') intent.status = 'unknown';
    }
    selected = true;
  }
  function adopt(task, preserveSlots = false) {
    if (!task || task.manifest.task_key !== state.taskKey) return;
    if (state.task && task.manifest.revision < state.task.manifest.revision) return;
    state.task = task;
    if (state.photoEditor && state.photoEditor.baseRevision !== task.manifest.revision) state.photoEditor.stale = true;
    for (const [id, feedback] of Object.entries(state.photoFeedback)) {
      const current = task.items.find((value) => value.local_id === id);
      if (!current) delete state.photoFeedback[id];
      else if (['saving', 'unknown'].includes(feedback.status) && feedback.baseRevision != null && task.manifest.revision > feedback.baseRevision && photoRoles(current)[feedback.side] && !needsPhoto(current)) Object.assign(feedback, { status: 'success', message: `${feedback.side === 'obverse' ? '正面' : '反面'}已补好` });
    }
    const assigned = assignedSources(task);
    state.pendingSourceIds = state.pendingSourceIds.filter((id) => !assigned.has(id));
    if (state.plan && state.plan.revision !== task.manifest.revision) state.plan = null;
    state.missing = false;
    const item = addItem(state);
    if (item) {
      state.localId = item.local_id;
      if (!preserveSlots) {
        const assignments = item.organization?.source_assignment?.length ? item.organization.source_assignment : item.evidence || [];
        state.slots = Object.fromEntries(SIDES.map((side) => {
          const source = task.sources.find((source) => source.source_id === assignments.find((entry) => entry.role === side)?.source_id);
          return [side, source ? { sourceId: source.source_id, name: source.origin?.original_name || side } : null];
        }).filter(([, value]) => value));
      }
    }
    persist();
  }
  function updateOperations(operations) {
    const known = new Map([...(state.operations || []), ...Object.values(state.intents).map((intent) => intent.operation).filter(Boolean)].map((op) => [op.id, op]));
    const incoming = operations.filter((op) => op.data?.taskKey === state.taskKey);
    state.operations = incoming.map((op) => known.get(op.id)?.revision > op.revision ? known.get(op.id) : op);
    const seen = new Set(state.operations.map((op) => op.id));
    state.operations.push(...[...known.values()].filter((op) => !seen.has(op.id)));
    for (const kind of ['identify', 'collect']) {
      const intent = state.intents[kind];
      const matches = state.operations.filter((op) => op.data?.taskKey === state.taskKey && op.data.kind === kind);
      const operation = intent ? matches.find((op) => op.id === intent.body.commandId) : matches[0];
      if (!operation) continue;
      if (intent?.operation && operation.revision < intent.operation.revision) continue;
      if (intent) Object.assign(intent, { status: operation.data.status, operation: clone(operation) });
      else state.intents[kind] = { body: clone(operation.data.request || { commandId: operation.id }), status: operation.data.status, operation: clone(operation) };
    }
    persist();
  }
  async function readCurrent({ preserveSlots = false } = {}) {
    if (!state.taskKey) return null;
    const task = await request(`/api/task?${new URLSearchParams({ key: state.taskKey })}`);
    adopt(task, preserveSlots);
    return task;
  }
  function finishCompletedBatch() {
    if (state.busy || state.photoEditor) return;
    const intent = state.intents.collect;
    const ids = operationIds(intent);
    const confirmed = intent?.showCollection && intent.status === 'completed' && ids.length
      && ids.every((id) => addCollected(state.task?.items.find((item) => item.local_id === id)));
    const notice = confirmed ? {
      taskKey: state.taskKey, count: ids.length, task: state.task,
      remaining: visibleItems(state).filter((item) => !isSupportMaterial(item) && !addCollected(item)).length,
    } : null;
    if (notice) {
      // Acknowledgement is persisted before navigation, including partial selections.
      intent.showCollection = false;
      persist();
    }
    if (addBatchComplete(state)) {
      const completion = { taskKey: state.taskKey, count: visibleItems(state).filter(addCollected).length };
      // Keep the completed task and receipts in history; only release the intake.
      persist();
      select(null);
      state.completion = completion;
      persist();
      taskChanged(null);
    }
    if (notice) collectionFinished(notice);
  }
  async function run(progress, work) {
    if (state.busy) throw new Error('正在保存当前操作，请稍候。');
    state.busy = true;
    state.error = '';
    state.progress = progress;
    changed();
    try { return await work(); }
    catch (error) {
      if (state.uploadProgress) error.uploadProgress = { completed: state.uploadProgress.completed, total: state.uploadProgress.total };
      if (!state.plan && state.task) state.planAttempt = planKey(state);
      state.error = friendlyAddError(error); state.diagnostic = error.code || error.name === 'SyntaxError' ? { code: error.code || error.name, message: error.message } : null; throw error; }
    finally { state.busy = false; state.progress = ''; state.uploadProgress = null; finishCompletedBatch(); changed(); }
  }
  function assertEditable() {
    if (hasPendingAdd(state)) throw new Error('原操作结果尚未确认，请先刷新查看进度。');
    if (addIdentified(addItem(state)) || addCollected(addItem(state))) throw new Error('这枚钱币已有结果。添加另一枚请使用“添加下一枚”。');
  }
  function assertPhotosEditable() {
    assertEditable();
    if (hasRecognitionAttempt(state)) throw new Error('这枚钱币已经提交过识别。更换照片请点击“添加另一枚”，原记录仍保留。');
  }
  function editorItem(localId) {
    if (state.busy || hasPendingAdd(state) || organizing(state)) throw new Error('正在处理照片，请稍后调整。');
    const item = state.task?.items.find((item) => item.local_id === localId);
    if (!editablePhotos(item)) throw new Error('这枚钱币已有识别或收藏记录，不能更改照片。');
    return item;
  }
  function editorDraft() {
    if (!state.photoEditor) throw new Error('请先打开照片调整。');
    editorItem(state.photoEditor.localId);
    if (state.photoEditor.stale || state.photoEditor.baseRevision !== state.task?.manifest.revision) throw new Error('照片或记录已更新，请刷新后重新选择。当前草稿仍保留。');
    return state.photoEditor;
  }
  function openEditor(localId, side) {
    const item = editorItem(localId);
    if (state.photoEditor && state.photoEditor.localId !== localId) throw new Error('请先保存或取消当前照片调整。');
    if (!state.photoEditor) {
      const roles = photoRoles(item);
      const slots = Object.fromEntries(SIDES.map((side) => [side, roles[side] || '']));
      state.photoEditor = { localId, baseRevision: state.task.manifest.revision, slots, initialSlots: clone(slots), pickerSide: SIDES.includes(side) ? side : SIDES.some((side) => slots[side]) ? null : 'obverse', stale: false, error: '' };
      state.plan = null; state.planAttempt = null;
    } else if (SIDES.includes(side)) state.photoEditor.pickerSide = side;
    persist(); changed();
    return state.photoEditor;
  }
  async function stageEditorPhoto(localId, side, file) {
    if (!SIDES.includes(side) || !/\.(jpe?g|png|webp|gif|avif|heic|heif)$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024) throw new Error('请选择一张不超过 20 MiB 的照片。');
    const draft = editorDraft();
    if (draft.localId !== localId) throw new Error('请先保存或取消当前照片调整。');
    const label = side === 'obverse' ? '正面' : '反面';
    state.photoFeedback[localId] = { side, status: 'saving', message: `正在保存${label}照片…` };
    return run(`正在保存${label}照片…`, async () => {
      await readCurrent();
      if (draft.stale || draft.baseRevision !== state.task.manifest.revision) throw new Error('照片或记录已更新，请刷新后重新选择。当前草稿仍保留。');
      let result;
      try {
        result = await request(`/api/connector/photo?${new URLSearchParams({ task: state.taskKey, revision: draft.baseRevision, localId, mode: 'stage', name: file.name })}`, file, { binary: true });
      } catch (error) {
        try { await readCurrent(); } catch { /* Keep the draft and do not repeat the upload. */ }
        draft.error = '尚未确认照片保存结果。请刷新后从本批照片中选择，系统不会重复上传。';
        draft.stale = true;
        state.photoFeedback[localId] = { side, status: 'error', message: draft.error };
        persist(); throw error;
      }
      if (!result.source?.source_id || result.revision == null) throw new Error('照片保存回执不完整，请刷新后从本批照片中选择。');
      draft.slots[side] = result.source.source_id;
      draft.pickerSide = null;
      draft.error = '';
      await readCurrent();
      if (state.task.manifest.revision === result.revision) { draft.baseRevision = result.revision; draft.stale = false; }
      state.photoFeedback[localId] = { side, status: 'success', message: `${label}照片已保存，点击“保存并继续”确认正反面。` };
      persist();
    });
  }
  function savePhotoPair(body, draft = null) {
      return run('正在保存正反面…', async () => {
        await readCurrent();
        if (draft?.stale || state.task.manifest.revision !== body.expectedRevision) throw new Error('照片或记录已更新，请刷新后重新选择。当前草稿仍保留。');
        let task;
        try { task = await request('/api/connector/photos', body); }
        catch (error) {
          try { await readCurrent(); } catch { /* A local write is never replayed automatically. */ }
          const current = state.task?.items.find((value) => value.local_id === body.localId), roles = photoRoles(current);
          if ((!error.code || ['offline', 'service_invalid_response'].includes(error.code)) && current?.organization?.pairing_state === 'confirmed' && roles.obverse === body.obverseSourceId && roles.reverse === body.reverseSourceId) task = state.task;
          else { if (draft) { draft.stale = true; draft.error = '保存结果暂未确认，请刷新后重新选择。系统不会重复保存。'; } persist(); throw error; }
        }
        adopt(task);
        state.photoEditor = null;
        state.photoFeedback[body.localId] = { status: 'success', message: '正反面已保存，可以继续识别。' };
        state.plan = null; state.planAttempt = null; persist();
        if (!state.pendingSourceIds.length && !organizing(state) && !hasPendingAdd(state) && selectedItems(state, 'identify').length) await loadPlan();
        return task;
      });
  }
  async function prepare() {
    if (!SIDES.every((side) => state.slots[side]?.sourceId)) return;
    const task = await request('/api/connector/prepare', {
      taskKey: state.taskKey, expectedRevision: state.task.manifest.revision,
      obverseSourceId: state.slots.obverse.sourceId, reverseSourceId: state.slots.reverse.sourceId,
    });
    adopt(task);
  }
  async function loadPlan() {
    const ids = selectedItems(state, 'identify').map((item) => item.local_id);
    if (!ids.length) throw new Error('请勾选图片完整、可以识别的钱币。');
    const revision = state.task.manifest.revision;
    state.planAttempt = planKey(state);
    state.plan = null;
    const plan = await request('/api/connector/identification-plan', { taskKey: state.taskKey, expectedRevision: revision, localIds: ids });
    if (plan.taskKey !== state.taskKey || plan.revision !== revision || !plan.hash || plan.items?.length !== ids.length || plan.items.some((item, index) => item.localId !== ids[index])) throw new Error('识别范围回执不完整，请刷新后重新检查。');
    state.plan = freeze(clone(plan));
    return state.plan;
  }
  function scopeItem() {
    const item = addItem(state);
    if (!item) throw new Error('请先选择这枚钱币的正反面照片。');
    return item;
  }
  async function submit(kind, body) {
    if (hasPendingAdd(state)) throw new Error('原操作结果尚未确认，不会重复发送。请刷新查看进度。');
    const intent = { body: { ...clone(body), commandId: makeId() }, status: 'sending', ...(kind === 'collect' ? { showCollection: true } : {}) };
    state.intents[kind] = intent;
    // Failure to persist the intent must stop BEFORE a potentially chargeable request.
    persist();
    if (state.persistenceError) {
      delete state.intents[kind];
      throw new Error('浏览器无法保存本次操作标识。请允许本地存储后再确认，尚未发送线上操作。');
    }
    changed();
    let operation;
    try {
      operation = await request(`/api/connector/${kind === 'collect' && intent.body.items ? 'collect-batch' : kind}`, clone(intent.body));
    } catch (error) {
      intent.status = error.detail?.remoteWriteStarted === false || rejectedCodes.has(error.code || error.detail?.code) ? 'rejected' : 'unknown';
      persist();
      if (intent.status === 'unknown') state.error = '请求结果尚未确认。请刷新查看原操作；不会自动重复上传、识别或收藏。';
      // Read-only recovery can discover a persisted operation even when the response was lost.
      try { await refresh(); } catch { /* Keep the original intent for the next read. */ }
      if (intent.operation && ['preparing', 'queued', 'running', 'completed'].includes(intent.status)) { state.error = ''; return intent.operation; }
      if (intent.status === 'unknown') throw new Error('请求结果尚未确认。请刷新查看原操作；不会自动重复上传、识别或收藏。');
      throw error;
    }
    if (!intent.operation || !(intent.operation.revision > operation.revision)) {
      intent.status = operation.data?.status || 'unknown';
      intent.operation = clone(operation);
    }
    persist();
    // A successful dispatch is already acknowledged; a failed read must not turn it into a new write.
    try { await readCurrent(); } catch { state.error = '操作已接收，进度暂未更新。请刷新查看结果。'; }
    return operation;
  }
  async function refresh() {
    await readCurrent();
    const workspace = await request('/api/snapshot');
    updateOperations(workspace.operations || []);
    changed();
    return state.task;
  }
  return {
    state,
    get photosDirty() { return Boolean(state.photoEditor && JSON.stringify(state.photoEditor.slots) !== JSON.stringify(state.photoEditor.initialSlots)); },
    get hasPhotoDraft() { return Boolean(state.photoEditor); },
    openPhotos: openEditor,
    photoSide(side) {
      const draft = editorDraft();
      if (!SIDES.includes(side)) return;
      draft.pickerSide = side; draft.error = ''; persist(); changed();
    },
    choosePhoto(sourceId) {
      const draft = editorDraft(), side = draft.pickerSide;
      if (!SIDES.includes(side)) throw new Error('请先选择要调整的正面或反面。');
      const source = availablePhotoSources(state, draft.localId).find((source) => source.source_id === sourceId);
      if (!source) throw new Error('这张照片已属于其他已确认或已识别的钱币，请选择其他图片。');
      const otherSide = side === 'obverse' ? 'reverse' : 'obverse';
      const other = state.task.sources.find((value) => value.source_id === draft.slots[otherSide]);
      if (other && (other.source_id === sourceId || (source.sha256 && source.sha256 === other.sha256))) {
        draft.error = '正反面不能使用同一张照片，请选择不同的两面。'; changed(); throw new Error(draft.error);
      }
      draft.slots[side] = sourceId; draft.pickerSide = null; draft.error = ''; persist(); changed();
    },
    swapPhotos() {
      const draft = editorDraft();
      [draft.slots.obverse, draft.slots.reverse] = [draft.slots.reverse, draft.slots.obverse];
      draft.pickerSide = null; draft.error = ''; persist(); changed();
    },
    cancelPhotos() {
      if (state.busy) return;
      state.photoEditor = null; state.planAttempt = null; persist(); changed();
    },
    async refreshPhotos() {
      const id = state.photoEditor?.localId;
      if (!id) return;
      return run('正在读取最新照片…', async () => {
        await readCurrent();
        const item = state.task?.items.find((value) => value.local_id === id);
        if (!editablePhotos(item)) throw new Error('这枚钱币已有识别或收藏记录，请取消调整后查看结果。');
        const roles = photoRoles(item);
        const slots = Object.fromEntries(SIDES.map((side) => [side, roles[side] || '']));
        state.photoEditor = { localId: id, baseRevision: state.task.manifest.revision, slots, initialSlots: clone(slots), pickerSide: null, stale: false, error: '' };
        state.plan = null; state.planAttempt = null; persist();
      });
    },
    async savePhotos() {
      const draft = editorDraft(), problem = photoDraftProblem(state);
      if (problem) { draft.error = problem; changed(); throw new Error(problem); }
      const body = { taskKey: state.taskKey, expectedRevision: draft.baseRevision, localId: draft.localId, obverseSourceId: draft.slots.obverse, reverseSourceId: draft.slots.reverse };
      return savePhotoPair(body, draft);
    },
    async confirmPhotos(localId) {
      if (state.photoEditor) throw new Error('请先保存或取消当前照片调整。');
      const item = editorItem(localId);
      if (!canConfirmPhotoPair(state, item)) throw new Error('请先选择这枚钱币的正面和反面。');
      const roles = photoRoles(item);
      return savePhotoPair({ taskKey: state.taskKey, expectedRevision: state.task.manifest.revision, localId, obverseSourceId: roles.obverse, reverseSourceId: roles.reverse });
    },
    setGroupOpen(group, open) {
      if (!['pending', 'missing', 'support'].includes(group)) return;
      state.groupOpen[group] = Boolean(open); persist();
    },
    get needsPlan() {
      return !state.photoEditor && !state.busy && !organizing(state) && !state.plan && !state.missing && !hasPendingAdd(state) && !state.pendingSourceIds.length && selectedItems(state, 'identify').length > 0 && state.planAttempt !== planKey(state);
    },
    sync(key, tasks = [], operations = []) {
      const wanted = key || (selected ? state.taskKey : saved.lastTaskKey);
      if (!selected || (key && key !== state.taskKey)) select(wanted);
      // A slow dispatch response must not hide newer progress from event polling.
      if (state.busy && state.taskKey) updateOperations(operations);
      if (!state.busy && state.taskKey) {
        const task = tasks.find((task) => task.manifest.task_key === state.taskKey);
        if (task) adopt(task);
        else state.missing = !state.task;
        updateOperations(operations);
        finishCompletedBatch();
      }
    },
    async upload(input) {
      if (state.photoEditor) throw new Error('请先保存或取消当前照片调整，再添加资料。');
      const files = [...input];
      if (!files.length) return;
      for (const file of files) {
        if (!/\.(jpe?g|png|webp|gif|avif|heic|heif|csv|xlsx|pdf|txt)$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024) throw new Error('请选择照片、CSV、XLSX、PDF 或 TXT，每个文件不超过 20 MiB。文件夹可在当前聊天中提供。');
      }
      if (hasPendingAdd(state)) throw new Error('原操作结果尚未确认，请先核验进度，再添加资料。');
      if (state.busy) throw new Error('正在保存当前操作，请稍候。');
      state.uploadProgress = { completed: 0, total: files.length, name: files[0].name };
      return run('正在保存资料到本机…', async () => {
        if (state.taskKey) await refresh();
        if (hasPendingAdd(state)) throw new Error('原操作结果尚未确认，请先核验进度，再添加资料。');
        const completedWork = state.operations.length || state.task?.items.some((item) => item.active_identification || item.collection_projection?.collection_uri);
        const hasIncompleteCoins = (state.task?.items || []).some(needsPhoto);
        if (!state.taskKey || (completedWork && !hasIncompleteCoins && !organizing(state))) {
          const task = await request('/api/tasks/create', { name: `钱币 · ${now().toLocaleString('zh-CN', { hour12: false })}`, timezone: timezone() });
          select(task.manifest.task_key);
          adopt(task, true);
          taskChanged(state.taskKey);
        }
        state.plan = null;
        state.planAttempt = null;
        const previous = new Map();
        for (const name of state.uploadRemainder) previous.set(name, (previous.get(name) || 0) + 1);
        for (const file of files) {
          if (previous.get(file.name)) previous.set(file.name, previous.get(file.name) - 1);
          else state.uploadRemainder.push(file.name);
        }
        persist();
        for (let index = 0; index < files.length; index++) {
          state.progress = `正在保存 ${index + 1}/${files.length}：${files[index].name}`;
          state.uploadProgress.name = files[index].name;
          changed();
          let result;
          for (let attempt = 0; attempt < 2; attempt++) {
            try {
              result = await request(`/api/upload?${new URLSearchParams({ task: state.taskKey, revision: state.task.manifest.revision, name: files[index].name })}`, files[index], { binary: true });
              break;
            } catch (error) {
              if (attempt || error.status !== 409 || (error.code || error.detail?.code) !== 'revision_conflict') throw error;
              await readCurrent();
            }
          }
          if (!result.source?.source_id) throw new Error('资料保存回执不完整，请刷新检查已保存的文件后再继续。');
          state.pendingSourceIds.push(result.source.source_id);
          state.uploadRemainder.splice(state.uploadRemainder.indexOf(files[index].name), 1);
          state.uploadProgress.completed++;
          persist();
          await readCurrent();
          changed();
        }
        // Each upload is already durably queued by the server. This releases the batch
        // immediately; if the response is lost the server's quiet-period fallback still runs.
        state.uploadProgress = null;
        state.progress = '正在开始整理照片…';
        changed();
        try {
          await request('/api/connector/organize', { taskKey: state.taskKey, expectedRevision: state.task.manifest.revision });
          await readCurrent();
        } catch { state.error = '资料已保存，自动整理状态暂未同步。请刷新进度，已保存的文件无需重传。'; }
      });
    },
    async organize() {
      if (state.photoEditor) throw new Error('请先保存或取消当前照片调整。');
      if (hasPendingAdd(state)) throw new Error('请先核验原操作，再重新整理资料。');
      return run('正在提交整理任务…', async () => {
        await readCurrent();
        await request('/api/connector/organize', { taskKey: state.taskKey, expectedRevision: state.task.manifest.revision, retry: true });
        await refresh();
      });
    },
    async supplement(localId, side, file) {
      if (!file) return;
      if (state.photoEditor) {
        const draft = state.photoEditor;
        draft.error = '';
        try { return await stageEditorPhoto(localId, side, file); }
        catch (error) {
          const message = draft.error || friendlyAddError(error);
          if (state.photoEditor === draft) draft.error = message;
          state.photoFeedback[localId] = { side, status: 'error', message };
          state.error = '';
          persist(); changed();
          throw error;
        }
      }
      const label = side === 'obverse' ? '正面' : '反面';
      try {
        if (!SIDES.includes(side) || !/\.(jpe?g|png|webp|gif|avif|heic|heif)$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024) throw new Error('请选择一张不超过 20 MiB 的照片。');
        if (hasPendingAdd(state) || organizing(state)) throw new Error('正在处理照片，请稍后补图。');
        state.photoFeedback[localId] = { side, status: 'saving', message: `正在补${label}…` };
        persist();
        const result = await run(`正在补${label}…`, async () => {
          await refresh();
          const item = state.task?.items.find((value) => value.local_id === localId);
          if (missingSide(item) !== side || item.active_identification || item.collection_projection) throw new Error('照片已更新，请查看当前缺少哪一面。');
          state.photoFeedback[localId].baseRevision = state.task.manifest.revision;
          persist();
          state.plan = null;
          state.planAttempt = null;
          try {
            await request(`/api/connector/photo?${new URLSearchParams({ task: state.taskKey, revision: state.task.manifest.revision, localId, side, name: file.name })}`, file, { binary: true });
          } catch (error) {
            // Local photo + pairing commit together. A lost reply can be resolved
            // by reading the card; never send the same upload automatically.
            try { await refresh(); } catch { throw error; }
            const current = state.task?.items.find((value) => value.local_id === localId);
            if (!photoRoles(current)[side]) throw error;
          }
          await refresh();
        });
        state.photoFeedback[localId] = { side, status: 'success', message: `${label}已补好` };
        persist(); changed();
        return result;
      } catch (error) {
        const message = /这张照片已在使用/.test(error.message || '') ? `这张照片已上传过，请选择缺少的${label}。` : friendlyAddError(error);
        state.photoFeedback[localId] = { side, status: 'error', message };
        state.error = '';
        persist(); changed();
        throw error;
      }
    },
    async pick(side, file) {
      if (!SIDES.includes(side) || !file) return;
      if (!/\.(jpe?g|png|webp|gif|avif|heic|heif)$/i.test(file.name) || !file.size || file.size > 20 * 1024 * 1024) throw new Error('请选择一张不超过 20 MiB 的图片。');
      assertPhotosEditable();
      return run(`正在保存${side === 'obverse' ? '正面' : '反面'}照片到本机…`, async () => {
        state.plan = null;
        if (!state.taskKey) {
          const stamp = now().toLocaleString('zh-CN', { hour12: false });
          const task = await request('/api/tasks/create', { name: `钱币 · ${stamp}`, timezone: timezone() });
          select(task.manifest.task_key);
          adopt(task, true);
          taskChanged(state.taskKey);
        } else await readCurrent({ preserveSlots: true });
        const result = await request(`/api/upload?${new URLSearchParams({ task: state.taskKey, revision: state.task.manifest.revision, name: file.name })}`, file, { binary: true });
        const sourceId = result.source?.source_id;
        if (!sourceId) throw new Error('照片保存回执不完整，请刷新后重新选择该面照片。');
        state.slots[side] = { sourceId, name: file.name };
        persist();
        await readCurrent({ preserveSlots: true });
        await prepare();
        if (SIDES.every((side) => state.slots[side]?.sourceId)) await loadPlan();
      });
    },
    async swap() {
      assertPhotosEditable();
      return run('正在保存照片方向…', async () => {
        if (!SIDES.every((side) => state.slots[side]?.sourceId)) throw new Error('请选择正反面照片后再交换。');
        state.plan = null;
        [state.slots.obverse, state.slots.reverse] = [state.slots.reverse, state.slots.obverse];
        persist();
        await readCurrent({ preserveSlots: true });
        await prepare();
        if (SIDES.every((side) => state.slots[side]?.sourceId)) await loadPlan();
      });
    },
    async preview() {
      if (state.photoEditor) throw new Error('请先保存或取消当前照片调整。');
      if (hasPendingAdd(state)) throw new Error('请先核验原操作结果。');
      return run('正在检查识别范围…', async () => {
        await readCurrent({ preserveSlots: true });
        if (state.pendingSourceIds.length || organizing(state)) throw new Error('新资料正在整理，请稍候查看最新配对结果。');
        // Legacy drafts may carry explicit user-selected slots. Existing Agent
        // organization is read without manufacturing a human pairing decision.
        if (!addItem(state) && SIDES.every((side) => state.slots[side]?.sourceId)) await prepare();
        if (!selectedItems(state, 'identify').length) throw new Error('配对尚需核对，或尚未勾选可以识别的钱币。');
        return loadPlan();
      });
    },
    async identify() {
      if (state.photoEditor) throw new Error('请先保存当前照片，再确认识别。');
      const plan = state.plan;
      if (!plan) throw new Error('请先检查连接，查看本次识别范围。');
      const quotaIssue = identificationQuotaIssue(plan.eligibility, plan.items.length);
      if (quotaIssue) throw Object.assign(new Error(quotaIssue), { code: plan.eligibility?.allowed === false ? 'not_eligible' : 'identify_quota_insufficient' });
      if (state.taskKey !== plan.taskKey || state.task?.manifest.revision !== plan.revision || JSON.stringify(selectedItems(state, 'identify').map((item) => item.local_id)) !== JSON.stringify(plan.items.map((item) => item.localId))) {
        state.plan = null;
        throw new Error('照片或记录已更新。请重新点击“开始识别”，确认最新范围。');
      }
      return run('正在提交已确认的识别…', async () => {
        try {
          const result = await submit('identify', { taskKey: plan.taskKey, expectedRevision: plan.revision, planHash: plan.hash, localIds: plan.items.map((item) => item.localId) });
          state.plan = null;
          return result;
        } catch (error) {
          // 确认时可能已有其他设备消耗额度，用服务端复核结果替换旧预览。
          if (state.taskKey === plan.taskKey && error.detail?.eligibility) {
            state.plan = freeze({ ...plan, eligibility: clone(error.detail.eligibility) });
          }
          throw error;
        }
      });
    },
    async collect() {
      if (state.photoEditor) throw new Error('请先保存或取消当前照片调整。');
      const items = selectedItems(state, 'collect');
      if (!items.length) {
        if (state.completion) return null;
        if (visibleItems(state).length && visibleItems(state).every(addCollected)) return null;
        if (unresolvedIssues(addItem(state))) throw new Error('来源资料与识别结果有差异，请先核对实物并记录判断依据。');
        throw new Error('请先查看并勾选成功识别的最新结果。');
      }
      // Capture every displayed immutable snapshot before the first asynchronous request.
      const scope = items.map((item) => ({ localId: item.local_id, snapshotId: item.active_identification.snapshot_id }));
      const body = { taskKey: state.taskKey, expectedRevision: state.task.manifest.revision,
        ...(scope.length === 1 ? scope[0] : { items: scope }) };
      return run('正在将已确认的钱币加入收藏…', () => submit('collect', body));
    },
    toggle(kind, id, checked) {
      if (!['identify', 'collect'].includes(kind) || state.photoEditor || state.busy || hasPendingAdd(state)) return;
      const list = kind === 'identify' ? identificationItems(state) : collectionItems(state);
      if (!list.some((item) => item.local_id === id)) return;
      const excluded = new Set(state.deselected[kind]);
      if (checked) excluded.delete(id); else excluded.add(id);
      state.deselected[kind] = [...excluded];
      if (kind === 'identify') { state.plan = null; state.planAttempt = null; }
      persist(); changed();
    },
    refresh: () => run('正在读取已保存的进度…', refresh),
    newCoin() {
      if (state.photoEditor) throw new Error('请先保存或取消当前照片调整。');
      if (state.busy || hasPendingAdd(state)) throw new Error('请先核验原操作结果，再添加下一枚。');
      select(null);
      persist();
      taskChanged(null);
      changed();
    },
  };
}

const quotaCount = (value) => Number.isSafeInteger(value) && value >= 0;

export function identificationQuotaIssue(eligibility, count) {
  const remaining = eligibility?.remainingTimes;
  if (remaining === 0 || eligibility?.allowed === false && (eligibility.reason === 'identify_limit' || eligibility.limitStatus > 0)) return '今日识别额度已用完';
  if (eligibility?.allowed === false) return '当前账号识别资格不足';
  if (quotaCount(remaining) && remaining < count) return `本次选了 ${count} 枚，今日还可识别 ${remaining} 枚`;
  return '';
}

export function identificationQuotaNotice(eligibility, apiBaseUrl, count) {
  const issue = identificationQuotaIssue(eligibility, count);
  if (!issue) return '';
  const { dailyLimit, usedTimes, remainingTimes } = eligibility || {};
  const figures = [
    quotaCount(dailyLimit) && quotaCount(usedTimes) ? `已用 ${usedTimes}/${dailyLimit} 次` : '',
    quotaCount(remainingTimes) ? `剩余 ${remainingTimes} 次` : '',
  ].filter(Boolean).join('，');
  let guide = '';
  try {
    // 仅打开账户所绑定 API 的官方回流入口，拒绝任意外站、协议和凭据。
    const base = new URL(apiBaseUrl);
    const target = new URL(eligibility?.guide?.guideUrl || '', base);
    if (['https:', 'http:'].includes(base.protocol) && target.origin === base.origin && !target.username && !target.password &&
        target.pathname === '/agent/v1/app-guides/page' && target.searchParams.get('uri')) guide = target.href;
  } catch { /* 无可用引导时仍展示额度与重新检查入口。 */ }
  const next = eligibility?.allowed === false || remainingTimes === 0 ? '资料已保留，识别资格恢复后可以继续。' : '请减少勾选后再确认。';
  return `<div class="note identify-quota-notice" role="status"><strong>${e(issue)}</strong><p>${figures ? `${e(figures)}。 ` : ''}${next}</p>${guide ? `<a class="button quiet small" href="${e(guide)}" target="_blank" rel="noopener noreferrer">在 HeriBase 查看额度</a>` : ''}</div>`;
}

export function identificationNotice(plan) {
  const count = plan.items?.length || 1;
  const blocked = identificationQuotaNotice(plan.eligibility, plan.account?.apiBaseUrl, count);
  if (blocked) return blocked;
  const remaining = plan.eligibility?.remainingTimes ?? plan.quota?.remainingTimes ?? plan.remainingTimes;
  const cost = plan.cost?.amount ?? plan.cost?.value ?? (typeof plan.cost === 'number' ? plan.cost : undefined);
  const required = plan.eligibility?.requiredTimes ?? plan.quota?.requiredTimes;
  const allowance = remaining !== undefined && remaining !== null && remaining !== '' ? `剩余 ${scalar(remaining)} 次` : '剩余次数未返回';
  const usage = required !== undefined && required !== null ? `本次使用 ${scalar(required)} 次` : '本次用量未返回';
  const price = cost !== undefined && cost !== null ? `费用 ${scalar(cost)} ${scalar(plan.cost?.currency)}`.trim() : '费用未返回';
  return `<div class="add-confirm"><p>将上传 ${count * 2} 张照片到 HeriBase。</p><p class="add-quota">${e(`${allowance} · ${usage} · ${price}`)}</p><details class="add-account"><summary>识别账户</summary><p>${e(plan.account?.subject || '未提供')}</p></details></div>`;
}

function reference(url) {
  try { const u = new URL(url); return u.protocol === 'https:' && ['cdn.heritcoin.com', 'cdn.heribase.com'].includes(u.hostname) && !u.username && !u.password && !u.port ? u.href : null; } catch { return null; }
}
function resultBody(item) {
  const result = item.recognitionResult || {};
  const attributes = Array.isArray(result.attributes) ? result.attributes : [];
  const value = (key) => scalar(attributes.find((attribute) => scalar(attribute?.name).trim().toLowerCase() === key.toLowerCase())?.value);
  const facts = (entries) => entries.map(([label, value]) => `<div><dt>${e(label)}</dt><dd>${e(scalar(value).trim() || '—')}</dd></div>`).join('');
  const identity = facts([['国家 / 地区', value('Country')], ['面额', value('Denomination')], ['年份', result.year], ['材质', value('Metal')], ['目录编号', value('Krause number')], ['造币标记', /^none$/i.test(scalar(result.mintMark).trim()) ? '—' : result.mintMark]]);
  const specifications = facts([['重量', value('weight')], ['直径', value('diameter')], ['厚度', value('thickness')], ['发行量', value('Mintage')]]);
  const referenceImages = Array.isArray(result.referenceImages) ? result.referenceImages : [];
  const referenceEntries = [['frontInfo', '正面'], ['backInfo', '反面']].map(([key, side]) => ({ url: reference(result.obverseReverseInfo?.[key]?.img), label: `参考${side}` })).filter((entry) => entry.url);
  const mapped = new Set(referenceEntries.map((entry) => entry.url));
  const extraReferences = [...new Set(referenceImages.map(reference).filter((url) => url && !mapped.has(url)))];
  referenceEntries.push(...extraReferences.map((url, index) => ({ url, label: `参考图 ${index + 1} · 面别未标明` })));
  const references = referenceEntries.map(({ url, label }) => `<figure><button type="button" class="add-reference-photo" data-action="zoom" data-image-kind="reference" data-url="${e(url)}" aria-label="查看${e(result.title || '钱币')} · 服务${e(label)}"><img src="${e(url)}" alt="服务${e(label)}" referrerpolicy="no-referrer" loading="lazy"></button><figcaption>${e(label)}</figcaption></figure>`).join('');
  const price = scalar(result.price?.value);
  return `<section class="add-recognition-data" aria-label="币种资料"><dl class="add-recognition-facts">${identity}</dl><dl class="add-specification-facts" aria-label="规格与发行">${specifications}</dl>${price ? `<div class="add-reference-price"><div><span>服务参考价</span><strong>${e(price)} ${e(scalar(result.price?.currency))}</strong></div><small>品相、报价日期未提供</small></div>` : ''}</section>${references ? `<section class="add-reference-section" aria-label="服务参考图片"><div class="add-reference-heading"><h4>参考图</h4><span>用于比对币种，非本枚实物</span></div><div class="add-reference-grid">${references}</div></section>` : ''}`;
}

function reviewNotice(state, item) {
  if (!unresolvedIssues(item)) return '';
  return `<div class="note add-error"><strong>来源资料与识别结果有差异</strong>${item.reviewIssues.map((issue) => `<p>${e(issue.field)}：${e(issue.source)}「${e(issue.original)}」<br>识别返回「${e(issue.recognized)}」</p>`).join('')}<p>请对照实物核对，并记录判断依据后再加入收藏。</p><a class="button quiet small" href="${e(route('review', state.taskKey, item.local_id))}">核对完整识别资料</a></div>`;
}

const isSupportMaterial = (item) => ['promotional_material', 'document'].includes(item.organization?.input_kind) || ['promotional_material', 'document'].includes(item.field_claims?.visual_analysis?.classification);
const visibleItems = (state) => (state.task?.items || []).filter((item) => ['active', 'source_incomplete', 'identity_conflict'].includes(item.status));
const originalSources = (state) => (state.task?.sources || []).filter((source) => !source.parent_source_id);
const needsPhoto = (item) => !isSupportMaterial(item) && (item.status === 'source_incomplete' || item.organization?.pairing_state === 'single_side' || item.attention_flags?.includes('source_incomplete'));
const photoRoles = (item) => Object.fromEntries((item?.organization?.source_assignment?.length ? item.organization.source_assignment : (item?.evidence || []).filter((entry) => entry.is_primary)).filter((entry) => SIDES.includes(entry.role)).map((entry) => [entry.role, entry.source_id]));
const missingSide = (item) => {
  if (!item || !needsPhoto(item)) return null;
  const roles = photoRoles(item);
  return SIDES.filter((side) => roles[side]).length === 1 ? SIDES.find((side) => !roles[side]) : null;
};
export function addBatchComplete(state) {
  if (!state.task || state.task.health?.ok === false || state.missing || organizing(state) || state.task.organization?.status === 'failed' || hasPendingAdd(state) || state.pendingSourceIds?.length || state.uploadRemainder?.length) return false;
  const coins = visibleItems(state).filter((item) => !isSupportMaterial(item));
  const assigned = assignedSources(state.task);
  return coins.length > 0 && coins.every((item) => item.status === 'active' && !needsPhoto(item) && !unresolvedIssues(item) && addCollected(item)) && originalSources(state).every((source) => assigned.has(source.source_id));
}
function assignedSources(task) {
  const assigned = new Set((task?.items || []).filter((item) => !['superseded', 'archived'].includes(item.status)).flatMap((item) => [...(item.source_refs || []), ...(item.evidence || []).map((entry) => entry.source_id)]));
  const parents = new Map((task?.sources || []).map((source) => [source.source_id, source.parent_source_id]));
  for (const id of assigned) {
    const parent = parents.get(id);
    if (parent) assigned.add(parent);
  }
  return assigned;
}

export function addWorkSummary(state) {
  const items = visibleItems(state), coins = items.filter((item) => !isSupportMaterial(item));
  const uploaded = originalSources(state).length;
  const ready = identificationItems(state).length;
  const missing = coins.filter(needsPhoto).length;
  const identified = coins.filter(addIdentified).length;
  const collected = coins.filter(addCollected).length;
  const attention = items.filter((item) => isSupportMaterial(item) || unresolvedIssues(item) || (!needsPhoto(item) && !eligibleForIdentification(item) && !addIdentified(item) && !addCollected(item))).length;
  const assigned = assignedSources(state.task);
  const unorganized = originalSources(state).filter((source) => !assigned.has(source.source_id)).length;
  const pending = hasPendingAdd(state);
  const statuses = [...Object.values(state.intents || {}).map((intent) => intent.status), ...(state.operations || []).map((operation) => operation.data?.status)];
  let phase = 'empty', title = '添加钱币', message = '';
  if (uploaded) {
    phase = 'waiting'; title = '照片已保存';
    message = '正在等待整理，照片不用重传。';
  }
  if (items.length) {
    phase = identified > collected ? 'review' : ready ? 'ready' : collected === coins.length && coins.length ? 'complete' : 'attention';
    title = phase === 'ready' ? `可识别 ${ready} 枚` : phase === 'review' ? `待收藏 ${identified - collected} 枚` : phase === 'complete' ? `已收藏 ${collected} 枚${missing ? ` · 待补图 ${missing} 枚` : ''}` : missing ? `待补图 ${missing} 枚` : '有资料需要确认';
    message = '';
  }
  if (items.length && unorganized) {
    phase = 'waiting'; title = `${unorganized} 份新照片待整理`;
    message = '已有结果保留。';
  }
  const job = state.task?.organization;
  if (organizing(state)) {
    phase = 'organizing'; title = job.status === 'queued' ? '准备整理照片…' : '正在整理照片…'; message = '';
  } else if (job?.status === 'failed') {
    phase = 'failed'; title = '整理暂未完成'; message = job.message;
  }
  if (state.busy && state.progress?.startsWith('正在保存')) { phase = 'uploading'; title = '正在保存资料'; message = state.progress; }
  if (state.task?.health?.ok === false) { phase = 'blocked'; title = '资料完整性需要检查'; message = '本地记录未通过完整性检查，请先查看原因。'; }
  if (pending) {
    phase = statuses.some((status) => ['unknown', 'sending', 'reconcile_required'].includes(status)) ? 'reconcile' : 'processing';
    title = phase === 'reconcile' ? '正在确认结果…' : '正在处理…';
    message = phase === 'reconcile' ? '请刷新查看，请勿重复提交。' : '';
  }
  return { phase, title, message, uploaded, ready, missing, attention, identified, collected, unorganized, organized: items.length, coins: coins.length };
}

export function addActivity(state) {
  const summary = addWorkSummary(state);
  const upload = state.uploadProgress;
  if (upload) return {
    state: 'working', stage: 0, title: '正在保存照片与资料',
    message: upload.name, count: `${upload.completed} / ${upload.total} 份已保存`,
    percent: upload.completed / upload.total * 100,
  };
  const intent = ['collect', 'identify'].map((kind) => {
    const value = state.intents?.[kind];
    return value && { ...value, kind };
  }).find((value) => value && (pendingStatuses.has(value.status) || (value.kind === 'collect' && awaitingCollectionProjection(state))))
    || (state.operations || []).filter((op) => pendingStatuses.has(op.data?.status)).map((op) => ({ operation: op, kind: op.data.kind, status: op.data.status }))[0];
  if (intent) {
    const collect = intent.kind === 'collect', stage = collect ? 3 : 2;
    const ids = operationIds(intent), scope = new Set(ids);
    const results = new Map((intent.operation?.data?.itemResults || []).filter((result) => scope.has(result.localId)).map((result) => [result.localId, result.status]));
    const succeeded = [...results.values()].filter((status) => status === 'succeeded').length;
    const failed = [...results.values()].filter((status) => status === 'failed').length;
    const unmatched = [...results.values()].filter((status) => status === 'recognition_failed').length;
    const uncertain = [...results.values()].filter((status) => status === 'reconcile_required').length;
    const paused = ['unknown', 'reconcile_required', 'partial_failed'].includes(intent.status);
    const projection = collect && intent.status === 'completed';
    return {
      state: paused ? 'error' : 'working', stage,
      title: paused ? (intent.status === 'partial_failed' ? '部分未完成' : '结果待确认') : projection ? '正在更新收藏结果' : collect ? '正在加入收藏' : '正在识别',
      message: paused ? '点“刷新进度”核对结果。' : projection ? '收藏已提交，正在读取保存结果。' : collect ? '保存完成后自动进入我的收藏。' : '结果会逐枚显示。',
      count: ids.length ? `${succeeded} / ${ids.length} 枚${collect ? '已收藏' : '识别成功'}` : '',
      detail: [failed && `${failed} 枚未完成`, unmatched && `${unmatched} 枚未识别出`, uncertain && `${uncertain} 枚待确认`].filter(Boolean).join(' · '),
      // Old failures survive retries. Only success advances the meter; a running
      // operation with all receipts still needs its final status/projection.
      percent: !paused && !projection && ids.length && succeeded < ids.length ? succeeded / ids.length * 100 : null,
    };
  }
  const job = state.task?.organization;
  if (organizing(state)) return {
    state: 'working', stage: 1, title: job.status === 'queued' ? '等待整理' : '正在整理照片',
    message: job.status === 'queued' ? '照片已保存，等待开始。' : ({
      reading: '读取照片与资料', analyzing: '匹配正反面，整理钱币', saving: '保存整理结果',
    }[job.stage] || '正在匹配正反面'),
    count: `${job.sourceIds?.length || summary.uploaded} 份资料`, percent: null,
  };
  if (state.busy) return {
    state: 'working', stage: /检查|识别/.test(state.progress) ? 2 : /收藏/.test(state.progress) ? 3 : 1,
    title: /检查/.test(state.progress) ? '正在检查识别条件' : state.progress?.replace(/[…。]+$/, '') || '正在更新进度',
    message: '', percent: null,
  };
  if (job?.status === 'failed') return { state: 'error', stage: 1, title: '整理未完成', message: '点“重新整理”继续，照片无需重传。' };
  if (state.task?.health?.ok === false || state.missing) return { state: 'error', stage: 1, title: '暂时无法继续', message: summary.message || '请刷新查看记录。' };
  const failed = ['collect', 'identify'].find((kind) => ['failed', 'blocked'].includes(state.intents?.[kind]?.status));
  if (failed) return { state: 'error', stage: failed === 'collect' ? 3 : 2, title: failed === 'collect' ? '收藏未完成' : '识别未完成', message: '查看下方提示后重试。' };
  if (summary.phase === 'ready') return { state: 'waiting', stage: 2, title: '整理完成，等待识别', message: '确认下方照片后，点击识别。', count: `${summary.ready} 枚可识别` };
  if (summary.phase === 'review') return { state: 'waiting', stage: 3, title: '识别完成，等待收藏', message: '核对下方结果后，点击加入收藏。', count: `${summary.identified - summary.collected} 枚待收藏` };
  if (summary.phase === 'complete') return { state: 'success', stage: 4, title: '收藏完成', message: '', count: `${summary.collected} 枚已收藏` };
  if (summary.phase === 'waiting') return { state: 'waiting', stage: 1, title: '照片已保存，等待整理', message: '点“重新整理”继续。' };
  return { state: 'waiting', stage: summary.missing ? 1 : 2, title: summary.missing ? '还需补图' : '整理完成，请确认资料', message: summary.missing ? '在缺图的位置补上正面或反面。' : '', count: summary.missing ? `${summary.missing} 枚待补图` : '' };
}

function renderActivity(state, summary) {
  const activity = addActivity(state), working = activity.state === 'working';
  const reviewCount = (state.task?.items || []).filter((item) => addIdentified(item) && !addCollected(item)).length;
  const needsReviewCount = (state.task?.items || []).filter((item) => addIdentified(item) && !addCollected(item) && unresolvedIssues(item)).length;
  if (activity.state === 'waiting' && reviewCount) return `<section class="add-activity-summary" aria-label="处理进度" aria-live="polite"><strong>已识别 ${summary.identified} 枚</strong><span>${reviewCount - needsReviewCount} 枚待收藏${needsReviewCount ? ` · ${needsReviewCount} 枚需核对` : ''}</span><small>${summary.uploaded} 份原件${summary.ready ? ` · ${summary.ready} 枚待识别` : ''}${summary.missing ? ` · ${summary.missing} 枚待补图` : ''}</small></section>`;
  const meter = working ? `<div class="add-meter ${activity.percent == null ? 'indeterminate' : ''}" role="progressbar" aria-label="${e(activity.title)}" ${activity.percent == null ? '' : `aria-valuemin="0" aria-valuemax="100" aria-valuenow="${activity.percent}"`} aria-valuetext="${e(activity.count || activity.message || activity.title)}"><span ${activity.percent == null ? '' : `style="width:${activity.percent}%"`}></span></div>` : '';
  const stages = ['上传', '整理', '识别', '收藏'].map((label, index) => `<li class="${index < activity.stage ? 'is-done' : index === activity.stage ? 'is-current' : 'is-next'}" ${index === activity.stage ? 'aria-current="step"' : ''}><span aria-hidden="true">${index < activity.stage ? '✓' : index + 1}</span><span>${label}</span></li>`).join('');
  return `<section class="add-work-summary add-activity" data-state="${activity.state}" aria-label="处理进度" aria-live="polite"><div class="add-activity-head"><span class="add-activity-icon" aria-hidden="true">${working ? '·' : activity.state === 'error' ? '!' : activity.state === 'success' ? '✓' : '→'}</span><div><h2>${e(activity.title)}</h2>${activity.message ? `<p>${e(activity.message)}</p>` : ''}</div>${activity.count ? `<strong class="add-activity-count">${e(activity.count)}</strong>` : ''}</div>${meter}<ol class="add-stage-list">${stages}</ol>${activity.detail ? `<p class="add-activity-detail">${e(activity.detail)}</p>` : ''}${summary.coins ? `<dl class="add-work-counts"><div><dt>可识别</dt><dd>${summary.ready}</dd></div><div><dt>待补图</dt><dd>${summary.missing}</dd></div>${summary.identified > summary.collected ? `<div><dt>待收藏</dt><dd>${summary.identified - summary.collected}</dd></div>` : ''}${summary.collected ? `<div><dt>已收藏</dt><dd>${summary.collected}</dd></div>` : ''}</dl>` : ''}</section>`;
}

function renderIntake(enabled, compact) {
  return `<section class="add-intake dropzone ${compact ? 'add-intake-compact' : ''}" data-add-drop aria-label="${compact ? '继续添加' : '添加资料'}">${compact ? '' : '<div class="add-intake-icon">＋</div>'}<h2>${compact ? '继续添加' : '上传钱币照片'}</h2>${compact ? '' : '<p>支持多选照片或表格，自动匹配正反面。</p>'}<input id="add-files" data-add-files type="file" multiple accept="image/jpeg,image/png,image/webp,image/gif,image/avif,.heic,.heif,.csv,.xlsx,.pdf,.txt" hidden ${enabled ? '' : 'disabled'}>${control('选择照片或表格', 'choose', !enabled, compact ? 'quiet small' : 'primary')}<small>可多选或拖入 · 每个文件不超过 20 MiB</small>${compact ? '' : '<details class="add-upload-info"><summary>照片如何处理</summary><p>使用当前 Codex 额度整理照片。上传到 HeriBase 识别前会再确认。</p></details>'}</section>`;
}
function sourceGallery(state) {
  const sources = originalSources(state);
  return `<div class="add-inputs">${sources.slice(0, 12).map((source, index) => `<figure>${source.mime_type?.startsWith('image/') ? `<button class="add-input-image" data-action="zoom" data-url="${e(media(state.taskKey, source.source_id))}" aria-label="查看上传图 ${index + 1}"><img src="${e(media(state.taskKey, source.source_id))}" alt="上传图 ${index + 1}"></button>` : '<div class="add-input-document">资料</div>'}<figcaption>${e(source.origin?.original_name || `上传资料 ${index + 1}`)}</figcaption></figure>`).join('')}</div>${sources.length > 12 ? `<p class="muted">另有 ${sources.length - 12} 份原件已保存。</p>` : ''}`;
}
function photoDisplayName(state, source) {
  const original = source.origin?.original_name || '';
  const basename = original.replace(/\.[^.]+$/, '');
  const technical = /(?:^|[-_])(?:[a-f0-9]{24,}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})(?:$|[-_])/i.test(basename)
    || /^(?:source|image|img|photo|crop|asset)[-_][a-z0-9_-]{32,}$/i.test(basename);
  const index = (state.task?.sources || []).filter((value) => value.mime_type?.startsWith('image/')).findIndex((value) => value.source_id === source.source_id) + 1;
  return !original || technical ? `照片 ${Math.max(index, 1)}` : original;
}
function renderPhotoEditor(state, item, title) {
  const draft = state.photoEditor;
  const problem = photoDraftProblem(state);
  const disabled = state.busy || draft.stale || draft.baseRevision !== state.task?.manifest.revision || !editablePhotos(item);
  const sources = availablePhotoSources(state, item.local_id);
  const sourceMap = new Map((state.task?.sources || []).map((source) => [source.source_id, source]));
  const slots = SIDES.map((side) => {
    const label = side === 'obverse' ? '正面' : '反面';
    const source = sourceMap.get(draft.slots[side]);
    const url = source ? media(state.taskKey, source.source_id) : null;
    return `<section class="add-editor-slot"><div class="add-editor-slot-head"><h4>${label}</h4>${source ? `<button class="text-button" data-action="zoom" data-url="${e(url)}">放大</button>` : '<small>待补图</small>'}</div>${source ? `<button type="button" class="add-editor-photo" data-action="add-photo-side" data-side="${side}" aria-label="更换${label}照片" ${disabled ? 'disabled' : ''}><img src="${e(url)}" alt="我的钱币 · ${label}"><span>从本批照片替换</span></button><p class="add-editor-filename" title="${e(source.origin?.original_name || '')}">${e(photoDisplayName(state, source))}</p>` : `<div class="add-editor-photo add-editor-empty"><button type="button" data-action="add-photo" data-id="${e(item.local_id)}" data-side="${side}" aria-label="补${label}" ${disabled ? 'disabled' : ''}><span aria-hidden="true">＋</span><strong>补${label}</strong></button><button type="button" class="text-button" data-action="add-photo-side" data-side="${side}" ${disabled ? 'disabled' : ''}>从本批照片选择</button><input type="file" data-add-supplement="${side}" data-id="${e(item.local_id)}" accept="image/jpeg,image/png,image/webp,image/gif,image/avif,.heic,.heif" hidden ${disabled ? 'disabled' : ''}></div>`}</section>`;
  }).join('');
  const side = draft.pickerSide;
  const other = sourceMap.get(draft.slots[side === 'obverse' ? 'reverse' : 'obverse']);
  const picker = SIDES.includes(side) ? `<section class="add-editor-picker" aria-label="选择${side === 'obverse' ? '正面' : '反面'}照片"><div class="add-editor-picker-head"><h4>选择${side === 'obverse' ? '正面' : '反面'}照片</h4><small>本批可用图片 · ${sources.length} 张</small></div><div class="add-editor-options">${sources.map((source) => {
    const selected = draft.slots[side] === source.source_id;
    const duplicate = other && (source.source_id === other.source_id || (source.sha256 && source.sha256 === other.sha256));
    return `<button type="button" class="add-editor-option ${selected ? 'selected' : ''}" data-action="add-photo-select" data-source="${e(source.source_id)}" title="${e(source.origin?.original_name || '')}" aria-pressed="${selected}" ${disabled || duplicate ? 'disabled' : ''}><img src="${e(media(state.taskKey, source.source_id))}" alt="${e(photoDisplayName(state, source))}"><span>${e(photoDisplayName(state, source))}</span><small>${duplicate ? `已用于${side === 'obverse' ? '反面' : '正面'}` : selected ? '当前选择' : '选择此图'}</small></button>`;
  }).join('') || '<p class="muted">暂无其他可用照片，可在缺失位置补图。</p>'}</div><p class="muted">已确认的其他钱币、已有识别或收藏记录的图片不会出现在可选列表。</p></section>` : '';
  const feedback = state.photoFeedback?.[item.local_id];
  return `<section class="add-photo-editor" aria-label="调整${e(title)}照片"><div class="add-editor-intro"><h4>调整正反面照片</h4><p>点照片可从本批图片替换；缺少的一面可直接补图。</p></div>${draft.stale ? '<div class="note add-editor-stale" role="alert"><strong>照片或记录已更新</strong><p>当前选择仍保留。刷新后需按最新记录重新选择。</p><button class="button quiet small" data-action="add-photo-refresh">刷新并重新选择</button></div>' : ''}${draft.error ? `<p class="add-editor-error" role="alert">${e(draft.error)}</p>` : ''}<div class="add-editor-slots">${slots}</div><div class="add-editor-tools"><button class="button quiet small" data-action="add-photo-swap" ${disabled ? 'disabled' : ''}>交换正反面</button></div>${picker}${feedback ? `<p class="add-editor-feedback" role="${feedback.status === 'error' ? 'alert' : 'status'}">${e(feedback.message)}</p>` : ''}<div class="add-editor-save"><p class="${problem ? 'add-editor-hint' : 'muted'}" ${problem ? 'role="status"' : ''}>${e(problem || '确认这两张照片属于同一枚钱币，保存后即可继续识别。')}</p><div class="actions"><button class="button primary" data-action="add-photo-save" ${disabled || problem ? 'disabled' : ''}>保存并继续</button><button class="button quiet" data-action="add-photo-cancel" ${state.busy ? 'disabled' : ''}>取消</button></div></div></section>`;
}
function organizedCard(state, item, index) {
  const title = item.recognitionResult?.title || item.resolved_fields?.name?.value || `钱币 ${index + 1}`;
  if (state.photoEditor?.localId === item.local_id) return `<article class="add-coin-card is-editing" data-coin-id="${e(item.local_id)}"><div class="add-card-head"><h3>${e(title)}</h3><span class="tag amber">调整照片</span></div>${renderPhotoEditor(state, item, title)}</article>`;
  const assignment = item.organization?.source_assignment?.length ? item.organization.source_assignment : (item.evidence || []).filter((entry) => entry.is_primary);
  const support = isSupportMaterial(item), missing = needsPhoto(item), side = missingSide(item);
  const ready = eligibleForIdentification(item) && !addIdentified(item);
  const enabled = !state.busy && !hasPendingAdd(state) && !organizing(state) && !item.active_identification && !item.collection_projection;
  const badge = support ? '其他图片' : side ? `缺${side === 'obverse' ? '正面' : '反面'}` : missing ? '待补图' : addCollected(item) ? '已收藏' : addIdentified(item) ? (unresolvedIssues(item) ? '需核对差异' : '待收藏') : ready ? '正反面齐全' : '待确认';
  const unknown = assignment.filter((entry) => !SIDES.includes(entry.role) && state.task?.sources.some((source) => source.source_id === entry.source_id && source.mime_type?.startsWith('image/')));
  let unknownIndex = 0;
  const previews = support ? assignment.slice(0, 1).map((entry) => ({ ...entry, label: '上传图片' })) : SIDES.map((role) => {
    const explicit = assignment.find((entry) => entry.role === role);
    if (explicit) return { source_id: explicit.source_id, role, label: role === 'obverse' ? '正面' : '反面' };
    const unassigned = unknown[unknownIndex++];
    return unassigned ? { source_id: unassigned.source_id, role: 'unknown', label: '待确认方向' } : { role, label: role === 'obverse' ? '正面' : '反面' };
  });
  const images = previews.map((entry) => {
    if (entry.source_id) return state.task?.sources.find((source) => source.source_id === entry.source_id)?.mime_type?.startsWith('image/')
      ? `<button class="add-card-photo" data-action="zoom" data-url="${e(media(state.taskKey, entry.source_id))}" aria-label="查看${e(title)} · ${e(entry.label)}"><img src="${e(media(state.taskKey, entry.source_id))}" alt="${e(entry.label)}"><span>${e(entry.label)}</span></button>`
      : '<div class="add-card-photo add-card-missing"><span>资料原件</span></div>';
    if (side === entry.role) return `<div class="add-card-photo add-card-missing add-photo-upload"><button type="button" data-action="add-photo" data-id="${e(item.local_id)}" data-side="${side}" aria-label="${e(title)}：补${entry.label}" ${enabled ? '' : 'disabled'}><span aria-hidden="true">＋</span><strong>补${entry.label}</strong></button><input type="file" data-add-supplement="${side}" data-id="${e(item.local_id)}" accept="image/jpeg,image/png,image/webp,image/gif,image/avif,.heic,.heif" hidden ${enabled ? '' : 'disabled'}></div>`;
    return `<div class="add-card-photo add-card-missing"><span>缺少${e(entry.label)}</span></div>`;
  }).join('');
  const reason = item.organization?.pairing_state === 'confirmed' ? '已按你选择的正反面保存。' : item.field_claims?.visual_analysis?.summary || item.organization?.pairing_rationale;
  const feedback = !addIdentified(item) && !addCollected(item) && state.photoFeedback?.[item.local_id];
  const feedbackHtml = feedback ? `<div class="add-photo-feedback ${e(feedback.status)}" role="${feedback.status === 'error' ? 'alert' : 'status'}"><p>${e(feedback.message)}</p>${feedback.status === 'success' && ready ? '<button class="button quiet small" data-action="add-next-step">去识别</button>' : ''}</div>` : '';
  const kind = ready ? 'identify' : collectionItems(state).some((value) => value.local_id === item.local_id) ? 'collect' : null;
  const selection = kind ? `<label class="add-card-select"><input type="checkbox" data-add-select="${kind}" data-id="${e(item.local_id)}" ${selectedItems(state, kind).some((value) => value.local_id === item.local_id) ? 'checked' : ''} ${state.busy || state.photoEditor || hasPendingAdd(state) ? 'disabled' : ''}>${kind === 'identify' ? '识别这枚' : '加入收藏'}</label>` : '';
  const recognized = addIdentified(item);
  const result = recognized ? `<div class="add-card-result">${reviewNotice(state, item)}${resultBody(item)}</div>` : '';
  return `<article class="add-coin-card${recognized ? ' is-recognized' : ''}" data-coin-id="${e(item.local_id)}"><div class="add-card-top">${selection}<div class="add-card-head"><h3>${e(title)}</h3><span class="tag ${ready || addCollected(item) ? 'green' : 'amber'}">${e(badge)}</span></div></div><div class="add-card-images ${support ? 'support-image' : ''}"${recognized ? ' aria-label="我的钱币照片"' : ''}>${images}</div><div class="add-card-body">${feedbackHtml}${result}${reason && !recognized ? `<details class="add-pair-reason"><summary>${support ? '图片说明' : '配对依据'}</summary><p>${e(reason)}</p></details>` : ''}${editablePhotos(item) ? `<div class="add-card-photo-actions">${canConfirmPhotoPair(state, item) ? `<button class="button primary small" data-action="add-photo-confirm" data-id="${e(item.local_id)}" ${enabled && !state.photoEditor ? '' : 'disabled'}>确认这组照片</button>` : ''}<button class="button ${!ready && !canConfirmPhotoPair(state, item) ? 'primary' : 'quiet'} small" data-action="add-photos" data-id="${e(item.local_id)}" ${enabled && !state.photoEditor ? '' : 'disabled'}>${!ready && !canConfirmPhotoPair(state, item) ? '选择正反面' : '调整照片'}</button></div>` : ''}</div></article>`;
}

export function renderAdd(state) {
  const items = visibleItems(state), item = items.length === 1 ? addItem(state) : null;
  const identified = addIdentified(item), done = addCollected(item);
  const blocked = hasPendingAdd(state), enabled = !state.photoEditor && !state.busy && !blocked && !state.missing;
  const isOrganizing = organizing(state), summary = addWorkSummary(state), hasInputs = summary.uploaded > 0 || Boolean(state.uploadProgress);
  const needsOrganization = Boolean(hasInputs && (!items.length || summary.unorganized || state.pendingSourceIds?.length));
  const progress = hasInputs ? renderActivity(state, summary) : '';
  const readyItems = identificationItems(state), reviewItems = items.filter((entry) => addIdentified(entry) && !addCollected(entry));
  const identifyScope = selectedItems(state, 'identify'), collectScope = selectedItems(state, 'collect');
  const canAct = enabled && !isOrganizing && !needsOrganization;
  const lastIdentify = state.intents.identify?.operation?.data;
  const eligibility = state.plan ? state.plan.eligibility : lastIdentify?.eligibility;
  const quotaIssue = identificationQuotaIssue(eligibility, identifyScope.length);
  const identifyAction = state.plan && !quotaIssue
    ? control(`识别这 ${identifyScope.length} 枚`, 'identify', !canAct || !identifyScope.length || state.persistenceError)
    : control(state.busy ? '正在检查…' : quotaIssue ? '重新检查额度' : '重新检查连接', 'preview', !canAct || !identifyScope.length);
  const collectAction = control(`加入收藏（${collectScope.length}）`, 'collect', !canAct || !collectScope.length || state.persistenceError);
  const groups = [
    ['识别结果', reviewItems, 'review'], ['待识别', readyItems, 'identify'],
    ['待确认', items.filter((entry) => !isSupportMaterial(entry) && !eligibleForIdentification(entry) && !needsPhoto(entry) && !addIdentified(entry) && !addCollected(entry)), 'pending'],
    ['待补图', items.filter((entry) => needsPhoto(entry) && !addIdentified(entry) && !addCollected(entry)), 'missing'],
    ['其他资料', items.filter(isSupportMaterial), 'support'],
  ];
  const group = items.length ? `<section class="add-organized">${groups.filter(([, entries]) => entries.length).map(([label, entries, key]) => {
    const cards = `<div class="add-cards">${entries.map((entry, index) => organizedCard(state, entry, index)).join('')}</div>`;
    const collapsed = key === 'support' || (reviewItems.length && ['pending', 'missing'].includes(key));
    if (collapsed) {
      const open = state.groupOpen?.[key] || entries.some((entry) => state.photoEditor?.localId === entry.local_id);
      return `<details class="add-result-group add-later" data-add-group="${key}" ${open ? 'open' : ''}><summary>${label} <span>${entries.length}</span></summary>${cards}</details>`;
    }
    if (key === 'review') return `<section class="add-result-group add-review-group"><div class="add-group-head"><h3>${label} <span>${entries.length}</span></h3>${collectAction}</div>${cards}<p class="add-review-caption">核对币种、年份和面额后加入收藏 · 图片识别不代表鉴真。</p></section>`;
    if (key === 'identify') return `<section class="add-result-group add-identify-group"><div class="add-group-head"><h3>${label} <span>${entries.length}</span></h3>${identifyAction}</div><div class="add-next add-group-note" aria-label="下一步">${state.plan ? identificationNotice(state.plan) : identificationQuotaNotice(eligibility, lastIdentify?.account?.apiBaseUrl, identifyScope.length)}</div>${cards}</section>`;
    return `<section class="add-result-group"><h3>${label} <span>${entries.length}</span></h3>${cards}</section>`;
  }).join('')}</section>` : '';
  const advanced = state.taskKey ? `<details class="add-advanced"><summary>更多</summary><div class="actions"><a class="button quiet small" href="${e(route('review', state.taskKey, item?.local_id))}">详细核对</a><a class="button quiet small" href="${e(route('operations', state.taskKey))}">执行记录</a><a class="button quiet small" href="${e(route('inputs', state.taskKey))}">原始资料</a></div>${state.diagnostic ? `<details><summary>错误详情</summary><p>${e(state.diagnostic.code)}</p><p>${e(state.diagnostic.message)}</p></details>` : ''}</details>` : '';
  const noMatch = state.intents.identify?.operation?.data?.itemResults?.some((result) => result.status === 'recognition_failed');
  const failed = ['identify', 'collect'].map((kind) => state.intents[kind]).find((intent) => ['failed', 'blocked'].includes(intent?.status) && !intent.operation?.data?.eligibility);
  const mainContent = `${progress}${hasInputs && !state.photoEditor && !isOrganizing && !blocked && ['waiting', 'failed'].includes(summary.phase) ? `<div class="add-organization-retry">${control('重新整理', 'organize', state.busy, 'quiet small')}</div>` : ''}${needsOrganization && !items.length && !state.uploadProgress ? `<section class="add-saved"><h2>已保存 ${summary.uploaded} 份资料</h2>${sourceGallery(state)}</section>` : ''}${group}${noMatch && !identified && !blocked ? '<div class="note"><strong>这次未识别出具体币种</strong><p>请换一张更清晰的照片。</p></div>' : ''}${failed && !blocked && !done ? `<div class="note"><strong>上次操作未完成</strong><p>${e(failed.operation?.data?.message || '请稍后重试。')}</p></div>` : ''}`;
  return `<div class="add-page"><div class="page-head"><h1>添加钱币</h1><a class="button quiet" href="#library">我的收藏 →</a></div>${state.error ? `<div class="note add-error" role="alert">${e(state.error)}</div>` : ''}${state.persistenceError ? '<div class="note" role="alert">浏览器无法保存进度，请允许本地存储后刷新。</div>' : ''}${state.missing ? '<div class="note" role="alert">暂未读到记录，请刷新。</div>' : ''}${hasInputs ? `<div class="add-work-layout"><div class="add-work-main" aria-label="处理结果">${mainContent}</div><aside class="add-work-aside" aria-label="补充与原件">${renderIntake(enabled, true)}${state.uploadRemainder?.length && !state.busy ? `<div class="note" role="alert">还有 ${state.uploadRemainder.length} 份资料尚未确认保存：${state.uploadRemainder.map(e).join('、')}</div>` : ''}<details class="add-originals"><summary>上传原件（${summary.uploaded}）</summary>${sourceGallery(state)}</details>${control('刷新进度', 'refresh', state.busy, 'quiet small')}</aside></div>` : renderIntake(enabled, false)}${advanced}</div>`;
}
