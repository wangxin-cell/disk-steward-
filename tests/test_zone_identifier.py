"""Zone.Identifier preservation uses only inert, disposable Windows fixtures.

No downloads, executable invocation or preexisting user files. Source marker
deletion is not claimed to be locked out: a pending-delete marker must instead
be detected before the primary source is marked for deletion.
"""

from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
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
    import verified_copy as vc
    import source_release as release
finally:
    sys.path.pop(0)

ZONE = b"[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://example.invalid/synthetic-only\r\n"
ZONE_OTHER = b"[ZoneTransfer]\r\nZoneId=4\r\nHostUrl=https://example.invalid/second-fixture\r\n"


def zone_path(path):
    return str(path) + ":Zone.Identifier"


def write_zone(path, content):
    with open(zone_path(path), "wb") as stream:
        stream.write(content)


def read_zone(path):
    with open(zone_path(path), "rb") as stream:
        return stream.read()


@contextmanager
def pending_zone_delete(path):
    """Hold a DELETE-only handle to a test marker after setting DeletePending."""
    from ctypes import wintypes

    class Disposition(ctypes.Structure):
        _fields_ = [("DeleteFile", ctypes.c_ubyte)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    disposition = kernel.SetFileInformationByHandle
    disposition.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    disposition.restype = wintypes.BOOL
    # Named source-stream lock permits DELETE but not read/write competitors.
    # Our new handle shares all operations already held by the release helper.
    handle = create(zone_path(path), 0x10000, 7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        value = Disposition(1)
        if not disposition(handle, 4, ctypes.byref(value), ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        yield handle
    finally:
        close(handle)


@unittest.skipUnless(os.name == "nt", "Zone.Identifier preservation and locks require native Windows")
class ZoneIdentifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".zone-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).absolute()
        self.source = self.base / "source"
        self.source.mkdir()
        self.file = self.source / "download.bin"
        self.second = self.source / "second.bin"
        self.keep = self.source / "keep.bin"
        self.primary = b"INERT SYNTHETIC TEST DATA\x00\r\n" * 128
        self.file.write_bytes(self.primary)
        self.second.write_bytes(b"second inert fixture")
        self.keep.write_bytes(b"unselected sentinel")
        try:
            write_zone(self.file, ZONE)
            write_zone(self.second, ZONE_OTHER)
            write_zone(self.keep, b"unselected marker must survive")
        except OSError:
            self.skipTest("Fixture filesystem does not support creating alternate streams")
        self.counter = 0

    def make_plan(self, include=None, preserve=True):
        self.counter += 1
        self.destination = self.base / f"retained-{self.counter}"
        self.copy_plan_path = self.base / f"copy-plan-{self.counter}.json"
        self.copy_receipt_path = self.base / f"copy-receipt-{self.counter}.json"
        self.release_plan_path = self.base / f"release-plan-{self.counter}.json"
        self.journal_path = self.base / f"release-receipt-{self.counter}.jsonl"
        self.copy_plan = vc.make_plan(self.source, self.destination, self.copy_plan_path,
                                     include=include or [self.file.name], preserve_zone_identifier=preserve)
        return self.copy_plan

    def apply_copy(self):
        return vc.apply_plan(self.copy_plan_path, self.copy_plan["plan_id"], self.copy_receipt_path)

    def ready_release(self, include=None):
        self.make_plan(include)
        receipt = self.apply_copy()
        self.assertEqual(receipt["status"], "verified", receipt)
        self.release_plan = release.make_plan(self.copy_plan_path, self.copy_receipt_path, self.release_plan_path)
        return self.release_plan

    def apply_release(self):
        return release.apply_plan(self.release_plan_path, self.release_plan["plan_id"], self.journal_path)

    def save_copy(self, plan):
        plan["plan_id"] = vc.canonical_id({key: value for key, value in plan.items() if key != "plan_id"})
        self.copy_plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def assert_stale_copy(self):
        result = self.apply_copy()
        self.assertEqual(result["status"], "failed", result)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.file.read_bytes(), self.primary)

    def assert_release_preserved_source(self):
        result = self.apply_release()
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["deleted_files"], 0)
        self.assertEqual(self.file.read_bytes(), self.primary)
        return result

    def test_opt_in_manifest_receipt_and_exact_marker_bytes(self):
        plan = self.make_plan()
        self.assertEqual(plan["schema_version"], 3)
        self.assertEqual(plan["stream_policy"], "preserve-zone-identifier")
        self.assertEqual(plan["zone_identifier_bytes"], len(ZONE))
        self.assertEqual(plan["total_bytes"], len(self.primary))
        self.assertEqual(plan["files"][0]["zone_identifier"], {
            "size": len(ZONE), "sha256": hashlib.sha256(ZONE).hexdigest()})
        self.assertNotIn("example.invalid", self.copy_plan_path.read_text())
        result = self.apply_copy()
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["verified_bytes"], len(self.primary))
        self.assertEqual(result["verified_zone_identifier_bytes"], len(ZONE))
        self.assertEqual(result["verified_zone_identifier_files"], 1)
        self.assertEqual((self.destination / self.file.name).read_bytes(), self.primary)
        self.assertEqual(read_zone(self.destination / self.file.name), ZONE)
        self.assertEqual(read_zone(self.file), ZONE)
        self.assertEqual(read_zone(self.keep), b"unselected marker must survive")

    def test_default_and_shared_cache_checks_still_reject_zone_stream(self):
        with self.assertRaises(vc.CopyError):
            self.make_plan(preserve=False)
        with self.assertRaises(vc.CopyError):
            vc.check_streams(self.file)
        with self.assertRaises(vc.CopyError):
            vc.checked_file(self.file)

    def test_null_marker_creates_no_marker_and_zero_marker_counters(self):
        os.unlink(zone_path(self.file))
        plan = self.make_plan()
        self.assertIsNone(plan["files"][0]["zone_identifier"])
        self.assertEqual(plan["zone_identifier_bytes"], 0)
        self.assertIsNone(vc.zone_descriptor(self.file))
        result = self.apply_copy()
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["verified_zone_identifier_files"], 0)
        self.assertEqual(result["verified_zone_identifier_bytes"], 0)
        self.assertIsNone(vc.read_zone_identifier(self.destination / self.file.name))

    def test_empty_marker_is_preserved_as_present_not_null(self):
        write_zone(self.file, b"")
        plan = self.make_plan()
        self.assertEqual(plan["files"][0]["zone_identifier"], {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()})
        self.assertEqual(vc.zone_descriptor(self.file), 0)
        result = self.apply_copy()
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["verified_zone_identifier_files"], 1)
        self.assertEqual(vc.read_zone_identifier(self.destination / self.file.name), b"")

    def test_opaque_non_utf8_bytes_and_case_insensitive_fixed_name(self):
        os.unlink(zone_path(self.file))
        opaque = b"\xff\xfe\x00opaque\r\n\x80no-ini-parsing\x00"
        with open(str(self.file) + ":zOnE.IdEnTiFiEr", "wb") as stream:
            stream.write(opaque)
        self.make_plan()
        result = self.apply_copy()
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(read_zone(self.destination / self.file.name), opaque)

    def test_oversized_marker_rejected_before_copy(self):
        write_zone(self.file, b"x" * (65536 + 1))
        with self.assertRaises(vc.CopyError):
            self.make_plan()
        self.assertFalse(self.destination.exists())

    def test_exact_64kib_marker_boundary_is_preserved_without_truncation(self):
        marker = bytes(range(256)) * 256
        self.assertEqual(len(marker), 65536)
        write_zone(self.file, marker)
        self.make_plan()
        result = self.apply_copy()
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["verified_zone_identifier_bytes"], 65536)
        self.assertEqual(read_zone(self.destination / self.file.name), marker)

    def test_v3_platform_guard_rejects_nonwindows_before_output_mutation(self):
        plan = self.make_plan()
        another_destination = self.base / "nonwindows-target"
        another_plan = self.base / "nonwindows-plan.json"
        with patch.object(vc.os, "name", "posix"):
            with self.assertRaises(vc.CopyError):
                vc.make_plan(self.source, another_destination, another_plan,
                             include=[self.file.name], preserve_zone_identifier=True)
            with self.assertRaises(vc.CopyError):
                vc.validate_plan(plan, plan["plan_id"])
            with self.assertRaises(vc.CopyError):
                self.apply_copy()
        self.assertFalse(another_destination.exists())
        self.assertFalse(another_plan.exists())
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.copy_receipt_path.exists())
        self.assertEqual(read_zone(self.file), ZONE)

    def test_unknown_stream_alongside_zone_is_rejected(self):
        with open(str(self.file) + ":unknown-metadata", "wb") as stream:
            stream.write(b"must not discard")
        with self.assertRaises(vc.CopyError):
            self.make_plan()
        self.assertEqual(read_zone(self.file), ZONE)

    def test_near_name_stream_is_not_the_allowed_marker(self):
        with open(str(self.file) + ":Zone.Identifier.extra", "wb") as stream:
            stream.write(b"not the allowlisted stream")
        with self.assertRaises(vc.CopyError):
            vc.zone_descriptor(self.file)

    def test_directory_marker_is_rejected_even_in_opt_in_mode(self):
        write_zone(self.source, ZONE)
        with self.assertRaises(vc.CopyError):
            self.make_plan()

    def test_marker_added_after_plan_is_stale(self):
        os.unlink(zone_path(self.file))
        self.make_plan()
        write_zone(self.file, ZONE)
        self.assert_stale_copy()

    def test_marker_removed_after_plan_is_stale(self):
        self.make_plan()
        os.unlink(zone_path(self.file))
        self.assert_stale_copy()

    def test_same_size_marker_change_with_restored_main_timestamp_is_stale(self):
        self.make_plan()
        before = self.file.stat()
        write_zone(self.file, b"x" * len(ZONE))
        os.utime(self.file, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assert_stale_copy()

    def test_marker_is_verified_before_any_primary_payload_is_written(self):
        self.make_plan()
        original = vc.write_zone_identifier
        observed = []

        def check_order(destination, content):
            observed.append(destination.stat().st_size)
            self.assertEqual(destination.stat().st_size, 0)
            result = original(destination, content)
            self.assertEqual(destination.stat().st_size, 0)
            self.assertEqual(read_zone(destination), ZONE)
            return result

        with patch.object(vc, "write_zone_identifier", side_effect=check_order):
            result = self.apply_copy()
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(observed, [0])

    def test_marker_write_failure_never_leaves_unmarked_primary_payload(self):
        self.make_plan()
        with patch.object(vc, "write_zone_identifier", side_effect=OSError("synthetic ADS destination failure")):
            result = self.apply_copy()
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(result["verified_files"], 0)
        self.assertEqual(self.file.read_bytes(), self.primary)
        self.assertEqual(read_zone(self.file), ZONE)
        target = self.destination / self.file.name
        if target.exists():
            self.assertEqual(target.stat().st_size, 0)

    def test_source_marker_changes_after_preflight_fail_copy(self):
        self.make_plan()
        original = vc.copy_file

        def mutate_before_copy(source, destination, item):
            before = source.stat()
            write_zone(source, b"x" * len(ZONE))
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
            return original(source, destination, item)

        with patch.object(vc, "copy_file", side_effect=mutate_before_copy):
            result = self.apply_copy()
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(self.file.read_bytes(), self.primary)

    def test_target_marker_corruption_after_copy_fails_final_verification(self):
        self.make_plan()
        original = vc.copy_file

        def corrupt_after_copy(source, destination, item):
            original(source, destination, item)
            before = destination.stat()
            write_zone(destination, b"x" * len(ZONE))
            os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))

        with patch.object(vc, "copy_file", side_effect=corrupt_after_copy):
            result = self.apply_copy()
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(self.file.read_bytes(), self.primary)

    def test_resigned_invalid_marker_schema_and_totals_are_rejected(self):
        original = self.make_plan()
        changes = [
            lambda p: p.update(stream_policy="discard-zone-identifier"),
            lambda p: p.update(zone_identifier_bytes=p["zone_identifier_bytes"] + 1),
            lambda p: p["files"][0].pop("zone_identifier"),
            lambda p: p["files"][0]["zone_identifier"].update(size=True),
            lambda p: p["files"][0]["zone_identifier"].update(size=-1),
            lambda p: p["files"][0]["zone_identifier"].update(size=65537),
            lambda p: p["files"][0]["zone_identifier"].update(sha256="bad"),
            lambda p: p["files"][0]["zone_identifier"].update(name="arbitrary:stream"),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                forged = json.loads(json.dumps(original))
                change(forged)
                self.save_copy(forged)
                with self.assertRaises(vc.CopyError):
                    vc.validate_plan(forged, forged["plan_id"])
        self.assertFalse(self.destination.exists())

    def test_legacy_v1_v2_plans_do_not_silently_gain_marker_support(self):
        for version in (1, 2):
            with self.subTest(version=version):
                legacy_source = self.base / f"legacy-source-{version}"
                legacy_source.mkdir()
                item = legacy_source / "plain.bin"
                item.write_bytes(b"legacy unmarked bytes")
                destination = self.base / f"legacy-copy-{version}"
                plan_path = self.base / f"legacy-plan-{version}.json"
                receipt_path = self.base / f"legacy-receipt-{version}.json"
                plan = vc.make_plan(legacy_source, destination, plan_path)
                self.assertEqual(plan["schema_version"], 2)
                self.assertNotIn("zone_identifier", plan["files"][0])
                if version == 1:
                    plan["schema_version"] = 1
                    plan.pop("scope")
                    plan.pop("selected_paths")
                    plan["plan_id"] = vc.canonical_id({k: v for k, v in plan.items() if k != "plan_id"})
                    plan_path.write_text(json.dumps(plan), encoding="utf-8")
                write_zone(item, ZONE)
                result = vc.apply_plan(plan_path, plan["plan_id"], receipt_path)
                self.assertEqual(result["status"], "failed", result)
                self.assertFalse(destination.exists())
                self.assertEqual(read_zone(item), ZONE)

    def test_release_preserves_exact_marker_and_unselected_files(self):
        self.ready_release()
        result = self.apply_release()
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["deleted_files"], 1)
        self.assertEqual(result["logical_source_zone_identifier_bytes_removed"], len(ZONE))
        self.assertEqual(result["deleted_zone_identifier_files"], 1)
        self.assertFalse(self.file.exists())
        self.assertEqual((self.destination / self.file.name).read_bytes(), self.primary)
        self.assertEqual(read_zone(self.destination / self.file.name), ZONE)
        self.assertEqual(self.keep.read_bytes(), b"unselected sentinel")
        self.assertEqual(read_zone(self.keep), b"unselected marker must survive")
        self.assertNotIn("example.invalid", self.journal_path.read_text())

    def test_release_planning_rejects_target_marker_mismatch(self):
        self.make_plan()
        self.assertEqual(self.apply_copy()["status"], "verified")
        write_zone(self.destination / self.file.name, b"x" * len(ZONE))
        with self.assertRaises(vc.CopyError):
            release.make_plan(self.copy_plan_path, self.copy_receipt_path, self.release_plan_path)
        self.assertTrue(self.file.exists())

    def test_source_marker_removed_after_release_plan_blocks_deletion(self):
        self.ready_release()
        os.unlink(zone_path(self.file))
        self.assert_release_preserved_source()

    def test_source_marker_changed_after_release_plan_blocks_deletion(self):
        self.ready_release()
        before = self.file.stat()
        write_zone(self.file, b"x" * len(ZONE))
        os.utime(self.file, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assert_release_preserved_source()

    def test_retained_marker_removed_after_release_plan_blocks_deletion(self):
        self.ready_release()
        os.unlink(zone_path(self.destination / self.file.name))
        self.assert_release_preserved_source()

    def test_retained_marker_changed_after_release_plan_blocks_deletion(self):
        self.ready_release()
        target = self.destination / self.file.name
        before = target.stat()
        write_zone(target, b"x" * len(ZONE))
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assert_release_preserved_source()

    def test_marker_added_to_previously_unmarked_retained_copy_blocks_release(self):
        os.unlink(zone_path(self.file))
        self.ready_release()
        write_zone(self.destination / self.file.name, ZONE)
        self.assert_release_preserved_source()

    def test_open_source_marker_writer_blocks_source_deletion(self):
        self.ready_release()
        with open(zone_path(self.file), "r+b"):
            self.assert_release_preserved_source()

    def test_open_retained_marker_writer_blocks_source_deletion(self):
        self.ready_release()
        with open(zone_path(self.destination / self.file.name), "r+b"):
            self.assert_release_preserved_source()

    def test_retained_marker_lock_blocks_competing_write_and_delete(self):
        plan = self.ready_release()
        target = self.destination / self.file.name
        with release.locked_file(target, plan["retained_files"][0]) as stream:
            self.assertIsNotNone(stream.zone_identifier_stream)
            with self.assertRaises(PermissionError):
                with open(zone_path(target), "wb"):
                    pass
            with self.assertRaises(PermissionError):
                os.unlink(zone_path(target))
        self.assertEqual(read_zone(target), ZONE)

    def test_pending_source_marker_deletion_is_detected_before_primary_deletion(self):
        plan = self.ready_release()
        target = self.destination / self.file.name
        with ExitStack() as held:
            def pending():
                held.enter_context(pending_zone_delete(self.file))

            with patch.object(release, "mark_for_deletion", wraps=release.mark_for_deletion) as marking:
                with self.assertRaises((vc.CopyError, OSError)):
                    release.remove_verified_pair(self.file, target, plan["copy_plan"]["files"][0],
                                                 plan["retained_files"][0], pending)
                marking.assert_not_called()
            self.assertEqual(self.file.read_bytes(), self.primary)
            self.assertEqual(read_zone(target), ZONE)
        self.assertTrue(self.file.exists())

    def test_failure_on_second_marked_file_retains_markers_and_partial_journal(self):
        self.ready_release(include=[self.file.name, self.second.name])
        original = release.mark_for_deletion
        calls = []

        def fail_second(stream):
            calls.append(stream)
            if len(calls) == 2:
                raise PermissionError("synthetic failure before second source deletion")
            return original(stream)

        with patch.object(release, "mark_for_deletion", side_effect=fail_second):
            result = self.apply_release()
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(result["deleted_files"], 1)
        self.assertFalse(self.file.exists())
        self.assertTrue(self.second.exists())
        self.assertEqual(read_zone(self.destination / self.file.name), ZONE)
        self.assertEqual(read_zone(self.destination / self.second.name), ZONE_OTHER)
        self.assertEqual(read_zone(self.keep), b"unselected marker must survive")
        events = [json.loads(line) for line in self.journal_path.read_text().splitlines()]
        self.assertEqual(events[-1]["status"], "partial")

    def test_cli_explicit_preservation_flag(self):
        destination = self.base / "cli-retained"
        plan_path = self.base / "cli-plan.json"
        result = vc.main(["plan", "--source", str(self.source), "--destination", str(destination),
                          "--include", self.file.name, "--preserve-zone-identifier", "--output", str(plan_path)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(plan_path.read_text())["schema_version"], 3)


if __name__ == "__main__":
    unittest.main()
