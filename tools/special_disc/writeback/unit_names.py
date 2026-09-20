"""Guarded writeback of reviewed SP-native unit names into COMPDATA."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.font import decode_glyph, standard_glyph_index
from srwz.text import decode_text, encode_text

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/unit-names.json'
MEMBER = 'DATA/COMPDATA.BN'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inputs():
    contract = json.loads(CONTRACT.read_text())
    require(contract['schema_version'] == 1 and contract['member'] == MEMBER,
            'SP unit-name contract identity drift')
    corpus_path = ROOT / contract['corpus']
    entries = [r for r in json.loads(corpus_path.read_text())['entries']
               if r['category'] == contract['category']]
    rows = {r['id']: r for r in entries}
    require(len(rows) == len(entries) == len(contract['entries']) and
            set(rows) == {r['id'] for r in contract['entries']}, 'SP unit-name coverage drift')
    for slot in contract['entries']:
        row = rows[slot['id']]
        require(row['source_text'] == slot['source_text'] and
                sha(row['source_text'].encode()) == row['source_text_sha256'] == slot['source_text_sha256'],
                'SP unit-name source identity drift')
        require(row['editorial_status'] == 'reviewed' and bool(row['translation']),
                'SP unit name lacks reviewed translation')
        require(row['locations'] == [dict(member=MEMBER, source_offset=slot['offset'],
                offset=slot['offset'], pointer_sites=slot['pointer_sites'])], 'SP unit-name location drift')
    return contract, rows, corpus_path


def check_pointers(data, contract):
    require(len(data) == contract['decoded_size'], 'SP COMPDATA decoded size drift')
    table = contract['unit_table']
    for slot in contract['entries']:
        pointer = contract['base_address'] + slot['offset']
        actual = [table['start'] + i * table['stride'] for i in range(table['count'])
                  if struct.unpack_from('<I', data, table['start'] + i * table['stride'])[0] == pointer]
        require(actual == slot['pointer_sites'], f"SP unit-name pointer drift: {slot['id']}")


def verify_unit_names(archive, readback):
    contract, rows, _ = inputs()
    data = decode_production(archive).output
    check_pointers(data, contract)
    labels = []
    for slot in contract['entries']:
        expected = rows[slot['id']]['translation']
        for site in slot['pointer_sites']:
            at = struct.unpack_from('<I', data, site)[0] - contract['base_address']
            actual = decode_text(data, at, readback, end=at + slot['capacity'])
            require(actual.text == expected and actual.terminator == 'nul' and
                    not any(data[at + actual.consumed:at + slot['capacity']]),
                    f"SP unit-name readback mismatch: {slot['id']}")
        labels.append(dict(id=slot['id'], translation=expected, offset=slot['offset'],
                           pointer_sites=slot['pointer_sites']))
    return labels


def verify_unit_name_glyphs(font, proposal, table, overrides):
    contract, rows, _ = inputs()
    registered = {a['character'] for key in ('assignments', 'surface_alias_assignments',
                  'source_compatibility_assignments') for a in proposal[key]}
    used = {ch for r in rows.values() for ch in r['translation']}
    missing = used - registered
    preserved = []
    for glyph in contract['preserved_glyphs']:
        char, code = glyph['character'], int(glyph['code'], 0)
        if char not in missing:
            continue
        require(encode_text(char, table, overrides=overrides) == code.to_bytes(2, 'big'),
                'SP preserved unit-name glyph code drift')
        pixels = decode_glyph(font, standard_glyph_index(code))
        require(sha(pixels) == glyph['pixels_sha256'], 'SP preserved unit-name glyph pixels drift')
        preserved.append(dict(character=char, code=glyph['code'], pixels_sha256=sha(pixels)))
        missing.remove(char)
    require(not missing, f'SP unit-name unverified glyphs: {sorted(missing)}')
    return preserved


def apply_unit_names(archive, table, overrides, readback, font, proposal):
    contract, rows, corpus_path = inputs()
    preserved = verify_unit_name_glyphs(font, proposal, table, overrides)
    decoded = decode_production(archive)
    check_pointers(decoded.output, contract)
    data = bytearray(decoded.output)
    changed = []
    for slot in contract['entries']:
        at, size = slot['offset'], slot['capacity']
        source = bytes.fromhex(slot['source_hex'])
        require(len(source) == size and decode_text(source, 0, table).text == slot['source_text'],
                'SP unit-name source bytes drift')
        encoded = encode_text(rows[slot['id']]['translation'], table, overrides=overrides, terminate=True)
        require(len(encoded) <= size, f"SP unit-name overflow: {slot['id']}")
        replacement = encoded + bytes(size - len(encoded))
        before = bytes(data[at:at + size])
        require(before in (source, bytes.fromhex(slot['accepted_migrated_hex']), replacement),
                f"SP unit-name preimage drift: {slot['id']}")
        if before != replacement:
            changed.append(slot['id'])
        data[at:at + size] = replacement
    require(len(data) == len(decoded.output), 'SP unit-name decoded size changed')
    if data == decoded.output:
        output, packed_size = archive, decoded.consumed
    else:
        packed = reencode_changed_suffix(archive, bytes(data), strategy='rust-fit',
                                        max_output_size=len(archive), original_result=decoded)
        require(len(packed) <= len(archive), 'SP unit-name compressed member overflow')
        require(decode_production(packed).output == data, 'SP unit-name compression roundtrip mismatch')
        output, packed_size = packed + bytes(len(archive) - len(packed)), len(packed)
    labels = verify_unit_names(output, readback)
    return output, dict(labels=labels, entries=len(labels),
        pointer_count=sum(len(r['pointer_sites']) for r in labels), changed_ids=changed,
        compressed_bytes=packed_size, allocated_bytes=len(archive),
        decoded_sha256=sha(data), non_name_bytes_preserved=True, preserved_glyphs=preserved,
        contract_sha256=sha(CONTRACT.read_bytes()),
        corpus=dict(path=contract['corpus'], sha256=sha(corpus_path.read_bytes())), runtime='pending')


def main():
    """Write a separate ISO from a pinned existing candidate and inherit its manifest."""
    import argparse
    import shutil
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_text_candidate import file_sha, read_member, verify_iso_ranges, write_json
    from migrate_slps_text import encoding_tables
    from srwz.iso9660 import member_map, scan_iso9660

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-iso', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output-iso', type=Path, required=True)
    parser.add_argument('--proposal', type=Path, required=True)
    args = parser.parse_args()
    source, dest = args.source_iso.resolve(), args.output_iso.resolve()
    require(source != dest and not dest.exists(), 'SP unit-name output must be new and separate')
    require(file_sha(source) == args.source_sha256, 'SP unit-name source ISO drift')
    manifest = json.loads(source.with_suffix('.json').read_text())
    require(manifest['iso']['sha256'] == args.source_sha256, 'SP source manifest drift')
    require(file_sha(args.proposal) == manifest['proposal_sha256'], 'SP source font proposal drift')
    members = member_map(scan_iso9660(source))
    require('SLPS_259.20' in members, 'SP unit-name candidate requires Special Disc')
    before = read_member(source, members, MEMBER)
    require(sha(before) == manifest['files'][MEMBER], 'SP source COMPDATA drift')
    exe = read_member(source, members, 'SLPS_259.20')
    a, b = struct.unpack_from('<2I', exe, 0x353790 + 3 * 4)
    vt = members['DATA/VT1.BIN']
    with source.open('rb') as stream:
        stream.seek(vt.extent_lba * 2048 + a)
        font = decode_production(stream.read(b - a)).output
    require(sha(font) == manifest['decoded_font_sha256'], 'SP source font drift')
    table, overrides, _, readback = encoding_tables(args.proposal)
    after, report = apply_unit_names(before, table, overrides, readback, font,
                                     json.loads(args.proposal.read_text()))
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix('.tmp.iso')
    require(not temporary.exists(), 'SP unit-name temporary output exists')
    shutil.copyfile(source, temporary)
    start = members[MEMBER].extent_lba * 2048
    with temporary.open('r+b') as stream:
        stream.seek(start)
        stream.write(after)
    output_members = member_map(scan_iso9660(temporary))
    require({n: (m.extent_lba, m.size) for n, m in members.items()} ==
            {n: (m.extent_lba, m.size) for n, m in output_members.items()}, 'SP ISO layout drift')
    require(read_member(temporary, output_members, MEMBER) == after, 'SP COMPDATA ISO reread drift')
    verify_unit_names(read_member(temporary, output_members, MEMBER), readback)
    protected = verify_iso_ranges(source, temporary, [(start, start + len(after))])
    # Detect another build replacing the input during this run.
    require(file_sha(source) == args.source_sha256, 'SP source ISO changed during writeback')
    manifest['unit_names'] = report
    manifest['coverage']['additional_native_unit_names'] = report['entries']
    manifest['coverage']['additional_native_unit_name_pointers'] = report['pointer_count']
    manifest['files'][MEMBER] = sha(after)
    manifest['unit_name_overlay'] = dict(source_iso=str(source), source_sha256=args.source_sha256,
        protected_iso_ranges=protected, member_layout_preserved=True, runtime='pending')
    manifest['iso'] = dict(path=str(dest.relative_to(ROOT)), sha256=file_sha(temporary), size=temporary.stat().st_size)
    manifest['source_files'][str(Path(__file__).relative_to(ROOT))] = file_sha(Path(__file__))
    temporary.replace(dest)
    write_json(dest.with_suffix('.json'), manifest)
    print(json.dumps(dict(iso=manifest['iso'], unit_names=report), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
