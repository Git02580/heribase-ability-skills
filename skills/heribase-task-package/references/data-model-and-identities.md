# Data model and identities

## Local identity

`task_key` identifies the task and never changes. `item_key` identifies one record within it. The permanent local ID is:

```text
<task_key>:<item_key>
```

Recommended item keys:

- local photo candidates: `local-01`, `local-02`, ...
- spreadsheet candidates: `table-001`, `table-002`, ...

Never reuse a retired key. Store historical IDs in `legacy_ids`. A split creates new keys whose `lineage.derived_from` references the source item. A merge creates a new item and marks inputs through `superseded_by`; it never erases history.

For duplicate spreadsheet rows, the grouping key derives from the lowest source row, and all row locators remain in `source_rows` or source claims.

## Service identity

Keep these meanings distinct:

| Field | Meaning | Source |
|---|---|---|
| `identify_uri` | one server-side identification result | identification/query raw response |
| `user_uniq_uri` | one physical coin belonging to the user | verified service response |
| `collection_uri` | successful collection record | collection result/query response |

Missing means JSON `null`. Empty strings, `"unknown"`, em dashes and fabricated placeholders are invalid.

`user_uniq_uri` is the only automatic cross-task physical-entity link. Matching names, year or images may generate a review suggestion but never an automatic link.

The same verified `user_uniq_uri` on two active items inside one task is `identity_conflict` and blocks automatic collection. A new service response that conflicts with a previous verified identity must be retained as a conflicting claim; do not overwrite the current identity silently.

## Item snapshot

`data/items.json` has top-level `schema_version`, `task_key`, `revision`, `updated_at`, and `items`.

An item contains:

- `local_id`, `item_key`, `legacy_ids`, `version`, `status`;
- `lineage.derived_from` and `lineage.superseded_by`;
- `source_refs` and image `evidence`;
- `organization` state, pairing completeness, duplicate group and warnings;
- `field_claims` and `resolved_fields`;
- `active_identification`;
- `review_projection` and `collection_projection`;
- `attention_flags`, `created_at`, `updated_at`.

Evidence roles are `obverse`, `reverse`, `slab`, `label`, `detail`, and `unknown`. Pairing is a claim, not a destructive rename: retain each evidence source, `pair_confidence`, and rationale.

`organization.pairing_suggestions` 保存全量比较产生的最多 3 条图片来源候选。每条建议含两个真实 `source_id`、关系类型、模型估计置信度、可复核理由、支持信号和冲突信号；同一来源对在两端 item 中应保留一致记录。建议不可当作 `source_assignment`、人工决定或服务身份，也不能单独授权识别。配对审核台展示建议与本地原图，供用户比较。

每一条表格候选必须保留表格字段、行定位和正反面 URL 作为来源声明。只有 URL 已成功获取并登记为本地 `remote_image` 来源后，才可加入 `evidence` 并参与配对或识别；URL、字段或下载失败记录本身不能充当视觉证据。表格候选与散图候选看似相同也不得自动合并，必须由高置信规则或已导入的用户配对决定支持。

盒子币标签分析存于 `field_claims.slab_label_analysis`，每项至少具有 `source_id`、`method`、`analyzed_at`、总体置信度和逐字段 `{raw_value, normalized_value, confidence, evidence_region}`。字段可包括 `grading_service`、`certification_number`、`grade`、`designation`、`coin_title`、`year`、`mint_mark`、`denomination`、`km_number`、`barcode` 和 `other_attributes`。它们均为模型可见文本的来源声明：不得从格式、校验位或目录惯例补全；不得写入服务身份字段或用于自动实体关联。标签与裸币图冲突时，创建冲突注意项并让审核决定选择后端检索线索。

## Claims and resolution

Never overwrite spreadsheet/source facts with recognition output. Store both as claims. A claim includes its value, origin type, origin reference, confidence if applicable, and time. A resolved field stores the selected value plus `claim_id` and resolution rule/actor.

When a key field changes, increment `item.version`. Key changes include evidence set/pairing, resolved coin identity, service identifiers, and system eligibility. Existing review decisions and collection plans then become stale. A review decision itself is an event/projection change rather than an evidence-version change; a changed decision invalidates a plan through its bound `decision_id`.

The dataset fingerprint covers sources and review-relevant item facts, but excludes rebuildable `review_projection`, `collection_projection`, and display-only `updated_at`. Otherwise persisting a decision would invalidate the same decision immediately. A changed user decision still invalidates an existing collection plan through its bound `decision_id`.

## Recognition projection

`active_identification` includes:

- `attempt_id`, `snapshot_id`, status;
- the four recognition service fields;
- `raw_response_ref` and `raw_response_sha256`;
- `recognized_at`.

All normalized service values must be traceable to this raw response. The raw object preserves unknown fields and nesting exactly.

## Review and collection projections

Projections are conveniences rebuilt from logs; logs remain the historical facts.

`review_projection` records the latest effective decision, its event, actor, item version and stale status.

`pairing_projection` records the latest effective pairing decision、来源分配、事件 ID、item version 和过期状态。每个活动的本地图片证据在同一时刻只能分配给一个活动候选；拆分、合并或重分配必须保留 lineage、递增相关 item version，并使识别、审核和未执行收藏计划过期。

`collection_projection` records the effective state, operation ID, `collection_uri`, `user_uniq_uri`, raw response reference and last error. Missing `collection_uri` after an apparently successful write is not success; mark `reconcile_required`.

## Global entity catalog

`_catalog/entities.json` maps a verified `user_uniq_uri` to references such as:

```json
{
  "user_uniq_uri": "...",
  "members": [
    {"task_key": "...", "local_id": "...", "collection_uri": null}
  ]
}
```

Keep task records separate. The catalog is reconstructable by scanning valid task snapshots. One `collection_uri` associated with multiple `user_uniq_uri` values is a severe conflict and must be surfaced.
