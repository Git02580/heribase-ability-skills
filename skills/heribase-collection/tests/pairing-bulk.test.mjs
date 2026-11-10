import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../assets/pairing-workbench/pairing-bulk.js", import.meta.url), "utf8");
const page = readFileSync(new URL("../assets/pairing-workbench/index.html", import.meta.url), "utf8");
const builder = readFileSync(new URL("../scripts/build_pairing_workbench.py", import.meta.url), "utf8");
const interaction = readFileSync(new URL("../assets/pairing-workbench/interaction.js", import.meta.url), "utf8");
function api() {
  const context = vm.createContext({ Object, Set, Map, Array, Date });
  vm.runInContext(source, context);
  return context.CoinPairingBulk;
}

function initializeInteraction(registerTool) {
  const appended = [];
  const document = {
    modelContext: { registerTool },
    querySelectorAll() { return []; },
    querySelector() { return { textContent: "" }; },
    addEventListener() {},
    createElement() { return { style: {} }; },
    body: { append(node) { appended.push(node); } },
  };
  const context = vm.createContext({
    window: { COIN_PAIRING_DATA: { buildMeta: { datasetFingerprint: "fingerprint", taskKey: "task-key" }, records: [] } },
    document,
    navigator: {},
    localStorage: { getItem() { return null; }, setItem() {} },
    Object,
    Set,
    Date,
    JSON,
    Math,
  });
  vm.runInContext(interaction, context);
  return appended;
}

const time = "2026-08-28T11:00:00.000Z";
const records = [
  { id: "ready", needsReview: true, evidence: [{ sourceId: "a", role: "obverse" }, { sourceId: "b", role: "reverse" }] },
  { id: "missing", needsReview: true, evidence: [{ sourceId: "c", role: "unknown" }] },
  { id: "automatic", needsReview: false, evidence: [{ sourceId: "d", role: "obverse" }, { sourceId: "e", role: "reverse" }] },
];

test("按状态全选时保留其他已选候选", () => {
  const selected = api().selectByStatus(records, ["automatic"], true);
  assert.deepEqual([...selected].sort(), ["automatic", "missing", "ready"]);
});

test("清空选择不会改动任何草稿", () => {
  assert.equal(JSON.stringify(api().clearSelection()), JSON.stringify([]));
});

test("批量确认配对会阻止单面或未知方向候选", () => {
  const result = api().applyAction(records, {}, ["ready", "missing"], "confirm_pair", time, "batch-1");
  // vm 模块返回跨 Realm 数组；序列化后比较实际导出内容。
  assert.equal(JSON.stringify(result.affectedIds), JSON.stringify(["ready"]));
  assert.equal(JSON.stringify(result.blockedIds), JSON.stringify(["missing"]));
  assert.equal(result.overwrittenCount, 0);
  assert.equal(result.drafts.ready.action, "confirm_pair");
  assert.equal(result.drafts.ready.batchActionId, "batch-1");
  assert.equal(result.drafts.ready.sourceAssignments, undefined);
});

test("待补图批量操作会覆盖已有草稿并保留每条独立决定", () => {
  const result = api().applyAction(records, { ready: { action: "exclude", updatedAt: time } }, ["ready", "automatic"], "need_photo", time, "batch-2");
  assert.equal(JSON.stringify([...result.affectedIds].sort()), JSON.stringify(["automatic", "ready"]));
  assert.equal(JSON.stringify(result.blockedIds), JSON.stringify([]));
  assert.equal(result.overwrittenCount, 1);
  assert.equal(JSON.stringify(result.drafts.automatic), JSON.stringify({ action: "need_photo", updatedAt: time, batchActionId: "batch-2" }));
});

test("配对页面提供批量控制，并由生成器复制批量逻辑模块", () => {
  assert.match(page, /id="bulk-toolbar"/);
  assert.match(page, /data-bulk-action="confirm_pair"/);
  assert.match(page, /data-select-status="review"/);
  assert.match(builder, /pairing-bulk\.js/);
});

test("候选队列按钮仍绑定详情切换处理", () => {
  assert.match(page, /itemButton\.onclick\s*=/);
});

test("WebMCP 只读工具读取当前暂存的配对决定", () => {
  const registration = interaction.match(/modelContext\.registerTool\(\{[\s\S]*?\n      \}\);/);
  assert.ok(registration, "应注册 WebMCP 工具");
  const block = registration[0];
  assert.match(block, /name:\s*["']get_pending_pairing_decisions["']/);
  assert.match(interaction, /document\.modelContext\s*\|\|\s*navigator\.modelContext/);
  assert.match(block, /inputSchema:\s*\{\s*type:\s*["']object["'],\s*properties:\s*\{\},\s*additionalProperties:\s*false\s*\}/);
  assert.match(block, /readOnlyHint:\s*true/);
  assert.match(block, /CoinPairingHandoff\.readPendingPackage\(/);
  assert.doesNotMatch(block, /fetch\(|task_operations\.py|link\.download/);
});

test("WebMCP 同步注册失败时仍创建 JSON 导出按钮", () => {
  const appended = initializeInteraction(() => { throw new Error("WebMCP unavailable"); });
  assert.equal(appended.length, 1);
  assert.equal(appended[0].id, "export-pairing");
  assert.equal(appended[0].textContent, "导出配对决定 JSON");
});
