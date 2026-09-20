"""Install native Japanese period pixels in current SP, without text changes."""
from pathlib import Path
import json
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import read_member, file_sha, verify_iso_ranges, write_json, sha, require
from special_disc.source import CURRENT_ISO, SOURCE_ISO
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.iso9660 import scan_iso9660, member_map
from srwz.font_profile import load_font_profile
from srwz.native_period import native_period_metadata, replace_period_slots


def main():
    receipt_path = CURRENT_ISO.with_suffix('.json')
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    baseline_sha = file_sha(CURRENT_ISO)
    require(baseline_sha == receipt['iso']['sha256'], 'SP current ISO/receipt drift')
    members = member_map(scan_iso9660(CURRENT_ISO))
    source_members = member_map(scan_iso9660(SOURCE_ISO))
    exe_name, member = 'SLPS_259.20', 'DATA/VT1.BIN'
    exe = read_member(CURRENT_ISO, members, exe_name)
    vt1 = read_member(CURRENT_ISO, members, member)
    source_exe = read_member(SOURCE_ISO, source_members, exe_name)
    source_vt1 = read_member(SOURCE_ISO, source_members, member)
    a, b = struct.unpack_from('<II', exe, 0x353790 + 3 * 4)
    sa, sb = struct.unpack_from('<II', source_exe, 0x353790 + 3 * 4)
    original = decode_production(source_vt1[sa:sb]).output
    require(sha(original) == 'e68a24df2daaf16f472e55e0ba9b2282752bb70225aedc0bbb8aeef7713662bd',
            'Japanese source font identity drift')
    before = decode_production(vt1[a:b])
    require(sha(before.output) == receipt['decoded_font_sha256'], 'current decoded font drift')
    proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
    require(file_sha(proposal) == receipt['proposal_sha256'], 'current encoding proposal drift')
    mapping = json.loads(proposal.read_text())
    assignments = [r for key in ('assignments', 'surface_alias_assignments',
                                 'source_compatibility_assignments') for r in mapping[key]]
    after, changed = replace_period_slots(before.output, original, assignments)
    if not changed:
        print('SP current already uses native Japanese period pixels')
        return
    require(changed == [2836, 4467], f'unexpected period slot changes: {changed}')
    codec = load_font_profile(ROOT, ROOT/'config/fonts/zh-release-font.json')['codec']
    packed = reencode_changed_suffix(vt1[a:b], after, **codec,
                                    max_output_size=b-a, original_result=before)
    require(len(packed) <= b-a and decode_production(packed).output == after,
            'period font roundtrip or slot budget failed')
    output = vt1[:a] + packed + bytes(b-a-len(packed)) + vt1[b:]
    report = dict(status='native_period_pixels_static_verified_runtime_pending',
        source=native_period_metadata(original), changed_glyphs=changed,
        characters=['.', '．'], codes_unchanged=True, renderer_widths_unchanged=True,
        previous_iso_sha256=baseline_sha, previous_font_sha256=sha(before.output),
        decoded_font_sha256=sha(after), slot_bytes=b-a, encoded_bytes=len(packed),
        proposal_sha256=file_sha(proposal))
    temporary = CURRENT_ISO.with_suffix('.native-period.tmp.iso')
    require(not temporary.exists(), 'period temporary ISO already exists')
    proof = ROOT / 'work/verification/native-period-sp'
    proof.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(CURRENT_ISO, temporary)
        at = members[member].extent_lba * 2048
        with temporary.open('r+b') as stream:
            stream.seek(at); stream.write(output)
        reread = member_map(scan_iso9660(temporary))
        require(members == reread, 'ISO member layout changed')
        require(read_member(temporary, reread, member) == output, 'VT1 ISO readback mismatch')
        report['protected_iso_ranges'] = verify_iso_ranges(CURRENT_ISO, temporary, [(at+a, at+b)])
        output_sha = file_sha(temporary)
        require(file_sha(CURRENT_ISO) == baseline_sha and receipt_path.read_bytes() == receipt_bytes,
                'SP current changed concurrently; refusing to overwrite')
        (proof/'previous-manifest.json').write_bytes(receipt_bytes)
        receipt['iso']['sha256'] = output_sha
        receipt['files'][member] = sha(output)
        receipt['decoded_font_sha256'] = sha(after)
        receipt['period_glyph_update'] = report
        # The inherited proposal still describes unchanged encoding assignments;
        # this explicit raster override supersedes its old period raster hashes.
        report['inherited_proposal_note'] = 'Encoding unchanged; only period raster hashes superseded by this receipt.'
        receipt['status'] = report['status']
        receipt['runtime'] = 'pending after native period update'
        receipt.get('baseline', {}).pop('delta', None)
        temporary.replace(CURRENT_ISO)
        write_json(receipt_path, receipt)
        write_json(proof/'readback.json', dict(report, iso=receipt['iso']))
        print(json.dumps(dict(iso=receipt['iso'], changed_glyphs=changed), indent=2))
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
