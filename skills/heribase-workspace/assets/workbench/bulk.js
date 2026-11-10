/* 选择范围与当前详情独立；按任务和阶段隔离。浏览器选择不代表用户已确认业务。 */
export function selectionFor(m) {
  const key = `${m.task?.manifest.task_key || ''}:${m.route.page}`;
  if (m.bulk?.key !== key) {
    m.bulk = { key, ids: new Set(), filter: 'all', query: '' };
    const handoff = m.identificationHandoff;
    // 只有用户点击“继续”才跨阶段带入选择；再次清空或切换任务不重新勾选。
    if (handoff && m.route.page === 'identify' && handoff.taskKey === m.task?.manifest.task_key) {
      const requested = new Set(handoff.localIds);
      m.bulk.ids = new Set(m.task.items.filter((i) => requested.has(i.local_id) && eligibleForIdentification(i)).map((i) => i.local_id));
    }
    m.identificationHandoff = null;
  }
  const existing = new Set((m.task?.items || [])
    .filter((item) => m.route.page !== 'pairing' || !['superseded', 'archived'].includes(item.status))
    .map((i) => i.local_id));
  for (const id of m.bulk.ids) if (!existing.has(id)) m.bulk.ids.delete(id);
  return m.bulk;
}
export function eligibleForIdentification(item) {
  const review = item.review_projection || {};
  if (item.status !== 'active' || item.active_identification?.status === 'succeeded') return false;
  if (['excluded', 'single_side', 'needs_review'].includes(item.organization?.pairing_state)) return false;
  if ((item.attention_flags || []).some((f) => ['pairing_needs_confirmation', 'source_incomplete', 'identity_conflict'].includes(f))) return false;
  if (!review.stale && ['exclude', 'need_photo'].includes(review.decision)) return false;
  const primary = (item.evidence || []).filter((e) => e.is_primary);
  const sources = new Set(primary.map((e) => e.source_id));
  const saved = item.organization?.source_assignment;
  const list = saved?.length ? saved.filter((e) => sources.has(e.source_id)) : primary;
  const roles = new Map(list.filter((e) => ['obverse', 'reverse'].includes(e.role)).map((e) => [e.role, e.source_id]));
  return roles.has('obverse') && roles.has('reverse') && roles.get('obverse') !== roles.get('reverse');
}
export function filteredItems(m) {
  const s = selectionFor(m);
  return (m.task?.items || []).filter((item) => {
    // 合并后的旧候选保留在任务包沿袭中供审计，但不再作为可操作的活动配对记录出现。
    if (m.route.page === 'pairing' && ['superseded', 'archived'].includes(item.status)) return false;
    const title = item.recognitionResult?.title || item.resolved_fields?.name?.value || item.resolved_fields?.title?.value || '';
    if (s.query && !`${title} ${item.local_id}`.toLowerCase().includes(s.query.toLowerCase())) return false;
    if (s.filter === 'all') return true;
    if (m.route.page === 'pairing') {
      const state = item.organization?.pairing_state;
      return s.filter === 'issues' ? state !== 'confirmed' : state === s.filter;
    }
    if (m.route.page === 'identify') return s.filter === 'ready' ? eligibleForIdentification(item) : !eligibleForIdentification(item);
    const review = item.review_projection || {};
    if (s.filter === 'pending') return !review.decision || review.stale;
    if (s.filter === 'issues')
      return (
        item.active_identification?.status !== 'succeeded' ||
        review.stale ||
        review.deferred ||
        (item.reviewIssues?.length && !item.reviewIssuesResolved) ||
        (item.attention_flags || []).length > 0
      );
    if (s.filter === 'hold') return review.deferred && !review.stale;
    return !review.stale && review.decision === s.filter;
  });
}

// 无选择时为明确标注的快捷入口提供候选；存在选择时绝不自动扩大范围。
export function identificationSelection(m) {
  const selected = selectionFor(m);
  return selected.ids.size
    ? [...selected.ids]
    : filteredItems(m)
        .filter(eligibleForIdentification)
        .map((i) => i.local_id);
}
