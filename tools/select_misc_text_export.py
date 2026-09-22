#!/usr/bin/env python3
"""Select menu/help, tutorial, and image records from a verified frozen export."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'menu-system-help': '菜单、系统与说明',
    'tutorial': '教程正文与标题',
    'image-text': '图片文字',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def group(category):
    if re.fullmatch(r'(0[1-9]|1[0-4])-[a-z-]+', category):
        return 'menu-system-help'
    if category == 'C1-tutorial':
        return 'tutorial'
    if category in {'D1-ui-images', 'D2-battle-images', 'D3-map-images'}:
        return 'image-text'
    return None


def run(source, output):
    source_checks = read(source / 'checksums.json')
    for name, digest in source_checks.items():
        path = (source / name).resolve()
        assert path.is_relative_to(source) and sha(path.read_bytes()) == digest, name
    source_manifest = read(source / 'manifest.json')
    original_rows = read(source / 'combined.json')['entries']
    rows = deepcopy([r for r in original_rows if group(r['category'])])
    ids = {r['id'] for r in rows}
    assert len(ids) == len(rows)
    for row in rows:
        row['export_group'] = group(row['category'])
        context = row.get('context', {})
        owners = context.get('shared_source_owner_ids', [])
        if owners:
            context['shared_source_owner_ids'] = [i for i in owners if i in ids]
            context['shared_source_owners_outside_selection'] = sum(i not in ids for i in owners)
    grouped = {key: [r for r in rows if r['export_group'] == key] for key in GROUPS}
    categories = dict(Counter(r['category'] for r in rows))
    differences = [r for r in rows if r['source_changed_in_best'] is True]
    review = [r for r in rows if r['classification']['needs_context_review']]
    output.mkdir(parents=True, exist_ok=False)
    for key, entries in grouped.items():
        write(output / (key + '.json'), {'schema_version': 2, 'group': key, 'label': GROUPS[key], 'entries': entries})
    write(output / 'combined.json', {'schema_version': 2, 'entries': rows})
    for edition in ('original', 'best'):
        write(output / (edition + '.json'), {'schema_version': 2, 'edition': edition,
              'source': source_manifest['sources'][edition],
              'entries': [{k: v for k, v in r.items() if k != 'editions'} | r['editions'][edition] for r in rows]})
    write(output / 'edition-differences.json', {'entries': differences})
    write(output / 'classification-review.json', {'scope': 'Category review only, not source extraction failures.', 'entries': review})
    (output / 'categories').mkdir()
    for category in categories:
        write(output / 'categories' / (category + '.json'), {
            'category': category, 'label': source_manifest['categories'][category]['label'],
            'entries': [r for r in rows if r['category'] == category]})
    manifest = {
        'schema_version': 2,
        'operation': 'selection_from_hash_verified_frozen_export; no_source_or_translation_refresh',
        'entry_count_per_edition': len(rows),
        'groups': {k: {'label': GROUPS[k], 'count': len(v)} for k, v in grouped.items()},
        'categories': {k: {'label': source_manifest['categories'][k]['label'], 'count': v} for k, v in categories.items()},
        'roles': dict(Counter(r['role'] for r in rows)),
        'edition_source_differences': len(differences),
        'classification_review_count': len(review),
        'image_caption_comparison_unknown': sum(r['source_changed_in_best'] is None for r in rows),
        'sources': source_manifest['sources'],
        'source_export': {'path': str(source.relative_to(ROOT)), 'manifest_sha256': sha((source / 'manifest.json').read_bytes()),
                          'combined_sha256': sha((source / 'combined.json').read_bytes()), 'verified_file_count': len(source_checks)},
        'source_input_sha256': source_manifest['input_sha256'],
        'selector_sha256': sha(Path(__file__).read_bytes()),
        'excluded': [*source_manifest['excluded'], 'standalone pilot, unit, weapon, demo, work-title and map-place name tables'],
        'image_scope': 'All three image categories retained, including world-map title images.',
        'translation_evidence': 'Corpus text frozen in the source export; not refreshed from the current workspace or decoded Chinese ISOs.',
        'image_evidence': source_manifest['image_evidence'],
    }
    write(output / 'manifest.json', manifest)
    html = (source / 'index.html').read_text(encoding='utf-8')
    start = html.index('const rows=') + len('const rows=')
    end = html.index(';const $=', start)
    html = html[:start] + json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c') + html[end:]
    summary = ('仅保留菜单、系统与说明，教程正文与标题，以及图片文字。独立名称表和地图地点名已移除；'
               '世界地图标题作为图片文字保留。日文与中文沿用已验证导出的快照，原始定位与版本差异保留。')
    html, count = re.subn(r'(<h1>[^<]*</h1>)<p>.*?</p>', lambda m: m[1] + '<p>' + summary + '</p>', html, count=1)
    assert count == 1
    (output / 'index.html').write_text(html, encoding='utf-8')
    lines = ['# 本篇 / BEST 菜单、教程与图片文字', '',
             f'每版 {len(rows):,} 条，{len(categories)} 个子类，日文版本差异 {len(differences)} 条。', '',
             '| 文件 | 内容 | 每版条数 |', '| --- | --- | --- |']
    lines += [f'| `{key}.json` | {GROUPS[key]} | {len(entries)} |' for key, entries in grouped.items()]
    lines += ['', '另附 `combined.json`、`original.json`、`best.json`、`categories/`、`edition-differences.json`、`classification-review.json` 和离线检索页 `index.html`。', '',
              '仅筛选上一份已验证导出，未刷新或改写日文、中文及来源位置。校验原包文件哈希后，按用户选定的三个组生成本包。',
              '已移除独立人物／机体／武器／待机演示名称、作品标题与地图地点名表；此前排除的 BGM 曲名、小队名和地形名继续排除。菜单自身的标签、能力／零件名称以及开局命名界面字段仍属于菜单组。',
              '图片文字保留界面、战斗界面及世界地图图片标题。图片原文为标注／贴图转写，不是字符串解码。',
              f'其中 {len(review):,} 条沿用规则初分，分类复核队列单列；不代表这部分原文未提取。',
              '教程第8页使用两版原盘实际的“选择帮助”标题，保留旧备注差异；第10页是 Q&A 入口介绍，不是 Q&A 正文。',
              '共用源字符串的其他用途若不在本次选择中，只记录外部用途数量，不带入被排除条目。', '',
              '中文为原导出时的语料，包含项目已采用的 BEST 修正，不是两版中文成品 ISO 的分别回读。', '',
              '本次未修改翻译语料、ISO 或构建锁。']
    (output / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    checks = {str(p.relative_to(output)): sha(p.read_bytes()) for p in sorted(output.rglob('*')) if p.is_file()}
    write(output / 'checksums.json', checks)
    with zipfile.ZipFile(output.with_suffix('.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.rglob('*')):
            if p.is_file():
                z.write(p, str(Path(output.name) / p.relative_to(output)))
    print(json.dumps({'entries_per_edition': len(rows), 'groups': manifest['groups'], 'differences': len(differences)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if not source.is_relative_to((ROOT / 'work').resolve()) or not output.is_relative_to((ROOT / 'work').resolve()):
        parser.error('Use paths inside project work/')
    if output.exists() or output.with_suffix('.zip').exists():
        parser.error('Output directory and ZIP must not already exist')
    run(source, output)


if __name__ == '__main__':
    main()
