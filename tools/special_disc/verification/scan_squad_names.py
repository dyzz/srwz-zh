"""Scan SP squad names using Original's structural and owner-pointer rules.

Default output is an ignored review report. --freeze explicitly records the
reviewed native inventory; builds consume that inventory without rescanning.
No ISO, font, source corpus or component is modified.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
import migrate_stage_dialogue as st
import migrate_nisv as nisv
from srwz import stage_formations as sf
from srwz.codec import decode_production
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.text import decode_text, encode_text, load_text_table

INVENTORY = ROOT / 'config/products/special-disc/squad-name-inventory.json'
CORPUS = ROOT / 'corpus/zh/special-disc/squad-names.json'
OUT = ROOT / 'work/review/special-disc/squad-names/scan.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stage_offsets(stage, hb):
    return read_executable_archive_offsets(hb, ExecutableOffsetSpec(
        name='SP STAGE', member=st.HB, table_start=st.sd.HB_STAGE_TABLE,
        table_end=st.sd.HB_STAGE_TABLE + st.HB_TABLE_SPAN), len(stage))


def indexed_pointer_owners(data, table):
    """SP challenge records may populate the six member fields with IDs.

    Original's sentinel-only predicate misses these records. Require two
    adjacent 32-byte records, the same selector/tail contract and six bounded
    member IDs. The entire owner record is frozen for each selected target.
    """
    candidates = {}
    for site in range(16, len(data) - 15, 4):
        address, selector, following, terminal = struct.unpack_from('<4I', data, site)
        target = address - st.sd.SD_STAGE_BASE
        if not (0 <= target < len(data) and target % 8 == 0 and terminal == 0):
            continue
        if not ((selector == 0xff and following == 0) or
                (selector >> 16 == 0xff and selector & 0xffff and following == 0xffffffff)):
            continue
        ids = struct.unpack_from('<6H', data, site - 12)
        if any(value != 0xffff and value > 0x3ff for value in ids):
            continue
        try:
            text = decode_text(data, target, table)
        except (ValueError, IndexError):
            continue
        if text.terminator == 'nul' and not text.unknown_code_count and 1 <= len(text.text) <= 20:
            candidates[site] = target
    return {site: target for site, target in candidates.items()
            if site - 32 in candidates or site + 32 in candidates}


def discover_chunk(data, table, index, known, protected=()):
    """Return nonoverlapping owned slots, including one-character names.

    The Original singleton heuristics can also match a speaker string after
    zero padding. Native parser spans take precedence over those candidates.
    A complete pointer owner independently proves even a single-character name.
    """
    previous = sf.STAGE_BASE_ADDRESS
    sf.STAGE_BASE_ADDRESS = st.sd.SD_STAGE_BASE
    try:
        groups = [*sf._scan_structural_record_groups(data, table, stage_index=index),
                  *sf._scan_structural_formation_groups(data, table, stage_index=index)]
        sources = set(known) | {c.source_text for g in groups for c in g.cells}
        packed = sf._scan_packed8_groups(data, table, stage_index=index, source_texts=None)
        sources.update(c.source_text for g in packed for c in g.cells)
        groups.extend(packed)
        for at in sorted(set(indexed_pointer_owners(data, table).values())):
            decoded = decode_text(data, at, table)
            size = ((decoded.consumed + 7) // 8) * 8
            if size <= 64 and at + size <= len(data) and not any(data[at + decoded.consumed:at + size]):
                sources.add(decoded.text)
                groups.append(sf.FormationGroup(index, f'pointer8-{size}', size, size,
                    (sf.FormationCell(at, decoded.text, decoded.consumed, ''),)))
        groups.extend(sf._scan_layout(data, table, stage_index=index,
                                      layout='slot32', slot_size=32, stride=32))
        short = {s for s in sources if len(encode_text(s, table, terminate=True)) <= 23}
        for fn, names in ((sf._scan_known_record_slots, short),
                          (sf._scan_known_formation_slots, sources)):
            group = fn(data, table, stage_index=index, source_texts=names)
            if group:
                groups.append(group)
        for at in sorted(set(sf.discover_stage_formation_pointer_owners(data).values())):
            decoded = decode_text(data, at, table)
            if (len(decoded.text) == 1 and decoded.terminator == 'nul'
                    and not decoded.unknown_code_count and at % 8 == 0
                    and not any(data[at + decoded.consumed:at + 8])):
                groups.append(sf.FormationGroup(index, 'pointer8-8', 8, 8,
                    (sf.FormationCell(at, decoded.text, decoded.consumed, ''),)))
        occupied = list(protected)
        selected = []
        for group in groups:
            cells = []
            for cell in group.cells:
                end = cell.offset + group.slot_size
                if any(cell.offset < b and a < end for a, b in occupied):
                    continue
                occupied.append((cell.offset, end))
                cells.append(cell)
            if cells:
                selected.append(replace(group, cells=tuple(cells)))
        return tuple(selected)
    finally:
        sf.STAGE_BASE_ADDRESS = previous


def scan():
    table = load_text_table(st.mst.TABLE)
    members = {name: st.read_disc_member(name) for name in
               (st.STAGE, st.HB, 'SLPS_259.20', nisv.MEMBER)}
    stage, hb, exe = (members[n] for n in (st.STAGE, st.HB, 'SLPS_259.20'))
    offsets = stage_offsets(stage, hb)
    mod = st.sd.sd_stage_module()
    functions = mod.read_stage_function_addresses(exe, start=st.sd.SD_FUNCTION_TABLE[0],
                                                   end=st.sd.SD_FUNCTION_TABLE[1])
    main = json.loads((ROOT / 'corpus/zh/menu/stage-default-formations.json').read_text())
    known = set(main['translations_by_source_text'])
    known.update(r['source_text'] for r in json.loads(
        (ROOT / 'corpus/zh/special-disc/frame-text.json').read_text())['entries']
        if r.get('kind') == 'formation_name')
    slots, excluded, chunks = [], [], []
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        decoded = decode_production(stage[start:end])
        data = decoded.output
        if any(stage[start + decoded.consumed:end]):
            raise ValueError('STAGE nonzero padding')
        # Chunk 0 is the flowchart; chunks 66/67 are stg_500/501 developer maps.
        if index == 0:
            excluded.append(dict(chunk=0, reason='flowchart; not a gameplay formation table'))
            continue
        parsed = mod.parse_stage(data, table, stage_index=index,
                                 function_address=functions[index], base_address=st.sd.SD_STAGE_BASE)
        protected = [(e.text_offset, data.index(0, e.text_offset) + 1)
                     for e in parsed.entries if e.text_offset is not None]
        groups = discover_chunk(data, table, index, known, protected)
        if index >= 66:
            excluded.append(dict(chunk=index, reason='developer stage',
                                 slots=sum(len(g.cells) for g in groups)))
            continue
        if not groups:
            continue
        chunks.append(dict(chunk=index, decoded_sha256=sha(data)))
        previous_base = sf.STAGE_BASE_ADDRESS
        sf.STAGE_BASE_ADDRESS = st.sd.SD_STAGE_BASE
        try:
            owners = sf.discover_stage_formation_pointer_owners(data)
        finally:
            sf.STAGE_BASE_ADDRESS = previous_base
        owners.update(indexed_pointer_owners(data, table))
        for group in groups:
            spec = sf._LOCKED_LAYOUT_SPECS[group.layout]
            for cell in group.cells:
                at, size = cell.offset, group.slot_size
                owner_start = at - spec['prefix_size']
                owner_end = at + size + spec['trailer_size']
                slots.append(dict(member=st.STAGE, chunk=index, offset=at, capacity=size,
                    layout=group.layout, source_text=cell.source_text,
                    source_slot_sha256=sha(data[at:at + size]),
                    prefix_hex=data[owner_start:at].hex(),
                    trailer_hex=data[at + size:owner_end].hex(),
                    pointer_owners=[dict(offset=site - 16, hex=data[site - 16:site + 16].hex())
                                    for site, target in sorted(owners.items()) if target == at]))
    offsets = nisv.sp_offsets(exe, nisv.SP_TABLE, len(members[nisv.MEMBER]))
    data = decode_production(members[nisv.MEMBER][offsets[4]:offsets[5]]).output
    count = struct.unpack_from('<H', data, 0x20)[0]
    if count != 113 or nisv.SQUAD_BASE + count * nisv.SQUAD_STRIDE > len(data):
        raise ValueError('SP NISV squad table geometry drift')
    for index in range(count):
        at = nisv.SQUAD_BASE + index * nisv.SQUAD_STRIDE
        source = decode_text(data, at, table, end=at + nisv.SQUAD_NAME)
        if source.unknown_code_count or source.terminator != 'nul':
            raise ValueError('NISV squad source decode failed')
        slots.append(dict(member=nisv.MEMBER, chunk=4, index=index, offset=at,
            capacity=nisv.SQUAD_NAME, layout='nisv-name28', source_text=source.text,
            source_slot_sha256=sha(data[at:at + nisv.SQUAD_NAME]),
            prefix_hex='', trailer_hex=''))
    slots.sort(key=lambda r: (r['member'], r['chunk'], r['offset']))
    return dict(schema_version=1, source_authority='original_sp_disc',
        selection_authority='explicit_locked_slots', scan_policy='explicit_refreeze_only',
        members={n: sha(b) for n, b in members.items()}, stage_chunks=chunks,
        excluded=excluded, counts=dict(slots=len(slots),
            stage_slots=sum(r['member'] == st.STAGE for r in slots), nisv_slots=count,
            stage_chunks=len(chunks), unique_sources=len({r['source_text'] for r in slots})),
        slots=slots)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    report = scan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if args.freeze:
        metadata = {k: v for k, v in report.items() if k != 'slots'}
        prefix = json.dumps(metadata, ensure_ascii=False, indent=2)[:-2]
        rows = ',\n'.join('    ' + json.dumps(r, ensure_ascii=False) for r in report['slots'])
        INVENTORY.write_text(prefix + ',\n  \"slots\": [\n' + rows + '\n  ]\n}\n')
    elif INVENTORY.exists() and json.loads(INVENTORY.read_text()) != report:
        raise ValueError('frozen squad inventory differs from independent scan')
    print(json.dumps(report['counts'], ensure_ascii=False))


if __name__ == '__main__':
    main()
