#!/usr/bin/env python3
"""Review and run an owning application's cache cleanup, without downloads.

First adapter: existing pip 25.3. Fixed purge command, isolated configuration,
explicit cache scope, bounded metadata snapshot, separate approval and receipt.
Not an uninstaller or a general AppData/orphan cleaner. Close cache writers first.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import verified_copy as vc

ADAPTER = 'pip-cache-purge-25.3'
SUPPORTED_PIP = '25.3'
MAX_ENTRIES = 100000
MAX_OUTPUT = 2 * 1024 * 1024


def child_environment():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PIP_')}
    env['PIP_CONFIG_FILE'] = os.devnull
    return env


def run_child(arguments, timeout=120):
    completed = subprocess.run(arguments, shell=False, env=child_environment(),
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if len(completed.stdout) + len(completed.stderr) > MAX_OUTPUT:
        raise vc.CopyError('Application output exceeded limit; inspect the reserved receipt before retrying')
    return completed


def python_command():
    return [str(Path(sys.executable).resolve(strict=True)), '-B', '-I', '-X', 'utf8']


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def runtime():
    # This executes the existing trusted interpreter/module, not any path or
    # command supplied by a plan. -I prevents working-directory import shadowing.
    probe = ("import json,sys,pip; import pip._internal.commands.cache as c; "
             "import pip._internal.utils.filesystem as f; "
             "print(json.dumps({'pip_version':pip.__version__,'python_version':sys.version,"
             "'module_paths':[pip.__file__,c.__file__,f.__file__]}))")
    result = run_child(python_command() + ['-c', probe])
    if result.returncode:
        raise vc.CopyError('Existing interpreter cannot load pip; no installation was attempted')
    data = json.loads(result.stdout)
    if data.get('pip_version') != SUPPORTED_PIP:
        raise vc.CopyError(f'This tested adapter supports pip {SUPPORTED_PIP}; found {data.get("pip_version")}. No upgrade/downgrade is performed.')
    modules = []
    for filename in data['module_paths']:
        path = Path(filename).resolve(strict=True)
        modules.append({'path': str(path), 'sha256': sha256(path)})
    executable = python_command()[0]
    return {'python': executable, 'python_sha256': sha256(executable),
            'python_version': data['python_version'], 'pip_version': data['pip_version'], 'modules': modules}


def pip_command(root, operation):
    if operation not in ('dir', 'purge'):
        raise vc.CopyError('Unsupported pip operation')
    command = python_command() + ['-m', 'pip', '--isolated', '--disable-pip-version-check', '--no-input', '--no-color']
    if root is not None:
        command += ['--cache-dir', str(root)]
    return command + ['cache', operation]


def discover():
    tool = runtime()
    result = run_child(pip_command(None, 'dir'))
    if result.returncode:
        raise vc.CopyError('pip could not report its isolated default cache directory')
    root = vc.absolute(result.stdout.strip())
    return {'adapter': ADAPTER, 'cache_dir': str(root), 'exists': root.is_dir(), 'tool': tool,
            'discovery': 'isolated_default',
            'limitation': 'PIP_* and configuration files are ignored; this is not necessarily your custom active cache.'}


def check_cache_root(root):
    vc.check_ancestors(root)
    actual = root.resolve(strict=True)
    if actual == Path(actual.anchor) or actual == Path.home().resolve():
        raise vc.CopyError('A drive root or user profile is not an acceptable cache root')
    if os.name == 'nt':
        for name in ('SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData'):
            value = os.environ.get(name)
            if value and vc.contained(actual, vc.absolute(value).resolve()):
                raise vc.CopyError(f'Protected system root is not an acceptable pip cache: {name}')
        for name in ('APPDATA', 'LOCALAPPDATA', 'USERPROFILE'):
            value = os.environ.get(name)
            if value and actual == vc.absolute(value).resolve():
                raise vc.CopyError('Choose the exact pip cache, not its profile/AppData parent')
    vc.check_streams(root)
    return actual


def is_candidate(relative):
    parts = relative.split('/')
    # Windows resolves named subroots without case sensitivity; Unix does not.
    subroot = os.path.normcase(parts[0])
    return len(parts) > 1 and (subroot in ('http', 'http-v2') or
                               subroot == 'wheels' and fnmatch.fnmatch(parts[-1], '*-*.whl'))


def metadata(path, info, relative):
    return {'path': relative, 'device': info.st_dev, 'inode': info.st_ino,
            'size': info.st_size, 'mtime_ns': info.st_mtime_ns}


def inspect_cache(root):
    root = vc.absolute(root)
    actual = check_cache_root(root)
    root_info = root.lstat()
    files, directories, pending = [], [], [root]
    count = 0
    while pending:
        directory = pending.pop()
        vc.check_ancestors(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise vc.CopyError('Cache inventory exceeds entry limit; no cleanup plan was produced')
                path = directory / entry.name
                relative = vc.relative_name(path.relative_to(root).as_posix())
                info = path.lstat()
                vc.check_attributes(path, info)
                if info.st_dev != root_info.st_dev:
                    raise vc.CopyError('Cache crosses a volume boundary')
                if stat.S_ISDIR(info.st_mode):
                    vc.check_streams(path)
                    directories.append(metadata(path, info, relative))
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    vc.checked_file(path)  # Reject hardlinks, streams, special files.
                    files.append({**metadata(path, info, relative), 'selected': is_candidate(relative)})
                else:
                    raise vc.CopyError(f'Special file in cache: {relative}')
    files.sort(key=lambda item: item['path'])
    directories.sort(key=lambda item: item['path'])
    return {'root_identity': {'path': str(actual), 'device': root_info.st_dev, 'inode': root_info.st_ino},
            'files': files, 'directories': directories,
            'candidate_files': sum(item['selected'] for item in files),
            'candidate_logical_bytes': sum(item['size'] for item in files if item['selected'])}


def output_path(value, cache):
    vc.relative_name(os.path.basename(os.fspath(value)))
    output = vc.absolute(value)
    vc.check_ancestors(output.parent)
    if vc.contained(output.parent.resolve(strict=True) / output.name, cache.resolve(strict=True)):
        raise vc.CopyError('Plans and receipts must be outside the cache root')
    return output


def make_plan(output, cache_dir=None):
    if cache_dir is None:
        discovered = discover()
        tool, cache, discovery = discovered['tool'], vc.absolute(discovered['cache_dir']), 'isolated_default'
    else:
        tool, cache, discovery = runtime(), vc.absolute(cache_dir), 'explicit_override_ownership_requires_user_confirmation'
    snapshot = inspect_cache(cache)
    if not snapshot['candidate_files']:
        raise vc.CopyError('No wheel/HTTP cache files matched; no cleanup is needed')
    output = output_path(output, cache)
    payload = {'schema_version': 1, 'kind': 'disk-steward-app-cache-plan', 'adapter': ADAPTER,
               'operation': 'pip-cache-purge', 'cache_dir': str(cache), 'tool': tool, 'snapshot': snapshot,
               'discovery': discovery, 'created_at': vc.utc_now(),
               'consequences': 'Removes wheel/HTTP caches, not installed packages. Later installs may need network/builds; cached offline reinstalls may be lost. No undo.',
               'scope': 'All pip wheel and HTTP cache entries under this root; close all cache writers before approval.'}
    plan = {**payload, 'plan_id': vc.canonical_id(payload)}
    if len(json.dumps(plan).encode('utf-8')) > 16 * 1024 * 1024:
        raise vc.CopyError('Cache plan is too large to review; no cleanup performed')
    with output.open('x', encoding='utf-8') as stream:
        vc.write_json(stream, plan)
    return plan


def validate_plan(plan, approval):
    keys = {'schema_version', 'kind', 'adapter', 'operation', 'cache_dir', 'tool', 'snapshot', 'discovery', 'created_at', 'consequences', 'scope', 'plan_id'}
    if not isinstance(plan, dict) or set(plan) != keys or type(plan['schema_version']) is not int or plan['schema_version'] != 1 or plan['kind'] != 'disk-steward-app-cache-plan' or plan['adapter'] != ADAPTER or plan['operation'] != 'pip-cache-purge':
        raise vc.CopyError('Unsupported application cleanup plan')
    if not all(isinstance(plan[k], str) for k in ('cache_dir', 'discovery', 'created_at', 'consequences', 'scope', 'plan_id')):
        raise vc.CopyError('Invalid application cleanup plan fields')
    if vc.canonical_id({k: v for k, v in plan.items() if k != 'plan_id'}) != plan['plan_id'] or approval != plan['plan_id']:
        raise vc.CopyError('Cleanup plan changed or exact approval is missing')
    cache = vc.absolute(plan['cache_dir'])
    if str(cache) != plan['cache_dir']:
        raise vc.CopyError('Cache path must be canonical and absolute')
    return cache


def apply_plan(plan_path, approval, receipt_path):
    plan = vc.load_plan(plan_path)
    cache = validate_plan(plan, approval)
    check_cache_root(cache)
    receipt_path = output_path(receipt_path, cache)
    result = {'kind': 'disk-steward-app-cache-receipt', 'plan_id': plan['plan_id'], 'adapter': ADAPTER,
              'cache_dir': str(cache), 'status': 'failed', 'command_started': False,
              'observed_removed_files': 0, 'observed_removed_logical_bytes': 0,
              'free_before_bytes': None, 'free_after_bytes': None, 'observed_free_delta_bytes': None}
    with receipt_path.open('x', encoding='utf-8') as stream:
        vc.write_json(stream, {**result, 'status': 'in_progress'})
        try:
            if runtime() != plan['tool']:
                raise vc.CopyError('Interpreter or pip changed; create a new cleanup plan')
            before = inspect_cache(cache)
            if before != plan['snapshot']:
                raise vc.CopyError('Cache changed since planning; create and review a new plan')
            result['free_before_bytes'] = shutil.disk_usage(cache).free
            command = pip_command(cache, 'purge')  # Never execute argv from JSON.
            result.update(command_started=True, command=command)
            stream.seek(0)
            stream.truncate()
            vc.write_json(stream, {**result, 'status': 'command_pending'})
            completed = run_child(command)
            result.update(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
            after = inspect_cache(cache)
            remaining = {item['path']: item for item in after['files']}
            removed = [item for item in before['files'] if item['path'] not in remaining]
            result['observed_removed_files'] = len(removed)
            result['observed_removed_logical_bytes'] = sum(item['size'] for item in removed)
            unselected_changes = [item['path'] for item in before['files'] if not item['selected'] and remaining.get(item['path']) != item]
            result['unexpected_unselected_changes'] = unselected_changes
            result['remaining_candidate_files'] = after['candidate_files']
            result['status'] = 'complete' if completed.returncode == 0 and not after['candidate_files'] and not unselected_changes else 'partial_or_failed'
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            result['error'] = str(error)
            result['status'] = 'partial_or_failed' if result['command_started'] else 'failed'
        except KeyboardInterrupt:
            result.update(error='Interrupted; inspect the cache and receipt before any retry', status='partial_or_failed' if result['command_started'] else 'failed')
        try:
            result['free_after_bytes'] = shutil.disk_usage(cache).free
            if result['free_before_bytes'] is not None:
                result['observed_free_delta_bytes'] = result['free_after_bytes'] - result['free_before_bytes']
        except OSError as error:
            result['measurement_error'] = str(error)
        result['finished_at'] = vc.utc_now()
        stream.seek(0)
        stream.truncate()
        vc.write_json(stream, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('discover', help='Report isolated pip default cache; ignores custom user configuration')
    planning = commands.add_parser('plan', help='Plan a pip-owned cache purge; no deletion')
    planning.add_argument('--cache-dir', help='Explicit confirmed custom cache; override alone does not prove ownership')
    planning.add_argument('--output', required=True)
    applying = commands.add_parser('apply', help='Run the fixed purge command after exact-scope approval')
    applying.add_argument('--plan', required=True)
    applying.add_argument('--approve', required=True)
    applying.add_argument('--receipt', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'discover':
            result = discover()
        elif args.command == 'plan':
            plan = make_plan(args.output, args.cache_dir)
            result = {'plan_id': plan['plan_id'], 'cache_dir': plan['cache_dir'], 'discovery': plan['discovery'],
                      'candidate_files': plan['snapshot']['candidate_files'], 'candidate_logical_bytes': plan['snapshot']['candidate_logical_bytes']}
        else:
            result = apply_plan(args.plan, args.approve, args.receipt)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if args.command != 'apply' or result['status'] == 'complete' else 2
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
