"""Application evidence is supplied synthetic JSON, never live registry data."""

import copy
import html
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/disk-steward/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import decision_report as report
finally:
    sys.path.pop(0)

FILE = r"C:\Samples\Tool\assets\data.bin"
OTHER = r"C:\Samples\Toolbox\notes.bin"
LOCATION = r"C:\Samples\Tool"


def plan():
    return {
        "schema_version": 1, "goal_kind": "additional_free_space", "goal_bytes": 1024,
        "scan_incomplete": False, "goal_volume": {"volume_id": "c", "free_bytes": 4096},
        "candidates": [{"path": path, "logical_bytes": size, "category": "user_file",
                        "volume_id": "c", "hardlink_count": 1}
                       for path, size in ((FILE, 256), (OTHER, 128))],
        "directory_reviews": [{"path": r"C:\Samples", "logical_bytes": 384,
                               "category": "user_file", "observed_files": 2}],
    }


def inventory(location=LOCATION):
    scopes = [{"hive": hive, "view": view, "status": "complete", "entries_examined": 0, "errors": []}
              for hive, view in (("HKLM", "32"), ("HKLM", "64"), ("HKCU", "32"), ("HKCU", "64"))]
    scopes[1]["entries_examined"] = 1
    return {
        "schema_version": 1, "kind": "disk-steward-application-inventory",
        "created_at": "2026-11-05T00:00:00+00:00", "coverage": "uninstall_registration_only",
        "incomplete": False, "max_entries": 1000, "entries_examined": 1, "scopes": scopes,
        "entries": [{"hive": "HKLM", "view": "64", "subkey": "Synthetic-Tool",
                     "display_name": "Synthetic Tool", "display_version": "1.0",
                     "publisher": "Synthetic Publisher", "install_location": location}],
    }


def choices():
    return {"schema_version": 1, "scenarios": [{"name": "conservative", "choices": [
        {"path": path, "action": "copy_then_release", "explanation": "Synthetic proposal",
         "consequence": "Requires its own later review", "destination_volume_id": "d"}
        for path in (FILE, OTHER)]}]}


def visible(text):
    return html.unescape(re.sub(r"\\([^\w\s])", r"\1", text))


class ApplicationReportTests(unittest.TestCase):
    def test_omitted_inventory_preserves_existing_api_and_output(self):
        for language in ("zh", "en"):
            self.assertEqual(report.render_report(plan(), choices(), language),
                             report.render_report(plan(), choices(), language, applications=None))
        self.assertEqual(report.analyze_scenarios(plan(), choices()),
                         report.analyze_scenarios(plan(), choices(), applications=None))

    def test_rendering_and_analysis_never_access_embedded_paths_or_registry(self):
        inputs, apps, proposals = plan(), inventory(), choices()
        originals = copy.deepcopy((inputs, apps, proposals))
        with patch("builtins.open", side_effect=AssertionError("File access")), \
                patch.object(Path, "open", side_effect=AssertionError("Path open")), \
                patch.object(Path, "stat", side_effect=AssertionError("Path stat")), \
                patch.object(Path, "lstat", side_effect=AssertionError("Path lstat")), \
                patch("os.stat", side_effect=AssertionError("stat")), \
                patch("os.scandir", side_effect=AssertionError("scandir")), \
                patch("subprocess.run", side_effect=AssertionError("Command")), \
                patch.object(report.inventory_tools, "collect",
                             side_effect=AssertionError("Registry collection")):
            rendered = report.render_report(inputs, proposals, "en", apps)
            analyzed = report.analyze_scenarios(inputs, proposals, apps)
        self.assertIn("Application registration path evidence", rendered)
        self.assertEqual(analyzed[0]["selected_logical_copy_scope_bytes"], 128)
        self.assertEqual((inputs, apps, proposals), originals)

    def test_registration_overlap_excludes_copy_even_if_plan_claims_user_file(self):
        result = report.analyze_scenarios(plan(), choices(), inventory())[0]
        self.assertEqual(result["rows"][0]["scope_status"], "excluded_application_registration")
        self.assertEqual(result["rows"][0]["counted_logical_bytes"], 0)
        self.assertEqual(result["rows"][1]["scope_status"], "hypothetical_copy_scope")
        self.assertEqual(result["selected_logical_copy_scope_bytes"], 128)
        self.assertFalse(result["authorization"])
        self.assertIsNone(result["goal_achieved"])
        self.assertIsNone(result["actual_reclaimed_bytes"])

    def test_case_and_separator_aliases_match_but_similar_names_do_not(self):
        apps = inventory("c:/SAMPLES/TOOL")
        result = report.analyze_scenarios(plan(), choices(), apps)[0]
        self.assertEqual(result["rows"][0]["scope_status"], "excluded_application_registration")
        self.assertEqual(result["rows"][1]["counted_logical_bytes"], 128)

    def test_file_and_parent_directory_have_distinct_relationships(self):
        raw = report.render_report(plan(), language="en", applications=inventory())
        rendered = visible(raw)
        self.assertIn("inside registered location", rendered)
        self.assertIn("directory contains registered location", rendered)
        self.assertIn("not wholly attributed", rendered)
        self.assertIn("does not prove installed status, ownership or disposability", rendered)
        self.assertIn("no match does not establish an orphan", rendered)
        first_row = lambda text, path: next(line for line in text.splitlines() if line.startswith("| " + report.escape_text(path) + " |"))
        self.assertIn("Verify current app status, data purpose and shared dependencies", first_row(raw, FILE))
        self.assertIn("Direct ordinary-file relocation or release is unproven", first_row(raw, FILE))
        self.assertIn("Review individual files", first_row(raw, r"C:\Samples"))
        self.assertIn("whole directory is not attributed", first_row(raw, r"C:\Samples"))
        self.assertEqual(first_row(raw, OTHER), first_row(report.render_report(plan(), language="en"), OTHER))
        chinese = report.render_report(plan(), applications=inventory())
        self.assertIn("先核实应用当前状态、数据用途及共享依赖", first_row(chinese, FILE))
        self.assertIn("先拆分审查具体文件用途", first_row(chinese, r"C:\Samples"))

    def test_only_related_registrations_are_disclosed(self):
        apps = inventory()
        unrelated = {**apps["entries"][0], "subkey": "Unrelated", "display_name": "PRIVATE-UNRELATED-APP",
                     "install_location": r"D:\Unrelated"}
        apps["entries"].append(unrelated)
        apps["entries_examined"] = apps["scopes"][1]["entries_examined"] = 2
        rendered = report.render_report(plan(), language="en", applications=apps)
        self.assertNotIn("PRIVATE", rendered)
        self.assertIn("Synthetic Tool", visible(rendered))

    def test_missing_variable_and_unsupported_locations_are_not_name_matched(self):
        for location in (None, "%LOCALAPPDATA%\\Tool", r"\\server\share\Tool", "relative\\Tool"):
            with self.subTest(location=location):
                apps = inventory(location)
                apps["entries"][0]["display_name"] = "Tool"
                result = report.analyze_scenarios(plan(), choices(), apps)[0]
                self.assertEqual(result["selected_logical_copy_scope_bytes"], 384)
                rendered = report.render_report(plan(), language="en", applications=apps)
                self.assertIn("ownership unknown", rendered)

    def test_unsupported_candidate_path_is_reported_without_io(self):
        inputs = plan()
        inputs["candidates"][0]["path"] = "/synthetic/not-a-windows-drive/data.bin"
        rendered = report.render_report(inputs, language="en", applications=inventory())
        self.assertIn("candidate path unsupported for association", rendered)

    def test_partial_scope_and_snapshot_counts_are_visible_in_both_languages(self):
        apps = inventory()
        apps["incomplete"] = True
        apps["scopes"][3].update(status="partial", errors=["Synthetic access denied"])
        for language, expected in (("en", "Partial registration coverage"), ("zh", "部分登记范围")):
            with self.subTest(language=language):
                rendered = visible(report.render_report(plan(), language=language, applications=apps))
                self.assertIn(expected, rendered)
                self.assertIn("2026-11-05T00:00:00+00:00", rendered)
                self.assertIn("1 / 1 / 1000", rendered)
                self.assertIn("HKCU", rendered)
                self.assertIn("partial", rendered)

    def test_malicious_application_metadata_stays_inert_in_both_languages(self):
        attack = '<img src=x onerror=alert(1)> [Run](https://evil.invalid) | cell\n# INJECTED\n```cmd\nwhoami\n```\u202e\u2060\x07\x1b'
        apps = inventory()
        for key in ("display_name", "display_version", "publisher"):
            apps["entries"][0][key] = attack
        apps["entries"][0]["subkey"] = '<b>Source</b> [Run](https://evil.invalid) | cell'
        for language in ("zh", "en"):
            with self.subTest(language=language):
                text = report.render_report(plan(), language=language, applications=apps)
                self.assertNotIn("<img", text)
                self.assertNotIn("https://", text)
                self.assertNotIn("\n# INJECTED", text)
                self.assertNotIn("\n```cmd", text)
                self.assertNotIn("\u202e", text)
                self.assertNotIn("\u2060", text)
                self.assertNotIn("\x07", text)
                self.assertNotIn("\x1b", text)
                self.assertNotRegex(text, r"(?<!\\)\| cell")
                self.assertIn("[U+202E]", visible(text))
                self.assertIn("[U+2060]", visible(text))
                self.assertIn("[U+0007]", visible(text))
                self.assertIn("[U+001B]", visible(text))
                self.assertIn("evil.invalid", visible(text))

    def test_invalid_or_malicious_collection_timestamp_is_rejected(self):
        for value in ("not-a-time", "2026-11-05\n# INJECTED", "<img src=x>", 42):
            apps = inventory()
            apps["created_at"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                report.render_report(plan(), applications=apps)

    def test_wrong_schema_coverage_and_self_asserted_status_are_rejected(self):
        for key, value in (("schema_version", 2), ("schema_version", True), ("kind", "trusted-owner-list"),
                           ("coverage", "all_applications"), ("ownership_verified", True)):
            apps = inventory()
            apps[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                report.analyze_scenarios(plan(), choices(), apps)
        apps = inventory()
        apps["entries"][0]["status"] = "ownership_verified"
        with self.assertRaises(ValueError):
            report.render_report(plan(), applications=apps)

    def test_duplicate_registration_identity_is_rejected(self):
        apps = inventory()
        apps["entries"].append({**apps["entries"][0], "subkey": "SYNTHETIC-TOOL"})
        apps["entries_examined"] = apps["scopes"][1]["entries_examined"] = 2
        with self.assertRaises(ValueError):
            report.render_report(plan(), applications=apps)

    def test_association_details_are_bounded_with_full_count_and_deduplicated_sources(self):
        apps = inventory()
        apps["entries"] = [{**apps["entries"][0], "subkey": f"Entry-{index}", "display_name": f"App{index}"}
                           for index in range(8)]
        apps["entries"][0]["subkey"] = "Straße"
        apps["entries"][1]["subkey"] = "STRASSE"
        apps["entries_examined"] = apps["scopes"][1]["entries_examined"] = 8
        rendered = visible(report.render_report(plan(), language="en", applications=apps))
        self.assertIn("At most 3 matches", rendered)
        self.assertIn("| 8 |", rendered)
        self.assertEqual(rendered.count("| App"), 3)
        self.assertIn("Straße", rendered)
        self.assertIn("STRASSE", rendered)
        self.assertEqual(report.analyze_scenarios(plan(), choices(), apps)[0]["selected_logical_copy_scope_bytes"], 128)

    def test_one_assessor_is_built_for_all_targets(self):
        original = report.inventory_tools.make_assessor
        with patch.object(report.inventory_tools, "make_assessor", wraps=original) as make:
            report.render_report(plan(), choices(), "en", inventory())
        self.assertEqual(make.call_count, 1)


class ApplicationReportCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".application-report-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.plan = self.base / "plan.json"
        self.apps = self.base / "applications.json"
        self.output = self.base / "report.md"
        self.plan.write_text(json.dumps(plan()), encoding="utf-8")
        self.apps.write_text(json.dumps(inventory()), encoding="utf-8")

    def run_cli(self):
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
            return report.main(["--plan", str(self.plan), "--applications", str(self.apps),
                                "--output", str(self.output), "--language", "en"])

    def test_cli_consumes_explicit_inventory_without_extra_outputs(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertIn("Application registration path evidence", self.output.read_text(encoding="utf-8"))
        self.assertEqual(sorted(path.name for path in self.base.iterdir()), ["applications.json", "plan.json", "report.md"])

    def test_duplicate_application_json_keys_fail_before_report_creation(self):
        self.apps.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        self.assertEqual(self.run_cli(), 2)
        self.assertFalse(self.output.exists())

    def test_invalid_inventory_fails_without_overwriting_existing_report(self):
        self.output.write_text("existing-report", encoding="utf-8")
        self.apps.write_text('{"schema_version":2}', encoding="utf-8")
        self.assertEqual(self.run_cli(), 2)
        self.assertEqual(self.output.read_text(), "existing-report")


if __name__ == "__main__":
    unittest.main()
