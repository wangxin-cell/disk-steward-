# Local validation record

Latest evidence: 2026-11-09; historical validation: 2026-11-05. Environment: native Windows, Python 3.13.11.

This record distinguishes disposable fixture execution, native registration collection and host integration. No Python packages, harness installers or third-party repositories were downloaded or installed. No preexisting user files were scanned, copied or cleaned. The 0.5.1 validation read limited real application-registration metadata, retained privately. Earlier C→D tests used new tiny synthetic fixtures in the authorized test workspaces.

## Initial public release supplement — 2026-11-09

One **Codex desktop explicit-invocation diagnosis workflow passed** on a prepared D-drive synthetic project. The user invoked `$disk-steward` with an additional-free-space goal of 1 GiB and required all sources to remain. Reviewed parent and review-subagent command traces show that the skill was read and its scan, plan and report scripts exited successfully. All 11 diagnosis-parent commands and three review-subagent commands exited 0; observed Python calls used `-B`.

Independent artifact checks passed against the original baseline hash. Source files, skill files and the canary retained their recorded identities, timestamps, primary bytes and file sets. The three requested artifacts were present with no extra report files. They consistently described **35 files / 11,776 logical bytes**, 30 largest-file candidates totaling 11,136 bytes, a D-drive synthetic scope, and no space-release operation or achieved 1 GiB goal. The agent added contextual notes to the plan and Markdown; the final report was not the renderer's untouched output.

This combines artifact validation, command-trace inspection and report review; the artifact verifier alone deliberately reports `host_workflow_verified=false`. It is not a kernel-level audit of every access, ACL or alternate stream. Some retrieved command outputs were truncated; full command text and local final artifacts were separately inspected. Exact desktop and model versions were not independently captured, so the prior CLI version is not attributed to this run.

The skill and production scripts remain those of **0.5.1-alpha**. This first-publication documentation supplement does not modify the previously built local ZIP archives or claim a full-suite rerun. See the [path-redacted desktop record](docs/codex-desktop-validation.json). Natural-language automatic selection, host-driven copy/source release, real C-drive cleanup and DeepSeek execution remain unverified by this case. The earlier CLI startup failures below remain historical failures with an unidentified denied resource; desktop success does not prove they were repaired.

Publication packaging checks ran **10 tests: 9 passed, 1 skipped, 0 failures**; the skip was a fixture link operation denied by local permissions. The dependency-free manifest/resource/link check passed. These focused checks do not replace the historical full-suite result. CI is configured for manual `workflow_dispatch` only; publishing does not trigger it. A manual hosted run fetches Actions and Python. No remote CI run was performed for this publication preparation.

## Historical 0.5.1-alpha validation supplement — 2026-11-05

The skill and production scripts are unchanged from 0.5.0-alpha. This revision adds validation evidence, not cleanup capabilities. The 264-test result below belongs to the 0.5.0 full-suite run; the full suite was not rerun for this supplement.

Updated packaging checks ran **10 tests: 9 passed, 1 skipped, 0 failures**. The skip was a fixture symlink operation denied by this sandbox. The dependency-free package/link check also passed. These checks do not upgrade any host-workflow or inventory-completeness claim.

### Native application-registration collection

The current collector ran on native Windows and exited **0**, producing a schema-valid **partial** inventory: **102 entries examined, 94 registration records retained, 26,475 output bytes, `incomplete=true`**. The collector's SHA-256 matched the code used in the run. Records can represent multiple registrations of an application; 94 records does not mean 94 currently installed applications.

| Scope | View | Status | Entries examined | Recorded errors |
|---|---|---|---:|---:|
| HKLM | 32 | partial | 32 | 4 |
| HKLM | 64 | partial | 70 | 4 |
| HKCU | 32 | partial | 0 | 1 |
| HKCU | 64 | partial | 0 | 1 |

The run's Python audit hook observed only the four allowed `winreg` event types: `OpenKey` (106), `OpenKey/result` (96), `EnumKey` (104) and `QueryValue` (376), with no unexpected registry events. This records API event names and counts, not every underlying access argument or operating-system action. The fixed read scopes and four queried metadata fields are supported by the matching collector source. The generic failures do not identify their underlying OS errors.

Raw registration data remained private; application names and installation paths were not included in the reviewed summary or public record. No registered application directory was scanned or cleaned. The result verifies that native collection can produce a bounded report with explicit gaps in this environment; it does not establish complete inventory coverage, current installation, ownership, uninstall remnants or permission to delete. See the [path-redacted native record](docs/native-application-validation.json).

### Codex workflow recheck

A fresh `codex exec` case was attempted after explicit, turn-scoped permission for the normal temporary PATH-alias area and model-service network access. The earlier temporary-directory warnings disappeared, but in-process app-server initialization still exited **1** with `Access denied (os error 5)`. There were no JSONL events, final reply or requested reports. Baseline and protected source/skill/canary snapshots remained unchanged. This remains an environment blocker before observed model execution, not a model-trigger failure or workflow pass.

No further filesystem permission expansion or sandbox bypass was used. The installed stdio app-server does not accept the same `--ignore-user-config` option, so it was not treated as an equivalent replacement for this controlled workflow test. The fatal denied object remains unidentified. See the [workflow evidence](docs/codex-workflow-validation.json); DeepSeek Harness remains unrun.

## Historical 0.5.0-alpha validation

The complete local suite ran **264 tests: 254 passed, 10 skipped, 0 failures**. Skips are fixture hardlink/symlink operations denied by the sandbox. This includes 31 application-inventory tests (30 passed, one symlink skip) and 18 application-report tests (all passed), alongside the existing suites. No test queried the user's real application registry or scanned preexisting user files.

The new collector was exercised through an injected fake registry: four fixed hive/view scopes, read access, exactly four metadata values, missing/denied keys, bounded entry/UTF-8 output budgets, partial coverage, schema consistency and exclusive report creation. Matching and report tests verify component boundaries, shared registrations, parent-directory relationships, no name-based fallback, Unicode expansion false-positive rejection, no embedded-path/registry access, visible control characters and exclusion from ordinary-copy scenario totals. These tests verify collection logic, not live Windows registry behavior.

An independent in-memory example reproduced two associations for a registered installation and its containing directory, zero associations for a similarly named sibling and an unknown Cache path, and a hypothetical copy-scope change from 9 GiB to 6 GiB when the registered 3 GiB payload was excluded. All paths, sizes, registrations and preferences are fictional. No bytes were freed and no capacity target was achieved. The reviewed bilingual outputs are [Chinese](docs/example-application-review.zh.md) and [English](docs/example-application-review.en.md).

The existing Codex 0.166.0-alpha.6 binary rediscovered the updated 0.5.0 skill as enabled in repo scope with parsed UI metadata and no discovery errors. Source/fixture manifest hashes matched. The isolated probe sent only `initialize`, `initialized` and `skills/list`, without a model turn or script execution. The [discovery record](docs/codex-discovery-validation.json) retains the earlier 0.4.0 result as well. The previous full-workflow startup blocker below remains unresolved; no model-level success is claimed.

## Historical 0.4.1-alpha focused checks

The skill and production scripts are unchanged from 0.4.0-alpha. The new acceptance-fixture tests ran **13 tests: 13 passed, 0 skipped, 0 failures**. Updated packaging tests separately ran **10 tests: 9 passed, 1 skipped, 0 failures**. The historical 202-test result below remains evidence for 0.4.0-alpha; this revision does not claim a full 215-test rerun.

`tools/acceptance_fixture.py` prepares `diagnose`, `copy` and `caution` cases with disposable same-volume inputs and an independent artifact verifier. Missing outputs fail verification. Artifact checks alone never establish a successful host workflow; observed skill loading, script execution and trace review are also required. See [host acceptance](docs/host-acceptance.md).

## Historical executed checks — 0.4.0-alpha

- Test suites: **202 tests run, 193 passed, 9 skipped, 0 failures**. Skips are real hardlink/symlink tests denied by sandbox privileges. Scanner: 26 tests; copy helper: 45; source release: 21; app cache: 30; decision reports: 37; Zone.Identifier: 33; offline packaging: 10. All 21 native Windows release and 33 marker tests passed. Core tests use the standard library; app-cache integration uses the already installed pip 25.3.
- CLI scan/plan and copy-plan/apply round trips using synthetic files.
- `tools/demo.py`: three synthetic files, 3,397 logical bytes, two selected files totaling 3,370 bytes. Default mode retained sources; `--release-synthetic` removed only selected source files and preserved the unselected file. Both modes passed and generated Chinese/English decision reports from the actual synthetic scan. The latest same-volume release observed zero net free-space change despite removing 3,370 logical bytes; this is not a reclaimed-space or storage benchmark.
- Independent forward test: Downloads-like archives plus an AppData-like cache; a synthetic 57,476-byte ZIP copied with matching SHA-256 and successful archive integrity check. It did not execute cleanup or infer a cache file was disposable.
- Independent code review found NTFS alternate-stream output paths, drive-relative paths and application-owned archive classification issues; regression fixes were added.
- Directory aggregation tests cover many small files, nested summaries, hardlink attribution, coverage limits and explicit volume boundaries. Capacity tests distinguish additional space from a free-space target and reject ambiguous multi-volume goals.
- Selection tests cover exact filenames, unrelated siblings, necessary parent directories, stale/tampered plans, and legacy v1 tree plans alongside new v2 selection plans.
- Source-release tests cover fresh source/target hashes, retained identity replacement, active writers, native locks, permanent handle deletion, distinct approval, JSONL logging, partial failure and preservation of unselected files/directories.
- Opt-in schema 3 marker tests cover opaque/non-UTF8, empty/absent and 64 KiB boundary markers; default/legacy strict ADS rejection; unknown/directory streams; marker-before-primary ordering and write failure; added/removed/changed marker snapshots with restored primary timestamps; final target tampering; retained marker write/delete exclusion; observable source marker DeletePending; separate counters; and partial-release preservation. Tests do not claim source-marker deletion is locked out or stream-name inventory is frozen.
- Two real pip 25.3 purge integrations used only synthetic cache trees, including uppercase Windows subroot names. HTTP entries and matching `*-*.whl` names were removed; `note.whl`, `origin.json` and outside files remained. No default/user cache was queried or cleaned. Unit checks cover stale plans, runtime drift, command injection rejection, path guards, environment isolation and partial-failure states.
- Offline packaging tests check deterministic bytes, per-member/archive SHA-256, exact allowlists, collision refusal and link/reparse rejection. Only authored source/skill files enter the archives; bytecode, runtime binaries, test fixtures and raw machine reports are excluded.
- Decision-report tests check that rendering never opens or stats listed source paths, that input keys/types/limits are validated, and that outputs are exclusively created. Markdown/HTML, bare URIs, bidirectional controls and hidden line separators remain inert or visible. Scenario arithmetic excludes overlapping directory summaries, wrong/unknown/same-volume proposals, hard links and managed/cloud paths; proposals never establish authorization, reclaimed space or goal achievement.
- The bilingual public report examples are explicitly fictional: paths, 5 GiB baseline, 20 GiB additional target, 12 GiB archive and 9 GiB possible cache are authored metadata, not measurements. Both scenarios show only 12 GiB of hypothetical logical copy scope; cache review adds no estimated gain. The examples were regenerated with the final renderer and independently reviewed.
- `tools/check_package.py` checks this package's simple scalar frontmatter, names, resource paths and documentation links without dependencies. It is not a general YAML parser.

The bundled skill-creator `quick_validate.py` could not run because its PyYAML dependency is absent. In accordance with the no-download instruction, it was not installed. The dependency-free package check is a limited alternative, not a claim that the upstream validator passed.

## Historical 0.4.0-alpha Codex discovery

The already installed **codex-cli 0.166.0-alpha.6** was run as a stdio app-server with child-only temporary state and a local skill copy under a disposable project's `.agents/skills`. Requests were limited to `initialize`, `initialized`, and `skills/list`. The updated 0.4.0-alpha skill was returned as `scope: repo`, `enabled: true`, with parsed UI metadata and no discovery errors. The source and fixture SKILL.md SHA-256 matched. No download or update was performed by this project.

No thread/turn/model request, software download, global installation or global configuration change occurred in that discovery probe. This proves discovery and metadata parsing only, not prompting, model triggering or script execution within Codex. See the path-redacted [record](docs/codex-discovery-validation.json).

## 0.4.1-alpha Codex workflow attempt

One `diagnose` case was attempted with the existing **codex-cli 0.166.0-alpha.6**, normal saved authentication and a natural-language storage request without an explicit skill name. The controlled CLI configuration requested `--ignore-user-config`, workspace-write sandboxing, approval policy `never` and disabled command network access. No sandbox or rules bypass, download or installation was used. These were requested settings; no tool execution was observed, so their runtime behavior and the user's normal configuration were not verified.

The process exited **1** during in-process app-server client initialization with `Access denied (os error 5)`. It produced **0 JSONL events / 0 bytes**, no final message and no requested reports. The baseline hash and protected source/skill/canary snapshot remained unchanged; artifact verification failed because required outputs were missing. This is classified as **`environment_blocked_before_observed_model_execution`**, not a model-trigger failure or a host-workflow pass. Empty events do not prove every possible internal operation was absent.

Warnings concerned temporary-state cleanup and PATH-alias creation in the normal Codex state area, but the fatal error did not identify the denied object. The exact failure path and sole cause remain unknown. See the [path-redacted workflow record](docs/codex-workflow-validation.json). A new acceptance attempt in a working host environment is still needed; DeepSeek Harness was not downloaded, installed or run.

## Actual C→D fixture

An independent CLI run on two distinct NTFS volumes completed scan → selected copy plan → verified copy → independent release plan → source release. Two selected files totaling **51,000 bytes** were verified at the destination and removed from the source. An unselected **47-byte** sentinel and all source directories remained. The JSONL journal recorded two delete intents, two completions and final `complete`.

Observed C-volume free-space change during release was **+53,248 bytes**. This is a net measurement affected by filesystem allocation and concurrent activity, not a precise or general reclaim forecast. The fixture and its reports were retained in isolated work directories. A path-redacted result is saved in [cross-volume-validation.json](docs/cross-volume-validation.json). This tiny test is not a performance benchmark or proof of universal filesystem support.

## C→D with downloaded-file markers

A fresh schema 3 CLI fixture copied two selected files totaling **1,910 primary bytes plus 39 marker bytes** from C to D. One marker was empty; the other contained opaque non-UTF8 bytes. Source files remained after copying. After a distinct release plan, only the two selected source files were removed; the unselected primary file and its marker, source directories, target copies and logs remained. Independent primary and marker hashes matched at D after release. The journal recorded two completed deletions and final `complete`.

Observed C-volume free-space change was **+8,192 bytes**, a net measurement rather than a logical-size conversion or forecast. The first attempt stopped on `PermissionError` before any helper command; after explicit turn-scoped permission for the isolated C test directory, a fresh run passed. This was not an unchanged-permission retry or access to existing user documents. See the [path-redacted record](docs/zone-identifier-validation.json).

Native scratch probes confirmed that a default-stream lock does not protect named-stream writes, retained marker READ/share-READ handles block marker writes/deletion, and source marker deletion sharing is required for deleting the primary source. An independently requested source-marker deletion remains possible; `FileStandardInfo.DeletePending` observed it on the bound handle. Creation of an unknown stream can also succeed under existing-stream locks. These observations limit the guarantee to reviewed, quiescent files and the documented checks. They are not SmartScreen/Attachment Manager behavior tests, a frozen inventory, or protection against hostile concurrent actors.

## Not verified

- Complete application-registration coverage across installers/architectures, current installation state, file ownership or automatic uninstall-remnant identification. The native run above returned a partial inventory; lexical registration-path evidence does not establish these properties.
- Codex natural-language automatic skill selection, permission prompts, host-driven copy/source release and broader workflow behavior. Only the explicit desktop diagnosis case above has passed. DeepSeek Harness installation/discovery/runtime remain untested.
- FAT/exFAT behavior, full NTFS feature coverage, interrupted power recovery or hostile concurrent mutation.
- Production-scale scan performance; default traversal is bounded and can be incomplete.
- Real OS hardlink/symlink creation in this sandbox. Those tests skip on denied privileges; simulated metadata tests do not replace them.
- Remote CI runs. A Windows/Linux and Python 3.11/3.13 workflow is provided with manual `workflow_dispatch` only; no remote execution is claimed. Manually dispatching it fetches Actions and Python on hosted runners.
- Application-residue ownership detection, other cache/app adapters, and automatic system cleanup. The current app-cache adapter is limited to the reviewed pip 25.3 behavior; it is not a general uninstaller.

## Reproduce

From the repository root with an existing Python 3.11+:

```text
python -m unittest discover -s tests -v
python tools/check_package.py
python tools/demo.py --output <new-directory-with-existing-parent>
python tools/demo.py --output <another-new-directory> --release-synthetic
```

Tests create and remove only their own temporary fixture directories under `tests/`. The demo refuses an existing output directory and retains reports and target copies. With `--release-synthetic`, it permanently removes only the selected source files newly created by that demo invocation. On non-Windows platforms the release backend is unavailable and native-release tests skip explicitly.
