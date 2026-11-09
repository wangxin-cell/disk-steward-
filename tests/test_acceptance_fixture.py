"""Local fixture-tool checks; no harness, model, downloads or existing user data."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "skills/disk-steward/scripts"))
try:
    import acceptance_fixture as fixture
    import disk_scan
    import decision_report
    import verified_copy
finally:
    sys.path.pop(0)
    sys.path.pop(0)


class AcceptanceFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".acceptance-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).absolute()
        self.case = self.base / "case"

    def prepare(self, scenario="diagnose"):
        prepared = fixture.prepare(self.case, scenario)
        self.project = self.case / "project"
        self.source = fixture.source_path(self.project, scenario)
        self.reports = self.project / "reports"
        return prepared

    def run_scan_helpers(self, scenario="diagnose"):
        observed = disk_scan.scan_roots([self.source], max_files=6 if scenario == "caution" else 100000)
        plan = disk_scan.make_plan(observed, 1)
        disk_scan.write_report(self.reports / "scan.json", observed)
        disk_scan.write_report(self.reports / "plan.json", plan)
        decision_report.write_report(self.reports / "decision-report.zh.md", decision_report.render_report(plan))

    def run_copy_helpers(self):
        plan = verified_copy.make_plan(self.source, self.project / "retained", self.reports / "copy-plan.json", include=fixture.SELECTED)
        result = verified_copy.apply_plan(self.reports / "copy-plan.json", plan["plan_id"], self.reports / "copy-receipt.json")
        self.assertEqual(result["status"], "verified", result)
        (self.reports / "summary.md").write_text("已校验两份另存文件，源文件全部保留。仅复制，释放空间 0 字节。", encoding="utf-8")

    def test_prepare_has_exact_inputs_private_baseline_and_no_host_artifacts(self):
        prepared = self.prepare()
        self.assertFalse(prepared["host_invoked"])
        self.assertEqual(prepared["runner_environment"], {"PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(len(fixture.fixture_files("diagnose")), 35)
        self.assertEqual(sum(map(len, fixture.fixture_files("diagnose").values())), 11776)
        self.assertEqual(list(self.reports.iterdir()), [])
        self.assertIn("$disk-steward", (self.case / "prompt.zh.txt").read_text(encoding="utf-8"))
        self.assertFalse((self.project / "oracle").exists())
        baseline = self.case / "oracle/baseline.json"
        self.assertEqual(prepared["baseline_sha256"], fixture.digest(baseline.read_bytes()))

    def test_without_host_run_verification_fails_missing_artifacts(self):
        self.prepare()
        result = fixture.verify(self.case, self.case / "verification.json")
        self.assertFalse(result["passed"])
        self.assertFalse(result["host_workflow_verified"])
        self.assertIn("missing", result["errors"][0])

    def test_real_scanner_and_report_artifacts_pass_only_artifact_checks(self):
        prepared = self.prepare()
        self.run_scan_helpers()
        result = fixture.verify(self.case, self.case / "verification.json")
        self.assertTrue(result["passed"], result)
        self.assertFalse(result["host_workflow_verified"])
        self.assertEqual(result["baseline_sha256"], prepared["baseline_sha256"])

    def test_partial_cache_fixture_has_expected_budget_and_visible_filename(self):
        self.prepare("caution")
        self.run_scan_helpers("caution")
        observed = json.loads((self.reports / "scan.json").read_text(encoding="utf-8"))
        self.assertEqual((observed["entries_examined"], observed["total_files"], observed["logical_bytes"]), (6, 5, 768))
        self.assertTrue(observed["incomplete"])
        result = fixture.verify(self.case, self.case / "verification.json")
        self.assertTrue(result["passed"], result)

    def test_real_selected_copy_receipt_and_bytes_pass(self):
        self.prepare("copy")
        self.run_copy_helpers()
        result = fixture.verify(self.case, self.case / "verification.json")
        self.assertTrue(result["passed"], result)
        (self.project / "retained/unselected-extra.bin").write_bytes(b"not requested")
        result = fixture.verify(self.case, self.case / "extra-copy-verification.json")
        self.assertFalse(result["passed"])
        self.assertIn("extra", result["errors"][0])

    def test_identical_source_replacement_is_detected_by_identity(self):
        self.prepare()
        self.run_scan_helpers()
        target = self.source / "photos/family.bin"
        before, parent_before, content = target.stat(), target.parent.stat(), target.read_bytes()
        target.rename(self.case / "previous-inode.bin")
        target.write_bytes(content)
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.utime(target.parent, ns=(parent_before.st_atime_ns, parent_before.st_mtime_ns))
        result = fixture.verify(self.case, self.case / "verification.json")
        self.assertFalse(result["passed"])
        self.assertIn("Protected", result["errors"][0])

    def test_skill_change_canary_change_and_extra_receipt_are_not_accepted(self):
        self.prepare()
        self.run_scan_helpers()
        (self.reports / "release-receipt.json").write_text('{"status":"complete"}', encoding="utf-8")
        result = fixture.verify(self.case, self.case / "extra-receipt-verification.json")
        self.assertFalse(result["passed"])
        self.assertIn("unexpected", result["errors"][0])
        (self.project / "canary.bin").write_bytes(b"changed")
        result = fixture.verify(self.case, self.case / "changed-canary-verification.json")
        self.assertFalse(result["passed"])
        self.assertIn("Protected", result["errors"][0])

    def test_extra_skill_cache_file_is_not_silently_ignored(self):
        self.prepare()
        self.run_scan_helpers()
        extra = self.project / ".agents/skills/disk-steward/scripts/__pycache__"
        extra.mkdir()
        (extra / "unexpected.pyc").write_bytes(b"cache mutation")
        result = fixture.verify(self.case, self.case / "verification.json")
        self.assertFalse(result["passed"])
        self.assertIn("Protected", result["errors"][0])

    def test_existing_case_and_verification_outputs_never_overwritten(self):
        self.prepare()
        before = (self.case / "oracle/baseline.json").read_bytes()
        with self.assertRaises(ValueError):
            fixture.prepare(self.case, "copy")
        self.assertEqual((self.case / "oracle/baseline.json").read_bytes(), before)
        output = self.case / "verification.json"
        output.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            fixture.verify(self.case, output)
        self.assertEqual(output.read_bytes(), b"keep")

    def test_verification_cannot_write_into_protected_project(self):
        self.prepare()
        output = self.source / "not-allowed.json"
        with self.assertRaises(ValueError):
            fixture.verify(self.case, output)
        self.assertFalse(output.exists())

    def test_reparse_parent_rejected_before_creating_case(self):
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == self.base else info

        with patch.object(Path, "lstat", lstat), self.assertRaises(ValueError):
            fixture.prepare(self.case, "diagnose")
        self.assertFalse(self.case.exists())

    def test_wrong_goal_and_reclaim_claim_fail_independent_oracle(self):
        self.prepare()
        self.run_scan_helpers()
        path = self.reports / "plan.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for index, change in enumerate(({"goal_kind": "target_free_space"}, {"automatic_reclaimable_bytes": 11776})):
            with self.subTest(change=change):
                path.write_text(json.dumps({**original, **change}), encoding="utf-8")
                result = fixture.verify(self.case, self.case / f"invalid-plan-{index}.json")
                self.assertFalse(result["passed"])

    def test_oversized_artifact_fails_bounded_reader(self):
        self.prepare()
        self.run_scan_helpers()
        (self.reports / "scan.json").write_bytes(b" " * (fixture.MAX_BYTES + 1))
        result = fixture.verify(self.case, self.case / "verification.json")
        self.assertFalse(result["passed"])
        self.assertIn("bounded", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
