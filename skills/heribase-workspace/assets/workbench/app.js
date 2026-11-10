import { createAddController, renderAdd, friendlyAddError, editablePhotos, hasPendingAdd, identificationQuotaNotice } from './add.js';
import { reviewImages, reviewDecision, reviewLabels, reviewBatch } from './review.js';
import * as api from './api.js';
import {
  continuationRequest,
  commandStatus,
  hostDisplayTitle,
  hostOptionLabel,
  INBOX_PROMPT,
  copyInboxPrompt,
  bridgeActionLabels,
  bridgeDeliveryHint,
  continuationSummary,
} from './bridge.js';
import { commercePages, createCommerceController } from './commerce.js';
import {
  render,
  esc,
  href,
  link,
  button,
  tag,
  titles,
  currentItem,
  itemSources,
  name,
  records,
  collected,
  remoteFields,
  bulkControls,
  queue,
  identifyRows,
  hasNoAppraisalCredits,
  appraisalPurchaseControl,
} from './views.js';

import { selectionFor, filteredItems, eligibleForIdentification, identificationSelection } from './bulk.js';

const main = document.querySelector('#main'),
  modal = document.querySelector('#dialog'),
  bridge = document.querySelector('#bridge-dialog');
const model = {
  workspace: { tasks: [], hosts: [], commands: [], notes: [], operations: [], queryLogs: [], appraisals: [], purchases: [], trackingPurchases: [], tracking: [], collectionIndex: [] },
  allTasks: [],
  task: null,
  route: { page: 'add' },
  events: [],
  files: [],
  // 首次进入藏品库时默认展示已收藏；用户点击标签后仍沿用当前选择。
  filter: 'collected',
  libraryView: 'grid',
  query: '',
  cursor: 0,
  appraisalServices: null,
};
let pairDirty = false;
let dirty = false,
  deferredRefresh = false,
  busy = false,
  refreshing = null;
let draftTimer = null,
  draftTick = 0,
  savingDraft = null;
let appraisalServicesLoading = false;
let appraisalCreditRequest = 0;
let accountProfileRequest = null;
let addMarkup = null;
let addPhotoRoute = null;
const commerce = createCommerceController({
  request: api.request,
  dialog,
  redraw: draw,
  toast,
  setDirty: (value) => {
    dirty = value;
  },
});
// 支付页在外部标签打开；用户返回工作台可见时立即查一次原订单，不依赖定时轮询。
window.addEventListener('focus', () => {
  void commerce.checkPaymentReturn();
  void refreshAccountProfile();
});
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') void commerce.checkPaymentReturn();
});
const add = createAddController({
  request: api.request,
  storage: (() => { try { return window.localStorage; } catch { return null; } })(),
  changed: () => { if (route().page === 'add') draw(); },
  taskChanged: (key) => { if (route().page === 'add') history.replaceState(null, '', href('add', key)); },
  collectionFinished: (notice) => {
    // Render the confirmed projection immediately, even before the next poll.
    model.allTasks = [notice.task, ...model.allTasks.filter((task) => task.manifest.task_key !== notice.taskKey)];
    model.collectionNotice = notice;
    model.filter = 'collected';
    model.query = '';
    if (route().page === 'add') location.hash = 'library';
  },
});
const primaryNav = [
  ['add', '＋', '添加钱币'],
  ['library', '◈', '我的收藏'],
];
const advancedNav = [
  ['home', '⌂', '空间总览'],
  ['tasks', '▤', '整理记录'],
  ['appraisals', '◎', '真人鉴定'],
  ['tracking', '⌁', '价格追踪'],
  ['market', '◉', '交易市场'],
  ['membership', '◇', '会员订阅'],
  ['reports', '▧', '资料与报告'],
  ['operations', '↗', '执行记录'],
  ['settings', '⊙', '设置与备份'],
];
const navLinks = (entries) => entries.map(([id, icon, title]) => `<a class="nav-item" data-nav="${id}" href="#${id}"><span class="nav-icon">${icon}</span>${title}</a>`).join('');
document.querySelector('#navigation').innerHTML = navLinks(primaryNav)
  + `<details class="nav-more" id="advanced-navigation"><summary>更多</summary>${navLinks(advancedNav)}<button class="nav-item" data-action="bridge"><span class="nav-icon">⌘</span><span id="host-status">与聊天协作</span></button></details>`;
document.querySelector('#mobile-navigation').innerHTML = '<a href="#add">＋ 添加钱币</a><a href="#library">我的收藏</a>'
  + `<details><summary>更多</summary><div>${navLinks(advancedNav)}<button class="button quiet small" data-action="bridge">与聊天协作</button></div></details>`;

function route() {
  const [page, query = ''] = location.hash.slice(1).split('?');
  const params = new URLSearchParams(query);
  // Saved links open the same intake; photo correction no longer has a separate workflow.
  if (page === 'import' || page === 'pairing') {
    history.replaceState(null, '', href('add', params.get('task'), params.get('item')));
    return { page: 'add', task: params.get('task'), item: params.get('item') };
  }
  return { page: titles[page] ? page : 'add', task: params.get('task'), item: params.get('item') };
}
function toast(message) {
  const el = document.querySelector('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove('show'), 4200);
}
function scrollAddStatus() {
  if (!document.querySelector('.add-activity')) return;
  window.scrollTo({
    top: 0,
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
  });
}
function dialog(title, body, actions = '') {
  modal.classList.remove('rr-zoom-dialog');
  modal.innerHTML = `<div class="dialog-head"><h2 id="dialog-title">${esc(title)}</h2><button class="close" data-action="close" aria-label="关闭">×</button></div><div class="dialog-body">${body}</div><div class="dialog-foot">${button('返回', 'close', 'quiet')}${actions}</div>`;
  if (!modal.open) modal.showModal();
}
function apiCheckDialog(result) {
  const host = result.host || {};
  const apiResult = result.api || {};
  const stage = (name, value) => {
    if (!value) return '';
    const detail = [
      value.durationMs === undefined ? '' : `${value.durationMs} ms`,
      value.addresses?.length ? value.addresses.join(', ') : '',
      value.address ? `地址 ${value.address}` : '',
      value.error || '',
    ].filter(Boolean).join(' · ');
    return `<li><span>${esc(name)}</span><span>${value.ok ? '正常' : '失败'}${detail ? ` · ${esc(detail)}` : ''}</span></li>`;
  };
  const apiError = apiResult.error || {};
  const diagnostic = apiError.diagnostic || {};
  const apiDetails = [
    apiError.code ? `错误码 ${apiError.code}` : '',
    apiError.httpStatus ? `HTTP ${apiError.httpStatus}` : '',
    apiError.apiCode ? `API ${apiError.apiCode}` : '',
    apiError.traceId ? `Trace ID ${apiError.traceId}` : '',
    diagnostic.phase ? `阶段 ${diagnostic.phase}` : '',
    diagnostic.code ? `传输码 ${diagnostic.code}` : '',
    diagnostic.durationMs === undefined ? '' : `耗时 ${diagnostic.durationMs} ms`,
  ].filter(Boolean).join(' · ');
  const ok = host.dns?.ok === true && host.tcp?.ok === true && (host.tls === undefined || host.tls.ok === true) && apiResult.ok === true;
  const apiMessage = apiResult.ok ? `API 请求正常${apiResult.status ? `（${esc(apiResult.status)}）` : ''}` : esc(apiError.message || 'API 请求失败');
  dialog(
    'API 网络检查',
    `<p>${ok ? '连接正常' : '检测到连接异常'}：${esc(host.host || '未知主机')}${host.port ? `:${esc(host.port)}` : ''}</p><ul class="dialog-list">${stage('DNS 解析', host.dns)}${stage('TCP 连接', host.tcp)}${stage('TLS 握手', host.tls)}<li><span>只读 API 请求</span><span>${apiMessage}</span></li></ul>${apiDetails ? `<p class="muted">${esc(apiDetails)}</p>` : ''}`,
  );
}
async function dialogAction(target, work) {
  if (busy) return;
  busy = true;
  target.disabled = true;
  try {
    await work();
  } catch (error) {
    showError(error);
  } finally {
    busy = false;
    if (target.isConnected) target.disabled = false;
  }
}
function showError(error) {
  if (error.name === 'AbortError') return;
  if (error.status === 409 && error.detail?.current) {
    model.conflict = error.detail.current;
    model.conflictDraft = document.querySelector('#edit-note-text')?.value;
    dialog(
      '记录已在其他位置更新',
      `<p>当前输入已保留。请对照最新内容，再决定是否修改。</p><pre class="conflict-data">${esc(JSON.stringify(error.detail.current.data, null, 2))}</pre>${model.conflictDraft !== undefined ? `<label>当前输入<textarea id="conflict-note-text">${esc(model.conflictDraft)}</textarea></label>` : ''}`,
      button('对照完成，继续编辑当前输入', 'accept-latest', 'primary'),
    );
    return;
  }

  // 操作通常从确认弹窗中发起；把错误直接写入同一个原生 dialog，
  // 避免短暂 toast 被当前弹窗的 backdrop 遮住或在用户读完前消失。
  const code = error.code || error.detail?.code;
  const isCliFailure = typeof code === 'string' && code.startsWith('cli_');
  const actions = isCliFailure
    ? link('查看执行记录', 'operations', model.route.task, null, 'button primary')
    : '';
  dialog(
    '操作未完成',
    `<p>${esc(error.message || '工作台未能完成这次操作。')}</p>${code ? `<p class="muted" style="margin-top:12px">错误代码：${esc(code)}</p>` : ''}`
      + (isCliFailure ? '<p class="muted" style="margin-top:12px">执行记录中保留了 CLI 返回详情和已完成项目，可先核对再决定下一步。</p>' : ''),
    actions,
  );
}
function draw() {
  model.route = route();
  if (model.route.page !== 'add') addPhotoRoute = null;
  model.task = model.allTasks.find((t) => t.manifest.task_key === model.route.task) || (!model.route.task ? model.allTasks[0] : null);
  if (model.route.page === 'add') {
    commerce.deactivate();
    add.sync(model.route.task, model.allTasks, model.workspace.operations || []);
    const markup = renderAdd(add.state);
    // Unchanged polling must not restart the working animation or close details.
    if (addMarkup !== markup) main.innerHTML = markup;
    addMarkup = markup;
    // Read-only scope is ready before the single Start identification confirmation.
    queueMicrotask(() => {
      const current = route();
      if (current.page !== 'add') return;
      const photoRoute = current.task && current.item ? `${current.task}:${current.item}` : null;
      if (photoRoute && photoRoute !== addPhotoRoute && add.state.task?.manifest.task_key === current.task) {
        const item = add.state.task.items.find((entry) => entry.local_id === current.item);
        // A read-only preflight started on the previous view may still be finishing.
        // Keep this deep link pending until the editor can open instead of consuming it.
        if (editablePhotos(item) && (add.state.busy || hasPendingAdd(add.state)
          || ['queued', 'running'].includes(add.state.task.organization?.status))) return;
        addPhotoRoute = photoRoute;
        if (editablePhotos(item)) {
          try {
            add.openPhotos(current.item);
            document.querySelector('.add-coin-card.is-editing')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } catch (error) {
            add.state.error = friendlyAddError(error);
            draw();
          }
        } else {
          const card = [...document.querySelectorAll('[data-coin-id]')].find((entry) => entry.dataset.coinId === current.item);
          const group = card?.closest('details');
          if (group) group.open = true;
          card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
      if (!photoRoute) addPhotoRoute = null;
      if (add.needsPlan) void add.preview().catch(() => {});
    });
  } else if (commercePages.has(model.route.page)) {
    addMarkup = null;
    void commerce.load(model.route);
    main.innerHTML = commerce.render(model.route);
  } else {
    addMarkup = null;
    commerce.deactivate();
    main.innerHTML = render(model);
    if (model.route.page === 'library' && model.collectionNotice && !model.collectionNotice.animated) {
      model.collectionNotice.animated = true;
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        main.querySelector('[data-collection-notice]')?.animate(
          [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'translateY(0)' }],
          { duration: 280, easing: 'ease-out' },
        );
      }
    }
  }
  document.title = `${titles[model.route.page]} · HeriBase 工作空间`;
  const group = ['task', 'inputs', 'pairing', 'identify', 'review', 'confirm'].includes(model.route.page)
    ? 'tasks'
    : model.route.page === 'coin'
      ? 'library'
      : ['appraisal', 'report'].includes(model.route.page)
        ? 'appraisals'
        : model.route.page;
  document.querySelectorAll('[data-nav]').forEach((el) => el.setAttribute('aria-current', el.dataset.nav === group ? 'page' : 'false'));
  document.querySelector('#host-status').textContent = '与聊天协作';
  const advanced = document.querySelector('#advanced-navigation');
  if (!['add', 'import', 'library', 'coin'].includes(model.route.page)) advanced.open = true;
  document.querySelector('#workspace-status').textContent = '资料保存在本机';
  if (model.route.task && !model.task && !['operations', 'add'].includes(model.route.page)) {
    const t = model.workspace.tasks.find((t) => t.task_key === model.route.task);
    if (t) {
      const errors = t.health?.errors?.length ? t.health.errors : ['任务完整性检查失败'];
      main.innerHTML = `<div class="breadcrumb">${link('整理任务', 'tasks')} / ${esc(t.display_name)}</div><div class="eyebrow">TASK MANAGEMENT</div><h1 style="margin:12px 0 8px">任务管理</h1><p class="muted">资料完整性尚未通过，因此暂时不能打开配对、识别或审核页面；执行记录、核验原因和协作请求仍可查看。</p><article class="operation-card warning"><div class="inline" style="justify-content:space-between"><h3>数据待核验</h3>${tag('需要处理', 'amber')}</div><p>${esc(errors.join('；'))}</p><details open><summary>完整性检查原因</summary><ul class="dialog-list">${errors.map((error) => `<li>${esc(error)}</li>`).join('')}</ul></details><div class="actions"><button class="button primary" data-action="task-health-refresh">重新检查</button>${link('查看本任务执行记录', 'operations', t.task_key, null, 'button quiet')}${button('与 Agent 协作', 'bridge', 'quiet')}</div></article>`;
    } else {
      main.innerHTML = `<div class="empty-state"><h1>未找到该任务</h1><p>请从整理任务选择当前可用的记录。</p>${link('查看整理任务', 'tasks')}</div>`;
    }
  }
  if (model.route.page === 'appraisal' && !model.appraisalServices && !appraisalServicesLoading) void loadAppraisalServices().catch(showError);
}

async function loadAppraisalServices(force = false) {
  if (appraisalServicesLoading || (!force && model.appraisalServices)) return model.appraisalServices;
  appraisalServicesLoading = true;
  try {
    model.appraisalServices = await api.request('/api/business/appraisals-services', {});
    if (route().page === 'appraisal' && !dirty) {
      draw();
      void refreshAppraisalCredits();
    }
    return model.appraisalServices;
  } catch (error) {
    // 保持页面可见并给用户一个明确的重新读取入口，而不是退回到内部默认 ID。
    model.appraisalServices = { experts: [], error: error.message || '鉴定服务目录读取失败' };
    if (route().page === 'appraisal' && !dirty) draw();
    throw error;
  } finally {
    appraisalServicesLoading = false;
  }
}

function selectedAppraisalService() {
  const choice = document.querySelector('#appraiser-choice')?.value || '';
  const [rawType, rawId] = choice.split(':');
  if (!choice.includes(':') || !Number.isInteger(Number(rawType)) || !Number.isInteger(Number(rawId))) return null;
  return { appraiserType: Number(rawType), appraiserId: Number(rawId) };
}

function creditStatusText(services) {
  const expert = services?.selected;
  const remaining = services?.credits?.remainingTimes;
  const details = [expert?.duration, expert?.experience ? `已完成 ${expert.experience} 鉴定` : null].filter(Boolean);
  if (typeof remaining === 'number' && remaining > 0) return [...details, `当前可用 ${remaining} 次`].join(' · ');
  if (hasNoAppraisalCredits(remaining)) return [...details, '当前无可用次数。'].join(' · ');
  return [...details, '暂未返回可用次数，请刷新后重试。'].join(' · ');
}

async function refreshAppraisalCredits({ notify = false } = {}) {
  const selected = selectedAppraisalService();
  if (!selected) return null;
  const request = ++appraisalCreditRequest;
  const origin = JSON.stringify(route());
  const services = await api.request('/api/business/appraisals-services', selected);
  // 切换服务或藏品后，旧请求即使较晚完成，也不能覆盖新选择的余额／购买入口。
  // 不全页重绘，以保留用户未保存的图片选择和描述。
  const current = selectedAppraisalService();
  if (
    request !== appraisalCreditRequest ||
    origin !== JSON.stringify(route()) ||
    current?.appraiserType !== selected.appraiserType ||
    current?.appraiserId !== selected.appraiserId
  )
    return null;
  model.appraisalServices = services;
  const status = document.querySelector('#appraisal-credit-status');
  if (status) status.textContent = creditStatusText(services);
  const purchaseControl = document.querySelector('#appraisal-purchase-control');
  if (purchaseControl) {
    // 选择服务后的异步次数查询不能只改文字，否则首次渲染时缺失的购买入口
    // 会一直不出现。局部替换控制区可保留用户尚未保存的鉴定材料。
    purchaseControl.innerHTML = appraisalPurchaseControl(services.selected, services.credits?.remainingTimes, model.workspace.purchases || []);
  } else if (route().page === 'appraisal' && !dirty) draw();
  if (notify) toast(hasNoAppraisalCredits(services.credits?.remainingTimes) ? '当前服务无可用次数，可购买后再次刷新' : '服务与可用次数已刷新');
  return services;
}
function drawAccountProfile(profile = {}) {
  const nickname = profile.nickname || '';
  const name = document.querySelector('#account-nickname');
  const avatar = document.querySelector('#account-avatar');
  const icon = document.querySelector('#account-avatar-icon');
  const initials = document.querySelector('#account-avatar-initials');
  const provider = profile.provider === 'google' ? 'Google 登录' : profile.provider === 'apple' ? 'Apple 登录' : '';
  name.textContent = nickname || 'HeriBase 账号';
  name.title = nickname;
  document.querySelector('#account-provider').textContent = provider
    || (profile.authenticated === false ? '未登录' : '账号资料暂不可用');

  // 图片加载失败或没有头像时保留姓名首字，姓名缺失则使用通用账号图标。
  const parts = nickname.split(/\s+/u);
  initials.textContent = nickname ? [parts[0], ...(parts.length > 1 ? [parts.at(-1)] : [])]
    .map((part) => Array.from(part)[0]).join('').toLocaleUpperCase() : '';
  icon.hidden = Boolean(nickname);
  initials.hidden = !nickname;
  const avatarUrl = profile.avatarUrl;
  if (avatar.getAttribute('src') === avatarUrl) return;
  // 请求新头像时立即隐藏上一账号的图片；只在新图片成功加载后显示。
  avatar.hidden = true;
  avatar.onload = () => { avatar.hidden = false; };
  avatar.onerror = () => { avatar.hidden = true; };
  if (avatarUrl) avatar.src = avatarUrl;
  else avatar.removeAttribute('src');
}

function refreshAccountProfile() {
  // 与工作台数据刷新解耦，不让一次网络取资料阻塞藏品、任务或轮询。
  if (accountProfileRequest === null) {
    accountProfileRequest = api.accountProfile().then(
      (profile) => drawAccountProfile(profile),
      () => drawAccountProfile(),
    ).finally(() => { accountProfileRequest = null; });
  }
  return accountProfileRequest;
}

async function refresh(force = false) {
  if ((dirty || pairDirty) && !force) {
    deferredRefresh = true;
    document.querySelector('#workspace-status').textContent = '有新变化 · 当前输入已保留，保存后更新页面';
    return;
  }
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const snapshot = await api.snapshot();
    const tasks = [];
    // 某一损坏任务不能阻断其他健康任务；服务端列表保留其异常信息。
    for (const entry of snapshot.tasks) {
      if (entry.health.ok) {
        try {
          tasks.push(await api.task(entry.task_key));
        } catch (error) {
          entry.health = { ok: false, errors: [error.message] };
        }
      }
    }
    // 请求途中也可能开始编辑。落快照前再次检查，不能让慢响应覆盖新草稿。
    if (dirty || pairDirty) {
      deferredRefresh = true;
      document.querySelector('#workspace-status').textContent = '有新变化 · 当前输入已保留，保存后更新页面';
      return;
    }
    model.workspace = snapshot;
    model.allTasks = tasks;
    model.events = snapshot.recentEvents || model.events;
    model.cursor = Math.max(model.cursor, snapshot.cursor);
    document.querySelector('#connection-status').textContent = '已连接本机服务';
    deferredRefresh = false;
    draw();
    if (bridge.open) drawBridge();
  })();
  try {
    await refreshing;
  } finally {
    refreshing = null;
  }
}
async function change(path, body, { close = true } = {}) {
  const result = await api.request(path, body);
  dirty = false;
  pairDirty = false;
  if (close && modal.open) modal.close();
  await refresh(true);
  return result;
}
function taskBody(extra = {}) {
  if (!model.task) throw new Error('先选择一项任务');
  return { taskKey: model.task.manifest.task_key, expectedRevision: model.task.manifest.revision, ...extra };
}
function go(page, task, item) {
  const next = href(page, task, item);
  if (location.hash === next) draw();
  else location.hash = next;
}

// 审核详情与决定同一次任务事务保存，避免备注成功、决定失败的半保存状态。
function reviewDraft() {
  const item = currentItem(model);
  if (model.reviewDraft?.localId !== item.local_id) model.reviewDraft = { localId: item.local_id };
  return model.reviewDraft;
}
function reviewEditor(section) {
  const item = currentItem(model),
    d = item.reviewDetails || {};
  const groups = {
    measure: [
      ['weight', '实测重量（g）'],
      ['diameter', '实测直径（mm）'],
      ['thickness', '实测厚度（mm）'],
      ['metal', '材质 / 磁性观察'],
      ['edge', '边缘 / 币轴'],
    ],
    identity: [
      ['variety', '细分版别 / 目录依据'],
      ['correction', '识别修正建议及依据'],
    ],
    condition: [['condition', '保存状态与品相观察']],
    resolution: [['resolution', '资料差异核对结论与依据']],
  };
  const fields = groups[section];
  if (!fields) return;
  model.reviewEditing = { body: taskBody({ localId: item.local_id }), fields: fields.map(([key]) => key), priorDirty: dirty };
  dialog(
    { measure: '补充实测记录', identity: '版别与识别修正', condition: '品相观察', resolution: '核对资料差异' }[section],
    `${section === 'resolution' ? `<div class="note">${(item.reviewIssues || []).map((i) => `${esc(i.field)}：${esc(i.original)} → ${esc(i.recognized)}`).join('<br>')}</div><p>请对照实物记录依据；仍不确定可暂留复核。</p>` : '<p>记录这枚实物的观察；服务参考资料保持独立。</p>'}<div class="rr-editor">${fields.map(([key, label]) => `<label>${label}<textarea data-review-field="${key}" maxlength="10000">${esc(section === 'resolution' && item.reviewDetailsStale ? '' : d[key] || '')}</textarea></label>`).join('')}</div>`,
    button('保存记录', 'review-edit-save', 'primary'),
  );
}
function reviewZoom(side) {
  const images = reviewImages(model.task, currentItem(model), side);
  model.reviewZoomSide = side;
  dialog(
    '放大对照 · ' + (side === 'obverse' ? '正面' : '反面'),
    `<div class="rr-zoom-tools"><label>缩放 <input type="range" id="review-zoom-range" min="100" max="300" step="25" value="100"></label>${button('实物旋转 90°', 'review-rotate-mine', 'small quiet')}${button('参考旋转 90°', 'review-rotate-reference', 'small quiet')}${button('重置', 'review-zoom-reset', 'small quiet')}</div><div class="rr-zoom-pair">${[
      ['mine', '我的实物', images.mine],
      ['reference', '服务参考', images.reference],
    ]
      .map(
        ([key, label, url]) =>
          `<div><h3>${label}</h3><div class="rr-zoom-image">${url ? `<img id="review-zoom-${key}" src="${esc(url)}" alt="${label}" referrerpolicy="no-referrer">` : '<p>此面暂无图片</p>'}</div></div>`,
      )
      .join('')}</div>`,
  );
  modal.classList.add('rr-zoom-dialog');
}

function drawBulk() {
  if (!model.task) return;
  // 输入搜索词时仅更新计数、按钮和候选队列；保留搜索框 DOM，避免中断输入法。
  const controls = document.querySelector('#bulk-controls');
  if (controls) {
    const template = document.createElement('template');
    template.innerHTML = bulkControls(model);
    controls.querySelector('.bulk-actionbar').replaceWith(template.content.querySelector('.bulk-actionbar'));
  }
  const list = document.querySelector('.queue');
  if (list) list.outerHTML = queue(model);
  const reviewTable = document.querySelector('.rr-batch')?.closest('.table-wrap');
  if (reviewTable)
    reviewTable.outerHTML = reviewBatch(model, {
      name,
      decision: (i) => (i.review_projection?.stale ? '决定已过期' : reviewLabels[reviewDecision(i)] || '尚未决定'),
      href,
    });
  const table = document.querySelector('#bulk-identify-table');
  if (table) table.innerHTML = identifyRows(model);
}
const batchLabel = (value) =>
  ({
    confirm_pair: '确认配对',
    collect: '待收藏',
    hold: '暂留复核',
    need_photo: '待补图',
    exclude: '排除',
    confirmed: '配对已确认',
    single_side: '待补图',
    excluded: '已排除',
    needs_review: '待核对',
  })[value] ||
  value ||
  '尚未决定';
function batchRows(items) {
  return `<ul class="dialog-list">${items.map((i) => `<li><div><strong>${esc(i.title || (model.task?.items.find((x) => x.local_id === i.localId) && name(model.task.items.find((x) => x.local_id === i.localId))) || i.localId)}</strong><small>${esc(i.localId)}${i.overwrite ? ' · 原决定：' + esc(batchLabel(i.previous)) : ''}</small></div><span>${esc({ ready: '将保存', blocked: '已跳过', unchanged: '保持不变', applied: '已保存' }[i.status])}<small>${esc(i.reason || batchLabel(i.action))}</small></span></li>`).join('')}</ul>`;
}

function drawBridge() {
  const draft = document.querySelector('#bridge-message')?.value || '';
  const selected = document.querySelector('#bridge-host')?.value;
  const host = model.workspace.hosts.find((h) => h.id === selected) || model.workspace.hosts[0];
  const labels = bridgeActionLabels();
  bridge.innerHTML = `<div class="dialog-head"><div><div class="eyebrow">WORKSPACE ↔ HOST</div><h2 id="bridge-title">与 Agent 协作</h2></div><button class="close" data-action="bridge-close" aria-label="关闭协作面板">×</button></div><div class="dialog-body"><div class="bridge-context"><strong>${esc(host ? `${host.host} · ${hostDisplayTitle(host)}` : '等待宿主会话连接')}</strong><small>${host ? `会话 ID：${esc(host.conversation)}<br>` : ''}任务：${esc(model.task?.manifest.display_name || '工作空间')}<br>当前对象：${esc(currentItem(model) ? name(currentItem(model)) : '未选择')}</small></div>${model.workspace.hosts.length > 1 ? `<label style="margin-top:14px">发送到哪个会话<select id="bridge-host">${model.workspace.hosts.map((h) => `<option value="${esc(h.id)}" ${h.id === host.id ? 'selected' : ''}>${esc(hostOptionLabel(h))}</option>`).join('')}</select></label>` : ''}<div style="margin:15px 0">${tag(host?.connected ? '宿主近期在线' : '等待 Agent 取件', host?.connected ? 'green' : 'amber')}</div>${
    model.workspace.commands
      .filter((c) => !host || c.bindingId === host.id)
      .slice()
      .reverse()
      .map(
        (c) =>
          `<div class="message-event"><small>网页 → ${esc(host?.host || 'Agent')} / ${esc(new Date(c.createdAt).toLocaleTimeString())}</small><p>${esc(c.payload.message)}</p>${tag(commandStatus(c), c.status === 'pending' || c.status === 'awaiting_user' ? 'amber' : c.status === 'running' ? 'green' : 'neutral')}${c.progress ? `<div class="note neutral" style="margin-top:12px"><strong>${esc(c.progress.step || '当前进度')}</strong><br>${esc(c.progress.message)}</div>` : ''}${c.reply ? `<div class="note neutral" style="margin-top:12px"><strong>Agent 回复</strong><br>${esc(c.reply.message)}</div>` : ''}</div>`,
      )
      .join('') || '<p class="muted" style="font-size:12px">协作请求与回执会保存在这里。回复建议不会自动授权业务操作。</p>'
  }</div><div class="bridge-compose">${host ? `<div class="bridge-prompt" aria-label="手动唤起 Agent"><div class="bridge-prompt-copy"><strong>需要 Agent 继续工作？</strong><small>默认手动唤起，在当前选中的会话发送：</small><code id="bridge-inbox-prompt" tabindex="0">${esc(INBOX_PROMPT)}</code></div>${button('复制提示词', 'bridge-copy-inbox-prompt', 'quiet small')}</div>` : ''}<label for="bridge-message">向 Agent 提出当前任务的请求</label><textarea id="bridge-message" placeholder="例如：检查这枚钱币的年份冲突，解释依据。">${esc(draft)}</textarea>${model.task ? `<div class="bridge-workflow-note"><strong>固定整理流程</strong><span>${esc(continuationSummary)}</span></div>` : ''}<div class="actions"><small class="muted">${esc(bridgeDeliveryHint(host))}</small>${button(labels.request, 'bridge-send', 'quiet small', !host)}${button(labels.continuation, 'bridge-continue', 'primary small', !host || !model.task)}</div></div>`;
  bridge.dataset.binding = host?.id || '';
}
function showBridge() {
  drawBridge();
  if (!bridge.open) bridge.showModal();
}
function candidateDialog() {
  const used = new Set(
    model.task.items.filter((i) => ['active', 'source_incomplete', 'identity_conflict'].includes(i.status)).flatMap((i) => i.evidence.map((e) => e.source_id)),
  );
  const available = model.task.sources.filter((s) => s.mime_type.startsWith('image/') && !used.has(s.source_id));
  dialog(
    '选择同一枚钱币的图片',
    `${available.length ? '<p>选择属于同一枚实物的照片；下一步单独确认正反面。</p>' : '<p>暂无未分配图片，请先追加资料。已有来源不会被重复分配给另一枚实物。</p>'}<div class="candidate-sources">${available.map((s) => `<label class="source-option"><input type="checkbox" data-source="${esc(s.source_id)}"><img src="${esc(api.media(model.task.manifest.task_key, s.source_id))}" alt="${esc(s.origin.original_name)}"><span>${esc(s.origin.original_name)}</span></label>`).join('')}</div><label>来源名称<input id="candidate-title" maxlength="200" placeholder="可填写清单中的名称，识别后再核对"></label>`,
    available.length ? button('建立候选', 'candidate-save', 'primary') : '',
  );
}

// 鉴定照片不使用原生下拉框：文件名通常由相机生成，无法帮助用户分辨正反面。
// 只允许本枚已关联证据和任务中尚未分配的照片，避免把其他候选的资料误提交给专家。
function appraisalSourcesForItem() {
  const item = currentItem(model);
  if (!item || !model.task) return [];
  const own = new Set(item.evidence.map((e) => e.source_id));
  const occupied = new Set(model.task.items.filter((other) => other.local_id !== item.local_id).flatMap((other) => other.evidence.map((e) => e.source_id)));
  return model.task.sources
    .filter((source) => source.mime_type?.startsWith('image/') && (own.has(source.source_id) || !occupied.has(source.source_id)))
    .map((source) => ({ source, associated: own.has(source.source_id) }));
}

function appraisalPhotoPreview(role, source, associated) {
  const title = { obverse: '正面照片', reverse: '反面照片', side: '侧面照片' }[role];
  if (!source) return '<div class="appraisal-photo-empty"><b>＋</b><span>尚未选择图片</span></div>';
  const filename = source.origin?.original_name || source.source_id;
  return `<img src="${esc(api.media(model.task.manifest.task_key, source.source_id))}" alt="${esc(title)}"><div><strong>${esc(filename)}</strong><small>${associated ? '已关联本枚' : '本任务待关联'}</small></div>`;
}

function appraisalPhotoPicker(role) {
  const roles = ['obverse', 'reverse', 'side'];
  const labels = { obverse: '正面', reverse: '反面', side: '侧面' };
  // 对话框底部的“清除”按钮没有额外 data 属性，暂存本次面别以便安全处理。
  model.appraisalPhotoRole = role;
  const selected = Object.fromEntries(roles.map((key) => [key, document.querySelector(`#appraisal-${key}`)?.value || '']));
  const usedByAnotherRole = new Map(roles.filter((key) => key !== role && selected[key]).map((key) => [selected[key], labels[key]]));
  const choices = appraisalSourcesForItem();
  const current = selected[role];
  dialog(
    `选择${labels[role]}照片`,
    `<p>点击缩略图即可选择。为避免同一张照片重复提交，一个面别已选用的照片会标明占用状态。</p><div class="appraisal-source-grid">${choices
      .map(({ source, associated }) => {
        const usedAs = usedByAnotherRole.get(source.source_id);
        const isCurrent = source.source_id === current;
        const filename = source.origin?.original_name || source.source_id;
        return `<button class="appraisal-source-option ${isCurrent ? 'selected' : ''}" data-action="appraisal-photo-select" data-role="${esc(role)}" data-source="${esc(source.source_id)}" ${usedAs ? 'disabled' : ''}><img src="${esc(api.media(model.task.manifest.task_key, source.source_id))}" alt="${esc(filename)}"><span><strong>${esc(filename)}</strong><small>${usedAs ? `已用于${usedAs}` : associated ? '已关联本枚' : '本任务待关联'}</small></span>${isCurrent ? '<i>当前选择</i>' : ''}</button>`;
      })
      .join('')}</div>${choices.length ? '' : '<p class="muted">暂无可用图片。可先从本地上传并归档，再回来选择。</p>'}`,
    current ? button(`清除${labels[role]}照片`, 'appraisal-photo-clear', 'quiet') : '',
  );
}

const collectionEditFields = [
  ['title', '藏品标题'],
  ['years', '年份'],
  ['mint', '铸记'],
  ['priceLevel', '品相标签'],
  ['priceGrade', '评级分数'],
  ['value', '估值'],
  ['dateAcquired', '购入日期 / 时间戳'],
  ['notes', '备注'],
  ['customWeight', '重量'],
  ['customSize', '尺寸'],
  ['customSerialNumber', '自定义编号'],
  ['customDenomination', '面额说明'],
];

function collectionDetailValue(detail, key) {
  const aliases = {
    years: ['years', 'year'],
    mint: ['mint', 'mintMark'],
    priceLevel: ['priceLevel'],
    priceGrade: ['priceGrade'],
    value: ['value'],
    dateAcquired: ['dateAcquired', 'dateAccquired'],
    notes: ['notes'],
    title: ['title'],
    customWeight: ['customWeight'],
    customSize: ['customSize'],
    customSerialNumber: ['customSerialNumber'],
    customDenomination: ['customDenomination'],
  }[key] || [key];
  for (const container of [detail, detail?.collection, detail?.data, detail?.detail]) {
    if (!container || typeof container !== 'object') continue;
    for (const name of aliases) if (container[name] !== undefined && container[name] !== null) return String(container[name]);
  }
  // 与 CLI 同步兼容 App 形状的 edit-detail：完整表单的可编辑值不全在顶层。
  const collectInfo = detail?.collectInfo;
  const priceInfo = detail?.priceInfo;
  const nested = {
    priceLevel: priceInfo?.label,
    priceGrade: priceInfo?.grade,
    value: collectInfo?.value,
    dateAcquired: collectInfo?.dateAccquired ?? collectInfo?.getTime,
    notes: collectInfo?.notes,
    customWeight: collectInfo?.customWeight,
    customSize: collectInfo?.customSize,
    customSerialNumber: collectInfo?.customSerialNumber,
    customDenomination: collectInfo?.customDenomination,
  }[key];
  if (nested !== undefined && nested !== null) return String(nested);
  return '';
}

function collectionEditDialog(response) {
  const item = currentItem(model);
  const baseline = Object.fromEntries(collectionEditFields.map(([key]) => [key, collectionDetailValue(response.detail, key)]));
  model.collectionEdit = { localId: item.local_id, collectionUri: response.collectionUri, baseline };
  dialog(
    '编辑收藏资料',
    `<p>字段保留为空表示不修改；备注留空并主动保存可清空备注。提交前会再次显示精确差异。</p><div class="form-grid collection-edit-form">${collectionEditFields
      .map(([key, label]) => `<label>${esc(label)}<input data-collection-field="${esc(key)}" value="${esc(baseline[key])}" maxlength="5000"></label>`)
      .join(
        '',
      )}</div><label class="collection-image-sync"><input id="collection-sync-images" type="checkbox"> 同步当前藏品已归档的正反面图片到收藏资料</label>`,
    button('检查编辑变更', 'collection-edit-plan', 'primary'),
  );
}

async function collectionMutationPlan(action) {
  const item = currentItem(model);
  if (!item) throw new Error('请先选择一枚已收藏档案');
  let changes = {};
  if (action === 'update') {
    const edit = model.collectionEdit;
    if (!edit || edit.localId !== item.local_id) throw new Error('请先读取当前收藏资料');
    changes = Object.fromEntries(
      collectionEditFields
        .map(([key]) => [key, document.querySelector(`[data-collection-field="${key}"]`)?.value ?? ''])
        .filter(([key, value]) => value !== edit.baseline[key]),
    );
    if (document.querySelector('#collection-sync-images')?.checked) {
      changes.collectImageSourceIds = item.evidence
        .map((entry) => entry.source_id)
        .filter(Boolean)
        .slice(0, 3);
    }
    if (!Object.keys(changes).length) throw new Error('尚未修改任何字段');
  }
  const plan = await api.request('/api/business/collection-mutation-plan', taskBody({ localId: item.local_id, action, changes }));
  model.pendingCollectionMutation = { action, plan };
  const items = plan.items || [];
  const changeText =
    action === 'cancel'
      ? '<p>此操作会取消该条远程收藏关联；本地档案与历史会继续保留。</p>'
      : `<dl class="remote-fields">${Object.entries(changes)
          .map(
            ([key, value]) =>
              `<dt>${esc(key === 'collectImageSourceIds' ? '收藏图片' : collectionEditFields.find(([field]) => field === key)?.[1] || key)}</dt><dd>${esc(Array.isArray(value) ? `同步 ${value.length} 张已归档图片` : value === '' ? '清空' : value)}</dd>`,
          )
          .join('')}</dl>`;
  dialog(
    action === 'cancel' ? '确认取消收藏' : '确认编辑收藏资料',
    `<p>${esc(items[0]?.display?.title || name(item))}</p>${changeText}<p class="muted">计划已绑定当前任务版本和收藏关联。确认后才会调用 HeriBase CLI。</p>`,
    button(action === 'cancel' ? '确认取消收藏' : '确认提交编辑', 'collection-mutation-start', action === 'cancel' ? 'danger' : 'primary'),
  );
}

function collectionHistoryDialog() {
  const item = currentItem(model);
  const history = (model.task?.collectionHistory || []).filter(
    (entry) => entry.localId === item?.local_id || (entry.items || []).some((value) => value.local_id === item?.local_id),
  );
  dialog(
    '收藏编辑历史',
    history.length
      ? history
          .map(
            (entry) =>
              `<article class="operation-card"><div class="inline" style="justify-content:space-between"><strong>${esc(entry.operationType === 'collection_cancel' ? '取消收藏' : entry.eventType === 'collection_plan_created' ? '编辑计划已创建' : '收藏编辑已归档')}</strong>${tag(entry.status === 'cancelled' ? '已取消' : entry.status || '已记录', entry.status === 'cancelled' ? 'amber' : 'neutral')}</div><small>${esc(new Date(entry.createdAt).toLocaleString())}</small>${
                entry.changes
                  ? `<dl class="remote-fields">${Object.entries(entry.changes)
                      .map(
                        ([key, value]) =>
                          `<dt>${esc(key === 'collectImageSourceIds' ? '收藏图片' : collectionEditFields.find(([field]) => field === key)?.[1] || key)}</dt><dd>${esc(Array.isArray(value) ? `同步 ${value.length} 张已归档图片` : value === '' ? '清空' : value)}</dd>`,
                      )
                      .join('')}</dl>`
                  : ''
              }${entry.rawResponseRef ? `<p class="muted">已归档服务回执：${esc(entry.rawResponseRef)}</p>` : ''}</article>`,
          )
          .join('')
      : '<p>尚无收藏编辑或取消记录。</p>',
  );
}
function updatePairPreviews() {
  for (const role of ['obverse', 'reverse']) {
    const sourceId = document.querySelector(`#${role}-source`)?.value;
    const frame = document.querySelector(`[data-pair-photo="${role}"]`);
    if (!frame || !model.task) continue;
    const label = role === 'obverse' ? '正面' : '反面';
    const source = model.task.sources.find((entry) => entry.source_id === sourceId);
    frame.classList.toggle('empty', !source);
    const url = source ? api.media(model.task.manifest.task_key, source.source_id) : null;
    frame.innerHTML = url
      ? `<button data-action="zoom" data-url="${esc(url)}" aria-label="放大${label}"><img src="${esc(url)}" alt="${label}"></button><figcaption><span>${label}</span><span>查看原图 ↗</span></figcaption>`
      : `<b>＋</b><span>尚未指定${label}</span><small>请选择对应资料</small>`;
  }
}
async function savePair(action) {
  const item = currentItem(model);
  const entries = itemSources(model.task, item);
  const front = document.querySelector('#obverse-source')?.value,
    back = document.querySelector('#reverse-source')?.value;
  const assignments = entries.map((e) => ({
    sourceId: e.source.source_id,
    role: e.source.source_id === front ? 'obverse' : e.source.source_id === back ? 'reverse' : 'unknown',
  }));
  if (action === 'confirm_pair' && (!front || !back || front === back)) throw new Error('请指定两张不同来源的正反面照片');
  await change('/api/tasks/pair', taskBody({ localId: item.local_id, action, assignments }));
  toast('配对决定已保存');
}
async function saveNote(value) {
  const item = currentItem(model),
    previous = model.workspace.notes.find((n) => n.id === item.local_id),
    tick = draftTick;
  const saved = await api.request('/api/entities', { kind: 'note', id: item.local_id, data: { text: value }, expectedRevision: previous?.revision || 0 });
  model.workspace.notes = model.workspace.notes.filter((n) => n.id !== saved.id).concat(saved);
  if (tick === draftTick) dirty = false;
  const status = document.querySelector('#note-status');
  if (status) status.textContent = dirty ? '正在保存新输入…' : '已自动保存';
  return saved;
}
function appraisalBody() {
  const item = currentItem(model),
    draft = model.workspace.appraisals.find((a) => a.id === item.local_id);
  const selected = selectedAppraisalService();
  if (!selected) throw new Error('请先从当前服务目录选择鉴定服务');
  return taskBody({
    localId: item.local_id,
    description: document.querySelector('#appraisal-desc').value,
    sourceIds: Object.fromEntries(['obverse', 'reverse', 'side'].map((role) => [role, document.querySelector('#appraisal-' + role).value || null])),
    ...selected,
    draftRevision: draft?.revision || 0,
  });
}

function appraisalServiceText(expert) {
  if (!expert) return '所选服务';
  return [expert.name, expert.duration, expert.price && expert.currency ? `${expert.currency}${expert.price} / 次` : null].filter(Boolean).join(' · ');
}

function purchasePrice(product) {
  const amount = Number(product?.amount),
    exponent = Number(product?.currencyExponent);
  if (!Number.isFinite(amount) || !Number.isInteger(exponent)) return '价格以支付页为准';
  return `${String(product.currency || '').toUpperCase()} ${(amount / 10 ** exponent).toFixed(exponent)}`.trim();
}
function trackingAvailableSlots(value) {
  const count = Number(value?.availableSlots);
  return Number.isFinite(count) && count >= 0 ? count : null;
}
function showTrackingPlan(plan) {
  const available = trackingAvailableSlots(plan.eligibility);
  if (available === 0) {
    dialog(
      '需要购买追踪位',
      `<p>${esc(plan.title)}</p><p>当前没有可用追踪位。选择商品、确认订单并完成支付后，工作台会核验追踪位到账；之后再回来确认开启这枚藏品的追踪。</p>${remoteFields(plan.eligibility)}`,
      button('查看可购买的追踪位', 'tracking-purchase-guide', 'primary'),
    );
    return;
  }
  if (available === null) {
    dialog(
      '暂时无法确认追踪位',
      `<p>${esc(plan.title)}</p><p>服务没有返回可用追踪位数量，请重新检查后再继续。</p>${remoteFields(plan.eligibility)}`,
      button('重新检查追踪位', 'tracking-recheck-slots', 'primary'),
    );
    return;
  }
  dialog(
    '确认开启追踪',
    `<p>${esc(plan.title)}</p><p>当前可用 ${available} 个追踪位。确认后会为这枚本人收藏开启追踪。</p>${remoteFields(plan.eligibility)}`,
    button('确认使用追踪位', 'tracking-run', 'primary'),
  );
}
async function saveAppraisal() {
  const tick = draftTick,
    result = await api.request('/api/business/appraisal-save', appraisalBody());
  model.workspace.appraisals = model.workspace.appraisals.filter((a) => a.id !== result.id).concat(result);
  if (tick === draftTick) dirty = false;
  return result;
}
async function persistDraft() {
  if (savingDraft) return savingDraft;
  const note = document.querySelector('#edit-note-text') || document.querySelector('#review-note');
  savingDraft = note ? saveNote(note.value) : document.querySelector('#appraisal-desc') ? saveAppraisal() : Promise.resolve();
  let saved = false;
  try {
    await savingDraft;
    saved = true;
  } finally {
    savingDraft = null;
    if (saved && dirty) {
      clearTimeout(draftTimer);
      draftTimer = setTimeout(() => persistDraft().catch(showError), 300);
    }
  }
}
function draftChanged() {
  dirty = true;
  draftTick++;
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => persistDraft().catch(showError), 800);
}
async function ingestFiles(files, key, revision) {
  let current = revision;
  for (let index = 0; index < files.length; index++) {
    document.querySelector('#workspace-status').textContent = `归档 ${index + 1}/${files.length}：${files[index].name}`;
    const result = await api.upload(key, current, files[index]);
    current = result.revision;
  }
  return current;
}

document.addEventListener('click', async (e) => {
  const skip = e.target.closest('.skip');
  if (skip) {
    e.preventDefault();
    main.focus();
    return;
  }
  const anchor = e.target.closest('a[href^="#"]');
  if (anchor && add.photosDirty) {
    e.preventDefault();
    dialog(
      '照片调整尚未保存',
      '<p>保存后再继续，或放弃这次调整。</p>',
      `<button class="button danger" data-action="add-photo-discard-navigate" data-href="${esc(anchor.getAttribute('href'))}">放弃调整并继续</button>`,
    );
    return;
  }
  if (anchor && (dirty || pairDirty)) {
    e.preventDefault();
    dialog(
      '当前输入尚未保存',
      '<p>请保存当前输入后再切换页面，或明确放弃这次输入。</p>',
      `<button class="button danger" data-action="discard-navigate" data-href="${esc(anchor.getAttribute('href'))}">放弃输入并继续</button>`,
    );
    return;
  }
  if (anchor?.hasAttribute('data-review-detail')) {
    model.reviewView = 'compare';
    if (location.hash === anchor.getAttribute('href')) {
      e.preventDefault();
      draw();
    }
  }
  if (anchor) {
    modal.close();
    bridge.close();
  }
  const target = e.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  if (action === 'add-photo-discard-navigate') {
    add.cancelPhotos();
    modal.close();
    location.hash = target.dataset.href;
    return;
  }
  if (action === 'add-choose') {
    document.querySelector('#add-files')?.click();
    return;
  }
  if (action === 'add-photo') {
    [...document.querySelectorAll('[data-add-supplement]')]
      .find((input) => input.dataset.id === target.dataset.id && input.dataset.addSupplement === target.dataset.side)?.click();
    return;
  }
  if (action === 'add-next-step') {
    document.querySelector('.add-next')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }
  const photoMethod = {
    'add-photos': ['openPhotos', target.dataset.id],
    'add-photo-side': ['photoSide', target.dataset.side],
    'add-photo-select': ['choosePhoto', target.dataset.source],
    'add-photo-swap': ['swapPhotos'],
    'add-photo-cancel': ['cancelPhotos'],
    'add-photo-refresh': ['refreshPhotos'],
    'add-photo-save': ['savePhotos'],
    'add-photo-confirm': ['confirmPhotos', target.dataset.id],
  }[action];
  if (photoMethod) {
    try {
      await add[photoMethod[0]](...photoMethod.slice(1));
      if (action === 'add-photo-save' || action === 'add-photo-confirm') {
        await refresh(true);
        document.querySelector('.add-next')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else if (action === 'add-photos') {
        document.querySelector('.add-coin-card.is-editing')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch (error) {
      add.state.error = friendlyAddError(error);
      draw();
    }
    return;
  }
  if (action.startsWith('add-')) {
    const method = { 'add-organize': 'organize', 'add-preview': 'preview', 'add-identify': 'identify', 'add-collect': 'collect', 'add-refresh': 'refresh', 'add-swap': 'swap', 'add-new': 'newCoin' }[action];
    if (!method) return;
    try {
      const work = add[method]();
      if (['add-identify', 'add-collect', 'add-organize'].includes(action)) scrollAddStatus();
      await work;
      if (action === 'add-identify' || action === 'add-collect' || action === 'add-refresh' || action === 'add-organize') await refresh(true);
    } catch (error) {
      add.state.error = friendlyAddError(error);
      draw();
    }
    return;
  }
  if (action.startsWith('commerce-')) {
    await dialogAction(target, () => commerce.handle(action, target));
    return;
  }
  if (action === 'api-check') {
    await dialogAction(target, async () => {
      const result = await api.apiCheck();
      apiCheckDialog(result);
      toast(result.api?.ok ? 'API 网络检查完成' : 'API 网络检查发现异常');
    });
    return;
  }
  if (action === 'bulk-select' || action === 'bulk-clear') {
    const selection = selectionFor(model);
    if (action === 'bulk-clear') selection.ids.clear();
    else {
      const visible = filteredItems(model).filter((i) => model.route.page !== 'identify' || eligibleForIdentification(i));
      const next = new Set([...selection.ids, ...visible.map((i) => i.local_id)]);
      if (next.size > 500) {
        toast('每批最多 500 枚，请缩小筛选范围');
        return;
      }
      selection.ids = next;
    }
    drawBulk();
    return;
  }
  if (action === 'bulk-history') {
    const batches = (model.task?.batches || []).filter((b) => b.stage === model.route.page || model.route.page === 'identify');
    dialog(
      '批量决定记录',
      batches
        .map(
          (b) =>
            `<details class="batch-history"><summary>${esc(new Date(b.createdAt).toLocaleString())} · ${b.stage === 'pairing' ? '配对' : '审核'} · 已保存 ${b.appliedCount ?? b.items.length} 枚 / 选中 ${b.items.length} 枚</summary><p class="muted">${esc(b.batchActionId)} · ${esc(b.actor)}</p>${batchRows(b.items)}</details>`,
        )
        .join('') || '<p>还没有已保存的批量决定。</p>',
    );
    return;
  }
  if (action === 'accept-latest') {
    const latest = model.conflict;
    if (latest.kind === 'note') model.workspace.notes = model.workspace.notes.filter((n) => n.id !== latest.id).concat(latest);
    else if (latest.kind === 'appraisal-draft') model.workspace.appraisals = model.workspace.appraisals.filter((a) => a.id !== latest.id).concat(latest);
    if (model.conflictDraft !== undefined) {
      const value = document.querySelector('#conflict-note-text')?.value || '';
      dialog('编辑本地备注', `<textarea id="edit-note-text" aria-label="本地备注">${esc(value)}</textarea>`, button('保存备注', 'save-edit-note', 'primary'));
    } else modal.close();
    return;
  }
  if (action === 'close') {
    if (model.reviewEditing) {
      dirty = model.reviewEditing.priorDirty;
      model.reviewEditing = null;
    }
    modal.close();
    return;
  }
  if (action === 'bridge-close') {
    bridge.close();
    return;
  }
  if (action === 'bridge') {
    showBridge();
    return;
  }
  if (action === 'candidate') {
    if (pairDirty) {
      toast('请先保存当前照片方向');
      return;
    }
    candidateDialog();
    return;
  }
  if (action === 'discard-navigate') {
    dirty = false;
    pairDirty = false;
    modal.close();
    location.hash = target.dataset.href;
    return;
  }
  if (action === 'pick-files' || action === 'append-files') {
    document.querySelector('#file-input').click();
    return;
  }
  if (action === 'appraisal-upload') {
    document.querySelector('#appraisal-file-input').click();
    return;
  }
  if (action === 'appraisal-photo-picker') {
    appraisalPhotoPicker(target.dataset.role);
    return;
  }
  if (action === 'appraisal-photo-select' || action === 'appraisal-photo-clear') {
    const role = target.dataset.role || model.appraisalPhotoRole;
    const input = document.querySelector(`#appraisal-${role}`);
    if (!input) throw new Error('请返回鉴定材料页重新选择照片');
    const selectedId = action === 'appraisal-photo-select' ? target.dataset.source : '';
    const alreadyUsed = ['obverse', 'reverse', 'side'].some((key) => key !== role && document.querySelector(`#appraisal-${key}`)?.value === selectedId);
    if (selectedId && alreadyUsed) {
      toast('这张照片已用于另一个面别，请选择不同照片');
      return;
    }
    const chosen = appraisalSourcesForItem().find(({ source }) => source.source_id === selectedId);
    if (selectedId && !chosen) throw new Error('该照片不属于当前藏品或已关联给其他候选，不能用于本次鉴定');
    input.value = selectedId || '';
    const preview = document.querySelector(`[data-appraisal-photo-preview="${role}"]`);
    if (preview) preview.innerHTML = appraisalPhotoPreview(role, chosen?.source, chosen?.associated);
    modal.close();
    draftChanged();
    toast(selectedId ? `${{ obverse: '正面', reverse: '反面', side: '侧面' }[role]}照片已选择` : '已清除该面别照片');
    return;
  }
  if (action === 'collection-edit') {
    void dialogAction(target, async () => {
      const detail = await api.request('/api/business/collection-edit-detail', taskBody({ localId: currentItem(model).local_id }));
      collectionEditDialog(detail);
    });
    return;
  }
  if (action === 'collection-edit-plan') {
    void dialogAction(target, () => collectionMutationPlan('update'));
    return;
  }
  if (action === 'collection-cancel-plan') {
    void dialogAction(target, () => collectionMutationPlan('cancel'));
    return;
  }
  if (action === 'collection-history') {
    collectionHistoryDialog();
    return;
  }
  if (action === 'swap') {
    const a = document.querySelector('#obverse-source'),
      b = document.querySelector('#reverse-source');
    [a.value, b.value] = [b.value, a.value];
    pairDirty = true;
    updatePairPreviews();
    toast('方向已交换，确认配对后保存');
    return;
  }
  if (action === 'review-zoom' || action === 'review-zoom-reset') {
    reviewZoom(action === 'review-zoom-reset' ? model.reviewZoomSide : target.dataset.side);
    return;
  }
  if (action === 'review-rotate-mine' || action === 'review-rotate-reference') {
    const img = document.querySelector('#review-zoom-' + (action.endsWith('mine') ? 'mine' : 'reference'));
    if (img) {
      img.dataset.angle = String(Number(img.dataset.angle || 0) + 90);
      img.style.transform = `rotate(${img.dataset.angle}deg)`;
    }
    return;
  }
  if (action === 'review-choice') {
    reviewDraft().decision = target.dataset.value;
    dirty = true;
    draw();
    return;
  }
  if (action === 'review-history') {
    const item = currentItem(model);
    dialog(
      '审核记录',
      (item.reviewHistory || [])
        .slice()
        .reverse()
        .map(
          (h) =>
            `<div class="operation-card"><h3>${esc(reviewLabels[h.decision] || h.decision)}</h3><small>${esc(new Date(h.createdAt).toLocaleString())} · ${esc(h.actor)}</small><pre class="conflict-data">${esc(JSON.stringify(h.details && Object.keys(h.details).length ? h.details : h.note || '无附加记录', null, 2))}</pre></div>`,
        )
        .join('') || '<p>暂无审核记录</p>',
    );
    return;
  }
  if (action === 'zoom') {
    const title = target.dataset.imageKind === 'reference' ? '服务参考图片 · 非本枚实物' : '原始证据';
    dialog(title, `<img src="${esc(target.dataset.url)}" alt="${esc(title)}" referrerpolicy="no-referrer" style="max-height:65vh;display:block;margin:auto;object-fit:contain">`);
    return;
  }
  if (action === 'filter') {
    model.filter = target.dataset.value;
    draw();
    return;
  }
  if (action === 'library-view') {
    model.libraryView = model.libraryView === 'grid' ? 'table' : 'grid';
    draw();
    return;
  }
  if (action === 'edit-note') {
    const value = model.workspace.notes.find((n) => n.id === currentItem(model).local_id)?.data.text || '';
    dialog('编辑本地备注', `<textarea id="edit-note-text" aria-label="本地备注">${esc(value)}</textarea>`, button('保存备注', 'save-edit-note', 'primary'));
    return;
  }
  if (action === 'search') {
    dialog(
      '搜索工作空间',
      '<input id="global-query" style="width:100%" aria-label="搜索工作空间" placeholder="搜索名称、年份或任务"><div id="global-results" class="search-results"></div>',
    );
    document.querySelector('#global-query').focus();
    return;
  }
  if (
    (dirty || pairDirty) &&
    ![
      'pair-confirm',
      'pair-photo',
      'pair-exclude',
      'save-note',
      'save-edit-note',
      'appraisal-save',
      'appraisal-preview',
      'bridge-send',
      'bridge-continue',
      'bridge-copy-inbox-prompt',
      'review-save',
      'review-save-next',
      'review-edit-save',
      'review-view',
      'review-edit',
    ].includes(action)
  ) {
    toast(pairDirty ? '请先确认当前照片方向，再执行批量操作' : '正在保存当前输入，请稍后再操作');
    return;
  }
  if (busy) return;
  busy = true;
  target.disabled = true;
  try {
    if (action === 'review-view') {
      model.reviewView = target.dataset.value;
      draw();
    }
    if (action === 'review-edit') reviewEditor(target.dataset.section);
    if (action === 'review-edit-save') {
      const editing = model.reviewEditing;
      const details = Object.fromEntries(editing.fields.map((key) => [key, document.querySelector(`[data-review-field="${key}"]`).value.trim()]));
      if (editing.fields.includes('resolution') && !details.resolution) throw new Error('请填写核对依据；仍不确定可暂留复核');
      await api.request('/api/tasks/review', { ...editing.body, details });
      model.reviewEditing = null;
      dirty = false;
      modal.close();
      await refresh(true);
      dirty = editing.priorDirty;
      toast('审核记录已保存');
    }
    if (action === 'review-save' || action === 'review-save-next') {
      const item = currentItem(model),
        draft = reviewDraft();
      const details = {
        note: draft.note ?? document.querySelector('#review-detail-note')?.value ?? item.reviewDetails?.note ?? '',
        checks: draft.checks || [...document.querySelectorAll('[data-review-check]:checked')].map((x) => x.dataset.reviewCheck),
      };
      const next = model.task.items[model.task.items.findIndex((i) => i.local_id === item.local_id) + 1];
      await api.request(
        '/api/tasks/review',
        taskBody({
          localId: item.local_id,
          decision: draft.decision || reviewDecision(item) || (item.active_identification?.status === 'succeeded' ? 'collect' : 'hold'),
          details,
        }),
      );
      model.reviewDraft = null;
      dirty = false;
      await refresh(true);
      if (action === 'review-save-next' && next) go('review', model.task.manifest.task_key, next.local_id);
      toast('审核决定与记录已保存');
    }
    if (action === 'refresh') {
      if (dirty || pairDirty) {
        toast('请先保存当前输入，再刷新状态');
        return;
      }
      void refreshAccountProfile();
      await refresh(true);
      toast('已更新');
    }
    if (action === 'create-task') {
      const title = document.querySelector('#task-name').value.trim();
      if (!title) throw new Error('请填写任务名称');
      model.importName = title;
      const task = await api.request('/api/tasks/create', { name: title, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' });
      const key = task.manifest.task_key;
      // 新任务创建成功后清空草稿名；下次进入新建页时按当日日期重新生成默认名。
      model.importName = undefined;
      try {
        await ingestFiles(model.files, key, task.manifest.revision);
        model.files = [];
        dirty = false;
        await refresh(true);
        go('inputs', key);
      } catch (error) {
        await refresh(true);
        go('inputs', key);
        throw error;
      }
    }
    if (action === 'bulk-preview') {
      const selection = selectionFor(model);
      const request = taskBody({ stage: model.route.page, action: target.dataset.value, localIds: [...selection.ids] });
      const plan = await api.request('/api/tasks/bulk-preview', request);
      model.pendingBulk = { request, plan };
      const ready = plan.items.filter((i) => i.status === 'ready').length,
        skipped = plan.items.filter((i) => i.status === 'blocked').length;
      dialog(
        `批量${batchLabel(request.action)} · 确认范围`,
        `<p>选中 ${plan.items.length} 枚：将保存 ${ready} 枚，跳过 ${skipped} 枚，保持原决定 ${plan.items.length - ready - skipped} 枚。覆盖已有决定 ${plan.items.filter((i) => i.overwrite).length} 枚。</p>${batchRows(plan.items)}<p class="muted">${model.route.page === 'pairing' ? '配对变化会使对应旧识别、审核与未执行计划过期。' : '待收藏仅保存审核决定；线上收藏仍需单独确认清单。'}</p>`,
        button('确认保存这些决定', 'bulk-apply', 'primary', !ready),
      );
    }
    if (action === 'bulk-apply') {
      const { request, plan } = model.pendingBulk;
      try {
        const result = await change('/api/tasks/bulk-apply', { ...request, planHash: plan.planHash });
        for (const id of result.appliedIds) selectionFor(model).ids.delete(id);
        drawBulk();
        const nextIds =
          request.stage === 'pairing' && request.action === 'confirm_pair'
            ? (model.task?.items || []).filter((i) => request.localIds.includes(i.local_id) && eligibleForIdentification(i)).map((i) => i.local_id)
            : [];
        model.nextIdentification = nextIds.length ? { taskKey: request.taskKey, localIds: nextIds } : null;
        dialog(
          '批量决定已保存',
          `<p>${result.appliedIds.length} 枚已保存。未处理条目继续保留选中，可调整后再处理。</p>${nextIds.length ? `<p>本批有 ${nextIds.length} 枚可以继续识别；下一步先检查范围，不会立即上传。</p>` : ''}${batchRows(result.items)}`,
          nextIds.length ? button(`继续确认识别范围（${nextIds.length} 枚）`, 'identify-continue', 'primary') : '',
        );
        model.pendingBulk = null;
      } catch (error) {
        // 不把旧确认套到新版本；保留选中对象，必须重新预览。
        if (error.status === 409) {
          modal.close();
          await refresh(true);
          model.pendingBulk = null;
        }
        throw error;
      }
    }
    if (action === 'identify-continue') {
      const handoff = model.nextIdentification;
      if (!handoff) throw new Error('请从识别页重新选择当前范围');
      model.identificationHandoff = handoff;
      model.nextIdentification = null;
      modal.close();
      go('identify', handoff.taskKey);
    }
    if (action === 'candidate-save') {
      const sources = [...document.querySelectorAll('[data-source]:checked')].map((el) => el.dataset.source);
      await change('/api/tasks/candidate', taskBody({ sourceIds: sources, title: document.querySelector('#candidate-title').value.trim() }));
      toast('候选已保存，请核对图片方向');
    }
    if (action === 'candidate-merge') {
      const targetItem = model.task.items.find((item) => item.local_id === target.dataset.targetLocalId);
      const sourceItem = model.task.items.find((item) => item.local_id === target.dataset.sourceLocalId);
      if (!targetItem || !sourceItem) throw new Error('候选已变化，请刷新后重新选择建议');
      const sourceCount = sourceItem.evidence?.length || 0;
      dialog(
        '合并两条图片候选？',
        `<p>将 <strong>${esc(name(sourceItem))}</strong> 的 ${sourceCount} 张图片并入当前候选 <strong>${esc(name(targetItem))}</strong>。</p><p>原记录会保留为“已合并”历史，所有图片方向会重置为待核对；合并后可在右侧重新指定正反面。</p><p class="muted">此操作只整理本地记录，不会上传图片、启动识别或加入收藏。</p>`,
        `<button class="button primary" data-action="candidate-merge-confirm" data-target-local-id="${esc(targetItem.local_id)}" data-source-local-id="${esc(sourceItem.local_id)}">确认合并并继续配对</button>`,
      );
      return;
    }
    if (action === 'candidate-merge-confirm') {
      await change('/api/tasks/merge-candidates', taskBody({
        targetLocalId: target.dataset.targetLocalId,
        sourceLocalId: target.dataset.sourceLocalId,
      }));
      if (modal.open) modal.close();
      toast('候选已合并，请在当前记录重新指定正反面');
    }
    if (action === 'pair-confirm') await savePair('confirm_pair');
    if (action === 'pair-photo') await savePair('need_photo');
    if (action === 'pair-exclude') await savePair('exclude');
    if (action === 'decision') {
      await change('/api/tasks/review', taskBody({ localId: currentItem(model).local_id, decision: target.dataset.value }));
      toast('审核决定已保存');
    }
    if (action === 'save-note') {
      await persistDraft();
      toast('备注已保存');
    }
    if (action === 'save-edit-note') {
      await persistDraft();
      modal.close();
      await refresh(true);
    }
    if (action === 'auto-open') {
      await change('/api/entities', {
        kind: 'settings',
        id: 'workspace',
        expectedRevision: model.workspace.settings?.revision || 0,
        data: { autoOpen: model.workspace.settings?.data.autoOpen === false },
      });
    }
    if (action === 'bridge-send') {
      const message = document.querySelector('#bridge-message').value.trim();
      if (!message) throw new Error('请填写请求内容');
      await api.request('/api/requests', {
        commandId: crypto.randomUUID(),
        bindingId: bridge.dataset.binding,
        taskId: model.task?.manifest.task_key || null,
        objectId: currentItem(model)?.local_id || null,
        message,
      });
      document.querySelector('#bridge-message').value = '';
      await refresh();
      if (bridge.open) drawBridge();
      toast('请求已保存，等待宿主接收');
    }
    if (action === 'bridge-copy-inbox-prompt') {
      const clipboard = navigator.clipboard;
      const writeText = clipboard?.writeText ? clipboard.writeText.bind(clipboard) : null;
      if (await copyInboxPrompt(writeText)) {
        toast('提示词已复制，请粘贴到当前选中的 Agent 会话');
      } else {
        const prompt = document.querySelector('#bridge-inbox-prompt');
        if (prompt) {
          prompt.focus();
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(prompt);
          selection?.removeAllRanges();
          selection?.addRange(range);
        }
        toast('无法自动复制，请手动复制已选中的提示词');
      }
    }
    if (action === 'bridge-continue') {
      const message = document.querySelector('#bridge-message').value.trim() || '请解析当前表格，建立表格候选，关联正反面图片，并停在配对审核供我确认。';
      await api.request('/api/requests', continuationRequest(model.task, currentItem(model), bridge.dataset.binding, message, crypto.randomUUID()));
      document.querySelector('#bridge-message').value = '';
      await refresh();
      if (bridge.open) drawBridge();
      toast('整理请求已保存；Agent 领取后会在这里更新进度');
    }
    if (action === 'identify-preview') {
      const ids = identificationSelection(model);
      if (!ids.length) throw new Error('没有可识别对象，请返回配对补全资料');
      if (ids.length > 500) throw new Error('每批最多 500 枚，请缩小筛选或勾选部分候选');
      selectionFor(model).ids = new Set(ids);
      drawBulk();
      const plan = await api.request('/api/tasks/identification-plan', taskBody({ localIds: ids }));
      const quotaNotice = identificationQuotaNotice(plan.eligibility, plan.account?.apiBaseUrl, plan.items.length);
      if (quotaNotice) {
        model.pendingPlan = null;
        dialog('识别额度', quotaNotice, button('重新检查额度', 'identify-preview', 'quiet'));
        return;
      }
      dialog(
        '确认上传与识别',
        `<p>本次处理 ${plan.items.length} 枚；确认后会上传图片并逐枚识别。</p><ul class="dialog-list">${plan.items.map((i) => `<li>${esc(i.title)}<span>正反面齐全</span></li>`).join('')}</ul><p class="muted">费用及批量剩余额度以服务返回为准；未知项不作承诺。</p>`,
        button('确认上传与识别', 'identify-run', 'primary'),
      );
      model.pendingPlan = plan;
    }
    if (action === 'identify-run') {
      const plan = model.pendingPlan;
      try {
        await change('/api/tasks/identify', taskBody({ planHash: plan.hash, localIds: plan.items.map((i) => i.localId), commandId: crypto.randomUUID() }));
      } catch (error) {
        const quotaNotice = identificationQuotaNotice(error.detail?.eligibility, plan.account?.apiBaseUrl, plan.items.length);
        if (!quotaNotice) throw error;
        model.pendingPlan = null;
        dialog('识别额度', quotaNotice, button('重新检查额度', 'identify-preview', 'quiet'));
        return;
      }
      go('operations', model.task.manifest.task_key);
    }
    if (action === 'collection-preview') {
      const ids = [...document.querySelectorAll('[data-confirm-id]:checked')].map((el) => el.dataset.confirmId);
      if (!ids.length) throw new Error('请至少选择一枚藏品');
      const plan = await api.request('/api/tasks/collection-plan', taskBody({ localIds: ids }));
      model.pendingPlan = plan;
      await refresh(true);
      dialog(
        '确认加入收藏',
        `<p>本次新增 ${plan.items.length} 枚收藏。</p>${remoteFields(plan.capacity)}<ul class="dialog-list">${plan.items.map((i) => `<li>${esc(i.display.title)}<span>新增收藏</span></li>`).join('')}</ul><p class="muted">本次确认只授权当前清单，不包含鉴定或价格追踪。</p>`,
        button('确认并开始收藏', 'collection-run', 'primary'),
      );
    }
    if (action === 'collection-run') {
      await change(
        '/api/tasks/collect',
        taskBody({ planId: model.pendingPlan.plan_id, planHash: model.pendingPlan.payload_sha256, commandId: crypto.randomUUID() }),
      );
      go('operations', model.task.manifest.task_key);
    }
    if (action === 'collection-mutation-start') {
      const pending = model.pendingCollectionMutation;
      if (!pending) throw new Error('请重新检查收藏编辑范围');
      await change('/api/business/collection-mutation-start', {
        taskKey: model.task.manifest.task_key,
        expectedRevision: pending.plan.revision,
        planId: pending.plan.plan_id,
        planHash: pending.plan.payload_sha256,
        commandId: crypto.randomUUID(),
        action: pending.action,
      });
      model.pendingCollectionMutation = null;
      go('operations', model.task.manifest.task_key);
    }
    if (action === 'export') {
      const quote = (value) => {
        const text = String(value ?? '');
        return '"' + (/^[=+@\-\t\r]/.test(text) ? "'" : '') + text.replaceAll('"', '""') + '"';
      };
      const csv =
        '\uFEFF' +
        [
          ['来源名称', '任务', '状态', '本地备注'],
          ...records(model).map(({ item, task }) => [
            name(item),
            task.manifest.display_name,
            collected(item) ? '已收藏' : decision(item),
            model.workspace.notes.find((n) => n.id === item.local_id)?.data.text || '',
          ]),
        ]
          .map((row) => row.map(quote).join(','))
          .join('\r\n');
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' })),
        a = document.createElement('a');
      a.href = url;
      a.download = 'HeriBase-藏品清单.csv';
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    if (action === 'appraisal-save') {
      await persistDraft();
      toast('鉴定材料已保存');
    }
    if (action === 'appraisal-preview') {
      await persistDraft();
      const plan = await api.request('/api/business/appraisal-plan', taskBody({ localId: currentItem(model).local_id }));
      model.pendingPlan = plan;
      dialog(
        '确认提交真人鉴定',
        `<p>${esc(plan.title)}</p><p>本次上传正面、反面与侧面照片，使用已有鉴定次数。</p><p>${esc(appraisalServiceText(plan.eligibility.selected))}</p>${remoteFields(plan.eligibility.credits)}<p>${esc(plan.draft.description)}</p>`,
        button('确认材料与已有次数', 'appraisal-run', 'primary'),
      );
    }
    if (action === 'appraisal-run') {
      await change('/api/business/appraisal-start', { planId: model.pendingPlan.id, planHash: model.pendingPlan.hash, commandId: crypto.randomUUID() });
      go('appraisals');
    }
    if (action === 'appraisal-services') {
      if (!model.appraisalServices?.experts?.length) {
        await loadAppraisalServices(true);
        await refreshAppraisalCredits({ notify: true });
        return;
      }
      await refreshAppraisalCredits({ notify: true });
    }
    if (action === 'appraisal-purchase-guide') {
      const selected = selectedAppraisalService();
      if (!selected) throw new Error('请先选择鉴定服务');
      const options = await api.request('/api/business/appraisal-purchase-options', selected);
      model.purchaseOptions = options;
      dialog(
        '选择购买次数',
        `<p>${esc(appraisalServiceText(options.service))}</p><p>请选择服务端当前可售的鉴定次数商品。价格和次数以本次商品目录为准。</p><div class="dialog-list">${options.products.map((product) => `<div><strong>${esc(`${product.times} 次鉴定`)}</strong><span>${esc(purchasePrice(product))}</span><button class="button small primary" data-action="appraisal-purchase-preview" data-sku="${esc(product.sku)}">选择</button></div>`).join('')}</div>`,
      );
    }
    if (action === 'appraisal-purchase-preview') {
      const selected = selectedAppraisalService();
      if (!selected) throw new Error('请先选择鉴定服务');
      const plan = await api.request('/api/business/appraisal-purchase-plan', { ...selected, sku: target.dataset.sku });
      model.pendingPurchase = plan;
      dialog(
        '确认创建支付订单',
        `<p>${esc(appraisalServiceText(plan.service))}</p><p>购买 ${esc(String(plan.product.times))} 次鉴定 · ${esc(purchasePrice(plan.product))}</p><p class="muted">确认后会创建订单并打开服务端提供的安全支付页面。付款完成后需返回这里核验次数到账。</p>`,
        button('确认购买并前往支付', 'appraisal-purchase-checkout', 'primary'),
      );
    }
    if (action === 'appraisal-purchase-checkout') {
      const plan = model.pendingPurchase;
      if (!plan) throw new Error('请重新选择购买商品');
      const result = await api.request('/api/business/appraisal-purchase-checkout', {
        planId: plan.id,
        planHash: plan.hash,
        commandId: crypto.randomUUID(),
      });
      await refresh(true);
      const purchase = result.purchase;
      dialog(
        result.checkoutUrl ? '订单已创建，完成支付' : '订单已创建',
        `<p>${esc(appraisalServiceText(purchase?.data?.service || plan.service))}</p><p>订单已保存。付款完成后返回工作台检查支付状态和次数发放。</p>${result.checkoutUrl ? `<a class="button primary" href="${esc(result.checkoutUrl)}" target="_blank" rel="noopener">前往安全支付</a>` : '<p class="muted">此订单已存在或支付页未返回。请从原支付页面继续，付款后在这里检查到账。</p>'}`,
        purchase
          ? `${!result.checkoutUrl ? `<button class="button" data-action="appraisal-purchase-resume" data-id="${esc(purchase.id)}">继续支付</button>` : ''}<button class="button primary" data-action="appraisal-purchase-refresh" data-id="${esc(purchase.id)}">我已付款，检查到账</button>`
          : '',
      );
    }
    if (action === 'appraisal-purchase-resume') {
      const result = await api.request('/api/business/appraisal-purchase-resume', { purchaseId: target.dataset.id });
      const purchase = result.purchase;
      dialog(
        '继续完成支付',
        `<p>${esc(appraisalServiceText(purchase?.data?.service))}</p><p>这是已有订单的支付页面；不会创建新的订单。付款完成后请返回工作台检查到账。</p><a class="button primary" href="${esc(result.checkoutUrl)}" target="_blank" rel="noopener">前往安全支付</a>`,
        `<button class="button" data-action="appraisal-purchase-refresh" data-id="${esc(purchase.id)}">我已付款，检查到账</button>`,
      );
    }
    if (action === 'appraisal-purchase-refresh') {
      const purchase = await change('/api/business/appraisal-purchase-refresh', { purchaseId: target.dataset.id });
      const remaining = purchase.data.credits?.remainingTimes;
      toast(
        purchase.data.status === 'granted'
          ? `购买已到账，当前可用 ${remaining ?? '—'} 次`
          : purchase.data.status === 'fulfillment_pending'
            ? '已付款，正在等待次数发放'
            : '尚未确认付款，请完成支付后再检查',
      );
    }
    if (action === 'business-refresh') {
      await change('/api/business/refresh', { kind: target.dataset.kind, localId: target.dataset.id });
      toast('已保存本次查询结果');
    }
    if (action === 'tracking-select') {
      const list = records(model).filter(({ item }) => collected(item));
      dialog(
        '选择需要追踪的收藏',
        list.length
          ? list.map(({ item, task }) => link(name(item), 'coin', task.manifest.task_key, item.local_id, 'button')).join(' ')
          : '<p>当前没有已验证的本人收藏。完成收藏后可从档案开启追踪。</p>',
      );
    }
    if (action === 'tracking-create') {
      const plan = await api.request('/api/business/tracking-plan', taskBody({ localId: currentItem(model).local_id }));
      model.pendingPlan = plan;
      showTrackingPlan(plan);
    }
    if (action === 'tracking-recheck-slots') {
      if (!model.pendingPlan) throw new Error('请返回藏品档案重新检查追踪位');
      const plan = await api.request('/api/business/tracking-plan', taskBody({ localId: currentItem(model).local_id }));
      model.pendingPlan = plan;
      showTrackingPlan(plan);
    }
    if (action === 'tracking-purchase-guide') {
      if (!model.pendingPlan) throw new Error('请返回藏品档案重新检查追踪位');
      const options = await api.request('/api/business/tracking-purchase-options', { planId: model.pendingPlan.id });
      model.trackingPurchaseOptions = options;
      const duration = (product) => {
        const unit = { month: '个月', year: '年' }[product.durationUnit] || '';
        return unit ? `${product.durationCount || 1}${unit}` : '';
      };
      dialog(
        '选择追踪位商品',
        `<p>${esc(options.title)} · 当前可用 ${esc(options.eligibility?.availableSlots ?? '—')} 个追踪位</p><p class="muted">商品与价格来自服务器目录。付款和追踪位发放分别核验。</p><div class="dialog-list">${options.products.map((product) => `<div><strong>${esc(`${product.times} 个追踪位${duration(product) ? ` · ${duration(product)}` : ''}`)}</strong><span>${esc(purchasePrice(product))}</span><button class="button small primary" data-action="tracking-purchase-preview" data-sku="${esc(product.sku)}">选择</button></div>`).join('')}</div>`,
      );
    }
    if (action === 'tracking-purchase-preview') {
      if (!model.pendingPlan) throw new Error('请返回藏品档案重新检查追踪位');
      const plan = await api.request('/api/business/tracking-purchase-plan', {
        planId: model.pendingPlan.id,
        sku: target.dataset.sku,
      });
      model.pendingTrackingPurchase = plan;
      const product = plan.product;
      const period = product.durationUnit === 'month' ? `${product.durationCount || 1}个月` : product.durationUnit === 'year' ? `${product.durationCount || 1}年` : '';
      dialog(
        '确认购买追踪位',
        `<p>${esc(plan.title)}</p><p>购买 ${esc(product.times)} 个追踪位${period ? ` · ${esc(period)}` : ''} · ${esc(purchasePrice(product))}</p><p class="muted">确认后会创建订单并打开安全支付页。付款后请回到工作台检查追踪位到账，再单独确认开启追踪。</p>`,
        button('确认购买并前往支付', 'tracking-purchase-checkout', 'primary'),
      );
    }
    if (action === 'tracking-purchase-checkout') {
      const plan = model.pendingTrackingPurchase;
      if (!plan) throw new Error('请重新选择追踪位商品');
      const result = await api.request('/api/business/tracking-purchase-checkout', {
        planId: plan.id,
        planHash: plan.hash,
        commandId: crypto.randomUUID(),
      });
      await refresh(true);
      const purchase = result.purchase;
      dialog(
        result.checkoutUrl ? '订单已创建，完成支付' : '订单已创建',
        `<p>${esc(purchase?.data?.title || plan.title)}</p><p>订单已保存。付款完成后返回工作台核验支付状态和追踪位发放。</p>${result.checkoutUrl ? `<a class="button primary" href="${esc(result.checkoutUrl)}" target="_blank" rel="noopener">前往安全支付</a>` : '<p class="muted">支付页暂不可用。请在“追踪”页继续原订单，避免重复创建。</p>'}`,
        purchase
          ? `${!result.checkoutUrl ? `<button class="button" data-action="tracking-purchase-resume" data-id="${esc(purchase.id)}">继续支付</button>` : ''}<button class="button primary" data-action="tracking-purchase-refresh" data-id="${esc(purchase.id)}">我已付款，检查到账</button>`
          : '',
      );
    }
    if (action === 'tracking-purchase-resume') {
      const result = await api.request('/api/business/tracking-purchase-resume', { purchaseId: target.dataset.id });
      const purchase = result.purchase;
      dialog(
        '继续完成支付',
        `<p>${esc(purchase?.data?.title || '追踪位订单')}</p><p>正在恢复已有订单的支付页面，不会创建新订单。付款后请回来检查到账。</p><a class="button primary" href="${esc(result.checkoutUrl)}" target="_blank" rel="noopener">前往安全支付</a>`,
        `<button class="button" data-action="tracking-purchase-refresh" data-id="${esc(purchase.id)}">我已付款，检查到账</button>`,
      );
    }
    if (action === 'tracking-purchase-refresh') {
      const purchase = await change('/api/business/tracking-purchase-refresh', { purchaseId: target.dataset.id });
      const data = purchase.data;
      const available = data.eligibility?.availableSlots;
      const message = data.status === 'granted'
        ? `追踪位已到账，当前可用 ${available ?? '—'} 个。还需返回藏品确认开启追踪。`
        : data.status === 'fulfillment_pending'
          ? '已确认付款，服务正在发放追踪位；稍后可再次检查。'
          : '服务尚未确认付款，请完成支付后再检查。';
      dialog(
        data.status === 'granted' ? '追踪位已到账' : '订单核验结果',
        `<p>${esc(message)}</p>${remoteFields(data.detail || {})}`,
        data.status === 'granted'
          ? `<button class="button primary" data-action="tracking-purchase-continue" data-id="${esc(purchase.id)}">返回藏品，继续开启追踪</button>`
          : '',
      );
    }
    if (action === 'tracking-purchase-continue') {
      const purchase = model.workspace.trackingPurchases.find((entry) => entry.id === target.dataset.id);
      if (!purchase) throw new Error('未找到追踪位订单');
      go('coin', purchase.data.taskKey, purchase.data.localId);
    }
    if (action === 'tracking-run') {
      try {
        await change('/api/business/tracking-start', { planId: model.pendingPlan.id, planHash: model.pendingPlan.hash, commandId: crypto.randomUUID() });
      } catch (error) {
        // 预览和确认之间追踪位可能被其他操作用掉；重新读取后直接展示购买入口。
        if (error.code === 'tracking_slots_empty') {
          const plan = await api.request('/api/business/tracking-plan', taskBody({ localId: currentItem(model).local_id }));
          model.pendingPlan = plan;
          showTrackingPlan(plan);
          return;
        }
        throw error;
      }
      go('tracking');
    }
    if (action === 'operation-inspect') {
      await change('/api/operations/inspect', { operationId: target.dataset.id });
      toast('已保存查询结果，可请 Agent 协助归档恢复');
    }
    if (action === 'operation-reconcile-identification') {
      const result = await change('/api/operations/reconcile-identification', { operationId: target.dataset.id });
      toast(result?.data?.message || '已发起远端只读核验；完成后会自动归档唯一精确匹配并恢复原记录');
    }
    if (action === 'operation-resume') {
      await change('/api/operations/resume', { operationId: target.dataset.id });
      toast('正在核验已归档结果并继续未完成项；未核实的请求不会重发');
    }
    if (action === 'task-health-refresh') {
      await refresh(true);
      toast('已重新执行任务完整性检查');
    }
    if (action === 'backup') {
      const result = await api.request('/api/backup', {});
      dialog('备份已保存', `<p>备份包含数据库快照与任务原件。</p><p>${esc(result.path)}</p>`);
    }
  } catch (error) {
    showError(error);
  } finally {
    busy = false;
    if (target.isConnected) target.disabled = false;
  }
});

document.addEventListener('input', (e) => {
  if (e.target.closest('#commerce-edit-form')) dirty = true;
  if (e.target.id === 'review-detail-note') {
    reviewDraft().note = e.target.value;
    dirty = true;
  }
  if (e.target.matches('[data-review-field]')) dirty = true;
  if (e.target.id === 'review-zoom-range')
    document.querySelectorAll('.rr-zoom-image img').forEach((img) => {
      img.style.width = e.target.value + '%';
      img.style.height = e.target.value + '%';
    });
  if (e.target.id === 'bulk-query') {
    selectionFor(model).query = e.target.value;
    drawBulk();
  }
  if (e.target.id === 'review-note' || e.target.id === 'edit-note-text') {
    draftChanged();
    const status = document.querySelector('#note-status');
    if (status) status.textContent = '尚未保存';
  }
  if (['appraisal-desc', 'appraiser-id'].includes(e.target.id)) draftChanged();
  if (e.target.id === 'task-name') model.importName = e.target.value;
  if (e.target.id === 'library-search') {
    const value = e.target.value,
      position = e.target.selectionStart;
    model.query = value;
    draw();
    const input = document.querySelector('#library-search');
    input.focus();
    input.setSelectionRange(position, position);
  }
  if (e.target.id === 'global-query') {
    const q = e.target.value.trim().toLowerCase();
    const result = document.querySelector('#global-results');
    result.innerHTML = q
      ? records(model)
          .filter(({ item }) => name(item).toLowerCase().includes(q))
          .map(({ item, task }) => link(name(item), 'coin', task.manifest.task_key, item.local_id, ''))
          .join('') +
        model.workspace.tasks
          .filter((t) => t.display_name.toLowerCase().includes(q))
          .map((t) => link(t.display_name, 'task', t.task_key, null, ''))
          .join('')
      : '';
  }
});
async function picked(files) {
  if ((model.route.page === 'inputs' || model.route.page === 'appraisal') && model.task) {
    try {
      await ingestFiles(files, model.task.manifest.task_key, model.task.manifest.revision);
      await refresh(true);
      toast(model.route.page === 'appraisal' ? '照片已归档，请在鉴定材料中选择对应面别' : '资料已归档');
    } catch (error) {
      await refresh(true);
      showError(error);
    }
  } else {
    model.files = [...model.files, ...files];
    draw();
  }
}
document.addEventListener('submit', (event) => {
  if (!event.target.matches('[data-commerce-form], #commerce-edit-form, #commerce-order-form')) return;
  event.preventDefault();
  const target = event.submitter || event.target;
  void dialogAction(target, () => commerce.submit(event.target));
});

// Remember user-expanded secondary groups across changing progress snapshots.
document.addEventListener('toggle', (event) => {
  const group = event.target;
  if (route().page === 'add' && group.isConnected && group.matches?.('details[data-add-group]')) add.setGroupOpen(group.dataset.addGroup, group.open);
}, true);

document.addEventListener('change', (e) => {
  if (e.target.matches('[data-add-select]')) {
    add.toggle(e.target.dataset.addSelect, e.target.dataset.id, e.target.checked);
    return;
  }
  if (e.target.matches('[data-add-files]')) {
    const work = add.upload([...e.target.files]);
    scrollAddStatus();
    void work.then(() => refresh(true)).catch((error) => {
      add.state.error = friendlyAddError(error);
      draw();
    });
    return;
  }
  if (e.target.matches('[data-add-supplement]')) {
    const file = e.target.files?.[0];
    const { id, addSupplement: side } = e.target.dataset;
    e.target.value = '';
    if (file) void add.supplement(id, side, file).then(() => refresh(true)).catch(() => {
      draw();
    }).finally(() => {
      [...document.querySelectorAll('[data-coin-id]')].find((card) => card.dataset.coinId === id)
        ?.querySelector('.add-photo-feedback, .add-editor-feedback, .add-editor-error')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    return;
  }
  if (e.target.matches('[data-add-side]')) {
    const file = e.target.files?.[0];
    if (file) void add.pick(e.target.dataset.addSide, file).catch((error) => {
      add.state.error = friendlyAddError(error);
      draw();
    });
    return;
  }
  if (e.target.matches('[data-commerce-upload]')) {
    void commerce.upload([...e.target.files], e.target).catch(showError);
    return;
  }
  if (e.target.matches('[data-review-check]')) {
    reviewDraft().checks = [...document.querySelectorAll('[data-review-check]:checked')].map((x) => x.dataset.reviewCheck);
    dirty = true;
  }
  if (['obverse-source', 'reverse-source'].includes(e.target.id)) { pairDirty = true; updatePairPreviews(); }
  if (e.target.id === 'bulk-filter') {
    selectionFor(model).filter = e.target.value;
    drawBulk();
  }
  if (e.target.matches('[data-bulk-id]')) {
    const selection = selectionFor(model),
      id = e.target.dataset.bulkId;
    if (e.target.checked && selection.ids.size >= 500) {
      e.target.checked = false;
      toast('每批最多 500 枚');
      return;
    }
    if (e.target.checked) selection.ids.add(id);
    else selection.ids.delete(id);
    drawBulk();
  }
  if (['appraisal-obverse', 'appraisal-reverse', 'appraisal-side'].includes(e.target.id)) draftChanged();
  if (e.target.id === 'appraiser-choice') {
    draftChanged();
    void refreshAppraisalCredits().catch(showError);
  }
  if (e.target.id === 'file-input') picked([...e.target.files]);
  if (e.target.id === 'appraisal-file-input') picked([...e.target.files]);
  if (e.target.id === 'bridge-host') drawBridge();
});
document.addEventListener('dragover', (e) => {
  if (e.target.closest('.dropzone')) e.preventDefault();
});
document.addEventListener('drop', (e) => {
  if (e.target.closest('[data-add-drop]')) {
    e.preventDefault();
    const work = add.upload([...e.dataTransfer.files]);
    scrollAddStatus();
    void work.then(() => refresh(true)).catch((error) => {
      add.state.error = friendlyAddError(error);
      draw();
    });
    return;
  }
  if (e.target.closest('.dropzone')) {
    e.preventDefault();
    picked([...e.dataTransfer.files]);
  }
});
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    document.querySelector('[data-action="search"]').click();
  }
});
window.addEventListener('hashchange', () => {
  if (dirty || pairDirty || add.photosDirty) {
    history.replaceState(null, '', href(model.route.page, model.route.task, model.route.item));
    toast(add.photosDirty ? '照片调整尚未保存，请先保存或取消' : '当前输入还未保存，请完成保存后切换');
    return;
  }
  if (model.route.page === 'library' && route().page !== 'library') model.collectionNotice = null;
  modal.close();
  bridge.close();
  draw();
  window.scrollTo(0, 0);
  main.focus({ preventScroll: true });
});
window.addEventListener('beforeunload', (e) => {
  if (dirty || pairDirty || add.photosDirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});

// 长轮询只刷新已提交状态。输入未保存时先保留草稿，不让聊天端事件覆盖文本框。
async function followEvents() {
  while (true) {
    try {
      const page = await api.request(`/api/events?after=${model.cursor}&wait=25`);
      model.cursor = page.cursor;
      if (page.events.length) {
        model.events = [...model.events, ...page.events].slice(-30);
        await refresh();
      } else if (deferredRefresh && !dirty && !pairDirty) await refresh();
    } catch (error) {
      document.querySelector('#connection-status').textContent = '连接中断，已保存数据仍保留';
      if (error.status === 401) return;
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
}
try {
  await api.connect();
  void refreshAccountProfile();
  await refresh(true);
  void followEvents();
} catch (error) {
  drawAccountProfile();
  main.innerHTML = `<div class="empty-state"><h1>工作空间暂未连接</h1><p>${esc(error.message)}</p><p>从业务 Skill 重新打开工作台即可恢复已保存的任务。</p></div>`;
  document.querySelector('#connection-status').textContent = '等待连接';
}

modal.addEventListener('cancel', () => {
  if (model.reviewEditing) {
    dirty = model.reviewEditing.priorDirty;
    model.reviewEditing = null;
  }
});
// 原生 dialog.close() 不移除表单 DOM，因此关闭时另行作废上传上下文。
modal.addEventListener('close', () => {
  // close 事件异步到达；已经打开下一个对话框时不能清空新编辑器。
  if (!modal.open) commerce.cancelEdit();
});
