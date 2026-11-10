---
name: heribase-task-package
description: Use when creating, importing, validating, recovering, migrating, or maintaining a HeriBase coin task package under ~/.heribase/user-tasks; when coin photos, spreadsheet rows, recognition results, review decisions, and collection outcomes need stable local identities, immutable raw responses, append-only audit logs, integrity checks, or cross-task entity linking. Also use before any HeriBase online collection write to validate the confirmed collection plan. Do not use for general-purpose folders or direct HeriBase CLI authentication.
compatibility: Python 3.9+; local filesystem access; HeriBase CLI only through the companion heribase-cli skill.
---

# HeriBase Task Package

## 工作空间集成

收藏默认由 [heribase-collection](../heribase-collection/SKILL.md) 在当前聊天中组织，复用 [heribase-workspace](../heribase-workspace/SKILL.md) 的常驻服务；统一使用“添加钱币”入口接收任意数量的资料，自动整理、配对及批量能力继续保留；需要纠正或核对时才打开相应步骤。本 Skill 继续是任务证据和受控事务的唯一契约。网页与聊天都使用当前 revision，写入后工作空间读取同一任务包；不复制一套可独立编辑的 items 快照。旧配对页和 WebMCP 作为兼容入口保留。配对变化会使旧识别、审核和未执行计划失效，原始响应及已完成收藏不丢弃。

## Purpose

This skill is the authoritative local data layer for a HeriBase coin workflow. It turns each job into a self-contained, recoverable and auditable package under `~/.heribase/user-tasks/<task_key>/`.

It does not identify coins by itself and does not proxy arbitrary CLI commands. Use `heribase-collection` for user-facing workflow and `heribase-cli` for real HeriBase service calls.

## 安装与环境依赖

本 Skill 需要 Python 3.9+ 与本地文件系统访问权限；执行线上操作时还依赖已安装的 `heribase-cli`。基础环境、CLI 安装和初始化见 [统一安装说明](../heribase-cli/references/installation.md)。

## Non-negotiable boundaries

1. Only manage `~/.heribase/user-tasks/`, or an explicit temporary root used for testing.
2. Never read or modify `~/.heribase/auth.json`, CLI config, cookies, tokens, environment secrets, or files outside the selected task root.
3. Never accept an arbitrary filesystem path from a browser request. Resolve validated `task_key`, `local_id`, and relative paths server-side.
4. Never infer `identify_uri`, `user_uniq_uri`, or `collection_uri`. They must trace to a real CLI raw response or a read-only reconciliation.
5. Never treat browser `localStorage` as authoritative. Persist decisions as append-only events.
6. Never perform an online collection write without a current, user-confirmed `collection/plan.json` whose payload hash still matches.
7. Never silently repair corruption, skip malformed complete log lines, or blind-retry an ambiguous online result.

## Standard workflow

### 1. Create or open a task

For a new task, run:

```bash
python3 <skill-dir>/scripts/task_package.py create \
  --display-name "待整理硬币" \
  --slug batch-flat \
  --timezone Asia/Shanghai
```

This skill's CLI command creates `~/.heribase/user-tasks/YYYYMMDD-HHmm-<slug>/`. Same-minute collisions receive `-02`, `-03`, and so on. The new task's `display_name` automatically receives the creation time in the selected timezone as the `YYYYMMDD-HHmm-` prefix; if the supplied name already starts with that timestamp format, the script does not add a duplicate prefix. Collision suffixes only affect `task_key`, not `display_name`. `task_key` is immutable; `display_name` may change. Other callers that invoke the shared creation function directly keep their existing display-name behavior.

Before modifying an existing task, validate it:

```bash
python3 <skill-dir>/scripts/task_package.py validate --task-key <task_key>
```

Stop online operations when validation returns `data_inconsistent` or a non-zero exit.

### 2. Ingest all evidence

Copy, never move, source spreadsheets, local images, documents, embedded spreadsheet images, and remote images into `inputs/`. Record each source in `inputs/sources.json` with original location, package-relative stored path, MIME type, byte size, SHA-256, acquisition time, parent source, and spreadsheet locator where applicable. 对电子表格，必须逐行保留原字段、工作表/行/列定位和图片 URL；每个远程正反面 URL 都要独立获取、归档为带父表格来源和行定位的 `remote_image`。失败不能静默跳过，必须保留 URL、失败原因、时间和受影响候选的待补图状态。

The finished package must remain reviewable offline after original directories and URLs disappear. A failed remote image acquisition makes the package incomplete and blocks that item's online operation; a table row that only retains fields or URLs is a source claim, not visual evidence.

Use the guarded transaction command for every acquired file:

```bash
python3 <skill-dir>/scripts/task_operations.py ingest-source \
  --task-key <task_key> --expected-revision <revision> \
  --file <local-copy> --kind local_image
```

Follow [task-package-layout.md](references/task-package-layout.md) and [data-model-and-identities.md](references/data-model-and-identities.md).

### 3. Normalize items without losing provenance

Write the current snapshot to `data/items.json`. Each item has:

- immutable `local_id` equal to `<task_key>:<item_key>`;
- source and image evidence references;
- independent source claims and recognition claims;
- optional multimodal slab-label claims, each bound to an image source and its visible region;
- explicit resolved fields that point back to claims;
- recognition, review and collection projections;
- lineage, warnings and attention flags.

Use `null` for unavailable service facts. Preserve old IDs in `legacy_ids`. Never reuse a deleted item key. Never auto-link physical coins using name, year, or image similarity; only identical verified `user_uniq_uri` creates a cross-task entity link.

盒标多模态结果只能写入 `field_claims.slab_label_analysis`：每个值保留原文、规范化值、字段置信度、证据 `source_id`、可见区域、分析方法和时间。PCGS/NGC 认证编号、等级、KM 编号、条码或盒标币种字段都是定位线索，不是服务端身份；模糊字符必须为 `null`/待复核，不能按格式补全。

Import a schema-valid snapshot with `task_operations.py import-items`; do not hand-edit `items.json` during a live task.

### 4. Store recognition facts in two layers

For every CLI recognition/query operation:

1. Save the exact stdout JSON object as an immutable file in `recognition/raw/<attempt_id>.json`.
2. Reject the save if it contains sensitive key names such as authorization, cookie, token, password, secret or private key; write a safe audit failure instead.
3. Append a recognition attempt event with command metadata, input evidence hashes, status, raw path and raw SHA-256.
4. Project normalized service fields into `items.json`, each linked to `attempt_id` and `raw_response_ref`.

A response that contradicts an existing `user_uniq_uri` creates `identity_conflict`; do not replace it silently. Unknown remote status stays unknown and must be queried.

Persist the attempt with `task_operations.py record-recognition --event-json <event> --raw-json <stdout-json>`.

### 5. Persist review decisions

Every user action appends one `review/decisions.jsonl` event. A bulk action still writes one event per item, sharing a `batch_action_id`. Agent recommendations are separate from user decisions.

Each decision binds the item version, recognition snapshot, dataset revision, and dataset fingerprint that the user saw. Changes to evidence, resolved identity or other critical fields make the decision stale.

Import the workbench's schema v2 JSON using `task_operations.py import-review`. It validates the fingerprint and converts bulk or single decisions into per-item hash-chained events.

### 5a. Persist pairing decisions before identification

照片配对审核使用独立的 `pairing/decisions.jsonl` 与交接包，不能复用收藏审核决定。低于 0.85 的配对、缺面、冲突或图片重用必须先经配对审核。配对审核台可以批量生成浏览器草稿，但交接包仍必须为每个 `local_id` 提供独立决定；同一批次可带可选 `batchActionId`，导入时记录为交互批次关联，不能作为单条“批量决定”替代逐项事件。默认从页面只读 WebMCP 工具 `get_pending_pairing_decisions` 取得当前包；该工具没有输入、不能写入任务包，也不能替代 `import-pairing`。若 WebMCP 缺失、注册失败或调用失败，才使用用户导出的同 schema JSON。导入时必须验证 dataset fingerprint、item version、来源存在性和活动本地图片的唯一归属；配对变化递增 `dataset_revision` 并使相关识别、审核与未执行计划过期。

### 6. Build and confirm an online plan

Before any remote write, create `collection/plan.json` containing the exact eligible records and exclusions. The plan binds dataset revision, dataset fingerprint, item versions, user decisions, recognition snapshots and all service identifiers. Compute `payload_sha256` over canonical plan payload.

Show the user impact counts, excluded records, unknown fees and the exact intended operation. Record explicit confirmation in the plan. Any bound-field change makes it `stale` and requires a new plan and confirmation.

See [operations-and-audit.md](references/operations-and-audit.md).

Create and authorize plans only through:

```bash
python3 <skill-dir>/scripts/task_operations.py build-plan --task-key <task_key> --expected-revision <revision>
python3 <skill-dir>/scripts/task_operations.py authorize-plan --task-key <task_key> \
  --expected-revision <revision> --plan-id <plan_id> \
  --confirmed-payload-sha256 <sha256> --confirmed-by <user>
python3 <skill-dir>/scripts/task_operations.py preflight-plan --task-key <task_key>
```

For an existing collection update or cancellation, first write a typed intent file containing only `local_id` and `changes`, then build the same protected plan:

```json
{"operations":[{"local_id":"<task_key>:local-01","changes":{"notes":"重点关注"}}]}
```

```bash
python3 <skill-dir>/scripts/task_operations.py build-plan --task-key <task_key> \
  --expected-revision <revision> --operation collection_update \
  --operations-json <intent.json>
```

Use `collection_cancel` with an empty `changes` object for cancellation. The task must already contain a verified `collection_uri`; the resulting plan still requires payload-bound authorization and immediate preflight. Never put CLI arguments, credentials or arbitrary paths in the intent file.

### 7. Execute atomically per item

For each authorized item, append an operation attempt and store the exact CLI response in `collection/raw/`. Success requires a real `collection_uri`. Partial success is valid: keep successes, expose failures, and retry only failed items with a new attempt.

Timeout, crash, missing `collection_uri`, or uncertain response becomes `reconcile_required`. Use a read-only query before any retry. A changed operation scope requires new user confirmation.

Persist each result with `task_operations.py record-collection`; this command downgrades a nominal success without a valid `collection_uri` to `reconcile_required`.

### 8. Refresh integrity and catalog

After controlled updates, refresh package integrity:

```bash
python3 <skill-dir>/scripts/task_package.py refresh-integrity --task-key <task_key>
```

If controlled snapshot/log/manifest files intentionally changed, first verify that exact change set and add `--expected-revision <revision> --accept-controlled-changes`. The utility refuses to re-baseline modified or removed source originals, remote/extracted evidence, raw CLI responses, or copied Schemas. New immutable evidence and raw responses must enter through `task_operations.py`, which registers them before refreshing integrity.

Rebuild global catalogs when tasks or verified entities change:

```bash
python3 <skill-dir>/scripts/task_package.py rebuild-catalog
```

Catalogs are derived. Catalog rebuild failure never rolls back a valid task write; mark it pending and retry.

### 9. Migrate copied schemas only through a named transaction

任务包会复制并完整性保护其 Schema。模板升级若删除 `currency_number`、`uniq_uri` 等已废弃投影字段，不能手改任务内 `schemas/` 或使用 `refresh-integrity` 重设基线；必须运行受控迁移：

```bash
python3 <skill-dir>/scripts/task_operations.py migrate-drop-sensitive-identifiers \
  --task-key <task_key> --expected-revision <revision> --actor <actor>
```

迁移只会替换受影响的复制 Schema、删除快照与计划中的这两个字段、使受影响的审核/收藏计划失效并追加审计事件；它会先拒绝任何其他完整性差异，且绝不改写原始服务响应。

## Write and recovery protocol

For any mutation: acquire the per-task lock, check expected revision/item version, save and scan raw response, append and fsync the event, atomically replace the snapshot, update manifest revision/statistics, refresh integrity, then release the lock.

Use [integrity-recovery-and-migration.md](references/integrity-recovery-and-migration.md) for crash recovery, tamper handling and legacy `batch_flat` migration.

## Required validation before completion

Run at minimum:

```bash
python3 <skill-dir>/scripts/task_package.py validate --task-key <task_key>
python3 <skill-dir>/scripts/task_package.py rebuild-catalog
```

Report the task path, task key, data health, item counts, unresolved identity conflicts, incomplete sources, stale decisions, plan state, retry/reconciliation items, and whether online writes are currently allowed.

Do not claim completion if the package is not self-contained, if integrity fails, or if a required service identifier was inferred rather than evidenced.

## Resources

- [Task package layout](references/task-package-layout.md)
- [Data model and identities](references/data-model-and-identities.md)
- [Operations and audit](references/operations-and-audit.md)
- [Integrity, recovery and migration](references/integrity-recovery-and-migration.md)
- [Acceptance checklist](references/acceptance-checklist.md)
- JSON Schemas in `assets/schemas/`
- Deterministic package utility in `scripts/task_package.py`
- Guarded workflow transactions in `scripts/task_operations.py`
