# Operations and audit

## JSONL envelope

All append-only logs are UTF-8 JSON Lines. Each complete line is one object with:

- document-specific `schema_version`;
- event or attempt ID, preferably UUIDv7;
- `task_key` and ISO timestamp;
- monotonically increasing `sequence`;
- `previous_event_sha256` (`null` for the first line);
- `event_sha256` computed from canonical JSON excluding `event_sha256`.

Flush and `fsync` the log before updating snapshots. A truncated final line may be quarantined during explicit recovery with an audit event. A malformed complete line is inconsistent data and must not be skipped.

## Recognition attempts

`recognition/attempts.jsonl` records:

- `attempt_id`, `local_id`, `attempt_number`, `operation_type`, `status`;
- input item version, evidence IDs and evidence hashes;
- sanitized command name and arguments;
- remote task ID if returned;
- start/end time, exit code and result classification;
- raw response reference/hash or structured error.

Statuses: `queued`, `uploading`, `requested`, `polling`, `succeeded`, `failed_retryable`, `failed_terminal`, `cancelled`, `unknown`.

Upload completion is not identification success. Unknown remote terms remain `unknown`; query them. Every retry is a new attempt.

## Review decisions

`review/decisions.jsonl` records:

- `decision_id`, `local_id`;
- action `set`, `clear`, or `revert`;
- decision `collect`, `need_photo`, `exclude`, or `null` as allowed by action;
- note and actor;
- interaction source `single`, `bulk`, `import`;
- optional `batch_action_id` or `import_ref`;
- the item version, identification snapshot and dataset fingerprint shown to the user;
- optional `supersedes` or `reverts`;
- creation time.

Bulk UI actions generate one event per item. Sharing `batch_action_id` preserves one-click semantics without losing per-item auditability. Agent recommendations never become user decisions automatically.

## Collection plan

`collection/plan.json` is a single current authorization artifact. It contains:

- `plan_id`, `task_key`, status;
- operation type and creation time;
- based-on dataset revision and dataset fingerprint;
- exact included records, bound versions, decisions, recognition snapshots and service IDs;
- exclusions with reasons;
- impact counts and fee information (`null` plus an explicit unknown flag when unknown);
- canonical `payload_sha256`;
- user authorization metadata.

Statuses: `draft`, `awaiting_confirmation`, `authorized`, `executing`, `consumed`, `cancelled`, `stale`.

Confirmation binds the payload hash. Recompute the hash immediately before writing. Any difference, or any item/version/decision/evidence/identity change, makes the plan stale.

For `collection_update` and `collection_cancel`, each planned item additionally binds its current verified `collection_uri` and a typed `changes` object. Updates require a non-empty changes object; cancellations require an empty one. Both use the same payload authorization and preflight gate as add operations. The browser or intent file must never supply a command line.

## Collection attempts

Every item is its own atomic operation in `collection/attempts.jsonl`. Record:

- `operation_id`, `attempt_id`, `plan_id`, `local_id`, `attempt_number`;
- operation type `collection_add`, `collection_update`, or `collection_cancel`;
- status;
- expected item version, `identify_uri`, and `user_uniq_uri`;
- sanitized CLI call, times, exit code and classification;
- raw response reference/hash;
- result `collection_uri` and `user_uniq_uri`;
- structured error.

Statuses: `queued`, `executing`, `succeeded`, `failed_retryable`, `failed_terminal`, `reconcile_required`, `cancelled`.

An exit code alone never proves business success. Require a valid response and real `collection_uri`. Preserve partial successes. Retry only failures, with a new attempt, and only within the original authorized scope. If the operation may have succeeded remotely, reconcile by read-only query before retrying.

## Raw response rules

The raw file is the exact parsed stdout JSON object serialized without field deletion or remapping. Write it first to a temporary file in the destination directory, scan all nested keys case-insensitively, then atomically rename it.

Reject raw persistence if any key indicates credentials or secrets, including `authorization`, `cookie`, `set-cookie`, `access_token`, `refresh_token`, `password`, `secret`, `private_key`, and obvious variants. Do not silently redact and then describe the file as raw.

## Audit log

`audit/events.jsonl` records material state transitions: task state changes, imports, pairing/split/merge, recognition results, review changes, plan generation/authorization/staleness, online outcomes, identity conflicts, migration, repair and integrity checks.

Events include entity reference, actor, correlation ID, before/after summaries, safe details and timestamp. Never include credentials, cookies, passwords, private keys or unfiltered environment data.

## Local service requirements

If a browser workbench writes task data, use a local service that:

- binds only `127.0.0.1`;
- enforces an allowlisted origin and random per-session CSRF token;
- accepts identifiers and typed payloads, never arbitrary paths or commands;
- validates task revision and item version;
- cannot access outside `~/.heribase/user-tasks/`;
- exposes only explicit task operations, not a generic shell/CLI proxy;
- routes all online writes through a validated authorized plan.
