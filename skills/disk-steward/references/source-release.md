# Releasing verified source files

This operation permanently deletes the ordinary source files in a successfully verified copy plan. It bypasses the Recycle Bin and has no automatic rollback. The retained target copy is the recovery source. It is native Windows only; do not substitute an unlocked deletion command on other hosts or after a lock/API failure.

Prepare a release plan only after checking representative destination files and confirming the user's intended keep/delete choices:

```text
python scripts/source_release.py plan --copy-plan <copy-plan.json> --copy-receipt <copy-receipt.json> --output <new-release-plan.json>
```

The helper verifies the copy receipt belongs to the copy plan, hashes source and target afresh, and creates a distinct release ID. Present exact source root and file list, retained destination, logical bytes, same/cross-volume status, permanent deletion and the fact that source directories and unselected files remain. Existing approval may cover this exact scope; otherwise obtain it before execution. A broad free-space target or copy-only approval does not cover permanent removal.

```text
python scripts/source_release.py apply --plan <release-plan.json> --approve <release-plan-id> --receipt <new-release-journal.jsonl>
```

Keep all plans and receipts outside both trees. `apply` reserves an exclusive new journal before mutation, checks the entire approved source selection and retained-copy snapshot again, then opens each pair with native Windows handles. It hashes both under locks, marks the source handle for deletion, and closes it while retaining the target lock. Lock failures stop the operation; it never forces another application closed. It deletes no directories and does not enumerate newly created source files for deletion.

The journal is **JSONL**, one event per line. `deleting` is intent, `deleted` records completion, and `finished` carries `complete`, `partial` or `failed`. An interrupted log with no final event is not success; a pending `deleting` event requires checking that source path and its retained counterpart. A partial operation does not undo earlier removals. Do not auto-retry or reuse a stale plan after a partial run. Preserve the journal, verify remaining files, and prepare a newly scoped recovery/copy workflow.

`logical_source_bytes_removed` is content length, not guaranteed disk space. `observed_free_delta_bytes` is the source volume's measured net free-space change during release; concurrent activity may change it or even make it negative. Copying and releasing on the same volume is not a net capacity strategy across the whole workflow. Cross-volume copying is needed to move usage off C.

The source/target files are locked pairwise, not the whole directory tree. Ancestor path swapping, hostile concurrent actors, power-loss recovery guarantees, application migration, full ACL preservation and storage-device failure are outside this alpha's guarantees.

For schema 3 copies prepared with `--preserve-zone-identifier`, [marker preservation](zone-identifier.md) also participates in the receipt, fresh hashes, retained manifest and native handle checks. Retained markers deny writing/deletion until the source closes. A source marker must share deletion and is checked for pending removal; do not describe its deletion as locked out. Existing-stream locks do not freeze the stream-name inventory, so writers must be closed. Marker logical bytes are reported separately from primary file length and physical free-space change.

Native behavior references: [CreateFileW sharing modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew), [SetFileInformationByHandle disposition](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle).
