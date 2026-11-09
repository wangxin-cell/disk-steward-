# Decision guide

The user's loss tolerance and workflow matter more than size alone. Ask only for missing decisions that affect the next action; continue read-only work while waiting.

| Evidence | Default proposal | Explain the tradeoff |
|---|---|---|
| User-owned videos, archives or exports with known purpose | Keep or copy to a named data drive | Target capacity, availability and backup coverage; verification precedes any source cleanup |
| Installer whose app/version and re-download source are confirmed | Offer deletion for review | Offline reinstalls may become impossible; age is not proof |
| Cache confirmed by its owning application's documentation | Use app cleanup or cache manager | Re-download/rebuild time; dependencies may need network |
| Application no longer wanted | Use its uninstaller | Confirm whether settings, licenses and saved work remain |
| Residual directory after uninstall | Inspect ownership, contents and shared dependencies | Never infer “orphan” solely from registry absence or an old timestamp |
| Windows component store, installer cache or system file | Windows-supported servicing only | Report uncertainty; never prune files manually |
| Cloud placeholder/sync directory | Use provider's online-only/storage controls | Deletion can synchronize to other devices; logical size differs from local allocation |
| Database, VM, WSL or Docker image | Vendor-aware workflow | Close/quiesce, export/backup and restore-test; deleting from a guest may not shrink the host image |

Suggested conversation: “You want 20 GiB of additional space. I found 12 GiB of ordinary archives that could be copied to D and 9 GiB of app-owned cache requiring confirmation. Copying alone does not free C. The scan skipped protected entries; this is not a complete drive inventory.” Numbers here are illustrative, not benchmark results.

For ongoing planning, propose a reserve with an explanation rather than an alleged universal Windows requirement. Example: user-selected 30 GiB reserve plus the next known 15 GiB installer. With comparable daily observations, estimate growth and days until reserve; do not infer trends from one snapshot. Prefer changing app download/cache/save locations through supported settings. Partition resizing and moving OS folders are outside this alpha.

Measure `free_after - free_before` on the relevant volume after cleanup. Concurrent activity can affect this measurement, so label it observed net change. Hardlinks, sparse/compressed files, recycling and cloud state make logical bytes unreliable as a forecast of freed bytes.

Use the [readable decision report](decision-report.md) to preserve these tradeoffs beside the dated capacity snapshot. Two proposed scenarios can compare which files the user wants to retain, consider for copying, or review in an owning app. These choices do not authorize execution. A scenario's hypothetical logical file scope cannot establish that a physical-space shortfall is covered.
