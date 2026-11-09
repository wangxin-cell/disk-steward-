"""Offline bundle invariants using synthetic source/output sibling directories."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release", SCRIPT)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".package-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).absolute()
        self.source = self.base / "source"
        self.source.mkdir()
        self.output = self.base / "output"
        self.output.mkdir()
        self.contents = {}
        for relative in package.SOURCE_FILES:
            path = self.source.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            content = f"Synthetic authored file: {relative}\n".encode("utf-8")
            path.write_bytes(content)
            self.contents[relative] = content

    def test_members_hashes_and_private_artifact_exclusions(self):
        for relative in (".git/config", "work/local-secret.json", "reports/scan.json", "tests/.fixture/token.txt",
                         "skills/disk-steward/scripts/__pycache__/disk_scan.pyc", "skills/disk-steward/secret.txt",
                         "docs/raw-machine-report.json", "unreviewed.py", "tools/codex.exe",
                         "skills/disk-steward/scripts/python.exe", ".codex/vendor/runtime.dll"):
            path = self.source.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"PRIVATE-MACHINE-FIXTURE")
        manifest = package.build_release(self.source, self.output)
        self.assertEqual(manifest["version"], "0.5.1-alpha")
        for record in manifest["artifacts"]:
            payload = (self.output / record["filename"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])
            self.assertEqual(len(payload), record["size_bytes"])
            self.assertNotIn(b"PRIVATE-MACHINE-FIXTURE", payload)
            expected = ({f"disk-steward/{name}" for name in package.SKILL_FILES} if record["kind"] == "skill"
                        else {f"disk-steward/{name}" for name in package.SOURCE_FILES})
            with zipfile.ZipFile(self.output / record["filename"]) as archive:
                self.assertEqual(set(archive.namelist()), expected)
                if record["kind"] == "skill":
                    self.assertIn("disk-steward/scripts/app_cache.py", archive.namelist())
                    self.assertIn("disk-steward/references/app-cache.md", archive.namelist())
                    self.assertIn("disk-steward/scripts/decision_report.py", archive.namelist())
                    self.assertIn("disk-steward/references/decision-report.md", archive.namelist())
                    self.assertIn("disk-steward/references/zone-identifier.md", archive.namelist())
                    self.assertIn("disk-steward/scripts/app_inventory.py", archive.namelist())
                    self.assertIn("disk-steward/references/application-evidence.md", archive.namelist())
                else:
                    self.assertIn("disk-steward/tests/test_app_cache.py", archive.namelist())
                    self.assertIn("disk-steward/docs/codex-discovery-validation.json", archive.namelist())
                    self.assertIn("disk-steward/tools/acceptance_fixture.py", archive.namelist())
                    self.assertIn("disk-steward/docs/codex-workflow-validation.json", archive.namelist())
                self.assertEqual(archive.namelist(), sorted(archive.namelist()))
                self.assertEqual(len(archive.namelist()), record["file_count"])
                for member in record["members"]:
                    self.assertEqual(hashlib.sha256(archive.read(member["path"])).hexdigest(), member["sha256"])
                    self.assertEqual(len(archive.read(member["path"])), member["size_bytes"])
                    self.assertEqual(archive.getinfo(member["path"]).date_time, package.FIXED_TIME)
                    self.assertEqual(archive.getinfo(member["path"]).compress_type, zipfile.ZIP_STORED)
        manifest_path = self.output / f"disk-steward-{package.VERSION}-manifest.json"
        self.assertEqual(json.loads(manifest_path.read_text()), manifest)
        self.assertNotIn(str(self.base), manifest_path.read_text())

    def test_reproducible_after_source_timestamps_change(self):
        first = package.build_release(self.source, self.output)
        second_output = self.base / "second-output"
        second_output.mkdir()
        for relative in package.SOURCE_FILES:
            os.utime(self.source / relative, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
        second = package.build_release(self.source, second_output)
        self.assertEqual(first, second)
        for original in self.output.iterdir():
            self.assertEqual(original.read_bytes(), (second_output / original.name).read_bytes())

    def test_existing_any_output_prevents_all_writes(self):
        sentinel = self.output / f"disk-steward-{package.VERSION}-source.zip"
        sentinel.write_bytes(b"existing artifact")
        with self.assertRaises(package.PackageError):
            package.build_release(self.source, self.output)
        self.assertEqual(sentinel.read_bytes(), b"existing artifact")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_source_and_nested_output_rejected(self):
        nested = self.source / "dist"
        nested.mkdir()
        for destination in (self.source, nested):
            with self.subTest(destination=destination), self.assertRaises(package.PackageError):
                package.build_release(self.source, destination)
        self.assertEqual(list(nested.iterdir()), [])

    def test_missing_authored_file_fails_before_outputs_are_created(self):
        (self.source / "README.md").unlink()
        with self.assertRaises(FileNotFoundError):
            package.build_release(self.source, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_file_and_source_ancestor_reparse_flags_rejected_without_link_privilege(self):
        original = Path.lstat
        for blocked in (self.source, self.source / "skills", self.source / "README.md", self.output):
            with self.subTest(blocked=blocked):
                def lstat(path, *args, **kwargs):
                    info = original(path, *args, **kwargs)
                    if path == blocked:
                        return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
                    return info
                with patch.object(Path, "lstat", lstat), self.assertRaises(package.PackageError):
                    package.build_release(self.source, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_real_symlink_source_ancestor_rejected(self):
        link = self.base / "linked-source"
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is unavailable")
        with self.assertRaises(package.PackageError):
            package.build_release(link, self.output)

    def test_hardlinked_authored_file_rejected_without_link_privilege(self):
        real_path = self.source / "README.md"
        original = Path.lstat

        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == real_path:
                return SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=2, st_file_attributes=0)
            return info

        with patch.object(Path, "lstat", lstat), self.assertRaises(package.PackageError):
            package.build_release(self.source, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_oversized_source_rejected_before_writes(self):
        with patch.object(package, "MAX_SOURCE_BYTES", 1), self.assertRaises(package.PackageError):
            package.build_release(self.source, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_cli_build_and_no_overwrite(self):
        arguments = ["--source", str(self.source), "--output", str(self.output)]
        self.assertEqual(package.main(arguments), 0)
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.assertEqual(package.main(arguments), 2)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})


if __name__ == "__main__":
    unittest.main()
