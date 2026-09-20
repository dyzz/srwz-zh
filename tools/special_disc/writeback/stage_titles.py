"""Install frozen SP stage-entry titles without rasterizing during builds."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.stage_title_snapshot import thaw_indexes
from srwz.tim2 import scan_tim2

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / 'config/assets/special-disc/stage-title-graphics.json'
CORPUS = ROOT / 'corpus/zh/special-disc/frame-text.json'
MEMBER = 'DATA/VT1.BIN'
GROUP_TABLE = 0x353790
TITLE_TABLE = 0x3763E0
RECORD_START = 0x68630
RECORD_STRIDE = 48


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def title_entries():
    rows = [r for r in json.loads(CORPUS.read_text())['entries']
            if r['category'] == 'episode-title']
    require(len(rows) == 21 and len({r['id'] for r in rows}) == 21,
            'SP stage-title corpus scope drift')
    return {r['id']: r for r in rows}


def image_span(data):
    records = scan_tim2(data)
    require(len(data) == 0x40E0 and len(records) == 1 and
            records[0].offset == 0x20 and len(records[0].pictures) == 1,
            'SP stage-title container drift')
    pic = records[0].pictures[0]
    require((pic.width, pic.height, pic.image_type, pic.image_size, pic.clut_color_count)
            == (512, 64, 4, 16384, 32), 'SP stage-title picture layout drift')
    start = pic.offset + pic.header_size
    return start, start + pic.image_size


def inputs(exe):
    snapshot = json.loads(SNAPSHOT.read_text())
    require(snapshot['schema_version'] == 1 and snapshot['status'] == 'frozen_indexed_stage_titles',
            'SP stage-title snapshot policy drift')
    a, b = struct.unpack_from('<2I', exe, GROUP_TABLE + 9 * 4)
    table = exe[TITLE_TABLE:TITLE_TABLE + 28 * 4]
    require([a, b] == snapshot['group_range'] and sha(table) == snapshot['table_sha256'],
            'SP stage-title placement drift')
    offsets = struct.unpack('<28I', table)
    require(offsets[0] == 0 and offsets[-1] == b - a and
            all(x < y for x, y in zip(offsets, offsets[1:])),
            'SP stage-title offsets invalid')
    rows = title_entries()
    titles = snapshot['titles']
    require(len(titles) == 21 and [t['selector'] for t in titles] == list(range(1, 22)) and
            {t['corpus_id'] for t in titles} == set(rows), 'SP stage-title coverage drift')
    for title in titles:
        row = rows[title['corpus_id']]
        require(title['translation'] == row['translation'] and
                title['source_text_sha256'] == row['source_text_sha256'] and
                title['locations'] == row['locations'], 'SP stage-title translation/binding drift')
        require(title['table_index'] == title['selector'] + 5,
                'SP stage-title selector mapping drift')
    return snapshot, offsets, a, b


def verify_title_bindings(compdata):
    """Lock native selectors and branch aliases while allowing translated pointers."""
    snapshot = json.loads(SNAPSHOT.read_text())
    for title in snapshot['titles']:
        for native in title['native_records']:
            at = RECORD_START + (native['chunk'] - 1) * RECORD_STRIDE
            record = compdata[at:at + RECORD_STRIDE]
            require(record[4:] == bytes.fromhex(native['record_hex'])[4:] and
                    struct.unpack_from('<H', record, 28)[0] == title['selector'],
                    'SP stage-title native selector/branch binding drift')


def verify_stage_titles(archive, exe):
    snapshot, offsets, a, b = inputs(exe)
    require(sha(archive[a:b]) == snapshot['output_group_sha256'],
            'SP stage-title output group drift')
    for title in snapshot['titles']:
        i = title['table_index']
        stored = archive[a + offsets[i]:a + offsets[i + 1]]
        require(sha(stored) == title['output_stored_sha256'], 'SP stage-title output slot drift')
        decoded = decode_production(stored)
        start, end = image_span(decoded.output)
        require(decoded.output[start:end] == thaw_indexes(title['packed_indexes']) and
                sha(decoded.output[:start] + decoded.output[end:]) == title['non_image_sha256'] and
                not any(stored[decoded.consumed:]), 'SP stage-title pixels/palette/trailer drift')
    return dict(count=21, rewritten=sum(not t['preserve_original'] for t in snapshot['titles']),
                group_sha256=sha(archive[a:b]), titles=[dict(selector=t['selector'],
                translation=t['translation'], chunks=t['stage_chunks']) for t in snapshot['titles']])


def apply_stage_titles(archive, exe):
    snapshot, offsets, a, b = inputs(exe)
    require(sha(archive[a:b]) == snapshot['source_group_sha256'],
            'SP stage-title source group drift')
    output = bytearray(archive)
    for title in snapshot['titles']:
        i = title['table_index']
        lo, hi = a + offsets[i], a + offsets[i + 1]
        stored = archive[lo:hi]
        require(sha(stored) == title['source_stored_sha256'], 'SP stage-title source slot drift')
        decoded = decode_production(stored)
        start, end = image_span(decoded.output)
        require(sha(decoded.output[:start] + decoded.output[end:]) == title['non_image_sha256'],
                'SP stage-title source palette/trailer drift')
        if title['preserve_original']:
            encoded = stored
        else:
            data = decoded.output[:start] + thaw_indexes(title['packed_indexes']) + decoded.output[end:]
            encoded = reencode_changed_suffix(stored, data, strategy='rust-maximum',
                                             original_result=decoded)
            require(len(encoded) <= hi - lo, 'SP stage-title slot overflow')
            encoded += bytes(hi - lo - len(encoded))
            require(decode_production(encoded).output == data, 'SP stage-title codec readback failed')
        require(sha(encoded) == title['output_stored_sha256'], 'SP stage-title frozen codec drift')
        output[lo:hi] = encoded
    result = bytes(output)
    require(result[:a + offsets[6]] == archive[:a + offsets[6]] and result[b:] == archive[b:],
            'SP stage-title non-target archive bytes changed')
    report = verify_stage_titles(result, exe)
    report.update(snapshot=dict(path=str(SNAPSHOT.relative_to(ROOT)), sha256=sha(SNAPSHOT.read_bytes())),
                  corpus_sha256=sha(CORPUS.read_bytes()), runtime='pending')
    return result, report
