"""Refresh explicitly owned SP name copies from current reviewed source bindings."""
import hashlib
import json
import re
import struct
from pathlib import Path

from srwz.compressed_workspace import CompressedStreamWorkspace, decoded_view, write_decoded
from srwz.text import decode_text, encode_text, two_byte_visible_spaces

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/shared-label-updates.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inputs():
    contract = json.loads(CONTRACT.read_text())
    if (contract['schema_version'], contract['member'], contract['runtime_base'], contract['decoded_size']) != (
            1, 'DATA/COMPDATA.BN', 0x764F80, 652800):
        raise ValueError('SP shared-label contract drift')
    labels, locks = [], {CONTRACT.relative_to(ROOT).as_posix(): sha(CONTRACT.read_bytes())}
    for slot in contract['entries']:
        path = ROOT / slot['corpus']
        rows = [r for r in json.loads(path.read_text())['entries'] if r['id'] == slot['corpus_id']]
        if (len(rows) != 1 or rows[0]['editorial_status'] != 'reviewed' or
                rows[0]['source_text_sha256'] != slot['source_text_sha256'] or
                sha(slot['source_text'].encode()) != slot['source_text_sha256']):
            raise ValueError('SP shared-label source binding drift')
        labels.append((slot, rows[0]['translation']))
        locks[slot['corpus']] = sha(path.read_bytes())
    return contract, labels, locks


def references(data, contract, slot):
    at, size = slot['offset'], slot['capacity']
    sites = []
    for site in range(0, len(data) - 3, 4):
        target = struct.unpack_from('<I', data, site)[0] - contract['runtime_base']
        if at <= target < at + size:
            if target != at:
                raise ValueError('SP shared-label interior reference drift')
            sites.append(site)
    if sites != slot['reference_sites']:
        raise ValueError('SP shared-label reference drift')


def audit_viewer_pilot_labels(data, readback):
    """Check the separate 48-byte viewer records, beyond the ordinary roster."""
    contract, labels, _ = inputs()
    binding = contract['viewer_pilot_list']
    if (binding['start'], binding['stride'], binding['count'], binding['name_pointer_delta']) != (
            0x71200, 48, 554, 4):
        raise ValueError('SP viewer pilot-list binding drift')
    metadata, targets = bytearray(), set()
    for record in range(binding['start'], binding['start'] + binding['stride'] * binding['count'],
                        binding['stride']):
        site = record + binding['name_pointer_delta']
        pointer = struct.unpack_from('<I', data, site)[0]
        metadata.extend(data[record:record + 8])
        at = pointer - contract['runtime_base']
        if not 0 <= at < len(data):
            raise ValueError('SP viewer pilot-list pointer out of bounds')
        actual = decode_text(data, at, readback)
        if not actual.text or actual.terminator != 'nul' or actual.unknown_code_count or re.search('[ぁ-ヺｦ-ﾟ]', actual.text):
            raise ValueError(f'SP viewer pilot-list untranslated name: {record:#x}: {actual.text}')
        targets.add(at)
    if sha(metadata) != binding['identity_and_name_pointers_sha256']:
        raise ValueError('SP viewer pilot-list identity or pointer drift')
    return dict(records=binding['count'], unique_name_targets=len(targets), kana_residue=0)


def patch_decoded(data, table, overrides, readback):
    contract, labels, locks = inputs()
    if len(data) != contract['decoded_size']:
        raise ValueError('SP shared-label decoded size drift')
    output = bytearray(data)
    owned = set()
    report = []
    for slot, text in labels:
        at, size = slot['offset'], slot['capacity']
        if not 0 <= at < at + size <= len(data) or owned.intersection(range(at, at + size)):
            raise ValueError('SP shared-label overlapping or invalid slots')
        owned.update(range(at, at + size))
        references(data, contract, slot)
        source = bytes.fromhex(slot['source_hex'])
        previous = bytes.fromhex(slot['previous_hex'])
        if len(source) != size or len(previous) != size or decode_text(source, 0, table).text != slot['source_text']:
            raise ValueError('SP shared-label source bytes drift')
        encoded = encode_text(two_byte_visible_spaces(text), table, overrides=overrides, terminate=True)
        if len(encoded) > size:
            raise ValueError('SP shared-label capacity exceeded')
        replacement = encoded + bytes(size - len(encoded))
        if data[at:at + size] not in (source, previous, replacement):
            raise ValueError(f'SP shared-label preimage drift: {at:#x}')
        if decode_text(replacement, 0, readback).text != two_byte_visible_spaces(text):
            raise ValueError('SP shared-label encoding readback mismatch')
        output[at:at + size] = replacement
        report.append(dict(offset=at, capacity=size, translation=text, reference_sites=slot['reference_sites']))
    return bytes(output), dict(labels=report, inputs=locks, non_owned_bytes_preserved=True)


def verify_shared_labels(archive, readback):
    data = decoded_view(archive).output
    contract, labels, locks = inputs()
    if len(data) != contract['decoded_size']:
        raise ValueError('SP shared-label final size drift')
    report = []
    for slot, text in labels:
        references(data, contract, slot)
        at, size = slot['offset'], slot['capacity']
        actual = decode_text(data, at, readback, end=at + size)
        if (actual.text != two_byte_visible_spaces(text) or actual.terminator != 'nul' or
                any(data[actual.end:at + size])):
            raise ValueError('SP shared-label final readback mismatch')
        report.append(dict(offset=at, capacity=size, translation=text, reference_sites=slot['reference_sites']))
    audit_viewer_pilot_labels(data, readback)
    return dict(labels=report, inputs=locks, non_owned_bytes_preserved=True)


def apply_shared_labels(archive, table, overrides, readback):
    decoded = decoded_view(archive)
    data, report = patch_decoded(decoded.output, table, overrides, readback)
    output = write_decoded(archive, decoded, data, stage='shared labels', label='SP shared-label')
    if verify_shared_labels(output, readback) != report:
        raise ValueError('SP shared-label receipt drift')
    return output, report
