"""Create isolated current-ISO candidates changing only the declared I records."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.iso9660 import member_map, scan_iso9660
from srwz.release_inputs import copy_file
from srwz.file_identity import sha256_file
from srwz.ui_headings import apply_shared_letter_patches
from special_disc.writeback.title_atlas import apply_title_atlas
from special_disc.writeback.build_text_candidate import verify_iso_ranges

EVIDENCE = ROOT / 'docs/issue-assets/robot-specifications-20260929'
previous = json.loads((EVIDENCE / 'readback.json').read_text())
config = json.loads((ROOT / 'config/assets/ui-headings-zh.json').read_text())
KVM, KVP = 'KURODATA/KVMDATA.BIN', 'KURODATA/KVPDATA.BIN'
report = dict(status='isolated_candidates_static_verified_runtime_pending', editions={})
for edition, entry in previous['editions'].items():
    source = ROOT / entry['current']['path']
    source_hash = sha256_file(source)
    members = member_map(scan_iso9660(source))
    data = {}
    with source.open('rb') as f:
        for name in (KVM, KVP):
            m = members[name]; f.seek(m.extent_lba * 2048); data[name] = f.read(m.size)
            assert hashlib.sha256(data[name]).hexdigest() == entry['current']['members'][name]['sha256']
    if edition == 'sp':
        atlas, fixed, receipt = apply_title_atlas(data[KVM], data[KVP])
        assert atlas == data[KVM]
        wanted_offsets = [0x2077a, 0x20790, 0x207d2, 0x207e8]
    else:
        fixed = apply_shared_letter_patches(data[KVM], data[KVP], config)
        wanted_offsets = [0x1def8, 0x1df24]
    allowed = {offset + i for offset in wanted_offsets for i in (10, 18, 19, 20, 21)}
    actual = {i for i, (a, b) in enumerate(zip(data[KVP], fixed)) if a != b}
    assert actual == allowed and len(fixed) == len(data[KVP])
    dest = ROOT / f'build/iso/robot-specifications-20260929/{edition}.iso'
    assert not dest.exists(), f'refusing to replace {dest}'
    copy_file(source, dest)
    m = members[KVP]; start = m.extent_lba * 2048
    with dest.open('r+b') as f:
        f.seek(start); f.write(fixed)
    after = member_map(scan_iso9660(dest))
    assert {n:(m.extent_lba,m.size) for n,m in members.items()} == {n:(m.extent_lba,m.size) for n,m in after.items()}
    with dest.open('rb') as f:
        f.seek(start); assert f.read(m.size) == fixed
    protected = verify_iso_ranges(source, dest, [(start, start + m.size)])
    assert sha256_file(source) == source_hash
    report['editions'][edition] = dict(source=str(source.relative_to(ROOT)), source_sha256=source_hash,
        candidate=str(dest.relative_to(ROOT)), candidate_sha256=sha256_file(dest), size=dest.stat().st_size,
        drawing_member_sha256=hashlib.sha256(fixed).hexdigest(), changed_bytes=len(actual),
        changed_member_offsets=sorted(actual), atlas_unchanged=True, geometry='left edge +1; right edge unchanged',
        donor_uv=[14,16,19,32], iso_layout_unchanged=True, protected_iso_ranges=protected)
    print(edition, 'candidate verified:', len(actual), 'changed bytes', flush=True)
(EVIDENCE / 'candidate-readback.json').write_text(json.dumps(report, indent=2) + '\n')
