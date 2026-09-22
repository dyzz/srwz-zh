"""Repair five SP keyword-list names using bounded slots and two relocations.

The translated list is independent of the KYWD article archive. Two reclaimed
tails belong to 塞文堡 and 荣耀之星; the latter also owns an empty UI label.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import decode_text, encode_text

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/keyword-list-names.json'
MEMBER = 'DATA/COMPDATA.BN'
BASE, TABLE = 0x764F80, 0x67400
WRITES = [(10, 0x88980, 16), (19, 0x889E8, 16), (21, 0x88A50, 24),
          (36, 0x88B78, 24), (41, 0x88C8A, 22)]
EMPTY = dict(pointer_offset=0x684C0, source_offset=0x88C98, target_offset=0x88C9C)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inputs():
    c = json.loads(CONTRACT.read_text())
    require((c['schema_version'], c['member'], c['decoded_size'], c['runtime_base'], c['pointer_table']) ==
            (1, MEMBER, 652800, BASE, TABLE), 'SP keyword contract drift')
    require([(s['index'], s['offset'], s['capacity']) for s in c['writes']] == WRITES and
            c['empty_label'] == EMPTY, 'SP keyword write binding drift')
    path = ROOT / c['corpus']
    corpus = json.loads(path.read_text())
    rows = corpus['entries']
    require(corpus['status'] == 'approved' and len(rows) == len(c['bindings']) == 52,
            'SP keyword corpus coverage drift')
    for i, (binding, row) in enumerate(zip(c['bindings'], rows)):
        require(binding['index'] == row['entry_index'] == i and
                binding['source_term'] == row['source_term'] and
                binding['source_text_sha256'] == row['source_text_sha256'] == sha(row['source_term'].encode()),
                'SP keyword source binding drift')
    return c, rows, path


def payload(text, table, overrides):
    # This UI consumes two-byte glyphs, including spaces and Latin letters.
    return encode_text(text.replace(' ', '\u3000'), table, overrides=overrides, terminate=True)


def verify_keyword_names(archive, readback):
    c, rows, _ = inputs()
    data = decode_production(archive).output
    require(len(data) == c['decoded_size'], 'SP keyword decoded size drift')
    for s in c['writes']:
        target = bytes.fromhex(s['target_hex'])
        require(len(target) <= s['capacity'] and
                data[s['offset']:s['offset']+s['capacity']] == target + bytes(s['capacity']-len(target)),
                'SP keyword library encoding readback mismatch')
    destinations = {i: at for i, at, _ in WRITES}
    labels = []
    for b, row in zip(c['bindings'], rows):
        at = destinations.get(b['index'], b['source_offset'])
        require(struct.unpack_from('<I', data, TABLE + 4*b['index'])[0] == BASE + at,
                'SP keyword pointer readback mismatch')
        actual = decode_text(data, at, readback)
        require(actual.terminator == 'nul' and actual.text.replace('\u3000', ' ') == row['translation'],
                f"SP keyword label readback mismatch: {b['index']}")
        labels.append(dict(index=b['index'], offset=at, translation=row['translation']))
    require(struct.unpack_from('<I', data, EMPTY['pointer_offset'])[0] == BASE + EMPTY['target_offset'] and
            data[EMPTY['target_offset']] == 0, 'SP keyword empty label changed')
    return labels


def patch_decoded(original, table, overrides):
    c, rows, _ = inputs()
    require(len(original) == c['decoded_size'], 'SP keyword decoded size drift')
    data = bytearray(original)
    plans = []
    for s in c['writes']:
        i, at, size = s['index'], s['offset'], s['capacity']
        binding = c['bindings'][i]
        require(decode_text(bytes.fromhex(binding['source_hex']), 0, table).text == binding['source_term'],
                'SP keyword source bytes drift')
        target = payload(rows[i]['translation'], table, overrides)
        require(target == bytes.fromhex(s['target_hex']),
                f'SP keyword must use library stored-text encoding: {i}')
        require(len(target) <= size, f'SP keyword overflow: {i}')
        replacement = target + bytes(size-len(target))
        before = original[at:at+size]
        require(len(bytes.fromhex(s['preimage_hex'])) == size and
                before in (bytes.fromhex(s['preimage_hex']), replacement), f'SP keyword preimage drift: {i}')
        plans.append((at, replacement))
        slot = TABLE + 4*i
        pointer = struct.unpack_from('<I', original, slot)[0]
        require(pointer in (BASE+binding['source_offset'], BASE+at), f'SP keyword pointer drift: {i}')
        plans.append((slot, struct.pack('<I', BASE+at)))
    empty_slot = EMPTY['pointer_offset']
    require(struct.unpack_from('<I', original, empty_slot)[0] in
            (BASE+EMPTY['source_offset'], BASE+EMPTY['target_offset']), 'SP keyword empty pointer drift')
    plans.append((empty_slot, struct.pack('<I', BASE+EMPTY['target_offset'])))
    allowed = {TABLE+4*i for i, _, _ in WRITES} | {empty_slot}
    # No unaccounted pointer may reference overwritten text or reclaimed padding.
    for slot in range(0, len(original)-3, 4):
        target = struct.unpack_from('<I', original, slot)[0] - BASE
        if any(at <= target < at+size for _, at, size in WRITES):
            require(slot in allowed, f'SP keyword unexpected reference at {slot:#x}')
    for at, replacement in plans:
        data[at:at+len(replacement)] = replacement
    require(data[EMPTY['target_offset']] == 0, 'SP keyword empty label overlaps translation')
    return bytes(data), plans


def apply_keyword_names(archive, table, overrides, readback):
    decoded = decode_production(archive)
    data, plans = patch_decoded(decoded.output, table, overrides)
    if data == decoded.output:
        output, packed_size = archive, decoded.consumed
    else:
        packed = reencode_changed_suffix(archive, data, strategy='rust-fit',
                                        max_output_size=len(archive), original_result=decoded)
        require(len(packed) <= len(archive) and decode_production(packed).output == data,
                'SP keyword compression roundtrip failed')
        output, packed_size = packed + bytes(len(archive)-len(packed)), len(packed)
    labels = verify_keyword_names(output, readback)
    _, _, path = inputs()
    return output, dict(labels=labels, repaired_entries=5, verified_entries=len(labels),
        changed=data != decoded.output, compressed_bytes=packed_size, allocated_bytes=len(archive),
        decoded_sha256=sha(data), owned_ranges=[dict(offset=a, size=len(b)) for a, b in plans],
        non_owned_bytes_preserved=True, contract_sha256=sha(CONTRACT.read_bytes()),
        corpus=dict(path=str(path.relative_to(ROOT)), sha256=sha(path.read_bytes())), runtime='pending')
