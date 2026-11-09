"""Render explicitly fictional decision examples without scanning a filesystem.

Only the two new Markdown outputs are written. The C/D paths and capacities
below are invented product examples, not measurements, user choices or benchmarks.
"""
import argparse
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills' / 'disk-steward' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import decision_report
import disk_scan


def example():
    gib = 1024**3
    stamp = '2026-11-05T00:00:00+00:00'
    archive = r'C:\Example\Downloads\completed-project.zip'
    active = r'C:\Example\Documents\active-project.zip'
    cache = r'C:\Example\AppData\Local\ExampleApp\Cache\payload.bin'
    volume = {
        'volume_id': 'fictional-source-volume-C', 'path': 'C:\\',
        'queried_at': r'C:\Example', 'sampled_at': stamp,
        'scan_roots': [r'C:\Example'],
        'total_bytes': 100 * gib, 'used_bytes': 95 * gib, 'free_bytes': 5 * gib,
    }
    files = [
        {'path': path, 'logical_bytes': size * gib, 'category': category,
         'hardlink_count': 1, 'volume_id': volume['volume_id']}
        for path, size, category in [
            (archive, 12, 'archive_or_installer'),
            (active, 4, 'user_file'),
            (cache, 9, 'possible_temp_or_cache'),
        ]
    ]
    directories = [
        {'path': r'C:\Example', 'logical_bytes': 25 * gib,
         'category': 'user_file', 'observed_files': 3, 'hardlinked_files': 0,
         'deduplicated_file_names': 0, 'incomplete': True, 'is_scan_root': True,
         'volume_id': volume['volume_id']},
        {'path': r'C:\Example\Downloads', 'logical_bytes': 12 * gib,
         'category': 'downloads', 'observed_files': 1, 'hardlinked_files': 0,
         'deduplicated_file_names': 0, 'incomplete': False, 'is_scan_root': False,
         'volume_id': volume['volume_id']},
    ]
    plan = disk_scan.make_plan({
        'schema_version': 1, 'created_at': stamp, 'incomplete': True,
        'volumes': [volume], 'largest_files': files, 'largest_directories': directories,
    }, 20, 'additional', 'C:\\')
    plan['created_at'] = stamp

    def choices(language):
        zh = language == 'zh'
        proposed_copy = {
            'path': archive, 'action': 'copy_then_release',
            'explanation': '示例意向：保留已完成项目，改放其他盘。' if zh else 'Fictional preference: retain the completed project on another drive.',
            'consequence': '以后访问依赖目标盘；源文件释放是独立的永久删除操作。' if zh else 'Access depends on the target drive; source release is a separate permanent deletion.',
            'destination_volume_id': 'fictional-declared-volume-D',
        }
        keep = {
            'path': active, 'action': 'keep',
            'explanation': '示例意向：近期仍在使用，保留当前位置。' if zh else 'Fictional preference: keep the active project at its current location.',
            'consequence': '这部分空间继续占用，不计入释放量。' if zh else 'Its space remains occupied; no space release is counted.',
        }
        app = {
            'path': cache, 'action': 'app_cleanup',
            'explanation': '示例意向：先确认应用归属，再检查应用自带清理。' if zh else 'Fictional preference: confirm application ownership, then review its supported cleanup.',
            'consequence': '可能需要重新下载或编译；尚无归属证据或清理授权。' if zh else 'May need downloads or rebuilding; ownership evidence and cleanup authorization are absent.',
        }
        return {'schema_version': 1, 'scenarios': [
            {'name': 'conservative', 'choices': [proposed_copy, keep]},
            {'name': 'expanded', 'choices': [proposed_copy, keep, app]},
        ]}
    return plan, choices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='Existing directory for two new Markdown files')
    args = parser.parse_args()
    output = Path(args.output)
    paths = {language: output / f'example-decision-report.{language}.md' for language in ('zh', 'en')}
    if not output.is_dir() or any(path.exists() for path in paths.values()):
        parser.error('Use an existing directory with no existing example report filenames')
    plan, choices = example()
    notices = {
        'zh': '> **虚构示例**：下方所有路径、容量和选择均为手工构造。没有扫描 C/D 盘、创建大文件或执行清理，不是性能或释放量测试。\n\n',
        'en': '> **Fictional example**: All paths, capacities and choices below are invented. No C/D scan, large-file creation or cleanup occurred. This is not a performance or reclaim test.\n\n',
    }
    for language, path in paths.items():
        decision_report.write_report(path, notices[language] + decision_report.render_report(plan, choices(language), language))
    print(json.dumps({'synthetic_example': True, 'outputs': [str(path) for path in paths.values()]}))


if __name__ == '__main__':
    main()
