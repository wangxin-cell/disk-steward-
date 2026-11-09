> **Fictional example**: Registrations, paths, sizes and preferences are invented. No registry query, file scan or cleanup occurred. Two records point to Atlas; neither proves current installation or exclusive ownership. Atlas-old does not match merely by name, and a non-match does not mean disposable.

# Disk space decision report

This report interprets the supplied plan only. It does not read listed files, copy, clean or delete anything, or authorize operations.

## Goal and capacity snapshot

- Selected volume: C&#58;\\ \[fictional\-source\-C\]
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
| C&#58;\\Example\\Apps | 5,368,709,120 bytes (5.000 GiB) | 2 | incomplete | Overlaps a registered install location. Review individual files, their purpose, ownership and shared dependencies separately. The whole directory is not attributed to the app; establish officially supported handling and recovery options. |

## File candidates (review only)

The input plan's order is retained. Age or naming does not determine disposability, and a cache hint does not establish low risk.

| File | Logical size | Hard links | Tradeoffs and recovery | Input evidence (not independently verified) |
|---|---:|---:|---|---|
| C&#58;\\Example\\Cache\\unknown\.bin | 1,073,741,824 bytes (1.000 GiB) | 1 | A name only suggests cache content; establish ownership first. App cleanup can lose offline reinstall material; recovery may need downloads or rebuilding. | Metadata\-only observation; contents and application dependencies were not inspected\. &#47; A directory name suggests temporary&#47;cache content; this is not proof of disposability\. |
| C&#58;\\Example\\Downloads\\completed\-project\.zip | 4,294,967,296 bytes (4.000 GiB) | 1 | Keeping preserves access at the original location. A copy needs destination capacity and verification. Separately releasing a source requires manual recovery from the retained copy; age does not establish disposability. | Metadata\-only observation; contents and application dependencies were not inspected\. |
| C&#58;\\Example\\Apps\\Atlas\-old\\saved\-export\.zip | 2,147,483,648 bytes (2.000 GiB) | 1 | Keeping preserves access at the original location. A copy needs destination capacity and verification. Separately releasing a source requires manual recovery from the retained copy; age does not establish disposability. | Metadata\-only observation; contents and application dependencies were not inspected\. |
| C&#58;\\Example\\Apps\\Atlas\\payload\.bin | 3,221,225,472 bytes (3.000 GiB) | 1 | Overlaps a registered install location. Verify current app status, data purpose and shared dependencies, then establish official uninstall, storage or migration options and recovery requirements. Direct ordinary-file relocation or release is unproven. | Metadata\-only observation; contents and application dependencies were not inspected\. |

## Application registration path evidence

Only the supplied uninstall-registration inventory is interpreted. No registry, application directory or uninstall command is accessed or executed. Path overlap does not prove installed status, ownership or disposability; no match does not establish an orphan.

- Inventory collection time (not installation or removal time): 2026\-11\-05T00&#58;00&#58;00\+00&#58;00
- Evidence scope: uninstall\_registration\_only
- Entries examined / retained registrations / examination limit: 2 / 2 / 1000
- Coverage: No omissions reported within listed registration scopes; portable apps, absent registrations and other paths remain unknown.

| Registry source | View | Scope status | Entries examined | Recorded errors |
|---|---|---|---:|---:|
| HKLM | 32 | complete | 0 | 0 |
| HKLM | 64 | complete | 0 | 0 |
| HKCU | 32 | complete | 0 | 0 |
| HKCU | 64 | complete | 2 | 0 |

The existing file and directory targets are compared lexically; actual path identities, junctions, drive mappings and short-name aliases are unverified. A directory containing a registered location is not wholly attributed to that application.

At most 3 matches and registration references are shown per target, with the full match count separately listed; the supplied JSON retains the complete evidence.

| Target | Type | Assessment | Total matches | Shown registration references and relationships |
|---|---|---|---:|---|
| C&#58;\\Example\\Cache\\unknown\.bin | file | no match in this inventory; ownership unknown | 0 | — |
| C&#58;\\Example\\Downloads\\completed\-project\.zip | file | no match in this inventory; ownership unknown | 0 | — |
| C&#58;\\Example\\Apps\\Atlas\-old\\saved\-export\.zip | file | no match in this inventory; ownership unknown | 0 | — |
| C&#58;\\Example\\Apps\\Atlas\\payload\.bin | file | registration path overlap; verify app status and ownership | 2 | R1 inside registered location; R2 inside registered location |
| C&#58;\\Example\\Apps | directory | registration path overlap; verify app status and ownership | 2 | R1 directory contains registered location; R2 directory contains registered location |

Only registrations referenced above are shown; their supplied fields are not independently verified.

| Reference | Display name | Version | Publisher | Registered install location | Registry source / view / subkey |
|---|---|---|---|---|---|
| R1 | Atlas Editor \(fictional\) | 1\.0\-example | Fictional Publisher | C&#58;\\Example\\Apps\\Atlas | HKCU &#47; 64 &#47; fictional\-atlas |
| R2 | Atlas Shared Component \(fictional\) | 1\.0\-example | Fictional Publisher | C&#58;\\Example\\Apps\\Atlas | HKCU &#47; 64 &#47; fictional\-shared |

Before cleanup, establish current app status, file purpose and shared dependencies, then consult official uninstall or storage settings. Files overlapping registered locations are excluded from ordinary-file copy scope; any copy proposal still grants no deletion permission.
Missing install locations, environment variables and unsupported path forms are not replaced by name-based guesses and cannot establish the absence of an association.


## Optional what-if scenarios

Scenarios are proposals, not authorization or execution requests. Unselected files have no proposed action; neither consent nor an explicit keep decision is inferred.

The goal-volume identity comes from the input plan; destination identities are user-declared and unverified. Totals describe deduplicated proposed logical file scope, not estimated physical reclaim, shortfall coverage or goal achievement. Copying alone releases no source space.

| Scenario | Keep proposals | Copy then separately review release | App-cleanup proposals | Further review | No proposed action | Hypothetical logical copy scope (not physical reclaim) |
|---|---:|---:|---:|---:|---:|---:|
| Conservative | 0 | 4 | 0 | 0 | 0 | 6,442,450,944 bytes (6.000 GiB) |

### Conservative

The name distinguishes proposals; it does not establish low risk.

- Hypothetical selected logical copy scope: 6,442,450,944 bytes (6.000 GiB)
- Unselected files (no proposed action): 0

| File | Proposed action | Explanation | Consequence | Destination (unverified) | Scope accounting |
|---|---|---|---|---|---|
| C&#58;\\Example\\Apps\\Atlas\\payload\.bin | copy/verify, then separately review source release | Fictional preference&#58; consider another copy; deletion is undecided\. | First establish purpose, destination and separately reviewed source\-release scope\. | fictional\-declared\-D | overlaps an application registration; not counted as ordinary-file copy scope |
| C&#58;\\Example\\Apps\\Atlas\-old\\saved\-export\.zip | copy/verify, then separately review source release | Fictional preference&#58; consider another copy; deletion is undecided\. | First establish purpose, destination and separately reviewed source\-release scope\. | fictional\-declared\-D | hypothetical logical scope only; destination unverified |
| C&#58;\\Example\\Cache\\unknown\.bin | copy/verify, then separately review source release | Fictional preference&#58; consider another copy; deletion is undecided\. | First establish purpose, destination and separately reviewed source\-release scope\. | fictional\-declared\-D | managed/app/cache content; not counted as ordinary migration |
| C&#58;\\Example\\Downloads\\completed\-project\.zip | copy/verify, then separately review source release | Fictional preference&#58; consider another copy; deletion is undecided\. | First establish purpose, destination and separately reviewed source\-release scope\. | fictional\-declared\-D | hypothetical logical scope only; destination unverified |

## What remains to establish

- Establish purpose, value, application ownership and recoverable copies; timestamps do not prove uninstall remnants.
- Verify the real destination volume and capacity, then verify any copy. Source release needs its own plan and authorization check.
- App cleanup can lose cache and offline reinstall capability. Recovery may depend on downloads or rebuilding; do not assume undo.
- Remeasure volume space after actual work; compression, sparse files, hard links and concurrent activity affect physical changes.
