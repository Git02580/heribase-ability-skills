# Acceptance checklist

Use this checklist before declaring a migrated or newly completed task ready for online operations.

- [ ] Task lives at `~/.heribase/user-tasks/<task_key>/` and key/directory/manifest agree.
- [ ] Same-minute slug collisions use deterministic `-02`, `-03` suffixes.
- [ ] Every local, spreadsheet, embedded and remote input has a package-local copy.
- [ ] Every source copy has provenance, size, MIME and verified SHA-256.
- [ ] Every spreadsheet row has a traceable table candidate or documented duplicate relation; each remote front/back URL has either a local `remote_image` source with row locator or an explicit acquisition failure and source-incomplete warning.
- [ ] Every slab-label analysis preserves image evidence, method, time, per-field raw/normalized value, confidence and visible region; unclear PCGS/NGC certification and KM values are not guessed or completed.
- [ ] Every item has immutable `<task_key>:<item_key>` identity; legacy IDs and lineage are preserved.
- [ ] CLI stdout raw JSON is preserved exactly and contains no sensitive key.
- [ ] Normalized service fields use `null` for missing values and trace to raw response/attempt/hash.
- [ ] `identify_uri`, `user_uniq_uri` and `collection_uri` are never inferred.
- [ ] Same-task active `user_uniq_uri` conflicts are resolved or explicitly blocking.
- [ ] Cross-task identical `user_uniq_uri` values link entities without merging task records.
- [ ] JSONL files are valid, hash-chained and append-only; every event is projected into the current snapshot.
- [ ] Single and bulk review actions produce per-item events; recommendations are not user decisions.
- [ ] Low-confidence, missing-side, conflicting or reused evidence has been resolved through pairing decisions before identification; pairing exports bind the current dataset fingerprint and preserve source assignment uniqueness.
- [ ] If pairing review is required for any scatter/table candidate, every slab candidate's label summary appears in the same confirmation list; otherwise the user was asked whether to review label extraction before identification.
- [ ] Browser cache can be cleared and decisions still restore from task logs.
- [ ] Current collection plan binds dataset revision, dataset fingerprint, item versions, decisions, snapshots and identifiers.
- [ ] User authorization matches the exact current plan payload hash.
- [ ] Partial successes, definite failures and `reconcile_required` items are reported separately.
- [ ] Ambiguous online operations were reconciled by read-only query before retry.
- [ ] `integrity.json` validates originals, raw responses, snapshots, logs and schemas.
- [ ] `_catalog` can be rebuilt entirely by scanning task packages.
- [ ] Read-only review service, if used, is loopback-only, GET-only, origin-isolated, path-safe and has no arbitrary CLI proxy.
- [ ] Any future browser-to-disk mutation service additionally enforces an allowlisted origin, per-session CSRF token, typed payloads, revision checks and an authorized-plan gate.
- [ ] Original source directories remain untouched; migration never modifies or deletes `batch_flat`.
- [ ] `task_package.py validate` exits successfully and reports whether online writes are allowed.
