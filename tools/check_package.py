"""Dependency-free checks for this package's intentionally simple manifest.

This is not a general YAML parser or the upstream skill validator.
"""
from pathlib import Path
import re


def main():
    root = Path(__file__).resolve().parents[1]
    skill = root / 'skills' / 'disk-steward'
    text = (skill / 'SKILL.md').read_text(encoding='utf-8')
    frontmatter, body = text.split('---', 2)[1:]
    fields = {}
    for line in frontmatter.strip().splitlines():
        key, value = line.split(': ', 1)
        assert key not in fields, 'Duplicate manifest key'
        assert value and ': ' not in value and not value.startswith(('!', '&', '*', '[', '{', '|', '>')), 'Use simple YAML scalars'
        fields[key] = value
    assert text.startswith('---\n') and set(fields) == {'name', 'description'}
    assert fields['name'] == skill.name
    assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', fields['name'])
    assert len(fields['name']) <= 64 and len(fields['description']) <= 500
    assert not any(x in fields['description'] for x in '<>')
    assert '[TODO:' not in text
    for document in root.rglob('*.md'):
        if '__pycache__' in document.parts:
            continue
        for target in re.findall(r'\]\(([^)]+)\)', document.read_text(encoding='utf-8')):
            if re.match(r'[a-z]+://', target) or target.startswith('#'):
                continue
            assert (document.parent / target.split('#')[0]).exists(), f'Broken local link: {document}: {target}'
    for filename in ('disk_scan.py', 'verified_copy.py', 'source_release.py', 'app_cache.py', 'app_inventory.py', 'decision_report.py'):
        assert (skill / 'scripts' / filename).is_file()
    metadata = (skill / 'agents' / 'openai.yaml').read_text(encoding='utf-8')
    assert '$disk-steward' in metadata
    assert (skill / 'LICENSE.txt').read_text(encoding='utf-8') == (root / 'LICENSE').read_text(encoding='utf-8')
    print('Package scalar manifest, resource paths and local documentation links: OK')


if __name__ == '__main__':
    main()
