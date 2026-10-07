"""Refresh approved Gravion unit and weapon copies on the preserved SP baseline."""
import hashlib
import json
import struct
from pathlib import Path

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import decode_text, encode_text, two_byte_visible_spaces

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/gravion-labels.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inputs():
    contract = json.loads(CONTRACT.read_text())
    if (contract['schema_version'], contract['member'], contract['runtime_base'], contract['decoded_size']) != (
            1, 'DATA/COMPDATA.BN', 0x764F80, 652800):
        raise ValueError('SP Gravion label contract drift')
    labels, locks = [], {CONTRACT.relative_to(ROOT).as_posix(): sha(CONTRACT.read_bytes())}
    for slot in contract['entries']:
        path = ROOT / slot.get('corpus', 'config/products/special-disc/shared-name-reference.json')
        document = json.loads(path.read_text())
        if 'reference_key' in slot:
            options = document['units'][slot['reference_key']]
            if len(options) != 1:
                raise ValueError('SP Gravion unit translation is ambiguous')
            text = options[0]
            if slot['reference_key'] != slot['source_text']:
                raise ValueError('SP Gravion unit source binding drift')
        else:
            rows = [r for r in document['terms'] if r['id'] == slot['term_id']]
            if len(rows) != 1 or rows[0]['status'] != 'approved' or slot['source_text'] not in rows[0]['source_terms']:
                raise ValueError('SP Gravion weapon source binding drift')
            text = rows[0]['translation']
        labels.append((slot, text))
        locks[path.relative_to(ROOT).as_posix()] = sha(path.read_bytes())
    return contract, labels, locks


def references(data, contract, slot):
    at, size = slot['offset'], slot['capacity']
    sites = []
    for site in range(0, len(data) - 3, 4):
        target = struct.unpack_from('<I', data, site)[0] - contract['runtime_base']
        if at <= target < at + size:
            if target != at:
                raise ValueError('SP Gravion label interior reference drift')
            sites.append(site)
    if sites != slot['reference_sites']:
        raise ValueError('SP Gravion label reference drift')


def patch_decoded(data, table, overrides, readback):
    contract, labels, locks = inputs()
    if len(data) != contract['decoded_size']:
        raise ValueError('SP Gravion label decoded size drift')
    output = bytearray(data)
    owned = set()
    report = []
    for slot, text in labels:
        at, size = slot['offset'], slot['capacity']
        if not 0 <= at < at + size <= len(data) or owned.intersection(range(at, at + size)):
            raise ValueError('SP Gravion label overlapping or invalid slots')
        owned.update(range(at, at + size))
        references(data, contract, slot)
        source = bytes.fromhex(slot['source_hex'])
        previous = bytes.fromhex(slot['previous_hex'])
        if len(source) != size or len(previous) != size or decode_text(source, 0, table).text != slot['source_text']:
            raise ValueError('SP Gravion label source bytes drift')
        encoded = encode_text(two_byte_visible_spaces(text), table, overrides=overrides, terminate=True)
        if len(encoded) > size:
            raise ValueError('SP Gravion label capacity exceeded')
        replacement = encoded + bytes(size - len(encoded))
        if data[at:at + size] not in (source, previous, replacement):
            raise ValueError(f'SP Gravion label preimage drift: {at:#x}')
        if decode_text(replacement, 0, readback).text != two_byte_visible_spaces(text):
            raise ValueError('SP Gravion label encoding readback mismatch')
        output[at:at + size] = replacement
        report.append(dict(offset=at, capacity=size, translation=text, reference_sites=slot['reference_sites']))
    return bytes(output), dict(labels=report, inputs=locks, non_owned_bytes_preserved=True)


def verify_gravion_labels(archive, readback):
    data = decode_production(archive).output
    contract, labels, locks = inputs()
    if len(data) != contract['decoded_size']:
        raise ValueError('SP Gravion label final size drift')
    report = []
    for slot, text in labels:
        references(data, contract, slot)
        at, size = slot['offset'], slot['capacity']
        actual = decode_text(data, at, readback, end=at + size)
        if (actual.text != two_byte_visible_spaces(text) or actual.terminator != 'nul' or
                any(data[actual.end:at + size])):
            raise ValueError('SP Gravion label final readback mismatch')
        report.append(dict(offset=at, capacity=size, translation=text, reference_sites=slot['reference_sites']))
    return dict(labels=report, inputs=locks, non_owned_bytes_preserved=True)


def apply_gravion_labels(archive, table, overrides, readback):
    decoded = decode_production(archive)
    data, report = patch_decoded(decoded.output, table, overrides, readback)
    if data == decoded.output:
        output = archive
    else:
        packed = reencode_changed_suffix(archive, data, strategy='rust-fit',
                                        max_output_size=len(archive), original_result=decoded)
        if len(packed) > len(archive) or decode_production(packed).output != data:
            raise ValueError('SP Gravion label compression roundtrip failed')
        output = packed + bytes(len(archive) - len(packed))
    if verify_gravion_labels(output, readback) != report:
        raise ValueError('SP Gravion label receipt drift')
    return output, report
