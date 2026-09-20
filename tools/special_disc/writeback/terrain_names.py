"""Write locked SP MAPMODEL terrain records, including maps without OG matches."""
from __future__ import annotations

import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path

from srwz.codec import SrwzEncodeError, decode_production, reencode_changed_suffix
from srwz.text import PreparedTextEncoder, decode_text

ROOT = Path(__file__).resolve().parents[3]
MEMBER = 'MAP/MAPMODEL.BIN'
CONTRACT = ROOT / 'config/products/special-disc/terrain-name-inventory.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inputs(exe, archive):
    contract = json.loads(CONTRACT.read_text())
    lock = contract['offset_table']
    raw = exe[lock['start']:lock['start'] + lock['count'] * 4]
    require(sha(raw) == lock['sha256'], 'SP terrain offset table drift')
    offsets = struct.unpack(f"<{lock['count']}I", raw)
    require(len(archive) == contract['source_archive']['size'] == offsets[-1], 'SP terrain archive size drift')
    corpus = ROOT / contract['corpus']['path']
    require(sha(corpus.read_bytes()) == contract['corpus']['sha256'], 'SP terrain corpus drift')
    translations = {r['source']: r['translation'] for r in json.loads(corpus.read_text())['entries']}
    rows = contract['occurrences']
    require(len(rows) == contract['expected']['occurrence_count'], 'SP terrain inventory count drift')
    require(len({r['member'] for r in rows}) == contract['expected']['member_count'], 'SP terrain member count drift')
    grouped = defaultdict(list)
    for row in rows:
        require(row['source'] in translations, 'SP terrain untranslated source')
        grouped[row['member']].append(row)
    return contract, offsets, translations, grouped


def verify_terrain_names(archive, exe, readback):
    contract, offsets, translations, grouped = inputs(exe, archive)
    for index, rows in grouped.items():
        data = decode_production(archive[offsets[index]:offsets[index + 1]]).output
        for row in rows:
            at = row['decoded_offset']
            actual = decode_text(data, at, readback, end=at + 24)
            require(actual.text == translations[row['source']] and actual.terminator == 'nul',
                    f'SP terrain readback mismatch: member {index} offset {at:#x}')
    return dict(contract['expected'])


def apply_terrain_names(archive, exe, source, table, overrides, readback):
    contract, offsets, translations, grouped = inputs(exe, archive)
    require(sha(source) == contract['source_archive']['sha256'], 'SP terrain original archive drift')
    encoder = PreparedTextEncoder(table, overrides)
    output = bytearray(archive)
    changed = []
    for index, rows in grouped.items():
        a, b = offsets[index:index + 2]
        original = decode_production(source[a:b]).output
        decoded = decode_production(archive[a:b])
        data = bytearray(decoded.output)
        require(len(data) == len(original), f'SP terrain decoded size drift: {index}')
        for row in rows:
            at, size = row['decoded_offset'], row['source_consumed']
            before = decode_text(original, at, table, end=at + 24)
            require(before.text == row['source'] and before.consumed == size,
                    f'SP terrain source record drift: {index}/{at:#x}')
            encoded = encoder.encode(translations[row['source']], terminate=True)
            require(len(encoded) <= size, f'SP terrain text overflow: {index}/{at:#x}')
            replacement = encoded + bytes(size - len(encoded))
            current = decode_text(bytes(data), at, readback, end=at + size)
            require(bytes(data[at:at + size]) == original[at:at + size]
                    or (current.text == translations[row['source']] and current.terminator == 'nul'),
                    f'SP terrain preimage drift: {index}/{at:#x}')
            if current.text == translations[row['source']] and current.terminator == 'nul':
                continue
            data[at:at + size] = replacement
        if data == decoded.output:
            continue
        # Only locked string spans above change; existing title images stay intact.
        try:
            packed = reencode_changed_suffix(archive[a:b], bytes(data), strategy='rust-fit',
                                             max_output_size=b-a, original_result=decoded)
        except SrwzEncodeError:
            packed = reencode_changed_suffix(archive[a:b], bytes(data), strategy='rust-maximum',
                                             max_output_size=b-a, original_result=decoded)
        require(len(packed) <= b-a, f'SP terrain compressed slot overflow: {index}')
        require(decode_production(packed).output == data, 'SP terrain codec readback')
        output[a:b] = packed + bytes(b-a-len(packed))
        changed.append(index)
    output = bytes(output)
    counts = verify_terrain_names(output, exe, readback)
    return output, dict(**counts, changed_members=changed, contract_sha256=sha(CONTRACT.read_bytes()),
                        corpus=contract['corpus'], runtime='pending')
