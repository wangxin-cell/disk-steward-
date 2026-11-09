# Application registration and suspected leftovers

Use this when a user wants to understand application-owned space or a suspected uninstall remnant. The helper supplies **registration-path evidence**, not an orphan detector or a deletion decision. A registration can be stale; an unregistered program can still be installed, portable, shared or needed.

## Collect a local snapshot

With the existing task's scope, on native Windows:

```text
python scripts/app_inventory.py collect --output <new-applications.json>
```

The collector reads only the local machine and current user's standard `Software\Microsoft\Windows\CurrentVersion\Uninstall` registrations, requesting the 32-bit and 64-bit registry views separately. It reads `DisplayName`, `DisplayVersion`, `Publisher` and `InstallLocation`. It does not query `UninstallString`, invoke an installer, use `Win32_Product`, write registry keys, enumerate another user's hive, or open registered application folders.

`--max-entries <count>` bounds examined subkeys across all four requested scopes (default and maximum 1,000). Access failures, unusable values and budget exhaustion remain visible. Missing registry values stay unknown. Environment-variable paths are not expanded, and executable paths/commands are not derived from display names. Shared registry views can yield duplicate registrations; do not interpret their count as a unique application count. The two view requests do not inventory every architecture-specific Windows/ARM installation context.

Save this snapshot outside scanned/copied trees and keep it private: application names, versions, publishers and locations can reveal how a computer is used. Collecting a snapshot does not upload it, but sharing it with a hosted model follows that host's data handling. Do not collect an application inventory merely because a generic disk-space scan is available.

## Add evidence to the decision report

```text
python scripts/decision_report.py --plan <plan.json> --applications <applications.json> --output <new-review.md>
```

This rendering step reads the supplied JSON only. It does not re-query Windows or inspect paths in either file. Use snapshots from the relevant machine and explain their dates; input JSON has no authenticity signature and is not a live-state assertion.

| Result | Interpretation | Next step |
|---|---|---|
| A candidate is within a registered installation location | A registry record names an overlapping path; contents and current installation state remain unverified | Confirm the product in Windows Installed apps or its own settings; review supported removal/migration procedures |
| A directory contains one or more registered locations | The aggregate includes application paths; it may also contain unrelated files | Review individual subdirectories and shared dependencies; do not assign the whole directory to one app |
| Multiple registrations overlap | Several records provide possible associations, including shared views or stale registrations | Resolve the ambiguity; do not choose an owner by name or timestamp |
| No registration path matches | This snapshot supplies no location evidence | Keep the status unknown; check portable apps, app settings, vendor documentation and user intent |
| An unsupported path or partial collection prevents a match | Coverage is insufficient | Gather the missing evidence without treating it as absence |

Matching is component-aware and case-insensitive for supported absolute Windows drive paths. It is lexical: no junction resolution, on-disk ownership validation or dependency analysis occurs. Names such as `Cache`, a publisher name or a similar sibling prefix do not create a match. An absent `InstallLocation` is not filled in from an uninstall command.

When application evidence is supplied, a matching file is excluded from the report's hypothetical ordinary-file copy total. This does not alter the raw scan, execute a cleanup, or make unmatched files disposable. A report cannot authorize deletion or override the copy helper's restrictions on application content.

## Establish a cleanup decision

Confirm the product and whether it is still used, inspect the exact vendor-supported data locations, and separate documents/settings/licenses from rebuildable cache and shared dependencies. Obtain the user's decision about what to retain. Use Windows or the application's supported cleanup/uninstall workflow for a concrete reviewed scope. If the product or data ownership remains unknown, retain the files and report that unresolved question.

No general residue deletion or registry sweeping command is supplied. This evidence step makes the existing [Windows cleanup workflow](windows-cleanup.md) more informed; it does not promise complete residue removal.

Sources: [Microsoft uninstall registration fields](https://learn.microsoft.com/en-us/windows/win32/msi/uninstall-registry-key), [installation-location semantics](https://learn.microsoft.com/en-us/windows/win32/msi/arpinstalllocation), [alternate registry views](https://learn.microsoft.com/en-us/windows/win32/winprog64/accessing-an-alternate-registry-view).
