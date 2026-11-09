#!/usr/bin/env python3
"""Bounded metadata-only disk inventory and conservative review planning.

Python 3.11+, standard library only. No file contents are opened by the scanner.
The only write is the explicitly requested JSON report, created exclusively.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import heapq
import json
import math
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
import sys

SCHEMA_VERSION = 1
GIB = 1024**3
DETAIL_LIMIT = 100
# FILE_ATTRIBUTE_REPARSE_POINT, OFFLINE, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS.
UNSAFE_ATTRIBUTES = 0x400 | 0x1000 | 0x40000 | 0x400000
PROTECTED_PARTS = {
    "windows", "program files", "program files (x86)", "programdata",
    "system volume information", "$recycle.bin", "recovery",
}
SYSTEM_FILES = {"pagefile.sys", "swapfile.sys", "hiberfil.sys", "dumpstack.log.tmp"}
RESERVED_NAME = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def absolute_path(value: str | Path) -> Path:
    """Normalize dots without resolving links or opening file contents."""
    return Path(os.path.abspath(os.fspath(value)))


def blocked_metadata(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & UNSAFE_ATTRIBUTES
    )


def check_ancestors(path: Path) -> None:
    """Reject linked/cloud ancestors before walking, including the target itself.

    This is a best-effort local inventory, not a filesystem security boundary:
    an adversarial concurrent rename can race any path-based metadata traversal.
    """
    for component in reversed((path, *path.parents)):
        metadata = component.lstat()
        if blocked_metadata(metadata):
            raise ValueError(f"Linked, reparse, or offline/cloud path is excluded: {component}")


def category_for(path: Path) -> str:
    parts = {part.casefold() for part in path.parts}
    if parts & PROTECTED_PARTS or path.name.casefold() in SYSTEM_FILES:
        return "system_managed"
    if parts & {"temp", "tmp", "cache", "caches", ".cache", "code cache", "cache_data"}:
        return "possible_temp_or_cache"
    # Application ownership matters more than a filename's extension or a
    # nested Downloads directory; app archives are not ordinary user backups.
    if parts & {"appdata", ".conda", ".npm", ".nuget", ".gradle", ".docker"}:
        return "application_data"
    if "downloads" in parts:
        return "downloads"
    if path.suffix.casefold() in {".iso", ".zip", ".7z", ".rar", ".msi", ".msix", ".exe"}:
        return "archive_or_installer"
    return "user_file"


def scan_roots(roots: list[str | Path], max_files: int = 100000, top: int = 30, top_directories: int = 30) -> dict:
    """Inspect at most max_files directory entries; deduplicate stable file IDs."""
    if not 1 <= max_files <= 10_000_000:
        raise ValueError("max-files must be between 1 and 10000000")
    if not 1 <= top <= 1000:
        raise ValueError("top must be between 1 and 1000")
    if not 1 <= top_directories <= 1000:
        raise ValueError("top-directories must be between 1 and 1000")
    if not roots or len(roots) > 64:
        raise ValueError("Provide between 1 and 64 explicit scan roots")
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "roots": [],
        "root_results": [],
        "volumes": [],
        "logical_bytes": 0,
        "total_files": 0,
        "entries_examined": 0,
        "entry_budget": max_files,
        "incomplete": False,
        "errors": [],
        "skips": [],
        "error_counts": {},
        "skip_counts": {},
        "largest_files": [],
        "largest_directories": [],
        "directory_accounting": {
            "method": "inclusive_unique_file_ids_attributed_to_first_observed_path",
            "overlapping_summaries": True,
            "limitations": [
                "Nested directory summaries overlap each other and the file sample; never sum them together.",
                "Hard-linked identities count once globally, attributed to the first observed path; other directories may show fewer bytes/files.",
                "Counts and bytes describe observed entries only; incomplete subtrees have unknown omitted content.",
                "These are logical bytes, not allocated space or a cleanup estimate.",
            ],
        },
        "categories": {},
        "recommendations": [
            "logical_bytes counts unique file IDs when available; it is not allocated or reclaimable space.",
            "Hard links, sparse/compressed files, cloud content, permissions and changing files affect accounting.",
            "Names and timestamps do not establish that a file is unused, disposable, or an uninstall remnant.",
            "Use Windows or application storage controls for managed content; do not delete system folders.",
            "Only explicitly supplied roots are inventoried. This report is not a full-volume accounting.",
        ],
    }
    errors: Counter = Counter()
    skips: Counter = Counter()
    seen_files: set = set()
    seen_directories: set = set()
    volumes: dict[str, dict] = {}
    root_rows: dict[Path, dict] = {}
    directory_totals: dict[Path, dict] = {}
    directory_parents: dict[Path, Path | None] = {}
    active_root: Path | None = None
    active_directory: Path | None = None
    heap: list = []
    serial = 0

    def record(kind: str, reason: str, path: Path, detail: str = "", incomplete: bool = True) -> None:
        target = report[kind]
        counter = errors if kind == "errors" else skips
        counter[reason] += 1
        if len(target) < DETAIL_LIMIT:
            target.append({"path": str(path), "reason": reason, "detail": detail})
        if incomplete:
            report["incomplete"] = True
            if active_root in root_rows:
                root_rows[active_root]["incomplete"] = True
            if active_directory in directory_totals:
                directory_totals[active_directory]["incomplete"] = True

    def add_directory(path: Path, root: Path, parent: Path | None) -> None:
        directory_totals[path] = {
            "path": str(path), "root": str(root), "volume_id": root_rows[root]["volume_id"],
            "logical_bytes": 0, "observed_files": 0, "hardlinked_files": 0,
            "deduplicated_file_names": 0, "incomplete": False,
            "category": category_for(path), "is_scan_root": parent is None,
        }
        directory_parents[path] = parent

    def key_for(path: Path, metadata: os.stat_result) -> tuple:
        if metadata.st_ino:
            return ("id", metadata.st_dev, metadata.st_ino)
        return ("path", os.path.normcase(str(path)))

    pending: list[tuple[Path, Path]] = []
    # Reject overlapping roots rather than scanning/counting them twice.
    accepted: list[Path] = []
    normalized = sorted({absolute_path(root) for root in roots}, key=lambda p: (len(p.parts), str(p)))
    for root in normalized:
        active_root, active_directory = root, None
        report["roots"].append(str(root))
        row = {"path": str(root), "volume_id": None, "logical_bytes": 0,
               "observed_files": 0, "entries_examined": 0, "incomplete": False,
               "coverage": "pending", "deduplicated_file_names": 0}
        root_rows[root] = row
        try:
            check_ancestors(root)
            metadata = root.lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("Scan root must be an existing directory")
        except (OSError, ValueError) as exc:
            row["coverage"] = "invalid_root"
            record("errors", "invalid_root", root, str(exc))
            continue
        volume_id = str(metadata.st_dev)
        row["volume_id"] = volume_id
        covered_by = next((prior for prior in reversed(accepted)
                           if (root == prior or prior in root.parents)
                           and volume_id == root_rows[prior]["volume_id"]), None)
        if covered_by is not None:
            row.update(coverage="overlapping_root_not_scanned_separately", covered_by_root=str(covered_by))
            record("skips", "overlapping_root", root, incomplete=False)
            continue
        accepted.append(root)
        pending.append((root, root))
        add_directory(root, root, None)
        active_directory = root
        if volume_id not in volumes:
            try:
                usage = shutil.disk_usage(root)
                volumes[volume_id] = {
                    "volume_id": volume_id,
                    "path": str(root.anchor or root),
                    "queried_at": str(root),
                    "sampled_at": now_iso(),
                    "scan_roots": [str(root)],
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                }
            except OSError as exc:
                record("errors", "volume_usage", root, str(exc))
        else:
            volumes[volume_id]["scan_roots"].append(str(root))

    budget_exhausted = False
    while pending and not budget_exhausted:
        root, directory = pending.pop()
        active_root, active_directory = root, directory
        try:
            # Recheck ancestors: a queued directory may have changed since discovery.
            check_ancestors(directory)
            metadata = directory.lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                record("skips", "changed_directory", directory)
                continue
            if str(metadata.st_dev) != root_rows[root]["volume_id"]:
                record("skips", "different_volume", directory, "Scan this volume through its own explicit root")
                continue
            identity = key_for(directory, metadata)
            if identity in seen_directories:
                record("skips", "duplicate_directory", directory, incomplete=False)
                continue
            seen_directories.add(identity)
            with os.scandir(directory) as entries:
                for entry in entries:
                    if report["entries_examined"] >= max_files:
                        budget_exhausted = True
                        record("skips", "entry_budget", directory, "Traversal stopped at configured entry budget")
                        break
                    report["entries_examined"] += 1
                    root_rows[root]["entries_examined"] += 1
                    path = directory / entry.name
                    try:
                        # Windows DirEntry.stat may zero st_ino/st_dev/st_nlink.
                        # lstat supplies identities needed for hard-link accounting.
                        metadata = path.lstat()
                    except OSError as exc:
                        record("errors", "stat_failed", path, str(exc))
                        continue
                    if blocked_metadata(metadata):
                        record("skips", "link_reparse_or_cloud", path)
                        continue
                    if str(metadata.st_dev) != root_rows[root]["volume_id"]:
                        record("skips", "different_volume", path, "Scan this volume through its own explicit root")
                        continue
                    if stat.S_ISDIR(metadata.st_mode):
                        add_directory(path, root, directory)
                        pending.append((root, path))
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        record("skips", "special_file", path)
                        continue
                    identity = key_for(path, metadata)
                    if identity in seen_files:
                        directory_totals[directory]["deduplicated_file_names"] += 1
                        record("skips", "duplicate_file_id", path, incomplete=False)
                        continue
                    seen_files.add(identity)
                    size = metadata.st_size
                    category = category_for(path)
                    item = {
                        "path": str(path), "logical_bytes": size, "category": category,
                        "mtime_ns": metadata.st_mtime_ns, "hardlink_count": metadata.st_nlink,
                        "volume_id": root_rows[root]["volume_id"],
                    }
                    aggregate = directory_totals[directory]
                    aggregate["logical_bytes"] += size
                    aggregate["observed_files"] += 1
                    aggregate["hardlinked_files"] += int(metadata.st_nlink > 1)
                    report["total_files"] += 1
                    report["logical_bytes"] += size
                    totals = report["categories"].setdefault(category, {"logical_bytes": 0, "files": 0})
                    totals["logical_bytes"] += size
                    totals["files"] += 1
                    serial += 1
                    if len(heap) < top:
                        heapq.heappush(heap, (size, serial, item))
                    elif size > heap[0][0]:
                        heapq.heapreplace(heap, (size, serial, item))
        except (OSError, ValueError) as exc:
            record("errors", "directory_unreadable_or_changed", directory, str(exc))
    # Direct counters are rolled into their parents once, avoiding work per
    # ancestor for every file. Storage is bounded by the entry budget + roots.
    for root, directory in pending:
        directory_totals[directory]["incomplete"] = True
        root_rows[root]["incomplete"] = True
    for directory in sorted(directory_totals, key=lambda path: len(path.parts), reverse=True):
        aggregate = directory_totals[directory]
        parent = directory_parents[directory]
        if parent is not None:
            parent_total = directory_totals[parent]
            for field in ("logical_bytes", "observed_files", "hardlinked_files", "deduplicated_file_names"):
                parent_total[field] += aggregate[field]
            parent_total["incomplete"] |= aggregate["incomplete"]
    for root, row in root_rows.items():
        aggregate = directory_totals.get(root)
        if aggregate is not None:
            for field in ("logical_bytes", "observed_files", "deduplicated_file_names"):
                row[field] = aggregate[field]
            row["incomplete"] |= aggregate["incomplete"]
            if row["coverage"] == "pending":
                row["coverage"] = "partial" if row["incomplete"] else "enumerated_without_known_omissions"
        elif row["coverage"] == "overlapping_root_not_scanned_separately":
            row.update(logical_bytes=None, observed_files=None, incomplete=True)
        if row["incomplete"]:
            report["incomplete"] = True
        if row["volume_id"] in volumes and str(root) not in volumes[row["volume_id"]]["scan_roots"]:
            volumes[row["volume_id"]]["scan_roots"].append(str(root))
    report["root_results"] = list(root_rows.values())
    report["volumes"] = list(volumes.values())
    report["largest_directories"] = heapq.nlargest(
        top_directories, directory_totals.values(), key=lambda item: (item["logical_bytes"], item["observed_files"], item["path"])
    )
    report["largest_files"] = [item for _, _, item in sorted(heap, reverse=True)]
    report["error_counts"] = dict(errors)
    report["skip_counts"] = dict(skips)
    return report


def path_key(value: str) -> str:
    """Compare recorded Windows paths even when planning on another OS."""
    if re.match(r"^[a-zA-Z]:[\\/]", value) or value.startswith("\\\\"):
        return ntpath.normcase(ntpath.normpath(value))
    return os.path.normcase(os.path.abspath(value))


def select_volume(scan: dict, goal_kind: str, volume_root: str | None) -> dict | None:
    volumes = scan.get("volumes", [])
    if not isinstance(volumes, list) or len(volumes) > 64:
        raise ValueError("Invalid volume inventory")
    if goal_kind == "free-target" and not volume_root:
        raise ValueError("free-target requires --volume-root naming one recorded scan root or volume path")
    if len(volumes) > 1 and not volume_root:
        raise ValueError("Multiple volumes were scanned; choose one with --volume-root for this goal")
    if not volumes:
        if volume_root or goal_kind == "free-target":
            raise ValueError("No volume free-space snapshot is available; rescan the selected volume")
        return None
    # Earlier schema 1 reports have no volume IDs. They can still supply generic
    # review candidates, but cannot establish a volume-specific capacity goal.
    if any(not isinstance(volume, dict) or not isinstance(volume.get("volume_id"), str) for volume in volumes):
        if volume_root or goal_kind == "free-target":
            raise ValueError("Volume identities are missing; rescan before selecting a volume")
        return None
    known_ids = set()
    for volume in volumes:
        if volume["volume_id"] in known_ids:
            raise ValueError("Duplicate volume identities in scan report")
        known_ids.add(volume["volume_id"])
        if any(type(volume.get(field)) is not int or volume[field] < 0 for field in ("free_bytes", "total_bytes", "used_bytes")):
            raise ValueError("Invalid volume capacity snapshot")
        if volume["free_bytes"] > volume["total_bytes"] or volume["used_bytes"] > volume["total_bytes"]:
            raise ValueError("Inconsistent volume capacity snapshot")
        if not isinstance(volume.get("scan_roots"), list) or not all(isinstance(root, str) for root in volume["scan_roots"]):
            raise ValueError("Invalid volume roots")
        if not all(isinstance(volume.get(key), str) for key in ("path", "queried_at")):
            raise ValueError("Invalid volume paths")
    if volume_root:
        selected_key = path_key(os.fspath(volume_root))
        matches = [volume for volume in volumes if selected_key in {
            path_key(root) for root in [volume["path"], volume["queried_at"], *volume["scan_roots"]]
        }]
        if len(matches) != 1:
            raise ValueError("--volume-root must match exactly one recorded volume; use a specific scanned root")
        return matches[0]
    return volumes[0]


def make_plan(scan: dict, goal_gib: float = 20, goal_kind: str = "additional", volume_root: str | None = None) -> dict:
    """Turn observed large files into review tasks, never deletion instructions."""
    if not math.isfinite(goal_gib) or goal_gib <= 0 or not math.isfinite(goal_gib * GIB):
        raise ValueError("goal-gib must be a positive finite number")
    if not isinstance(scan, dict) or scan.get("schema_version") != SCHEMA_VERSION or not isinstance(scan.get("largest_files"), list):
        raise ValueError("Expected a version 1 scan report with largest_files")
    if len(scan["largest_files"]) > 1000:
        raise ValueError("Report exceeds largest_files limit")
    if goal_kind not in ("additional", "free-target"):
        raise ValueError("goal-kind must be additional or free-target")
    selected_volume = select_volume(scan, goal_kind, volume_root)
    selected_id = selected_volume["volume_id"] if selected_volume else None
    goal_bytes = math.ceil(goal_gib * GIB)
    baseline_free_bytes = selected_volume["free_bytes"] if selected_volume else None
    required_additional_bytes = goal_bytes if goal_kind == "additional" else max(goal_bytes - baseline_free_bytes, 0)
    candidates = []
    excluded_system_files = 0
    excluded_other_volume_files = 0
    seen: set[str] = set()
    priority = {"possible_temp_or_cache": 0, "downloads": 1, "archive_or_installer": 2, "user_file": 3, "application_data": 4}
    for item in scan["largest_files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Invalid file entry")
        size = item.get("logical_bytes")
        links = item.get("hardlink_count")
        if type(size) is not int or size < 0 or type(links) is not int or links < 1:
            raise ValueError("Invalid file size or hardlink count")
        if selected_id is not None and item.get("volume_id") != selected_id:
            excluded_other_volume_files += 1
            continue
        path = item["path"]
        if path in seen:
            continue
        seen.add(path)
        # Classification is only a heuristic, never evidence that deletion is safe.
        # Use reported classification to retain Windows paths on non-Windows hosts.
        category = item.get("category", "user_file")
        if category not in {*priority, "system_managed"}:
            category = "user_file"
        if category == "system_managed":
            excluded_system_files += 1
            continue
        evidence = ["Metadata-only observation; contents and application dependencies were not inspected."]
        if category == "possible_temp_or_cache":
            action = "review_in_owning_application"
            evidence.append("A directory name suggests temporary/cache content; this is not proof of disposability.")
        elif category == "application_data":
            action = "review_application_supported_relocation"
        else:
            action = "review_for_archive_or_verified_copy"
        if links > 1:
            evidence.append("Multiple hard links exist; removing this name may release zero bytes.")
        candidates.append({
            "path": path, "category": category, "logical_bytes": size,
            "volume_id": item.get("volume_id"),
            "action": action, "risk": "high" if links > 1 or category == "application_data" else "needs_user_review",
            "hardlink_count": links, "evidence": evidence,
            "estimated_reclaimable_bytes": None,
        })
    candidates.sort(key=lambda item: (priority[item["category"]], -item["logical_bytes"]))
    directories = scan.get("largest_directories", [])
    if not isinstance(directories, list) or len(directories) > 1000:
        raise ValueError("Invalid or oversized directory summary sample")
    directory_reviews = []
    seen_directories = set()
    for item in directories:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Invalid directory summary")
        if any(type(item.get(field)) is not int or item[field] < 0 for field in
               ("logical_bytes", "observed_files", "hardlinked_files", "deduplicated_file_names")):
            raise ValueError("Invalid directory summary counters")
        if selected_id is not None and item.get("volume_id") != selected_id:
            continue
        if item["path"] in seen_directories:
            continue
        seen_directories.add(item["path"])
        category = item.get("category", "user_file")
        if category == "system_managed":
            continue
        if category not in priority:
            category = "user_file"
        action = "review_directory_contents_before_selecting_files"
        if category == "possible_temp_or_cache":
            action = "review_in_owning_application"
        elif category == "application_data":
            action = "review_application_supported_relocation"
        directory_reviews.append({
            "path": item["path"], "volume_id": item.get("volume_id"), "category": category,
            "logical_bytes": item["logical_bytes"], "observed_files": item["observed_files"],
            "hardlinked_files": item["hardlinked_files"], "deduplicated_file_names": item["deduplicated_file_names"],
            "incomplete": bool(item.get("incomplete", True)), "is_scan_root": bool(item.get("is_scan_root", False)),
            "action": action, "estimated_reclaimable_bytes": None,
            "evidence": [
                "Inclusive observed totals may reveal many small files absent from the largest-file sample.",
                "Nested summaries and file candidates overlap; do not add their bytes together.",
                "Hard links are attributed to the first observed path globally; this is not an independent directory size.",
                "Directory totals do not establish that all contents can be copied or deleted.",
            ],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "scan_created_at": scan.get("created_at"),
        "scan_incomplete": bool(scan.get("incomplete", True)),
        "goal_bytes": goal_bytes,
        "goal_kind": "additional_free_space" if goal_kind == "additional" else "target_free_space",
        "goal_volume": selected_volume,
        "baseline_free_bytes": baseline_free_bytes,
        "required_additional_bytes": required_additional_bytes,
        "capacity_snapshot_status": ("additional_space_requested" if goal_kind == "additional" else
                                     "below_free_target" if required_additional_bytes else "already_at_free_target_at_scan_time"),
        "goal_evaluation": "unknown_until_user_choices_and_post_action_volume_measurement",
        "candidates": candidates,
        "directory_reviews": directory_reviews,
        "candidate_logical_bytes": sum(item["logical_bytes"] for item in candidates),
        "automatic_reclaimable_bytes": 0,
        "excluded_system_files": excluded_system_files,
        "excluded_other_or_unknown_volume_files": excluded_other_volume_files,
        "limitations": [
            "This plan contains review candidates, not authorized cleanup operations.",
            "Candidates come only from the bounded largest-files sample, not every scanned file.",
            "Samples are bounded across all scanned roots; rescan the selected volume alone if other volumes dominate them.",
            "Directory reviews are a separate overlapping summary; do not add them to file candidate bytes or to each other.",
            "Capacity shortfall uses a recorded free-space snapshot for one volume; current free space may have changed.",
            "Candidate logical bytes are not a promise of released disk space; no reclaim estimate is available.",
            "A verified copy does not release source space. Cleanup requires a separate decision.",
            "Inspect application ownership, backups and user value before any change; age alone is insufficient.",
            "Use Windows Settings / Storage and official application uninstall/cache controls for managed files.",
        ],
    }


def write_report(path: str | Path, report: dict) -> None:
    # Validate the spelling before Windows abspath can strip trailing dots/spaces.
    name = Path(path).name
    if not name or name[-1:] in (".", " ") or RESERVED_NAME.match(name) or any(
        ord(char) < 32 or char in '<>:"|?*' for char in name
    ):
        raise ValueError("Report filename must be portable; device names and alternate data streams are unsupported")
    output = absolute_path(path)
    check_ancestors(output.parent)
    # Exclusive creation also prevents following an existing final-path symlink.
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scanner = subparsers.add_parser("scan", help="Inventory metadata under explicit directory roots")
    scanner.add_argument("--root", action="append", required=True)
    scanner.add_argument("--max-files", type=int, default=100000, help="Traversal entry budget (files AND directories), default 100000")
    scanner.add_argument("--top", type=int, default=30, help="Largest file sample size, 1..1000")
    scanner.add_argument("--top-directories", type=int, default=30, help="Inclusive directory summary sample size, 1..1000; summaries overlap")
    scanner.add_argument("--output", required=True, help="New JSON file; parent must exist; never overwrites")
    planner = subparsers.add_parser("plan", help="Generate review candidates; never executes cleanup")
    planner.add_argument("--scan", required=True)
    planner.add_argument("--goal-gib", type=float, default=20, help="GiB requested under --goal-kind; no achieved-space guarantee")
    planner.add_argument("--goal-kind", choices=("additional", "free-target"), default="additional", help="Seek additional free GiB (default), or reach total free GiB on one volume")
    planner.add_argument("--volume-root", help="Recorded scan root or volume path; required for free-target and multi-volume scans")
    planner.add_argument("--output", required=True, help="New JSON file; parent must exist; never overwrites")
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            report = scan_roots(args.root, args.max_files, args.top, args.top_directories)
        else:
            scan_path = absolute_path(args.scan)
            check_ancestors(scan_path)
            if scan_path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("Scan JSON is too large (limit: 16 MiB)")
            with scan_path.open(encoding="utf-8") as stream:
                report = make_plan(json.load(stream), args.goal_gib, args.goal_kind, args.volume_root)
        write_report(args.output, report)
        print(json.dumps({"output": str(absolute_path(args.output)), "incomplete": report.get("incomplete", report.get("scan_incomplete"))}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"disk-steward: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
