import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "skills/disk-steward/scripts/verified_copy.py"
SPEC = importlib.util.spec_from_file_location("verified_copy", SCRIPT)
vc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vc)


class CopyTests(unittest.TestCase):
    def setUp(self):
        # Avoid system-managed temp roots: only isolated fixtures in this repo.
        self.temp = tempfile.TemporaryDirectory(prefix=".copy-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).absolute()
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "nested").mkdir()
        (self.source / "empty").mkdir()
        (self.source / "nested" / "hello.txt").write_bytes(b"hello\x00world")
        (self.source / "file [literal].txt").write_bytes(b"ordinary bytes")
        self.destination = self.base / "copied"
        self.plan_path = self.base / "plan.json"
        self.receipt_path = self.base / "receipt.json"

    def plan(self):
        return vc.make_plan(self.source, self.destination, self.plan_path)

    def save(self, plan):
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def resign(self, plan):
        plan["plan_id"] = vc.canonical_id({k: v for k, v in plan.items() if k != "plan_id"})
        self.save(plan)

    def test_copy_bytes_empty_directories_receipt_and_preserve_source(self):
        plan = self.plan()
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "verified", receipt)
        self.assertEqual(receipt["verified_files"], 2)
        self.assertEqual(receipt["reclaimed_bytes"], 0)
        self.assertTrue((self.destination / "empty").is_dir())
        for entry in plan["files"]:
            self.assertEqual((self.source / entry["path"]).read_bytes(), (self.destination / entry["path"]).read_bytes())
            self.assertEqual((self.destination / entry["path"]).stat().st_mtime_ns, entry["mtime_ns"])
        self.assertEqual(json.loads(self.receipt_path.read_text())["status"], "verified")

    def test_selected_copy_contains_only_exact_files_and_required_parents(self):
        plan = vc.make_plan(self.source, self.destination, self.plan_path,
                            include=["nested/hello.txt"])
        self.assertEqual(plan["schema_version"], 2)
        self.assertEqual(plan["scope"], "files")
        self.assertEqual(plan["selected_paths"], ["nested/hello.txt"])
        self.assertEqual(plan["directories"], ["nested"])
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "verified", receipt)
        self.assertEqual((self.destination / "nested/hello.txt").read_bytes(), b"hello\x00world")
        self.assertFalse((self.destination / "empty").exists())
        self.assertFalse((self.destination / "file [literal].txt").exists())
        self.assertTrue((self.source / "file [literal].txt").exists())
        self.assertTrue((self.source / "nested/hello.txt").exists())

    def test_selected_copy_does_not_scan_or_hash_unselected_files(self):
        (self.source / "OneDrive - Excluded").mkdir()
        (self.source / "OneDrive - Excluded/private.txt").write_bytes(b"unselected")
        original = vc.fingerprint

        def selected_only(path):
            self.assertEqual(path.name, "hello.txt")
            return original(path)

        with patch.object(vc, "fingerprint", side_effect=selected_only), patch.object(vc.os, "scandir", side_effect=AssertionError("Selection must not enumerate siblings")):
            plan = vc.make_plan(self.source, self.destination, self.plan_path,
                                include=["nested/hello.txt"])
            vc.check_snapshot(self.source, plan)

    def test_unselected_changes_do_not_invalidate_selected_plan(self):
        plan = vc.make_plan(self.source, self.destination, self.plan_path,
                            include=["nested/hello.txt"])
        unselected = self.source / "file [literal].txt"
        unselected.write_bytes(b"changed but not selected")
        (self.source / "new-file.txt").write_bytes(b"new but not selected")
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "verified", receipt)
        self.assertEqual(unselected.read_bytes(), b"changed but not selected")

    def test_changed_selected_file_invalidates_plan(self):
        plan = vc.make_plan(self.source, self.destination, self.plan_path,
                            include=["nested/hello.txt"])
        (self.source / "nested/hello.txt").write_bytes(b"changed")
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(self.destination.exists())

    def test_selection_rejects_directories_globs_duplicates_and_traversal(self):
        for selection in (["nested"], ["*.txt"], ["../outside"], [],
                          ["nested/hello.txt", "nested/hello.txt"],
                          ["nested/hello.txt", "NESTED/other.txt"],
                          ["nested", "nested/hello.txt"]):
            with self.subTest(selection=selection), self.assertRaises((vc.CopyError, OSError)):
                vc.make_plan(self.source, self.destination, self.plan_path, include=selection)
            self.assertFalse(self.plan_path.exists())

    def test_selection_treats_brackets_literally_and_sorts_names(self):
        plan = vc.make_plan(self.source, self.destination, self.plan_path,
                            include=["nested/hello.txt", "file [literal].txt"])
        self.assertEqual(plan["selected_paths"], ["file [literal].txt", "nested/hello.txt"])
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "verified", receipt)

    def test_selection_budget_includes_parent_directories_and_root_files(self):
        with patch.object(vc, "MAX_ENTRIES", 2), self.assertRaises(vc.CopyError):
            vc.make_plan(self.source, self.destination, self.plan_path,
                         include=["nested/hello.txt", "file [literal].txt"])
        self.assertFalse(self.plan_path.exists())

    def test_cli_repeated_include_roundtrip(self):
        result = vc.main(["plan", "--source", str(self.source), "--destination", str(self.destination),
                          "--output", str(self.plan_path), "--include", "nested/hello.txt",
                          "--include", "file [literal].txt"])
        self.assertEqual(result, 0)
        plan = vc.load_plan(self.plan_path)
        self.assertEqual(plan["scope"], "files")
        self.assertEqual(vc.main(["apply", "--plan", str(self.plan_path), "--approve", plan["plan_id"],
                                  "--receipt", str(self.receipt_path)]), 0)
        self.assertFalse((self.destination / "empty").exists())

    def test_forged_selected_plan_cannot_expand_or_omit_selection(self):
        plan = vc.make_plan(self.source, self.destination, self.plan_path,
                            include=["nested/hello.txt"])
        plan["selected_paths"].append("file [literal].txt")
        plan["selected_paths"].sort()
        self.resign(plan)
        with self.assertRaises(vc.CopyError):
            vc.validate_plan(plan, plan["plan_id"])

    def test_selection_rejects_managed_ancestors(self):
        target = self.source / "AppData/state.txt"
        target.parent.mkdir()
        target.write_bytes(b"application data")
        with self.assertRaises(vc.CopyError):
            vc.make_plan(self.source, self.destination, self.plan_path,
                         include=["AppData/state.txt"])

    def test_selected_plan_cannot_add_unused_directories(self):
        plan = vc.make_plan(self.source, self.destination, self.plan_path,
                            include=["nested/hello.txt"])
        plan["directories"].append("unselected")
        self.resign(plan)
        with self.assertRaises(vc.CopyError):
            vc.validate_plan(plan, plan["plan_id"])

    def test_validate_existing_destination_mode_requires_existing_plain_directory(self):
        plan = self.plan()
        with self.assertRaises(OSError):
            vc.validate_plan(plan, plan["plan_id"], require_new_destination=False)
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "verified", receipt)
        self.assertEqual(vc.validate_plan(plan, plan["plan_id"], require_new_destination=False),
                         (self.source, self.destination))
        with self.assertRaises(vc.CopyError):
            vc.validate_plan(plan, plan["plan_id"])

    def test_existing_destination_validation_still_rejects_overlap(self):
        plan = self.plan()
        plan["destination"] = str(self.source / "nested")
        self.resign(plan)
        with self.assertRaises(vc.CopyError):
            vc.validate_plan(plan, plan["plan_id"], require_new_destination=False)

    def test_legacy_v1_plan_remains_supported_as_whole_tree(self):
        plan = self.plan()
        plan["schema_version"] = 1
        plan.pop("scope")
        plan.pop("selected_paths")
        self.resign(plan)
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "verified", receipt)
        self.assertTrue((self.destination / "empty").is_dir())

    def test_changed_source_does_not_create_destination(self):
        plan = self.plan()
        (self.source / "nested" / "hello.txt").write_bytes(b"modified")
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(self.destination.exists())
        self.assertTrue(self.source.exists())

    def test_changed_bytes_with_restored_mtime_are_detected(self):
        plan = self.plan()
        path = self.source / "nested" / "hello.txt"
        before = path.stat()
        path.write_bytes(b"X" * before.st_size)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(self.destination.exists())

    def test_tampered_plan_rejected(self):
        plan = self.plan()
        plan["destination"] = str(self.base / "wrong")
        self.save(plan)
        with self.assertRaises(vc.CopyError):
            vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertFalse(self.destination.exists())

    def test_forged_traversal_rejected_even_with_recomputed_id(self):
        plan = self.plan()
        plan["files"][0]["path"] = "../outside.txt"
        self.resign(plan)
        with self.assertRaises(vc.CopyError):
            vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertFalse((self.base / "outside.txt").exists())

    def test_wrong_approval_rejected(self):
        self.plan()
        with self.assertRaises(vc.CopyError):
            vc.apply_plan(self.plan_path, "yes", self.receipt_path)

    def test_existing_destination_never_overwritten(self):
        plan = self.plan()
        self.destination.mkdir()
        (self.destination / "sentinel").write_bytes(b"keep")
        with self.assertRaises(vc.CopyError):
            vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual((self.destination / "sentinel").read_bytes(), b"keep")

    def test_plan_and_receipt_cannot_be_inside_source(self):
        with self.assertRaises(vc.CopyError):
            vc.make_plan(self.source, self.destination, self.source / "plan.json")
        plan = self.plan()
        with self.assertRaises(vc.CopyError):
            vc.apply_plan(self.plan_path, plan["plan_id"], self.source / "receipt.json")

    def test_existing_receipt_never_overwritten(self):
        plan = self.plan()
        self.receipt_path.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(self.receipt_path.read_text(), "keep")
        self.assertFalse(self.destination.exists())

    def test_plan_output_not_overwritten(self):
        self.plan_path.write_text("keep", encoding="utf-8")
        with self.assertRaises(vc.CopyError):
            self.plan()
        self.assertEqual(self.plan_path.read_text(), "keep")

    def test_plan_output_alternate_stream_rejected(self):
        victim = self.base / "existing.txt"
        victim.write_bytes(b"keep")
        output = str(victim) + ":plan.json"
        with self.assertRaises(vc.CopyError):
            vc.make_plan(self.source, self.destination, output)
        self.assertEqual(victim.read_bytes(), b"keep")
        self.assertFalse(os.path.lexists(output))

    def test_receipt_output_alternate_stream_rejected(self):
        plan = self.plan()
        victim = self.base / "existing.txt"
        victim.write_bytes(b"keep")
        output = str(victim) + ":receipt.json"
        with self.assertRaises(vc.CopyError):
            vc.apply_plan(self.plan_path, plan["plan_id"], output)
        self.assertEqual(victim.read_bytes(), b"keep")
        self.assertFalse(self.destination.exists())
        self.assertFalse(os.path.lexists(output))

    def test_plan_output_trailing_dot_or_space_rejected_before_normalization(self):
        for suffix in (".", " "):
            with self.subTest(suffix=suffix), self.assertRaises(vc.CopyError):
                vc.make_plan(self.source, self.destination, str(self.plan_path) + suffix)
            self.assertFalse(self.plan_path.exists())
            self.assertFalse(self.destination.exists())

    def test_receipt_output_trailing_dot_or_space_rejected_before_normalization(self):
        plan = self.plan()
        for suffix in (".", " "):
            with self.subTest(suffix=suffix), self.assertRaises(vc.CopyError):
                vc.apply_plan(self.plan_path, plan["plan_id"], str(self.receipt_path) + suffix)
            self.assertFalse(self.receipt_path.exists())
            self.assertFalse(self.destination.exists())

    def test_destination_trailing_dot_or_space_rejected_before_normalization(self):
        for suffix in (".", " "):
            with self.subTest(suffix=suffix), self.assertRaises(vc.CopyError):
                vc.make_plan(self.source, str(self.destination) + suffix, self.plan_path)
            self.assertFalse(self.plan_path.exists())
            self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == "nt", "Windows path normalization")
    def test_raw_source_and_ancestor_aliases_are_rejected(self):
        for suffix in (".", " "):
            with self.subTest(suffix=suffix), self.assertRaises(vc.CopyError):
                vc.make_plan(str(self.source) + suffix, self.destination, self.plan_path)
            with self.subTest(ancestor_suffix=suffix), self.assertRaises(vc.CopyError):
                vc.make_plan(self.source, self.destination,
                             str(self.base) + suffix + "\\aliased-output.json")
            self.assertFalse(self.plan_path.exists())
            self.assertFalse((self.base / "aliased-output.json").exists())

    @unittest.skipUnless(os.name == "nt", "Windows drive-relative path semantics")
    def test_drive_relative_paths_including_bare_drive_rejected(self):
        for path in ("C:", "C:relative", "D:"):
            with self.subTest(path=path), self.assertRaises(vc.CopyError):
                vc.absolute(path)

    def test_destination_inside_source_rejected(self):
        with self.assertRaises(vc.CopyError):
            vc.make_plan(self.source, self.source / "nested-new", self.plan_path)

    def test_hardlink_rejected(self):
        try:
            os.link(self.source / "nested" / "hello.txt", self.source / "hardlink.txt")
        except OSError:
            self.skipTest("Hardlinks unavailable")
        with self.assertRaises(vc.CopyError):
            self.plan()

    def test_symlink_rejected(self):
        try:
            os.symlink(self.source / "nested", self.source / "linked", target_is_directory=True)
        except OSError:
            self.skipTest("Symlinks require platform permission")
        with self.assertRaises(vc.CopyError):
            self.plan()

    def test_symlink_ancestor_rejected(self):
        link = self.base / "linked-parent"
        try:
            os.symlink(self.source, link, target_is_directory=True)
        except OSError:
            self.skipTest("Symlinks require platform permission")
        with self.assertRaises(vc.CopyError):
            vc.make_plan(link / "nested", self.destination, self.plan_path)

    def test_cloud_directory_rejected(self):
        (self.source / "OneDrive - Example").mkdir()
        with self.assertRaises(vc.CopyError):
            self.plan()

    def test_entry_budget_exhaustion_rejected(self):
        with patch.object(vc, "MAX_ENTRIES", 1):
            with self.assertRaises(vc.CopyError):
                self.plan()

    def test_hardlink_metadata_rejected_even_without_link_permission(self):
        real_path = self.source / "nested" / "hello.txt"
        original = Path.lstat

        def link_stat(path):
            info = original(path)
            if path == real_path:
                return SimpleNamespace(st_mode=info.st_mode, st_nlink=2,
                                       st_file_attributes=getattr(info, "st_file_attributes", 0))
            return info

        with patch.object(Path, "lstat", link_stat), self.assertRaises(vc.CopyError):
            vc.checked_file(real_path)

    def test_reparse_or_placeholder_metadata_is_rejected(self):
        for attribute in (0x400, 0x1000, 0x4000, 0x40000, 0x400000):
            info = type("Info", (), {"st_mode": 0o100644, "st_file_attributes": attribute})()
            with self.subTest(attribute=attribute), self.assertRaises(vc.CopyError):
                vc.check_attributes(self.source, info)

    def test_insufficient_space_leaves_source_untouched(self):
        plan = self.plan()
        with patch.object(vc.shutil, "disk_usage", return_value=type("Usage", (), {"free": 0})()):
            receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(self.destination.exists())

    def test_partial_failure_keeps_receipt_and_source(self):
        plan = self.plan()
        with patch.object(vc, "copy_file", side_effect=OSError("simulated full disk")):
            receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "partial")
        self.assertTrue(self.destination.is_dir())
        self.assertTrue((self.source / "nested" / "hello.txt").exists())
        self.assertIn("simulated full disk", json.loads(self.receipt_path.read_text())["error"])

    def test_destination_corruption_fails_final_verification(self):
        plan = self.plan()
        original = vc.copy_file

        def corrupt_after_copy(source, destination, item):
            original(source, destination, item)
            destination.write_bytes(b"corrupted")

        with patch.object(vc, "copy_file", side_effect=corrupt_after_copy):
            receipt = vc.apply_plan(self.plan_path, plan["plan_id"], self.receipt_path)
        self.assertEqual(receipt["status"], "partial")
        self.assertIn("Destination changed", receipt["error"])
        self.assertTrue((self.source / "nested" / "hello.txt").exists())

    def test_windows_aliases_rejected(self):
        for name in ("file:stream", "CON.txt", "trail.", "trail ", "a\\b", "/absolute", "a//b", "a/../b", "a/./b"):
            with self.subTest(name=name), self.assertRaises(vc.CopyError):
                vc.relative_name(name)

    def test_duplicate_json_keys_rejected(self):
        self.plan_path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(vc.CopyError):
            vc.load_plan(self.plan_path)

    @unittest.skipUnless(os.name == "nt", "Windows alternate stream test")
    def test_alternate_data_stream_rejected(self):
        target = self.source / "nested" / "hello.txt"
        try:
            with open(str(target) + ":extra", "wb") as stream:
                stream.write(b"must not lose this")
        except OSError:
            self.skipTest("Filesystem does not support alternate streams")
        with self.assertRaises(vc.CopyError):
            self.plan()


if __name__ == "__main__":
    unittest.main()
