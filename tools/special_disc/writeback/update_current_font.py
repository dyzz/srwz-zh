"""Append verified glyphs to sp-current without rebuilding reviewed text or images.

The old proposal must match the current ISO receipt. Existing mappings and glyph
pixels remain exact; only newly allocated glyphs, audio placement and its two
VT1 table entries may change. A temporary ISO is fully checked before promotion.
"""
from pathlib import Path
import argparse
import copy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import (WORK, load, sha, file_sha, read_member,
                                  require, write_json, verify_iso_ranges)
from install_font import sp_offsets, VT1_TABLE, FONT_DECODED_SIZE
from special_disc.source import CURRENT_ISO
from special_disc.writeback.stage_titles import verify_stage_titles
from srwz.codec import decode_production
from srwz.iso9660 import scan_iso9660, member_map

EXE, VT1 = 'SLPS_259.20', 'DATA/VT1.BIN'
GLYPH_BYTES = 288


def appended_assignments(before, after):
    """Require exact old rows, including aliases and source compatibility."""
    added = []
    for key in ('assignments', 'surface_alias_assignments',
                'source_compatibility_assignments'):
        old = before[key]
        new = after[key]
        require(new[:len(old)] == old, f'existing {key} moved or changed')
        if key != 'assignments':
            require(new == old, f'{key} unexpectedly extended')
        else:
            added = new[len(old):]
    occupied = {r['glyph_index'] for key in ('assignments',
                'surface_alias_assignments', 'source_compatibility_assignments')
                for r in before[key]}
    require(not occupied.intersection(r['glyph_index'] for r in added),
            'new assignment overwrites an existing glyph')
    return added


def verify_glyph_delta(before, after, added):
    require(len(before) == len(after) == FONT_DECODED_SIZE, 'font geometry drift')
    allowed = {r['glyph_index'] for r in added}
    changed = {i for i in range(len(before)//GLYPH_BYTES)
               if before[i*GLYPH_BYTES:(i+1)*GLYPH_BYTES] !=
                  after[i*GLYPH_BYTES:(i+1)*GLYPH_BYTES]}
    require(changed <= allowed, f'previous glyph pixels changed: {sorted(changed-allowed)}')
    for i in allowed:
        require(any(after[i*GLYPH_BYTES:(i+1)*GLYPH_BYTES]), 'new glyph is blank')
    return sorted(changed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-proposal', type=Path, required=True)
    parser.add_argument('--output', type=Path,
                        default=ROOT/'work/verification/sp-current-font')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = CURRENT_ISO.with_suffix('.json')
    manifest = load(manifest_path)
    require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'], 'current ISO identity drift')
    require(file_sha(args.previous_proposal) == manifest['proposal_sha256'],
            'previous proposal does not describe current ISO')
    proposal = WORK/'font/proposal.json'
    added = appended_assignments(load(args.previous_proposal), load(proposal))
    require(bool(added), 'no appended font assignments to install')
    font_report = load(WORK/'sp-font/report.json')
    validation = load(WORK/'font/manifest.json')
    require(validation['proposal']['sha256'] == file_sha(proposal), 'unverified proposal')
    profile = load(ROOT/'config/fonts/zh-release-font.json')
    require(load(WORK/'font/profile.json')['allocation_snapshot'] == profile['allocation_snapshot'],
            'font snapshot/profile drift')
    require(file_sha(ROOT/profile['allocation_snapshot']['path']) == profile['allocation_snapshot']['sha256'],
            'allocation snapshot drift')
    for key in ('report', 'slps', 'vt1'):
        lock = validation['font_component'][key]
        require(file_sha(ROOT/lock['path']) == lock['sha256'], f'font component drift: {key}')
    require(validation['font_component']['decoded_font_sha256'] == font_report['font']['decoded_sha256'],
            'installed font differs from verified font')
    members = member_map(scan_iso9660(CURRENT_ISO))
    old_exe, old_vt1 = (read_member(CURRENT_ISO, members, n) for n in (EXE, VT1))
    new_exe, new_vt1 = ((WORK/'sp-font'/n).read_bytes() for n in (EXE, VT1))
    for n, data in ((EXE, new_exe), (VT1, new_vt1)):
        require(sha(data) == font_report['files'][n], f'installed component drift: {n}')
    old = sp_offsets(old_exe, VT1_TABLE, len(old_vt1))
    new = sp_offsets(new_exe, VT1_TABLE, len(new_vt1))
    # Later current chunks may have their own reviewed relocation. The native
    # font component owns neither those table entries nor the later payloads.
    require(len(old) == len(new) and old[:2] == new[:2] and old[4] == new[4],
            'font/audio envelope changed')
    old_font = decode_production(old_vt1[old[3]:old[4]]).output
    new_font = decode_production(new_vt1[new[3]:new[4]]).output
    require(sha(old_font) == manifest['decoded_font_sha256'], 'current font identity drift')
    require(sha(new_font) == font_report['font']['decoded_sha256'], 'new font decode drift')
    changed = verify_glyph_delta(old_font, new_font, added)
    require(old_vt1[old[2]:old[3]] == new_vt1[new[2]:new[3]], 'audio payload changed')
    start, end = min(old[2], new[2]), old[4]
    require(not any(old_vt1[start:old[2]]) and not any(new_vt1[start:new[2]]),
            'font relocation donor is not zero padding')
    output_vt1 = old_vt1[:start] + new_vt1[start:end] + old_vt1[end:]
    output_exe = bytearray(old_exe)
    for index in (2, 3):
        at = VT1_TABLE + index*4
        output_exe[at:at+4] = new_exe[at:at+4]
    verify_stage_titles(output_vt1, bytes(output_exe))
    patches = {EXE: bytes(output_exe), VT1: output_vt1}
    require(all(len(d) == members[n].size for n, d in patches.items()), 'member size changed')
    write_json(args.output/'previous-manifest.json', manifest)
    shutil.copyfile(args.previous_proposal, args.output/'previous-proposal.json')
    temporary = CURRENT_ISO.with_suffix('.tmp.iso')
    require(not temporary.exists(), 'another current ISO update is in progress')
    try:
        shutil.copyfile(CURRENT_ISO, temporary)
        with temporary.open('r+b') as stream:
            for n, data in patches.items():
                stream.seek(members[n].extent_lba*2048); stream.write(data)
        after = member_map(scan_iso9660(temporary))
        require({n:(m.extent_lba,m.size) for n,m in after.items()} ==
                {n:(m.extent_lba,m.size) for n,m in members.items()}, 'ISO layout changed')
        for n, data in patches.items():
            require(read_member(temporary, after, n) == data, f'ISO readback mismatch: {n}')
        vt1_at, exe_at = (members[n].extent_lba*2048 for n in (VT1, EXE))
        protected = verify_iso_ranges(CURRENT_ISO, temporary,
            [(vt1_at+start, vt1_at+end), (exe_at+VT1_TABLE+8, exe_at+VT1_TABLE+16)])
        receipt = dict(status='append_only_font_verified_runtime_pending',
            previous_iso=manifest['iso'], additions=added, changed_glyphs=changed,
            existing_mappings_and_pixels_unchanged=True, audio_payload_unchanged=True,
            stage_titles_verified=True, protected_iso_ranges=protected,
            proposal_sha256=file_sha(proposal), decoded_font_sha256=sha(new_font),
            font_validation=dict(path=str((WORK/'font/manifest.json').relative_to(ROOT)),
                                 sha256=file_sha(WORK/'font/manifest.json')),
            iso=dict(path=str(CURRENT_ISO.relative_to(ROOT)), size=temporary.stat().st_size,
                     sha256=file_sha(temporary)))
        updated = copy.deepcopy(manifest)
        updated.update(iso=receipt['iso'], status=receipt['status'],
            proposal_sha256=receipt['proposal_sha256'], decoded_font_sha256=sha(new_font),
            runtime='pending after font update')
        updated['files'].update({n:sha(d) for n,d in patches.items()})
        updated['font_update'] = dict(receipt=str((args.output/'readback.json').relative_to(ROOT)),
            previous_manifest=str((args.output/'previous-manifest.json').relative_to(ROOT)),
            full_corpus_rebuilt=False,
            inherited_metadata='Text/image coverage and build components describe the previous build. Only the appended font was rebuilt here.')
        # The canary delta may have been regenerated; the inherited baseline is history.
        updated['baseline'].pop('delta', None)
        require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'], 'current ISO changed during update')
        temporary.replace(CURRENT_ISO)
        write_json(manifest_path, updated)
        write_json(args.output/'readback.json', receipt)
        print(receipt['iso'])
        print('Added characters:', ''.join(r['character'] for r in added))
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
