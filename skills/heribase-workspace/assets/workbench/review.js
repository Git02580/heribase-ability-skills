/* 专业审核展示：服务参考资料与实物观察分开，所有文字在进入 HTML 前转义。 */
import { media } from './api.js';
import { filteredItems, selectionFor } from './bulk.js';
const e = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const reviewDecision = (item) => (item?.review_projection?.deferred ? 'hold' : item?.review_projection?.decision);
export const reviewLabels = { collect: '待收藏', hold: '暂留复核', need_photo: '需要补图', exclude: '排除', pending: '尚未决定' };
export const unresolvedReview = (item) => !!item?.reviewIssues?.length && !item.reviewIssuesResolved;
const btn = (text, action, extra = '') => `<button class="button small quiet" data-action="${action}" ${extra}>${text}</button>`;
const panel = (title, body, extra = '') =>
  `<section class="panel rr-panel"><div class="panel-head"><h3>${title}</h3>${extra}</div><div class="rr-body">${body}</div></section>`;
const value = (result, key) =>
  (Array.isArray(result?.attributes) ? result.attributes : []).find((a) => String(a.name).toLowerCase() === key.toLowerCase())?.value;
const missing = (v) => e(v === undefined || v === null || v === '' ? '未提供' : v);
export function referenceURL(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && ['cdn.heritcoin.com', 'cdn.heribase.com'].includes(u.hostname) && !u.username && !u.password && !u.port ? u.href : null;
  } catch {
    return null;
  }
}
// 本地图片只使用用户确认的方向；unknown 和未标面参考数组都不猜测正反面。
export function reviewImages(task, item, side) {
  const assigned = item.organization?.source_assignment;
  const evidence = assigned?.length ? assigned : item.evidence || [];
  const sourceId = evidence.find((x) => x.role === side && task.sources.some((s) => s.source_id === x.source_id))?.source_id;
  const info = item.recognitionResult?.obverseReverseInfo?.[side === 'obverse' ? 'frontInfo' : 'backInfo'];
  return { mine: sourceId ? media(task.manifest.task_key, sourceId) : null, reference: referenceURL(info?.img) };
}
function imageCell(url, label, side, kind) {
  return `<div class="rr-image-cell"><div class="rr-image-label">${label}<small>${kind === 'mine' ? '已归档照片' : '非本枚实物'}</small></div>${url ? `<button class="rr-image rr-image-${kind}" data-action="review-zoom" data-side="${side}" aria-label="放大${label}"><img src="${e(url)}" alt="${label}" referrerpolicy="no-referrer"><span>放大查看 ↗</span></button>` : `<div class="rr-image rr-empty">暂无${label}<small>可返回配对页补充或核对资料</small></div>`}</div>`;
}
function photos(task, item) {
  const r = item.recognitionResult || {};
  const mapped = new Set(['obverse', 'reverse'].map((side) => reviewImages(task, item, side).reference).filter(Boolean));
  const extras = [...new Set((Array.isArray(r.referenceImages) ? r.referenceImages : []).map(referenceURL).filter((url) => url && !mapped.has(url)))];
  return `<section class="panel rr-panel"><div class="panel-head"><h3>实物与参考对照</h3><small>正反面同时展示 · 同面横向对照</small></div>${[
    ['obverse', '正面'],
    ['reverse', '反面'],
  ]
    .map(([side, title]) => {
      const images = reviewImages(task, item, side);
      return `<div class="rr-photo-row"><div class="rr-row-head"><strong>${title}</strong>${btn('放大' + title + '对照 ↗', 'review-zoom', `data-side="${side}"`)}</div><div class="rr-photo-grid">${imageCell(images.mine, '我的实物 · ' + title, side, 'mine')}${imageCell(images.reference, '服务参考 · ' + title, side, 'reference')}</div></div>`;
    })
    .join(
      '',
    )}<div class="rr-caption">实物照片适配预览；点击可查看完整原图。图片显示尺寸不代表真实直径。</div>${extras.length ? `<div class="rr-body"><h3>其他服务参考图 · 面别未标明</h3><div class="rr-gallery">${extras.map((url) => `<button data-action="zoom" data-url="${e(url)}" aria-label="放大未标面参考图"><img src="${e(url)}" alt="面别未标明的服务参考图" referrerpolicy="no-referrer"></button>`).join('')}</div></div>` : ''}</section>`;
}
function facts(item) {
  const r = item.recognitionResult || {},
    d = item.reviewDetails || {};
  return panel(
    '材质与规格',
    `<table class="rr-facts"><thead><tr><th>项目</th><th>服务参考规格</th><th>我的实测 / 观察</th></tr></thead><tbody>${[
      ['材质', 'Metal', 'metal', ''],
      ['重量', 'weight', 'weight', ' g'],
      ['直径', 'diameter', 'diameter', ' mm'],
      ['厚度', 'thickness', 'thickness', ' mm'],
      ['边缘 / 币轴', null, 'edge', ''],
    ]
      .map(
        ([label, key, field, unit]) =>
          `<tr><td>${label}</td><td>${missing(key ? value(r, key) : null)}</td><td>${d[field] ? e(d[field] + unit) : '<span class="muted">尚未记录</span>'}</td></tr>`,
      )
      .join('')}</tbody></table><p class="rr-caption">参考规格描述币种；实测描述这一枚实物。两套数值独立保存。</p>`,
    btn('补充实测', 'review-edit', 'data-section="measure"'),
  );
}
function motifs(item) {
  const info = item.recognitionResult?.obverseReverseInfo || {};
  return panel(
    '正反面图案与铭文',
    `<div class="rr-two">${[
      ['frontInfo', '正面'],
      ['backInfo', '反面'],
    ]
      .map(([key, title]) => {
        const side = info[key] || {};
        return `<div><h3>${title}</h3><div class="rr-tags">${[...(Array.isArray(side.labels) ? side.labels : []), ...(Array.isArray(side.tags) ? side.tags : [])].map((v) => `<span>${e(v)}</span>`).join('') || '<small class="muted">未提供图文标签</small>'}</div>${(Array.isArray(side.detail) ? side.detail : []).map((d) => `<p>${e(d.property)}：${e(d.value)}</p>`).join('')}</div>`;
      })
      .join('')}</div><p class="rr-caption">以上来自服务参考资料，不等同于从实物照片中识别出的文字。</p>`,
  );
}
function allAttributes(item) {
  const r = item.recognitionResult || {},
    d = item.reviewDetails || {};
  return panel(
    '币种、版别与发行信息',
    `<table class="rr-facts"><tbody>${[['识别原名', r.title], ['年份', r.year], ['造币标记', r.mintMark], ['细分版别 / 错版补充', d.variety], ['识别修正建议', d.correction], ...(Array.isArray(r.attributes) ? r.attributes : []).map((a) => [{ Country: '国家 / 地区', Denomination: '面额', 'Krause number': '目录编号', Mintage: '发行量', Metal: '材质', weight: '重量', diameter: '直径', thickness: '厚度' }[a.name] || a.name, a.value])].map(([k, v]) => `<tr><td>${e(k)}</td><td>${missing(v)}</td></tr>`).join('')}</tbody></table><p class="rr-caption">保留服务原值；未提供的铸造厂、工艺、细分版别不自行推断。发行量不直接换算稀有度。</p>`,
    btn('补充版别 / 修正', 'review-edit', 'data-section="identity"'),
  );
}
function provenance(item) {
  return panel(
    '来源与识别记录',
    `<p class="muted">识别时间：${item.active_identification?.recognized_at ? e(new Date(item.active_identification.recognized_at).toLocaleString()) : '尚未识别'}</p><details><summary>原始整理 / 导入记录</summary><pre>${e(JSON.stringify({ resolved_fields: item.resolved_fields, field_claims: item.field_claims }, null, 2))}</pre></details><details><summary>服务返回的识别资料</summary><pre>${e(JSON.stringify(item.recognitionResult || {}, null, 2))}</pre></details>`,
    btn('审核记录', 'review-history'),
  );
}
function discrepancy(item) {
  return `${item.reviewDetailsStale ? '<div class="note">图片或识别已更新，旧核对清单与差异结论需要重新确认；历史记录仍保留。</div>' : ''}${item.reviewIssues?.length ? `<div class="note ${unresolvedReview(item) ? '' : 'green'}"><strong>${unresolvedReview(item) ? '来源与识别资料需要核对' : '已保存资料差异核对说明'}</strong>${item.reviewIssues.map((i) => `<p>${e(i.field)}：${e(i.source)}「${e(i.original)}」<br>识别返回「${e(i.recognized)}」</p>`).join('')}<p>两份资料都可能需要修正。请回看实物，记录判断依据。</p>${btn('查看 / 记录核对结论', 'review-edit', 'data-section="resolution"')}</div>` : ''}`;
}
function decisionPane(m, item) {
  const r = item.reviewDetails || {},
    draft = m.reviewDraft?.localId === item.local_id ? m.reviewDraft : {};
  const current = draft.decision || reviewDecision(item) || (item.active_identification?.status === 'succeeded' ? 'collect' : 'hold');
  const old = m.workspace.notes?.find((n) => n.id === item.local_id)?.data.text || '';
  return `<aside class="decision-pane rr-decision"><div class="eyebrow">YOUR REVIEW</div><h2>我的审核决定</h2><p class="rr-caption">核对影响币种判断的要点，再记录是否采纳。</p><div class="rr-checks"><small class="muted">核对清单 · 用户记录</small>${[
    ['identity', '国家、面额与年份'],
    ['catalog', '造币标记与目录编号'],
    ['motif', '正反面图案与铭文'],
  ]
    .map(
      ([key, title]) =>
        `<label><input type="checkbox" data-review-check="${key}" ${(draft.checks || (!item.reviewDetailsStale ? r.checks : []) || []).includes(key) ? 'checked' : ''}>${title}</label>`,
    )
    .join(
      '',
    )}</div>${btn('补充版别 / 识别修正', 'review-edit', 'data-section="identity"')}<label class="rr-note-label">审核备注<textarea id="review-detail-note" maxlength="10000" placeholder="记录核对依据与仍待确认的部分…">${e(draft.note ?? r.note ?? old)}</textarea></label><div class="rr-decisions">${Object.entries(
    reviewLabels,
  )
    .filter(([key]) => key !== 'pending')
    .map(
      ([key, title]) =>
        `<button class="button ${current === key ? 'primary' : 'quiet'}" data-action="review-choice" data-value="${key}" ${key === 'collect' && (item.active_identification?.status !== 'succeeded' || item.collection_projection?.collection_uri) ? 'disabled' : ''}>${title}</button>`,
    )
    .join(
      '',
    )}</div><div class="rr-save">${btn('保存决定', 'review-save')}${btn('保存，下一枚 →', 'review-save-next')}</div><div class="saved">${item.review_projection?.stale ? '决定已过期' : e(reviewLabels[reviewDecision(item)] || '尚未决定')}</div><p class="rr-caption">待收藏进入确认清单，正式写入另行确认。暂留复核会撤回当前采纳资格。</p>${btn('查看审核记录', 'review-history')}${btn('询问 Agent', 'bridge')}</aside>`;
}
export function reviewBatch(m, h) {
  const selection = selectionFor(m);
  return `<div class="table-wrap"><table class="rr-batch"><thead><tr><th>选择</th><th>实物 / 参考</th><th>识别结果</th><th>参考规格</th><th>审核关注</th><th>决定</th><th></th></tr></thead><tbody>${
    filteredItems(m)
      .map((i) => {
        const r = i.recognitionResult || {},
          imgs = reviewImages(m.task, i, 'obverse');
        return `<tr><td><input type="checkbox" data-bulk-id="${e(i.local_id)}" aria-label="选择${e(h.name(i))}" ${selection.ids.has(i.local_id) ? 'checked' : ''}></td><td><div class="rr-batch-images">${[
          ['实物', imgs.mine],
          ['参考', imgs.reference],
        ]
          .map(([label, url]) => (url ? `<img src="${e(url)}" alt="${label}" referrerpolicy="no-referrer">` : `<small>无${label}</small>`))
          .join(
            '',
          )}</div></td><td><strong>${e(h.name(i))}</strong><small>${missing(r.year)} · ${missing(value(r, 'Krause number'))}</small></td><td>${missing(value(r, 'Metal'))}<small>${missing(value(r, 'weight'))} / ${missing(value(r, 'diameter'))}</small></td><td>${unresolvedReview(i) ? '<span class="tag amber">差异待核对</span>' : i.active_identification?.status === 'succeeded' ? '可人工审核' : '尚未识别'}</td><td>${e(h.decision(i))}</td><td><a href="${e(h.href('review', m.task.manifest.task_key, i.local_id))}" class="link" data-review-detail>逐枚对照 ↗</a></td></tr>`;
      })
      .join('') || '<tr><td colspan="7">没有符合条件的候选</td></tr>'
  }</tbody></table></div>`;
}
export function reviewContent(m, h) {
  const item = h.currentItem(m);
  if (!item) return '';
  const view = m.reviewView || 'compare',
    r = item.recognitionResult || {};
  const tabs = `<div class="rr-viewbar"><div class="tabs">${[
    ['compare', '对照审核'],
    ['details', '完整资料'],
    ['batch', '批量速览'],
  ]
    .map(([key, label]) => `<button class="tab ${key === view ? 'active' : ''}" data-action="review-view" data-value="${key}">${label}</button>`)
    .join('')}</div><small class="muted">服务资料与实物观察分层保存</small></div>`;
  if (view === 'batch') return tabs + reviewBatch(m, h);
  const summary = `<section class="panel rr-identity"><div class="eyebrow">${e(item.item_key)} · 服务识别结果</div><h2>${e(h.name(item))}</h2><div class="rr-summary">${[
    ['国家 / 地区', value(r, 'Country')],
    ['面额', value(r, 'Denomination')],
    ['年份', r.year],
    ['目录编号', value(r, 'Krause number')],
  ]
    .map(([label, v]) => `<div><small>${label}</small><strong>${missing(v)}</strong></div>`)
    .join('')}</div></section>`;
  return `${tabs}<div class="rr-layout">${h.queue(m)}<article class="rr-center">${summary}${discrepancy(item)}${view === 'compare' ? photos(m.task, item) : allAttributes(item)}${facts(item)}${motifs(item)}${view === 'details' ? `<div class="rr-two">${panel('保存状态与品相', `<p>${e(item.reviewDetails?.condition || '尚未记录实物观察')}</p><p class="rr-caption">可记录磨损、划痕、清洗疑点、包浆、光泽、边缘及铸打细节。当前没有结构化评级与鉴真凭证。</p>`, btn('记录观察', 'review-edit', 'data-section="condition"'))}${panel('价格与来源', `<h2>${missing(r.price?.value)} <small>${e(r.price?.currency || '')}</small></h2><p class="rr-caption">服务参考价格。报价日期、对应品相与估价方法未提供，不作为本枚实物的确认价值。</p>`)}</div>${provenance(item)}` : `<details class="rr-more"><summary>完整币种资料、价格与来源</summary>${allAttributes(item)}${provenance(item)}${panel('服务参考价格', `${missing(r.price?.value)} ${e(r.price?.currency || '')}<p class="rr-caption">报价日期、对应品相和估价方法未提供。</p>`)}</details>`}${h.link('返回配对检查', 'pairing', m.task.manifest.task_key, item.local_id, 'button small quiet')}</article>${decisionPane(m, item)}</div>`;
}
