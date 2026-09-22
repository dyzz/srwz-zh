"""Bind reviewed SP answers to styled records inside the original allocations."""
from collections import defaultdict
import json
import struct

from srwz.text import PreparedTextEncoder, decode_text, project_runtime_text_table, two_byte_visible_spaces
from srwz.nisv_strategy_qa import QA_METADATA_GROUPS
from special_disc.writeback.qa_layout import ROOT, page, require, sha, compile_original
from special_disc.writeback.slot_codec import encode_slot
from srwz.codec import decode_production, reencode_changed_suffix

LAYOUT = ROOT / 'config/products/special-disc/qa-layout.json'
CORPUS = ROOT / 'corpus/zh/special-disc/native-text.json'
from srwz.qa_typography import (
    MAX_X, CLOSE, OPEN, ATOMIC, PROTECTED, legal_break, split_glyphs,
    emit, flow, styled_runs, shared_records, repair_shared, validate_records,
    pack_page,
)


def native_records(binding, entry):
    text = entry['translation']
    require(sha(text.encode()) == binding['translation_sha256'], 'Q&A colour binding translation drift')
    require('\n'.join(line['text'] for line in binding['lines']) == text, 'Q&A paragraphs changed')
    records, y = [], 25
    for line in binding['lines']:
        kind, t = line['kind'], line['text']
        if kind == 'title':
            require(t.startswith('A．'), 'Q&A answer title drift')
            records.extend([dict(text=t[:2], style=[4,0], position=[0,1,1]),
                            dict(text=t[2:], style=[4,6], position=[46,1,1])])
            continue
        if kind == 'blank':
            y += 11
            continue
        if kind == 'heading':
            records.append(dict(text=t, style=[2,14], position=[38,y,1]))
        elif kind == 'table':
            require(''.join(c['text'] for c in line['cells']) == t, 'Q&A table text mismatch')
            records.extend(dict(text=c['text'], style=c['style'], position=[c['x'],y,1]) for c in line['cells'])
        else:
            require(''.join(r['text'] for r in line['runs']) == t, 'Q&A colour span text mismatch')
            added,y = flow(line['runs'], line['first_x'], line['continuation_x'], y)
            records.extend(added)
        y += 11
    require(''.join(r['text'] for r in records) == text.replace('\n',''), 'Q&A translation loss')
    validate_records(records)
    return records


def metadata(chunk):
    cursor = 0x476
    result = []
    for group,count in QA_METADATA_GROUPS:
        for index in range(count):
            end = chunk.index(0, cursor)
            result.append((group,index,chunk[cursor:end]))
            cursor = end+1
    return result


def apply_reviewed_chunk(current, source, original_jp, original_zh, table, overrides, *, runtime_table=None):
    bindings = json.loads(LAYOUT.read_text())
    require((bindings['glyph_advance'],bindings['line_step'],bindings['max_last_glyph_x']) ==
            (19,11,MAX_X), 'Q&A layout metrics drift')
    native = {e['id']:e for e in json.loads(CORPUS.read_text())['entries']}
    runtime = runtime_table if runtime_table is not None else project_runtime_text_table(table, overrides)
    encoder = PreparedTextEncoder(table, overrides)
    output = bytearray(current)
    report = dict(native_pages=[], shared_layout_repairs=[], metadata=[], page_records=[])
    by_page = {e['page']:e for e in bindings['pages']}
    for n in range(1,103):
        jp, og, zh, now = [page(chunk,n) for chunk in (source,original_jp,original_zh,current)]
        if n in by_page:
            b = by_page[n]; e = native[b['id']]
            rows = defaultdict(list)
            for r in jp['records']:
                rows[r['y']].append(decode_text(r['raw']+b'\0',0,table).text)
            source_text = '\n'.join(''.join(rs) for rs in rows.values())
            require(sha(source_text.encode()) == e['source_text_sha256'] == b['source_text_sha256'], 'Native Q&A source drift')
            records = native_records(b,e)
            require({tuple(r['style']) for r in records} <= {(r['style0'],r['style1']) for r in jp['records']}, 'Native Q&A new style code')
            report['native_pages'].append(n)
            require([r['raw'] for r in now['records']] == [r['raw'] for r in jp['records']] or
                    styled_runs(shared_records(now,runtime)) == styled_runs(records),
                    f'Concurrent native Q&A text/style drift: {n}')
        else:
            require(source[jp['start']:jp['start']+jp['size']] == original_jp[og['start']:og['start']+og['size']], 'Unreviewed SP answer differs')
            require(jp['size'] == zh['size'], 'Shared Q&A allocation size drift')
            require(styled_runs(shared_records(now,runtime)) == styled_runs(shared_records(zh,runtime)),
                    f'Concurrent shared Q&A text/style drift: {n}')
            records, fixes = repair_shared(shared_records(zh,runtime))
            if fixes:
                report['shared_layout_repairs'].append(dict(page=n,repairs=fixes))
        validate_records(records)
        require(now['size'] == jp['size'] and now['sprite_bytes'] == jp['sprite_bytes'], 'SP Q&A allocation/sprite drift')
        payload,padding = pack_page(jp,records,encoder,runtime)
        output[now['start']:now['start']+now['size']] = payload
        report['page_records'].append(dict(page=n,records=records,allocation=jp['size'],padding=padding))
    # Rebuild only the sequential strings; metadata indexes remain byte exact.
    chunks = [metadata(c) for c in (source,original_jp,original_zh,current)]
    blob = bytearray()
    for (group,index,jp),(_,_,og),(_,_,zh),(_,_,now) in zip(*chunks):
        id_ = f'sd/nisv/qa/metadata/{group}/{index:03d}'
        if jp != og:
            e = native[id_]
            require(sha(decode_text(jp+b'\0',0,table).text.encode()) == e['source_text_sha256'], 'Q&A metadata source drift')
            text = e['translation']
            encoded = encoder.encode(two_byte_visible_spaces(text),terminate=True)
            require(decode_text(encoded,0,runtime).text == two_byte_visible_spaces(text), 'Q&A metadata readback')
            require(b'\x20' not in encoded, 'Metadata raw visible space')
            require(now == jp or decode_text(now+b'\0',0,runtime).text == two_byte_visible_spaces(text),
                    f'Concurrent native Q&A metadata drift: {id_}')
            blob += encoded
            report['metadata'].append(dict(id=id_,translation=text))
        else:
            require(decode_text(now+b'\0',0,runtime).text == decode_text(zh+b'\0',0,runtime).text,
                    f'Concurrent shared Q&A metadata drift: {id_}')
            blob += zh+b'\0'
    end = page(source,1)['start']
    require(len(blob) <= end-0x476, 'Q&A metadata allocation overflow')
    require(current[0x350:0x476] == source[0x350:0x476], 'Q&A metadata index drift')
    output[0x476:end] = blob + bytes(end-0x476-len(blob))
    require(output[:0x476] == current[:0x476], 'Q&A allocation table/index changed')
    report.update(metadata_padding=end-0x476-len(blob),layout_sha256=sha(LAYOUT.read_bytes()),
                  corpus_sha256=sha(CORPUS.read_bytes()),runtime='pending')
    require(len(report['native_pages']) == 22 and len(report['metadata']) == 15, 'Q&A reviewed inventory drift')
    return bytes(output),report


def apply_reviewed_qa(archive, exe, source, table, overrides, *, runtime_table=None):
    a,b = struct.unpack_from('<II',exe,0x384A00+24)
    require(0 < a < b <= len(archive) == len(source), 'SP Q&A slot drift')
    original_jp,original_zh,inputs = compile_original(table,overrides)
    decoded = decode_production(archive[a:b])
    output,report = apply_reviewed_chunk(decoded.output,decode_production(source[a:b]).output,
                                         original_jp,original_zh,table,overrides,runtime_table=runtime_table)
    changed = [n for n in range(1,103) if
        output[page(output,n)['start']:page(output,n)['start']+page(output,n)['size']] !=
        decoded.output[page(decoded.output,n)['start']:page(decoded.output,n)['start']+page(decoded.output,n)['size']]]
    report.update(inputs=inputs,changed_pages=changed,decoded_sha256=sha(output),
                  metadata_changed=output[0x476:page(output,1)['start']] != decoded.output[0x476:page(output,1)['start']])
    if output == decoded.output:
        return archive,report
    packed = encode_slot(archive[a:b],output,
                                     max_output_size=b-a,original_result=decoded)
    require(len(packed) <= b-a and decode_production(packed).output == output, 'SP Q&A compressed readback')
    report.update(stored_size=len(packed),stored_budget=b-a)
    return archive[:a]+packed+bytes(b-a-len(packed))+archive[b:],report
