#!/usr/bin/env python3
"""Separately approve permanent removal of files with a freshly verified copy.

Stream-free plan validation is portable; schema 3 marker handling and actual
removal require native Windows file locking and
delete-by-handle; no path-unlink fallback. Retains all source directories. The
receipt is an append-only JSONL journal, not a single JSON object. No downloads.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

import verified_copy as vc

KIND = 'disk-steward-release-plan'
OPERATION = 'permanent-delete-verified-source-files'


def same_content(files, expected):
    return [vc.content_signature(x) for x in files] == [vc.content_signature(x) for x in expected]


def check_pair(copy_plan):
    if not isinstance(copy_plan, dict):
        raise vc.CopyError('Expected a copy-plan JSON object')
    source, destination = vc.validate_plan(copy_plan, copy_plan.get('plan_id'), require_new_destination=False)
    vc.check_snapshot(source, copy_plan)
    retained, directories = vc.inventory_for_plan(destination, copy_plan)
    if directories != copy_plan['directories'] or not same_content(retained, copy_plan['files']):
        raise vc.CopyError('Retained copy does not match the approved source content')
    return source, destination, retained


def make_plan(copy_plan_path, copy_receipt_path, output):
    copy_plan, receipt = vc.load_plan(copy_plan_path), vc.load_plan(copy_receipt_path)
    source, destination, retained = check_pair(copy_plan)
    if not copy_plan['files']:
        raise vc.CopyError('Nothing to release: the copy plan contains no files')
    if not isinstance(receipt, dict) or receipt.get('kind') != 'disk-steward-copy-receipt' or receipt.get('status') != 'verified':
        raise vc.CopyError('A successful verified-copy receipt is required')
    if (receipt.get('plan_id') != copy_plan['plan_id'] or receipt.get('source') != str(source)
            or receipt.get('destination') != str(destination) or receipt.get('source_preserved') is not True
            or type(receipt.get('verified_files')) is not int or type(receipt.get('verified_bytes')) is not int
            or receipt.get('verified_files') != len(copy_plan['files']) or receipt.get('verified_bytes') != copy_plan['total_bytes']):
        raise vc.CopyError('Copy receipt does not match the copy plan')
    if copy_plan['schema_version'] == 3:
        marker_files = sum(item['zone_identifier'] is not None for item in copy_plan['files'])
        if (type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 3
                or receipt.get('stream_policy') != copy_plan['stream_policy']
                or type(receipt.get('verified_zone_identifier_bytes')) is not int
                or receipt['verified_zone_identifier_bytes'] != copy_plan['zone_identifier_bytes']
                or type(receipt.get('verified_zone_identifier_files')) is not int
                or receipt['verified_zone_identifier_files'] != marker_files):
            raise vc.CopyError('Copy receipt does not match the preserved Zone.Identifier manifest')
    output = vc.external_output(output, source, destination)
    payload = {'schema_version': 1, 'kind': KIND, 'operation': OPERATION,
               'copy_plan': copy_plan, 'retained_files': retained, 'created_at': vc.utc_now(),
               'cross_volume': source.stat().st_dev != destination.stat().st_dev,
               'recovery': 'No Recycle Bin or automatic undo; recover manually from the retained copy.'}
    result = {**payload, 'plan_id': vc.canonical_id(payload)}
    with output.open('x', encoding='utf-8') as stream:
        vc.write_json(stream, result)
    return result


def validate_plan(plan, approval):
    keys = {'schema_version', 'kind', 'operation', 'copy_plan', 'retained_files', 'created_at', 'cross_volume', 'recovery', 'plan_id'}
    if not isinstance(plan, dict) or set(plan) != keys or type(plan['schema_version']) is not int or plan['schema_version'] != 1 or plan['kind'] != KIND or plan['operation'] != OPERATION:
        raise vc.CopyError('Unsupported release plan schema')
    if not all(isinstance(plan[k], str) for k in ('created_at', 'recovery', 'plan_id')) or type(plan['cross_volume']) is not bool:
        raise vc.CopyError('Invalid release plan fields')
    if vc.canonical_id({k: v for k, v in plan.items() if k != 'plan_id'}) != plan['plan_id'] or approval != plan['plan_id']:
        raise vc.CopyError('Release plan changed or explicit release approval is missing')
    copied = plan['copy_plan']
    if not isinstance(copied, dict):
        raise vc.CopyError('Invalid embedded copy plan')
    source, destination = vc.validate_plan(copied, copied.get('plan_id'), require_new_destination=False)
    if not copied['files'] or not isinstance(plan['retained_files'], list) or len(plan['retained_files']) != len(copied['files']):
        raise vc.CopyError('Invalid release file list')
    # Reuse the copy schema validator for every retained fingerprint, including
    # paths/duplicates/types/digests, without trusting receipt text as evidence.
    shadow = {**copied, 'files': plan['retained_files']}
    shadow['plan_id'] = vc.canonical_id({k: v for k, v in shadow.items() if k != 'plan_id'})
    vc.validate_plan(shadow, shadow['plan_id'], require_new_destination=False)
    if not same_content(plan['retained_files'], copied['files']):
        raise vc.CopyError('Release and retained-file manifests disagree')
    if (source.stat().st_dev != destination.stat().st_dev) != plan['cross_volume']:
        raise vc.CopyError('Source or destination volume changed since release planning')
    return source, destination


def journal(stream, event, **fields):
    stream.write(json.dumps({'event': event, 'at': vc.utc_now(), **fields}, ensure_ascii=True) + '\n')
    stream.flush()
    os.fsync(stream.fileno())


def require_windows():
    if os.name != 'nt':
        raise vc.CopyError('Source release requires native Windows; no unlocked deletion fallback is provided')


@contextmanager
def open_locked_stream(path, delete_access=False, share=None):
    """Open a native read handle with explicit sharing; close exactly this handle."""
    require_windows()
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # Main source remains exclusive. A named source stream must share deletion
    # to coexist with the main DELETE handle; its bytes are still deny-write.
    handle = create(str(path), 0x80000000 | (0x10000 if delete_access else 0),
                    (0 if delete_access else 1) if share is None else share,
                    None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
    except BaseException:
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        close(handle)
        raise
    with os.fdopen(fd, 'rb') as stream:
        yield stream


def file_standard_info(stream):
    """Read pending deletion from the bound handle, including a named stream."""
    require_windows()
    import msvcrt
    from ctypes import wintypes

    class StandardInfo(ctypes.Structure):
        _fields_ = [('AllocationSize', ctypes.c_longlong), ('EndOfFile', ctypes.c_longlong),
                    ('NumberOfLinks', wintypes.DWORD), ('DeletePending', ctypes.c_ubyte),
                    ('Directory', ctypes.c_ubyte)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    query = kernel.GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    info = StandardInfo()
    if not query(msvcrt.get_osfhandle(stream.fileno()), 1, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'size': info.EndOfFile, 'link_count': info.NumberOfLinks,
            'delete_pending': bool(info.DeletePending), 'directory': bool(info.Directory)}


def check_locked_streams(stream):
    """Check observable identity, inventory and pending deletion on held handles.

    This does not freeze the stream-name inventory. Named source streams must
    share deletion, so an observable pending deletion is rejected explicitly.
    """
    path, expected = stream.release_path, stream.release_expected
    identity = (expected['device'], expected['inode'], expected['size'], expected['mtime_ns'])
    info = os.fstat(stream.fileno())
    vc.check_attributes(path, info)
    main = file_standard_info(stream)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or vc.file_identity(info) != identity
            or main['directory'] or main['link_count'] != 1 or main['delete_pending']
            or main['size'] != expected['size']):
        raise vc.CopyError(f'Opened file no longer matches release plan: {path}')
    if 'zone_identifier' not in expected:
        vc.check_streams(path)
        return
    marker = expected['zone_identifier']
    if vc.zone_descriptor(path) != (None if marker is None else marker['size']):
        raise vc.CopyError(f'Zone.Identifier inventory changed under release locks: {path}')
    zone = stream.zone_identifier_stream
    if marker is None:
        if zone is not None:
            raise vc.CopyError(f'Unexpected Zone.Identifier release handle: {path}')
        return
    if zone is None:
        raise vc.CopyError(f'Missing Zone.Identifier release handle: {path}')
    zone_stat = os.fstat(zone.fileno())
    zone_info = file_standard_info(zone)
    if (not stat.S_ISREG(zone_stat.st_mode) or zone_stat.st_nlink != 1
            or (zone_stat.st_dev, zone_stat.st_ino) != identity[:2]
            or zone_stat.st_size != marker['size'] or zone_info['size'] != marker['size']
            or zone_info['directory'] or zone_info['link_count'] != 1 or zone_info['delete_pending']):
        raise vc.CopyError(f'Zone.Identifier identity or pending deletion changed: {path}')


@contextmanager
def locked_file(path, expected, delete_access=False):
    """Hash the same main and optional marker objects retained during deletion."""
    require_windows()
    preserve_zone = 'zone_identifier' in expected
    before = vc.checked_file(path, preserve_zone_identifier=preserve_zone)
    vc.reject_managed(path)
    identity = (expected['device'], expected['inode'], expected['size'], expected['mtime_ns'])
    if vc.file_identity(before) != identity:
        raise vc.CopyError(f'File identity changed since release planning: {path}')
    # Nested cleanup closes the source marker before its main handle. The outer
    # retained contexts in remove_verified_pair remain held until source closes.
    with open_locked_stream(path, delete_access=delete_access) as stream, ExitStack() as markers:
        stream.release_path, stream.release_expected = path, expected
        stream.zone_identifier_stream = None
        marker = expected.get('zone_identifier')
        if marker is not None:
            stream.zone_identifier_stream = markers.enter_context(
                open_locked_stream(str(path) + ':Zone.Identifier', share=4 if delete_access else 1))
        check_locked_streams(stream)
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(vc.CHUNK), b''):
            digest.update(chunk)
        if digest.hexdigest() != expected['sha256'] or vc.file_identity(os.fstat(stream.fileno())) != identity:
            raise vc.CopyError(f'Locked file content differs from release plan: {path}')
        if marker is not None:
            contents = stream.zone_identifier_stream.read(vc.MAX_ZONE_BYTES + 1)
            if len(contents) != marker['size'] or hashlib.sha256(contents).hexdigest() != marker['sha256']:
                raise vc.CopyError(f'Locked Zone.Identifier differs from release plan: {path}')
        check_locked_streams(stream)
        yield stream


def mark_for_deletion(stream):
    require_windows()
    import msvcrt
    from ctypes import wintypes

    class Disposition(ctypes.Structure):
        _fields_ = [('DeleteFile', ctypes.c_ubyte)]  # Win32 BOOLEAN, not BOOL.

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    change = kernel.SetFileInformationByHandle
    change.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    change.restype = wintypes.BOOL
    disposition = Disposition(1)
    if not change(msvcrt.get_osfhandle(stream.fileno()), 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
        raise ctypes.WinError(ctypes.get_last_error())


def remove_verified_pair(source_file, destination_file, expected_source, expected_destination, pending):
    # Retained main+marker deny write/delete. The source main remains exclusive;
    # its optional marker denies read/write but must share delete. Source closes
    # before either retained handle is released. No recursive API or unlocked gap.
    with locked_file(destination_file, expected_destination) as retained:
        with locked_file(source_file, expected_source, delete_access=True) as source:
            pending()
            check_locked_streams(retained)
            check_locked_streams(source)
            mark_for_deletion(source)


def apply_plan(plan_path, approval, receipt_path):
    require_windows()
    plan = vc.load_plan(plan_path)
    source, destination = validate_plan(plan, approval)
    receipt_path = vc.external_output(receipt_path, source, destination)
    result = {'kind': 'disk-steward-release-result', 'plan_id': plan['plan_id'], 'status': 'failed',
              'deleted_files': 0, 'logical_source_bytes_removed': 0, 'pending_path': None,
              'source_directories_preserved': True, 'retained_copy': str(destination),
              'free_before_bytes': None, 'free_after_bytes': None, 'observed_free_delta_bytes': None,
              'cross_volume': plan['cross_volume'], 'atomic': False}
    preserve_zone = plan['copy_plan']['schema_version'] == 3
    if preserve_zone:
        result.update(stream_policy=plan['copy_plan']['stream_policy'],
                      logical_source_zone_identifier_bytes_removed=0, deleted_zone_identifier_files=0)
    with receipt_path.open('x', encoding='utf-8') as log:
        marker_start = ({'stream_policy': plan['copy_plan']['stream_policy'],
                         'zone_identifier_bytes': plan['copy_plan']['zone_identifier_bytes']}
                        if preserve_zone else {})
        journal(log, 'started', plan_id=plan['plan_id'], source=str(source), destination=str(destination),
                operation=OPERATION, **marker_start)
        try:
            _, _, retained = check_pair(plan['copy_plan'])
            if retained != plan['retained_files']:
                raise vc.CopyError('Retained copy changed since release planning')
            result['free_before_bytes'] = shutil.disk_usage(source).free
            journal(log, 'preflight_complete', free_before_bytes=result['free_before_bytes'])
            for item, kept in zip(plan['copy_plan']['files'], plan['retained_files']):
                parts = item['path'].split('/')
                current = source.joinpath(*parts)
                saved = destination.joinpath(*parts)
                marker = item.get('zone_identifier')
                marker_bytes = 0 if marker is None else marker['size']
                marker_fields = ({'zone_identifier': marker, 'zone_identifier_bytes': marker_bytes}
                                 if preserve_zone else {})

                def pending():
                    journal(log, 'deleting', path=item['path'], sha256=item['sha256'],
                            logical_bytes=item['size'], **marker_fields)
                    result['pending_path'] = item['path']

                remove_verified_pair(current, saved, item, kept, pending)
                # Source directories intentionally remain: an unselected/new file
                # can never be removed by recursive cleanup after this loop.
                result['deleted_files'] += 1
                result['logical_source_bytes_removed'] += item['size']
                if preserve_zone:
                    result['logical_source_zone_identifier_bytes_removed'] += marker_bytes
                    result['deleted_zone_identifier_files'] += marker is not None
                result['pending_path'] = None
                journal(log, 'deleted', path=item['path'], logical_bytes=item['size'], **marker_fields)
            result['status'] = 'complete'
        except (OSError, ValueError, OverflowError, NotImplementedError) as error:
            result['error'] = str(error)
            result['status'] = 'partial' if result['deleted_files'] or result['pending_path'] else 'failed'
        except KeyboardInterrupt:
            result['error'] = 'Interrupted; inspect the journal and retained copy before any further action'
            result['status'] = 'partial' if result['deleted_files'] or result['pending_path'] else 'failed'
        try:
            result['free_after_bytes'] = shutil.disk_usage(source).free
            if result['free_before_bytes'] is not None:
                result['observed_free_delta_bytes'] = result['free_after_bytes'] - result['free_before_bytes']
        except OSError as error:
            result['measurement_error'] = str(error)
        journal(log, 'finished', **result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    planning = commands.add_parser('plan', help='Reverify a copy and prepare a separate permanent-removal plan')
    planning.add_argument('--copy-plan', required=True)
    planning.add_argument('--copy-receipt', required=True)
    planning.add_argument('--output', required=True)
    applying = commands.add_parser('apply', help='Permanently delete only approved source files; Windows only')
    applying.add_argument('--plan', required=True)
    applying.add_argument('--approve', required=True, help='The distinct release plan_id, not the copy plan_id')
    applying.add_argument('--receipt', required=True, help='New append-only JSONL journal outside both trees')
    args = parser.parse_args(argv)
    try:
        if args.command == 'plan':
            result = make_plan(args.copy_plan, args.copy_receipt, args.output)
            print(json.dumps({'plan_id': result['plan_id'], 'operation': result['operation'],
                              'files': len(result['copy_plan']['files']), 'cross_volume': result['cross_volume']}))
        else:
            result = apply_plan(args.plan, args.approve, args.receipt)
            print(json.dumps(result))
            if result['status'] != 'complete':
                return 2
        return 0
    except (OSError, ValueError, OverflowError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
