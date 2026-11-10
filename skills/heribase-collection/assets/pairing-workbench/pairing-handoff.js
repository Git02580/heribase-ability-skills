/* 配对审核的浏览器草稿与 JSON 交接契约；不写入任务包。 */
(function attachPairingHandoff(global) {
  "use strict";
  const ALLOWED = new Set(["confirm_pair", "split", "merge", "need_photo", "exclude"]);
  function validTime(value) { return typeof value === "string" && Number.isFinite(Date.parse(value)); }
  function assignmentsFor(record, decision) {
    const evidence = (record.evidence || []).filter((e) => e && typeof e.sourceId === "string");
    const evidenceIds = new Set(evidence.map((e) => e.sourceId));
    const chosen = Array.isArray(decision.sourceAssignments) ? decision.sourceAssignments : [];
    const roles = new Set();
    const valid = chosen.length === evidence.length && chosen.every((value) => {
      if (!value || !evidenceIds.has(value.sourceId) || !["obverse", "reverse"].includes(value.role) || roles.has(value.role)) return false;
      roles.add(value.role); return true;
    });
    // 只有用户完整指定且每面唯一时才覆盖初始角色，避免导出半套或伪造的分配。
    return valid ? chosen.map((value) => ({ sourceId: value.sourceId, role: value.role })) : evidence.map((e) => ({ sourceId: e.sourceId, role: ["obverse", "reverse"].includes(e.role) ? e.role : "unknown" }));
  }
  function buildPackage(records, decisions, exportedAt, datasetFingerprint) {
    const byId = new Map((Array.isArray(records) ? records : []).filter((r) => r && typeof r.id === "string").map((r) => [r.id, r]));
    const accepted = Object.entries(decisions || {}).filter(([id, decision]) => byId.has(id) && decision && ALLOWED.has(decision.action) && validTime(decision.updatedAt)).map(([localId, decision]) => {
      const exported = {
        localId, action: decision.action,
        sourceAssignments: assignmentsFor(byId.get(localId), decision),
        updatedAt: decision.updatedAt,
      };
      // 批量 ID 只是同批浏览器草稿的审计关联；每条决定仍独立导出和导入。
      if (typeof decision.batchActionId === "string" && decision.batchActionId) exported.batchActionId = decision.batchActionId;
      return exported;
    });
    return { schemaVersion: 1, taskKey: records?.taskKey || "", datasetFingerprint: typeof datasetFingerprint === "string" ? datasetFingerprint : "", exportedAt: validTime(exportedAt) ? exportedAt : new Date(0).toISOString(), summary: { confirmed: accepted.filter((x) => x.action === "confirm_pair").length, needPhoto: accepted.filter((x) => x.action === "need_photo").length, excluded: accepted.filter((x) => x.action === "exclude").length }, decisions: accepted };
  }
  function readPendingPackage(records, decisions, datasetFingerprint, taskKey, readAt) {
    const payload = buildPackage(records, decisions, readAt, datasetFingerprint);
    // 读取接口的任务键必须来自调用方，避免依赖 records 上可能不存在或过期的字段。
    payload.taskKey = taskKey;
    return payload;
  }
  global.CoinPairingHandoff = Object.freeze({ buildPackage, readPendingPackage, allowedActions: [...ALLOWED] });
}(globalThis));
