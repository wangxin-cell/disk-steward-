# Application-owned cache cleanup

The first executable adapter supports an **already installed pip 25.3** in the Python interpreter running the helper. It does not install, upgrade or downgrade pip. Other versions fail closed until their purge behavior is reviewed and tested. This adapter clears pip wheel/HTTP caches; it does not uninstall packages or detect abandoned application directories.

## Discover and prepare

```text
python scripts/app_cache.py discover
python scripts/app_cache.py plan --output <new-cache-plan.json>
```

Discovery asks pip for its **isolated default** cache, with user/environment configuration disabled. This is not necessarily the cache chosen by a user's normal shell or custom `PIP_CACHE_DIR`. The command does not enumerate contents until `plan`. If a different root is independently known to be the relevant pip cache, pass `--cache-dir <exact-cache-root>` to `plan`. An explicit override or a directory named Cache is not independent evidence of ownership; confirm provenance and show that uncertainty in the recommendation.

The plan inventories a bounded cache tree, rejects links/junctions, cloud placeholders, hardlinks and alternate streams, and records the interpreter, pip version and relevant module fingerprints. It lists candidate and retained files. The tested pip wheel pattern is `*-*.whl`; HTTP files are under `http` and `http-v2`. Metadata such as `origin.json`, selfcheck state and empty directories may remain.

Explain the exact root, candidate logical bytes and consequences: installed packages remain installed, but later installs may need downloads or rebuilds and previously cached offline reinstalls may no longer work. There is no undo. Ask only for missing approval of that concrete scope; a generic free-space target is not approval for losing offline cache contents.

## Apply the reviewed scope

```text
python scripts/app_cache.py apply --plan <cache-plan.json> --approve <cache-plan-id> --receipt <new-receipt.json>
```

Close other pip/cache writers before planning and execution. The helper reserves a new receipt outside the cache, rechecks runtime identity and the entire metadata snapshot, then invokes a fixed pip purge command with an explicit root. It never executes a command string or arbitrary argv supplied in JSON. Pip environment variables are removed and all configuration files disabled; update checks are disabled. No package download is performed by this workflow.

The app's purge is not an atomic transaction or a filesystem security boundary. A hostile concurrent junction swap is outside the guarantee; the helper does not hold locks over the entire cache tree. A failed/timed-out command may have already removed some entries. `partial_or_failed` or `command_pending` requires inspection, not an automatic retry. Compare observed volume free space and reported removed logical bytes; do not equate them or promise the folder becomes empty.

## Other applications

For npm, `cache verify` mutates the cache by garbage collection; do not present it as read-only diagnosis. For uv, determine how environments use the cache before cleaning: symlink-based installs can depend on cache content. No executable npm/uv purge adapter is supplied yet. Application residue detection remains evidence-driven and separate from cache cleanup.

Sources: [pip caching](https://pip.pypa.io/en/stable/topics/caching/), [pip configuration](https://pip.pypa.io/en/stable/topics/configuration/), [pip 25.3 cache implementation](https://github.com/pypa/pip/blob/25.3/src/pip/_internal/commands/cache.py), [npm cache](https://docs.npmjs.com/cli/v11/commands/npm-cache/), [uv cache](https://docs.astral.sh/uv/concepts/cache/).
