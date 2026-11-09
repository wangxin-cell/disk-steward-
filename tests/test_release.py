"""Source removal tests use only isolated disposable files created here."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/disk-steward/scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    import source_release as release
finally:
    sys.path.pop(0)
vc = release.vc


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.release-test-', dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).absolute()
        self.source = self.base / 'source'
        self.source.mkdir()
        (self.source / 'nested').mkdir()
        (self.source / 'a.txt').write_bytes(b'first disposable file')
        (self.source / 'nested/b.txt').write_bytes(b'second disposable file')
        (self.source / 'keep.txt').write_bytes(b'unselected source must survive')
        self.destination = self.base / 'retained'
        self.copy_plan_path = self.base / 'copy-plan.json'
        self.copy_receipt_path = self.base / 'copy-receipt.json'
        self.release_path = self.base / 'release-plan.json'
        self.journal_path = self.base / 'release-receipt.jsonl'
        self.copy_plan = vc.make_plan(self.source, self.destination, self.copy_plan_path,
                                     include=['a.txt', 'nested/b.txt'])
        receipt = vc.apply_plan(self.copy_plan_path, self.copy_plan['plan_id'], self.copy_receipt_path)
        self.assertEqual(receipt['status'], 'verified', receipt)

    def plan(self):
        return release.make_plan(self.copy_plan_path, self.copy_receipt_path, self.release_path)

    def apply(self, plan):
        return release.apply_plan(self.release_path, plan['plan_id'], self.journal_path)

    def events(self):
        return [json.loads(line) for line in self.journal_path.read_text().splitlines()]

    def whole_tree_plan(self, legacy=False):
        # Fresh artifacts keep the selected-copy setup intact and avoid any
        # overwrite/deletion of prior fixture evidence during test preparation.
        (self.source / 'empty').mkdir()
        self.destination = self.base / 'retained-tree'
        self.copy_plan_path = self.base / 'copy-tree-plan.json'
        self.copy_receipt_path = self.base / 'copy-tree-receipt.json'
        self.copy_plan = vc.make_plan(self.source, self.destination, self.copy_plan_path)
        if legacy:
            self.copy_plan['schema_version'] = 1
            self.copy_plan.pop('scope')
            self.copy_plan.pop('selected_paths')
            self.copy_plan['plan_id'] = vc.canonical_id(
                {k: v for k, v in self.copy_plan.items() if k != 'plan_id'})
            self.copy_plan_path.write_text(json.dumps(self.copy_plan), encoding='utf-8')
        receipt = vc.apply_plan(self.copy_plan_path, self.copy_plan['plan_id'], self.copy_receipt_path)
        self.assertEqual(receipt['status'], 'verified', receipt)
        return self.plan()

    def test_release_plan_rechecks_target_content(self):
        (self.destination / 'a.txt').write_bytes(b'damaged')
        with self.assertRaises(vc.CopyError):
            self.plan()
        self.assertFalse(self.release_path.exists())
        self.assertTrue((self.source / 'a.txt').exists())

    def test_release_requires_matching_verified_copy_receipt(self):
        receipt = json.loads(self.copy_receipt_path.read_text())
        receipt['status'] = 'partial'
        self.copy_receipt_path.write_text(json.dumps(receipt))
        with self.assertRaises(vc.CopyError):
            self.plan()

    def test_malformed_copy_json_is_rejected_cleanly(self):
        self.copy_plan_path.write_text('[]')
        with self.assertRaises(vc.CopyError):
            self.plan()
        self.assertFalse(self.release_path.exists())

    def test_release_id_differs_from_copy_and_rejects_copy_approval(self):
        plan = self.plan()
        self.assertNotEqual(plan['plan_id'], self.copy_plan['plan_id'])
        with self.assertRaises(vc.CopyError):
            release.validate_plan(plan, self.copy_plan['plan_id'])

    def test_outer_tampering_rejected(self):
        plan = self.plan()
        plan['copy_plan']['files'][0]['path'] = '../outside.txt'
        with self.assertRaises(vc.CopyError):
            release.validate_plan(plan, plan['plan_id'])

    def test_resigned_traversal_rejected_by_schema(self):
        plan = self.plan()
        plan['copy_plan']['files'][0]['path'] = '../outside.txt'
        plan['copy_plan']['plan_id'] = vc.canonical_id({k: v for k, v in plan['copy_plan'].items() if k != 'plan_id'})
        plan['plan_id'] = vc.canonical_id({k: v for k, v in plan.items() if k != 'plan_id'})
        with self.assertRaises(vc.CopyError):
            release.validate_plan(plan, plan['plan_id'])

    def test_nonwindows_apply_fails_without_deletion_fallback(self):
        with patch.object(release.os, 'name', 'posix'):
            with self.assertRaises(vc.CopyError):
                release.require_windows()

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_selected_files_removed_but_siblings_and_directories_retained(self):
        plan = self.plan()
        result = self.apply(plan)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['deleted_files'], 2)
        self.assertFalse((self.source / 'a.txt').exists())
        self.assertFalse((self.source / 'nested/b.txt').exists())
        self.assertTrue((self.source / 'nested').is_dir())
        self.assertEqual((self.source / 'keep.txt').read_bytes(), b'unselected source must survive')
        self.assertEqual((self.destination / 'a.txt').read_bytes(), b'first disposable file')
        self.assertEqual(self.events()[-1]['status'], 'complete')
        self.assertEqual([x['event'] for x in self.events()].count('deleted'), 2)
        self.assertIsInstance(result['observed_free_delta_bytes'], int)

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_whole_tree_v2_release_preserves_all_directories_and_copy_bytes(self):
        plan = self.whole_tree_plan()
        self.assertEqual(plan['copy_plan']['schema_version'], 2)
        self.assertEqual(plan['copy_plan']['scope'], 'tree')
        result = self.apply(plan)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['deleted_files'], 3)
        for item in self.copy_plan['files']:
            self.assertFalse((self.source / item['path']).exists())
            self.assertEqual(vc.fingerprint(self.destination / item['path'])['sha256'], item['sha256'])
        self.assertTrue((self.source / 'nested').is_dir())
        self.assertTrue((self.source / 'empty').is_dir())
        self.assertEqual(self.events()[-1]['status'], 'complete')

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_legacy_v1_whole_tree_release_is_supported(self):
        plan = self.whole_tree_plan(legacy=True)
        self.assertEqual(plan['copy_plan']['schema_version'], 1)
        self.assertNotIn('scope', plan['copy_plan'])
        result = self.apply(plan)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['deleted_files'], 3)
        self.assertFalse((self.source / 'a.txt').exists())
        self.assertFalse((self.source / 'nested/b.txt').exists())
        self.assertFalse((self.source / 'keep.txt').exists())
        self.assertTrue((self.source / 'nested').is_dir())
        self.assertTrue((self.source / 'empty').is_dir())
        self.assertEqual((self.destination / 'a.txt').read_bytes(), b'first disposable file')
        self.assertEqual((self.destination / 'nested/b.txt').read_bytes(), b'second disposable file')

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_new_source_file_after_whole_tree_plan_blocks_all_deletions(self):
        plan = self.whole_tree_plan()
        (self.source / 'new.txt').write_bytes(b'not part of the approved tree snapshot')
        result = self.apply(plan)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['deleted_files'], 0)
        for item in self.copy_plan['files']:
            self.assertTrue((self.source / item['path']).is_file())
        self.assertEqual((self.source / 'new.txt').read_bytes(), b'not part of the approved tree snapshot')

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_changed_source_blocks_all_deletions(self):
        plan = self.plan()
        (self.source / 'nested/b.txt').write_bytes(b'new source content')
        result = self.apply(plan)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((self.source / 'a.txt').exists())
        self.assertTrue((self.source / 'nested/b.txt').exists())
        self.assertEqual(result['deleted_files'], 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_changed_target_with_restored_mtime_blocks_all_deletions(self):
        plan = self.plan()
        path = self.destination / 'a.txt'
        before = path.stat()
        path.write_bytes(b'x' * before.st_size)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        result = self.apply(plan)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['deleted_files'], 0)
        self.assertTrue((self.source / 'a.txt').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_identical_retained_replacement_with_new_identity_blocks_deletion(self):
        plan = self.plan()
        path = self.destination / 'a.txt'
        before, contents = path.stat(), path.read_bytes()
        # Keep the old inode alive outside the retained tree to ensure a distinct
        # replacement, without making extra files part of the destination scan.
        path.rename(self.base / 'original-retained.txt')
        path.write_bytes(contents)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertNotEqual(path.stat().st_ino, before.st_ino)
        self.assertEqual(path.read_bytes(), contents)
        result = self.apply(plan)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['deleted_files'], 0)
        self.assertEqual((self.source / 'a.txt').read_bytes(), b'first disposable file')
        self.assertTrue((self.source / 'nested/b.txt').is_file())

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_resigned_retained_identity_tamper_blocks_deletion(self):
        plan = self.plan()
        plan['retained_files'][0]['inode'] += 1
        plan['plan_id'] = vc.canonical_id({k: v for k, v in plan.items() if k != 'plan_id'})
        self.release_path.write_text(json.dumps(plan), encoding='utf-8')
        result = self.apply(plan)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['deleted_files'], 0)
        self.assertEqual((self.source / 'a.txt').read_bytes(), b'first disposable file')
        self.assertTrue((self.source / 'nested/b.txt').is_file())

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_existing_journal_is_not_overwritten(self):
        plan = self.plan()
        self.journal_path.write_text('preserve this journal')
        with self.assertRaises(FileExistsError):
            self.apply(plan)
        self.assertEqual(self.journal_path.read_text(), 'preserve this journal')
        self.assertTrue((self.source / 'a.txt').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_failure_on_second_file_leaves_partial_auditable_progress(self):
        plan = self.plan()
        original = release.mark_for_deletion
        calls = []

        def fail_second(stream):
            calls.append(stream)
            if len(calls) == 2:
                raise PermissionError('injected failure before second deletion')
            return original(stream)

        with patch.object(release, 'mark_for_deletion', side_effect=fail_second):
            result = self.apply(plan)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['deleted_files'], 1)
        self.assertFalse((self.source / 'a.txt').exists())
        self.assertTrue((self.source / 'nested/b.txt').exists())
        self.assertEqual(result['pending_path'], 'nested/b.txt')
        self.assertTrue((self.destination / 'a.txt').exists())
        self.assertTrue((self.destination / 'nested/b.txt').exists())
        self.assertEqual(self.events()[-1]['status'], 'partial')

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_open_source_writer_prevents_deletion(self):
        plan = self.plan()
        with (self.source / 'a.txt').open('r+b'):
            result = self.apply(plan)
        self.assertEqual(result['status'], 'failed', result)
        self.assertTrue((self.source / 'a.txt').exists())
        self.assertEqual(result['deleted_files'], 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_open_retained_writer_prevents_source_deletion(self):
        plan = self.plan()
        with (self.destination / 'a.txt').open('r+b'):
            result = self.apply(plan)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['deleted_files'], 0)
        self.assertEqual((self.source / 'a.txt').read_bytes(), b'first disposable file')
        self.assertTrue((self.source / 'nested/b.txt').is_file())
        self.assertEqual((self.destination / 'a.txt').read_bytes(), b'first disposable file')

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_locked_target_denies_competing_write(self):
        plan = self.plan()
        expected = plan['retained_files'][0]
        path = self.destination / expected['path']
        with release.locked_file(path, expected):
            with self.assertRaises(PermissionError):
                path.open('wb')
        self.assertEqual(path.read_bytes(), b'first disposable file')

    @unittest.skipUnless(os.name == 'nt', 'Windows native release backend')
    def test_ads_added_after_planning_blocks_release(self):
        plan = self.plan()
        try:
            with open(str(self.source / 'a.txt') + ':extra', 'wb') as stream:
                stream.write(b'new information that must not be lost')
        except OSError:
            self.skipTest('ADS creation not supported')
        result = self.apply(plan)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((self.source / 'a.txt').exists())


if __name__ == '__main__':
    unittest.main()
