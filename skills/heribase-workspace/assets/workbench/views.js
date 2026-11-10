import { reviewContent, reviewDecision, unresolvedReview } from './review.js';
import { media } from './api.js';
import { selectionFor, filteredItems, eligibleForIdentification, identificationSelection } from './bulk.js';

export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const titles = {
  add: '添加钱币',
  home: '首页',
  tasks: '整理任务',
  import: '新建与导入',
  task: '任务概览',
  inputs: '输入资料',
  pairing: '配对审核',
  identify: '识别结果',
  review: '结果审核',
  confirm: '收藏确认',
  operations: '执行记录',
  library: '藏品库',
  coin: '藏品档案',
  appraisals: '真人鉴定',
  appraisal: '申请鉴定',
  report: '鉴定报告',
  tracking: '追踪',
  reports: '资料与报告',
  settings: '设置与备份',
  market: '交易市场',
  buying: '我的购买',
  selling: '商家管理',
  membership: '会员订阅',
};
export const href = (page, task, item) => {
  const q = new URLSearchParams();
  if (task) q.set('task', task);
  if (item) q.set('item', item);
  return `#${page}${q.size ? '?' + q : ''}`;
};
// 按用户浏览器的本地日期生成新任务默认名称，避免 UTC 日期与用户当前日期错位。
const defaultTaskName = () => {
  const now = new Date();
  const date = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`;
  return `${date}-钱币整理`;
};
export const link = (label, page, task, item, style = 'button') => `<a class="${style}" href="${esc(href(page, task, item))}">${esc(label)}</a>`;
export const button = (label, action, style = '', disabled = false) =>
  `<button class="button ${style}" data-action="${action}" ${disabled ? 'disabled' : ''}>${esc(label)}</button>`;
export const tag = (label, tone = 'neutral') => `<span class="tag ${tone}">${esc(label)}</span>`;
// CLI 的 remainingTimes 在不同服务版本中可能是 number 或数字字符串。空值代表
// 尚未读取，不能误判为 0；只有明确的零额度才显示购买入口。
export const hasNoAppraisalCredits = (value) =>
  (typeof value === 'number' && value === 0) || (typeof value === 'string' && value.trim() !== '' && Number(value) === 0);
export const appraisalPurchaseControl = (selected, credits, purchases = []) => {
  if (!selected) return '';
  // 购买入口只取决于当前服务的可用次数。已有订单另行展示，不能让历史订单
  // 或尚未到账的订单遮住零次数时的购买按钮；点击购买仍先选商品并确认。
  const purchaseEntry = hasNoAppraisalCredits(credits)
    ? `<div style="margin-top:10px">${button('购买鉴定次数', 'appraisal-purchase-guide', 'small primary')}<p class="muted" style="font-size:11px;margin:8px 0 0">暂时没有可用次数。也可在 HeriBase 应用购买当前服务的鉴定次数，完成后返回这里点击“刷新服务与次数”。</p></div>`
    : '';
  const purchase = purchases.find(
    (entry) =>
      entry.data.service?.appraiserType === selected.appraiserType &&
      entry.data.service?.appraiserId === selected.appraiserId &&
      entry.data.status !== 'granted',
  );
  if (purchase) {
    return `${purchaseEntry}<div style="margin-top:10px"><p class="muted" style="font-size:11px">已有订单：${esc({ awaiting_payment: '等待付款', fulfillment_pending: '已付款，等待次数发放' }[purchase.data.status] || purchase.data.status)}</p>${purchase.data.status === 'awaiting_payment' ? `<button class="button small" data-action="appraisal-purchase-resume" data-id="${esc(purchase.id)}">继续支付</button>` : ''}<button class="button small" data-action="appraisal-purchase-refresh" data-id="${esc(purchase.id)}">我已付款，检查到账</button></div>`;
  }
  return purchaseEntry;
};
// 未完成订单在刷新或切换页面后仍可恢复；不能要求用户从创建订单的弹窗找回。
export const trackingPurchaseCards = (purchases = []) => purchases
  .map((entry) => {
    const data = entry.data || {};
    const status = {
      awaiting_payment: '追踪位订单待付款',
      fulfillment_pending: '已付款，等待追踪位发放',
      granted: '追踪位已到账，可继续开启',
    }[data.status] || '追踪位订单待核验';
    const times = data.product?.times || data.product?.entitlementSpec?.times;
    const controls = [
      data.status === 'awaiting_payment'
        ? `<button class="button small" data-action="tracking-purchase-resume" data-id="${esc(entry.id)}">继续支付</button>`
        : '',
      data.status !== 'granted'
        ? `<button class="button small" data-action="tracking-purchase-refresh" data-id="${esc(entry.id)}">检查订单与追踪位</button>`
        : `<button class="button small primary" data-action="tracking-purchase-continue" data-id="${esc(entry.id)}">继续开启追踪</button>`,
      link('返回藏品', 'coin', data.taskKey, data.localId, 'button quiet'),
    ].filter(Boolean).join(' ');
    return `<article class="operation-card"><div class="inline" style="justify-content:space-between"><strong>${esc(data.title || '追踪位购买')}</strong>${tag(status, data.status === 'awaiting_payment' ? 'amber' : 'neutral')}</div><p>购买 ${esc(times || '—')} 个追踪位 · 订单状态以服务端核验为准。</p><div class="actions">${controls}</div></article>`;
  }).join('');
const section = (title, extra = '') => `<div class="section-head"><h2>${esc(title)}</h2>${extra}</div>`;
const head = (kicker, title, description, actions = '') =>
  `<div class="page-head"><div><div class="eyebrow">${esc(kicker)}</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div><div class="actions">${actions}</div></div>`;
export const empty = (title, text, action = '') => `<div class="empty-state"><h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div>`;
const field = (item, ...names) => {
  for (const name of names) {
    const v = item?.resolved_fields?.[name];
    if (v?.value !== undefined && v.value !== null) return v.value;
    if (v !== undefined && v !== null && typeof v !== 'object') return v;
  }
  return '';
};
export const name = (item) => item?.recognitionResult?.title || field(item, 'title', 'name') || item?.local_id?.split(':').at(-1) || '未选择藏品';
export const collected = (item) => item?.collection_projection?.status === 'succeeded' && !!item.collection_projection.collection_uri;
export const identified = (item) => item?.active_identification?.status === 'succeeded';
export const decision = (item) =>
  item?.review_projection?.stale
    ? '决定已过期'
    : { collect: '待收藏', hold: '暂留复核', need_photo: '需要补图', exclude: '已排除' }[reviewDecision(item)] || '尚未决定';
export const currentItem = (m) => m.task?.items.find((item) => item.local_id === m.route.item) || m.task?.items[0];
export const records = (m) => m.allTasks.flatMap((task) => task.items.map((item) => ({ item, task })));
const taskKey = (m) => m.task?.manifest.task_key;
const stateName = (value) =>
  ({
    received: '待整理',
    indexing: '资料整理',
    grouping: '照片配对',
    awaiting_precheck: '待确认配对',
    identification_pending: '待识别确认',
    identifying: '识别中',
    identification_review: '结果审核',
    awaiting_collection_confirmation: '待收藏确认',
    collecting: '收藏执行中',
    completed: '已完成',
    completed_with_exceptions: '部分完成',
    cancelled: '已取消',
    data_inconsistent: '数据待核验',
  })[value] ||
  value ||
  '待整理';
export const itemSources = (task, item) => {
  if (!item) return [];
  const assignments = item.organization?.source_assignment;
  return item.evidence
    .map((e) => ({
      source: task.sources.find((s) => s.source_id === e.source_id),
      role: assignments?.find((a) => a.source_id === e.source_id)?.role || e.role,
    }))
    .filter((e) => e.source);
};
export const picture = (task, item, role) => {
  const list = itemSources(task, item);
  const source = list.find((e) => e.role === role)?.source || (role === 'obverse' ? list[0]?.source : null);
  return source ? media(task.manifest.task_key, source.source_id) : null;
};
// The preview and selector must derive their defaults from the same exact source IDs.
export const pairingSources = (task, item) => {
  const list = itemSources(task, item);
  const obverse = list.find((entry) => entry.role === 'obverse')?.source.source_id;
  const reverse = list.find((entry) => entry.role === 'reverse')?.source.source_id;
  const unknown = list.filter((entry) => entry.role === 'unknown' || !entry.role).map((entry) => entry.source.source_id);
  const front = obverse || unknown.find((id) => id !== reverse);
  return { obverse: front || '', reverse: reverse || unknown.find((id) => id !== front) || '' };
};
const photo = (task, item, role, label, selected) => {
  const url = selected === undefined ? picture(task, item, role) : selected ? media(task.manifest.task_key, selected) : null;
  const data = selected === undefined ? '' : ` data-pair-photo="${role}"`;
  return url
    ? `<figure class="photo"${data}><button data-action="zoom" data-url="${esc(url)}" aria-label="放大${label}"><img src="${esc(url)}" alt="${label}"></button><figcaption><span>${label}</span><span>查看原图 ↗</span></figcaption></figure>`
    : `<figure class="photo empty"${data}><b>＋</b><span>尚未指定${label}</span><small>在配对页选择对应资料</small></figure>`;
};
const thumb = (task, item) => {
  const url = picture(task, item, 'obverse');
  return url ? `<img class="thumb" src="${esc(url)}" alt="">` : '<span class="file-icon">币</span>';
};
const stages = (m) =>
  `<div class="stagebar" aria-label="任务阶段">${[
    ['task', '概览'],
    ['inputs', '输入资料'],
    ['pairing', '整理配对'],
    ['identify', '识别结果'],
    ['review', '结果审核'],
    ['confirm', '收藏确认'],
    ['operations', '执行记录'],
  ]
    .map(
      ([id, title], i) =>
        `<a class="stage ${m.route.page === id ? 'active' : ''}" href="${esc(href(id, taskKey(m), m.route.item))}"><span>0${i + 1}</span>${title}</a>`,
    )
    .join('')}</div>`;
const taskHead = (m, actions = '') =>
  `<div class="breadcrumb">${link('整理任务', 'tasks', null, null, '')} / ${esc(m.task.manifest.display_name)}</div>${head('COLLECTION TASK', m.task.manifest.display_name, `${m.task.items.length} 枚候选 · ${m.task.sources.length} 份资料 · 审核决定与任务进度已持久化`, actions || button('与 Agent 协作', 'bridge', 'quiet'))}${stages(m)}`;
export function bulkControls(m) {
  const selected = selectionFor(m),
    visible = filteredItems(m);
  const identifyIds = m.route.page === 'identify' ? identificationSelection(m) : [];
  const outside = [...selected.ids].filter((id) => !visible.some((i) => i.local_id === id)).length;
  const filters =
    m.route.page === 'pairing'
      ? [
          ['all', '全部'],
          ['issues', '待处理 / 异常'],
          ['confirmed', '已确认'],
          ['single_side', '待补图'],
          ['excluded', '已排除'],
        ]
      : m.route.page === 'identify'
        ? [
            ['all', '全部'],
            ['ready', '可识别'],
            ['issues', '未就绪 / 已识别'],
          ]
        : [
            ['all', '全部'],
            ['pending', '尚未决定 / 已过期'],
            ['issues', '识别异常 / 待复核'],
            ['collect', '待收藏'],
            ['hold', '暂留复核'],
            ['need_photo', '待补图'],
            ['exclude', '已排除'],
          ];
  const actions =
    m.route.page === 'pairing'
      ? [
          ['confirm_pair', '批量确认配对'],
          ['need_photo', '批量待补图'],
          ['exclude', '批量排除'],
        ]
      : [
          ['collect', '批量待收藏'],
          ['hold', '批量暂留复核'],
          ['need_photo', '批量待补图'],
          ['exclude', '批量排除'],
        ];
  return `<div class="bulk-filters"><label>筛选<select id="bulk-filter">${filters.map(([v, l]) => `<option value="${v}" ${selected.filter === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label><label>搜索<input id="bulk-query" value="${esc(selected.query)}" placeholder="名称或候选编号" type="search"></label>${button('全选筛选结果', 'bulk-select', 'small quiet')}${button('清空选择', 'bulk-clear', 'small quiet')}${button('批量记录', 'bulk-history', 'small quiet')}</div>
  <div class="bulk-actionbar"><span>筛选结果 ${visible.length} 枚 · <strong>已选 ${selected.ids.size} 枚</strong>${outside ? `（筛选外 ${outside} 枚仍在选择范围）` : ''}</span><div class="actions">${m.route.page === 'identify' ? button(selected.ids.size ? `检查所选识别范围（${selected.ids.size} 枚）` : identifyIds.length ? `选择 ${identifyIds.length} 枚并检查范围` : '暂无可识别项', 'identify-preview', 'primary', !identifyIds.length || identifyIds.length > 500) : actions.map(([v, l]) => `<button class="button small ${v === 'exclude' ? 'quiet' : 'primary'}" data-action="bulk-preview" data-value="${v}" ${!selected.ids.size ? 'disabled' : ''}>${l}</button>`).join('')}</div></div>`;
}
export const queue = (m) => {
  const s = selectionFor(m),
    items = filteredItems(m);
  return `<aside class="queue"><div class="queue-title">勾选加入批量范围 · 点击查看详情</div>${items.map((item) => `<div class="bulk-queue-row"><input type="checkbox" data-bulk-id="${esc(item.local_id)}" aria-label="选择${esc(name(item))}" ${s.ids.has(item.local_id) ? 'checked' : ''}><a class="queue-item ${currentItem(m)?.local_id === item.local_id ? 'active' : ''}" href="${esc(href(m.route.page, taskKey(m), item.local_id))}">${thumb(m.task, item)}<span><strong>${esc(name(item))}</strong><small>${esc(m.route.page === 'pairing' ? { confirmed: '配对已确认', single_side: '待补图', excluded: '已排除' }[item.organization?.pairing_state] || '待确认配对' : collected(item) ? '已收藏' : decision(item))}</small></span></a></div>`).join('') || '<p class="muted pad">没有匹配候选；清空筛选可查看全部。</p>'}</aside>`;
};
export function identifyRows(m) {
  const s = selectionFor(m);
  return (
    filteredItems(m)
      .map(
        (item) =>
          `<tr><td><input type="checkbox" data-bulk-id="${esc(item.local_id)}" aria-label="选择${esc(name(item))}" ${s.ids.has(item.local_id) ? 'checked' : ''} ${eligibleForIdentification(item) ? '' : 'disabled'}></td><td>${esc(name(item))}${name(item) !== item.item_key ? `<small class="muted" style="display:block">${esc(item.item_key)}</small>` : ''}</td><td>${tag(eligibleForIdentification(item) ? '可以识别' : identified(item) ? '已识别' : '资料或决定待核对', eligibleForIdentification(item) ? 'green' : 'amber')}</td><td>${esc(decision(item))}</td><td>${link('查看候选', 'pairing', taskKey(m), item.local_id, 'link')}</td></tr>`,
      )
      .join('') || '<tr><td colspan="5">没有符合筛选条件的候选。</td></tr>'
  );
}
const rows = (entries, action = '查看档案') =>
  entries
    .map(
      ({ item, task }) =>
        `<tr><td><a class="coin-cell" href="${esc(href('coin', task.manifest.task_key, item.local_id))}">${thumb(task, item)}<span><strong>${esc(name(item))}</strong><small>${esc(field(item, 'year', 'years') || '年份待确认')}</small></span></a></td><td>${tag(identified(item) ? '已识别' : item.active_identification?.status === 'stale' ? '识别已过期' : '未识别', identified(item) ? 'green' : 'amber')}</td><td>${tag(collected(item) ? '已收藏' : decision(item), collected(item) ? 'green' : 'neutral')}</td><td>${link(action, 'coin', task.manifest.task_key, item.local_id, 'link')}</td></tr>`,
    )
    .join('');
const taskRequired = () => empty('先选择一项整理任务', '从已有任务继续，或导入新的照片和清单。', link('查看整理任务', 'tasks'));

function home(m) {
  const list = records(m),
    pending = list.filter(({ item }) => identified(item) && (!item.review_projection?.decision || item.review_projection.stale)).length;
  const toCollect = list.filter(
    ({ item }) => identified(item) && !collected(item) && item.review_projection?.decision === 'collect' && !item.review_projection.stale,
  ).length;
  const incomplete = list.filter(({ item }) => item.evidence.length < 2 || item.organization?.pairing_state === 'single_side').length;
  const recent = m.allTasks[0],
    selected = recent?.items[0],
    host = m.workspace.hosts[0];
  return `${head('我的工作空间', '让每一枚收藏，都有来处。', '接着上次的进度，把资料、判断和收藏放在一起。', link('＋ 导入新的资料', 'import', null, null, 'button gold'))}
    <div class="overview-strip">${[
      [pending, '等待审核', 'review'],
      [toCollect, '等待收藏确认', 'confirm'],
      [incomplete, '需要补图', 'pairing'],
      [(m.workspace.operations || []).filter((o) => o.data.status === 'reconcile_required').length, '需要核验', 'operations'],
    ]
      .map(
        ([n, label, page]) =>
          `<a href="${esc(href(page, recent?.manifest.task_key))}"><strong>${n}</strong><span>${label}<br>来自已保存的任务</span><b class="arrow">↗</b></a>`,
      )
      .join('')}</div>
    <div class="two-col"><div><article class="continue-card"><div class="continue-content"><div class="eyebrow">CONTINUE WHERE YOU LEFT OFF</div><h2>${esc(recent?.manifest.display_name || '从第一份资料开始')}</h2><p>${recent ? `${recent.items.length} 枚候选，${recent.sources.length} 份资料。<br>每一步决定都可以保存后再回来。` : '导入钱币照片和清单，建立可持续整理的收藏档案。'}</p>${link(recent ? '继续整理 →' : '创建整理任务 →', recent ? 'task' : 'import', recent?.manifest.task_key, null, 'button')}</div><div class="continue-art">${selected && picture(recent, selected, 'obverse') ? `<img src="${esc(picture(recent, selected, 'obverse'))}" alt="最近整理的钱币">${picture(recent, selected, 'reverse') ? `<img src="${esc(picture(recent, selected, 'reverse'))}" alt="另一面">` : ''}` : '<div class="workspace-emblem">H</div>'}</div></article>
    ${section('需要你处理', link('查看全部任务 →', 'tasks', null, null, 'link'))}${
      m.workspace.tasks.length
        ? m.workspace.tasks
            .slice(0, 5)
            .map(
              (task, i) =>
                `<div class="todo-row"><div class="todo-mark">${String(i + 1).padStart(2, '0')}</div><div class="grow"><strong>${esc(task.display_name)}</strong><p>${esc(stateName(task.state))} · ${task.statistics?.items || 0} 枚候选</p></div>${link(task.health.ok ? '继续处理' : '查看状态', 'task', task.task_key, null, 'button small')}</div>`,
            )
            .join('')
        : empty('还没有待处理任务', '导入后，待配对、待审核和待确认事项会出现在这里。')
    }
    ${section('最近变化')}<div class="panel pad">${
      m.events
        .slice(-4)
        .reverse()
        .map(
          (event) =>
            `<div class="activity">${esc({ 'task.created': '建立了整理任务', 'task.updated': '任务资料或决定已更新', 'entity.updated': '本地记录已保存', 'command.replied': 'Agent 已回复请求', 'host.bound': '宿主会话已连接' }[event.type] || '工作空间状态已更新')}<small>${esc(event.actor.startsWith('user:') ? '网页操作' : event.actor.startsWith('agent:') || event.actor.startsWith('host:') ? 'Agent 协作' : '工作空间')} · ${esc(new Date(event.createdAt).toLocaleString())}</small></div>`,
        )
        .join('') || '<p class="muted">这里会记录你的整理与协作进展。</p>'
    }</div></div>
    <aside><div>${section('协作状态', tag(host?.connected ? '宿主近期在线' : '等待宿主连接', host?.connected ? 'green' : 'neutral'))}<div class="panel pad"><div class="eyebrow">HOST AGENT</div><h3>${esc(host?.host || '在聊天中连接工作空间')}</h3><p class="muted" style="font-size:12px;margin:10px 0 18px">${host ? '请求会保留到宿主取件。已接收与业务完成分别记录。' : '从业务 Skill 进入时绑定当前会话，之后可以在网页与聊天间继续。'}</p>${button('查看协作动态 ↗', 'bridge', 'small quiet')}</div></div><div>${section('收藏概况')}<div class="summary-grid"><a href="#library"><small>本地藏品记录</small><strong>${list.length}</strong></a><a href="#library"><small>已收藏</small><strong>${list.filter(({ item }) => collected(item)).length}</strong></a><a href="#appraisals"><small>鉴定记录</small><strong>${m.workspace.appraisals.length}</strong></a><a href="#tracking"><small>追踪记录</small><strong>${m.workspace.tracking.length}</strong></a></div></div></aside></div>`;
}
function tasks(m) {
  return `${head('TASKS', '整理任务', '每次整理都有独立进度。任务结束后，资料和藏品继续保留。', link('＋ 新建任务', 'import', null, null, 'button gold'))}${m.workspace.tasks.length ? `<div class="table-wrap"><table><thead><tr><th>整理任务</th><th>当前阶段</th><th>资料与进度</th><th></th></tr></thead><tbody>${m.workspace.tasks.map((t) => `<tr><td><strong>${esc(t.display_name)}</strong><small>${esc(new Date(t.updated_at || Date.now()).toLocaleString())}</small></td><td>${tag(t.health.ok ? stateName(t.state) : '数据待核验', t.health.ok ? 'neutral' : 'amber')}</td><td>${t.statistics?.items || 0} 枚候选 · ${t.statistics?.sources || 0} 份资料</td><td>${link('打开任务 →', 'task', t.task_key, null, 'button small')}</td></tr>`).join('')}</tbody></table></div>` : empty('这里会保留每一次整理', '创建一项任务，将照片和来源归档在一起。', link('导入资料', 'import'))}`;
}
function importer(m) {
  const taskName = m.importName ?? defaultTaskName();
  return `${head('BATCH ADD', '批量上传与自动配对', '一次选择整批照片或表格，无需先分好正反面。原件先保存在本机，再由当前聊天中的 Agent 整批匹配。')}<div class="two-col"><div class="panel pad"><div class="form-grid"><label>任务名称<input id="task-name" maxlength="100" value="${esc(taskName)}"></label><div class="dropzone"><div class="drop-icon">↥</div><h2>把照片和清单放到这里</h2><p>图片、CSV、XLSX、PDF 或 TXT · 单个文件不超过 20 MiB<br>文件会复制到本机任务目录，保留原始文件。</p><input id="file-input" type="file" multiple accept="image/*,.csv,.xlsx,.pdf,.txt" hidden>${button('选择多张照片或表格', 'pick-files', 'primary')}</div><div id="selected-files">${(m.files || []).map((f) => `<div class="file-row"><span class="file-icon">${esc(f.name.split('.').at(-1).toUpperCase())}</span><span><strong>${esc(f.name)}</strong><small>${Math.ceil(f.size / 1024)} KB</small></span></div>`).join('') || '<p class="muted">尚未选择文件；也可以先建任务再追加。</p>'}</div></div></div><aside><div class="panel pad"><div class="eyebrow">WHAT HAPPENS NEXT</div><h2>整批匹配，只核对疑问。</h2><ol class="check-list"><li>一次上传整批照片及表格，保留原件</li><li>由 Agent 自动匹配同枚钱币的正反面</li><li>只核对缺图、重复或不确定的配对</li><li>确认选定范围后批量识别、审核及收藏</li></ol><p class="muted" style="font-size:12px">上传按钮仅保存资料，不会自动唤醒聊天。保存后在当前聊天中说“整理这批照片”，由 Agent 继续配对；线上识别与收藏仍需确认。</p></div></aside></div><div class="bottom-bar"><div id="import-status">已选 ${(m.files || []).length} 个文件</div>${button('批量保存到本机 →', 'create-task', 'primary')}</div>`;
}
function taskView(m) {
  if (!m.task) return taskRequired();
  const t = m.task;
  return `${taskHead(m)}<div class="task-stat"><div><small>候选实物</small><strong>${t.items.length}</strong></div><div><small>原始资料</small><strong>${t.sources.length}</strong></div><div><small>已识别</small><strong>${t.items.filter(identified).length}</strong></div><div><small>已收藏</small><strong>${t.items.filter(collected).length}</strong></div></div><div class="two-col"><div>${section('当前记录', link('进入配对 →', 'pairing', taskKey(m), null, 'link'))}${t.items.length ? `<div class="table-wrap"><table><thead><tr><th>硬币与来源</th><th>识别</th><th>当前决定</th><th></th></tr></thead><tbody>${rows(t.items.map((item) => ({ item, task: t })))}</tbody></table></div>` : empty('原始资料已保留，开始建立候选', '选择属于同一枚钱币的照片，再检查正反面。', link('整理配对', 'pairing', taskKey(m)))}${section('任务信息')}<div class="panel pad"><dl class="facts"><dt>建立时间</dt><dd>${esc(new Date(t.manifest.created_at).toLocaleString())}</dd><dt>当前阶段</dt><dd>${esc(stateName(t.manifest.state))}</dd><dt>数据完整性</dt><dd>已校验</dd></dl></div></div><aside><div class="panel pad"><h2>接着上次的工作</h2><p class="muted" style="font-size:12px;margin:12px 0 20px">可以随时返回任一阶段。照片或配对改变后，旧识别与未执行计划需要重新确认。</p>${link('进入结果审核', 'review', taskKey(m), null, 'button primary')}${section('与 Agent 协作')}${button('请 Agent 协助整理', 'bridge', 'quiet')}</div></aside></div>`;
}
function inputs(m) {
  if (!m.task) return taskRequired();
  return `${taskHead(m, `${button('追加资料', 'append-files', 'quiet')}${button('与 Agent 协作', 'bridge', 'quiet')}`)}<input type="file" id="file-input" multiple hidden><div class="equal-cols"><div class="panel pad"><h2>输入来源</h2>${m.task.sources.map((s) => `<div class="file-row"><span class="file-icon">${esc(s.kind === 'local_image' ? 'IMG' : s.kind === 'spreadsheet' ? '表格' : '文档')}</span><span><strong>${esc(s.origin.original_name || s.source_id)}</strong><small>${Math.ceil(s.byte_size / 1024)} KB · 已保存原件</small></span>${tag('已归档', 'green')}</div>`).join('') || '<p class="muted" style="margin-top:15px">尚未导入资料。</p>'}</div><div class="panel pad"><h2>来源与解释分别保留</h2><ul class="check-list"><li>原件归档后不会因源文件移动而丢失</li><li>来源字段与识别结论分别保存</li><li>待补图条目不会阻塞完整条目</li></ul><div class="note">表格里的购买金额与用户估值含义不同，不能直接互相覆盖。</div><div style="margin-top:18px">${link('查看配对 →', 'pairing', taskKey(m), null, 'button primary')}</div></div></div>`;
}
const pairingSuggestionRelations = {
  opposite_faces: '可能是同一枚钱币的正反面',
  same_face_duplicate: '可能是同面重复照片',
  same_coin_detail: '可能是同一枚钱币的细节图',
  uncertain: '关系尚不确定',
};
function pairingSuggestionPanel(task, item) {
  const suggestions = item.organization?.pairing_suggestions;
  if (!Array.isArray(suggestions) || !suggestions.length) return '';

  // 建议只提供全量比较的线索；配对、来源分配和识别资格仍由用户审核决定。
  const cards = suggestions.slice(0, 3).map((suggestion) => {
    const suggestionSources = suggestion.source_ids || [];
    const owners = [...new Set(suggestionSources.map((sourceId) =>
      task.items.find((entry) => entry.evidence?.some((evidence) => evidence.source_id === sourceId))?.local_id,
    ).filter(Boolean))];
    const otherOwnerId = owners.find((ownerId) => ownerId !== item.local_id);
    const otherOwner = task.items.find((entry) => entry.local_id === otherOwnerId);
    const mergeAllowed = otherOwner && otherOwner.status === 'active'
      && !['confirmed', 'excluded'].includes(otherOwner.organization?.pairing_state)
      && !otherOwner.active_identification
      && !otherOwner.collection_projection?.collection_uri
      && !item.active_identification
      && !item.collection_projection?.collection_uri
      && item.status === 'active'
      && !['confirmed', 'excluded'].includes(item.organization?.pairing_state)
      && suggestion.relation !== 'uncertain';
    const sources = suggestionSources.map((sourceId) => {
      const source = task.sources.find((entry) => entry.source_id === sourceId);
      const owner = task.items.find((entry) => entry.evidence?.some((evidence) => evidence.source_id === sourceId));
      const sourceName = source?.origin?.original_name || sourceId;
      const preview = source
        ? `<img src="${esc(media(task.manifest.task_key, sourceId))}" alt="${esc(sourceName)}">`
        : '<span class="pair-suggestion-missing">来源不可用</span>';
      const ownerLink = owner && owner.local_id !== item.local_id
        ? `<a href="${esc(href('pairing', task.manifest.task_key, owner.local_id))}">查看 ${esc(owner.item_key)}</a>`
        : '<span>当前候选</span>';
      return `<div class="pair-suggestion-source">${preview}<small>${esc(sourceName)}</small>${ownerLink}</div>`;
    }).join('');
    const confidence = Number.isFinite(suggestion.confidence)
      ? `${Math.round(suggestion.confidence * 100)}%（模型估计）`
      : '未评估';
    const signals = (values, label, className = '') => Array.isArray(values) && values.length
      ? `<p class="${className}"><strong>${label}：</strong>${values.map(esc).join('；')}</p>`
      : '';
    const mergeControl = mergeAllowed
      ? `<div class="actions" style="margin-top:12px"><button class="button small quiet" data-action="candidate-merge" data-target-local-id="${esc(item.local_id)}" data-source-local-id="${esc(otherOwner.local_id)}">将两条候选合并</button><span class="muted" style="font-size:11px">把另一条记录的全部图片并入当前候选，随后可指定正反面。</span></div>`
      : '';
    return `<article class="pair-suggestion"><div class="pair-suggestion-head"><strong>${esc(pairingSuggestionRelations[suggestion.relation] || '配对候选')}</strong>${tag(confidence, 'amber')}</div><div class="pair-suggestion-sources">${sources}</div><p>${esc(suggestion.rationale || '尚未记录比较理由')}</p>${signals(suggestion.supporting_signals, '支持线索')}${signals(suggestion.conflicting_signals, '冲突线索', 'pair-suggestion-conflict')}${mergeControl}</article>`;
  }).join('');
  return `<section class="pair-suggestions"><h2>跨图配对建议</h2><p class="muted">建议按整批图片比较得出，只帮助发现候选，不会自动配对或替你确认。</p>${cards}</section>`;
}
function pairing(m) {
  if (!m.task) return taskRequired();
  const item = currentItem(m);
  const suggestions = item ? pairingSuggestionPanel(m.task, item) : '';
  const selectedSources = pairingSources(m.task, item);
  return `${taskHead(m, `${button('从图片建立候选', 'candidate', 'primary')}${button('与 Agent 协作', 'bridge', 'quiet')}`)}<div id="bulk-controls">${bulkControls(m)}</div>${
    !item
      ? empty(
          '把属于同一枚的钱币照片放在一起',
          '先导入照片，再选择候选的图片来源；此时不会上传或识别。',
          button('选择图片建立候选', 'candidate', 'primary', !m.task.sources.some((s) => s.mime_type.startsWith('image/'))),
        )
      : `<div class="review-kicker"><span class="muted">配对决定与收藏决定分别保存</span>${tag(item.organization?.pairing_state === 'confirmed' ? '配对已确认' : '需要你核对', 'amber')}</div>${suggestions}<div class="review-layout">${queue(m)}<div class="evidence"><div class="evidence-top"><h2>照片与实物对应</h2>${button('交换正反面', 'swap', 'small quiet')}</div><div class="photos">${photo(m.task, item, 'obverse', '正面', selectedSources.obverse)}${photo(m.task, item, 'reverse', '反面', selectedSources.reverse)}</div>${section('指定方向')}<div class="equal-cols">${[
          ['obverse', '正面'],
          ['reverse', '反面'],
        ]
          .map(
            ([role, label]) =>
              `<label>${label}<select id="${role}-source"><option value="">尚未指定</option>${itemSources(m.task, item)
                .map(
                  (e, i) =>
                    `<option value="${esc(e.source.source_id)}" ${selectedSources[role] === e.source.source_id ? 'selected' : ''}>${esc(e.source.origin.original_name || e.source.source_id)}</option>`,
                )
                .join('')}</select></label>`,
          )
          .join('')}</div>${section('资料来源')}<p class="muted">${itemSources(m.task, item)
          .map((e) => esc(e.source.origin.original_name))
          .join(
            '、',
          )}</p></div><div class="decision-pane"><div class="eyebrow">PAIRING REVIEW</div><h2>这是同一枚钱币吗？</h2><p class="muted" style="font-size:12px">确认图片归属和方向，缺面时可以保存待补图。</p><div class="note">修改配对后，旧识别与未执行收藏计划将过期。已完成的收藏保留。</div>${button('确认这组配对', 'pair-confirm', 'primary')}<div class="actions" style="margin-top:10px">${button('需要补图', 'pair-photo', 'small quiet')}${button('排除此候选', 'pair-exclude', 'small quiet')}</div><div class="saved">决定直接保存到当前任务</div>${button('询问 Agent', 'bridge', 'quiet small')}</div></div><div class="bottom-bar"><div>完整配对后再进入识别</div>${link('检查识别范围 →', 'identify', taskKey(m), item.local_id, 'button primary')}</div>`
  }`;
}
function identify(m) {
  if (!m.task) return taskRequired();
  return `${taskHead(m)}<div class="note neutral">当前有 ${m.task.items.filter(eligibleForIdentification).length} 枚可以识别。点击“选择并检查范围”，或先勾选部分候选。检查范围不会上传图片；确认后才开始识别。${link('返回配对补全资料 →', 'pairing', taskKey(m), null, 'link')}</div><div id="bulk-controls">${bulkControls(m)}</div><div class="table-wrap"><table><thead><tr><th>选择</th><th>候选与来源</th><th>识别状态</th><th>用户决定</th><th></th></tr></thead><tbody id="bulk-identify-table">${identifyRows(m)}</tbody></table></div><div class="bottom-bar"><p>成功识别不代表已加入收藏。</p>${link('审核识别结果 →', 'review', taskKey(m), null, 'button primary')}</div>`;
}
function review(m) {
  if (!m.task) return taskRequired();
  if (!currentItem(m)) return `${taskHead(m)}${empty('暂无候选', '请先整理配对', link('整理配对', 'pairing', taskKey(m)))}`;
  return `${taskHead(m, link('查看收藏清单', 'confirm', taskKey(m), null, 'button primary'))}<div id="bulk-controls">${bulkControls(m)}</div>${reviewContent(m, { currentItem, name, decision, queue, href, link })}<div class="bottom-bar"><p>审核决定已持久化，正式收藏需确认范围。</p>${link('检查收藏清单 →', 'confirm', taskKey(m), null, 'button primary')}</div>`;
}

function confirm(m) {
  if (!m.task) return taskRequired();
  const plan = m.task.plan;
  const eligible = m.task.items.filter(
    (item) =>
      identified(item) && !collected(item) && item.review_projection?.decision === 'collect' && !item.review_projection.stale && !unresolvedReview(item),
  );
  return `${taskHead(m)}<div class="two-col"><div>${section('本次将新增的收藏', tag(`${eligible.length} 枚`))}${eligible.length ? `<div class="table-wrap"><table><thead><tr><th></th><th>收藏对象</th><th>状态</th></tr></thead><tbody>${eligible.map((item) => `<tr><td><input type="checkbox" data-confirm-id="${esc(item.local_id)}" checked aria-label="选择${esc(name(item))}"></td><td>${esc(name(item))}</td><td>${tag('等待确认', 'amber')}</td></tr>`).join('')}</tbody></table></div>` : empty('还没有待确认的收藏', '在审核页选择已识别的候选，并标记待收藏。', link('返回结果审核', 'review', taskKey(m)))}${section('确认与执行')}<div class="panel pad"><div class="activity">只授权你看过的这份清单<small>资料、识别或审核决定改变后，旧确认将失效。</small></div><div class="activity">逐条执行，保留实际结果<small>已完成项不重复提交，结果未知时先核验。</small></div></div></div><aside><div class="panel pad"><div class="eyebrow">REVIEW BEFORE EXECUTION</div><h2>本次操作摘要</h2><dl class="facts" style="margin:15px 0"><dt>操作</dt><dd>新增收藏</dd><dt>计划状态</dt><dd>${esc(plan ? { awaiting_confirmation: '等待确认', authorized: '已确认', stale: '旧计划已过期', consumed: '已执行' }[plan.status] || plan.status : '尚未生成')}</dd><dt>容量 / 费用</dt><dd>执行前查询；未返回项保持未知</dd></dl>${button('生成并检查收藏计划', 'collection-preview', 'primary', !eligible.length)}</div></aside></div>`;
}
// 全局收藏索引的关联键由 CLI 固定写入：batchId → 任务包目录，candidateId → item_key。
// 索引加快“已收藏”检索；任务包继续提供照片、审核和原始响应等完整档案。
const collectionKey = (taskKey, candidateId) => `${taskKey || ''}\u0000${candidateId || ''}`;
const candidateId = (item) => item?.item_key || item?.local_id?.split(':').at(-1) || '';
const libraryStatus = (item, isCollected = collected(item)) => {
  if (isCollected) return ['已收藏', 'green'];
  if (item.collection_projection?.status === 'cancelled') return ['已取消收藏', 'amber'];
  const review = item.review_projection || {};
  if (review.decision === 'collect' && !review.stale) return ['等待收藏确认', 'amber'];
  if (review.decision === 'hold' && !review.stale) return ['暂留复核', 'amber'];
  if (review.decision === 'need_photo' && !review.stale) return ['需要补图', 'amber'];
  if (review.decision === 'exclude' && !review.stale) return ['已排除', 'neutral'];
  if (identified(item)) return ['等待结果审核', 'amber'];
  if (item.organization?.pairing_state === 'confirmed') return ['等待识别', 'neutral'];
  return ['资料整理中', 'neutral'];
};

function libraryEntries(m) {
  const linked = new Map();
  const indexByKey = new Map();
  const seenUris = new Set();
  for (const record of m.workspace.collectionIndex || []) {
    // 同一远程收藏只保留最新一条索引，避免跨任务重复展示同一枚收藏。
    const uriKey = `${record.accountSubject || ''}\u0000${record.collectionUri || ''}`;
    if (!record.batchId || !record.candidateId || !record.collectionUri || seenUris.has(uriKey)) continue;
    seenUris.add(uriKey);
    indexByKey.set(collectionKey(record.batchId, record.candidateId), record);
  }
  const entries = records(m).map(({ item, task }) => {
    const key = collectionKey(task.manifest.task_key, candidateId(item));
    const indexed = indexByKey.get(key) || null;
    if (indexed) linked.set(key, true);
    // 旧任务可能早于 CLI 索引接入；保留任务包中已验证的收藏回执，不能因索引缺口隐藏藏品。
    return { item, task, indexed, isCollected: Boolean(indexed) || collected(item) };
  });
  // 索引比任务包更耐久：任务包被移走时，仍能看到一条可追溯的已收藏历史。
  for (const [key, indexed] of indexByKey) {
    if (!linked.has(key)) entries.push({ item: null, task: null, indexed, isCollected: true });
  }
  return entries;
}

const libraryEntryName = (entry) => (entry.item ? name(entry.item) : entry.indexed.title || entry.indexed.candidateId || '已收藏记录');
const libraryEntryYear = (entry) =>
  (entry.item && field(entry.item, 'year', 'years')) ||
  (identified(entry.item) && entry.item.recognitionResult?.year) ||
  entry.indexed?.year || '';
const libraryEntryTask = (entry) => entry.task?.manifest.display_name || entry.indexed?.batchId || '历史收藏索引';
const libraryEntryState = (entry) => (entry.item ? libraryStatus(entry.item, entry.isCollected) : ['已收藏', 'green']);
const libraryEntryLink = (entry) => (entry.item ? href('coin', entry.task.manifest.task_key, entry.item.local_id) : null);

function libraryRows(entries) {
  return entries
    .map((entry) => {
      const [label, tone] = libraryEntryState(entry);
      const title = libraryEntryName(entry);
      const year = libraryEntryYear(entry) || '年份待确认';
      const target = libraryEntryLink(entry);
      const titleCell = entry.item
        ? `<a class="coin-cell" href="${esc(target)}">${thumb(entry.task, entry.item)}<span><strong>${esc(title)}</strong><small>${esc(year)}</small></span></a>`
        : `<div class="coin-cell"><span class="file-icon">索引</span><span><strong>${esc(title)}</strong><small>${esc(year)} · 任务包待关联</small></span></div>`;
      return `<tr><td>${titleCell}</td><td>${entry.item ? tag(identified(entry.item) ? '已识别' : '未识别', identified(entry.item) ? 'green' : 'amber') : tag('任务包待关联', 'amber')}</td><td>${tag(label, tone)}</td><td>${target ? link('查看档案', 'coin', entry.task.manifest.task_key, entry.item.local_id, 'link') : `<small class="muted">${esc(libraryEntryTask(entry))}</small>`}</td></tr>`;
    })
    .join('');
}

function libraryCard(entry) {
  const [label, tone] = libraryEntryState(entry);
  const title = libraryEntryName(entry);
  const year = libraryEntryYear(entry) || '年份待确认';
  const target = libraryEntryLink(entry);
  const content = `<div class="coin-card-art">${tag(label, tone)}${entry.item && picture(entry.task, entry.item, 'obverse') ? `<img src="${esc(picture(entry.task, entry.item, 'obverse'))}" alt="${esc(title)}">` : '<span class="workspace-emblem">H</span>'}</div><div class="coin-card-body"><h3>${esc(title)}</h3><p>${esc(year)}</p><div class="coin-card-bottom"><span>${esc(libraryEntryTask(entry))}</span><span>${target ? '查看档案 ↗' : '任务包待关联'}</span></div></div>`;
  return target ? `<a class="coin-card" href="${esc(target)}">${content}</a>` : `<article class="coin-card">${content}</article>`;
}

function library(m) {
  const activeFilter = m.filter === 'collected' ? 'collected' : 'all';
  let list = libraryEntries(m);
  if (activeFilter === 'collected') list = list.filter((entry) => entry.isCollected);
  if (m.query) {
    const query = m.query.toLowerCase();
    list = list.filter((entry) => `${libraryEntryName(entry)} ${libraryEntryYear(entry)} ${libraryEntryTask(entry)}`.toLowerCase().includes(query));
  }
  const notice = m.collectionNotice;
  const completion = notice ? `<div class="add-complete" data-collection-notice role="status"><span>✓ 已加入收藏 ${Number(notice.count)} 枚</span>${notice.remaining ? link(`继续处理 ${Number(notice.remaining)} 枚 →`, 'add', notice.taskKey, null, 'link') : ''}</div>` : '';
  return `${head('', '我的收藏', '', link('＋ 添加钱币', 'add', null, null, 'button gold'))}${completion}<div class="toolbar"><div class="tabs">${[
    ['all', '全部档案'],
    ['collected', '已收藏'],
  ]
    .map(([value, label]) => `<button class="tab ${activeFilter === value ? 'active' : ''}" data-action="filter" data-value="${value}">${label}</button>`)
    .join(
      '',
    )}</div><div class="actions"><input class="search-field" id="library-search" value="${esc(m.query || '')}" aria-label="搜索藏品" placeholder="搜索名称、年份或任务">${button(m.libraryView === 'table' ? '图片视图' : '表格视图', 'library-view', 'small')}</div></div>${!list.length ? empty('这里暂时没有匹配记录', '调整筛选，或导入资料建立本地档案。') : m.libraryView === 'table' ? `<div class="table-wrap"><table><thead><tr><th>藏品</th><th>识别</th><th>当前状态</th><th></th></tr></thead><tbody>${libraryRows(list)}</tbody></table></div>` : `<div class="coin-grid">${list.map(libraryCard).join('')}</div>`}`;
}
function coin(m) {
  if (!m.task) return taskRequired();
  const item = currentItem(m);
  if (!item) return empty('未找到藏品', '从藏品库选择一枚记录。', link('返回藏品库', 'library'));
  const note = m.workspace.notes.find((n) => n.id === item.local_id);
  const [statusLabel, statusTone] = libraryStatus(item);
  const collectionProjection = item.collection_projection || {};
  const collectionActions = collectionProjection.collection_uri
    ? `<div class="actions">${collected(item) ? `${button('编辑收藏资料', 'collection-edit', 'primary')}${button('取消收藏', 'collection-cancel-plan', 'quiet')}` : ''}${button('收藏编辑历史', 'collection-history', 'quiet')}</div>`
    : '';
  return `<div class="breadcrumb">${link('藏品库', 'library', null, null, '')} / ${esc(name(item))}</div>${head('', '藏品详情', '', button('编辑本地备注', 'edit-note', 'quiet'))}<div class="detail-hero"><div class="photos">${photo(m.task, item, 'obverse', '正面')}${photo(m.task, item, 'reverse', '反面')}</div><div class="detail-copy">${tag(statusLabel, statusTone)}<h1>${esc(name(item))}</h1><dl class="facts"><dt>年份</dt><dd>${esc(field(item, 'year', 'years') || (identified(item) && item.recognitionResult?.year) || '待确认')}</dd><dt>资料来源</dt><dd>${esc(m.task.manifest.display_name)}</dd><dt>用户备注</dt><dd>${esc(note?.data.text || '暂无备注')}</dd></dl><div class="actions">${link('申请真人鉴定', 'appraisal', taskKey(m), item.local_id, 'button primary')}${button('加入价格追踪', 'tracking-create', 'quiet', !collected(item))}</div>${collectionActions}</div></div><div class="two-col"><div>${section('处理记录')}<div class="panel pad"><div class="timeline-row"><time>当前</time><div><strong>${esc(collected(item) ? '已收藏' : statusLabel)}</strong></div></div><div class="timeline-row"><time>识别</time><div><strong>${identified(item) ? '已识别' : '待识别'}</strong></div></div><div class="timeline-row"><time>来源</time><div><strong>${item.evidence.length} 张照片</strong><p>${esc(new Date(item.created_at).toLocaleString())}</p></div></div></div></div><aside>${section('相关资料')}<div class="panel pad">${link('回到整理任务 →', 'task', taskKey(m), item.local_id, 'link')}<hr class="divider">${link('查看原始资料 →', 'inputs', taskKey(m), item.local_id, 'link')}</div></aside></div>`;
}
function operationsView(m) {
  const taskKey = m.route.task;
  const taskScoped = Boolean(taskKey);
  const task = m.task || m.workspace.tasks?.find((entry) => entry.task_key === taskKey);
  const allOperations = m.workspace.operations || [];
  // 任务阶段入口已经携带 taskKey；只显示明确关联该任务的执行记录，避免猜测归属。
  const list = taskScoped ? allOperations.filter((op) => op.data.taskKey === taskKey) : allOperations;
  // CLI 查询日志暂未记录 taskKey，因此只在全局执行记录页展示，不能混入某项整理任务。
  const queryLogs = taskScoped ? [] : m.workspace.queryLogs || [];
  const state = (value) =>
    ({ completed: '已完成', reconcile_required: '结果待核验', partial_failed: '部分完成，可重试失败项', running: '执行中', failed: '已失败' })[value] || value;
  const results = (op) => {
    const outcomes = new Map((op.data.itemResults || []).map((item) => [item.localId, item]));
    const scope = Array.isArray(op.data.scope) ? op.data.scope : [];
    const rows = scope.length
      ? scope.map((item) => {
          const localId = item.localId || item.local_id;
          return { localId, ...(outcomes.get(localId) || {}) };
        })
      : op.data.itemResults || [];
    const statusText = (item) => {
      if (!outcomes.has(item.localId)) return '尚未执行';
      if (item.status === 'succeeded') return `已完成 · 第 ${item.attempts} 次`;
      if (item.status === 'recognition_failed') return `识别已完成，未识别出版本 · 第 ${item.attempts} 次`;
      if (item.status === 'reconcile_required') return `结果待核验 · 第 ${item.attempts} 次`;
      return `明确失败 · 已尝试 ${item.attempts} 次`;
    };
    return rows.length
      ? `<ul class="dialog-list">${rows.map((item) => `<li><span>${esc(item.localId)}</span><span>${esc(statusText(item))}${item.error ? `<small>${esc(item.error.remoteCode || item.error.code)} · ${esc(item.error.message)}</small>` : ''}</span></li>`).join('')}</ul>`
      : '';
  };
  const queryLogCards = queryLogs.length
    ? `<section class="panel pad" style="margin-top:24px"><div class="section-head"><h2>CLI 查询异常日志</h2>${tag(`${queryLogs.length} 条`, 'amber')}</div><p class="muted">仅记录只读查询失败；识别、收藏等写操作仍在上方执行记录中。</p>${queryLogs.map((entry) => `<article class="operation-card warning"><div class="inline" style="justify-content:space-between"><h3>${esc((entry.data.argv || []).join(' '))}</h3>${tag(entry.data.status || 'exception', 'amber')}</div><p>${esc(entry.data.error?.code || 'cli_query_exception')} · ${esc(entry.data.error?.message || 'CLI 查询失败')}</p><small class="muted">${esc(entry.data.queriedAt || entry.updatedAt || '')}${entry.data.cliTaskId ? ` · CLI 任务 ${esc(entry.data.cliTaskId)}` : ''}</small><details><summary>查看 CLI 原始返回</summary><pre>${esc(entry.data.stdout || 'CLI 未返回 stdout')}</pre></details></article>`).join('')}</section>`
    : '';
  const reconciliationHistory = (op) => {
    const attempts = op.data.remoteReconciliationAttempts || [];
    if (!attempts.length) return '';
    const labels = {
      running: '核验中', matched: '已匹配并归档', no_match: '没有精确匹配',
      ambiguous: '存在多个匹配', query_failed: '查询未完成',
    };
    return `<section class="panel pad" style="margin-top:12px"><h4>远端核验记录</h4>${attempts.map((attempt) => {
      const evidence = attempt.matchEvidence || {};
      const criteria = [evidence.accountMatched && '账户一致', evidence.cliTaskMatched && '原 CLI 请求一致', evidence.imagesMatched && '正反图片及顺序一致'].filter(Boolean).join(' · ');
      const statusLabel = attempt.status === 'no_match' && !attempt.searchComplete ? '未找到匹配（扫描未完成）' : labels[attempt.status] || attempt.status;
      return `<div class="timeline-row"><time>${esc(attempt.finishedAt || attempt.startedAt || '')}</time><div><strong>${esc(attempt.localId || '识别项')} · ${esc(statusLabel)}</strong><p>${attempt.searchComplete ? '分页已完整读取' : '搜索范围尚未确认完整'} · 精确匹配 ${Number(attempt.candidateCount || 0)} 条${criteria ? ` · ${esc(criteria)}` : ''}${attempt.identifyUri ? ` · ${esc(attempt.identifyUri)}` : ''}</p>${attempt.error ? `<small>${esc(attempt.error.code || '核验异常')} · ${esc(attempt.error.message || '')}</small>` : ''}</div></div>`;
    }).join('')}</section>`;
  };
  // 只有识别和新增收藏支持按条自动重试；编辑 / 取消被明确拒绝后必须重新生成计划。
  const resumable = (op) =>
    ['identify', 'collect'].includes(op.data.kind) &&
    (op.data.status === 'partial_failed' ||
      (op.data.status === 'reconcile_required' &&
        (op.data.kind !== 'identify' &&
          ((op.data.itemResults || []).some((item) => item.status === 'failed') &&
            (op.data.itemResults || []).filter((item) => item.status === 'failed').every((item) => item.error?.code === 'cli_retryable_failure')))));
  const remoteReconcileRunning = (op) => (op.data.remoteReconciliationAttempts || []).some((attempt) => attempt.status === 'running');
  const taskName = task?.manifest?.display_name || task?.display_name || '当前整理';
  const pageTitle = taskScoped ? `${taskName} · 执行记录` : '执行记录';
  const pageDescription = taskScoped ? '仅显示与本次整理任务关联的识别、收藏等执行操作。' : '已完成、部分完成与结果待核验分别记录。';
  const actions = taskScoped
    ? `${link('查看全部执行记录', 'operations', null, null, 'button quiet')} ${button('与 Agent 协作', 'bridge', 'quiet')}`
    : button('与 Agent 协作', 'bridge', 'quiet');
  const emptyState = taskScoped
    ? empty('本次整理暂无执行记录', '确认上传识别或收藏后，相关结果会显示在这里。')
    : empty('尚无业务执行记录', '配对和审核保存在本地。确认上传识别或收藏后，这里会显示每条实际执行结果。');
  return `${head(taskScoped ? 'TASK EXECUTION HISTORY' : 'EXECUTION HISTORY', pageTitle, pageDescription, actions)}${list.length ? list.map((op) => `<article class="operation-card ${op.data.status === 'reconcile_required' || op.data.status === 'partial_failed' ? 'warning' : ''}"><div class="inline" style="justify-content:space-between"><h3>${esc(op.data.label || op.data.kind)}</h3>${tag(state(op.data.status), op.data.status === 'reconcile_required' || op.data.status === 'partial_failed' ? 'amber' : 'neutral')}</div><p>${esc(op.data.message || '')}</p>${results(op)}${op.data.status === 'reconcile_required' ? `<button class="button quiet" data-action="operation-inspect" data-id="${esc(op.id)}">只读核验 CLI 状态</button>` : ''}${op.data.status === 'reconcile_required' && op.data.kind === 'identify' ? `<button class="button primary" data-action="operation-reconcile-identification" data-id="${esc(op.id)}" ${remoteReconcileRunning(op) ? 'disabled' : ''}>${remoteReconcileRunning(op) ? '正在核验远端结果' : '核验远端结果'}</button>` : ''}${resumable(op) ? `<button class="button primary" data-action="operation-resume" data-id="${esc(op.id)}">重试失败项</button>` : ''}${reconciliationHistory(op)}<details><summary>查看执行记录</summary><pre>${esc(JSON.stringify(op.data, null, 2))}</pre></details></article>`).join('') : emptyState}${queryLogCards}`;
}

export function remoteFields(value, depth = 0) {
  if (value === null || value === undefined) return '<span class="muted">未返回</span>';
  if (typeof value !== 'object') return esc(String(value));
  if (depth > 5) return '<span class="muted">详细内容已归档</span>';
  const labels = {
    title: '名称',
    status: '服务状态',
    remaining: '剩余次数',
    credits: '可用次数',
    experts: '鉴定专家',
    appraiserId: '专家 ID',
    appraiserType: '服务类型',
    name: '名称',
    description: '说明',
    conclusion: '鉴定结论',
    report: '报告',
    grade: '品相',
    label: '标签',
    price: '价格',
    value: '数值',
    currency: '币种',
    date: '日期',
    time: '时间',
    allowed: '是否可用',
    guideUrl: '查看入口',
    uri: '记录 URI',
    list: '记录',
    items: '记录',
    count: '数量',
  };
  return `<dl class="remote-fields">${Object.entries(value)
    .map(([key, v]) => `<dt>${esc(labels[key] || key)}</dt><dd>${remoteFields(v, depth + 1)}</dd>`)
    .join('')}</dl>`;
}
const businessStatus = (value) =>
  ({ draft: '材料草稿', submitting: '提交中', submitted: '已受理，待查询进度', reconcile_required: '结果待核验' })[value] || value;

function appraisals(m) {
  return `${head('EXPERT APPRAISALS', '真人鉴定', '准备材料、跟进进度，并保留每一份专家报告。', link('＋ 申请鉴定', 'appraisal', taskKey(m), m.route.item, 'button gold'))}${m.workspace.appraisals.length ? `<div class="table-wrap"><table><thead><tr><th>鉴定对象</th><th>状态</th><th>关注问题</th><th></th></tr></thead><tbody>${m.workspace.appraisals.map((a) => `<tr><td>${esc(a.data.title || a.id)}</td><td>${tag(businessStatus(a.data.status))}</td><td>${esc(a.data.description || '尚未填写')}</td><td>${link(['draft', 'failed'].includes(a.data.status) ? '继续准备' : '查看进度与报告', ['draft', 'failed'].includes(a.data.status) ? 'appraisal' : 'report', a.data.taskKey, a.data.localId, 'button small')}</td></tr>`).join('')}</tbody></table></div>` : empty('这里会保留你的鉴定申请', '选择藏品，准备图片和希望专家关注的问题。', link('从藏品库选择', 'library'))}<div class="note neutral" style="margin-top:22px">提交受理与专家报告完成分别跟进。使用已有次数；次数不足时保留草稿。</div>`;
}
function appraisal(m) {
  const item = currentItem(m);
  if (!item)
    return `${head('APPRAISAL REQUEST', '选择需要鉴定的对象', '从已有本地档案进入，保留材料的来历。')}${empty('先选一枚藏品', '在藏品档案中点击申请真人鉴定。', link('打开藏品库', 'library'))}`;
  const draft = m.workspace.appraisals.find((a) => a.id === item.local_id),
    data = draft?.data || {};
  if (draft && !['draft', 'failed'].includes(data.status))
    return `${head('APPRAISAL REQUEST', '这份申请已保存', '请从原记录查看进度，避免重复提交。')}${link('查看进度与报告', 'report', taskKey(m), item.local_id, 'button primary')}`;
  // 鉴定材料不能借用其他候选的照片：当前实物已关联的证据可选，尚未分配的图片
  // 也允许在用户确认后作为补充侧面照；已归属其他实物的来源一律排除。
  const own = new Set(item.evidence.map((e) => e.source_id));
  const occupied = new Set(m.task.items.filter((other) => other.local_id !== item.local_id).flatMap((other) => other.evidence.map((e) => e.source_id)));
  const sources = m.task.sources.filter((s) => s.mime_type.startsWith('image/') && (own.has(s.source_id) || !occupied.has(s.source_id)));
  const paired = Object.fromEntries(itemSources(m.task, item).map(({ source, role }) => [role, source.source_id]));
  const selectedSource = (role) => sources.find((source) => source.source_id === (data.sourceIds?.[role] || paired[role]));
  const photoChoice = (role) => {
    const source = selectedSource(role);
    const title = { obverse: '正面照片', reverse: '反面照片', side: '侧面照片' }[role];
    const preview = source
      ? `<img src="${esc(media(m.task.manifest.task_key, source.source_id))}" alt="${esc(title)}"><div><strong>${esc(source.origin?.original_name || source.source_id)}</strong><small>${own.has(source.source_id) ? '已关联本枚' : '本任务待关联'}</small></div>`
      : `<div class="appraisal-photo-empty"><b>＋</b><span>尚未选择图片</span></div>`;
    return `<section class="appraisal-photo-choice"><div class="inline" style="justify-content:space-between"><strong>${title}</strong><button class="button small quiet" data-action="appraisal-photo-picker" data-role="${role}">更换照片</button></div><input id="appraisal-${role}" type="hidden" value="${esc(source?.source_id || '')}"><div class="appraisal-photo-preview" data-appraisal-photo-preview="${role}">${preview}</div></section>`;
  };
  const services = m.appraisalServices?.experts || [];
  const selected =
    services.find((expert) => expert.appraiserType === data.appraiserType && expert.appraiserId === data.appraiserId) || (!draft ? services[0] : null);
  const serviceLabel = (expert) =>
    [expert.name, expert.duration, expert.price && expert.currency ? `${expert.currency}${expert.price} / 次` : null].filter(Boolean).join(' · ');
  const serviceOptions = services.length
    ? services
        .map(
          (expert) =>
            `<option value="${expert.appraiserType}:${expert.appraiserId}" ${selected === expert ? 'selected' : ''}>${esc(serviceLabel(expert))}${expert.recommended ? ' · 推荐' : ''}</option>`,
        )
        .join('')
    : '<option value="" selected>正在读取可用鉴定服务…</option>';
  const credits =
    m.appraisalServices?.selected &&
    selected &&
    m.appraisalServices.selected.appraiserType === selected.appraiserType &&
    m.appraisalServices.selected.appraiserId === selected.appraiserId
      ? m.appraisalServices.credits?.remainingTimes
      : null;
  const purchaseControl = appraisalPurchaseControl(selected, credits, m.workspace.purchases || []);
  const serviceNote = selected
    ? `<div class="note neutral" style="margin:14px 0"><strong>${esc(selected.name)}</strong><p id="appraisal-credit-status">${esc([selected.duration, selected.experience ? `已完成 ${selected.experience} 鉴定` : null, credits === null ? '正在查询当前可用次数…' : `当前可用 ${credits} 次`].filter(Boolean).join(' · '))}</p><div id="appraisal-purchase-control">${purchaseControl}</div></div>`
    : '<p class="muted" style="font-size:12px;margin:14px 0">服务目录从 CLI 读取后显示。若此前选择的服务已下线，请重新选择。</p>';
  return `${head('APPRAISAL REQUEST', '准备一份清楚的鉴定材料', '关联藏品、说明疑问、检查图片，再确认使用已有次数。')}<div class="two-col"><div class="panel pad"><h2>${esc(name(item))}</h2>${section('鉴定图片')}<div class="photos">${photo(m.task, item, 'obverse', '当前正面')}${photo(m.task, item, 'reverse', '当前反面')}</div><div class="appraisal-photo-grid">${['obverse', 'reverse', 'side'].map(photoChoice).join('')}</div><input id="appraisal-file-input" type="file" multiple accept="image/*" hidden><p class="muted">正反面默认使用当前藏品的确认配对图片。点击“更换照片”可在缩略图中选择；需要补拍时，${button('从本地上传照片', 'appraisal-upload', 'small quiet')}，归档后即可选择。</p>${section('你希望专家关注什么')}<textarea id="appraisal-desc" aria-label="鉴定描述" maxlength="5000" placeholder="描述想复核的年份、铸记、版别或表面问题。">${esc(data.description || '')}</textarea></div><aside><div class="panel pad"><div class="eyebrow">EXPERT & CREDITS</div><h2>服务与次数</h2><p class="muted" style="font-size:12px;margin:15px 0">服务信息与可用次数由 CLI 实时查询；不会展示内部服务类型或专家 ID。</p><label>选择鉴定服务<select id="appraiser-choice" ${services.length ? '' : 'disabled'}>${serviceOptions}</select></label>${serviceNote}<div class="actions" style="margin-top:20px">${button(services.length ? '刷新服务与次数' : '重新读取服务目录', 'appraisal-services', 'quiet')}${button('保存材料草稿', 'appraisal-save', 'quiet', !selected)}${button('检查提交范围', 'appraisal-preview', 'primary', !selected)}</div><small class="muted">${draft ? '已有保存的草稿' : '材料暂未保存'}</small></div></aside></div>`;
}
function report(m) {
  const entry = m.workspace.appraisals.find((a) => a.id === m.route.item);
  if (!entry)
    return `${head('APPRAISAL REPORT', '鉴定报告', '原始报告、识别结果和用户决定分别保留。')}${empty('先选择一份鉴定记录', '鉴定仍在处理中时，不会显示推测结论。', link('查看鉴定记录', 'appraisals'))}`;
  const data = entry.data;
  return `${head('APPRAISAL REPORT', data.title, '受理回执与专家进度分别显示。', `<button class="button primary" data-action="business-refresh" data-kind="appraisal" data-id="${esc(entry.id)}" ${!data.uri ? 'disabled' : ''}>查询最新进度</button>`)}<div class="two-col"><div class="panel pad"><h2>服务返回的进度与报告</h2>${data.detail ? remoteFields(data.detail) : empty('尚未查询报告', '提交受理后，可查询当前进度；未返回的结论保持空白。')}<p class="muted">${data.queriedAt ? '查询时间：' + esc(new Date(data.queriedAt).toLocaleString()) : ''}</p></div><aside><div class="panel pad">${tag(businessStatus(data.status))}<h2 style="margin-top:18px">关注问题</h2><p>${esc(data.description || '未填写')}</p><details><summary>提交回执</summary>${remoteFields(data.response)}</details>${link('查看藏品档案', 'coin', data.taskKey, data.localId, 'button quiet')}</div></aside></div>`;
}
function tracking(m) {
  const entry = m.workspace.tracking.find((t) => t.id === m.route.item) || m.workspace.tracking[0];
  const purchaseCards = trackingPurchaseCards(m.workspace.trackingPurchases || []);
  return `${head('PRICE TRACKING', '追踪', '持续关注本人收藏；行情带上来源、时间与适用条件。', button('＋ 选择藏品开启追踪', 'tracking-select', 'gold'))}${purchaseCards ? `<div class="panel pad" style="margin-bottom:18px"><h2>追踪位购买</h2>${purchaseCards}</div>` : ''}<div class="tracking-layout"><div><div class="panel pad"><h2>我的追踪</h2>${m.workspace.tracking.length ? m.workspace.tracking.map((t) => `<div class="running-item">${link(t.data.title || t.id, 'tracking', t.data.taskKey, t.id, 'link')}<p>${esc(t.data.label || '')}</p>${tag(businessStatus(t.data.status))}</div>`).join('') : '<p class="muted" style="font-size:12px;margin-top:16px">尚未开启追踪。先选一枚本人收藏，再检查可用追踪位。</p>'}</div></div><div class="panel pad"><div class="eyebrow">PRICE HISTORY</div><h2>${esc(entry?.data.title || '行情与来源')}</h2>${entry ? `<button class="button quiet" data-action="business-refresh" data-kind="tracking" data-id="${esc(entry.id)}" ${!entry.data.uri ? 'disabled' : ''}>查询追踪与行情</button><p class="muted">${entry.data.queriedAt ? '查询时间：' + esc(new Date(entry.data.queriedAt).toLocaleString()) : '尚未查询最新行情'}</p>${entry.data.prices ? remoteFields(entry.data.prices) : empty('暂无已核实的行情', '查询后展示服务实际返回的价格或查看入口。')}<details><summary>追踪详情</summary>${remoteFields(entry.data.detail || entry.data.response)}</details>` : empty('暂无已核实的行情', '有完整价格数据时显示数据；未返回价格时不会绘制推测曲线。')}</div></div>`;
}
function reports(m) {
  return `${head('MATERIALS & REPORTS', '资料与报告', '从原始来源到最终结果，都可以回到关联任务。', button('导出当前藏品清单', 'export', 'primary'))}${m.allTasks.length ? m.allTasks.map((t) => `<div class="panel pad" style="margin-bottom:18px"><div class="inline" style="justify-content:space-between"><h2>${esc(t.manifest.display_name)}</h2>${link('查看来源 →', 'inputs', t.manifest.task_key, null, 'link')}</div><p class="muted" style="margin:12px 0">${t.sources.length} 份来源资料 · ${t.items.length} 枚候选 · ${t.items.filter(collected).length} 枚已收藏</p>${link('阅读任务记录', 'task', t.manifest.task_key, null, 'button small')}</div>`).join('') : empty('原始资料和整理报告会保存在这里', '先导入照片、表格或文档。', link('导入资料', 'import'))}`;
}
function settings(m) {
  const current = m.workspace.settings;
  return `${head('WORKSPACE SETTINGS', '设置与备份', '本地工作空间、宿主协作与数据管理。')}<div class="two-col"><div class="panel pad"><h2>业务入口与工作台</h2><div class="switch-row"><div><strong>进入业务 Skill 时打开工作台</strong><p>启动或复用本地服务，打开对应任务页面。</p></div><button class="switch" role="switch" aria-label="进入业务 Skill 时打开工作台" aria-checked="${current?.data.autoOpen !== false}" data-action="auto-open"></button></div><div class="switch-row"><div><strong>聊天与网页共享任务事实</strong><p>本地请求持久化，宿主接收后显示回执。</p></div>${button('查看协作', 'bridge', 'small quiet')}</div>${section('本地数据')}<dl class="facts"><dt>数据库</dt><dd>heribase.sqlite</dd><dt>任务与证据</dt><dd>受控任务包 · 原始资料独立保存</dd><dt>旧历史索引</dt><dd>CLI 打开时迁入新库，原文件保留</dd></dl></div><aside><div class="panel pad"><h2>备份与恢复</h2><p class="muted" style="font-size:12px;margin:12px 0 20px">备份应包含业务数据库与媒体原件；连接凭据不进入分享资料。</p>${button('备份工作空间', 'backup', 'quiet')}</div></aside></div>`;
}

export function render(m) {
  return (
    {
      home,
      tasks,
      import: importer,
      task: taskView,
      inputs,
      pairing,
      identify,
      review,
      confirm,
      operations: operationsView,
      library,
      coin,
      appraisals,
      appraisal,
      report,
      tracking,
      reports,
      settings,
    }[m.route.page] || home
  )(m);
}
