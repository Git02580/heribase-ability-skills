# Task package layout

## Canonical root

Production tasks live only under:

```text
~/.heribase/user-tasks/
├── _catalog/
│   ├── tasks.json
│   └── entities.json
├── _runtime/
│   └── locks/
└── <task_key>/
```

`_catalog` and `_runtime` are reserved names. A task key must match `YYYYMMDD-HHmm-<slug>` with optional deterministic collision suffix `-02`, `-03`, etc. The directory name, `manifest.task_key`, and every record's `task_key` must agree.

## Package tree

```text
<task_key>/
├── manifest.json
├── README.md
├── integrity.json
├── schemas/
│   ├── manifest.schema.json
│   ├── sources.schema.json
│   ├── items.schema.json
│   ├── recognition-attempt.schema.json
│   ├── pairing-decision.schema.json
│   ├── pairing-export.schema.json
│   ├── review-decision.schema.json
│   ├── review-export.schema.json
│   ├── collection-plan.schema.json
│   ├── collection-operation.schema.json
│   ├── audit-event.schema.json
│   └── integrity.schema.json
├── inputs/
│   ├── sources.json
│   ├── originals/
│   │   ├── spreadsheets/
│   │   ├── images/
│   │   └── documents/
│   ├── remote-images/
│   └── extracted/spreadsheet-images/
├── data/items.json
├── recognition/
│   ├── attempts.jsonl
│   └── raw/
├── pairing/
│   ├── decisions.jsonl
│   └── exports/
├── review/
│   ├── decisions.jsonl
│   └── exports/
├── collection/
│   ├── plan.json
│   ├── attempts.jsonl
│   └── raw/
├── audit/events.jsonl
└── derived/
    ├── review-dataset.json
    ├── review-workbench/
    │   ├── index.html
    │   ├── review-handoff.js
    │   └── review-data.js
    └── reports/
```

`pairing/` may be absent only for a legacy task that has never needed pairing review; controlled migration creates it before importing a pairing package. `collection/plan.json` is conditional: it may be absent until a plan is generated. An absent plan means no online operation is authorized.

## Path rules

- All paths stored inside JSON are POSIX-style and relative to the task root.
- Reject absolute paths, `..`, empty path components and NUL bytes.
- Reject every symbolic link inside a package, even if it currently resolves within the package.
- Resolve package paths against a validated `task_key`; never concatenate browser-provided paths.
- `origin.original_path` is provenance only and may be absolute. It is removed or relativized from exported/sharable packages.
- Do not use `origin.original_path` as a live read path after ingestion.

## `manifest.json`

Required fields:

- `schema_version`: `heribase.task-manifest.v1`
- immutable `task_key`
- editable `display_name` and optional `description`
- `created_at`, `updated_at`: ISO 8601 timestamps with offsets
- `created_timezone`: IANA timezone such as `Asia/Shanghai`
- positive `revision` for every committed package mutation
- positive `dataset_revision` for review-relevant source/item changes
- `state`
- `data_health`
- per-document `schema_versions`
- recomputable `statistics`
- `dataset_fingerprint`
- `created_by`

State values:

```text
received
indexing
grouping
awaiting_precheck
identification_pending
identifying
identification_review
awaiting_collection_confirmation
collecting
completed
completed_with_exceptions
cancelled
data_inconsistent
```

The task state describes workflow progress; `data_health` separately describes whether persisted facts are trustworthy. `data_inconsistent` blocks remote writes. `revision` advances for every committed transaction, while `dataset_revision` advances only when sources, evidence, organization, resolved facts or identification identity changes. Review decisions and plan/operation lifecycle changes advance `revision` but not `dataset_revision`; plans bind `dataset_revision`, item versions, decision IDs and the dataset fingerprint separately.

## `inputs/sources.json`

Top-level fields are `schema_version`, `task_key`, `revision`, `updated_at`, and `sources`.

Each source has:

- stable `source_id`;
- `kind`: local image, spreadsheet, document, remote image or extracted image;
- `origin`: type, original name, original path and/or URL;
- package-relative `stored_path`;
- `mime_type`, `byte_size`, `sha256`, `acquired_at`;
- optional `parent_source_id`;
- optional spreadsheet `locator` with sheet, row, column, cell and relationship ID;
- `integrity_status`.

For a spreadsheet image URL, `parent_source_id` points to the spreadsheet, and `locator` identifies the exact row and URL column; a successful download is a distinct `remote_image` source even if the byte hash is shared. Identical file hashes may share a physical stored file, but every distinct provenance location keeps its own source record. Original files are copied, never moved.

## Immutability classes

- Immutable: `inputs/originals/**`, `inputs/remote-images/**`, `inputs/extracted/**`, `recognition/raw/**`, `collection/raw/**`, historical JSONL lines.
- Controlled mutable: `manifest.json`, `inputs/sources.json`, `data/items.json`, `collection/plan.json`, `integrity.json`.
- Rebuildable: `derived/**`, `_catalog/**`.

Changing an immutable file is corruption, not an edit.
