#!/usr/bin/env python3
"""Read-only, edition-aware export of explanations and their UI context."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

from srwz.codec import decode_production
from srwz.iso9660 import member_map, scan_iso9660
from srwz.library import parse_zkn_decoded_chunk
from srwz.menu import parse_menu_file
from srwz.text import decode_text, load_text_table

ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = {'robot': 'DATA/MTVZKNRT.BIN', 'character': 'DATA/MTVZKNPT.BIN',
             'glossary': 'DATA/MTVZKNKW.BIN'}
EXCLUDED_SECTIONS = {'Battle Lines', 'Weapon', 'Stage Name'}


def excluded_ui_location(kind, offset):
    # Tutorial headings and Strategy Q&A navigation/help, outside NISVDATA.
    if kind == 'elf':
        return offset in {0x340BD8, 0x347338} or 0x347B40 <= offset <= 0x347CA0
    return offset == 0x7FCB0


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Export:
    def __init__(self):
        self.inputs = {}
        self.layout = self.load('config/editions/best/source-layout.json')
        self.table = load_text_table(ROOT / 'vendor/upstream-python/project/tbl_all.json')
        self.inputs['vendor/upstream-python/project/tbl_all.json'] = sha(
            (ROOT / 'vendor/upstream-python/project/tbl_all.json').read_bytes())
        self.rows = {}
        self.sources = {}
        self.native = {}
        self.profiles = {}
        self.menu_translations = {}
        for path in sorted((ROOT / 'corpus/zh/menu').glob('*.json')):
            if path.name in {'battle-lines.json', 'weapons.json', 'stage-names.json',
                             'stage-overviews.json', 'hsfc-overviews.json', 'release-v0.3.json',
                             'nisv-strategy-qa.json', 'nisv-tutorial-pages.json'}:
                continue
            document = self.load(str(path.relative_to(ROOT)))
            for entry in document.get('entries', []):
                if entry.get('id', '').startswith('menu/'):
                    self.menu_translations[entry['id']] = (entry, str(path.relative_to(ROOT)))
        # Match the production release selection, including its reviewed overrides.
        path = 'corpus/zh/menu/release-v0.3.json'
        for entry in self.load(path)['entries']:
            self.menu_translations[entry['id']] = (entry, path)
        self.remaining = self.load('corpus/zh/menu/remaining-ui.json')
        self.library = self.load('corpus/zh/library/v0.2-reviewed.json')
        self.by_hash = {e['source_text_sha256']: e for e in self.library['entries']}
        self.field_overrides = {e['id']: e for e in self.library.get('field_translation_overrides', [])}

    def load(self, relative):
        path = ROOT / relative
        self.inputs[relative] = sha(path.read_bytes())
        return read_json(path)

    def mapped(self, offset):
        slot = self.layout['elf_support_attack_slot']
        if slot['original_start'] <= offset < slot['original_end']:
            return slot['best_start'] + offset - slot['original_start']
        for start, end, target in self.layout['elf_spans']:
            if start <= offset < end:
                return target + offset - start
        raise ValueError(f'No audited BEST mapping for 0x{offset:X}')

    def load_disc(self, edition):
        p = self.load(f'config/editions/{edition}/edition.json')
        self.profiles[edition] = p
        path = ROOT / p['source_iso']['path']
        with path.open('rb') as stream:
            hasher = hashlib.sha256()
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                hasher.update(block)
            digest = hasher.hexdigest()
        assert digest == p['source_iso']['sha256'], f'{edition}: ISO hash drift'
        assert path.stat().st_size == p['source_iso']['size']
        members = member_map(scan_iso9660(path))
        names = [p['executable']['member'], 'DATA/COMPDATA.BN', *LIBRARIES.values()]
        source = {}
        locks = {}
        with path.open('rb') as stream:
            for name in names:
                member = members[name]
                stream.seek(member.extent_lba * 2048)
                source[name] = stream.read(member.size)
                assert len(source[name]) == member.size
                locks[name] = {'sha256': sha(source[name]), 'size': member.size,
                               'extent_lba': member.extent_lba}
        assert locks[p['executable']['member']]['sha256'] == p['executable']['sha256']
        self.sources[edition] = {'iso': p['source_iso'], 'members': locks}
        source['elf'] = source[p['executable']['member']]
        source['compdata'] = decode_production(source['DATA/COMPDATA.BN']).output
        self.native[edition] = source

    def chunk(self, edition, member, index):
        spec = next(r for r in self.layout['archive_tables'] if r['member'] == member)
        start = spec[f'{edition}_start']
        source = self.native[edition]
        offsets = list(struct.unpack_from('<' + 'I' * spec['count'], source['elf'], start))
        if offsets[-1] != len(source[member]):
            offsets.append(len(source[member]))
        assert offsets[0] == 0 and all(a <= b for a, b in zip(offsets, offsets[1:]))
        assert offsets[-1] == len(source[member])
        if index is None:
            return len(offsets) - 1
        lo, hi = offsets[index:index + 2]
        stored = source[member][lo:hi]
        decoded = decode_production(stored)
        assert not any(stored[decoded.consumed:])
        return decoded.output, {'member': member, 'chunk_index': index,
                                'stored_range': [lo, hi], 'decoded_sha256': sha(decoded.output)}

    def text_at(self, data, offset):
        decoded = decode_text(data, offset, self.table)
        assert decoded.unknown_code_count == 0, f'Unknown code at {offset:X}'
        return decoded.text

    def add(self, entry_id, category, role, translation, refs, texts, locations, **context):
        assert entry_id not in self.rows, entry_id
        self.rows[entry_id] = {
            'id': entry_id, 'category': category, 'role': role,
            'translation_zh': translation, 'translation_basis': 'current_working_tree_corpus',
            'corpus_references': refs, 'context': context,
            'source_changed_in_best': texts['original'] != texts['best'],
            'editions': {e: {'source_ja': texts[e], 'source_text_sha256': sha(texts[e].encode()),
                             'location': locations[e]} for e in ('original', 'best')},
        }

    def menus(self):
        descriptors = self.load('vendor/upstream-python/project/menu_files.json')
        # Parse stable Original IDs; independently decode every mapped BEST slot.
        for descriptor in descriptors:
            kind = 'elf' if descriptor['friendly_name'] == 'SLPS' else 'compdata'
            parsed = parse_menu_file(self.native['original'][kind], descriptor, self.table)
            for entry in parsed.entries:
                if entry.section in EXCLUDED_SECTIONS:
                    continue
                if not entry.text.strip() or any(excluded_ui_location(kind, o) for o in entry.target_offsets):
                    continue
                translated = self.menu_translations.get(entry.entry_id)
                if translated is None:
                    raise ValueError(f'Missing translation owner: {entry.entry_id}')
                corpus, ref = translated
                assert corpus['source_text_sha256'] == sha(entry.text.encode()), entry.entry_id
                texts, locations = {}, {}
                for edition in ('original', 'best'):
                    offsets = [self.mapped(o) if edition == 'best' and kind == 'elf' else o
                               for o in entry.target_offsets]
                    variants = {self.text_at(self.native[edition][kind], o) for o in offsets}
                    assert len(variants) == 1, (entry.entry_id, variants)
                    texts[edition] = variants.pop()
                    locations[edition] = {'member': self.profiles[edition]['executable']['member']
                                          if kind == 'elf' else 'DATA/COMPDATA.BN',
                                          'offset_space': 'file' if kind == 'elf' else 'decoded',
                                          'text_offsets': offsets}
                self.add(entry.entry_id, 'menu/' + entry.section, 'ui_text', corpus['translation'],
                         [{'path': ref, 'id': entry.entry_id}], texts, locations,
                         editorial_status=corpus.get('editorial_status', 'release_selection'))
        # Direct writers override/add UI strings outside the old pointer descriptors.
        groups = ['compdata_direct_by_offset', 'compdata_context_help_by_offset',
                  'compdata_inline_by_offset', 'leadership_effect_by_offset',
                  'slps_context_ui_by_offset', 'slps_by_offset']
        for group in groups:
            kind = 'elf' if group.startswith('slps') else 'compdata'
            for raw_offset, value in self.remaining[group].items():
                offset = int(raw_offset, 0)
                if excluded_ui_location(kind, offset):
                    continue
                translation = value['translation'] if isinstance(value, dict) else value
                refs = [{'path': 'corpus/zh/menu/remaining-ui.json', 'json_pointer': f'/{group}/{raw_offset}'}]
                member = self.profiles['original']['executable']['member'] if kind == 'elf' else 'DATA/COMPDATA.BN'
                matches = [r for r in self.rows.values() if r['editions']['original']['location']['member'] == member
                           and offset in r['editions']['original']['location'].get('text_offsets', [])]
                if matches:
                    for row in matches:
                        row['translation_zh'] = translation
                        row['corpus_references'] += refs
                    continue
                texts, locations = {}, {}
                for edition in ('original', 'best'):
                    target = self.mapped(offset) if edition == 'best' and kind == 'elf' else offset
                    texts[edition] = self.text_at(self.native[edition][kind], target)
                    locations[edition] = {'member': self.profiles[edition]['executable']['member']
                                          if kind == 'elf' else member,
                                          'offset_space': 'file' if kind == 'elf' else 'decoded',
                                          'text_offsets': [target]}
                role = 'explanation' if 'help' in group or 'leadership' in group else 'ui_text'
                self.add(f'ui/{kind}/{offset:08X}', 'menu/' + group, role, translation, refs,
                         texts, locations, editorial_status=self.remaining['editorial_status'])

    def libraries(self):
        ref = 'corpus/zh/library/v0.2-reviewed.json'
        for domain, member in LIBRARIES.items():
            counts = {e: self.chunk(e, member, None) for e in self.native}
            assert counts['original'] == counts['best']
            for index in range(counts['original']):
                docs, loc = {}, {}
                for edition in self.native:
                    data, loc[edition] = self.chunk(edition, member, index)
                    docs[edition] = parse_zkn_decoded_chunk(data)
                for field in docs['original'].fields:
                    if field.text is None or not field.text.strip():
                        continue
                    field_id = f'{domain}/{index:03d}/{field.tag}'
                    corpus = self.by_hash[sha(field.text.encode())]
                    selected = self.field_overrides.get(field_id, corpus)
                    texts = {e: docs[e].field(field.tag).text for e in docs}
                    locations = {e: {**loc[e], 'field_tag': field.tag} for e in docs}
                    title_tag = {'robot': 'RBTN', 'character': 'CHFN', 'glossary': 'WORD'}[domain]
                    title = next((f.text for f in docs['original'].fields if f.tag == title_tag), None)
                    self.add(f'library/{field_id}', f'library/{domain}',
                             'explanation' if field.tag in {'DSCR', 'DSC2'} else 'heading',
                             selected['translation'], [{'path': ref, 'id': selected['id']}],
                             texts, locations, title_ja=title, editorial_status=corpus['editorial_status'])

    def run(self, output):
        for edition in ('original', 'best'):
            print(f'Verifying and reading {edition} ISO', flush=True)
            self.load_disc(edition)
        for method in (self.menus, self.libraries):
            print(f'Exporting {method.__name__}', flush=True)
            method()
        rows = list(self.rows.values())
        assert all(r['translation_zh'] for r in rows)
        assert not any(r['category'].removeprefix('menu/') in EXCLUDED_SECTIONS for r in rows)
        for relative, digest in self.inputs.items():
            assert sha((ROOT / relative).read_bytes()) == digest, f'Input changed during export: {relative}'
        self.inputs[str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__).read_bytes())
        output.mkdir(parents=True, exist_ok=False)
        for edition in self.native:
            write_json(output / f'{edition}.json', {
                'schema_version': 1, 'edition': edition, 'source': self.sources[edition],
                'entries': [{k: v for k, v in r.items() if k != 'editions'} | r['editions'][edition] for r in rows]})
        write_json(output / 'combined.json', {'schema_version': 1, 'entries': rows})
        differences = [r for r in rows if r['source_changed_in_best']]
        write_json(output / 'edition-differences.json', {'schema_version': 1, 'entries': differences})
        summary = {'entry_count_per_edition': len(rows), 'edition_source_differences': len(differences),
                   'categories': dict(Counter(r['category'] for r in rows)),
                   'roles': dict(Counter(r['role'] for r in rows)), 'sources': self.sources,
                   'input_sha256': self.inputs, 'unknown_code_count': 0,
                   'scope': 'Explanations plus associated menu labels and library metadata; no tutorials, strategy Q&A, STAGE/SRVC/battle lines.',
                   'translation_evidence': 'Current corpus, not decoded Chinese ISO or runtime verification.'}
        write_json(output / 'manifest.json', summary)
        self.html(output, rows, summary)
        print(json.dumps({k: v for k, v in summary.items() if k in ('entry_count_per_edition', 'edition_source_differences', 'roles')}, ensure_ascii=False))

    def html(self, output, rows, summary):
        data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
        html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>本篇 / BEST 说明文本</title>
<style>body{font:15px/1.65 system-ui;margin:32px;color:#183046;background:#f7f9fb}h1{font-size:27px}input,select,button{font:inherit;padding:7px;margin:4px}table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #dbe3eb;padding:12px;text-align:left;vertical-align:top}td{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#61778b}th{background:#eaf0f5}td:first-child{width:19%}td:not(:first-child){width:27%}</style>
<h1>本篇 / BEST · 说明文本日中对照</h1><p>菜单帮助、能力说明与图鉴正文（已排除教程和攻略 Q&A），连同相关标题、名称及界面标签。日文从两版原始 ISO 分别读取；中文来自当前工作区语料。每页显示 80 条。</p>
<input id="query" placeholder="搜索 ID、日文或中文" size="35"><select id="category"><option value="">全部类别</option></select><select id="role"><option value="">全部字段</option><option value="explanation">明确的正文 / 说明字段</option><option value="ui_text">菜单文本（包含短说明）</option><option value="heading">标题 / 图鉴元数据</option></select><label><input id="diff" type="checkbox">只看版本差异</label>
<p id="count"></p><button id="prev">上一页</button><button id="next">下一页</button><table><thead><tr><th>ID / 来源 / 类别</th><th>本篇日文</th><th>BEST 日文</th><th>当前中文</th></tr></thead><tbody id="body"></tbody></table>
<script>const rows=DATA;let page=0;const $=id=>document.getElementById(id);
for(const c of [...new Set(rows.map(r=>r.category))].sort()){const o=document.createElement('option');o.value=o.textContent=c;$('category').append(o)}
function render(){const q=$('query').value.toLowerCase(),c=$('category').value,role=$('role').value;const a=rows.filter(r=>(!c||r.category===c)&&(!role||r.role===role)&&(!$('diff').checked||r.source_changed_in_best)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));const pages=Math.max(1,Math.ceil(a.length/80));page=Math.max(0,Math.min(page,pages-1));$('count').textContent=`${a.length} 条 · 第 ${page+1} / ${pages} 页`;$('body').replaceChildren();for(const r of a.slice(page*80,page*80+80)){const tr=document.createElement('tr');for(const text of [r.id+'\\n'+r.category+'\\n'+JSON.stringify(r.editions.original.location),r.editions.original.source_ja,r.editions.best.source_ja,r.translation_zh]){const td=document.createElement('td');td.textContent=text;tr.append(td)}$('body').append(tr)}$('prev').disabled=page===0;$('next').disabled=page===pages-1}
for(const id of ['query','category','role','diff'])$(id).addEventListener('input',()=>{page=0;render()});$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};render();</script></html>'''
        (output / 'index.html').write_text(html.replace('const rows=DATA;', 'const rows=' + data + ';'), encoding='utf-8')
        (output / 'README.md').write_text(f'''# 本篇 / BEST 非对白说明文本结构化导出

每版 {len(rows)} 条，日文存在版本差异 {summary['edition_source_differences']} 条。

- `index.html`：离线检索、分类筛选、日中对照和版本差异。
- `combined.json`：以稳定 ID 对齐两版，保留源字符串哈希、位置和中文语料引用。
- `original.json` / `best.json`：单版扁平条目；中文为当前共享翻译语料。
- `edition-differences.json`：本次范围内全部原文差异。
- `manifest.json`：原始 ISO 与成员哈希、语料文件哈希、范围和统计。

范围包含描述符覆盖的非对白菜单文本，剩余 UI 的直接字符串，人物／机体／术语图鉴。图鉴以字段为单位，DSCR/DSC2 是说明正文。菜单标签和短说明混存，保留全部相关字段，不按字符串长短猜测后丢弃。

排除教程、攻略 Q&A 及相关目录标题、STAGE 剧情、关卡概要／世界史／Z报告、SRVC 战斗对白、COMPDATA Battle Lines、纯武器名表、关卡名表、图片文字和特别盘。没有进行 OCR，也不宣称枚举了未知资源中的文字。

日文取自两版各自 ISO；完整 ISO SHA-256 与版本配置核对。BEST 可执行文件使用项目已审计分段映射；其他归档使用各版本原生目录。中文取自当前工作区的生产语料选择，应用 remaining-ui 覆盖和图鉴字段覆盖，保留控制标记、换行与占位符。共享中文已包含项目采纳的 BEST 修正，因此不应当作 Original 原始日文的逐字翻译；两版不同的源文单独保留。中文不是成品 ISO 回读，不代表运行时验证或新的翻译审校结论。

重跑：`python3 tools/export_explanatory_text.py --output work/exports/explanatory-text-新目录`。输出目录必须不存在；不修改 ISO、翻译语料或构建锁。输入哈希固定本次工作区内容。
''', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'work').resolve()):
        parser.error('Output must be inside the project work directory')
    if output.exists():
        parser.error('Output directory already exists')
    Export().run(output)


if __name__ == '__main__':
    main()
