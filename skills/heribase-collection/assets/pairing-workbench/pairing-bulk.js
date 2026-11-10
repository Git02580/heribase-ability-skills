/* 配对审核台的批量草稿逻辑；只计算浏览器草稿，绝不写入任务包。 */
(function attachPairingBulk(global) {
  "use strict";

  const BULK_ACTIONS = new Set(["confirm_pair", "need_photo", "exclude"]);

  function recordsById(records) {
    return new Map((Array.isArray(records) ? records : [])
      .filter((record) => record && typeof record.id === "string")
      .map((record) => [record.id, record]));
  }

  function hasConfirmedSides(record) {
    const roles = new Set((record.evidence || []).map((evidence) => evidence?.role));
    return roles.has("obverse") && roles.has("reverse") && !roles.has("unknown");
  }

  function selectByStatus(records, selectedIds, needsReview) {
    const selected = new Set(Array.isArray(selectedIds) ? selectedIds : []);
    for (const record of Array.isArray(records) ? records : []) {
      if (record && record.needsReview === needsReview && typeof record.id === "string") selected.add(record.id);
    }
    return [...selected];
  }

  function applyAction(records, drafts, selectedIds, action, updatedAt, batchActionId) {
    const nextDrafts = { ...(drafts || {}) };
    const allowed = BULK_ACTIONS.has(action) && typeof batchActionId === "string" && batchActionId.length > 0;
    const byId = recordsById(records);
    const affectedIds = [];
    const blockedIds = [];
    let overwrittenCount = 0;

    for (const localId of new Set(Array.isArray(selectedIds) ? selectedIds : [])) {
      const record = byId.get(localId);
      if (!allowed || !record || (action === "confirm_pair" && !hasConfirmedSides(record))) {
        if (record && action === "confirm_pair") blockedIds.push(localId);
        continue;
      }
      if (nextDrafts[localId]) overwrittenCount += 1;
      // 保留用户已经逐条选定的照片方向；批量操作只替换决定本身。
      nextDrafts[localId] = { ...nextDrafts[localId], action, updatedAt, batchActionId };
      affectedIds.push(localId);
    }

    return { drafts: nextDrafts, affectedIds, blockedIds, overwrittenCount };
  }

  global.CoinPairingBulk = Object.freeze({
    allowedActions: [...BULK_ACTIONS],
    clearSelection: () => [],
    selectByStatus,
    applyAction,
  });
}(globalThis));
