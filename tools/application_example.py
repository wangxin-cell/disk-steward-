"""Render fictional application-registration evidence without reading Windows.

The authored paths, registrations and sizes are illustrative metadata. No path
in the sample is opened, no registry is queried and no cleanup is performed.
"""
import argparse
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/disk-steward/scripts'
sys.path.insert(0, str(SCRIPTS))
import app_inventory
import decision_report
import disk_scan


def example():
    stamp = '2026-11-05T00:00:00+00:00'
    gib = 1024**3
    candidates = [
        (r'C:\Example\Apps\Atlas\payload.bin', 3, 'user_file'),
        (r'C:\Example\Apps\Atlas-old\saved-export.zip', 2, 'archive_or_installer'),
        (r'C:\Example\Cache\unknown.bin', 1, 'possible_temp_or_cache'),
        (r'C:\Example\Downloads\completed-project.zip', 4, 'archive_or_installer'),
    ]
    volume = {'volume_id': 'fictional-source-C', 'path': 'C:\\',
              'queried_at': r'C:\Example', 'sampled_at': stamp,
              'scan_roots': [r'C:\Example'], 'total_bytes': 100 * gib,
              'used_bytes': 95 * gib, 'free_bytes': 5 * gib}
    files = [{'path': path, 'logical_bytes': size * gib, 'category': category,
              'hardlink_count': 1, 'volume_id': volume['volume_id']}
             for path, size, category in candidates]
    directories = [{'path': r'C:\Example\Apps', 'logical_bytes': 5 * gib,
                    'category': 'user_file', 'observed_files': 2, 'hardlinked_files': 0,
                    'deduplicated_file_names': 0, 'incomplete': True,
                    'is_scan_root': False, 'volume_id': volume['volume_id']}]
    plan = disk_scan.make_plan({'schema_version': 1, 'created_at': stamp,
                               'incomplete': True, 'volumes': [volume],
                               'largest_files': files, 'largest_directories': directories},
                              20, 'additional', 'C:\\')
    plan['created_at'] = stamp
    scopes = [{'hive': hive, 'view': view, 'status': 'complete',
               'entries_examined': 2 if (hive, view) == ('HKCU', '64') else 0,
               'errors': []}
              for hive in ('HKLM', 'HKCU') for view in ('32', '64')]
    inventory = {
        'schema_version': 1, 'kind': 'disk-steward-application-inventory',
        'created_at': stamp, 'coverage': 'uninstall_registration_only',
        'incomplete': False, 'max_entries': 1000, 'entries_examined': 2,
        'scopes': scopes,
        'entries': [
            {'hive': 'HKCU', 'view': '64', 'subkey': name,
             'display_name': title, 'display_version': '1.0-example',
             'publisher': 'Fictional Publisher', 'install_location': r'C:\Example\Apps\Atlas'}
            for name, title in (('fictional-atlas', 'Atlas Editor (fictional)'),
                                ('fictional-shared', 'Atlas Shared Component (fictional)'))
        ],
    }
    app_inventory.validate_inventory(inventory)

    def choices(language):
        zh = language == 'zh'
        return {'schema_version': 1, 'scenarios': [{'name': 'conservative', 'choices': [
            {'path': path, 'action': 'copy_then_release',
             'explanation': '虚构意向：考虑另存，尚未决定删除。' if zh else 'Fictional preference: consider another copy; deletion is undecided.',
             'consequence': '需先确认用途、目标盘与独立释放范围。' if zh else 'First establish purpose, destination and separately reviewed source-release scope.',
             'destination_volume_id': 'fictional-declared-D'}
            for path, _, _ in candidates
        ]}]}
    return plan, inventory, choices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='Existing directory for two new example reports')
    args = parser.parse_args()
    output = Path(args.output)
    paths = {language: output / f'example-application-review.{language}.md' for language in ('zh', 'en')}
    if not output.is_dir() or any(path.exists() for path in paths.values()):
        parser.error('Use an existing directory without these example reports')
    plan, inventory, choices = example()
    notices = {
        'zh': '> **虚构示例**：登记信息、路径、容量与用户意向均为手工构造，没有查询注册表、扫描文件或执行清理。两个登记都指向 Atlas；它们不能证明当前安装状态或独占归属。Atlas-old 的相似名称不构成关联，无关联也不代表可删。\n\n',
        'en': '> **Fictional example**: Registrations, paths, sizes and preferences are invented. No registry query, file scan or cleanup occurred. Two records point to Atlas; neither proves current installation or exclusive ownership. Atlas-old does not match merely by name, and a non-match does not mean disposable.\n\n',
    }
    for language, path in paths.items():
        rendered = decision_report.render_report(plan, choices(language), language, applications=inventory)
        decision_report.write_report(path, notices[language] + rendered)
    print(json.dumps({'fictional_example': True, 'registry_queried': False,
                      'outputs': [str(path) for path in paths.values()]}))


if __name__ == '__main__':
    main()
