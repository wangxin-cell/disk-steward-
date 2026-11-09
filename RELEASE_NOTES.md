# 0.5.1-alpha 初次公开发布补充

日期：2026-11-09。skill 与生产脚本保持 0.5.1-alpha 的内容不变；本次补入 Codex 桌面版验收记录及公开使用说明，不新增清理能力，也不改写此前生成的本地 ZIP。

**Codex 桌面版显式调用的基础诊断验收通过**：用户在准备好的项目中调用 `$disk-steward`，实际读取 skill，并成功执行扫描、规划与报告脚本。独立产物检查和主会话／审查子代理的命令记录共同核实：35 个 D 盘合成文件共 11,776 逻辑字节；源文件、skill 文件与测试标记保持原始记录一致；三份报告没有声称已释放空间或达成额外 1 GiB 目标。见[脱敏验收记录](docs/codex-desktop-validation.json)。

这次验收仅覆盖显式调用的诊断流程。自然语言自动选择、宿主内复制／源文件释放、真实 C 盘清理及 DeepSeek Harness 仍未由此验证。此前受控 CLI 初始化失败保留为历史记录，桌面版成功不代表该错误已修复。

本次发布准备的打包检查运行 **10 项：9 通过、1 项链接权限跳过、0 失败**；清单与文档链接检查通过，没有重跑完整测试集。GitHub Actions 配置为手动 `workflow_dispatch`，发布不会自动运行；手动启动时托管 runner 会获取 Actions 和 Python。本次未触发远端 CI，未下载或安装软件。

## English brief — initial public release

The 2026-11-09 publication supplement keeps the **0.5.1-alpha** skill and production scripts unchanged and adds a reviewed Codex desktop diagnosis record. One explicit `$disk-steward` invocation successfully loaded the skill and ran scan, plan and report scripts. Independent artifact checks and parent/review-subagent command traces confirmed 35 synthetic D-drive files totaling 11,776 logical bytes, unchanged protected source/skill/canary snapshots, and reports that made no reclaimed-space or achieved-goal claim. See the [redacted record](docs/codex-desktop-validation.json).

Natural-language selection, host-driven copy/source release, real C-drive cleanup and DeepSeek Harness remain outside this pass. Earlier controlled CLI startup failures remain unresolved historical evidence. Packaging checks ran **10 tests: 9 passed, 1 permission-related skip, 0 failures**; package/link checks passed. The full suite was not rerun and earlier local ZIP archives were not replaced. CI is manual-only (`workflow_dispatch`); dispatching it fetches Actions and Python on hosted runners. No remote CI run, software download or installation occurred for this publication preparation.

The dated sections below preserve the state of earlier local revisions; their unpublished/unverified statements describe those historical runs.

---

# Historical 0.5.1-alpha 验证补记

日期：2026-11-05。本次只补充验证记录，skill 与生产脚本沿用 0.5.0-alpha，没有新增清理能力，尚未发布到 GitHub。

应用登记采集已在原生 Windows 上执行：检查 **102 条登记，保留 94 条记录**，生成结构有效的报告并明确标为 `incomplete=true`。四个登记范围均有读取缺口，退出码 0 表示报告成功生成，不代表完整读取成功。原始清单保留在本地私有测试目录；公开记录不含应用名称或安装路径。观察到的注册表审计事件仅有四类允许的读取相关 API，没有意外事件。它不证明当前安装状态、文件归属或可清理的卸载残余。见[脱敏原生采集记录](docs/native-application-validation.json)。

一次新的 Codex 工作流尝试在明确授予本轮临时状态目录写入及模型服务网络权限后，消除了先前的临时目录警告，但仍在 app-server 初始化阶段因拒绝访问退出。没有模型事件或报告，受保护文件快照未变；完整模型工作流仍未通过。没有继续扩大权限或绕过沙箱。DeepSeek Harness 未下载、安装或运行。

下方 **264 项完整测试（254 通过、10 跳过）**保留为 0.5.0-alpha 的历史代码验证；本轮没有重新运行全量测试。没有下载、安装软件，也没有扫描或清理已有用户文件。完整证据范围见 [VALIDATION.md](VALIDATION.md)。

本轮更新后的打包测试为 **10 项：9 通过、1 项链接权限跳过、0 失败**；文件清单与文档链接检查通过。

## English brief — 0.5.1-alpha

This unpublished supplement changes validation records only; the skill and production scripts remain those of 0.5.0-alpha. Native Windows collection examined **102 entries**, retained **94 registration records**, and generated a schema-valid report explicitly marked incomplete. All four scopes had gaps. Raw data stayed private; public evidence contains no application names or installation paths. Only four allowed read-related `winreg` audit-event types were observed, with no unexpected registry events. This is not proof of complete inventory, current installation, ownership or uninstall remnants. See the [native record](docs/native-application-validation.json).

A fresh Codex workflow attempt, after explicit temporary-state write and model-service network permissions, no longer emitted the earlier temporary-directory warnings but still failed at app-server initialization. No model events or reports were produced; protected snapshots were unchanged. No further permission expansion or sandbox bypass was used. Full model workflows and DeepSeek Harness runtime remain unverified. The **264-test / 254-pass / 10-skip** result below is historical 0.5.0 evidence, not a full-suite rerun for this supplement. No software was downloaded or installed, and no existing user files were scanned or cleaned.

---

# 0.5.0-alpha 本地修订说明

日期：2026-11-05。新增应用登记路径证据，帮助审查疑似卸载残余；尚未发布到 GitHub。

`app_inventory.py collect` 以只读方式查询当前用户及本机的固定卸载登记范围，保留四项显示/安装位置字段，明确记录范围、预算和失败情况。它不读取应用文件，不执行卸载命令，也不写注册表。报告新增 `--applications`，显示候选与登记位置的关联、共享路径和未知项，并把关联文件排除在普通文件复制方案的逻辑量之外。登记不证明应用当前仍安装或独占归属，无匹配仍需继续核实。

完整本地测试 **264 项：254 通过、10 跳过、0 失败**。新增 31 项登记证据测试及 18 项报告测试；跳过项为受本机权限限制的真实链接夹具。采集逻辑使用模拟注册表验证，真实机器登记采集尚未运行。中英[虚构示例](docs/example-application-review.zh.md)展示了共享关联、相似兄弟目录不匹配，以及登记关联导致假设复制范围从 9 GiB 调整为 6 GiB；这不是实际清理或空间回收结果。

独立审阅修正了 Unicode 大小写折叠造成的错误路径关联，以及应用字段中隐藏控制字符的展示。更新后的 skill 使用已有 Codex 0.166.0-alpha.6 通过了本地发现与元数据解析。完整模型工作流的启动环境问题仍未解决；DeepSeek Harness 未下载、安装或运行。本轮没有下载软件，也没有操作已有用户文件。详情见 [VALIDATION.md](VALIDATION.md) 和[应用证据流程](skills/disk-steward/references/application-evidence.md)。

## English brief — 0.5.0-alpha

This unpublished revision adds bounded, read-only uninstall-registration collection and optional application-path evidence in the decision report. It never reads registered application files, executes uninstall commands or writes registry keys. Matching files are excluded from ordinary-copy scenario totals. Registration does not establish current installation or exclusive ownership; a non-match is not proof of an orphan.

The full local suite ran **264 tests: 254 passed, 10 skipped, 0 failures**. Collection logic was checked against a fake registry; live Windows collection remains unverified. The [fictional example](docs/example-application-review.en.md) exercises shared associations and sibling-name boundaries without actual cleanup. Updated Codex discovery passed; model workflows and DeepSeek Harness runtime remain unverified. No software download or preexisting user-file operation occurred.

---

# 0.4.1-alpha 本地修订说明

日期：2026-11-05。本次是验收工具与文档的小修订，skill 和生产脚本与 0.4.0-alpha 相同，尚未发布到 GitHub。

新增 `tools/acceptance_fixture.py` 与[宿主验收流程](docs/host-acceptance.md)，为 `diagnose`、`copy`、`caution` 三种场景准备同卷合成资料，并独立复核产物与受保护文件。缺少产物会失败；工具不会仅凭产物检查就宣称宿主工作流通过。

本轮新增工具的定向测试 **13 项全部通过，无跳过、无失败**；更新后的打包定向测试 **10 项：9 通过、1 跳过、0 失败**。下方保留的 202 项完整测试结果属于 0.4.0-alpha 历史验证，本轮没有声称重新运行全部 215 项测试。

使用已有 Codex 0.166.0-alpha.6 和正常保存的认证，尝试自然语言诊断场景。CLI 在进程内 app-server 客户端初始化阶段因拒绝访问退出，退出码 1；没有 JSONL 事件、最终回复或报告。baseline 与受保护文件快照未变，产物验证因缺少输出失败。分类为 **`environment_blocked_before_observed_model_execution`**，不是模型触发失败，也不是工作流通过。临时状态目录警告不足以确定致命错误的具体路径或唯一根因。

该次请求使用 `--ignore-user-config` 的受控配置、workspace-write、approval `never` 与禁用命令网络；因没有观察到工具执行，不能声称已实际验证这些设置或用户正常配置。未绕过沙箱或规则，未下载、安装软件或操作已有用户数据。DeepSeek Harness 未下载、安装或运行；模型工作流及远端 CI 仍未验证。见[脱敏验收记录](docs/codex-workflow-validation.json)与 [VALIDATION.md](VALIDATION.md)。

## English brief — 0.4.1-alpha

This unpublished revision adds three same-volume host-acceptance fixtures and independent artifact verification; the skill and production scripts are unchanged. The new tool's focused tests passed **13/13 with no skips or failures**. Updated packaging tests ran **10: 9 passed, 1 skipped, 0 failures**. The 202-test result retained below is historical 0.4.0 evidence, not a full 215-test rerun.

One attempt with existing Codex 0.166.0-alpha.6 and saved authentication exited 1 during in-process app-server initialization with access denied, before model execution was observed. There were no events, final message or reports; protected snapshots and baseline remained unchanged, and verification failed on missing outputs. This is an environment blocker, not a trigger failure or workflow pass. The exact fatal path remains unknown. Controlled sandbox/network/approval options were requested, not exercised by observed tools. No bypass, downloads, installation or preexisting user-data operations occurred. See the [acceptance procedure](docs/host-acceptance.md), [failure evidence](docs/codex-workflow-validation.json) and [validation record](VALIDATION.md).

---

# 0.4.0-alpha 本地修订说明

日期：2026-11-05。状态：已完成下述本地验证的 alpha 修订，尚未发布到 GitHub。

本轮为普通文件迁移增加显式启用的 `Zone.Identifier` 保留选项，避免复制下载文件时丢失 Windows 来源标记。使用方式和并发边界见 [Zone.Identifier 说明](skills/disk-steward/references/zone-identifier.md)，完整验证范围见 [VALIDATION.md](VALIDATION.md)。

## 本轮变更

- 在新建复制计划时加入 `--preserve-zone-identifier`，生成 schema 3 计划。默认行为以及旧 schema 1/2 计划仍拒绝所有备用数据流，不会自动放宽已有批准范围。
- 仅允许固定 ASCII 名称 `Zone.Identifier`，按大小写不敏感匹配；逐字节保留并以 SHA-256 校验其不超过 64 KiB 的原始内容，包括空标记和非 UTF-8 内容。不存在的标记与空标记分别记录，其他备用数据流仍会被拒绝。
- 目标标记先写入并校验，成功后才写入该文件的主数据。首次写入或校验标记失败时，不会继续复制该文件的主数据；后续最终校验仍可能在正文已复制后失败。没有去除标记或转成旁车文件的降级路径。计划和回执分别统计主数据与标记字节。
- 独立源文件释放流程复核两份内容及标记，并在源句柄关闭前持续持有目标标记的禁止写入、禁止删除句柄。源标记通过禁止写入的句柄校验，并检查可观察到的删除等待状态。

复制仍保留源文件；永久释放源文件仍需要独立计划及明确授权。未选文件及其标记、源目录均保留，部分失败没有自动回滚。这是普通文件及指定来源标记的迁移功能，不是完整 NTFS 元数据备份。

## 本地验证

完整测试共运行 **202 项：193 项通过、9 项跳过、0 项失败**，包含本轮新增的 33 项原生 Windows 标记测试。跳过项为受沙箱权限限制的真实硬链接/符号链接测试，不计作通过。

本轮在明确获准的 C 盘测试目录中新建微型合成资料，并完成真实 C→D CLI 流程：选定复制计划 → 已校验复制 → 独立释放计划 → 源文件释放。两个选中文件共 **1,910 主数据字节、39 标记字节**，包含一个空标记和一个不透明、含非 UTF-8 字节的标记。释放后，目标主数据和标记的全部 SHA-256 仍匹配；两个选中源文件已移除，未选文件、未选标记及所有源目录保留，日志记录两项删除完成。

该次释放观察到 C 卷空闲空间净变化为 **+8,192 字节**。这是受文件系统分配和同期活动影响的实际净测量，不能当作释放量预测、性能基准或普遍结果；复制本身仍不释放源盘空间。见[去除私人路径的验证记录](docs/zone-identifier-validation.json)。

本轮没有下载或安装软件，没有清理既有用户文件。所有执行验证均使用新建合成资料。

## 已知边界与兼容性

Windows 的共享限制按数据流维护，现有句柄**不能冻结备用数据流名称清单**。复查能拒绝已观察到的新增、变化或不支持的流，但不能消除最终检查与删除之间的所有竞争窗口。源标记必须允许删除共享，才能与主文件的删除句柄共存；删除等待检查不代表已禁止其他进程删除源标记。应关闭写入程序，在静止目录上操作；本版本不承诺抵御恶意并发流变更。

使用已有 **Codex 0.166.0-alpha.6** 重新验证了 0.4.0-alpha skill 的本地发现与元数据解析。检查仅调用 `initialize`、`initialized` 和 `skills/list`；更新后的 skill 以启用的 `repo` 范围返回，无发现错误，测试副本与源清单 SHA-256 一致。见[发现记录](docs/codex-discovery-validation.json)。没有模型调用、下载或安装；模型触发、权限交互和完整模型驱动工作流仍未验证。DeepSeek Harness 未下载、安装或运行，其他 harness 没有新增验证结论。

本版本未发布到 GitHub，没有远端 CI 结果或真实用户清理结果。文件系统与恢复方面的未覆盖范围见 [VALIDATION.md](VALIDATION.md)。

## English brief

Version 0.4.0-alpha is a locally validated, unpublished alpha revision. The opt-in `--preserve-zone-identifier` copy policy creates schema 3 plans and preserves the fixed ASCII `Zone.Identifier` stream name, matched case-insensitively. Default behavior and legacy schema 1/2 plans continue to reject all alternate data streams.

The marker is preserved as opaque bytes, including an empty marker or non-UTF-8 content, up to 64 KiB. Its bytes are hashed, written and verified before the destination file's primary payload is written. Other named streams remain unsupported. Primary bytes and marker bytes are reported separately; this is not general NTFS metadata backup.

Separately authorized source release rechecks both copies and their markers. It holds the retained marker against writes and deletion until the source handles close. The source marker handle denies writes but must share deletion; observable delete-pending state is checked. Existing-stream locks do not freeze the stream inventory, so final enumeration cannot eliminate every concurrent stream-creation or deletion race. Use quiescent folders; hostile concurrent mutation is outside the validated scope. See the [marker policy and limits](skills/disk-steward/references/zone-identifier.md).

The full local suite ran **202 tests: 193 passed, 9 skipped, 0 failed**, including 33 new native Windows marker tests. The skipped real-link tests were restricted by sandbox permissions. A fresh, authorized C→D CLI fixture copied and released two selected files containing **1,910 primary bytes and 39 marker bytes**, including empty and opaque/non-UTF-8 markers. All retained primary and marker hashes still matched after release; the unselected file and marker and all source directories remained. The journal recorded two completed deletions. The observed C-volume free-space delta was **+8,192 bytes**, a net measurement rather than a reclaim forecast or benchmark. See the [path-redacted fixture record](docs/zone-identifier-validation.json).

The existing **Codex 0.166.0-alpha.6** binary successfully rediscovered the 0.4.0-alpha skill as enabled with `repo` scope and no discovery errors. Source and fixture manifest SHA-256 matched. The probe called only `initialize`, `initialized` and `skills/list`, covering local discovery and metadata parsing without model calls; see the [discovery record](docs/codex-discovery-validation.json).

No software was downloaded or installed, and no preexisting user files were cleaned. Model triggering, permission interactions and complete model-driven workflows remain unverified, as does DeepSeek Harness. No GitHub publication, remote CI run or real-user cleanup outcome is claimed. See [VALIDATION.md](VALIDATION.md) for the complete evidence and exclusions.
