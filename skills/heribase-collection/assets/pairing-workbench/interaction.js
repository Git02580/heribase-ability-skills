/* 页面操作只保存浏览器草稿；用户导出的 JSON 才能进入 import-pairing。 */
(function () {
  const data = window.COIN_PAIRING_DATA;
  const key = `heribase-pairing:${data.buildMeta.datasetFingerprint}`;
  let drafts = {};
  let selectedIds = new Set();
  try { drafts = JSON.parse(localStorage.getItem(key) || "{}"); } catch (_) { drafts = {}; }

  // WebMCP is optional: browsers without it continue using the JSON export handoff.
  // The tool only snapshots current local drafts; it deliberately has no input or write path.
  const modelContext = document.modelContext || navigator.modelContext;
  if (modelContext?.registerTool) {
    try {
      const registration = modelContext.registerTool({
        name: "get_pending_pairing_decisions",
        description: "读取当前页面暂存的配对决定；只读，不写入整理任务。",
        inputSchema: { type: "object", properties: {}, additionalProperties: false },
        annotations: { readOnlyHint: true },
        execute() {
          return CoinPairingHandoff.readPendingPackage(
            data.records,
            drafts,
            data.buildMeta.datasetFingerprint,
            data.buildMeta.taskKey,
            new Date().toISOString(),
          );
        },
      });
      // Registration failures must not disable the JSON export fallback.
      void Promise.resolve(registration).catch(() => {});
    } catch (_) {
      // Some hosts throw synchronously for an unsupported registration; keep initializing.
    }
  }

  const actions = ["confirm_pair", "split", "merge", "need_photo", "exclude"];
  const labels = { confirm_pair: "已确认同一枚硬币", split: "已标记为拆分单面", merge: "已标记为重新合并", need_photo: "已标记等待补图", exclude: "已标记排除" };
  const bulkLabels = { confirm_pair: "批量确认配对", need_photo: "批量标记待补图", exclude: "批量排除" };
  const current = () => data.records.find((item) => item.id === document.querySelector(".item.on")?.dataset.id);
  const message = (value) => { document.querySelector("#bulk-message").textContent = value; };
  const saveDrafts = () => localStorage.setItem(key, JSON.stringify(drafts));
  const batchId = () => `pairing-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  function syncSelection() {
    document.querySelectorAll(".select-item").forEach((input) => { input.checked = selectedIds.has(input.dataset.id); });
    document.querySelector("#selection-count").textContent = `已选 ${selectedIds.size} 条`;
  }

  document.addEventListener("click", (event) => {
    const actionButton = event.target.closest(".actions button");
    if (actionButton) {
      const record = current(); if (!record) return;
      const action = actions[[...actionButton.parentNode.children].indexOf(actionButton)];
      drafts[record.id] = { ...drafts[record.id], action, updatedAt: new Date().toISOString() };
      saveDrafts();
      document.querySelector(".note").textContent = `本地草稿：${labels[action]}。导出 JSON 后才能正式写入整理任务。`;
      return;
    }

    const statusButton = event.target.closest("[data-select-status]");
    if (statusButton) {
      selectedIds = new Set(window.CoinPairingBulk.selectByStatus(data.records, [...selectedIds], statusButton.dataset.selectStatus === "review"));
      syncSelection();
      message(`已加入${statusButton.dataset.selectStatus === "review" ? "需要人工确认" : "自动就绪"}的候选。`);
      return;
    }

    if (event.target.closest("[data-clear-selection]")) {
      selectedIds = new Set(window.CoinPairingBulk.clearSelection());
      syncSelection(); message("已清空批量选择。");
      return;
    }

    const bulkButton = event.target.closest("[data-bulk-action]");
    if (bulkButton) {
      const action = bulkButton.dataset.bulkAction;
      const result = window.CoinPairingBulk.applyAction(data.records, drafts, [...selectedIds], action, new Date().toISOString(), batchId());
      if (!result.affectedIds.length) {
        message(action === "confirm_pair" && result.blockedIds.length ? "所选候选没有完整且方向已确定的正反面；请逐条调整后再确认。" : "请先选择至少一条候选。");
        return;
      }
      const notice = `${bulkLabels[action]}将影响 ${result.affectedIds.length} 条${result.overwrittenCount ? `，覆盖 ${result.overwrittenCount} 条已有草稿` : ""}${result.blockedIds.length ? `；${result.blockedIds.length} 条因照片不完整或方向待定而跳过` : ""}。`;
      if (!window.confirm(`${notice}\n\n继续吗？`)) return;
      drafts = result.drafts; saveDrafts();
      message(`${bulkLabels[action]}已暂存 ${result.affectedIds.length} 条${result.blockedIds.length ? `；已跳过 ${result.blockedIds.length} 条` : ""}。导出 JSON 后才会写入整理任务。`);
      return;
    }

    if (event.target.id === "export-pairing") {
      const payload = CoinPairingHandoff.buildPackage(data.records, drafts, new Date().toISOString(), data.buildMeta.datasetFingerprint);
      payload.taskKey = data.buildMeta.taskKey;
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
      link.download = "硬币配对决定.json"; link.click(); URL.revokeObjectURL(link.href);
    }
  });

  document.addEventListener("change", (event) => {
    const checkbox = event.target.closest(".select-item");
    if (checkbox) {
      if (checkbox.checked) selectedIds.add(checkbox.dataset.id); else selectedIds.delete(checkbox.dataset.id);
      syncSelection(); return;
    }
    const selector = event.target.closest(".role-select");
    if (!selector) return;
    const record = current(); if (!record) return;
    const previous = drafts[record.id] || {};
    const assignments = (record.evidence || []).map((evidence) => ({
      sourceId: evidence.sourceId,
      role: evidence.sourceId === selector.dataset.sourceId ? selector.value : (previous.sourceAssignments || []).find((value) => value.sourceId === evidence.sourceId)?.role || evidence.role,
    }));
    drafts[record.id] = { ...previous, sourceAssignments: assignments, updatedAt: new Date().toISOString() };
    saveDrafts();
  });

  const exportButton = document.createElement("button");
  exportButton.id = "export-pairing"; exportButton.textContent = "导出配对决定 JSON";
  exportButton.style.cssText = "position:fixed;right:20px;bottom:20px;padding:10px 12px;background:#285842;color:#fffdf8;border:0;cursor:pointer";
  document.body.append(exportButton);
  syncSelection();
}());
