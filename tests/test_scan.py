"""Metadata and planning invariants; operates only in temporary fixtures."""

import importlib.util
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "disk-steward" / "scripts" / "disk_scan.py"
SPEC = importlib.util.spec_from_file_location("disk_scan", SCRIPT)
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)


class ScanTests(unittest.TestCase):
    def setUp(self):
        # A system TEMP ancestor may itself be AppData/Temp, changing category
        # heuristics; keep isolated fixtures here and remove them after each test.
        self.temporary = tempfile.TemporaryDirectory(prefix=".scan-test-", dir=Path(__file__).parent)
        self.base = Path(self.temporary.name)
        self.root = self.base / "inventory"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def file(self, relative, data):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_sizes_categories_and_bounded_top_without_content_reads(self):
        self.file("Downloads/setup.iso", b"x" * 101)
        self.file("AppData/Local/Cache/blob", b"x" * 203)
        self.file("notes.txt", b"x" * 7)
        # Any Python file-content open from scanning would fail this test.
        with patch("builtins.open", side_effect=AssertionError("Scanner opened content")), patch.object(Path, "open", side_effect=AssertionError("Scanner opened content")):
            result = scan.scan_roots([self.root], top=2)
        self.assertEqual(result["logical_bytes"], 311)
        self.assertEqual(result["total_files"], 3)
        self.assertFalse(result["incomplete"])
        self.assertEqual([item["logical_bytes"] for item in result["largest_files"]], [203, 101])
        self.assertEqual(result["categories"]["possible_temp_or_cache"]["files"], 1)

    def test_nested_roots_do_not_double_count(self):
        file = self.file("child/test.txt", b"abc")
        result = scan.scan_roots([self.root, file.parent])
        self.assertEqual(result["logical_bytes"], 3)
        self.assertEqual(result["skip_counts"]["overlapping_root"], 1)
        self.assertFalse(result["incomplete"])
        self.assertEqual(result["root_results"][1]["logical_bytes"], 3)
        self.assertEqual(result["root_results"][1]["coverage"], "overlapping_root_not_scanned_separately")

    def test_nested_other_volume_requires_its_own_root_and_deduplicates_its_child_root(self):
        self.file("direct.txt", b"1234")
        nested = self.file("mounted/child/data.txt", b"12345")
        mount = nested.parent.parent
        original_lstat = Path.lstat

        def lstat(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if path == mount or mount in path.parents:
                return SimpleNamespace(st_mode=info.st_mode, st_dev=info.st_dev + 1,
                    st_ino=info.st_ino, st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
                    st_nlink=info.st_nlink, st_file_attributes=getattr(info, "st_file_attributes", 0))
            return info

        with patch.object(Path, "lstat", lstat):
            result = scan.scan_roots([self.root, mount, nested.parent])
        roots = {item["path"]: item for item in result["root_results"]}
        self.assertEqual(result["logical_bytes"], 9)
        self.assertEqual(result["total_files"], 2)
        self.assertEqual(len(result["volumes"]), 2)
        self.assertEqual(roots[str(self.root)]["logical_bytes"], 4)
        self.assertTrue(roots[str(self.root)]["incomplete"])
        self.assertEqual(roots[str(mount)]["logical_bytes"], 5)
        self.assertFalse(roots[str(mount)]["incomplete"])
        self.assertEqual(roots[str(nested.parent)]["coverage"], "overlapping_root_not_scanned_separately")
        self.assertEqual(roots[str(nested.parent)]["covered_by_root"], str(mount))
        self.assertEqual(result["skip_counts"]["different_volume"], 1)

    def test_entry_budget_counts_directories(self):
        for index in range(20):
            (self.root / str(index)).mkdir()
        result = scan.scan_roots([self.root], max_files=3)
        self.assertEqual(result["entries_examined"], 3)
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["skip_counts"]["entry_budget"], 1)

    def test_many_small_files_appear_in_directory_review_without_double_counting(self):
        self.file("large-single.bin", b"x" * 100)
        for index in range(200):
            self.file(f"Cache/{index}.bin", b"x" * 10)
        result = scan.scan_roots([self.root], top=1, top_directories=2)
        self.assertEqual(result["largest_files"][0]["logical_bytes"], 100)
        self.assertEqual(len(result["largest_directories"]), 2)
        cache = next(item for item in result["largest_directories"] if Path(item["path"]).name == "Cache")
        self.assertEqual(cache["logical_bytes"], 2000)
        self.assertEqual(cache["observed_files"], 200)
        self.assertFalse(cache["incomplete"])
        plan = scan.make_plan(result)
        review = next(item for item in plan["directory_reviews"] if item["path"] == cache["path"])
        self.assertEqual(review["action"], "review_in_owning_application")
        self.assertIsNone(review["estimated_reclaimable_bytes"])
        self.assertEqual(plan["candidate_logical_bytes"], 100)
        self.assertNotIn("directory_logical_bytes", plan)
        self.assertEqual(result["logical_bytes"], 2100)
        self.assertTrue(result["directory_accounting"]["overlapping_summaries"])

    def test_nested_directory_aggregates_are_inclusive_not_additive(self):
        self.file("parent/direct.txt", b"123")
        self.file("parent/child/nested.txt", b"12345")
        result = scan.scan_roots([self.root])
        by_path = {item["path"]: item for item in result["largest_directories"]}
        self.assertEqual(by_path[str(self.root / "parent")]["logical_bytes"], 8)
        self.assertEqual(by_path[str(self.root / "parent" / "child")]["logical_bytes"], 5)
        self.assertEqual(by_path[str(self.root)]["logical_bytes"], 8)
        self.assertEqual(by_path[str(self.root)]["observed_files"], 2)
        self.assertEqual(result["root_results"][0]["logical_bytes"], 8)
        self.assertFalse(result["root_results"][0]["incomplete"])

    def test_budget_marks_only_unfinished_roots_and_their_aggregates_incomplete(self):
        unfinished = self.base / "a-unfinished"
        completed = self.base / "z-completed"
        unfinished.mkdir()
        completed.mkdir()
        for index in range(10):
            (unfinished / f"{index}.txt").write_bytes(b"ab")
        (completed / "one.txt").write_bytes(b"finished")
        # Roots are processed from the end of the deterministic root stack.
        result = scan.scan_roots([unfinished, completed], max_files=3)
        roots = {item["path"]: item for item in result["root_results"]}
        self.assertEqual(result["entries_examined"], 3)
        self.assertFalse(roots[str(completed)]["incomplete"])
        self.assertTrue(roots[str(unfinished)]["incomplete"])
        self.assertEqual(roots[str(unfinished)]["observed_files"], 2)
        summaries = {item["path"]: item for item in result["largest_directories"]}
        self.assertTrue(summaries[str(unfinished)]["incomplete"])
        self.assertFalse(summaries[str(completed)]["incomplete"])

    def test_queued_directory_is_not_reported_as_complete_empty(self):
        self.file("nested/deep/data.txt", b"not observed")
        self.file("other.txt", b"x")
        result = scan.scan_roots([self.root], max_files=1)
        self.assertTrue(result["incomplete"])
        self.assertTrue(result["root_results"][0]["incomplete"])
        for item in result["largest_directories"]:
            self.assertTrue(item["incomplete"])

    def test_hardlinks_count_once_and_never_claim_reclaim(self):
        source = self.file("first.txt", b"1234567")
        try:
            os.link(source, self.root / "second.txt")
        except OSError as exc:
            self.skipTest(f"Hard links unavailable: {exc}")
        result = scan.scan_roots([self.root])
        self.assertEqual(result["logical_bytes"], 7)
        self.assertEqual(result["total_files"], 1)
        self.assertEqual(result["skip_counts"]["duplicate_file_id"], 1)
        plan = scan.make_plan(result)
        self.assertEqual(plan["automatic_reclaimable_bytes"], 0)
        self.assertIsNone(plan["candidates"][0]["estimated_reclaimable_bytes"])
        self.assertEqual(plan["candidates"][0]["risk"], "high")

    def test_symlink_root_and_child_are_not_followed(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "private.txt").write_bytes(b"not inventoried")
        link = self.root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        result = scan.scan_roots([self.root])
        self.assertEqual(result["total_files"], 0)
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["skip_counts"]["link_reparse_or_cloud"], 1)
        result = scan.scan_roots([link])
        self.assertEqual(result["error_counts"]["invalid_root"], 1)
        child = outside / "child"
        child.mkdir()
        result = scan.scan_roots([link / "child"])
        self.assertEqual(result["error_counts"]["invalid_root"], 1)

    def test_reparse_cloud_and_offline_flags_are_blocked(self):
        for attribute in [0x400, 0x1000, 0x40000, 0x400000]:
            with self.subTest(attribute=attribute):
                self.assertTrue(scan.blocked_metadata(SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=attribute)))
        self.assertFalse(scan.blocked_metadata(SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0)))

    def test_simulated_hardlink_metadata_deduplicates_without_link_privilege(self):
        first = self.file("first.txt", b"1234567")
        second = self.file("second.txt", b"1234567")
        original_lstat = Path.lstat
        metadata = first.lstat()
        identity = SimpleNamespace(st_ino=metadata.st_ino, st_dev=metadata.st_dev,
            st_mode=metadata.st_mode, st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns, st_nlink=2, st_file_attributes=0)

        def lstat(path, *args, **kwargs):
            return identity if path in (first, second) else original_lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", lstat):
            result = scan.scan_roots([self.root])
        self.assertEqual(result["logical_bytes"], 7)
        self.assertEqual(result["skip_counts"]["duplicate_file_id"], 1)
        plan = scan.make_plan(result)
        self.assertEqual(plan["automatic_reclaimable_bytes"], 0)
        self.assertEqual(plan["candidates"][0]["risk"], "high")

    def test_cross_directory_hardlinks_are_attributed_once_and_explicitly_flagged(self):
        first = self.file("left/first.txt", b"1234567")
        second = self.file("right/second.txt", b"1234567")
        original_lstat = Path.lstat
        metadata = first.lstat()
        identity = SimpleNamespace(st_ino=metadata.st_ino, st_dev=metadata.st_dev,
            st_mode=metadata.st_mode, st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns, st_nlink=2, st_file_attributes=0)

        def lstat(path, *args, **kwargs):
            return identity if path in (first, second) else original_lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", lstat):
            result = scan.scan_roots([self.root])
        summaries = {item["path"]: item for item in result["largest_directories"]}
        self.assertEqual(result["logical_bytes"], 7)
        self.assertEqual(summaries[str(self.root)]["logical_bytes"], 7)
        self.assertEqual(summaries[str(self.root)]["hardlinked_files"], 1)
        self.assertEqual(summaries[str(self.root)]["deduplicated_file_names"], 1)
        child_sizes = [summaries[str(self.root / name)]["logical_bytes"] for name in ("left", "right")]
        self.assertEqual(sorted(child_sizes), [0, 7])
        self.assertEqual(result["root_results"][0]["observed_files"], 1)
        self.assertEqual(result["root_results"][0]["deduplicated_file_names"], 1)
        self.assertTrue(all(item["estimated_reclaimable_bytes"] is None for item in scan.make_plan(result)["directory_reviews"]))

    def test_simulated_cloud_directory_is_not_enumerated(self):
        hidden = self.file("cloud/should-not-appear.txt", b"secret")
        original_lstat = Path.lstat
        original_scandir = os.scandir

        def lstat(path, *args, **kwargs):
            if path == hidden.parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400000)
            return original_lstat(path, *args, **kwargs)

        def scandir(path):
            self.assertNotEqual(Path(path), hidden.parent, "Entered cloud placeholder")
            return original_scandir(path)

        with patch.object(Path, "lstat", lstat), patch.object(os, "scandir", scandir):
            result = scan.scan_roots([self.root])
        self.assertEqual(result["total_files"], 0)
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["skip_counts"]["link_reparse_or_cloud"], 1)

    def test_simulated_reparse_ancestor_rejects_root(self):
        nested = self.root / "junction" / "child"
        nested.mkdir(parents=True)
        original_lstat = Path.lstat

        def lstat(path, *args, **kwargs):
            if path == nested.parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original_lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", lstat):
            result = scan.scan_roots([nested])
        self.assertEqual(result["error_counts"]["invalid_root"], 1)
        self.assertEqual(result["entries_examined"], 0)

    def test_unreadable_root_is_reported_not_silently_ignored(self):
        result = scan.scan_roots([self.root / "missing"])
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["error_counts"]["invalid_root"], 1)

    def test_system_content_is_excluded_from_candidates(self):
        self.file("Windows/WinSxS/component.dll", b"123")
        self.file("personal.pdf", b"ab")
        plan = scan.make_plan(scan.scan_roots([self.root]))
        self.assertEqual(plan["excluded_system_files"], 1)
        self.assertEqual(len(plan["candidates"]), 1)
        self.assertEqual(plan["candidate_logical_bytes"], 2)

    def test_application_ownership_takes_priority_over_archive_or_downloads(self):
        self.file("AppData/Local/Example/archive.zip", b"123")
        self.file("AppData/Local/Example/Downloads/file.iso", b"1234")
        self.file("AppData/Local/Example/Cache/data.zip", b"12")
        plan = scan.make_plan(scan.scan_roots([self.root]), goal_gib=5)
        by_name = {Path(item["path"]).name: item for item in plan["candidates"]}
        for name in ("archive.zip", "file.iso"):
            self.assertEqual(by_name[name]["category"], "application_data")
            self.assertEqual(by_name[name]["action"], "review_application_supported_relocation")
        self.assertEqual(by_name["data.zip"]["action"], "review_in_owning_application")
        self.assertEqual(plan["goal_kind"], "additional_free_space")
        self.assertEqual(plan["goal_bytes"], 5 * 1024**3)
        self.assertEqual(plan["goal_evaluation"], "unknown_until_user_choices_and_post_action_volume_measurement")

    def test_report_rejects_alternate_streams_and_windows_aliases(self):
        existing = self.base / "existing.txt"
        existing.write_bytes(b"keep")
        for name in ("existing.txt:scan.json", "CON", "NUL.json", "trailing.", "trailing ", "report?.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                scan.write_report(self.base / name, {"report": True})
        self.assertEqual(existing.read_bytes(), b"keep")
        self.assertFalse(Path(str(existing) + ":scan.json").exists())

    def test_plan_rejects_invalid_size_and_nonfinite_goal(self):
        self.file("file.txt", b"hello")
        result = scan.scan_roots([self.root])
        for goal in [0, -1, float("inf"), float("nan")]:
            with self.subTest(goal=goal), self.assertRaises(ValueError):
                scan.make_plan(result, goal)
        result["largest_files"][0]["logical_bytes"] = True
        with self.assertRaises(ValueError):
            scan.make_plan(result)

    def multi_volume_report(self):
        self.file("ordinary.txt", b"hello")
        result = scan.scan_roots([self.root])
        result["volumes"][0].update(total_bytes=100 * scan.GIB, used_bytes=98 * scan.GIB, free_bytes=2 * scan.GIB)
        result["volumes"].append({
            "volume_id": "test-other-volume", "path": "Z:\\", "queried_at": "Z:\\fixture",
            "scan_roots": ["Z:\\fixture"], "total_bytes": 100 * scan.GIB,
            "used_bytes": 97 * scan.GIB, "free_bytes": 3 * scan.GIB,
        })
        result["largest_files"].append({
            "path": "Z:\\fixture\\other.bin", "volume_id": "test-other-volume",
            "logical_bytes": 1000, "category": "user_file", "hardlink_count": 1,
        })
        result["largest_directories"].append({
            "path": "Z:\\fixture", "volume_id": "test-other-volume", "logical_bytes": 1000,
            "observed_files": 1, "hardlinked_files": 0, "deduplicated_file_names": 0,
            "category": "user_file", "incomplete": False, "is_scan_root": True,
        })
        return result

    def test_free_target_shortfall_uses_only_explicit_volume_snapshot(self):
        result = self.multi_volume_report()
        plan = scan.make_plan(result, 10, "free-target", str(self.root))
        self.assertEqual(plan["goal_kind"], "target_free_space")
        self.assertEqual(plan["baseline_free_bytes"], 2 * scan.GIB)
        self.assertEqual(plan["required_additional_bytes"], 8 * scan.GIB)
        self.assertEqual(plan["capacity_snapshot_status"], "below_free_target")
        self.assertEqual(plan["candidate_logical_bytes"], 5)
        self.assertEqual(plan["excluded_other_or_unknown_volume_files"], 1)
        self.assertTrue(all(item["volume_id"] == result["volumes"][0]["volume_id"] for item in plan["directory_reviews"]))
        self.assertEqual(plan["goal_evaluation"], "unknown_until_user_choices_and_post_action_volume_measurement")

    def test_already_free_target_is_snapshot_information_not_achieved_claim(self):
        result = self.multi_volume_report()
        plan = scan.make_plan(result, 1, "free-target", str(self.root))
        self.assertEqual(plan["required_additional_bytes"], 0)
        self.assertEqual(plan["capacity_snapshot_status"], "already_at_free_target_at_scan_time")
        self.assertEqual(plan["automatic_reclaimable_bytes"], 0)
        self.assertNotIn("goal_achieved", plan)

    def test_missing_unknown_or_ambiguous_volume_selection_rejected(self):
        result = self.multi_volume_report()
        for kind in ("additional", "free-target"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                scan.make_plan(result, 10, kind)
        with self.assertRaises(ValueError):
            scan.make_plan(result, 10, "free-target", "Q:\\not-recorded")
        ambiguous = copy.deepcopy(result)
        ambiguous["volumes"][1]["path"] = ambiguous["volumes"][0]["path"]
        with self.assertRaises(ValueError):
            scan.make_plan(ambiguous, 10, "free-target", ambiguous["volumes"][0]["path"])
        result["volumes"].pop()
        with self.assertRaises(ValueError):
            scan.make_plan(result, 10, "free-target")

    def test_additional_goal_does_not_subtract_existing_free_space(self):
        result = self.multi_volume_report()
        plan = scan.make_plan(result, 10, "additional", "z:/fixture")
        self.assertEqual(plan["goal_kind"], "additional_free_space")
        self.assertEqual(plan["required_additional_bytes"], 10 * scan.GIB)
        self.assertEqual(plan["baseline_free_bytes"], 3 * scan.GIB)
        self.assertEqual(plan["candidate_logical_bytes"], 1000)

    def test_cli_directory_and_free_target_options(self):
        self.file("data/small.txt", b"hello")
        report = self.base / "directories.json"
        plan_path = self.base / "free-target.json"
        self.assertEqual(scan.main(["scan", "--root", str(self.root), "--top-directories", "1", "--output", str(report)]), 0)
        self.assertEqual(len(json.loads(report.read_text(encoding="utf-8"))["largest_directories"]), 1)
        self.assertEqual(scan.main(["plan", "--scan", str(report), "--goal-kind", "free-target",
                                   "--goal-gib", "20", "--volume-root", str(self.root), "--output", str(plan_path)]), 0)
        self.assertEqual(json.loads(plan_path.read_text(encoding="utf-8"))["goal_kind"], "target_free_space")

    def test_cli_roundtrip_and_existing_output_preserved(self):
        self.file("sample.txt", b"hello")
        report = self.base / "scan.json"
        plan = self.base / "plan.json"
        self.assertEqual(scan.main(["scan", "--root", str(self.root), "--output", str(report)]), 0)
        self.assertEqual(scan.main(["plan", "--scan", str(report), "--output", str(plan)]), 0)
        self.assertEqual(json.loads(plan.read_text(encoding="utf-8"))["automatic_reclaimable_bytes"], 0)
        before = report.read_bytes()
        self.assertEqual(scan.main(["scan", "--root", str(self.root), "--output", str(report)]), 2)
        self.assertEqual(report.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
