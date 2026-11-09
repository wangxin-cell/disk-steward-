> **Fictional example**: All paths, capacities and choices below are invented. No C/D scan, large-file creation or cleanup occurred. This is not a performance or reclaim test.

# Disk space decision report

This report interprets the supplied plan only. It does not read listed files, copy, clean or delete anything, or authorize operations.

## Goal and capacity snapshot

- Selected volume: C&#58;\\ \[fictional\-source\-volume\-C\]
- Snapshot time: 2026\-11\-05T00&#58;00&#58;00\+00&#58;00
- Goal: Additional free space 21,474,836,480 bytes (20.000 GiB)
- Free space at snapshot: 5,368,709,120 bytes (5.000 GiB)
- Additional space required by the snapshot: 21,474,836,480 bytes (20.000 GiB)
- Coverage: Partial coverage: some content was skipped or not traversed.

Capacity reflects the recorded instant; remeasure before deciding. An empty candidate list does not establish no opportunities: other volumes may dominate the bounded largest-file sample.

Recorded scan roots on the selected volume:

- C&#58;\\Example

## Directory signals (not additive)

Directory totals include descendants and overlap file candidates. Hard links are attributed to the first observed path; do not sum summaries or treat them as reclaimable space.

| Directory | Observed logical size | Files | Coverage | Tradeoffs and recovery |
|---|---:|---:|---|---|
| C&#58;\\Example | 26,843,545,600 bytes (25.000 GiB) | 3 | incomplete | An aggregate may mix ordinary files, app data and caches. Inspect contents and ownership before selecting specific ordinary files; suitability of the whole directory for relocation or cleanup is unproven. |
| C&#58;\\Example\\Downloads | 12,884,901,888 bytes (12.000 GiB) | 1 | no omissions reported | An aggregate may mix ordinary files, app data and caches. Inspect contents and ownership before selecting specific ordinary files; suitability of the whole directory for relocation or cleanup is unproven. |

## File candidates (review only)

The input plan's order is retained. Age or naming does not determine disposability, and a cache hint does not establish low risk.

| File | Logical size | Hard links | Tradeoffs and recovery | Input evidence (not independently verified) |
|---|---:|---:|---|---|
| C&#58;\\Example\\AppData\\Local\\ExampleApp\\Cache\\payload\.bin | 9,663,676,416 bytes (9.000 GiB) | 1 | A name only suggests cache content; establish ownership first. App cleanup can lose offline reinstall material; recovery may need downloads or rebuilding. | Metadata\-only observation; contents and application dependencies were not inspected\. &#47; A directory name suggests temporary&#47;cache content; this is not proof of disposability\. |
| C&#58;\\Example\\Downloads\\completed\-project\.zip | 12,884,901,888 bytes (12.000 GiB) | 1 | Keeping preserves access at the original location. A copy needs destination capacity and verification. Separately releasing a source requires manual recovery from the retained copy; age does not establish disposability. | Metadata\-only observation; contents and application dependencies were not inspected\. |
| C&#58;\\Example\\Documents\\active\-project\.zip | 4,294,967,296 bytes (4.000 GiB) | 1 | Keeping preserves access at the original location. A copy needs destination capacity and verification. Separately releasing a source requires manual recovery from the retained copy; age does not establish disposability. | Metadata\-only observation; contents and application dependencies were not inspected\. |

## Optional what-if scenarios

Scenarios are proposals, not authorization or execution requests. Unselected files have no proposed action; neither consent nor an explicit keep decision is inferred.

The goal-volume identity comes from the input plan; destination identities are user-declared and unverified. Totals describe deduplicated proposed logical file scope, not estimated physical reclaim, shortfall coverage or goal achievement. Copying alone releases no source space.

| Scenario | Keep proposals | Copy then separately review release | App-cleanup proposals | Further review | No proposed action | Hypothetical logical copy scope (not physical reclaim) |
|---|---:|---:|---:|---:|---:|---:|
| Conservative | 1 | 1 | 0 | 0 | 1 | 12,884,901,888 bytes (12.000 GiB) |
| Expanded | 1 | 1 | 1 | 0 | 0 | 12,884,901,888 bytes (12.000 GiB) |

### Conservative

The name distinguishes proposals; it does not establish low risk.

- Hypothetical selected logical copy scope: 12,884,901,888 bytes (12.000 GiB)
- Unselected files (no proposed action): 1

| File | Proposed action | Explanation | Consequence | Destination (unverified) | Scope accounting |
|---|---|---|---|---|---|
| C&#58;\\Example\\Downloads\\completed\-project\.zip | copy/verify, then separately review source release | Fictional preference&#58; retain the completed project on another drive\. | Access depends on the target drive; source release is a separate permanent deletion\. | fictional\-declared\-volume\-D | hypothetical logical scope only; destination unverified |
| C&#58;\\Example\\Documents\\active\-project\.zip | propose keep | Fictional preference&#58; keep the active project at its current location\. | Its space remains occupied; no space release is counted\. | — | not an ordinary cross-volume copy proposal; not counted |

### Expanded

The name distinguishes proposals; it does not establish low risk.

- Hypothetical selected logical copy scope: 12,884,901,888 bytes (12.000 GiB)
- Unselected files (no proposed action): 0

| File | Proposed action | Explanation | Consequence | Destination (unverified) | Scope accounting |
|---|---|---|---|---|---|
| C&#58;\\Example\\Downloads\\completed\-project\.zip | copy/verify, then separately review source release | Fictional preference&#58; retain the completed project on another drive\. | Access depends on the target drive; source release is a separate permanent deletion\. | fictional\-declared\-volume\-D | hypothetical logical scope only; destination unverified |
| C&#58;\\Example\\Documents\\active\-project\.zip | propose keep | Fictional preference&#58; keep the active project at its current location\. | Its space remains occupied; no space release is counted\. | — | not an ordinary cross-volume copy proposal; not counted |
| C&#58;\\Example\\AppData\\Local\\ExampleApp\\Cache\\payload\.bin | propose app cleanup (verify ownership and impact) | Fictional preference&#58; confirm application ownership, then review its supported cleanup\. | May need downloads or rebuilding; ownership evidence and cleanup authorization are absent\. | — | not an ordinary cross-volume copy proposal; not counted |

## What remains to establish

- Establish purpose, value, application ownership and recoverable copies; timestamps do not prove uninstall remnants.
- Verify the real destination volume and capacity, then verify any copy. Source release needs its own plan and authorization check.
- App cleanup can lose cache and offline reinstall capability. Recovery may depend on downloads or rebuilding; do not assume undo.
- Remeasure volume space after actual work; compression, sparse files, hard links and concurrent activity affect physical changes.
