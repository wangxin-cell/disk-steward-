#!/usr/bin/env python3
"""Read-only, bounded Windows uninstall-registration evidence; stdlib only.

collect() reads four fixed HKLM/HKCU x 32/64-bit registry scopes. It queries
only DisplayName, DisplayVersion, Publisher and InstallLocation, never uninstall
commands. REG_EXPAND_SZ is retained verbatim, not expanded. Registration is a
limited snapshot: a record does not prove current installation or ownership,
and a missing record does not establish that a path is an uninstall remnant.

validate_inventory(data) returns the validated dict or raises InventoryError.
assess_path(inventory, path, directory=False) compares strings only. For batches,
make_assessor(inventory) validates and indexes once and returns the same callable.
No listed installation/candidate path is opened, traversed or modified.

CLI: app_inventory.py collect --output NEW.json [--max-entries 1000]
Only the explicit, exclusively created JSON output is written. No apply command.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import ntpath
import os
from pathlib import Path
import re
import sys
import unicodedata

import disk_scan as scanner

MAX_ENTRIES = 1000
MAX_TEXT = 4096
MAX_ERRORS = 32
MAX_ERROR_TEXT = 512
MAX_JSON_BYTES = 2 * 1024 * 1024
REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
SCOPES = (("HKLM", "32"), ("HKLM", "64"), ("HKCU", "32"), ("HKCU", "64"))
VALUE_FIELDS = (("DisplayName", "display_name"), ("DisplayVersion", "display_version"),
                ("Publisher", "publisher"), ("InstallLocation", "install_location"))
ENTRY_KEYS = {"hive", "view", "subkey", *(field for _, field in VALUE_FIELDS)}
SCOPE_KEYS = {"hive", "view", "status", "entries_examined", "errors"}
INVENTORY_KEYS = {"schema_version", "kind", "created_at", "coverage", "incomplete",
                  "max_entries", "entries_examined", "scopes", "entries"}


class InventoryError(ValueError):
    """Invalid or unsupported inventory input."""


def _keys(value, expected):
    if type(value) is not dict or set(value) != expected:
        raise InventoryError("Unexpected object fields in application inventory")


def _integer(value, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InventoryError("Application inventory integer is out of range")


def _text(value, limit=MAX_TEXT, *, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not str or len(value) > limit or any(
        ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF for char in value
    ):
        raise InventoryError("Application inventory text is invalid or too long")


def _subkey(value):
    _text(value)
    if not value or "\\" in value or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
        raise InventoryError("Invalid registration child-key name")


def _encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def validate_inventory(data):
    """Validate the exact schema, bounded fields and cross-field consistency."""
    _keys(data, INVENTORY_KEYS)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InventoryError("Unsupported application inventory schema")
    if data["kind"] != "disk-steward-application-inventory" or data["coverage"] != "uninstall_registration_only":
        raise InventoryError("Unsupported application inventory coverage")
    _text(data["created_at"], 64)
    try:
        timestamp = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        if "T" not in data["created_at"] or timestamp.utcoffset() is None:
            raise ValueError
    except ValueError as error:
        raise InventoryError("created_at must be a timezone-aware ISO timestamp") from error
    if type(data["incomplete"]) is not bool:
        raise InventoryError("incomplete must be a boolean")
    _integer(data["max_entries"], MAX_ENTRIES, 1)
    _integer(data["entries_examined"], data["max_entries"])
    scopes = data["scopes"]
    entries = data["entries"]
    if type(scopes) is not list or len(scopes) != len(SCOPES):
        raise InventoryError("All four fixed registry scopes are required")
    if type(entries) is not list or len(entries) > data["entries_examined"]:
        raise InventoryError("Invalid application inventory entries")
    examined = 0
    incomplete = False
    for scope, identity in zip(scopes, SCOPES):
        _keys(scope, SCOPE_KEYS)
        if (scope["hive"], scope["view"]) != identity:
            raise InventoryError("Registry scopes must be unique and in fixed hive/view order")
        if scope["status"] not in ("complete", "missing", "partial", "not_examined"):
            raise InventoryError("Unknown registry scope status")
        _integer(scope["entries_examined"], data["max_entries"])
        if type(scope["errors"]) is not list or len(scope["errors"]) > MAX_ERRORS:
            raise InventoryError("Invalid registry scope errors")
        for error in scope["errors"]:
            _text(error, MAX_ERROR_TEXT)
            if not error:
                raise InventoryError("Registry error must not be empty")
        if bool(scope["errors"]) != (scope["status"] == "partial"):
            raise InventoryError("Only partial scopes have nonempty errors")
        if scope["status"] in ("missing", "not_examined") and scope["entries_examined"]:
            raise InventoryError("Unexamined or missing scopes cannot contain examined entries")
        examined += scope["entries_examined"]
        incomplete |= scope["status"] in ("partial", "not_examined")
    if examined != data["entries_examined"] or incomplete != data["incomplete"]:
        raise InventoryError("Scope counts or incomplete flag disagree with inventory")
    counts = Counter()
    seen = set()
    for entry in entries:
        _keys(entry, ENTRY_KEYS)
        identity = (entry["hive"], entry["view"])
        if identity not in SCOPES:
            raise InventoryError("Entry has an unsupported registry scope")
        _subkey(entry["subkey"])
        key = (*identity, entry["subkey"].lower())
        if key in seen:
            raise InventoryError("Duplicate application registration key")
        seen.add(key)
        counts[identity] += 1
        for _, field in VALUE_FIELDS:
            _text(entry[field], nullable=True)
    for scope in scopes:
        count = counts[(scope["hive"], scope["view"])]
        if count > scope["entries_examined"] or (scope["status"] == "complete" and count != scope["entries_examined"]):
            raise InventoryError("Entry counts disagree with their registry scope")
    # Count the exact UTF-8 output, including the final newline, without first
    # constructing a potentially oversized serialized copy of direct dict input.
    encoded_size = 1
    for chunk in json.JSONEncoder(ensure_ascii=False, indent=2, allow_nan=False).iterencode(data):
        encoded_size += len(chunk.encode("utf-8"))
        if encoded_size > MAX_JSON_BYTES:
            raise InventoryError("Application inventory exceeds the 2 MiB JSON limit")
    return data


def _error(scope, message):
    scope["status"] = "partial"
    if len(scope["errors"]) < MAX_ERRORS:
        scope["errors"].append(message[:MAX_ERROR_TEXT])


def _missing(error):
    return isinstance(error, FileNotFoundError) or getattr(error, "winerror", None) == 2


def collect(max_entries=MAX_ENTRIES, registry=None):
    """Collect bounded registration metadata. Inject a winreg-like fake in tests."""
    _integer(max_entries, MAX_ENTRIES, 1)
    if registry is None:
        if os.name != "nt":
            raise InventoryError("Native registration collection requires Windows")
        import winreg as registry
    result = {
        "schema_version": 1, "kind": "disk-steward-application-inventory",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "coverage": "uninstall_registration_only", "incomplete": False,
        "max_entries": max_entries, "entries_examined": 0,
        "scopes": [{"hive": hive, "view": view, "status": "not_examined",
                    "entries_examined": 0, "errors": []} for hive, view in SCOPES],
        "entries": [],
    }
    # Reserve the maximum escaped error text and structural overhead so stopping
    # collection itself can always be reported within the total JSON byte bound.
    entry_limit = MAX_JSON_BYTES - 4 * MAX_ERRORS * (MAX_ERROR_TEXT * 6 + 128) - 8192
    entry_bytes = 0
    seen = set()
    stopped = False
    for scope in result["scopes"]:
        if stopped:
            break
        hive = registry.HKEY_LOCAL_MACHINE if scope["hive"] == "HKLM" else registry.HKEY_CURRENT_USER
        view = registry.KEY_WOW64_32KEY if scope["view"] == "32" else registry.KEY_WOW64_64KEY
        access = registry.KEY_READ | view
        scope["status"] = "complete"
        try:
            root = registry.OpenKey(hive, REGISTRY_PATH, 0, access)
        except OSError as error:
            if _missing(error):
                scope["status"] = "missing"
            else:
                _error(scope, "Cannot read this fixed registry scope")
            continue
        with root:
            index = 0
            while True:
                if result["entries_examined"] >= max_entries:
                    _error(scope, "Global examined-entry budget reached; remaining coverage is unknown")
                    stopped = True
                    break
                try:
                    subkey = registry.EnumKey(root, index)
                except OSError as error:
                    if getattr(error, "winerror", None) != 259:  # ERROR_NO_MORE_ITEMS
                        _error(scope, "Cannot enumerate all registration child keys")
                    break
                index += 1
                scope["entries_examined"] += 1
                result["entries_examined"] += 1
                try:
                    _subkey(subkey)
                except InventoryError:
                    _error(scope, "Registration child-key name is invalid or oversized")
                    continue
                identity = (scope["hive"], scope["view"], subkey.lower())
                if identity in seen:
                    _error(scope, "Duplicate registration child key observed during enumeration")
                    continue
                seen.add(identity)
                entry = {"hive": scope["hive"], "view": scope["view"], "subkey": subkey,
                         **{field: None for _, field in VALUE_FIELDS}}
                try:
                    child = registry.OpenKey(root, subkey, 0, access)
                except OSError:
                    _error(scope, "Cannot read an enumerated registration child key")
                    continue
                with child:
                    for value_name, field in VALUE_FIELDS:
                        try:
                            value, value_type = registry.QueryValueEx(child, value_name)
                        except OSError as error:
                            if not _missing(error):
                                _error(scope, f"Cannot read registration value {value_name}")
                            continue
                        try:
                            _text(value)
                            if type(value_type) is not int or value_type not in (registry.REG_SZ, registry.REG_EXPAND_SZ):
                                raise InventoryError("Non-string registry type")
                        except InventoryError:
                            _error(scope, f"Invalid or oversized registration value {value_name}")
                            continue
                        entry[field] = value
                encoded = _encoded(entry)
                size = len(encoded) + 4 * (encoded.count(b"\n") + 1) + 2
                if entry_bytes + size > entry_limit:
                    _error(scope, "JSON byte budget reached; remaining coverage is unknown")
                    stopped = True
                    break
                entry_bytes += size
                result["entries"].append(entry)
    result["incomplete"] = any(scope["status"] in ("partial", "not_examined") for scope in result["scopes"])
    return validate_inventory(result)


def _windows_parts(value):
    """Lexical local-path comparison only; never ask the filesystem to resolve."""
    if type(value) is not str or not 3 <= len(value) <= MAX_TEXT:
        return None
    if not re.match(r"^[A-Za-z]:[\\/]", value) or "%" in value or any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value
    ):
        return None
    remainder = value[3:].replace("/", "\\")
    if remainder.endswith("\\"):
        remainder = remainder[:-1]
    parts = remainder.split("\\") if remainder else []
    if any(not part or part in (".", "..") or part.endswith((".", " ")) or
           scanner.RESERVED_NAME.match(part) or any(char in '<>:"|?*' for char in part) for part in parts):
        return None
    # Windows path normalization must not use Unicode casefold: it expands
    # distinct names such as Straße and STRASSE into the same spelling.
    return (value[0].lower(), *(ntpath.normcase(part) for part in parts))


def make_assessor(inventory):
    """Validate/index once, returning a pure string assessor for many targets."""
    validate_inventory(inventory)
    locations = []
    for entry in inventory["entries"]:
        parts = _windows_parts(entry["install_location"])
        if parts is not None and len(parts) > 1:  # A whole drive is not ownership evidence.
            locations.append((parts, dict(entry)))
    incomplete = inventory["incomplete"]

    def assess(path, directory=False):
        if type(directory) is not bool:
            raise InventoryError("directory must be a boolean")
        candidate = _windows_parts(path)
        matches = []
        if candidate is not None:
            for location, entry in locations:
                if len(candidate) >= len(location) and candidate[:len(location)] == location:
                    relation = "inside_registered_location"
                elif directory and len(candidate) < len(location) and location[:len(candidate)] == candidate:
                    relation = "contains_registered_location"
                else:
                    continue
                matches.append({**entry, "relation": relation})
        return {"status": ("unsupported_candidate_path" if candidate is None else
                           "registration_path_overlap" if matches else "no_registration_path_match"),
                "matches": matches, "match_count": len(matches), "incomplete": incomplete}

    return assess


def assess_path(inventory, path, directory=False):
    return make_assessor(inventory)(path, directory=directory)


def _output_path(value):
    raw = os.fspath(value)
    if not raw or len(raw) > MAX_TEXT or raw.startswith(("\\\\", "//")) or re.match(r"^[a-zA-Z]:(?:$|[^\\/])", raw):
        raise InventoryError("An explicit local output path is required; UNC/device/drive-relative paths are unsupported")
    # Validate every component before abspath can normalize Windows aliases.
    tail = raw[2:] if re.match(r"^[A-Za-z]:", raw) else raw
    for part in re.split(r"[\\/]", tail):
        if not part or part == ".":
            continue
        if part == ".." or part.endswith((".", " ")) or scanner.RESERVED_NAME.match(part) or any(
            unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} or char in '<>:"|?*' for char in part
        ):
            raise InventoryError("Output path must have portable ordinary components without alternate streams")
    output = scanner.absolute_path(raw)
    scanner.check_ancestors(output.parent)
    return output


def write_inventory(path, inventory):
    validate_inventory(inventory)
    output = _output_path(path)
    with output.open("xb") as stream:
        stream.write(_encoded(inventory))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collector = commands.add_parser("collect", help="Read four fixed uninstall-registration scopes; never execute commands")
    collector.add_argument("--max-entries", type=int, default=MAX_ENTRIES, help="Global examined-key budget, 1..1000")
    collector.add_argument("--output", required=True, help="New JSON file; existing parent required; never overwrites")
    args = parser.parse_args(argv)
    try:
        output = _output_path(args.output)
        # A pre-existing output should fail before native collection is attempted.
        if output.exists() or output.is_symlink():
            raise FileExistsError("Inventory output already exists")
        inventory = collect(args.max_entries)
        write_inventory(output, inventory)
        print(json.dumps({"output": str(output), "entries_examined": inventory["entries_examined"],
                          "incomplete": inventory["incomplete"]}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(f"disk-steward: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
