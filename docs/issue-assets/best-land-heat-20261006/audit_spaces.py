"""Read-only semantic space audit of the two actual current ISO files."""
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_full_story_iso_content import read_members
from srwz.codec import decode_production
from srwz.display_names import load_display_name_source, parse_display_names
from srwz.menu import parse_menu_file
from srwz.stage import parse_stage
from srwz.stage_formations import load_locked_stage_default_formations
from srwz.text import TextTable, control_notation_positions, decode_text, load_text_table
from srwz.release_inputs import sha256_file

source_table = load_text_table(ROOT / 'vendor/upstream-python/project/tbl_all.json')
assignments = json.loads((ROOT / 'config/encoding/zh-release-font-assignments.json').read_text())
characters = dict(source_table.characters)
for key in ('primary_assignments', 'surface_alias_assignments', 'source_compatibility_assignments'):
    characters.update({int(row['code'], 16): row['character'] for row in assignments[key]})
table = TextTable(characters, source_table.tags)
descriptors = {row['friendly_name']: row for row in json.loads((ROOT / 'vendor/upstream-python/project/menu_files.json').read_text())}
config = json.loads((ROOT / 'config/full-story-components.json').read_text())
structure, _, _, _ = load_display_name_source(ROOT, ROOT / config['full_pilot_names']['structure']['path'])
contract = json.loads((ROOT / 'config/editions/best/source-layout.json').read_text())
native_best = read_members(ROOT / 'rom/best.iso', ('SLPS_732.70',))['SLPS_732.70']
native = read_members(ROOT / 'rom/original.iso', ('DATA/COMPDATA.BN', 'DATA/STAGE.BIN', 'HEDBDY/HB.BIN', 'SLPS_258.87'))
original_comp = decode_production(native['DATA/COMPDATA.BN']).output
original_display = parse_display_names(original_comp, source_table, structure, verify_text_preimages=False)
original_menus = {key: parse_menu_file(original_comp if key == 'Compdata' else native['SLPS_258.87'], descriptor, source_table)
                  for key, descriptor in descriptors.items() if key in ('Compdata', 'SLPS')}
inventory = json.loads((ROOT / 'config/stage-default-formation-inventory.json').read_text())
groups = load_locked_stage_default_formations(native['DATA/STAGE.BIN'], native['HEDBDY/HB.BIN'], source_table, inventory)
map_names = json.loads((ROOT / 'corpus/zh/menu/ui-name-tables.json').read_text())['map_names']
stage_indices = sorted({int(p.stem.split('-')[-1]) for p in (ROOT / 'corpus/zh/story-dialogue').glob('stage-*.json')})

def stored_visible_spaces(data, offset):
    decoded = decode_text(data, offset, table)
    protected = control_notation_positions(decoded.text)
    cursor, position, codes, raw_offsets = offset, 0, Counter(), []
    while cursor < decoded.end and data[cursor] != 0:
        byte = data[cursor]
        size = 2 if (0x31 <= byte <= 0x35 or 0x80 <= byte <= 0x9F or 0xE0 <= byte <= 0xEA) else 1
        raw = data[cursor:cursor + size]
        piece = decode_text(raw, 0, table, allow_end=True).text
        if piece in (' ', '\u3000') and position not in protected:
            codes[raw.hex()] += 1
            if raw == b' ': raw_offsets.append(cursor)
        position += len(piece)
        cursor += size
    return dict(codes), raw_offsets

# Deliberately preserve a raw-space override to prove byte-level distinction.
assert stored_visible_spaces(bytes.fromhex('82738267826420826782648260827300'), 0)[1] == [6]
assert stored_visible_spaces(bytes.fromhex('8273826782648140826782648260827300'), 0) == ({'8140': 1}, [])
assert stored_visible_spaces(bytes.fromhex('8273826782649864826782648260827300'), 0) == ({'9864': 1}, [])

def elf_offset(offset, best):
    if not best:
        return offset
    support = contract['elf_support_attack_slot']
    if offset == support['original_start']:
        return support['best_start']
    for start, end, target in contract['elf_spans']:
        if start <= offset < end:
            return target + offset - start
    return None

reports = []
for edition, executable in (('original', 'SLPS_258.87'), ('best', 'SLPS_732.70')):
    best = edition == 'best'
    iso = ROOT / f'build/iso/zh-release-{edition}/current-{edition}.iso'
    members = read_members(iso, (executable, 'DATA/COMPDATA.BN', 'DATA/STAGE.BIN', 'HEDBDY/HB.BIN', 'DATA/NISVDATA.BIN', 'MAP/MAPNAME.BIN'))
    comp = decode_production(members['DATA/COMPDATA.BN']).output
    counts, findings, native_preserved = Counter(), [], []
    native_fallbacks = []
    safe_decoded_ascii_space_entries = []
    stored_space_code_counts = Counter()
    def check(surface, identity, text, original=None, offset=None, data=None):
        counts[surface] += 1
        assert data is not None and offset is not None
        codes, raw_offsets = stored_visible_spaces(data, offset)
        stored_space_code_counts.update(codes)
        row = dict(surface=surface, identity=identity, text=text, space_encoding_codes=codes, offset=offset)
        if raw_offsets:
            row['raw_single_byte_space_offsets'] = raw_offsets
            (native_preserved if original is not None and text == original else findings).append(row)
        elif any(ch == ' ' and i not in control_notation_positions(text) for i, ch in enumerate(text)):
            safe_decoded_ascii_space_entries.append(row)
    display = original_display if best else parse_display_names(comp, table, structure, verify_text_preimages=False)
    originals = {row.entry_id: row.text for row in original_display.entries}
    for row in display.entries:
        target = (struct.unpack_from('<I', comp, row.pointer_offsets[0])[0] - struct.unpack_from('<I', comp, 8)[0]
                  if best and row.pointer_offsets else row.target_offset)
        check('display_names', row.entry_id, decode_text(comp, target, table).text, originals[row.entry_id], target, data=comp)
    for key, menu in original_menus.items():
        data = comp if key == 'Compdata' else members[executable]
        seen = set()
        for row in menu.entries:
            for offset in row.target_offsets:
                if offset in seen: continue
                seen.add(offset)
                target = offset if key == 'Compdata' else elf_offset(offset, best)
                if target is None:
                    end = native['SLPS_258.87'].index(b'\0', offset) + 1
                    payload = native['SLPS_258.87'][offset:end]
                    assert len(payload) > 2, (row.entry_id, offset)
                    targets = []
                    pos = native_best.find(payload)
                    while pos >= 0:
                        targets.append(pos)
                        pos = native_best.find(payload, pos + 1)
                    assert targets, (row.entry_id, offset, payload.hex())
                    native_fallbacks.append(dict(identity=row.entry_id, original_offset=offset,
                                                  native_payload_hex=payload.hex(), best_targets=targets,
                                                  method='all exact NUL-terminated native BEST source matches; no fuzzy selection'))
                    for candidate in targets:
                        check(f'{key}_menu_targets', row.entry_id, decode_text(data, candidate, table).text, row.text, candidate, data=data)
                else:
                    check(f'{key}_menu_targets', row.entry_id, decode_text(data, target, table).text, row.text, target, data=data)
    nisv_start = next(row['best_start' if best else 'original_start'] for row in contract['archive_tables'] if row['member'] == 'DATA/NISVDATA.BIN')
    offsets = struct.unpack_from('<7I', members[executable], nisv_start)
    names = decode_production(members['DATA/NISVDATA.BIN'][offsets[4]:offsets[5]]).output
    for index in range(104):
        check('nisv_squad_names', str(index), decode_text(names, 34 + 286 * index, table).text, offset=34 + 286 * index, data=names)
    for row in map_names:
        check('map_names', row['id'], decode_text(members['MAP/MAPNAME.BIN'], 256 * row['index'], table).text, row['source'], 256 * row['index'], data=members['MAP/MAPNAME.BIN'])
    offsets = struct.unpack_from('<206I', members['HEDBDY/HB.BIN'], 30320)
    decoded = {}
    def chunk(index):
        if index not in decoded:
            decoded[index] = decode_production(members['DATA/STAGE.BIN'][offsets[index]:offsets[index + 1]]).output
        return decoded[index]
    for group in groups:
        layout = contract['stage_layouts'].get(str(group.stage_index), {}) if best else {}
        for cell in group.cells:
            shift = layout.get('second_shift', 0) if 'second_region' in layout and cell.offset >= layout['second_region'] else layout.get('shift', 0)
            target = cell.offset + shift
            check('stage_default_formations', f'{group.stage_index}/{cell.offset:#x}', decode_text(chunk(group.stage_index), target, table).text, cell.source_text, target, data=chunk(group.stage_index))
    original_offsets = struct.unpack_from('<206I', native['HEDBDY/HB.BIN'], 30320)
    for index in stage_indices:
        current = parse_stage(chunk(index), table, stage_index=index,
                              function_address=struct.unpack_from('<I', members[executable], (0x2ff830 if best else 0x2ff0b0) + 4 * index)[0],
                              base_address=0x756ef0 if best else 0x7566f0)
        old = decode_production(native['DATA/STAGE.BIN'][original_offsets[index]:original_offsets[index + 1]]).output
        parsed = parse_stage(old, source_table, stage_index=index,
                             function_address=struct.unpack_from('<I', native['SLPS_258.87'], 0x2ff0b0 + 4 * index)[0])
        originals = {row.entry_id: row.text for row in parsed.entries}
        speaker_offsets = {}
        for row in current.entries:
            if row.kind == 'dialogue': speaker_offsets.setdefault(row.speaker_id, row.text_offset)
        for row in current.entries:
            target = speaker_offsets[row.speaker_id] if row.kind == 'speaker' else row.text_offset
            check('stage_' + row.kind, row.entry_id, row.text, originals.get(row.entry_id), target, data=chunk(index))
    report = dict(stored_visible_space_code_counts=dict(stored_space_code_counts),
                  safe_decoded_ascii_space_entries=safe_decoded_ascii_space_entries,
                  safe_decoded_ascii_space_entry_count=len(safe_decoded_ascii_space_entries),
                  native_exact_match_fallbacks=native_fallbacks, edition=edition, iso=str(iso), iso_sha256=sha256_file(iso), counts=dict(counts),
                  total_entries=sum(counts.values()), findings=findings, findings_count=len(findings),
                  preserved_native_strings=native_preserved, preserved_native_string_count=len(native_preserved),
                  native_control_spaces_excluded=True, method='typed ownership, version-mapped offsets, byte-unit classified visible spaces, native-control exclusions, reviewed safe blank-glyph aliases; no whole-binary byte grep')
    reports.append(report)
    (ROOT / f'work/analysis/best-land-heat-20261006/space-audit-{edition}-latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(edition, report['total_entries'], 'findings', len(findings), 'native preserved', len(native_preserved), flush=True)
output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'work/analysis/best-land-heat-20261006/space-audit.json'
output.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + '\n')
