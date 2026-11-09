# Compatibility / 兼容性

Documentation and local discovery reviewed: 2026-11-05. Latest desktop acceptance: 2026-11-09. This initial public release adds validation evidence to 0.5.1-alpha; the skill and production scripts are unchanged from 0.5.0. No software was downloaded or globally installed for validation. Local skill copies were placed only in disposable discovery/acceptance projects.

| Host | Documented layout | Current evidence | Remaining verification |
|---|---|---|---|
| Codex | `<project>/.agents/skills/disk-steward/` | Installed CLI 0.166.0-alpha.6 discovery passed; one desktop explicit `$disk-steward` diagnosis workflow passed on 2026-11-09 with artifact and command-trace review. Desktop/model versions were not captured. Earlier controlled CLI startup attempts failed. | Natural-language automatic selection, permission prompts, host-driven copy/source release and broader version coverage |
| DeepSeek Harness | `<project>/.agents/skills/disk-steward/` or `.dsh/skills/disk-steward/` | Official upstream skills subsystem documentation | Windows desktop invocation, script execution and permission behavior |
| Other Agent Skills hosts | Host-specific skill root containing `disk-steward/SKILL.md` | Portable frontmatter and relative resource paths | Host discovery, runtime, tool and OS access |

One skill folder can serve multiple hosts. `agents/openai.yaml` is optional Codex UI metadata; the core does not depend on it. Do not install an extra nested `skills/` folder inside the discovery root: DeepSeek's provider discovers immediate skill subdirectories, not arbitrary nested packages. Its documentation's disabled `dsh-skill-badge` plugin is a UI detail, not evidence that all skill discovery is disabled.

The earlier Codex discovery probe used child-only state/config isolation and sent only `initialize`, `initialized` and `skills/list`. No thread/turn, model inference, dependency installation or global configuration change was performed in that probe. Read the path-redacted [discovery record](codex-discovery-validation.json); this does not establish model-level behavior.

In the desktop diagnosis case, the user explicitly invoked the skill on 35 synthetic D-drive files totaling 11,776 bytes. Observed scan/plan/report calls succeeded, the independent baseline verifier passed, and the reports respected the retain-all instruction without claiming freed space. This verifies that bounded diagnosis workflow only; see the [desktop record](codex-desktop-validation.json).

The earlier controlled `codex exec` workflow failed at in-process app-server initialization. In the 0.5.1 recheck, explicit temporary-state write and model-service network permissions removed temporary-directory warnings, but the same access-denied error remained. Exit 1, missing events/reports and unchanged protected snapshots do not establish a model-trigger failure or workflow success. Those requested tool sandbox/approval settings remain unverified. The installed stdio app-server cannot accept the same `--ignore-user-config` option and was not used as an equivalent substitute. The desktop result does not identify or repair the CLI failure. See [validation](../VALIDATION.md), the [historical CLI record](codex-workflow-validation.json) and [acceptance procedure](host-acceptance.md). DeepSeek Harness remains uninstalled and unrun by this project.

Use the project's actual working directory in each host. For global installs, consult the host/version documentation instead of assuming every product uses `.codex/skills`. Do not change existing settings automatically.

Portable packaging does not imply universal OS support. Native Windows can address `C:\`; WSL uses different paths and metadata behavior, and remote sandboxes may not see the user's disk at all. This alpha targets local Windows. Linux fixture tests are regression checks, not a claim of production macOS/Linux support or Windows metadata coverage.

Application registration collection requires native Windows and the standard-library `winreg` module. Alongside fake-registry tests, a native run now produced a schema-valid partial inventory: 102 entries examined and 94 records retained, with gaps in all four scopes. Raw registration data remained private; see the [redacted native record](native-application-validation.json). The report can interpret supplied inventory JSON without native registry access. Neither operation establishes current installation, complete ownership or that unmatched directories are uninstall remnants.

Before claiming tested support for a host, record exact host version, Windows version, Python version, install path, discovery result, prompt, commands, outputs and permissions. Exercise read-only scan and a copy of disposable test data. Confirm a broad “free space” request cannot trigger personal-file deletion without scoped authorization. Never test destructive behavior on actual user data.

Sources:

- [Agent Skills specification](https://agentskills.io/specification)
- [Codex local skill discovery](https://learn.chatgpt.com/docs/build-skills)
- [DeepSeek Harness landing page](https://deepseek.com/harness/)
- [DeepSeek Harness skills provider](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)
