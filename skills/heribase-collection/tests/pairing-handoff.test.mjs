import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../assets/pairing-workbench/pairing-handoff.js", import.meta.url), "utf8");
function api() { const context = vm.createContext({ Object, Set, Map, Date }); vm.runInContext(source, context); return context.CoinPairingHandoff; }

test("配对决定仅导出当前记录并绑定数据集指纹", () => {
  const result = api().buildPackage([{ id: "task:local-01", evidence: [{ sourceId: "source-a", role: "obverse" }] }], {
    "task:local-01": { action: "confirm_pair", updatedAt: "2026-08-28T10:00:00.000Z" },
  }, "2026-08-28T11:00:00.000Z", "a".repeat(64));
  assert.equal(result.schemaVersion, 1);
  assert.equal(result.decisions[0].localId, "task:local-01");
  assert.equal(result.decisions[0].sourceAssignments[0].sourceId, "source-a");
});

test("不接受未知操作或失效时间", () => {
  const result = api().buildPackage([{ id: "one", evidence: [] }], { one: { action: "collect", updatedAt: "bad" } }, "2026-08-28T11:00:00.000Z", "a".repeat(64));
  assert.equal(result.decisions.length, 0);
});

test("确认配对时以用户选定的正反面方向覆盖初始 unknown 标签", () => {
  const result = api().buildPackage([{
    id: "task:local-01",
    evidence: [{ sourceId: "source-a", role: "unknown" }, { sourceId: "source-b", role: "unknown" }],
  }], {
    "task:local-01": {
      action: "confirm_pair", updatedAt: "2026-08-28T11:00:00.000Z",
      sourceAssignments: [{ sourceId: "source-a", role: "obverse" }, { sourceId: "source-b", role: "reverse" }],
    },
  }, "2026-08-28T11:01:00.000Z", "b".repeat(64));
  assert.equal(JSON.stringify(result.decisions[0].sourceAssignments), JSON.stringify([
    { sourceId: "source-a", role: "obverse" }, { sourceId: "source-b", role: "reverse" },
  ]));
});

test("导出时保留批量操作 ID", () => {
  const result = api().buildPackage([{ id: "task:local-01", evidence: [{ sourceId: "source-a", role: "obverse" }] }], {
    "task:local-01": { action: "exclude", updatedAt: "2026-08-28T11:00:00.000Z", batchActionId: "batch-1" },
  }, "2026-08-28T11:01:00.000Z", "c".repeat(64));
  assert.equal(result.decisions[0].batchActionId, "batch-1");
});

test("读取待处理包时绑定显式任务键且不修改草稿", () => {
  const records = [{ id: "task:local-01", evidence: [{ sourceId: "source-a", role: "obverse" }] }];
  records.taskKey = "legacy-records-task-key";
  const drafts = {
    "task:local-01": { action: "confirm_pair", updatedAt: "2026-08-28T11:00:00.000Z" },
  };
  const draftsSnapshot = JSON.stringify(drafts);
  const result = api().readPendingPackage(
    records,
    drafts,
    "d".repeat(64),
    "explicit-task-key",
    "2026-08-28T11:01:00.000Z",
  );
  assert.equal(result.decisions[0].action, "confirm_pair");
  assert.equal(result.datasetFingerprint, "d".repeat(64));
  assert.equal(result.taskKey, "explicit-task-key");
  assert.equal(JSON.stringify(drafts), draftsSnapshot);
});
