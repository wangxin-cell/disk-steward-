#!/usr/bin/env python3
"""Plan and SHA-256 verify copies of ordinary closed files; never delete sources.

This is a conservative copy helper, not a backup/migration tool for running apps,
databases, cloud sync roots or Windows system data. It preserves file bytes and
basic timestamps, not ACLs, ownership or application settings. Native Windows
can opt into byte-preserving Zone.Identifier handling; other ADS remain excluded.
Checks detect normal concurrent changes; hostile filesystem races are out of scope.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from datetime import datetime, timezone

VERSION = 2
ZONE_VERSION = 3
ZONE_POLICY = "preserve-zone-identifier"
MAX_ZONE_BYTES = 65536
ZONE_SUFFIX = ":Zone.Identifier"
KIND = "disk-steward-copy-plan"
MAX_ENTRIES = 100_000
MAX_PLAN_BYTES = 64 * 1024 * 1024
CHUNK = 1024 * 1024
UNSUPPORTED_ATTRIBUTES = 0x400 | 0x1000 | 0x4000 | 0x40000 | 0x400000
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


class CopyError(ValueError):
    """A validation or copy invariant failed."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def absolute(value):
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        raise CopyError("An explicit nonempty local path is required")
    if os.name == "nt" and (raw.startswith(("\\\\", "//")) or re.match(r"^[a-zA-Z]:(?:$|[^\\/])", raw)):
        raise CopyError("UNC, device and drive-relative paths are unsupported")
    if os.name == "nt":
        # GetFullPathName (used by abspath) silently normalizes trailing dots and
        # spaces, including in ancestors. Validate the original spelling first,
        # for sources as well as mutation targets; never approve a hidden alias.
        original = Path(raw)
        for component in original.parts:
            if component not in (original.anchor, ".", ".."):
                relative_name(component)
    return Path(os.path.abspath(raw))


def contained(path, root):
    return path == root or root in path.parents


def check_attributes(path, info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & UNSUPPORTED_ATTRIBUTES:
        raise CopyError(f"Linked, offline, encrypted or cloud placeholder path is unsupported: {path}")


def check_ancestors(path):
    for item in reversed((path, *path.parents)):
        info = item.lstat()
        check_attributes(item, info)
        if not stat.S_ISDIR(info.st_mode):
            raise CopyError(f"Expected a directory: {item}")


def reject_managed(path):
    # Known managed roots are excluded even if their files are currently hydrated.
    blocked_names = {"appdata", "program files", "program files (x86)", "programdata", "windows", "$recycle.bin", "system volume information", "dropbox", "google drive", "googledrive", "icloud drive", ".git", ".svn"}
    if any(part.casefold() in blocked_names or part.casefold().startswith("onedrive") for part in path.parts):
        raise CopyError(f"System, application or cloud-managed folder is unsupported: {path}")
    if os.name == "nt":
        for key in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA", "OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            location = os.environ.get(key)
            if location and contained(path, absolute(location)):
                raise CopyError(f"Managed root ({key}) is unsupported: {path}")


def relative_name(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CopyError("Invalid portable relative path")
    parts = value.split("/")
    if PurePosixPath(value).is_absolute() or any(
        not part or part in (".", "..") or part[-1:] in (".", " ")
        or any(ord(ch) < 32 or ch in '<>:"|?*' for ch in part)
        or RESERVED.match(part) for part in parts
    ):
        raise CopyError(f"Unsafe or nonportable relative path: {value!r}")
    return value


def stream_inventory(path):
    if os.name != "nt":
        return []
    from ctypes import wintypes

    class StreamData(ctypes.Structure):
        _fields_ = [("size", ctypes.c_longlong), ("name", ctypes.c_wchar * 296)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    first = kernel.FindFirstStreamW
    first.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(StreamData), wintypes.DWORD]
    first.restype = wintypes.HANDLE
    next_stream = kernel.FindNextStreamW
    next_stream.argtypes = [wintypes.HANDLE, ctypes.POINTER(StreamData)]
    next_stream.restype = wintypes.BOOL
    close = kernel.FindClose
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    data = StreamData()
    handle = first(str(path), 0, ctypes.byref(data), 0)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error == 38:  # No streams (e.g. an empty directory).
            return []
        raise CopyError(f"Cannot verify alternate streams on {path}: Windows error {error}")
    streams = []
    try:
        while True:
            streams.append((data.name, data.size))
            if len(streams) > 64:
                raise CopyError(f"Too many alternate streams: {path}")
            if not next_stream(handle, ctypes.byref(data)):
                error = ctypes.get_last_error()
                if error != 38:
                    raise CopyError(f"Cannot enumerate streams on {path}: Windows error {error}")
                break
    finally:
        close(handle)
    return streams


def check_streams(path):
    # Shared by cache cleanup: remain strict unless a copy explicitly opts in.
    if any(name != "::$DATA" for name, size in stream_inventory(path)):
        raise CopyError(f"Alternate data streams are unsupported by this policy: {path}")


def require_zone_support():
    if os.name != "nt":
        raise CopyError("Zone.Identifier preservation requires native Windows")


def zone_descriptor(path):
    """Validate the observed stream set and return marker length or None.

    Enumerates metadata only; safe to call while native data handles are held.
    The stream inventory is not frozen against concurrent creation/deletion.
    """
    require_zone_support()
    main_seen, zone_seen, zone_size = False, False, None
    for name, size in stream_inventory(path):
        if name == "::$DATA" and not main_seen:
            main_seen = True
        elif name.isascii() and name.lower() == ":zone.identifier:$data" and not zone_seen:
            if not 0 <= size <= MAX_ZONE_BYTES:
                raise CopyError(f"Zone.Identifier exceeds the {MAX_ZONE_BYTES}-byte limit: {path}")
            zone_seen, zone_size = True, size
        else:
            raise CopyError(f"Unsupported or duplicate alternate stream on {path}: {name!r}")
    if not main_seen:
        raise CopyError(f"Cannot establish the ordinary file's primary stream: {path}")
    return zone_size


def zone_fingerprint(content):
    return None if content is None else {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def read_zone_identifier(path):
    """Read at most 64 KiB of opaque marker bytes, never interpret its URLs."""
    require_zone_support()
    check_ancestors(path.parent)
    before = path.lstat()
    check_attributes(path, before)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise CopyError(f"Marker requires an ordinary singly linked file: {path}")
    size = zone_descriptor(path)
    if size is None:
        return None
    with open(str(path) + ZONE_SUFFIX, "rb") as stream:
        info = os.fstat(stream.fileno())
        check_attributes(path, info)
        if (info.st_dev, info.st_ino, info.st_size) != (before.st_dev, before.st_ino, size):
            raise CopyError(f"Marker identity changed while opening: {path}")
        content = stream.read(MAX_ZONE_BYTES + 1)
        if len(content) != size or file_identity(os.fstat(stream.fileno())) != file_identity(info):
            raise CopyError(f"Marker changed while reading: {path}")
    if file_identity(path.lstat()) != file_identity(before) or zone_descriptor(path) != size:
        raise CopyError(f"File or marker changed while reading: {path}")
    return content


def write_zone_identifier(destination, content):
    """Create/verify the marker on a new empty target BEFORE copying payload.

    No strip/sidecar fallback. A failure preserves the source and partial target.
    """
    require_zone_support()
    if content is not None and (not isinstance(content, bytes) or len(content) > MAX_ZONE_BYTES):
        raise CopyError("Invalid Zone.Identifier payload")
    check_ancestors(destination.parent)
    before = checked_file(destination)
    if before.st_size != 0:
        raise CopyError("Marker must be written before destination primary content")
    if content is not None:
        with open(str(destination) + ZONE_SUFFIX, "xb") as stream:
            info = os.fstat(stream.fileno())
            if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
                raise CopyError("Marker target is no longer the exclusive destination file")
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    after = checked_file(destination, preserve_zone_identifier=True)
    if (after.st_dev, after.st_ino, after.st_size) != (before.st_dev, before.st_ino, 0):
        raise CopyError("Destination changed before copying primary content")
    if read_zone_identifier(destination) != content:
        raise CopyError("Destination marker verification failed before copying primary content")


def file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def checked_file(path, preserve_zone_identifier=False):
    check_ancestors(path.parent)
    info = path.lstat()
    check_attributes(path, info)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise CopyError(f"Special files and hard links are unsupported: {path}")
    if preserve_zone_identifier:
        zone_descriptor(path)
    else:
        check_streams(path)
    return info


def open_source(path, info):
    # O_NOFOLLOW closes the final-component link race where supported. Parent
    # checks are best effort; this tool is not a hostile multi-user race sandbox.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    stream = os.fdopen(descriptor, "rb")
    opened = os.fstat(stream.fileno())
    if not stat.S_ISREG(opened.st_mode) or file_identity(opened) != file_identity(info):
        stream.close()
        raise CopyError(f"Source changed while opening: {path}")
    return stream


def fingerprint(path, preserve_zone_identifier=False):
    before = checked_file(path, preserve_zone_identifier=preserve_zone_identifier)
    marker = read_zone_identifier(path) if preserve_zone_identifier else None
    digest = hashlib.sha256()
    with open_source(path, before) as source:
        for chunk in iter(lambda: source.read(CHUNK), b""):
            digest.update(chunk)
        if file_identity(os.fstat(source.fileno())) != file_identity(before):
            raise CopyError(f"Source changed while reading: {path}")
    after = checked_file(path, preserve_zone_identifier=preserve_zone_identifier)
    if file_identity(before) != file_identity(after):
        raise CopyError(f"Source changed while reading: {path}")
    result = {"size": before.st_size, "mtime_ns": before.st_mtime_ns, "device": before.st_dev,
              "inode": before.st_ino, "sha256": digest.hexdigest()}
    if preserve_zone_identifier:
        if read_zone_identifier(path) != marker:
            raise CopyError(f"Marker changed while fingerprinting: {path}")
        result["zone_identifier"] = zone_fingerprint(marker)
    return result


def content_signature(item):
    marker = item.get("zone_identifier")
    return (item.get("path"), item["size"], item["sha256"],
            None if marker is None else (marker["size"], marker["sha256"]))


def _fingerprint_for_policy(path, preserve_zone_identifier):
    return fingerprint(path, preserve_zone_identifier=True) if preserve_zone_identifier else fingerprint(path)


def inventory(root, preserve_zone_identifier=False):
    check_ancestors(root)
    reject_managed(root)
    check_streams(root)
    files, directories = [], []
    stack = [root]
    seen = set()
    count = 0
    while stack:
        directory = stack.pop()
        check_ancestors(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise CopyError(f"Source exceeds the {MAX_ENTRIES} entry limit")
                path = Path(entry.path)
                name = relative_name(path.relative_to(root).as_posix())
                if name.casefold() in seen:
                    raise CopyError(f"Case-insensitive path collision: {name}")
                seen.add(name.casefold())
                info = entry.stat(follow_symlinks=False)
                check_attributes(path, info)
                if stat.S_ISDIR(info.st_mode):
                    reject_managed(path)
                    check_streams(path)
                    directories.append(name)
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    files.append({"path": name, **_fingerprint_for_policy(path, preserve_zone_identifier)})
                else:
                    raise CopyError(f"Special files are unsupported: {path}")
    return sorted(files, key=lambda item: item["path"]), sorted(directories)


def selection_directories(selected_paths):
    """Validate exact selectors and return only their required parent paths."""
    if not isinstance(selected_paths, list) or not selected_paths or len(selected_paths) > MAX_ENTRIES:
        raise CopyError("File selection must contain 1 to 100000 exact relative file paths")
    files_seen, directory_spellings = set(), {}
    for value in selected_paths:
        name = relative_name(value)
        if name.casefold() in files_seen:
            raise CopyError("Duplicate or case-colliding selected file")
        files_seen.add(name.casefold())
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            key = parent.as_posix().casefold()
            previous = directory_spellings.setdefault(key, parent.as_posix())
            if previous != parent.as_posix():
                raise CopyError("Case-colliding selected parent directory")
            if len(directory_spellings) + len(files_seen) > MAX_ENTRIES:
                raise CopyError("Selected files and parent directories exceed entry limit")
            parent = parent.parent
        if len(directory_spellings) + len(files_seen) > MAX_ENTRIES:
            raise CopyError("Selected files and parent directories exceed entry limit")
    if files_seen & directory_spellings.keys():
        raise CopyError("A selected path cannot be both a file and a parent directory")
    return sorted(directory_spellings.values())


def selected_inventory(root, selected_paths, preserve_zone_identifier=False):
    """Hash exact selected files without enumerating or reading their siblings."""
    directories = selection_directories(selected_paths)
    check_ancestors(root)
    reject_managed(root)
    check_streams(root)
    actual_root = root.resolve(strict=True)
    reject_managed(actual_root)
    for name in directories:
        path = root.joinpath(*name.split("/"))
        check_ancestors(path)
        reject_managed(path)
        reject_managed(path.resolve(strict=True))
        check_streams(path)
    files = []
    for name in sorted(selected_paths):
        path = root.joinpath(*name.split("/"))
        reject_managed(path.parent)
        checked_file(path, preserve_zone_identifier=preserve_zone_identifier)
        actual_path = path.resolve(strict=True)
        reject_managed(actual_path.parent)
        if actual_path.relative_to(actual_root).as_posix() != name:
            raise CopyError(f"Selected file must use its exact on-disk spelling: {name}")
        # Selection never expands globs or reads siblings. Stream handling is
        # confined to the explicit plan policy, with all directory ADS excluded.
        files.append({"path": name, **_fingerprint_for_policy(path, preserve_zone_identifier)})
    return files, directories


def inventory_for_plan(root, plan):
    """Inventory the approved scope; callers must first validate the copy plan."""
    if plan.get("schema_version") == 1:
        return inventory(root)
    preserve_zone_identifier = plan.get("schema_version") == ZONE_VERSION
    scope = plan.get("scope")
    if scope == "tree" and plan.get("selected_paths") == []:
        return inventory(root, preserve_zone_identifier=preserve_zone_identifier)
    if scope == "files":
        return selected_inventory(root, plan.get("selected_paths"), preserve_zone_identifier=preserve_zone_identifier)
    raise CopyError("Invalid plan selection scope")


def canonical_id(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def check_locations(source, destination, require_new_destination=True):
    check_ancestors(source)
    check_ancestors(destination.parent)
    reject_managed(source)
    reject_managed(destination)
    if source == Path(source.anchor):
        raise CopyError("Copying a filesystem root is unsupported")
    relative_name(destination.name)
    # After rejecting linked ancestors, resolve native spellings (e.g. Windows
    # 8.3 aliases) before checking overlap. Do not use resolve to bypass links.
    actual_source = source.resolve(strict=True)
    reject_managed(actual_source)
    if require_new_destination:
        if os.path.lexists(destination):
            raise CopyError("Destination must not exist; merging or overwriting is unsupported")
        actual_destination = destination.parent.resolve(strict=True) / destination.name
    else:
        # Used by independent verification/release tools after a copy. Existing
        # destination still must be a plain directory with unlinked ancestors.
        check_ancestors(destination)
        check_streams(destination)
        actual_destination = destination.resolve(strict=True)
    reject_managed(actual_destination)
    if contained(actual_destination, actual_source) or contained(actual_source, actual_destination):
        raise CopyError("Source and destination must be separate, nonoverlapping trees")


def external_output(value, source, destination):
    # Check before abspath: Windows may strip a final dot/space and otherwise
    # turn a rejected name into a different ordinary file silently.
    relative_name(os.path.basename(os.fspath(value)))
    path = absolute(value)
    # Reject alternate data stream syntax and Windows alias/device names before
    # opening a report: exclusive stream creation can still modify an existing
    # ordinary file (e.g. existing.txt:plan.json) on NTFS.
    relative_name(path.name)
    check_ancestors(path.parent)
    actual_path = path.parent.resolve(strict=True) / path.name
    actual_source = source.resolve(strict=True)
    actual_destination = destination.parent.resolve(strict=True) / destination.name
    if contained(actual_path, actual_source) or contained(actual_path, actual_destination):
        raise CopyError("Plan and receipt files must be outside source and destination trees")
    return path


def write_json(stream, value):
    json.dump(value, stream, indent=2, ensure_ascii=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())


def make_plan(source, destination, output, include=None, preserve_zone_identifier=False):
    if type(preserve_zone_identifier) is not bool:
        raise CopyError("preserve_zone_identifier must be a boolean")
    if preserve_zone_identifier:
        require_zone_support()
    relative_name(os.path.basename(os.fspath(destination)))
    source, destination = absolute(source), absolute(destination)
    check_locations(source, destination)
    output = external_output(output, source, destination)
    if os.path.lexists(output):
        raise CopyError("Plan output must not already exist")
    if include is None:
        scope, selected_paths = "tree", []
        files, directories = inventory(source, preserve_zone_identifier=preserve_zone_identifier)
    else:
        # Reject duplicate selectors instead of silently broadening or changing
        # an explicit choice. Names use '/' even in Windows PowerShell.
        selection_directories(include)
        scope, selected_paths = "files", sorted(include)
        files, directories = selected_inventory(source, selected_paths, preserve_zone_identifier=preserve_zone_identifier)
    payload = {"schema_version": ZONE_VERSION if preserve_zone_identifier else VERSION, "kind": KIND, "source": str(source),
               "destination": str(destination), "files": files, "directories": directories,
               "scope": scope, "selected_paths": selected_paths,
               "total_bytes": sum(item["size"] for item in files), "created_at": utc_now()}
    if preserve_zone_identifier:
        payload.update(stream_policy=ZONE_POLICY,
                       zone_identifier_bytes=sum(item["zone_identifier"]["size"] for item in files if item["zone_identifier"] is not None))
    plan = {**payload, "plan_id": canonical_id(payload)}
    check_ancestors(output.parent)
    with output.open("x", encoding="utf-8") as stream:
        write_json(stream, plan)
    return plan


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CopyError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_plan(path):
    with open(path, "rb") as stream:
        raw = stream.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise CopyError("Plan exceeds size limit")
    return json.loads(raw, object_pairs_hook=strict_object)


def validate_plan(plan, approval, require_new_destination=True):
    keys = {"schema_version", "kind", "source", "destination", "files", "directories", "total_bytes", "created_at", "plan_id"}
    if not isinstance(plan, dict) or type(plan.get("schema_version")) is not int or plan["schema_version"] not in (1, VERSION, ZONE_VERSION):
        raise CopyError("Unsupported plan schema")
    if plan["schema_version"] >= VERSION:
        keys |= {"scope", "selected_paths"}
    preserve_zone_identifier = plan["schema_version"] == ZONE_VERSION
    if preserve_zone_identifier:
        require_zone_support()
        keys |= {"stream_policy", "zone_identifier_bytes"}
    if set(plan) != keys or plan["kind"] != KIND:
        raise CopyError("Unsupported plan schema")
    if preserve_zone_identifier and plan["stream_policy"] != ZONE_POLICY:
        raise CopyError("Unsupported alternate-stream policy")
    if not all(isinstance(plan[key], str) for key in ("source", "destination", "created_at", "plan_id")):
        raise CopyError("Invalid plan strings")
    payload = {key: value for key, value in plan.items() if key != "plan_id"}
    if canonical_id(payload) != plan["plan_id"] or approval != plan["plan_id"]:
        raise CopyError("Plan ID mismatch or missing explicit approval")
    source, destination = absolute(plan["source"]), absolute(plan["destination"])
    if str(source) != plan["source"] or str(destination) != plan["destination"]:
        raise CopyError("Plan paths must be canonical absolute paths")
    if not isinstance(plan["files"], list) or not isinstance(plan["directories"], list) or len(plan["files"]) + len(plan["directories"]) > MAX_ENTRIES:
        raise CopyError("Invalid or oversized inventory")
    seen, file_names, directories = set(), set(), set()
    for name in plan["directories"]:
        name = relative_name(name)
        if name.casefold() in seen:
            raise CopyError("Duplicate or case-colliding plan path")
        seen.add(name.casefold())
        directories.add(name)
    for item in plan["files"]:
        file_keys = {"path", "size", "mtime_ns", "device", "inode", "sha256"}
        if preserve_zone_identifier:
            file_keys.add("zone_identifier")
        if not isinstance(item, dict) or set(item) != file_keys:
            raise CopyError("Invalid file entry")
        name = relative_name(item["path"])
        if name.casefold() in seen:
            raise CopyError("Duplicate or case-colliding plan path")
        seen.add(name.casefold())
        file_names.add(name)
        if any(type(item[key]) is not int or (key != "mtime_ns" and item[key] < 0) for key in ("size", "mtime_ns", "device", "inode")):
            raise CopyError("Invalid file metadata")
        if not isinstance(item["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", item["sha256"]):
            raise CopyError("Invalid file digest")
        if preserve_zone_identifier:
            marker = item["zone_identifier"]
            if marker is not None:
                if (not isinstance(marker, dict) or set(marker) != {"size", "sha256"}
                        or type(marker["size"]) is not int or not 0 <= marker["size"] <= MAX_ZONE_BYTES
                        or not isinstance(marker["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", marker["sha256"])):
                    raise CopyError("Invalid Zone.Identifier descriptor")
    for name in file_names | directories:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            if parent.as_posix() not in directories:
                raise CopyError("Missing parent directory in plan")
            parent = parent.parent
    if type(plan["total_bytes"]) is not int or plan["total_bytes"] != sum(item["size"] for item in plan["files"]):
        raise CopyError("Invalid total bytes")
    if preserve_zone_identifier:
        if (type(plan["zone_identifier_bytes"]) is not int
                or plan["zone_identifier_bytes"] != sum(item["zone_identifier"]["size"] for item in plan["files"] if item["zone_identifier"] is not None)):
            raise CopyError("Invalid Zone.Identifier byte total")
    if plan["schema_version"] >= VERSION:
        if plan["scope"] == "tree":
            if plan["selected_paths"] != []:
                raise CopyError("Whole-tree plans must have an empty selected_paths list")
        elif plan["scope"] == "files":
            expected_directories = selection_directories(plan["selected_paths"])
            if plan["selected_paths"] != sorted(plan["selected_paths"]):
                raise CopyError("Selected paths must be in canonical sorted order")
            if [item["path"] for item in plan["files"]] != plan["selected_paths"] or plan["directories"] != expected_directories:
                raise CopyError("Plan inventory must match exactly the selected files and necessary parent directories")
        else:
            raise CopyError("Invalid selection scope")
    check_locations(source, destination, require_new_destination)
    return source, destination


def check_snapshot(source, plan):
    files, directories = inventory_for_plan(source, plan)
    if files != plan["files"] or directories != plan["directories"]:
        raise CopyError("Source changed since planning; create and review a new plan")


def copy_file(source, destination, item):
    preserve_zone_identifier = "zone_identifier" in item
    before = checked_file(source, preserve_zone_identifier=preserve_zone_identifier)
    if file_identity(before) != (item["device"], item["inode"], item["size"], item["mtime_ns"]):
        raise CopyError(f"Source metadata changed: {source}")
    check_ancestors(destination.parent)
    marker = read_zone_identifier(source) if preserve_zone_identifier else None
    if preserve_zone_identifier and zone_fingerprint(marker) != item["zone_identifier"]:
        raise CopyError(f"Source marker changed since planning: {source}")
    digest = hashlib.sha256()
    with open_source(source, before) as incoming, destination.open("xb") as outgoing:
        # Failure to preserve provenance leaves no unmarked executable payload.
        # Do not copy primary data before the marker's write/readback succeeds.
        if preserve_zone_identifier:
            write_zone_identifier(destination, marker)
        for chunk in iter(lambda: incoming.read(CHUNK), b""):
            outgoing.write(chunk)
            digest.update(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
        if file_identity(os.fstat(incoming.fileno())) != file_identity(before):
            raise CopyError(f"Source changed during copy: {source}")
    if digest.hexdigest() != item["sha256"] or file_identity(checked_file(source, preserve_zone_identifier=preserve_zone_identifier)) != file_identity(before):
        raise CopyError(f"Source content changed during copy: {source}")
    if preserve_zone_identifier and read_zone_identifier(source) != marker:
        raise CopyError(f"Source marker changed during copy: {source}")
    copied = {"path": item["path"], **_fingerprint_for_policy(destination, preserve_zone_identifier)}
    if content_signature(copied) != content_signature(item):
        raise CopyError(f"Destination verification failed: {destination}")
    if os.utime in os.supports_follow_symlinks:
        os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns), follow_symlinks=False)
    else:
        # Windows does not expose follow_symlinks=False for utime in all Python
        # builds. Recheck the exclusive output before setting its timestamps.
        checked_file(destination, preserve_zone_identifier=preserve_zone_identifier)
        os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))


def apply_plan(plan_path, approval, receipt_path):
    plan = load_plan(plan_path)
    source, destination = validate_plan(plan, approval)
    preserve_zone_identifier = plan["schema_version"] == ZONE_VERSION
    receipt_path = external_output(receipt_path, source, destination)
    receipt = {"schema_version": ZONE_VERSION if preserve_zone_identifier else VERSION, "kind": "disk-steward-copy-receipt", "plan_id": plan["plan_id"],
               "source": str(source), "destination": str(destination), "source_preserved": True,
               "status": "failed", "verified_files": 0, "verified_bytes": 0, "started_at": utc_now(),
               "source_deleted": False, "reclaimed_bytes": 0,
               "limits": "Bytes and basic file timestamps only; no ACL, ownership, application or backup guarantee."}
    if preserve_zone_identifier:
        receipt.update(stream_policy=ZONE_POLICY, verified_zone_identifier_bytes=0,
                       verified_zone_identifier_files=0,
                       limits="Primary bytes, basic timestamps and observed Zone.Identifier bytes only; not a full NTFS backup or a frozen stream inventory.")
    # Reserve the receipt before copying; never overwrite an earlier receipt.
    with receipt_path.open("x", encoding="utf-8") as receipt_stream:
        write_json(receipt_stream, {**receipt, "status": "in_progress"})
        try:
            check_snapshot(source, plan)
            check_locations(source, destination)
            # Logical length is a lower bound for destination storage requirements.
            marker_count = sum(item.get("zone_identifier") is not None for item in plan["files"])
            needed = plan["total_bytes"] + plan.get("zone_identifier_bytes", 0) + (len(plan["files"]) + len(plan["directories"]) + marker_count + 1) * 65536
            if shutil.disk_usage(destination.parent).free < needed:
                raise CopyError("Insufficient destination free space including allocation allowance")
            destination.mkdir()  # Exclusive; never merge with an existing directory.
            receipt["status"] = "partial"
            for name in sorted(plan["directories"], key=lambda item: (item.count("/"), item)):
                target = destination.joinpath(*name.split("/"))
                check_ancestors(target.parent)
                target.mkdir()
            for item in plan["files"]:
                parts = item["path"].split("/")
                copy_file(source.joinpath(*parts), destination.joinpath(*parts), item)
                receipt["verified_files"] += 1
                receipt["verified_bytes"] += item["size"]
                if preserve_zone_identifier and item["zone_identifier"] is not None:
                    receipt["verified_zone_identifier_bytes"] += item["zone_identifier"]["size"]
                    receipt["verified_zone_identifier_files"] += 1
            check_snapshot(source, plan)
            # Verify all destination bytes again after the entire copy to catch
            # normal late changes. Metadata identity differs by design.
            copied_files, copied_dirs = inventory(destination, preserve_zone_identifier=preserve_zone_identifier)
            if copied_dirs != plan["directories"] or [content_signature(x) for x in copied_files] != [content_signature(x) for x in plan["files"]]:
                raise CopyError("Destination changed before final verification")
            receipt["status"] = "verified"
        except (OSError, ValueError, OverflowError, NotImplementedError) as error:
            receipt["error"] = str(error)
        except KeyboardInterrupt:
            receipt["error"] = "Interrupted; partial destination preserved for review"
        finally:
            receipt["finished_at"] = utc_now()
            receipt_stream.seek(0)
            receipt_stream.truncate()
            write_json(receipt_stream, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="Hash ordinary files and write a reviewable copy plan")
    planning.add_argument("--source", required=True)
    planning.add_argument("--destination", required=True)
    planning.add_argument("--output", required=True)
    planning.add_argument("--include", action="append", help="Exact relative file path using '/', repeat to select files; omitted means whole tree. No globs or directories.")
    planning.add_argument("--preserve-zone-identifier", action="store_true", help="Native Windows: explicitly preserve and verify opaque Zone.Identifier bytes (max 64 KiB); reject every other ADS.")
    applying = commands.add_parser("apply", help="Copy approved files without deleting the source")
    applying.add_argument("--plan", required=True)
    applying.add_argument("--approve", required=True, help="Full plan_id from the reviewed plan")
    applying.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = make_plan(args.source, args.destination, args.output, args.include, args.preserve_zone_identifier)
            print(json.dumps({"plan_id": result["plan_id"], "scope": result["scope"], "files": len(result["files"]), "total_bytes": result["total_bytes"],
                              "stream_policy": result.get("stream_policy", "reject-all-alternate-streams"),
                              "zone_identifier_bytes": result.get("zone_identifier_bytes", 0), "source_preserved": True}))
        else:
            result = apply_plan(args.plan, args.approve, args.receipt)
            print(json.dumps(result, ensure_ascii=True))
            if result["status"] != "verified":
                return 2
        return 0
    except (OSError, ValueError, OverflowError) as error:
        print(json.dumps({"error": str(error), "source_deleted": False}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
