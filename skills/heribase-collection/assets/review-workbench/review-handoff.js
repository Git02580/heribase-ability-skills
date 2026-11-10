/*
 * 审核决定的单一交接契约。
 *
 * 此文件由浏览器直接加载，也由 Node 测试在隔离上下文中执行。它不读取
 * localStorage、不发起网络请求；调用方必须显式传入当前内存中的决定与记录。
 */
(function attachCoinReviewHandoff(global) {
  "use strict";

  const ALLOWED_DECISIONS = new Set(["collect", "need-photo", "exclude"]);

  /**
   * 从已加载的记录与内存决定创建可导出、可由 WebMCP 返回的最小审核包。
   * 仅保留仍存在的记录、白名单决定和有效时间，避免旧缓存污染后续处理。
   */
  function buildPackage(records, decisions, exportedAt, options = {}) {
    const recordsById = new Map(
      Array.isArray(records)
        ? records.filter((record) => record && typeof record.id === "string").map((record) => [record.id, record])
        : [],
    );
    const entries = Object.entries(decisions && typeof decisions === "object" ? decisions : []);
    const accepted = entries
      .filter(([recordId, value]) => recordsById.has(recordId) && isValidDecision(value))
      .map(([recordId, value]) => {
        const item = {
          recordId,
          sourceRows: sourceRowsOf(recordsById.get(recordId)),
          decision: value.decision,
          updatedAt: value.updatedAt,
        };
        // v2 才输出操作来源；旧缓存没有这些字段时保持 v1 数据最小化。
        if (value.source === "single" || value.source === "bulk" || value.source === "import") item.source = value.source;
        if (typeof value.batchActionId === "string" && value.batchActionId) item.batchActionId = value.batchActionId;
        return item;
      })
      .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt) || left.recordId.localeCompare(right.recordId));

    const summary = { collect: 0, needPhoto: 0, excluded: 0 };
    for (const item of accepted) {
      if (item.decision === "collect") summary.collect += 1;
      if (item.decision === "need-photo") summary.needPhoto += 1;
      if (item.decision === "exclude") summary.excluded += 1;
    }

    const datasetFingerprint = validFingerprint(options.datasetFingerprint) ? options.datasetFingerprint : "";
    return {
      schemaVersion: datasetFingerprint ? 2 : 1,
      ...(datasetFingerprint ? { datasetFingerprint } : {}),
      exportedAt: validTimestamp(exportedAt) ? exportedAt : new Date(0).toISOString(),
      summary,
      decisions: accepted,
    };
  }

  /**
   * 在真正修改决定前计算影响范围。推荐收藏的未识别记录始终阻止；需复核记录
   * 进入警告集合，交给界面明确展示并由用户再次确认。
   */
  function previewBulkDecision(records, decisions, selectedIds, decision) {
    const recordsById = new Map(
      Array.isArray(records)
        ? records.filter((record) => record && typeof record.id === "string").map((record) => [record.id, record])
        : [],
    );
    const requestedIds = [...new Set(Array.isArray(selectedIds) ? selectedIds.filter((id) => typeof id === "string") : [])];
    const eligibleIds = [];
    const warningIds = [];
    const blockedIds = [];
    let overwrittenCount = 0;

    for (const recordId of requestedIds) {
      const record = recordsById.get(recordId);
      if (!record) {
        blockedIds.push(recordId);
        continue;
      }
      if (decision === "collect" && record.systemStatus === "unidentified") {
        blockedIds.push(recordId);
        continue;
      }
      if (decision === "collect" && record.systemStatus === "review") warningIds.push(recordId);
      else eligibleIds.push(recordId);
      const existingDecision = decisions?.[recordId]?.decision;
      if (existingDecision && existingDecision !== decision) overwrittenCount += 1;
    }

    return { requestedCount: requestedIds.length, eligibleIds, warningIds, blockedIds, overwrittenCount };
  }

  /** 应用已经展示给用户的批量预检结果，并保存逐条旧值用于精确撤销。 */
  function applyBulkDecision(decisions, preview, decision, updatedAt, batchActionId) {
    const next = cloneDecisionMap(decisions);
    const affectedIds = [...new Set([...(preview?.eligibleIds ?? []), ...(preview?.warningIds ?? [])])];
    const previous = {};
    for (const recordId of affectedIds) {
      previous[recordId] = Object.hasOwn(next, recordId) ? { ...next[recordId] } : null;
      if (decision) {
        next[recordId] = {
          decision,
          updatedAt: validTimestamp(updatedAt) ? updatedAt : new Date(0).toISOString(),
          source: "bulk",
          batchActionId: typeof batchActionId === "string" ? batchActionId : "",
        };
      } else {
        delete next[recordId];
      }
    }
    return { decisions: next, appliedIds: affectedIds, undo: { previous } };
  }

  /** 只还原本次批量动作触及的记录，不覆盖动作之后产生的其他决定。 */
  function undoDecisionBatch(decisions, undo) {
    const next = cloneDecisionMap(decisions);
    for (const [recordId, previous] of Object.entries(undo?.previous ?? {})) {
      if (previous === null) delete next[recordId];
      else next[recordId] = { ...previous };
    }
    return next;
  }

  /**
   * 将导出的 v1/v2 包恢复为 localStorage 使用的决定映射。v2 指纹不一致时
   * 完全拒绝导入，避免同名 recordId 在另一批数据上发生静默错配。
   */
  function parseImportedPackage(payload, records, expectedFingerprint) {
    if (!payload || typeof payload !== "object" || ![1, 2].includes(payload.schemaVersion) || !Array.isArray(payload.decisions)) {
      return { ok: false, reason: "invalid-package" };
    }
    if (
      payload.schemaVersion === 2
      && validFingerprint(expectedFingerprint)
      && payload.datasetFingerprint !== expectedFingerprint
    ) {
      return {
        ok: false,
        reason: "dataset-mismatch",
        expectedFingerprint,
        actualFingerprint: payload.datasetFingerprint ?? "",
      };
    }

    const recordIds = new Set(Array.isArray(records) ? records.map((record) => record?.id).filter(Boolean) : []);
    const decisions = {};
    let rejectedCount = 0;
    for (const item of payload.decisions) {
      if (!item || !recordIds.has(item.recordId) || !isValidDecision(item)) {
        rejectedCount += 1;
        continue;
      }
      decisions[item.recordId] = {
        decision: item.decision,
        updatedAt: item.updatedAt,
        source: "import",
        ...(typeof item.batchActionId === "string" && item.batchActionId ? { batchActionId: item.batchActionId } : {}),
      };
    }
    const warnings = [];
    if (payload.schemaVersion === 1) warnings.push("旧版审核包没有数据集指纹，已按记录 ID 恢复");
    if (rejectedCount > 0) warnings.push(`${rejectedCount} 条决定因记录缺失或格式无效被跳过`);
    return { ok: true, decisions, acceptedCount: Object.keys(decisions).length, rejectedCount, warnings };
  }

  /**
   * 将同一个审核包以两个只读 WebMCP 工具暴露给支持该 API 的浏览器。
   * 页面只传入 buildPackage 闭包，工具本身没有对页面或存储的写权限。
   */
  async function registerReadOnlyTools(modelContext, packageFactory) {
    if (!modelContext || typeof modelContext.registerTool !== "function") {
      return { registered: false, reason: "unsupported" };
    }
    if (typeof packageFactory !== "function") {
      return { registered: false, reason: "invalid-package-factory" };
    }

    const inputSchema = { type: "object", properties: {}, additionalProperties: false };
    const annotations = { readOnlyHint: true, untrustedContentHint: false };
    try {
      await modelContext.registerTool({
        name: "get_review_decisions",
        description: "Return the current coin-review decisions as a read-only versioned package.",
        inputSchema,
        annotations,
        execute: async () => packageFactory(),
      });
      await modelContext.registerTool({
        name: "get_review_decision_summary",
        description: "Return a read-only summary of the current coin-review decisions.",
        inputSchema,
        annotations,
        execute: async () => {
          const reviewPackage = packageFactory();
          return {
            schemaVersion: reviewPackage.schemaVersion,
            ...(reviewPackage.datasetFingerprint
              ? { datasetFingerprint: reviewPackage.datasetFingerprint }
              : {}),
            exportedAt: reviewPackage.exportedAt,
            summary: reviewPackage.summary,
          };
        },
      });
      return { registered: true, reason: "registered" };
    } catch {
      return { registered: false, reason: "registration-failed" };
    }
  }

  function toFileName(exportedAt) {
    const date = validTimestamp(exportedAt) ? exportedAt.slice(0, 10) : "unknown-date";
    return `硬币审核决定-${date}.json`;
  }

  function sourceRowsOf(record) {
    return Array.isArray(record?.sourceRows)
      ? record.sourceRows.filter((row) => Number.isInteger(row)).slice()
      : [];
  }

  function isValidDecision(value) {
    return Boolean(
      value
      && typeof value === "object"
      && ALLOWED_DECISIONS.has(value.decision)
      && validTimestamp(value.updatedAt),
    );
  }

  function validTimestamp(value) {
    return typeof value === "string" && value !== "" && Number.isFinite(Date.parse(value));
  }

  function validFingerprint(value) {
    return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  }

  function cloneDecisionMap(decisions) {
    return Object.fromEntries(
      Object.entries(decisions && typeof decisions === "object" ? decisions : {})
        .filter(([, value]) => value && typeof value === "object")
        .map(([recordId, value]) => [recordId, { ...value }]),
    );
  }

  global.CoinReviewHandoff = Object.freeze({
    buildPackage,
    previewBulkDecision,
    applyBulkDecision,
    undoDecisionBatch,
    parseImportedPackage,
    registerReadOnlyTools,
    toFileName,
  });
}(globalThis));
