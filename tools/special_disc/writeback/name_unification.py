"""Apply the 2026-10-17 本篇／BEST／SP name decisions to the SP COMPDATA.

The SP disc inherits most names from a frozen main-game build; this pass rewrites
only the slots the user's decisions name (config/products/special-disc/
name-unification-20261017.json): pointer-reached unit/weapon/viewer strings and
inline pilot-name fields. Each slot is bound to its source bytes, the bytes the
earlier SP writers left there, its pointer sites (strings only) and capacity.
"""
import hashlib
import json
import struct
from pathlib import Path

from srwz.compressed_workspace import decoded_view, write_decoded
from srwz.text import decode_text, encode_text, two_byte_visible_spaces

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/name-unification-20261017.json'
PILOT_START, PILOT_STRIDE = 0x2B50, 178
PILOT_FIELDS = {'display': (2, 21), 'family': (23, 23), 'given': (46, 23)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inputs():
    contract = json.loads(CONTRACT.read_text())
    require((contract['schema_version'], contract['member'], contract['runtime_base'], contract['decoded_size']) ==
            (1, 'DATA/COMPDATA.BN', 0x764F80, 652800), 'SP name-unification contract drift')
    # The decision record (config/editorial/…) is outside the SP edition's frozen inputs;
    # the contract carries each slot's decision id and the record's digest as provenance.
    records = contract['decisions']
    require(isinstance(records, list) and records and
            all(set(r) == {'path', 'sha256', 'ids'} for r in records), 'SP name-unification provenance drift')
    decided = {(r['path'], i) for r in records for i in r['ids']}
    for slot in contract['entries']:
        require((slot['decision_record'], slot['decision']) in decided,
                f"SP name-unification slot without a decision: {slot['offset']:#x}")
        if slot['kind'] == 'pilot_field':
            delta, capacity = PILOT_FIELDS[slot['field']]
            require(slot['offset'] == PILOT_START + slot['pilot_index'] * PILOT_STRIDE + delta and
                    slot['capacity'] == capacity, f"SP name-unification pilot field drift: {slot['offset']:#x}")
        else:
            require(slot['kind'] == 'string' and slot['reference_sites'], 'SP name-unification slot kind drift')
    locks = {CONTRACT.relative_to(ROOT).as_posix(): sha(CONTRACT.read_bytes())}
    return contract, locks


def references(data, contract, slot):
    if slot['kind'] != 'string':
        return
    at, size = slot['offset'], slot['capacity']
    sites = []
    for site in range(0, len(data) - 3, 4):
        target = struct.unpack_from('<I', data, site)[0] - contract['runtime_base']
        if at <= target < at + size:
            require(target == at, f'SP name-unification interior reference: {at:#x}')
            sites.append(site)
    require(sites == slot['reference_sites'], f'SP name-unification reference drift: {at:#x}')


def receipt(slot):
    return dict(offset=slot['offset'], capacity=slot['capacity'], translation=slot['translation'],
                decision=slot['decision'], decision_record=slot['decision_record'])


def patch_decoded(data, table, overrides, readback):
    contract, locks = inputs()
    require(len(data) == contract['decoded_size'], 'SP name-unification decoded size drift')
    output = bytearray(data)
    owned = set()
    report = []
    for slot in contract['entries']:
        at, size = slot['offset'], slot['capacity']
        require(0 <= at < at + size <= len(data) and not owned.intersection(range(at, at + size)),
                'SP name-unification overlapping or invalid slots')
        owned.update(range(at, at + size))
        references(data, contract, slot)
        source, previous = bytes.fromhex(slot['source_hex']), bytes.fromhex(slot['previous_hex'])
        require(len(source) == len(previous) == size and
                decode_text(source, 0, table, end=size).text == slot['source_text'],
                f'SP name-unification source bytes drift: {at:#x}')
        text = two_byte_visible_spaces(slot['translation'])
        encoded = encode_text(text, table, overrides=overrides, terminate=True)
        require(len(encoded) <= size, f'SP name-unification capacity exceeded: {at:#x}')
        replacement = encoded + bytes(size - len(encoded))
        require(bytes(data[at:at + size]) in (source, previous, replacement),
                f'SP name-unification preimage drift: {at:#x}')
        require(decode_text(replacement, 0, readback, end=size).text == text,
                'SP name-unification encoding readback mismatch')
        output[at:at + size] = replacement
        report.append(receipt(slot))
    return bytes(output), dict(labels=report, inputs=locks, non_owned_bytes_preserved=True)


def verify_name_unification(archive, readback):
    data = decoded_view(archive).output
    contract, locks = inputs()
    require(len(data) == contract['decoded_size'], 'SP name-unification final size drift')
    report = []
    for slot in contract['entries']:
        references(data, contract, slot)
        at, size = slot['offset'], slot['capacity']
        actual = decode_text(data, at, readback, end=at + size)
        require(actual.text == two_byte_visible_spaces(slot['translation']) and actual.terminator == 'nul' and
                not any(data[actual.end:at + size]), f'SP name-unification final readback mismatch: {at:#x}')
        report.append(receipt(slot))
    return dict(labels=report, inputs=locks, non_owned_bytes_preserved=True)


def apply_name_unification(archive, table, overrides, readback):
    decoded = decoded_view(archive)
    data, report = patch_decoded(decoded.output, table, overrides, readback)
    output = write_decoded(archive, decoded, data, stage='name unification', label='SP name-unification')
    require(verify_name_unification(output, readback) == report, 'SP name-unification receipt drift')
    return output, report
