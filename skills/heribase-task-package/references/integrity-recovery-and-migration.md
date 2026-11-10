# Integrity, recovery and migration

## Integrity manifest

`integrity.json` records `schema_version`, `task_key`, task revision, generation time, protected files and `package_sha256`.

Each protected entry contains relative path, role, byte size, SHA-256, and for logs the last sequence/event ID. Exclude `integrity.json` itself and rebuildable `derived/**`. Protect source metadata, original/evidence files, schemas, item snapshot, raw responses and logs.

The package digest is SHA-256 over deterministic lines containing path, byte size and file hash in path order. A changed original or raw response is corruption.

New evidence and new raw responses may be added only as part of a controlled, revisioned transaction and must already be referenced by `sources.json`, an attempt event, or an item projection before integrity is refreshed. Once present in an integrity baseline, their bytes are immutable. Existing JSONL bytes must remain an exact prefix of the new log; only valid appended lines are allowed.

## Lock and commit sequence

Use `~/.heribase/user-tasks/_runtime/locks/<task_key>.lock` with a short lease and owner metadata. Never hold a lock while waiting for user input or a long remote operation.

For a local commit:

1. Acquire lock and reject a live competing owner.
2. Revalidate expected task revision and item version.
3. Validate current integrity and identity constraints.
4. If present, write raw response to temp file, scan secrets, `fsync`, and atomically rename.
5. Append event, `fsync` log.
6. Build new snapshot in the same directory, `fsync`, atomically replace.
7. Update manifest revision/statistics/fingerprint atomically.
8. Refresh integrity.
9. Release lock.

The remote CLI call itself occurs outside a long-held filesystem lock. Reacquire and revalidate before recording its response. This prevents UI edits from being silently overwritten.

## Recovery matrix

| Observation | Classification | Required action |
|---|---|---|
| log contains event absent from snapshot | recoverable | replay log, write snapshot, audit repair |
| raw response exists without referencing log | orphan response | inspect correlation, attach or quarantine, audit |
| snapshot revision greater than manifest | interrupted manifest update | verify logs/raw, advance manifest, audit |
| manifest revision greater than snapshot | inconsistent | block writes; rebuild snapshot from logs or restore backup |
| final JSONL line truncated | recoverable tail | quarantine exact bytes, truncate explicitly, audit |
| complete JSONL line malformed/hash broken | corruption | block writes; do not skip |
| online command timed out/crashed | reconcile required | perform read-only service query before retry |
| integrity mismatch in original/raw | corruption | preserve evidence, block writes, investigate |

Repairs never delete the only copy of evidence. Keep quarantined bytes and produce an audit event.

## Catalog recovery

`_catalog/tasks.json` and `_catalog/entities.json` are derived. Rebuild by scanning valid task directories, manifests and item snapshots. A catalog failure does not roll back an already committed task mutation; expose rebuild-pending status.

Detect:

- duplicate active `user_uniq_uri` inside a task;
- one `collection_uri` mapped to multiple `user_uniq_uri` values;
- references to missing tasks/items;
- invalid or inconsistent tasks, which must be listed but excluded from trusted entity resolution.

## Legacy `batch_flat` migration

Migration is additive and non-destructive:

1. Create a new task using the actual migration date/time. Preserve earlier observed dates in migration metadata, not in `task_key`.
2. Copy all local images, spreadsheets, CSV/Markdown files and derived data. Do not modify or remove `batch_flat`.
3. Download every referenced remote spreadsheet image into `inputs/remote-images/`; record failures and mark affected items `source_incomplete`.
4. Convert records to stable task IDs (`local-*`, `table-*`) and preserve former IDs in `legacy_ids`.
5. Treat existing `identification.recordId` only as a pending-verification `identify_uri` claim until a read-only CLI query confirms it.
6. Save each query response in raw form, then normalize `identify_uri` and `user_uniq_uri` with traceability.
7. Import browser decisions from JSON or WebMCP as review events with `interaction_source: import` and an `import_ref`.
8. Convert historical collection drafts/outcomes. If a result lacks a raw response and verifiable `collection_uri`, mark `reconcile_required` rather than success.
9. Produce migration and integrity reports under `derived/reports/`.
10. Validate offline completeness and package integrity before enabling online operations.

## Copied schema migration

任务内 `schemas/` 是完整性保护对象，不能通过普通刷新重设基线。对于已知的 `currency_number`、`uniq_uri` 字段移除，使用 `task_operations.py migrate-drop-sensitive-identifiers`；它在任务无其他完整性差异时才替换复制 Schema，并审计性地删除快照/计划投影。任何既有原始响应都保持不变；若计划受影响，必须标记为过期并重新确认。

## Archive/export rules

Before archive or transfer, run full validation. Remove or relativize local absolute provenance paths from the exported copy, never from the authoritative local task. Do not export `_runtime`. Include schemas and integrity metadata so another system can validate the package independently.
