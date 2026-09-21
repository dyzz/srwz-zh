"""Write the seven reviewed Noir names into fixed SP pilot fields."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import decode_text, encode_text

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/pilot-names.json'
MEMBER = 'DATA/COMPDATA.BN'
PILOTS = {797, 827, 845, 899, 909, 914, 931}
FIELDS = {'display': (2, 21), 'given': (46, 23)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inputs():
    contract = json.loads(CONTRACT.read_text())
    require(contract['schema_version'] == 1 and contract['member'] == MEMBER and
            contract['pilot_table'] == dict(start=0x2B50, stride=178, count=969) and
            contract['decoded_size'] == 652800, 'SP pilot-name contract drift')
    expected = {f'sd/compdata/pilot/{i}/{f}' for i in PILOTS for f in FIELDS}
    slots = contract['entries']
    require(len(slots) == len(expected) and {s['id'] for s in slots} == expected,
            'SP pilot-name coverage drift')
    corpus_path = ROOT / contract['corpus']
    entries = [r for r in json.loads(corpus_path.read_text())['entries'] if r['id'] in expected]
    rows = {r['id']: r for r in entries}
    require(len(entries) == len(rows) == len(expected), 'SP pilot-name corpus coverage drift')
    for slot in slots:
        row = rows[slot['id']]
        index, field = int(slot['id'].split('/')[3]), slot['id'].split('/')[4]
        delta, capacity = FIELDS[field]
        at = 0x2B50 + index * 178 + delta
        require((slot['pilot_index'], slot['field'], slot['offset'], slot['capacity']) ==
                (index, field, at, capacity), 'SP pilot-name field binding drift')
        require(row['locations'] == [dict(member=MEMBER, offset=at, field=field)],
                'SP pilot-name location drift')
        require(row['source_text'] == slot['source_text'] and
                sha(row['source_text'].encode()) == row['source_text_sha256'] == slot['source_text_sha256'],
                'SP pilot-name source identity drift')
        require(row['editorial_status'] == 'reviewed' and bool(row['translation']),
                'SP pilot name lacks reviewed translation')
    return contract, rows, corpus_path


def verify_pilot_names(archive, readback):
    contract, rows, _ = inputs()
    data = decode_production(archive).output
    require(len(data) == contract['decoded_size'], 'SP pilot-name decoded size drift')
    labels = []
    for slot in contract['entries']:
        at, size = slot['offset'], slot['capacity']
        actual = decode_text(data, at, readback, end=at + size)
        expected = rows[slot['id']]['translation']
        require(actual.text == expected and actual.terminator == 'nul' and
                not any(data[at + actual.consumed:at + size]),
                f"SP pilot-name readback mismatch: {slot['id']}")
        labels.append(dict(id=slot['id'], translation=expected, offset=at, capacity=size))
    return labels


def apply_pilot_names(archive, table, overrides, readback):
    contract, rows, corpus_path = inputs()
    decoded = decode_production(archive)
    require(len(decoded.output) == contract['decoded_size'], 'SP pilot-name decoded size drift')
    data = bytearray(decoded.output)
    changed = []
    for slot in contract['entries']:
        at, size = slot['offset'], slot['capacity']
        source = bytes.fromhex(slot['source_hex'])
        require(len(source) == size and decode_text(source, 0, table, end=size).text == slot['source_text'],
                'SP pilot-name source bytes drift')
        encoded = encode_text(rows[slot['id']]['translation'], table, overrides=overrides, terminate=True)
        require(len(encoded) <= size, f"SP pilot-name overflow: {slot['id']}")
        replacement = encoded + bytes(size - len(encoded))
        before = bytes(data[at:at + size])
        require(before in (source, replacement), f"SP pilot-name preimage drift: {slot['id']}")
        if before != replacement:
            changed.append(slot['id'])
        data[at:at + size] = replacement
    if data == decoded.output:
        output, packed_size = archive, decoded.consumed
    else:
        packed = reencode_changed_suffix(archive, bytes(data), strategy='rust-fit',
                                        max_output_size=len(archive), original_result=decoded)
        require(len(packed) <= len(archive), 'SP pilot-name compressed member overflow')
        require(decode_production(packed).output == data, 'SP pilot-name compression roundtrip mismatch')
        output, packed_size = packed + bytes(len(archive) - len(packed)), len(packed)
    labels = verify_pilot_names(output, readback)
    return output, dict(labels=labels, entries=len(labels), pilots=len(PILOTS), changed_ids=changed,
        compressed_bytes=packed_size, allocated_bytes=len(archive), decoded_sha256=sha(data),
        non_name_bytes_preserved=True, contract_sha256=sha(CONTRACT.read_bytes()),
        corpus=dict(path=str(corpus_path.relative_to(ROOT)), sha256=sha(corpus_path.read_bytes())),
        runtime='pending')
