# Disk Steward

An agent skill for deciding what to keep, clean or relocate when a Windows system drive is running out of space.

[中文](README.md) · [Compatibility](docs/compatibility.md) · [Security](SECURITY.md)

[Preview a decision report](docs/example-decision-report.en.md) — explicitly fictional paths, capacities and preferences; no scan or cleanup.

**0.5.1-alpha.** This initial public release includes a **2026-11-09 Codex desktop explicit-invocation diagnosis check**: the skill loaded, its scan/plan/report scripts ran, and synthetic source files stayed intact. See the [acceptance record](docs/codex-desktop-validation.json). The skill and production scripts are unchanged, with no new cleanup capability. Earlier controlled CLI startup failures remain unresolved; DeepSeek Harness has not been run. Python 3.11+, standard-library core. Source release requires a separate plan and approval; copying preserves the source.

- Read-only bounded scanning with volume capacity, large files, inclusive directory aggregates and per-root coverage.
- Additional-free-space or target-free-space plans for an explicitly selected volume; logical bytes are not promised reclaimed bytes.
- Readable Chinese/English decision reports with optional conservative/expanded proposals, consequences and recovery limits. Choices do not authorize execution.
- Verified copying of whole ordinary user directories or repeated exact `--include <relative-file>` selections, with hashes, no overwrite and source preservation.
- Explicit native-Windows `--preserve-zone-identifier` copy policy: preserve and verify the full downloaded-file marker (up to 64 KiB) before writing primary content, and revalidate it during later source release. Other ADS remain unsupported; default and legacy plans still reject all ADS.
- Separately approved native-Windows source release: revalidate both sides, lock and hash each pair, remove selected source files by handle, retain unselected files/directories, and append a JSONL journal.
- Skill guidance for Windows/app-owned cleanup, leftover ownership checks and future save locations.
- Optional read-only application-registration collection and path associations in the report. A match is evidence to investigate; a non-match never establishes an orphan or permission to delete.
- Optional fixed-command pip-cache adapter for an existing pip 25.3 installation; separately reviewed scope, stale-plan checks and measured results. No installation or version changes.

Get the source from [wangxin-cell/disk-steward-](https://github.com/wangxin-cell/disk-steward-), then copy the complete `skills/disk-steward` folder into `<project>/.agents/skills/`. Both hosts document this layout. Codex discovery and one desktop diagnosis workflow explicitly invoking `$disk-steward` have been tested; DeepSeek runtime compatibility has not. Start a new Codex chat in that project. See the [compatibility matrix](docs/compatibility.md). This project does not install Python, a model, or a harness for you.

Example request: “Use disk-steward to inspect my Downloads folder read-only. I want 20 GiB more free space. Show a conservative plan and explain the consequences before changing files.”

From the repository root:

```text
python skills/disk-steward/scripts/disk_scan.py scan --root <directory> --output <new-scan.json>
python skills/disk-steward/scripts/disk_scan.py plan --scan <scan.json> --goal-gib 20 --output <new-plan.json>
python skills/disk-steward/scripts/decision_report.py --plan <plan.json> --language en --output <new-report.md>
python skills/disk-steward/scripts/verified_copy.py plan --source <directory> --destination <new-directory> --output <new-copy-plan.json>
python skills/disk-steward/scripts/verified_copy.py apply --plan <copy-plan.json> --approve <plan-id> --receipt <new-receipt.json>
python -m unittest discover -s tests -v
```

Keep reports outside scanned/copied trees. Copying frees zero source space; source cleanup is a separate decision after validation. System directories, app-managed data, cloud-sync trees and special filesystem features are not ordinary-file migration targets. The tool is not an NTFS backup and does not lock an entire tree against concurrent writers.

For ordinary downloaded files, add `--preserve-zone-identifier` to a new copy-plan command and review the marker policy along with the paths and scope. Never strip a marker to bypass a failure. Read [marker preservation and concurrency limits](skills/disk-steward/references/zone-identifier.md): retained markers deny write/delete during source release, but source markers must share deletion and stream-name inventory is not frozen. Close writers first.

For remaining free capacity, add `--goal-kind free-target --volume-root <recorded-root-or-volume>` to the planning command. Multiple-volume scans require an explicit goal volume. Directory summaries overlap: do not sum parents, children and file candidates together.

The report generator reads only supplied JSON, never the listed source files. Add `--choices <choices.json>` to compare proposed actions and their costs; unselected files remain undecided. Logical scope is not a reclaim forecast or proof that a goal is met. See the [decision report format](skills/disk-steward/references/decision-report.md).

For suspected remnants, optionally collect Windows registration metadata with `python skills/disk-steward/scripts/app_inventory.py collect --output <new-applications.json>`, then add `--applications <applications.json>` when rendering. No uninstall command or registry write is performed. Matching files are excluded from ordinary-copy scenario totals; registration does not establish current installation or exclusive ownership. Native Windows collection has now produced a partial inventory, with incomplete coverage. See the [redacted native record](docs/native-application-validation.json), [fictional example](docs/example-application-review.en.md) and [application-evidence workflow](skills/disk-steward/references/application-evidence.md).

After opening and validating the retained copy, prepare a distinct release plan. Applying it permanently removes selected source files without the Recycle Bin or automatic rollback; partial failure keeps completed deletions and stops. Only use the release plan ID after approving that exact destructive scope:

```text
python skills/disk-steward/scripts/source_release.py plan --copy-plan <copy-plan.json> --copy-receipt <copy-receipt.json> --output <new-release-plan.json>
python skills/disk-steward/scripts/source_release.py apply --plan <release-plan.json> --approve <release-plan-id> --receipt <new-journal.jsonl>
```

See [release semantics](skills/disk-steward/references/source-release.md) and [validation](VALIDATION.md). A tiny real C→D NTFS fixture passed; this does not establish full filesystem, scale or host integration coverage.

Scanning does not read contents. Copy hashing does. Scripts make no network calls; reports shared with a cloud model follow the host's data policies. Redact personal paths before posting issues. [MIT license](LICENSE).

For pip cache cleanup, read [app-cache.md](skills/disk-steward/references/app-cache.md). The isolated default is not necessarily your configured cache. Purging can remove offline reinstall material and require later downloads/builds; it does not uninstall packages. Unknown application leftovers still require ownership evidence.

`tools/acceptance_fixture.py` prepares three same-volume synthetic cases: `diagnose`, `copy` and `caution`. Its independent checks cover artifacts and protected files; they cannot establish a host-workflow pass without observed model and tool traces. The [desktop diagnosis check](docs/codex-desktop-validation.json) passed with both artifact and command-trace review. Natural-language skill selection, host-driven copy/release and DeepSeek remain unverified. See the [host-acceptance procedure](docs/host-acceptance.md) and the separate [historical blocked CLI record](docs/codex-workflow-validation.json); desktop success does not fix or replace those failed attempts.

The Windows/Linux and Python 3.11/3.13 CI workflow runs only when manually dispatched (`workflow_dispatch`), not on push. A manual run fetches Actions and Python on GitHub-hosted runners. No remote CI run was triggered for this publication; see [local validation](VALIDATION.md).

Build deterministic offline archives from reviewed local files with `python tools/build_release.py --output <existing-directory-outside-source-tree>`. The skill ZIP, source ZIP and SHA-256 manifest exclude caches, generated fixtures and raw local reports, and never overwrite existing output. Checksums are not release signatures.
