# Contributing

Run `python -m unittest discover -s tests -v` before proposing code changes. Use only disposable fixtures. Never make a test depend on cleaning a real profile or drive.

Useful contributions include verified host/version compatibility reports, reproducible edge cases, accessible translations and application-specific cleanup guidance supported by the application's official documentation. Include observed versus expected behavior, OS/Python/host versions, a minimal synthetic fixture and any skips.

For a cleanup rule, provide ownership evidence, supported app versions, exact scope, consequences, recoverability and negative cases (files that must remain). A path matching `cache` is not enough evidence. Destructive executors require a separate design review covering stale plans, reparse points, changed files and failure recovery.

Do not attach raw disk reports or real user documents. No telemetry is collected by these scripts. Benchmark claims must name hardware, dataset, command and limits. Do not label host packaging as runtime-tested without recorded execution.
