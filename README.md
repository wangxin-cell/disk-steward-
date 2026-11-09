# Disk Steward

**让 AI 帮你决定 C 盘什么该留、该清、该迁，并验证每一次普通文件复制。**

[English](README.en.md) · [产品路线](ROADMAP.md) · [兼容性](docs/compatibility.md) · [安全与隐私](SECURITY.md)

[先看一份决策报告](docs/example-decision-report.zh.md)（明确标注的虚构示例，无扫描或清理）

面向 Windows 的 **0.5.1-alpha**。核心工具只用 Python 标准库；可选缓存适配器调用已有应用。初次公开发布补充了 **2026-11-09 Codex 桌面版显式调用的基础诊断验收**：实际加载 skill、扫描合成样本、生成计划与报告，源文件保持完整。skill 与生产脚本不变，没有新增清理能力。此前受控 CLI 的启动错误未被修复；DeepSeek Harness 未运行。源文件释放需要独立计划和确认，不随复制自动执行。详见[本次验收记录](docs/codex-desktop-validation.json)。

## 现在可以做什么

| 能力 | 当前实现 |
|---|---|
| 空间诊断 | 只读元数据扫描、卷容量、大文件与目录聚合、逐根目录覆盖情况 |
| 取舍建议 | 区分“额外释放”和“剩余达到”，按选定卷计算缺口；中英可读报告、两组意向方案及代价比较 |
| 残余审查与清理 | 只读收集应用登记信息，在报告中显示路径关联与未知项；核实归属后使用 Windows / 应用自带工具 |
| 应用缓存清理 | 首个适配器调用已有 pip 25.3 的缓存维护命令，提供计划、范围复核及回执 |
| 跨盘另存 | 完整普通目录或明确选中文件、SHA-256 校验、拒绝覆盖、源文件保留；可明确保留下载来源标记 |
| 迁移后清理 | 独立源文件释放计划；Windows 原生锁定双方后校验、逐文件永久删除源文件、JSONL 日志 |
| 长期规划 | skill 引导选择空间储备、调整保存路径；无后台监控或自动执行 |

普通文件复制和应用迁移不同。AppData、Windows、安装目录、同步盘、虚拟磁盘和数据库必须使用对应工具。当前复制器不提供 NTFS 完整元数据备份，也不承诺抵御其他进程同时篡改路径。

面对“这个目录是不是卸载残余”，可用应用登记信息补充判断：[查看虚构示例](docs/example-application-review.zh.md)。登记路径关联不证明应用当前仍安装，也不证明独占归属；没有匹配登记仍是未知，不能自动删除。此功能不会执行卸载命令或修改注册表。已在原生 Windows 采集到部分登记信息，但覆盖不完整；详见[脱敏采集记录](docs/native-application-validation.json)及[应用证据流程](skills/disk-steward/references/application-evidence.md)。

通过重复 `--include` 可以只迁移目录中的几个指定文件，未选中的文件保持原样。目录聚合能显示大量小文件的总占用，但父子目录数据重叠，不能叠加成清理收益。计划工具不会自动判断用户文件价值或凑出“最优删除组合”，最终取舍由 skill 与用户完成。

默认复制计划仍拒绝 NTFS 附加数据流。在原生 Windows 上，可添加 `--preserve-zone-identifier` 明确保留下载文件的 `Zone.Identifier` 来源标记，最多 64 KiB，内容逐字节校验；其他附加流仍被拒绝。标记会先于正文写入目标，写入失败不会继续复制该文件的正文。不要为绕过检查而清除来源标记。详见[来源标记与并发边界](skills/disk-steward/references/zone-identifier.md)。

## 使用前提

- 已安装 Python 3.11+；运行时仅使用标准库，没有 `pip install` 步骤。
- 可选 pip 缓存适配器要求该解释器已有 pip 25.3；不会安装或调整其版本。
- 本地 Windows 文件访问权限。远程 agent / 容器不天然拥有本机 C 盘访问能力。
- 文件操作前有明确目标和用户授权。脚本不会获取管理员权限。

开发验证没有下载、安装或克隆第三方软件，也没有扫描或清理已有用户文件。已用合成资料完成微型 C→D 脚本流程、Codex `.agents/skills` 发现和桌面版显式诊断流程；没有全局安装或配置修改。自然语言自动触发、宿主内复制及清理、DeepSeek 运行仍需验证。下述安装命令供你选择使用。

## 安装到 Codex / DeepSeek Harness

从 [wangxin-cell/disk-steward-](https://github.com/wangxin-cell/disk-steward-) 获取源码。两个平台的官方文档均支持项目内 `.agents/skills`；DeepSeek 的运行兼容性尚未验证。把仓库中的 `skills/disk-steward` **完整目录**放在目标项目的 `.agents/skills/` 下：

```text
your-project/
└── .agents/
    └── skills/
        └── disk-steward/
            ├── SKILL.md
            ├── agents/openai.yaml
            ├── scripts/
            └── references/
```

例如，在本仓库根目录运行 PowerShell（替换项目路径；已有同名目录时停止）：

```powershell
$skillParent = 'D:\YourProject\.agents\skills'
$skillTarget = Join-Path $skillParent 'disk-steward'
if (Test-Path -LiteralPath $skillTarget) { throw '目标已存在，请先审查现有版本。' }
New-Item -ItemType Directory -Path $skillParent -Force | Out-Null
Copy-Item -LiteralPath '.\skills\disk-steward' -Destination $skillTarget -Recurse
```

在相应项目启动本地 harness，并让它读取该 skill。Codex 可用 `$disk-steward`；其他 host 可明确给出 `SKILL.md` 路径。详情与验证状态见[兼容性矩阵](docs/compatibility.md)。安装布局依据 [Codex 官方文档](https://learn.chatgpt.com/docs/build-skills) 与 [DeepSeek Harness 官方技能文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)。

也可使用离线构建的 skill ZIP：其中顶层 `disk-steward/` 应完整放入项目的 `.agents/skills/`。源码 ZIP 包含工具、测试和文档。构建方式见下文；创建这些文件不需要下载任何依赖。

## 试用提示词

> 使用 disk-steward。C 盘快满了，先只读扫描我的 Downloads，目标是再腾出 20 GiB。给我保守方案和可选方案，说明代价；不要先删文件。

> 使用 disk-steward。帮我把已经关闭的项目归档目录复制到 D 盘，先给出计划和校验方式；确认文件能正常打开后，再讨论源文件清理。

> 使用 disk-steward。规划以后新下载内容和游戏素材存放在哪个盘。给出建议，不修改设置。

## 不依赖 harness 的命令行

以下命令由仓库根目录运行。`work` 存放你自己的本地报告，切勿把包含私人路径的报告提交到 GitHub。输出文件使用未占用的新名称；将其放在扫描 / 复制目录之外。

```powershell
New-Item -ItemType Directory -Path '.\work' -Force | Out-Null
python .\skills\disk-steward\scripts\disk_scan.py scan --root 'C:\Users\YourName\Downloads' --output '.\work\scan.json'
python .\skills\disk-steward\scripts\disk_scan.py plan --scan '.\work\scan.json' --goal-gib 20 --output '.\work\plan.json'
python .\skills\disk-steward\scripts\decision_report.py --plan '.\work\plan.json' --output '.\work\decision-report.md'
python .\skills\disk-steward\scripts\verified_copy.py plan --source 'C:\Users\YourName\Documents\Archive' --destination 'D:\Archive-copy' --output '.\work\copy-plan.json'
```

要让“C 盘剩余达到 20 GiB”，使用 `--goal-kind free-target --volume-root 'C:\' --goal-gib 20`；默认 `additional` 指额外释放 20 GiB。多卷扫描必须明确选择目标卷。计算依据是扫描时的容量快照。

可读报告只读取计划 JSON，不访问清单中的文件。它展示容量缺口、覆盖限制、目录与文件的取舍代价；加 `--language en` 可输出英文。可选的 `--choices <choices.json>` 比较保守和扩展方案，未选择的文件保持未决。方案中的逻辑规模不等于能释放的空间，填写选择也不构成删除授权。格式见[决策报告说明](skills/disk-steward/references/decision-report.md)。

要只复制两个散落文件，在复制计划命令末尾添加 `--include 'notes.txt' --include 'exports/report.pdf'`，路径相对于 `--source`，使用 `/` 分隔符。只接受精确文件名，不展开通配符，也不接受目录选择项。

如果这些普通文件带有下载来源标记，再添加 `--preserve-zone-identifier`。这会创建独立的 schema 3 计划，将标记的存在状态、大小和哈希纳入审查；不把标记中的来源网址写进计划。旧计划保持原有规则，不能通过手工改 JSON 升级。后续源文件释放也会重新验证这些标记。

阅读计划，确认源、目标和影响后，将其中的 `plan_id` 填入下列命令。此步骤会创建目标副本，**保留源文件，释放空间为 0**。

```powershell
python .\skills\disk-steward\scripts\verified_copy.py apply --plan '.\work\copy-plan.json' --approve '<plan_id>' --receipt '.\work\copy-receipt.json'
```

不要以旧回执为依据删除当前源文件；它们可能已发生变化。失败的部分副本不会被自动清除。扫描不读文件内容；复制计划与执行会读取内容做哈希。

## 复制验证后释放源文件

先实际打开目标文件，确认保留副本和原文件取舍。以下计划会重新核对双方内容，**执行会永久删除所选源文件，不进回收站**；保留目标副本、未选文件和源目录。它不会清空目录或识别应用残余。仅支持原生 Windows。

```powershell
python .\skills\disk-steward\scripts\source_release.py plan --copy-plan '.\work\copy-plan.json' --copy-receipt '.\work\copy-receipt.json' --output '.\work\release-plan.json'
```

审阅 `release-plan.json` 的完整文件清单与影响，独立确认后使用它的 **release plan_id**（不是复制计划 ID）：

```powershell
python .\skills\disk-steward\scripts\source_release.py apply --plan '.\work\release-plan.json' --approve '<release_plan_id>' --receipt '.\work\release-journal.jsonl'
```

源或目标变化、文件锁定、校验失败时停止；部分执行不会回滚已完成的删除。日志逐行记录删除意图、完成情况和实测空间变化。详见[源文件释放与失败处理](skills/disk-steward/references/source-release.md)。

## 开发与验证

可选的 pip 缓存清理先独立生成计划，审查根目录与重装代价后才执行：

```powershell
python .\skills\disk-steward\scripts\app_cache.py discover
python .\skills\disk-steward\scripts\app_cache.py plan --output '.\work\pip-cache-plan.json'
python .\skills\disk-steward\scripts\app_cache.py apply --plan '.\work\pip-cache-plan.json' --approve '<cache_plan_id>' --receipt '.\work\pip-cache-receipt.json'
```

`discover` 返回隔离配置下的默认目录，并非用户自定义配置目录。`plan --cache-dir <目录>` 仅用于已确认归属的自定义缓存。清理会影响离线重装或带来重新下载/编译成本，不卸载已安装包，也不保证目录全空。详见[缓存规则与限制](skills/disk-steward/references/app-cache.md)。

先用合成文件体验复制流程，不接触已有用户资料（输出目录必须尚不存在）：

```powershell
New-Item -ItemType Directory -Path '.\work' -Force | Out-Null
python .\tools\demo.py --output '.\work\first-demo'
```

它会生成扫描报告、审查计划、中英可读报告、复制计划、校验回执和摘要。演示只在同一卷的小型合成目录执行，不能代替真实跨卷测试；源文件保留，释放字节数为 0。

在原生 Windows，可追加 `--release-synthetic`，仅释放本次演示新建的选中文件，同时验证未选文件仍在。该选项不会作用于任意现有文件。

```powershell
python -m unittest discover -s tests -v
python tools/check_package.py
```

测试使用临时夹具，不操作用户文档。CI 已配置 Windows / Linux 与 Python 3.11 / 3.13，仅由 `workflow_dispatch` 手动触发，推送不会自动运行。手动启动时，托管 runner 会获取 Actions 和 Python；本次发布未触发远端 CI。当前本地验证结果见 [VALIDATION.md](VALIDATION.md)。

`tools/acceptance_fixture.py` 可准备 `diagnose`、`copy`、`caution` 三种同卷合成验收场景，并独立复核产物及受保护文件。产物检查不能单独证明宿主工作流通过；还需真实模型与工具轨迹。2026-11-09 的桌面版显式诊断已结合两类证据通过验收：[成功记录](docs/codex-desktop-validation.json)。流程见[宿主验收说明](docs/host-acceptance.md)；此前 CLI 启动受阻的[历史记录](docs/codex-workflow-validation.json)保留，不能据桌面版结果宣称已修复。

离线构建源码包、skill 包和 SHA-256 清单（输出目录必须已存在且位于源码树之外；不覆盖已有包）：

```powershell
python .\tools\build_release.py --output 'D:\YourReleaseDirectory'
```

打包采用明确的文件清单，排除缓存、测试资料和本机原始报告。同一组源码会生成一致的 ZIP 字节；清单可用于复核包内容，不等于发布签名。

欢迎提交可复现问题、真实应用的清理规则依据和兼容性记录。先读 [CONTRIBUTING.md](CONTRIBUTING.md)。许可证：[MIT](LICENSE)。
