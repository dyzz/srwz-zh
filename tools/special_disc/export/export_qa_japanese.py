"""Export remaining Japanese Q&A with lossless record structure and reviewed references.

Reads the current SP ISO and locked Japanese source. Never writes corpus or ISO.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback'), str(Path(__file__).parent)]
from build_text_candidate import read_member, file_sha, write_json
from migrate_slps_text import encoding_tables
from export_sd_text import qa_lines
from srwz.iso9660 import member_map, scan_iso9660
from srwz.codec import decode_production
from srwz.nisv_strategy_qa import QA_METADATA_GROUPS
from srwz.text import decode_text, RUNTIME_FORMAT_TOKEN
from special_disc.source import CURRENT_ISO, SOURCE_ISO, DISC_INVENTORY
from special_disc.writeback.qa_layout import compile_original, page, require, sha

# The Katakana block also contains the legitimate Chinese list separator ・.
KANA = re.compile(r'[\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fd-\u30ff\uff66-\uff9f]')
NATIVE = ROOT / 'corpus/zh/special-disc/native-text.json'
PROPOSAL = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'


def metadata(chunk):
    cursor = 0x476
    for group, count in QA_METADATA_GROUPS:
        for index in range(count):
            end = chunk.index(0, cursor)
            yield group, index, cursor, chunk[cursor:end]
            cursor = end + 1


def rebuild_page(row):
    records = b''.join(struct.pack('<BBHHH', *r['style'], *r['position']) +
                       bytes.fromhex(r['raw_hex']) + b'\0' for r in row['records'])
    return (struct.pack('<H', len(records)) + records +
            struct.pack('<H', len(bytes.fromhex(row['sprite_hex']))) +
            bytes.fromhex(row['sprite_hex']) + bytes(row['padding_size']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    archive_path = out.with_suffix('.zip')
    require(not out.exists() and not archive_path.exists(), 'Refusing to overwrite an existing export')
    receipt_bytes = CURRENT_ISO.with_suffix('.json').read_bytes()
    receipt = json.loads(receipt_bytes)
    iso_stat = CURRENT_ISO.stat()
    require(file_sha(CURRENT_ISO) == receipt['iso']['sha256'], 'Current ISO receipt mismatch')
    native_bytes = NATIVE.read_bytes()
    native = {r['id']: r for r in json.loads(native_bytes)['entries']}
    table, _, overrides, runtime = encoding_tables(PROPOSAL)
    locks = {r['path']: r for r in json.loads(DISC_INVENTORY.read_text())['sp']['members']}
    chunks = []
    inputs = []
    for iso in (SOURCE_ISO, CURRENT_ISO):
        members = member_map(scan_iso9660(iso))
        data = {name: read_member(iso, members, name) for name in ('SLPS_259.20', 'DATA/NISVDATA.BIN')}
        if iso == SOURCE_ISO:
            for name, blob in data.items():
                require(sha(blob) == locks[name]['sha256'], f'Source lock mismatch: {name}')
        a, b = struct.unpack_from('<II', data['SLPS_259.20'], 0x384A00 + 24)
        chunk = decode_production(data['DATA/NISVDATA.BIN'][a:b]).output
        chunks.append(chunk)
        inputs.append(dict(iso=str(iso.relative_to(ROOT)), members={n: sha(v) for n, v in data.items()},
                           qa_slot=[a, b], decoded_sha256=sha(chunk)))
    source, current = chunks
    text = lambda raw, t=table: decode_text(raw + b'\0', 0, t).text
    entries = []
    residual = []
    questions = {i+1: text(raw) for group, i, _, raw in metadata(source) if group == 'questions'}

    def reference(id_, source_text):
        r = native.get(id_)
        require(r is not None and r['source_text'] == source_text and
                r['source_text_sha256'] == sha(source_text.encode()), f'Reviewed source mismatch: {id_}')
        return dict(corpus_path=str(NATIVE.relative_to(ROOT)),
            source_text_sha256=r['source_text_sha256'], translation=r['translation'],
            editorial_status=r['editorial_status'], writeback_status=r['writeback_status'],
            terminology_check=r.get('terminology_check'), review_notes=r.get('review_notes', ''),
            review_resolution=r.get('review_resolution'))

    for number in range(1, 103):
        jp, now = page(source, number), page(current, number)
        source_text = qa_lines([(r['y'], text(r['raw'])) for r in jp['records']])
        unchanged = [r['raw'] for r in jp['records']] == [r['raw'] for r in now['records']]
        if not unchanged:
            if any(KANA.search(text(r['raw'], runtime)) for r in now['records']):
                residual.append(dict(page=number, reason='kana_in_modified_page'))
            continue
        if not KANA.search(source_text):
            continue
        id_ = f'sd/nisv/qa/page/{number:03d}'
        row = dict(id=id_, kind='page', page=number, question_japanese=questions[number],
            source_text=source_text, source_text_sha256=sha(source_text.encode()),
            source_equals_current_text_bytes=True, source_allocation_offset=jp['start'],
            current_allocation_offset=now['start'], allocation_size=now['size'],
            text_section_size=now['text_size'], sprite_hex=now['sprite_bytes'].hex(),
            padding_size=now['padding_size'], records=[], reference=reference(id_, source_text))
        for index, (s, r) in enumerate(zip(jp['records'], now['records'])):
            row['records'].append(dict(id=f'{id_}/record/{index:03d}', ordinal=index,
                source_offset=s['offset'], current_offset=r['offset'], style=[r['style0'], r['style1']],
                position=[r['x'], r['y'], r['z']], source_position=[s['x'], s['y'], s['z']],
                source_header_hex=s['header'].hex(), header_hex=r['header'].hex(), raw_hex=r['raw'].hex(),
                byte_length=len(r['raw']), terminator_hex='00', japanese=text(r['raw']),
                current_font_decode_diagnostic=text(r['raw'], runtime)))
        raw = current[now['start']:now['start'] + now['size']]
        require(rebuild_page(row) == raw, f'Page structure round-trip failed: {id_}')
        row['allocation_sha256'] = sha(raw)
        row['raw_file'] = f'raw/page-{number:03d}.bin'
        row['tagged_source'] = '\n'.join(
            f'[[R{r["ordinal"]:03d} style={r["style"][0]:02X}:{r["style"][1]:02X} xyz={",".join(map(str,r["position"]))}]]'
            + r['japanese'] + f'[[/R{r["ordinal"]:03d}]]' for r in row['records'])
        entries.append(row)
    for (group, index, _, jp), (g, i, offset, now) in zip(metadata(source), metadata(current)):
        require((g, i) == (group, index), 'Metadata order mismatch')
        if jp != now:
            if KANA.search(text(now, runtime)):
                residual.append(dict(group=group, index=index, reason='kana_in_modified_metadata'))
            continue
        source_text = text(jp)
        id_ = f'sd/nisv/qa/metadata/{group}/{index:03d}'
        # Japanese-only kanji such as 地形効果 has no kana; keep known pending
        # source-locked entries even when a kana heuristic cannot detect them.
        if not KANA.search(source_text) and id_ not in native:
            continue
        entries.append(dict(id=id_, kind='metadata', group=group, index=index,
            source_text=source_text, source_text_sha256=sha(source_text.encode()),
            source_equals_current_text_bytes=True, current_offset=offset, raw_hex=now.hex(),
            byte_length=len(now), terminator_hex='00', raw_file=f'raw/{group}-{index:03d}.bin',
            current_font_decode_diagnostic=text(now, runtime),
            tagged_source=f'[[META {group}/{index:03d}]]'+source_text+f'[[/META {group}/{index:03d}]]',
            reference=reference(id_, source_text)))
    # Check the other side as well; this is a component, not an Original ISO claim.
    _, original, _ = compile_original(table, overrides)
    original_residual = [dict(page=n, record=i) for n in range(1, 103)
        for i, r in enumerate(page(original, n)['records']) if KANA.search(text(r['raw'], runtime))]
    original_residual += [dict(group=g, index=i) for g, i, _, raw in metadata(original)
                          if KANA.search(text(raw, runtime))]
    require(not residual, f'Unexported mixed Japanese requires investigation: {residual}')
    # Read-only work must not silently mix an ISO changed by another task.
    identity = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    require(identity(CURRENT_ISO.stat()) == identity(iso_stat) and CURRENT_ISO.with_suffix('.json').read_bytes() == receipt_bytes,
            'Current ISO changed during export; rerun against the new snapshot')
    require(NATIVE.read_bytes() == native_bytes, 'Reviewed corpus changed during export')
    out.mkdir(parents=True)
    (out / 'raw').mkdir()
    (out / 'pages').mkdir()
    for row in entries:
        raw = rebuild_page(row) if row['kind'] == 'page' else bytes.fromhex(row['raw_hex']) + b'\0'
        (out / row['raw_file']).write_bytes(raw)
    write_json(out / 'qa-japanese.json', dict(schema_version=1, iso=receipt['iso'], entries=entries))
    write_json(out / 'qa-review.json', dict(schema_version=1,
        instructions='仅填写 review_translation 与 review_notes；id 和 source_text_sha256 不改。格式标记是导出结构，不是游戏控制码。',
        entries=[dict(id=r['id'], source_text_sha256=r['source_text_sha256'],
                      review_translation='', review_notes='') for r in entries]))
    tag_parts = []
    combined_md = ['# SP Q&A 剩余日文：完整对照与校订稿', '',
                   '格式说明及来源校验见 README.md；记录结构以 qa-japanese.json 为准。', '']
    metadata_md = ['# Q&A 剩余日文：标题与关键词摘要', '']
    for r in entries:
        title = f'第 {r["page"]} 页 · {r["question_japanese"]}' if r['kind'] == 'page' else r['id']
        lines = [f'# {title}', '', f'ID：`{r["id"]}`', '',
            '现有稿标记为 reviewed，但尚未写回。下面的日文按原始日文字表还原。', '',
            '## 日文原文（按显示行合并，仅供阅读）', '', '````text', r['source_text'], '````', '',
            '## 现有中文稿（参考，尚未排版入盘）', '', '````text', r['reference']['translation'], '````', '',
            '## 格式保留稿', '', '同一 y 的记录属于同一显示行；标记与换行不应当作待翻译文字。', '',
            '````text', r['tagged_source'], '````', '',
            '## 校订译文', '', '````text', '', '````', '', '## 校订备注', '', '',
            '## 原有审校备注及后续裁定', '', r['reference']['review_notes'], '',
            json.dumps(r['reference']['review_resolution'], ensure_ascii=False, indent=2) if r['reference']['review_resolution'] else '无额外裁定。', '']
        if r['kind'] == 'page':
            (out / 'pages' / f'{r["page"]:03d}.md').write_text('\n'.join(lines))
        else:
            metadata_md += lines
        combined_md += lines
        tag_parts += [f'=== {r["id"]} ===', r['tagged_source'], '']
    (out / 'metadata.md').write_text('\n'.join(metadata_md))
    (out / 'review-all.md').write_text('\n'.join(combined_md))
    (out / 'tagged-source.txt').write_text('\n'.join(tag_parts))
    counts = collections.Counter(r['kind'] for r in entries)
    symbols = collections.Counter(ch for r in entries for ch in r['source_text']
        if ch in '○×△□※＋－−〜～→↓％%／・＜＞「」『』（）：')
    controls = [dict(id=r['id'], tokens=RUNTIME_FORMAT_TOKEN.findall(r['source_text'])) for r in entries
                if RUNTIME_FORMAT_TOKEN.search(r['source_text'])]
    readme = f'''# SP Q&A 剩余日文导出

当前 ISO：`{receipt['iso']['path']}`；SHA-256：`{receipt['iso']['sha256']}`。
扫描范围仅为 Q&A：两边各 102 页正文及 264 条元数据，不代表整张游戏的日文清查。

共 {counts['page']} 页正文、{counts['metadata']} 条标题／关键词摘要，均为当前 SP 保留的原日文字节。
这些条目全部已有 reviewed 中文稿，仍待绑定、术语核对和排版写回。
Original 当前语料编译组件中的假名残留候选：{len(original_residual)}；没有 Original ISO 回读声明。

## 文件

- `review-all.md`：全部 37 条日文／中文对照及校订区，适合一次性阅读或交给审校。
- `pages/*.md`：每页日文、现有中文参考、格式标记和校订区。
- `metadata.md`：标题及关键词摘要，保留全角空格和实际换行。
- `tagged-source.txt`：全部日文的带标记版本。
- `qa-japanese.json`：完整结构；保留原始字节、样式、x/y/z、偏移、空记录、图片段及填充。
- `qa-review.json`：可填写的整页／整条校订稿；仅改 `review_translation`、`review_notes`。
- `raw/`：对应页的完整二进制分配区，以及元数据的原始 NUL 结尾字节。
- `manifest.json`：来源、覆盖范围、特殊符号和逐文件哈希。

## 特殊格式约定

1. `[[R000 style=04:00 xyz=0,1,1]]…[[/R000]]` 是本次导出的结构标记，不是游戏控制码。ID、style、xyz 和开闭标记不翻译、不删除；只翻译中间文字。整页校订也可填入 `qa-review.json`，后续再绑定颜色和布局。
2. 样式两个字节原样保存，不把样式值擅自解释成可编辑颜色名。同 y 不同 x 可能是不同颜色片段，也可能是表格列，不能用顺序拼接文本替代表格结构。z 和空记录同样保留。
3. 正文阅读稿的换行由坐标重建；格式稿一条记录一行，不等同于游戏换行。元数据中的实际 `\\n` 控制字节、全角空格 `U+3000` 均原样保留。JSON 的 `\\n` 是真实换行的序列化表达，不是反斜杠加 n 两个字。
4. 保留数字、百分比、正负号、箭头、按钮符号和 Latin 缩写；`SR`、`PP`、`EN`、`HP`、`PLA`、`Pls`、`START`、`SELECT`、`L1/R1` 等不能因换行被拆散。原日文的全角 Latin／数字保存在源字段，中文如何用半角沿用项目规则。
5. 不正规化 `〜/～`、`−/－`、`％/%` 等看似相同的符号；准确字节以 `raw_hex` 为准。将来写回可见空格必须使用双字节 `0x8140`，不能直接塞入原始 `0x20`。
6. `current_font_decode_diagnostic` 是当前中文字库解释未替换日文字节的诊断结果，可能混杂错误字形。翻译必须以 `source_text`／`japanese` 为准。
7. 现有审校备注可能包含早期术语建议；如有 `review_resolution`，同时查看后续裁定，不能只按旧备注覆盖现有译文。
8. 本工具只导出。填写稿件不会自动修改语料或 ISO，也不证明文字已适配原页面容量；回写前仍须重新排版、检查颜色／表格／数字和压缩预算。

## 正文目录

''' + '\n'.join(f'- [{r["page"]:03d} · {r["question_japanese"]}](pages/{r["page"]:03d}.md)' for r in entries if r['kind']=='page') + '\n'
    (out / 'README.md').write_text(readme)
    # Re-read the exported JSON: verify that serialization preserved every byte.
    saved = json.loads((out / 'qa-japanese.json').read_text())['entries']
    for row in saved:
        actual = rebuild_page(row) if row['kind'] == 'page' else bytes.fromhex(row['raw_hex']) + b'\0'
        require(actual == (out / row['raw_file']).read_bytes(), f'Export round-trip mismatch: {row["id"]}')
        require(sha(row['source_text'].encode()) == row['source_text_sha256'], 'Export source text mismatch')
    files = {str(p.relative_to(out)): dict(size=p.stat().st_size, sha256=file_sha(p)) for p in sorted(out.rglob('*')) if p.is_file()}
    manifest = dict(schema_version=1, scope='Q&A only', iso=receipt['iso'], inputs=inputs,
        reviewed_corpus=dict(path=str(NATIVE.relative_to(ROOT)), sha256=sha(native_bytes)),
        proposal_sha256=file_sha(PROPOSAL), counts=dict(counts),
        pages=[r['page'] for r in entries if r['kind']=='page'],
        record_count=sum(len(r.get('records', [])) for r in entries),
        metadata_groups=dict(collections.Counter(r['group'] for r in entries if r['kind']=='metadata')),
        special_symbols=dict(symbols), runtime_format_tokens=controls,
        unexported_mixed_japanese=residual, original_component_kana_candidates=original_residual,
        all_source_hashes_match_reviewed_corpus=True, lossless_binary_roundtrip=True,
        corpus_modified=False, iso_modified=False, files=files)
    write_json(out / 'manifest.json', manifest)
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(out.rglob('*')):
            if p.is_file():
                archive.write(p, Path(out.name) / p.relative_to(out))
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None, 'ZIP CRC validation failed')
    print(json.dumps(dict(directory=str(out), zip=str(archive_path), counts=dict(counts),
        record_count=manifest['record_count'], original_component_kana_candidates=original_residual,
        lossless_binary_roundtrip=True), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
