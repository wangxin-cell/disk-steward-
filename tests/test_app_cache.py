"""Pip cache adapter checks use only synthetic cache trees in this repository."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/disk-steward/scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    import app_cache as cache
finally:
    sys.path.pop(0)


class CacheFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.app-cache-test-', dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'pip-cache'
        self.root.mkdir()
        self.http = self.root / 'http-v2/ab/cd/response'
        self.body = self.root / 'http-v2/ab/cd/response.body'
        self.wheel = self.root / 'wheels/ab/cd/demo-1.0-py3-none-any.whl'
        self.origin = self.root / 'wheels/ab/cd/origin.json'
        self.nonmatching_wheel = self.root / 'wheels/ab/cd/note.whl'
        for path, data in ((self.http, b'fake cached headers'), (self.body, b'fake cached response'),
                           (self.wheel, b'fake cached wheel'), (self.origin, b'{"url":"fixture"}'),
                           (self.nonmatching_wheel, b'no hyphen: pip purge retains this file')):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.outside = self.base / 'outside.txt'
        self.outside.write_bytes(b'outside cache must survive')
        self.output = self.base / 'cache-plan.json'
        self.receipt = self.base / 'cache-receipt.json'

    def plan(self):
        return cache.make_plan(self.output, cache_dir=self.root)

    def assert_candidates_exist(self):
        for path in (self.http, self.body, self.wheel):
            self.assertTrue(path.is_file(), path)
        self.assertEqual(self.origin.read_bytes(), b'{"url":"fixture"}')
        self.assertEqual(self.nonmatching_wheel.read_bytes(), b'no hyphen: pip purge retains this file')
        self.assertEqual(self.outside.read_bytes(), b'outside cache must survive')


class CacheInventoryTests(CacheFixture):
    def test_metadata_inventory_distinguishes_candidates_from_origin(self):
        inspected = cache.inspect_cache(self.root)
        self.assertEqual(inspected['candidate_files'], 3)
        self.assertEqual(inspected['candidate_logical_bytes'],
                         sum(path.stat().st_size for path in (self.http, self.body, self.wheel)))
        entries = {entry['path']: entry for entry in inspected['files']}
        self.assertTrue(entries[self.http.relative_to(self.root).as_posix()]['selected'])
        self.assertTrue(entries[self.wheel.relative_to(self.root).as_posix()]['selected'])
        self.assertFalse(entries[self.origin.relative_to(self.root).as_posix()]['selected'])
        self.assertFalse(entries[self.nonmatching_wheel.relative_to(self.root).as_posix()]['selected'])
        self.assertNotIn('outside.txt', entries)
        self.assert_candidates_exist()

    def test_missing_cache_is_rejected_without_creation(self):
        missing = self.base / 'missing-cache'
        with self.assertRaises((ValueError, OSError)):
            cache.inspect_cache(missing)
        self.assertFalse(missing.exists())

    def test_regular_file_is_not_a_cache_root(self):
        with self.assertRaises((ValueError, OSError)):
            cache.inspect_cache(self.outside)
        self.assert_candidates_exist()

    def test_hardlinked_candidate_is_rejected(self):
        try:
            os.link(self.http, self.base / 'linked-response')
        except OSError:
            self.skipTest('Actual hardlink creation unavailable')
        with self.assertRaises((ValueError, OSError)):
            cache.inspect_cache(self.root)
        self.assert_candidates_exist()

    def test_linked_cache_root_is_rejected(self):
        linked = self.base / 'linked-cache'
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Actual symlink creation unavailable')
        with self.assertRaises((ValueError, OSError)):
            cache.inspect_cache(linked)
        self.assert_candidates_exist()

    def test_linked_descendant_is_rejected(self):
        linked = self.root / 'http-v2/linked-file'
        try:
            linked.symlink_to(self.outside)
        except OSError:
            self.skipTest('Actual symlink creation unavailable')
        with self.assertRaises((ValueError, OSError)):
            cache.inspect_cache(self.root)
        self.assert_candidates_exist()

    def test_reparse_root_metadata_is_rejected_without_link_privilege(self):
        original = Path.lstat

        def reparse(path, *args, **kwargs):
            if path == self.root:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'lstat', reparse), self.assertRaises(ValueError):
            cache.inspect_cache(self.root)
        self.assert_candidates_exist()

    def test_hardlink_metadata_is_rejected_without_link_privilege(self):
        original = Path.lstat
        actual = self.http.stat()
        hardlinked = SimpleNamespace(st_mode=actual.st_mode, st_dev=actual.st_dev,
                                     st_ino=actual.st_ino, st_size=actual.st_size,
                                     st_mtime_ns=actual.st_mtime_ns, st_nlink=2,
                                     st_file_attributes=0)

        def lstat(path, *args, **kwargs):
            return hardlinked if path == self.http else original(path, *args, **kwargs)

        with patch.object(Path, 'lstat', lstat), self.assertRaises(ValueError):
            cache.inspect_cache(self.root)
        self.assert_candidates_exist()

    def test_profile_root_is_rejected_before_enumeration(self):
        # Substitute a fixture for the profile: never inspect the real home.
        with patch.object(Path, 'home', return_value=self.root), \
                patch.object(cache.os, 'scandir', side_effect=AssertionError('Entered profile root')), \
                self.assertRaises(ValueError):
            cache.inspect_cache(self.root)

    def test_inventory_budget_bounds_directory_traversal(self):
        with patch.object(cache, 'MAX_ENTRIES', 1), self.assertRaises(ValueError):
            cache.inspect_cache(self.root)
        self.assert_candidates_exist()

    def test_legacy_http_entries_are_candidates(self):
        legacy = self.root / 'http/response'
        legacy.parent.mkdir()
        legacy.write_bytes(b'legacy cache')
        inspected = cache.inspect_cache(self.root)
        self.assertEqual(inspected['candidate_files'], 4)
        self.assertTrue(next(item for item in inspected['files'] if item['path'] == 'http/response')['selected'])

    @unittest.skipUnless(os.name == 'nt', 'Windows case-insensitive named subroots')
    def test_uppercase_subroots_match_windows_pip_scope(self):
        (self.root / 'http-v2').rename(self.root / 'http-intermediate')
        (self.root / 'http-intermediate').rename(self.root / 'HTTP-V2')
        (self.root / 'wheels').rename(self.root / 'wheels-intermediate')
        (self.root / 'wheels-intermediate').rename(self.root / 'WHEELS')
        inspected = cache.inspect_cache(self.root)
        self.assertEqual(inspected['candidate_files'], 3)
        self.assertEqual(sum(item['selected'] for item in inspected['files']), 3)


class CachePlanTests(CacheFixture):
    def setUp(self):
        super().setUp()
        self.tool = {'python': str(Path(sys.executable).resolve()), 'python_sha256': '0' * 64,
                     'python_version': 'unit-test-runtime', 'pip_version': '25.3', 'modules': []}
        patcher = patch.object(cache, 'runtime', return_value=self.tool)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, plan, resign=False):
        if resign:
            plan['plan_id'] = cache.vc.canonical_id({key: value for key, value in plan.items() if key != 'plan_id'})
        self.output.write_text(json.dumps(plan), encoding='utf-8')

    def test_plan_is_read_only_and_records_explicit_cache_scope(self):
        with patch.object(cache, 'run_child', side_effect=AssertionError('No child needed after runtime check')):
            plan = self.plan()
        self.assertEqual(plan['adapter'], 'pip-cache-purge-25.3')
        self.assertEqual(plan['cache_dir'], str(self.root))
        self.assertEqual(plan['snapshot']['candidate_files'], 3)
        self.assertIn('explicit', plan['discovery'])
        self.assert_candidates_exist()

    def test_no_candidates_produces_no_plan(self):
        empty = self.base / 'empty-cache'
        empty.mkdir()
        with self.assertRaises(ValueError):
            cache.make_plan(self.output, cache_dir=empty)
        self.assertFalse(self.output.exists())

    def test_wrong_approval_never_starts_child(self):
        self.plan()
        with patch.object(cache, 'run_child', side_effect=AssertionError('Unauthorized child')), self.assertRaises(ValueError):
            cache.apply_plan(self.output, 'yes', self.receipt)
        self.assertFalse(self.receipt.exists())
        self.assert_candidates_exist()

    def test_tampered_plan_never_starts_child(self):
        plan = self.plan()
        plan['cache_dir'] = str(self.base)
        self.save(plan)
        with patch.object(cache, 'run_child', side_effect=AssertionError('Tampered child')), self.assertRaises(ValueError):
            cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assert_candidates_exist()

    def test_resigned_extra_argv_is_rejected_not_executed(self):
        plan = self.plan()
        plan['argv'] = ['fixture-malicious-command', str(self.outside)]
        self.save(plan, resign=True)
        with patch.object(cache, 'run_child', side_effect=AssertionError('Plan-supplied argv executed')), self.assertRaises(ValueError):
            cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assert_candidates_exist()

    def test_existing_output_is_not_overwritten(self):
        self.output.write_text('preserve existing plan', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.plan()
        self.assertEqual(self.output.read_text(), 'preserve existing plan')
        self.assert_candidates_exist()

    def test_existing_receipt_is_not_overwritten(self):
        plan = self.plan()
        self.receipt.write_text('preserve existing receipt', encoding='utf-8')
        with patch.object(cache, 'run_child', side_effect=AssertionError('Child before journal reserve')), self.assertRaises(FileExistsError):
            cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(self.receipt.read_text(), 'preserve existing receipt')
        self.assert_candidates_exist()

    def test_outputs_inside_cache_are_rejected(self):
        with self.assertRaises(ValueError):
            cache.make_plan(self.root / 'plan.json', cache_dir=self.root)
        self.assertFalse((self.root / 'plan.json').exists())
        plan = self.plan()
        with self.assertRaises(ValueError):
            cache.apply_plan(self.output, plan['plan_id'], self.root / 'receipt.json')
        self.assertFalse((self.root / 'receipt.json').exists())
        self.assert_candidates_exist()

    def test_output_and_receipt_ads_aliases_are_rejected(self):
        output_ads = str(self.outside) + ':plan.json'
        with self.assertRaises(ValueError):
            cache.make_plan(output_ads, cache_dir=self.root)
        plan = self.plan()
        receipt_ads = str(self.outside) + ':receipt.json'
        with self.assertRaises(ValueError):
            cache.apply_plan(self.output, plan['plan_id'], receipt_ads)
        self.assertFalse(os.path.lexists(output_ads))
        self.assertFalse(os.path.lexists(receipt_ads))
        self.assert_candidates_exist()

    def test_changed_candidate_snapshot_blocks_purge(self):
        plan = self.plan()
        self.http.write_bytes(b'changed after approval planning')
        with patch.object(cache, 'run_child', side_effect=AssertionError('Stale snapshot executed')):
            result = cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(result['status'], 'failed', result)
        self.assertFalse(result['command_started'])
        self.assert_candidates_exist()

    def test_replaced_cache_root_blocks_purge(self):
        plan = self.plan()
        old_root = self.base / 'original-cache'
        self.assertTrue(self.root.resolve().is_relative_to(self.base))
        self.root.rename(old_root)
        shutil.copytree(old_root, self.root)
        with patch.object(cache, 'run_child', side_effect=AssertionError('Replaced cache root executed')):
            result = cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(result['status'], 'failed', result)
        self.assertFalse(result['command_started'])
        self.assert_candidates_exist()

    def test_tool_version_drift_blocks_purge(self):
        plan = self.plan()
        changed_tool = {**self.tool, 'pip_version': 'unsupported-fixture-version'}
        with patch.object(cache, 'runtime', return_value=changed_tool), \
                patch.object(cache, 'run_child', side_effect=AssertionError('Changed tool executed')):
            result = cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(result['status'], 'failed', result)
        self.assertFalse(result['command_started'])
        self.assert_candidates_exist()

    def test_failed_child_is_audited_and_fixed_command_is_used(self):
        plan = self.plan()
        completed = subprocess.CompletedProcess([], 1, 'fixture output', 'fixture failure')
        with patch.object(cache, 'run_child', return_value=completed) as run:
            result = cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(result['status'], 'partial_or_failed', result)
        self.assertTrue(result['command_started'])
        self.assertEqual(result['observed_removed_files'], 0)
        self.assertEqual(result['returncode'], 1)
        self.assertEqual(result['stderr'], 'fixture failure')
        run.assert_called_once_with(cache.pip_command(self.root, 'purge'))
        argv = run.call_args.args[0]
        self.assertEqual(argv[-2:], ['cache', 'purge'])
        self.assertEqual(argv[argv.index('--cache-dir') + 1], str(self.root))
        self.assertEqual(json.loads(self.receipt.read_text())['status'], 'partial_or_failed')
        self.assert_candidates_exist()

    def test_child_timeout_keeps_a_receipt_and_does_not_retry(self):
        plan = self.plan()
        with patch.object(cache, 'run_child', side_effect=subprocess.TimeoutExpired('fixture-child', 1)) as run:
            result = cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(result['status'], 'partial_or_failed', result)
        run.assert_called_once()
        self.assertTrue(self.receipt.is_file())
        self.assert_candidates_exist()


class CacheRuntimeTests(unittest.TestCase):
    def test_pip_environment_overrides_are_removed_and_config_disabled(self):
        with patch.dict(os.environ, {'PIP_CACHE_DIR': 'fixture-only', 'PIP_INDEX_URL': 'fixture-only', 'PIP_CONFIG_FILE': 'fixture-only'}):
            env = cache.child_environment()
        self.assertNotIn('PIP_CACHE_DIR', env)
        self.assertNotIn('PIP_INDEX_URL', env)
        self.assertEqual(env['PIP_CONFIG_FILE'], os.devnull)

    def test_unsupported_installed_pip_is_rejected_without_installing(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps({'pip_version': 'unsupported-fixture-version'}), '')
        with patch.object(cache, 'run_child', return_value=completed) as run, self.assertRaises(ValueError):
            cache.runtime()
        run.assert_called_once()
        self.assertIn('-I', run.call_args.args[0])
        self.assertIn('-c', run.call_args.args[0])


class ExistingPipIntegrationTests(CacheFixture):
    @classmethod
    def setUpClass(cls):
        try:
            detected = cache.runtime()  # Version/module probe only; no cache discovery.
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            raise unittest.SkipTest(f'Existing trusted pip 25.3 unavailable: {error}')
        if detected['pip_version'] != '25.3':
            raise unittest.SkipTest('Native integration requires already installed pip 25.3')

    def test_actual_pip_purge_only_removes_fixture_candidates(self):
        plan = self.plan()
        expected_bytes = sum(path.stat().st_size for path in (self.http, self.body, self.wheel))
        result = cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['observed_removed_files'], 3)
        self.assertEqual(result['observed_removed_logical_bytes'], expected_bytes)
        for path in (self.http, self.body, self.wheel):
            self.assertFalse(path.exists(), path)
        self.assertEqual(self.origin.read_bytes(), b'{"url":"fixture"}')
        self.assertEqual(self.nonmatching_wheel.read_bytes(), b'no hyphen: pip purge retains this file')
        self.assertEqual(self.outside.read_bytes(), b'outside cache must survive')
        self.assertEqual(result['unexpected_unselected_changes'], [])
        self.assertEqual(json.loads(self.receipt.read_text())['status'], 'complete')

    @unittest.skipUnless(os.name == 'nt', 'Windows case-insensitive named subroots')
    def test_actual_pip_purge_uppercase_subroots_matches_inventory(self):
        (self.root / 'http-v2').rename(self.root / 'http-intermediate')
        (self.root / 'http-intermediate').rename(self.root / 'HTTP-V2')
        (self.root / 'wheels').rename(self.root / 'wheels-intermediate')
        (self.root / 'wheels-intermediate').rename(self.root / 'WHEELS')
        plan = self.plan()
        self.assertEqual(plan['snapshot']['candidate_files'], 3)
        result = cache.apply_plan(self.output, plan['plan_id'], self.receipt)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['observed_removed_files'], 3)
        self.assertEqual(self.origin.read_bytes(), b'{"url":"fixture"}')
        self.assertEqual(self.nonmatching_wheel.read_bytes(), b'no hyphen: pip purge retains this file')
        self.assertEqual(self.outside.read_bytes(), b'outside cache must survive')


if __name__ == '__main__':
    unittest.main()
