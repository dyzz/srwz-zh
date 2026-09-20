"""Verify SP squad coverage, shared glyphs, writers and fixed compressed slots.

Only writes a review report. Does not rebuild or replace an ISO/component.
"""
from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback'), str(Path(__file__).resolve().parent)]
import migrate_stage_dialogue as st
import migrate_nisv as nisv
from stage_auxiliary import formation_groups, write_formations
from stage_bindings import StageBindings
from squad_names import load_names, patch_slots, sha, INVENTORY_PATH, CORPUS_PATH
from scan_squad_names import stage_offsets
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import decode_text, normalize_original_fullwidth_ascii


def verify():
    inventory, entries = load_names()
    proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
    table, _, overrides, readback = st.mst.encoding_tables(proposal)
    font = json.loads(proposal.read_text())
    characters = {a['character'] for key in ('assignments', 'surface_alias_assignments',
                  'source_compatibility_assignments') for a in font[key]}
    missing = sorted({c for row in entries.values() for c in row['translation']
                      if ord(c) > 127 and c != '　' and c not in characters})
    if missing:
        raise ValueError(f'unverified squad glyphs: {missing}')
    bindings = StageBindings(ROOT, allow_draft=True)
    members = {n: st.read_disc_member(n) for n in inventory['members']}
    if {n: sha(data) for n, data in members.items()} != inventory['members']:
        raise ValueError('squad source archive identity drift')
    grouped = defaultdict(list)
    for slot in inventory['slots']:
        grouped[slot['member'], slot['chunk']].append(slot)
    reports = []
    consumed_direct = set()
    for (member, chunk), slots in sorted(grouped.items()):
        archive = members[member]
        offsets = (stage_offsets(archive, members[st.HB]) if member == st.STAGE else
                   nisv.sp_offsets(members['SLPS_259.20'], nisv.SP_TABLE, len(archive)))
        start, end = offsets[chunk:chunk + 2]
        stored = archive[start:end]
        original = decode_production(stored)
        rebuilt = patch_slots(original.output, slots, entries, table, overrides, readback)
        if member == st.STAGE:
            groups = formation_groups(original.output, table, chunk, st.sd.SD_STAGE_BASE)
            actual, regions, rows = write_formations(original.output, groups, chunk, bindings,
                                                     table, overrides, readback, st.sd.SD_STAGE_BASE)
            if actual != rebuilt or len(regions) != len(slots):
                raise ValueError('STAGE writer differs from independent locked-slot patch')
            consumed_direct.update(r['target'] for r in rows)
        packed = reencode_changed_suffix(stored, rebuilt, strategy='rust-fit',
                                         original_result=original)
        reread = decode_production(packed).output
        if reread != rebuilt:
            raise ValueError('squad archive roundtrip mismatch')
        allowed = bytearray(len(reread))
        for slot in slots:
            at, size = slot['offset'], slot['capacity']
            allowed[at:at + size] = b'\1' * size
            expected = normalize_original_fullwidth_ascii(entries[slot['source_text']]['translation'])
            if decode_text(reread, at, readback).text != expected:
                raise ValueError('squad independent decoded readback mismatch')
        if len(reread) != len(original.output) or any(a != b and not allowed[i]
                for i, (a, b) in enumerate(zip(original.output, reread))):
            raise ValueError('squad non-name bytes changed')
        report = dict(member=member, chunk=chunk, slots=len(slots), compressed=len(packed),
                      allocated=len(stored), headroom=len(stored) - len(packed),
                      decoded_sha256=sha(reread), non_name_bytes_unchanged=True)
        reports.append(report)
        print(f'{member} {chunk:03d}: {len(slots)} names; {report["headroom"]} bytes free', flush=True)
    direct = {k for k in bindings.direct if '/formation/' in k}
    if not direct <= consumed_direct:
        raise ValueError(f'existing SP formation bindings lost: {direct - consumed_direct}')
    return dict(status='decoded_name_writeback_verified_runtime_pending', counts=inventory['counts'],
        glyphs_missing=missing, existing_direct_bindings=len(direct),
        sources=dict(Counter(r['translation_source'] for r in entries.values())),
        inputs={p: sha((ROOT / p).read_bytes()) for p in (INVENTORY_PATH, CORPUS_PATH)},
        proposal_sha256=sha(proposal.read_bytes()), chunks=reports,
        scope='Names-only compression against original archives; does not establish capacity with all other pending Pro edits.',
        iso_modified=False, runtime='not_tested')


def verify_components(directory):
    inventory, entries = load_names()
    proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
    _, _, _, readback = st.mst.encoding_tables(proposal)
    stage_report = json.loads((directory / 'stage/report.json').read_text())
    nisv_report = json.loads((directory / 'nisv/report.json').read_text())
    if stage_report['failures'] or stage_report['pending_native_targets']:
        raise ValueError('combined STAGE build has pending or failed bindings')
    for reference in (INVENTORY_PATH, CORPUS_PATH):
        expected = sha((ROOT / reference).read_bytes())
        if (stage_report['inputs'][reference] != expected or
                nisv_report['chunks']['squad names (chunk 4)']['inputs'][reference] != expected):
            raise ValueError('squad component input drift')
    hb, exe = st.read_disc_member(st.HB), st.read_disc_member('SLPS_259.20')
    count = 0
    for member, folder, report in ((st.STAGE, 'stage', stage_report), (nisv.MEMBER, 'nisv', nisv_report)):
        data = (directory / folder / member).read_bytes()
        if sha(data) != report['files'][member]:
            raise ValueError('squad component member hash drift')
        offsets = stage_offsets(data, hb) if member == st.STAGE else nisv.sp_offsets(exe, nisv.SP_TABLE, len(data))
        cache = {}
        for slot in inventory['slots']:
            if slot['member'] != member:
                continue
            chunk = slot['chunk']
            if chunk not in cache:
                cache[chunk] = decode_production(data[offsets[chunk]:offsets[chunk + 1]]).output
            text = decode_text(cache[chunk], slot['offset'], readback).text
            if text != normalize_original_fullwidth_ascii(entries[slot['source_text']]['translation']):
                raise ValueError('combined component squad readback mismatch')
            count += 1
    return dict(status='combined_components_reread', slots=count,
        stage_chunks=len(stage_report['chunk_reports']),
        stage_minimum_headroom=min(r['allocated'] - r['compressed'] for r in stage_report['chunk_reports']),
        nisv_headroom=nisv_report['chunks']['squad names (chunk 4)']['headroom'],
        stage_sha256=stage_report['files'][st.STAGE], nisv_sha256=nisv_report['files'][nisv.MEMBER])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', type=Path)
    args = parser.parse_args()
    report = verify()
    if args.components:
        report['components'] = verify_components(args.components)
    out = ROOT / 'work/review/special-disc/squad-names/verification.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['counts'], ensure_ascii=False))


if __name__ == '__main__':
    main()
