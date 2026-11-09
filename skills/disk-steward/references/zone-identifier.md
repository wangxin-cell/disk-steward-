# Preserve downloaded-file provenance

Use this only for ordinary files carrying the Windows `Zone.Identifier` alternate data stream. The marker can influence how Windows treats downloaded content; removing it is the behavior of [Unblock-File](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/unblock-file). Do not remove it to get a copy or cleanup operation to succeed.

## Explicit copy policy

On native Windows, add the following flag when preparing a new ordinary-file copy plan:

```text
python scripts/verified_copy.py plan --source <directory> --destination <new-directory> --include <exact-relative-file> --preserve-zone-identifier --output <new-copy-plan.json>
```

Resolve `scripts/` relative to this skill. The flag creates a schema 3 plan with `stream_policy: preserve-zone-identifier`. Default plans remain schema 2 and reject all ADS; old schema 1/2 plans keep that same restriction. Do not edit or reuse an approved old plan to enable the new behavior.

The policy supports only the fixed ASCII stream name `Zone.Identifier`, matched case-insensitively. It preserves its entire opaque contents byte for byte, including line endings and an empty marker, up to 65,536 bytes per file. An absent marker and an empty marker are different states. Other named streams, directory streams, unsupported filesystems, hard links, cloud/managed paths and other existing copy exclusions stop the operation. This is not general NTFS metadata backup.

The plan includes marker presence, length and SHA-256, plus a separate marker-byte total. It does not include raw `HostUrl`/`ReferrerUrl` content. Marker contents are read for verification; sending a plan to a cloud model still shares its file paths and metadata under that host's policies.

Review source, destination, selected files, this stream policy and consequences together. Applying the plan uses the same `verified_copy.py apply` command and still preserves source files. It creates an exclusive empty destination, writes and verifies the marker first, then writes primary file contents. Failure while creating or initially verifying the marker stops before copying that file's primary payload. Later snapshot or final verification failures can occur after primary content was copied. There is no unmarked or sidecar fallback, and a partial target is retained for inspection.

Marker presence and bytes are checked alongside primary content during source snapshot validation and final destination verification. A changed, added, removed or unrecognized stream invalidates the observed snapshot. `verified_bytes` continues to mean primary data length; `verified_zone_identifier_bytes` and `verified_zone_identifier_files` report marker progress separately. Only a final `status: verified` establishes the full copy's verification result. Copying still releases zero source space.

## Later source release

After checking the retained copy, use the independent [source-release plan](source-release.md) and the user's authorization for that exact permanent deletion. The release helper requires the schema 3 copy receipt's marker counts and policy to match, rechecks both current copies, and includes marker fingerprints in its retained-file manifest.

The primary source and target retain their existing native handle protections. Each existing target marker gets its own read handle that denies writing and deletion and remains open until the source handles close. The source marker is also hashed through a held read handle that denies writes, but **must permit deletion sharing** so Windows can delete the primary file. Observable pending marker deletion is checked from the bound handle before marking the primary source for deletion. A pending or changed stream stops the operation; it does not justify silently deleting an unverified source.

These are protections for the existing streams, **not a frozen inventory of stream names**. Windows maintains [sharing modes per stream](https://learn.microsoft.com/en-us/windows/win32/fileio/file-streams). It can permit another process to create an additional stream while these handles are open. Re-enumeration detects changes observed before deletion but cannot close every interval between a final check and deletion. Close writers and use quiescent folders. Do not claim safety against hostile concurrent stream creation/removal, or claim that source-marker deletion is itself locked out.

The JSONL journal keeps primary logical bytes and marker bytes separate. `logical_source_zone_identifier_bytes_removed` is marker content length, not physical reclaimed storage. Actual free-space change still needs volume measurement. Source directories and unselected files/markers remain; partial execution has no automatic rollback.

## Native behavior references

- [FindFirstStreamW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirststreamw): stream enumeration and error handling; unsupported filesystems are not treated as proof that no streams exist.
- [MS-FSA cross-stream delete sharing](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/82b364ce-6d7b-422f-8d88-4db32eea809a) and [per-stream sharing checks](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/8c0e3f4f-0729-49f4-a14d-7f7add593819): why source-marker deletion sharing differs from retained-marker protection.
- [SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle): disposition requires a handle with deletion access.
