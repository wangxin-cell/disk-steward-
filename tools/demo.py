"""Create disposable synthetic files and demonstrate diagnosis + verified copy.

Creates only the new --output directory; no downloads or user-file scans.
Optional --release-synthetic permanently removes only selected fixture files.
Plans are applied automatically only to the synthetic files this demo creates.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def module(name):
    script = Path(__file__).resolve().parents[1] / 'skills' / 'disk-steward' / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, script)
    result = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(result)
    finally:
        sys.path.pop(0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New directory with an existing parent')
    parser.add_argument('--release-synthetic', action='store_true', help='Windows only: also release the newly created selected fixture files')
    args = parser.parse_args()
    scanner, copier, reporter = module('disk_scan'), module('verified_copy'), module('decision_report')
    releaser = module('source_release') if args.release_synthetic else None
    if releaser:
        releaser.require_windows()
    copier.relative_name(Path(args.output).name)
    output = copier.absolute(args.output)
    copier.check_ancestors(output.parent)
    copier.relative_name(output.name)
    output.mkdir()
    source = output / 'fixture' / 'Downloads' / 'Archives'
    source.mkdir(parents=True)
    (source / 'example.txt').write_bytes(b'Synthetic project archive\n' * 128)
    (source / 'notes.txt').write_text('All files in this example are synthetic.\n', encoding='utf-8')
    (source / 'keep.txt').write_bytes(b'Keep this unselected file.\n')
    (source / 'empty-folder').mkdir()
    scan = scanner.scan_roots([source])
    scanner.write_report(output / 'scan.json', scan)
    review_plan = scanner.make_plan(scan, 20)
    scanner.write_report(output / 'review-plan.json', review_plan)
    for language in ('zh', 'en'):
        reporter.write_report(output / f'decision-report.{language}.md', reporter.render_report(review_plan, language=language))
    plan_path = output / 'copy-plan.json'
    plan = copier.make_plan(source, output / 'verified-copy', plan_path, include=['example.txt', 'notes.txt'])
    receipt = copier.apply_plan(plan_path, plan['plan_id'], output / 'receipt.json')
    released = None
    if releaser and receipt['status'] == 'verified':
        release_path = output / 'release-plan.json'
        release_plan = releaser.make_plan(plan_path, output / 'receipt.json', release_path)
        released = releaser.apply_plan(release_path, release_plan['plan_id'], output / 'release-journal.jsonl')
    summary = {
        'synthetic_demo': True,
        'actual_cross_volume_test': False,
        'scanned_files': scan['total_files'],
        'logical_bytes': scan['logical_bytes'],
        'scan_incomplete': scan['incomplete'],
        'copy_status': receipt['status'],
        'verified_files': receipt['verified_files'],
        'verified_bytes': receipt['verified_bytes'],
        'source_files_still_exist': all((source / item['path']).exists() for item in plan['files']),
        'unselected_source_preserved': (source / 'keep.txt').read_bytes() == b'Keep this unselected file.\n',
        'copy_reclaimed_bytes': receipt['reclaimed_bytes'],
        'release_status': released['status'] if released else 'not_requested',
        'release_logical_bytes_removed': released['logical_source_bytes_removed'] if released else 0,
        'release_observed_free_delta_bytes': released['observed_free_delta_bytes'] if released else None,
    }
    scanner.write_report(output / 'summary.json', summary)
    print(json.dumps(summary, indent=2))
    return 0 if receipt['status'] == 'verified' and (not releaser or released and released['status'] == 'complete') else 2


if __name__ == '__main__':
    raise SystemExit(main())
