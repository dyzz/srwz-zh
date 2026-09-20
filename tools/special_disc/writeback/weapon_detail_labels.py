"""SP-native, guarded runtime strings for the shared weapon detail renderer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from srwz.text import decode_text
from srwz.weapon_category_labels import apply_runtime_weapon_category_labels
from srwz.weapon_special_effects import apply_weapon_special_effect_2

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'config/products/special-disc/weapon-detail-labels.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inputs():
    contract = json.loads(CONTRACT.read_text())
    require(contract['schema_version'] == 1 and contract['member'] == 'SLPS_259.20',
            'SP weapon contract identity drift')
    lock = contract['weapon_special_effect_2']['corpus']
    corpus_bytes = (ROOT / lock['path']).read_bytes()
    require(len(corpus_bytes) == lock['size'] and
            hashlib.sha256(corpus_bytes).hexdigest() == lock['sha256'],
            'weapon effect corpus lock drift')
    return contract, json.loads(corpus_bytes)


def apply_weapon_detail_labels(executable, table, overrides, readback):
    contract, corpus = inputs()
    output, category = apply_runtime_weapon_category_labels(
        executable, contract['runtime_weapon_category_labels'])
    output, effects = apply_weapon_special_effect_2(
        output, contract['weapon_special_effect_2'], corpus,
        source_table=table, encoding_overrides=overrides)
    labels = verify_weapon_detail_labels(output, readback)
    return output, dict(category=category, effects=effects, labels=labels,
                        changed_byte_count=sum(a != b for a, b in zip(executable, output)),
                        contract_sha256=hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
                        executable_size_preserved=len(executable) == len(output), runtime='pending')


def verify_weapon_detail_labels(executable, readback):
    """Independently assemble actual MIPS immediates from the final ISO ELF."""
    contract, corpus = inputs()
    # Protect SP-specific stores, icon IDs, flag tests and branches, including
    # instructions between the individual LUI/ORI builders.
    allowed = {int(builder[key], 0) + i
               for field in contract['weapon_special_effect_2']['fields']
               for builder in field['word_builders']
               for key in ('lui_file_offset', 'ori_file_offset') if key in builder
               for i in (0, 1)}
    for context in contract['effect_contexts']:
        at = int(context['file_offset'], 0)
        for i, byte in enumerate(bytes.fromhex(context['original_hex'])):
            require(at + i in allowed or executable[at + i] == byte,
                    f'SP effect instruction context drift at 0x{at+i:X}')
    labels = {}
    for site, pairs in zip(contract['runtime_weapon_category_labels']['sites'],
                           (((0, 2), (4, 5), (8, 9), (12, 14)),
                            ((2, 3), (4, 6), (8, 10), (12, 14)))):
        at = int(site['file_offset'], 0)
        block = bytes.fromhex(site['replacement_block_hex'])
        require(executable[at:at+len(block)] == block, 'SP category ISO instruction drift')
        data = b''.join(executable[at+ori*4:at+ori*4+2] +
                        executable[at+lui*4:at+lui*4+2] for lui, ori in pairs) + b'\0'
        text = decode_text(data, 0, readback).text
        require(text == site['translation'], 'SP category ISO text drift')
        labels[site['id']] = text
    for field, row in zip(contract['weapon_special_effect_2']['fields'], corpus['entries']):
        data = bytearray()
        for builder in field['word_builders']:
            low = int(builder['ori_file_offset'], 0)
            high = builder.get('lui_file_offset')
            for key in ('lui', 'ori'):
                if key + '_file_offset' in builder:
                    at = int(builder[key + '_file_offset'], 0)
                    require(executable[at+2:at+4] == bytes.fromhex(builder[key+'_original_hex'])[2:],
                            'SP effect ISO opcode/register drift')
            data.extend(executable[low:low+2])
            data.extend(executable[int(high, 0):int(high, 0)+2] if high else b'\0\0')
        decoded = decode_text(bytes(data), 0, readback)
        require(field['id'] == row['id'] and decoded.text == row['translation'] and
                decoded.terminator == 'nul' and not any(data[decoded.consumed:]),
                'SP effect ISO text/padding drift')
        labels[field['id']] = decoded.text
    return labels


def main():
    """Make an isolated, source-pinned candidate without rebuilding other work."""
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
    source, destination = args.source_iso.resolve(), args.output_iso.resolve()
    require(source != destination, 'weapon candidate must use a separate output')
    require(not destination.exists(), 'weapon candidate output already exists')
    require(file_sha(source) == args.source_sha256, 'weapon candidate source ISO drift')
    members = member_map(scan_iso9660(source))
    require('SLPS_259.20' in members, 'weapon candidate requires Special Disc')
    before = read_member(source, members, 'SLPS_259.20')
    table, overrides, _, readback = encoding_tables(args.proposal)
    after, report = apply_weapon_detail_labels(before, table, overrides, readback)
    require(len(before) == len(after), 'weapon candidate executable size drift')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp.iso')
    require(not temporary.exists(), 'weapon candidate temporary output already exists')
    shutil.copyfile(source, temporary)
    member = members['SLPS_259.20']
    start = member.extent_lba * 2048
    with temporary.open('r+b') as stream:
        stream.seek(start)
        stream.write(after)
    output_members = member_map(scan_iso9660(temporary))
    require({n: (m.extent_lba, m.size) for n, m in members.items()} ==
            {n: (m.extent_lba, m.size) for n, m in output_members.items()}, 'weapon candidate ISO layout drift')
    reread = read_member(temporary, output_members, 'SLPS_259.20')
    require(reread == after, 'weapon candidate executable reread drift')
    labels = verify_weapon_detail_labels(reread, readback)
    protected = verify_iso_ranges(source, temporary, [(start, start + len(after))])
    report.update(status='weapon_detail_iso_readback_passed_runtime_pending',
                  source_iso=dict(path=str(source), sha256=args.source_sha256),
                  iso=dict(path=str(destination), sha256=file_sha(temporary), size=temporary.stat().st_size),
                  proposal=dict(path=str(args.proposal.resolve()), sha256=file_sha(args.proposal)),
                  iso_readback_labels=labels, protected_iso_ranges=protected,
                  executable_changed_offsets=[hex(i) for i, (a, b) in enumerate(zip(before, after)) if a != b],
                  member_layout_preserved=True)
    temporary.replace(destination)
    write_json(destination.with_suffix('.json'), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
