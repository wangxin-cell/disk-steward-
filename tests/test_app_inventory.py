"""Registration evidence checks use a fake registry and disposable output only."""

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/disk-steward/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import app_inventory as inv
finally:
    sys.path.pop(0)


def winerror(code):
    error = OSError("synthetic registry error")
    error.winerror = code
    return error


class Handle:
    def __init__(self, registry, hive, view, subkey=None):
        self.registry, self.hive, self.view, self.subkey = registry, hive, view, subkey

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.registry.closed.append((self.hive, self.view, self.subkey))


class FakeRegistry:
    HKEY_LOCAL_MACHINE = "hklm-handle"
    HKEY_CURRENT_USER = "hkcu-handle"
    KEY_READ, KEY_WOW64_32KEY, KEY_WOW64_64KEY = 0x20019, 0x200, 0x100
    REG_SZ, REG_EXPAND_SZ = 1, 2

    def __init__(self, data=None):
        self.data = {scope: [] for scope in inv.SCOPES}
        self.data.update(data or {})
        self.calls, self.closed = [], []
        self.child_failures, self.enum_failures = {}, {}

    def OpenKey(self, key, path, reserved=0, access=0):
        self.calls.append(("open", key, path, reserved, access))
        if isinstance(key, Handle):
            assert access == self.KEY_READ | (self.KEY_WOW64_32KEY if key.view == "32" else self.KEY_WOW64_64KEY)
            assert key.subkey is None
            fault = self.child_failures.get((key.hive, key.view, path))
            if fault:
                raise fault
            assert any(name == path for name, values in self.data[(key.hive, key.view)])
            return Handle(self, key.hive, key.view, path)
        assert path == inv.REGISTRY_PATH and reserved == 0
        assert access in (self.KEY_READ | self.KEY_WOW64_32KEY, self.KEY_READ | self.KEY_WOW64_64KEY)
        assert key in (self.HKEY_LOCAL_MACHINE, self.HKEY_CURRENT_USER)
        hive = "HKLM" if key == self.HKEY_LOCAL_MACHINE else "HKCU"
        view = "32" if access & self.KEY_WOW64_32KEY else "64"
        if isinstance(self.data[(hive, view)], Exception):
            raise self.data[(hive, view)]
        return Handle(self, hive, view)

    def EnumKey(self, handle, index):
        self.calls.append(("enum", handle.hive, handle.view, index))
        if (handle.hive, handle.view, index) in self.enum_failures:
            raise self.enum_failures[(handle.hive, handle.view, index)]
        rows = self.data[(handle.hive, handle.view)]
        if index == len(rows):
            raise winerror(259)
        return rows[index][0]

    def QueryValueEx(self, handle, name):
        self.calls.append(("query", handle.hive, handle.view, handle.subkey, name))
        assert name in {value for value, field in inv.VALUE_FIELDS}
        row = next(values for key, values in self.data[(handle.hive, handle.view)] if key == handle.subkey)
        if name not in row:
            raise FileNotFoundError("synthetic missing value")
        value = row[name]
        if isinstance(value, Exception):
            raise value
        return value


def inventory(locations=(), *, incomplete=False):
    result = {
        "schema_version": 1, "kind": "disk-steward-application-inventory",
        "created_at": "2026-11-05T00:00:00+00:00", "coverage": "uninstall_registration_only",
        "incomplete": incomplete, "max_entries": 1000, "entries_examined": len(locations),
        "scopes": [{"hive": hive, "view": view, "status": "complete", "entries_examined": 0, "errors": []}
                   for hive, view in inv.SCOPES],
        "entries": [{"hive": "HKCU", "view": "64", "subkey": f"fixture-{index}",
                     "display_name": f"Example {index}", "display_version": None,
                     "publisher": None, "install_location": location} for index, location in enumerate(locations)],
    }
    result["scopes"][-1]["entries_examined"] = len(locations)
    if incomplete:
        result["scopes"][0].update(status="partial", errors=["Synthetic access failure"])
    return result


class CollectionTests(unittest.TestCase):
    def test_only_four_fixed_scopes_four_values_and_read_view_flags(self):
        fake = FakeRegistry({scope: [("Example", {"DisplayName": ("Example", 1),
                                                "InstallLocation": (r"C:\Apps\Example", 1),
                                                "UninstallString": ("NEVER EXECUTE THIS", 1)})] for scope in inv.SCOPES})
        result = inv.collect(registry=fake)
        self.assertFalse(result["incomplete"])
        self.assertEqual(result["entries_examined"], 4)
        self.assertEqual(len(result["entries"]), 4)
        self.assertEqual(len(fake.closed), 8)
        roots = [call for call in fake.calls if call[0] == "open" and not isinstance(call[1], Handle)]
        self.assertEqual(len(roots), 4)
        self.assertEqual({call[2] for call in roots}, {inv.REGISTRY_PATH})
        queries = [call[-1] for call in fake.calls if call[0] == "query"]
        self.assertEqual(queries, [field for field, _ in inv.VALUE_FIELDS] * 4)
        self.assertNotIn("UninstallString", queries)
        self.assertIs(inv.validate_inventory(result), result)

    def test_missing_values_are_null_and_expandable_text_is_unchanged(self):
        fake = FakeRegistry({("HKLM", "32"): [("Example", {"InstallLocation": (r"%LOCALAPPDATA%\Example", 2)})]})
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\must-not-expand"}):
            result = inv.collect(registry=fake)
        entry = result["entries"][0]
        self.assertIsNone(entry["display_name"])
        self.assertIsNone(entry["display_version"])
        self.assertIsNone(entry["publisher"])
        self.assertEqual(entry["install_location"], r"%LOCALAPPDATA%\Example")
        self.assertFalse(result["incomplete"])
        self.assertEqual(inv.assess_path(result, r"C:\must-not-expand\Example\data.bin")["match_count"], 0)

    def test_missing_scope_access_failure_and_not_present_are_distinct(self):
        fake = FakeRegistry({("HKLM", "32"): FileNotFoundError(), ("HKLM", "64"): PermissionError(),
                             ("HKCU", "32"): winerror(2)})
        result = inv.collect(registry=fake)
        self.assertEqual([scope["status"] for scope in result["scopes"]], ["missing", "partial", "missing", "complete"])
        self.assertTrue(result["incomplete"])
        self.assertTrue(result["scopes"][1]["errors"])
        self.assertEqual(result["entries_examined"], 0)

    def test_child_and_enum_failures_count_only_enumerated_entries(self):
        fake = FakeRegistry({("HKLM", "32"): [("Denied", {}), ("Good", {})]})
        fake.child_failures[("HKLM", "32", "Denied")] = PermissionError()
        fake.enum_failures[("HKLM", "32", 2)] = PermissionError()
        result = inv.collect(registry=fake)
        self.assertEqual(result["entries_examined"], 2)
        self.assertEqual([row["subkey"] for row in result["entries"]], ["Good"])
        self.assertEqual(result["scopes"][0]["status"], "partial")
        self.assertEqual(len(result["scopes"][0]["errors"]), 2)

    def test_bad_value_type_size_and_access_failure_make_scope_partial(self):
        fake = FakeRegistry({("HKLM", "32"): [("Bad", {
            "DisplayName": (7, 4), "DisplayVersion": ("x" * 4097, 1),
            "Publisher": PermissionError(), "InstallLocation": (r"C:\Apps\Example", 3)})]})
        result = inv.collect(registry=fake)
        self.assertTrue(result["incomplete"])
        self.assertEqual(len(result["scopes"][0]["errors"]), 4)
        self.assertTrue(all(result["entries"][0][field] is None for _, field in inv.VALUE_FIELDS))

    def test_budget_is_global_counts_denied_keys_and_does_not_probe_next(self):
        fake = FakeRegistry({("HKLM", "32"): [("Denied", {}), ("Good", {}), ("DoNotExamine", {})]})
        fake.child_failures[("HKLM", "32", "Denied")] = PermissionError()
        result = inv.collect(2, fake)
        self.assertEqual(result["entries_examined"], 2)
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual([scope["status"] for scope in result["scopes"]], ["partial", "not_examined", "not_examined", "not_examined"])
        self.assertEqual([call[-1] for call in fake.calls if call[0] == "enum"], [0, 1])
        self.assertEqual(len([call for call in fake.calls if call[0] == "open" and not isinstance(call[1], Handle)]), 1)

    def test_exact_budget_is_conservatively_incomplete_without_eof_probe(self):
        result = inv.collect(1, FakeRegistry({("HKLM", "32"): [("Only", {})]}))
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["scopes"][0]["status"], "partial")

    def test_duplicate_and_unsafe_child_keys_not_opened(self):
        fake = FakeRegistry({("HKLM", "32"): [("Example", {}), ("EXAMPLE", {}),
                                               (r"nested\outside", {}), ("bidi\u202e", {})]})
        result = inv.collect(registry=fake)
        self.assertEqual(result["entries_examined"], 4)
        self.assertEqual(len(result["entries"]), 1)
        opened = [call[2] for call in fake.calls if call[0] == "open" and isinstance(call[1], Handle)]
        self.assertEqual(opened, ["Example"])
        self.assertTrue(result["incomplete"])

    def test_distinct_unicode_registry_keys_are_not_casefold_duplicates(self):
        fake = FakeRegistry({("HKLM", "32"): [("Straße", {}), ("STRASSE", {})]})
        result = inv.collect(registry=fake)
        self.assertFalse(result["incomplete"])
        self.assertEqual([entry["subkey"] for entry in result["entries"]], ["Straße", "STRASSE"])

    def test_errors_are_bounded_even_when_every_value_fails(self):
        fake = FakeRegistry({("HKLM", "32"): [(str(index), {name: PermissionError("not exported") for name, _ in inv.VALUE_FIELDS})
                                               for index in range(50)]})
        result = inv.collect(registry=fake)
        self.assertEqual(len(result["scopes"][0]["errors"]), inv.MAX_ERRORS)
        self.assertTrue(all(len(error) <= inv.MAX_ERROR_TEXT for error in result["scopes"][0]["errors"]))
        self.assertNotIn("not exported", json.dumps(result))

    def test_actual_utf8_export_remains_bounded_when_fields_are_huge(self):
        fake = FakeRegistry({("HKLM", "32"): [(str(index), {name: ("界" * inv.MAX_TEXT, 1) for name, _ in inv.VALUE_FIELDS})
                                               for index in range(1000)]})
        result = inv.collect(registry=fake)
        self.assertTrue(result["incomplete"])
        self.assertLess(result["entries_examined"], 1000)
        self.assertLessEqual(len(inv._encoded(result)), inv.MAX_JSON_BYTES)
        self.assertTrue(any("JSON byte budget" in error for error in result["scopes"][0]["errors"]))

    def test_invalid_limits_fail_before_any_registry_call(self):
        for limit in (0, -1, 1001, True, 1.0, "2"):
            fake = FakeRegistry()
            with self.subTest(limit=limit), self.assertRaises(inv.InventoryError):
                inv.collect(limit, fake)
            self.assertEqual(fake.calls, [])


class SchemaTests(unittest.TestCase):
    def test_empty_inventory_and_partial_inventory_are_valid(self):
        for data in (inventory(), inventory([r"C:\Apps\Example"], incomplete=True)):
            self.assertIs(inv.validate_inventory(data), data)

    def test_unknown_fields_and_scalar_types_are_rejected(self):
        changes = [("extra", 1), ("schema_version", True), ("kind", "other"),
                   ("coverage", "all_applications"), ("incomplete", 0), ("max_entries", 1001),
                   ("entries_examined", True), ("created_at", "2026-11-05"), ("created_at", "2026-11-05T00:00:00")]
        for field, value in changes:
            data = inventory()
            data[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(inv.InventoryError):
                inv.validate_inventory(data)

    def test_scope_uniqueness_order_counts_and_incomplete_must_agree(self):
        cases = []
        data = inventory(); data["scopes"][1] = deepcopy(data["scopes"][0]); cases.append(data)
        data = inventory(); data["scopes"].reverse(); cases.append(data)
        data = inventory(); data["scopes"].pop(); cases.append(data)
        data = inventory(); data["scopes"][0]["entries_examined"] = 1; cases.append(data)
        data = inventory(); data["incomplete"] = True; cases.append(data)
        data = inventory(); data["scopes"][0].update(status="partial", errors=["denied"]); cases.append(data)
        data = inventory(incomplete=True); data["scopes"][0]["errors"] = []; cases.append(data)
        data = inventory(); data["scopes"][0]["errors"] = ["unexpected"]; cases.append(data)
        data = inventory([r"C:\Apps\Example"]); data["scopes"][-1]["status"] = "missing"; cases.append(data)
        data = inventory([r"C:\Apps\Example"]); data["entries"] = []; cases.append(data)
        for index, data in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(inv.InventoryError):
                inv.validate_inventory(data)

    def test_entries_require_valid_scope_unique_child_and_bounded_nullable_strings(self):
        for field, value in (("hive", "HKCR"), ("view", "native"), ("subkey", ""),
                             ("subkey", "a\\b"), ("subkey", "a\nb"), ("display_name", []),
                             ("publisher", "\ud800"), ("display_version", "a" * 4097)):
            data = inventory([r"C:\Apps\Example"])
            data["entries"][0][field] = value
            with self.subTest(field=field, value=repr(value)[:40]), self.assertRaises(inv.InventoryError):
                inv.validate_inventory(data)
        data = inventory([r"C:\Apps\A", r"C:\Apps\B"])
        data["entries"][1]["subkey"] = data["entries"][0]["subkey"].upper()
        with self.assertRaises(inv.InventoryError):
            inv.validate_inventory(data)
        data = inventory([r"C:\Apps\A"])
        data["entries"][0]["extra"] = "ignored?"
        with self.assertRaises(inv.InventoryError):
            inv.validate_inventory(data)

    def test_oversized_json_rejected_even_with_individually_valid_text(self):
        data = inventory([r"C:\Apps\Example"] * 1000)
        for entry in data["entries"]:
            entry["display_name"] = "界" * inv.MAX_TEXT
        with self.assertRaisesRegex(inv.InventoryError, "2 MiB"):
            inv.validate_inventory(data)


class AssessmentTests(unittest.TestCase):
    def test_case_slashes_and_component_boundaries(self):
        assess = inv.make_assessor(inventory([r"C:\Apps\Editor"]))
        self.assertEqual(assess("c:/APPS/editor/data/file.bin")["match_count"], 1)
        for path in (r"C:\Apps\Editor2\data.bin", r"C:\Apps\Edit\data.bin", r"D:\Apps\Editor\data.bin"):
            with self.subTest(path=path):
                self.assertEqual(assess(path)["status"], "no_registration_path_match")

    def test_unicode_casefold_expansion_does_not_create_false_path_overlap(self):
        assess = inv.make_assessor(inventory([r"C:\Apps\Straße"]))
        self.assertEqual(assess(r"c:\apps\straße\data.bin")["match_count"], 1)
        self.assertEqual(assess(r"C:\Apps\STRASSE\data.bin")["status"], "no_registration_path_match")

    def test_parent_contains_relation_only_for_directories(self):
        data = inventory([r"C:\Apps\Editor"])
        self.assertEqual(inv.assess_path(data, r"C:\Apps")["match_count"], 0)
        result = inv.assess_path(data, r"C:\Apps", directory=True)
        self.assertEqual(result["matches"][0]["relation"], "contains_registered_location")
        for directory in (False, True):
            result = inv.assess_path(data, r"C:\Apps\Editor\Data", directory=directory)
            self.assertEqual(result["matches"][0]["relation"], "inside_registered_location")

    def test_multiple_matches_retained_without_ownership_inference(self):
        data = inventory([r"C:\Apps\Shared", r"C:\Apps\Shared", r"C:\Apps\Shared\Plugin"])
        result = inv.assess_path(data, r"C:\Apps\Shared\Plugin\data.bin")
        self.assertEqual(result["match_count"], 3)
        self.assertEqual(len(result["matches"]), 3)
        self.assertEqual({row["subkey"] for row in result["matches"]}, {"fixture-0", "fixture-1", "fixture-2"})
        self.assertNotIn("owner", result)

    def test_no_name_or_cache_heuristics_and_missing_does_not_mean_uninstalled(self):
        data = inventory([None], incomplete=True)
        data["entries"][0]["display_name"] = "Cache"
        result = inv.assess_path(data, r"C:\Users\Example\Cache\data.bin")
        self.assertEqual(result, {"status": "no_registration_path_match", "matches": [], "match_count": 0, "incomplete": True})

    def test_unsupported_paths_are_not_normalized_into_matches(self):
        assess = inv.make_assessor(inventory([r"C:\Apps\Example"]))
        paths = [r"\\server\share\Apps\Example", r"\\?\C:\Apps\Example", r"C:Apps\Example", "Apps/Example",
                 r"C:\Apps\other\..\Example", r"C:\Apps\.\Example", r"C:\Apps\Example\file:stream",
                 r"C:\Apps\Example.", "C:\\Apps\\Example ", r"%SYSTEMDRIVE%\Apps\Example",
                 "C:\\Apps\\Example\n", "C:\\Apps\\Exa\u202emple", r"C:\Apps\NUL", "C:\\Apps\\\ud800"]
        for path in paths:
            with self.subTest(path=repr(path)):
                self.assertEqual(assess(path)["status"], "unsupported_candidate_path")

    def test_invalid_or_drive_root_registered_locations_are_ignored(self):
        data = inventory(["C:\\", r"C:\Apps\other\..\Example", r"%LOCALAPPDATA%\Example", r"\\server\share", None, ""])
        self.assertEqual(inv.assess_path(data, r"C:\Apps\Example\data.bin")["match_count"], 0)
        self.assertEqual(inv.assess_path(data, "C:\\", directory=True)["match_count"], 0)

    def test_metadata_is_inert_and_assessment_does_not_touch_files_or_registry(self):
        data = inventory([r"C:\Apps\Example"])
        malicious = "[Execute cleanup](file:///C:/data)\n<script>bad()</script>\u202e"
        data["entries"][0]["display_name"] = malicious
        data["entries"][0]["subkey"] = "<key>[command](example)"
        with patch("builtins.open", side_effect=AssertionError("No file IO")), \
             patch.object(Path, "stat", side_effect=AssertionError("No stat")), \
             patch.object(inv, "collect", side_effect=AssertionError("No registry access")):
            result = inv.assess_path(data, r"C:\Apps\Example\data.bin")
        self.assertEqual(result["matches"][0]["display_name"], malicious)
        self.assertEqual(data["entries"][0]["display_name"], malicious)

    def test_prepared_assessor_validates_once_and_freezes_entry_metadata(self):
        data = inventory([r"C:\Apps\Example"])
        with patch.object(inv, "validate_inventory", wraps=inv.validate_inventory) as validate:
            assess = inv.make_assessor(data)
            data["entries"][0]["display_name"] = "mutated"
            data["incomplete"] = True
            for _ in range(20):
                result = assess(r"C:\Apps\Example\data.bin")
            self.assertEqual(validate.call_count, 1)
        self.assertEqual(result["matches"][0]["display_name"], "Example 0")
        self.assertFalse(result["incomplete"])
        with self.assertRaises(inv.InventoryError):
            assess(r"C:\Apps", directory=1)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".inventory-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def test_exclusive_utf8_json_output_and_existing_bytes_survive(self):
        output = self.base / "inventory.json"
        data = inventory([r"C:\Apps\Example"])
        data["entries"][0]["display_name"] = "示例"
        inv.write_inventory(output, data)
        original = output.read_bytes()
        self.assertEqual(original, inv._encoded(data))
        self.assertEqual(json.loads(original), data)
        with self.assertRaises(FileExistsError):
            inv.write_inventory(output, inventory())
        self.assertEqual(output.read_bytes(), original)

    def test_bad_output_names_and_parent_components_rejected(self):
        for value in ("report.json:stream", "NUL.json", "report. ", "report\n.json", "bad.\\report.json", "..\\report.json"):
            with self.subTest(value=value), self.assertRaises((inv.InventoryError, ValueError)):
                inv.write_inventory(str(self.base) + "\\" + value, inventory())
        for value in (r"\\server\share\report.json", r"\\?\C:\report.json", "C:report.json"):
            with self.subTest(value=value), self.assertRaises(inv.InventoryError):
                inv.write_inventory(value, inventory())

    def test_dot_relative_output_is_supported(self):
        previous = Path.cwd()
        try:
            os.chdir(self.base)
            inv.write_inventory(os.path.join(".", "relative.json"), inventory())
        finally:
            os.chdir(previous)
        self.assertEqual(json.loads((self.base / "relative.json").read_bytes()), inventory())

    def test_symlink_parent_rejected_if_host_supports_symlinks(self):
        actual = self.base / "actual"
        actual.mkdir()
        alias = self.base / "alias"
        try:
            alias.symlink_to(actual, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Host does not permit fixture symlinks: {error}")
        with self.assertRaises(ValueError):
            inv.write_inventory(alias / "report.json", inventory())
        self.assertEqual(list(actual.iterdir()), [])

    def test_cli_writes_injected_fake_result_and_never_collects_for_existing_output(self):
        output = self.base / "inventory.json"
        data = inventory()
        with patch.object(inv, "collect", return_value=data) as collect, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(inv.main(["collect", "--output", str(output), "--max-entries", "10"]), 0)
            collect.assert_called_once_with(10)
        with patch.object(inv, "collect", side_effect=AssertionError("Must fail before collection")), \
             patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(inv.main(["collect", "--output", str(output)]), 2)
        self.assertEqual(json.loads(output.read_bytes()), data)


if __name__ == "__main__":
    unittest.main()
