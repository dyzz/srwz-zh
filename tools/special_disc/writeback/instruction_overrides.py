"""Apply scoped SP instruction revisions after inherited text components.

Fixed fields keep their original allocations and pointers. Q&A/tutorial pages
keep allocation tables and sprite bytes; every other page and metadata string
is protected. A pinned preimage prevents later source edits being overwritten.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct

from special_disc.writeback.slot_codec import encode_slot
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import PreparedTextEncoder, decode_text, normalize_original_fullwidth_ascii, two_byte_visible_spaces
from srwz.nisv_tutorial import parse_nisv_tutorial_pages
from srwz.qa_typography import pack_page, shared_records, validate_records
from special_disc.writeback.qa_layout import page
from special_disc.writeback.qa_native import metadata
from special_disc.writeback.exe_data_guard import require_text_range

ROOT = Path(__file__).resolve().parents[3]
CORPUS = 'corpus/zh/special-disc/instructions-overrides.json'
LAYOUT = 'config/editorial/special-disc/instructions-layout.json'
EXE, CD, NISV = 'SLPS_259.20', 'DATA/COMPDATA.BN', 'DATA/NISVDATA.BIN'
TABLE = 0x384A00


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def normalize(text):
    return two_byte_visible_spaces(normalize_original_fullwidth_ascii(text))


def record_hash(records):
    return sha(json.dumps(records, ensure_ascii=False, separators=(',', ':')))


def page_text(parsed, table):
    lines, current, last = [], '', None
    for r in parsed['records']:
        if last is not None and r['y'] != last:
            lines.append(current)
            current = ''
        current += decode_text(r['raw'] + b'\0', 0, table).text
        last = r['y']
    lines.append(current)
    return '\n'.join(line for line in lines if line)


def get_page(data, chunk, number):
    return parse_nisv_tutorial_pages(data)[number] if chunk == 5 else page(data, number)


def validate_layout(records, chunk):
    if chunk == 6:
        validate_records(records)
        return
    by_row = defaultdict(list)
    for r in records:
        x, y, z = r['position']
        advance = {1: 17, 2: 19, 3: 21, 4: 23}[r['style'][0]]
        require(x >= 0 and 0 <= y <= 200 and z == 1, 'Tutorial position drift')
        require(x + (len(r['text']) - 1) * advance <= 513, 'Tutorial width overflow')
        if r['text']:
            by_row[y].append((x, x + len(r['text']) * advance))
    for row in by_row.values():
        row.sort()
        require(all(a[1] <= b[0] for a, b in zip(row, row[1:])), 'Tutorial record overlap')


def load(root):
    corpus = json.loads((root / CORPUS).read_text())
    layout = json.loads((root / LAYOUT).read_text())
    require(corpus['schema_version'] == layout['schema_version'] == 1, 'Instruction schema drift')
    rows = corpus['entries']
    require(len({r['id'] for r in rows}) == len(rows), 'Duplicate instruction IDs')
    for r in rows:
        require(sha(r['source_text']) == r['source_text_sha256'], 'Instruction source hash drift')
    pages = {r['id']: r for r in layout['pages']}
    require(len(pages) == len(layout['pages']) and set(pages) == {r['id'] for r in rows if r['kind'] == 'page'},
            'Instruction layout coverage drift')
    require(all(r['kind'] in ('fixed', 'metadata', 'page') for r in rows), 'Unknown instruction kind')
    return rows, pages


def apply_fixed(data, original, rows, encoder, table, runtime):
    """Only predeclared string allocations can change; all pointers stay exact."""
    output = bytearray(data)
    spans = []
    for r in rows:
        loc = r['location']; at, size = loc['offset'], loc['capacity']
        require(0 <= at < at + size <= len(data) == len(original), 'Instruction range outside member')
        if loc['member'] == EXE:
            require_text_range(at, size)
        src = decode_text(original, at, table)
        require(src.text == r['source_text'], 'Instruction native source drift: ' + r['id'])
        require(src.consumed <= size <= ((at + src.consumed + 7) & ~7) - at and
                not any(original[at + src.consumed:at + size]), 'Instruction capacity is not original padding')
        require(sha(original[at:at + size]) == loc['source_slot_sha256'], 'Instruction source allocation drift')
        require(sha(data[at:at + size]) == loc['baseline_slot_sha256'], 'Instruction preimage drift: ' + r['id'])
        require(decode_text(data, at, runtime).text == r['baseline_translation'], 'Instruction baseline text drift')
        for site in loc.get('pointer_sites', []):
            require(struct.unpack_from('<I', data, site)[0] == struct.unpack_from('<I', original, site)[0]
                    == 0x764F80 + at, 'Instruction pointer drift')
        require(not any(at < b and a < at + size for a, b in spans), 'Overlapping instruction allocations')
        payload = encoder.encode(normalize(r['translation']), terminate=True)
        require(len(payload) <= size, 'Instruction fixed-slot overflow: ' + r['id'])
        require(decode_text(payload, 0, runtime).text == normalize(r['translation']), 'Instruction encoding drift')
        output[at:at + size] = payload + bytes(size - len(payload)); spans.append((at, at + size))
    # Independently protect every byte outside the authorized allocations.
    cursor = 0
    for a, b in sorted(spans):
        require(output[cursor:a] == data[cursor:a], 'Instruction out-of-scope member change'); cursor = b
    require(output[cursor:] == data[cursor:], 'Instruction member suffix changed')
    return bytes(output)


def apply_pages(current, original, chunk, rows, layouts, encoder, table, runtime):
    output = bytearray(current); spans = []
    for r in rows:
        if r['kind'] != 'page':
            continue
        binding = layouts[r['id']]
        if binding['chunk'] != chunk:
            continue
        n = binding['page']; source, before = get_page(original, chunk, n), get_page(current, chunk, n)
        require(sha(page_text(source, table)) == r['source_text_sha256'], 'Instruction page source drift: ' + r['id'])
        require(record_hash(shared_records(before, runtime)) == binding['baseline_records_sha256'],
                'Instruction page preimage drift: ' + r['id'])
        require(before['start'] == source['start'] and before['size'] == source['size'] == binding['allocation']
                and before['sprite_bytes'] == source['sprite_bytes'], 'Instruction page container drift')
        records = binding['records']
        require(sha(r['translation']) == binding['translation_sha256'] and
                ''.join(x['text'] for x in records) == r['translation'].replace('\n', ''), 'Instruction layout text drift')
        require({tuple(x['style']) for x in records} <= {(x['style0'], x['style1']) for x in source['records']},
                'Instruction introduced unsupported style')
        validate_layout(records, chunk)
        payload, _ = pack_page(source, records, encoder, runtime)
        a, b = before['start'], before['start'] + before['size']; output[a:b] = payload; spans.append((a, b))
    if chunk == 6:
        wanted = {r['id']: r for r in rows if r['kind'] == 'metadata'}; consumed = set(); blob = bytearray()
        for (g, n, src), (g2, n2, old) in zip(metadata(original), metadata(current)):
            require((g, n) == (g2, n2), 'Instruction metadata order drift')
            ident = f'sd/nisv/qa/metadata/{g}/{n:03d}'
            if ident in wanted:
                r = wanted[ident]; consumed.add(ident)
                require(sha(decode_text(src + b'\0', 0, table).text) == r['source_text_sha256'], 'Instruction metadata source drift')
                require(decode_text(old + b'\0', 0, runtime).text == r['baseline_translation'], 'Instruction metadata preimage drift')
                blob += encoder.encode(normalize(r['translation']), terminate=True)
            else:
                blob += old + b'\0'
        require(consumed == set(wanted), 'Missing instruction metadata')
        start, end = 0x476, page(original, 1)['start']
        require(len(blob) <= end - start, 'Instruction metadata overflow')
        output[start:end] = blob + bytes(end - start - len(blob)); spans.append((start, end))
    cursor = 0
    for a, b in sorted(spans):
        require(output[cursor:a] == current[cursor:a], 'Instruction non-target page/index changed'); cursor = b
    require(output[cursor:] == current[cursor:], 'Instruction chunk suffix changed')
    return bytes(output)


def apply_overrides(patches, original, table, overrides, runtime, root=ROOT):
    rows, layouts = load(root); encoder = PreparedTextEncoder(table, overrides)
    result = dict(patches); reports = []
    for name in (EXE, CD):
        source = original(name); before = result[name]; decoded = None
        if name == CD:
            source = decode_production(source).output; decoded = decode_production(before); data = decoded.output
        else:
            data = before
        targets = [r for r in rows if r['kind'] == 'fixed' and r['location']['member'] == name]
        after = apply_fixed(data, source, targets, encoder, table, runtime)
        if name == CD:
            packed = encode_slot(before, after, max_output_size=len(before), original_result=decoded)
            require(len(packed) <= len(before) and decode_production(packed).output == after, 'Instruction COMPDATA compression drift')
            result[name] = packed + bytes(len(before) - len(packed))
        else:
            result[name] = after
        reports.append(dict(member=name,targets=len(targets),decoded_sha256=sha(after)))
    archive = result[NISV]; original_archive = original(NISV); exe = result[EXE]
    for chunk in (5, 6):
        a, b = struct.unpack_from('<II', exe, TABLE + chunk * 4)
        require(0 < a < b <= len(archive) == len(original_archive), 'Instruction NISV slot drift')
        require(struct.unpack_from('<II', original(EXE), TABLE + chunk * 4) == (a, b), 'Instruction NISV offsets changed')
        stored = archive[a:b]; decoded = decode_production(stored); source = decode_production(original_archive[a:b]).output
        after = apply_pages(decoded.output, source, chunk, rows, layouts, encoder, table, runtime)
        packed = encode_slot(stored, after, max_output_size=b-a, original_result=decoded)
        require(len(packed) <= b-a and decode_production(packed).output == after, 'Instruction page compression drift')
        archive = archive[:a] + packed + bytes(b-a-len(packed)) + archive[b:]
        reports.append(dict(member=NISV,chunk=chunk,stored_size=len(packed),budget=b-a,decoded_sha256=sha(after)))
    result[NISV] = archive
    return result, dict(corpus_sha256=sha((root/CORPUS).read_bytes()),layout_sha256=sha((root/LAYOUT).read_bytes()),
                        targets=len(rows),components=reports,runtime='not_tested')


def verify_overrides(member, runtime, root=ROOT):
    """Parse the final members and compare all targets directly with author text."""
    rows, layouts = load(root); exe = member(EXE); cd = decode_production(member(CD)).output; archive = member(NISV)
    chunks = {}; results = []
    for r in rows:
        if r['kind'] == 'fixed':
            loc = r['location']; data = exe if loc['member'] == EXE else cd; at = loc['offset']
            decoded = decode_text(data, at, runtime, end=at + loc['capacity'])
            require(decoded.terminator == 'nul', 'Instruction fixed terminator missing')
            actual = decoded.text
            for site in loc.get('pointer_sites', []):
                require(struct.unpack_from('<I', data, site)[0] == 0x764F80 + at, 'Final instruction pointer drift')
        else:
            chunk = layouts[r['id']]['chunk'] if r['kind'] == 'page' else 6
            if chunk not in chunks:
                a, b = struct.unpack_from('<II', exe, TABLE + chunk * 4); chunks[chunk] = decode_production(archive[a:b]).output
            data = chunks[chunk]
            if r['kind'] == 'metadata':
                g, n = r['id'].split('/')[-2:]
                raw = next(blob for group, index, blob in metadata(data) if (group,index) == (g,int(n)))
                actual = decode_text(raw + b'\0', 0, runtime).text
            else:
                binding = layouts[r['id']]; parsed = get_page(data,chunk,binding['page']); records = shared_records(parsed,runtime)
                validate_layout(records,chunk)
                expected = [dict(x,text=normalize(x['text'])) for x in binding['records']]
                require(records == expected, 'Final instruction positions/styles differ: ' + r['id'])
                actual = ''.join(x['text'] for x in records)
        expected = normalize(r['translation'].replace('\n','') if r['kind'] == 'page' else r['translation'])
        require(actual == expected, 'Final instruction text mismatch: ' + r['id'])
        results.append(dict(id=r['id'],text_sha256=sha(actual)))
    return dict(targets=len(results),entries=results,corpus_sha256=sha((root/CORPUS).read_bytes()),layout_sha256=sha((root/LAYOUT).read_bytes()))
