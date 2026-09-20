"""Frozen SP squad-name slots and source-exact translations shared by writers."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from srwz.stage_formations import FormationCell, FormationGroup
from srwz.text import decode_text, encode_text, normalize_original_fullwidth_ascii

ROOT = Path(__file__).resolve().parents[3]
INVENTORY_PATH = 'config/products/special-disc/squad-name-inventory.json'
CORPUS_PATH = 'corpus/zh/special-disc/squad-names.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_names(root=ROOT):
    inventory = json.loads((root / INVENTORY_PATH).read_text())
    corpus = json.loads((root / CORPUS_PATH).read_text())
    if inventory['selection_authority'] != 'explicit_locked_slots':
        raise ValueError('squad inventory selection authority drift')
    entries = {r['source_text']: r for r in corpus['entries']}
    if len(entries) != len(corpus['entries']) or set(entries) != {s['source_text'] for s in inventory['slots']}:
        raise ValueError('squad source coverage drift')
    positions = set()
    for slot in inventory['slots']:
        key = slot['member'], slot['chunk'], slot['offset']
        if key in positions:
            raise ValueError('duplicate squad slot')
        positions.add(key)
    for source, row in entries.items():
        if row['source_text_sha256'] != sha(source.encode()) or not row['translation']:
            raise ValueError('squad source hash or translation drift')
        expected = [{k: s[k] for k in ('member', 'chunk', 'offset', 'capacity', 'layout')}
                    for s in inventory['slots'] if s['source_text'] == source]
        if row['locations'] != expected:
            raise ValueError('squad corpus location drift')
    return inventory, entries


def validate_slot(data, slot, table):
    at, size = slot['offset'], slot['capacity']
    prefix, trailer = bytes.fromhex(slot['prefix_hex']), bytes.fromhex(slot['trailer_hex'])
    if not 0 <= at - len(prefix) <= at + size + len(trailer) <= len(data):
        raise ValueError('squad slot boundary drift')
    if sha(data[at:at + size]) != slot['source_slot_sha256']:
        raise ValueError('squad source slot drift')
    if data[at - len(prefix):at] != prefix or data[at + size:at + size + len(trailer)] != trailer:
        raise ValueError('squad owner metadata drift')
    for owner in slot.get('pointer_owners', []):
        start = owner['offset']
        expected = bytes.fromhex(owner['hex'])
        if data[start:start + len(expected)] != expected:
            raise ValueError('squad pointer owner drift')
    decoded = decode_text(data, at, table, end=at + size)
    if decoded.text != slot['source_text'] or decoded.unknown_code_count or decoded.terminator != 'nul':
        raise ValueError('squad source text drift')
    return decoded


def locked_stage_groups(data, table, index):
    inventory, _ = load_names()
    grouped = defaultdict(list)
    for slot in inventory['slots']:
        if slot['member'] != 'DATA/STAGE.BIN' or slot['chunk'] != index:
            continue
        decoded = validate_slot(data, slot, table)
        grouped[slot['layout'], slot['capacity']].append(FormationCell(
            slot['offset'], slot['source_text'], decoded.consumed,
            slot['trailer_hex'], slot['prefix_hex']))
    return tuple(FormationGroup(index, layout, size,
        29 if layout == 'record6+23' else 52 if layout == 'formation18+33+1' else size,
        tuple(cells)) for (layout, size), cells in grouped.items())


def patch_slots(data, slots, entries, table, overrides, readback):
    output = bytearray(data)
    allowed = bytearray(len(data))
    for slot in slots:
        validate_slot(data, slot, table)
        at, size = slot['offset'], slot['capacity']
        if any(allowed[at:at + size]):
            raise ValueError('overlapping squad slots')
        text = normalize_original_fullwidth_ascii(entries[slot['source_text']]['translation'])
        payload = encode_text(text, table, overrides=overrides, terminate=True)
        if len(payload) > size:
            raise ValueError(f'squad name exceeds capacity: {text!r}')
        output[at:at + size] = payload + bytes(size - len(payload))
        allowed[at:at + size] = b'\1' * size
        if decode_text(bytes(output), at, readback).text != text:
            raise ValueError('squad translation readback mismatch')
    if len(output) != len(data) or any(a != b and not allowed[i] for i, (a, b) in enumerate(zip(data, output))):
        raise ValueError('squad write escaped name slots')
    return bytes(output)
