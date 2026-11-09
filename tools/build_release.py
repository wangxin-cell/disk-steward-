#!/usr/bin/env python3
"""Build reproducible local ZIP bundles without downloads or dependencies.

Only the explicit authored-file allowlist is read. Output paths must be outside
the source tree, and existing artifacts are never overwritten. Input trees must
be quiescent; path checks are not a sandbox against hostile filesystem races.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import zipfile

NAME = "disk-steward"
VERSION = "0.5.1-alpha"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024
BLOCKED_ATTRIBUTES = 0x400 | 0x1000 | 0x4000 | 0x40000 | 0x400000

SKILL_FILES = (
    "SKILL.md", "LICENSE.txt", "agents/openai.yaml",
    "references/app-cache.md", "references/application-evidence.md", "references/decision-guide.md", "references/decision-report.md", "references/migration.md",
    "references/source-release.md", "references/windows-cleanup.md", "references/zone-identifier.md",
    "scripts/app_cache.py", "scripts/app_inventory.py", "scripts/decision_report.py", "scripts/disk_scan.py", "scripts/source_release.py", "scripts/verified_copy.py",
)
# Keep this list deliberate: new files need review before entering a release.
# The JSON files below are authored, path-redacted validation summaries, not raw
# machine reports. Arbitrary JSON reports, fixture trees and caches are excluded.
SOURCE_FILES = tuple(sorted((
    ".gitignore", ".github/workflows/test.yml", "CONTRIBUTING.md", "LICENSE",
    "README.md", "README.en.md", "RELEASE_NOTES.md", "ROADMAP.md", "SECURITY.md", "VALIDATION.md",
    "docs/compatibility.md", "docs/cross-volume-validation.json", "docs/codex-discovery-validation.json",
    "docs/zone-identifier-validation.json",
    "docs/host-acceptance.md", "docs/codex-workflow-validation.json", "docs/codex-desktop-validation.json",
    "docs/native-application-validation.json",
    "docs/example-decision-report.zh.md", "docs/example-decision-report.en.md",
    "docs/example-application-review.zh.md", "docs/example-application-review.en.md",
    "tests/test_acceptance_fixture.py", "tests/test_app_cache.py", "tests/test_app_inventory.py", "tests/test_application_report.py", "tests/test_copy.py", "tests/test_decision_report.py", "tests/test_package.py", "tests/test_release.py", "tests/test_scan.py", "tests/test_zone_identifier.py",
    "tools/acceptance_fixture.py", "tools/application_example.py", "tools/build_release.py", "tools/check_package.py", "tools/demo.py", "tools/report_example.py",
    *(f"skills/{NAME}/{relative}" for relative in SKILL_FILES),
)))


class PackageError(ValueError):
    """The source or output does not meet the release packaging contract."""


def absolute(value: str | Path) -> Path:
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        raise PackageError("An explicit local filesystem path is required")
    if os.name == "nt":
        if raw.startswith(("\\\\", "//")) or re.match(r"^[a-zA-Z]:(?:$|[^\\/])", raw):
            raise PackageError("UNC, device and drive-relative paths are unsupported")
        # Validate before Windows abspath silently removes trailing dots/spaces.
        if any(part not in (".", "..") and part.endswith((".", " ")) for part in Path(raw).parts):
            raise PackageError("Trailing dot/space path aliases are unsupported")
    return Path(os.path.abspath(raw))


def check_path(path: Path, *, directory: bool = False) -> os.stat_result:
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & BLOCKED_ATTRIBUTES:
            raise PackageError(f"Linked, reparse, encrypted or offline/cloud path is unsupported: {component}")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise PackageError(f"Expected directory ancestor: {component}")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise PackageError(f"Expected an existing directory: {path}")
    return info


def identity(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def read_source(path: Path) -> bytes:
    before = check_path(path)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise PackageError(f"Only ordinary, singly linked authored files are supported: {path}")
    if before.st_size > MAX_FILE_BYTES:
        raise PackageError(f"Authored file exceeds the 16 MiB limit: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise PackageError(f"Source changed while opening: {path}")
        content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES or len(content) != before.st_size or identity(os.fstat(stream.fileno())) != identity(before):
            raise PackageError(f"Source changed while reading: {path}")
    if identity(check_path(path)) != identity(before):
        raise PackageError(f"Source changed while reading: {path}")
    return content


def archive_bytes(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    # ZIP_STORED avoids compression-library/version differences. All metadata is
    # fixed, so identical source bytes give identical bundles across platforms.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content)
    return output.getvalue()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_release(source: str | Path, output: str | Path) -> dict:
    source, output = absolute(source), absolute(output)
    check_path(source, directory=True)
    check_path(output, directory=True)
    # Resolve native spellings only AFTER rejecting linked ancestors, to catch
    # Windows 8.3 aliases without silently accepting a linked source directory.
    source_native, output_native = source.resolve(strict=True), output.resolve(strict=True)
    if output_native == source_native or source_native in output_native.parents:
        raise PackageError("Output directory must be outside the source tree")

    stem = f"{NAME}-{VERSION}"
    names = {"skill": f"{stem}-skill.zip", "source": f"{stem}-source.zip", "manifest": f"{stem}-manifest.json"}
    for filename in names.values():
        if os.path.lexists(output / filename):
            raise PackageError(f"Output already exists; no artifacts were overwritten: {filename}")

    authored = {}
    total = 0
    for relative in SOURCE_FILES:
        content = read_source(source.joinpath(*relative.split("/")))
        total += len(content)
        if total > MAX_SOURCE_BYTES:
            raise PackageError("Authored source exceeds the 128 MiB limit")
        authored[relative] = content
    bundle_members = {
        "skill": {f"{NAME}/{relative}": authored[f"skills/{NAME}/{relative}"] for relative in SKILL_FILES},
        "source": {f"{NAME}/{relative}": content for relative, content in authored.items()},
    }
    payloads, archive_records = {}, []
    for kind in ("skill", "source"):
        members = bundle_members[kind]
        payload = archive_bytes(members)
        payloads[names[kind]] = payload
        archive_records.append({
            "kind": kind, "filename": names[kind], "sha256": sha256(payload),
            "size_bytes": len(payload), "file_count": len(members),
            "members": [{"path": name, "sha256": sha256(content), "size_bytes": len(content)}
                        for name, content in sorted(members.items())],
        })
    manifest = {
        "schema_version": 1, "name": NAME, "version": VERSION,
        "format": "zip-stored", "fixed_zip_timestamp": "2020-01-01T00:00:00",
        "artifacts": archive_records,
    }
    payloads[names["manifest"]] = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")

    check_path(output, directory=True)
    # Reserve all outputs exclusively before writing. A concurrent writer or I/O
    # failure may leave partial outputs; never remove/replace an existing file.
    with ExitStack() as stack:
        streams = {filename: stack.enter_context((output / filename).open("xb")) for filename in sorted(payloads)}
        for filename, stream in streams.items():
            stream.write(payloads[filename])
            stream.flush()
            os.fsync(stream.fileno())
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(Path(__file__).absolute().parents[1]), help="Authored source root (default: this repository)")
    parser.add_argument("--output", required=True, help="Existing local output directory outside the source tree; artifacts must not exist")
    args = parser.parse_args(argv)
    try:
        result = build_release(args.source, args.output)
        print(json.dumps({"version": result["version"], "artifacts": [item["filename"] for item in result["artifacts"]],
                          "manifest": f"{NAME}-{VERSION}-manifest.json"}))
        return 0
    except (OSError, ValueError) as error:
        print(f"disk-steward packaging: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
