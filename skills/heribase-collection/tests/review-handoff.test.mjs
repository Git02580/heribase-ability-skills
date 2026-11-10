import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../assets/review-workbench/review-handoff.js", import.meta.url), "utf8");

function loadApi() {
  const context = vm.createContext({ structuredClone, Object, Set, Map, Date });
  vm.runInContext(source, context);
  return context.CoinReviewHandoff;
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("schema v2 导出绑定数据集指纹并过滤无效记录", () => {
  const api = loadApi();
  const result = api.buildPackage(
    [{ id: "task:local-01", sourceRows: [] }],
    {
      "task:local-01": { decision: "collect", updatedAt: "2026-08-28T10:00:00.000Z", source: "single" },
      stale: { decision: "exclude", updatedAt: "2026-08-28T10:00:00.000Z" },
    },
    "2026-08-28T11:00:00.000Z",
    { datasetFingerprint: "a".repeat(64) },
  );
  assert.equal(result.schemaVersion, 2);
  assert.equal(result.datasetFingerprint, "a".repeat(64));
  assert.equal(result.decisions.length, 1);
  assert.equal(result.decisions[0].recordId, "task:local-01");
});

test("批量收藏阻断未识别项并为每项保留 batchActionId", () => {
  const api = loadApi();
  const records = [
    { id: "one", systemStatus: "collect" },
    { id: "two", systemStatus: "review" },
    { id: "three", systemStatus: "unidentified" },
  ];
  const preview = api.previewBulkDecision(records, {}, ["one", "two", "three"], "collect");
  assert.deepEqual(plain(preview.eligibleIds), ["one"]);
  assert.deepEqual(plain(preview.warningIds), ["two"]);
  assert.deepEqual(plain(preview.blockedIds), ["three"]);
  const applied = api.applyBulkDecision({}, preview, "collect", "2026-08-28T11:00:00.000Z", "batch-1");
  assert.equal(applied.decisions.one.batchActionId, "batch-1");
  assert.equal(applied.decisions.two.batchActionId, "batch-1");
  assert.equal(applied.decisions.three, undefined);
});

test("v2 导入拒绝另一数据集的决定", () => {
  const api = loadApi();
  const result = api.parseImportedPackage(
    {
      schemaVersion: 2,
      datasetFingerprint: "a".repeat(64),
      decisions: [],
    },
    [],
    "b".repeat(64),
  );
  assert.equal(result.ok, false);
  assert.equal(result.reason, "dataset-mismatch");
});

test("WebMCP 仅注册无输入只读工具", async () => {
  const api = loadApi();
  const tools = [];
  const result = await api.registerReadOnlyTools(
    { async registerTool(tool) { tools.push(tool); } },
    () => ({ schemaVersion: 2, datasetFingerprint: "a".repeat(64), decisions: [], summary: {} }),
  );
  assert.equal(result.registered, true);
  assert.deepEqual(plain(tools.map((tool) => tool.name)), ["get_review_decisions", "get_review_decision_summary"]);
  assert.ok(tools.every((tool) => tool.annotations.readOnlyHint === true));
  assert.ok(tools.every((tool) => tool.inputSchema.additionalProperties === false));
  const summary = await tools[1].execute();
  assert.equal(summary.datasetFingerprint, "a".repeat(64));
});
