"""Read-only ISO member audit; writes evidence and an offline indexed comparison."""
from pathlib import Path
import datetime
import hashlib
import json
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.iso9660 import member_map, scan_iso9660
from srwz.tim2 import parse_tim2

OUT = ROOT / 'docs/issue-assets/robot-specifications-20260929'
OUT.mkdir(parents=True, exist_ok=True)
WORK = ROOT / 'work/analysis/robot-specifications-20260929'
WORK.mkdir(parents=True, exist_ok=True)
KVM, KVP = 'KURODATA/KVMDATA.BIN', 'KURODATA/KVPDATA.BIN'
RECT = (106, 0, 112, 16)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_iso(path):
    path = ROOT / path
    before = path.stat()
    members = member_map(scan_iso9660(path))
    data, locks = {}, {}
    with path.open('rb') as f:
        for name in (KVM, KVP):
            m = members[name]
            f.seek(m.extent_lba * 2048)
            data[name] = f.read(m.size)
            assert len(data[name]) == m.size
            locks[name] = dict(size=m.size, sha256=sha(data[name]), extent_lba=m.extent_lba)
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return data, dict(path=str(path.relative_to(ROOT)), size=before.st_size,
                     mtime_ns=before.st_mtime_ns, members=locks,
                     identity_scope='actual member readback; full ISO hash not computed')


def page(data):
    # All editions use the verified 33,344-byte TIM2 page slots for page 2.
    p = parse_tim2(data, offset=66688).pictures[0]
    assert (p.width, p.height, p.image_type, p.image_size, p.clut_type) == (256, 256, 4, 32768, 1)
    a = p.offset + p.header_size
    return bytes(v for b in data[a:a+p.image_size] for v in (b & 15, b >> 4)), data[66688:a] + data[a+p.image_size:100032]


def crop(indices, rect=RECT):
    u, v, r, b = rect
    return bytes(indices[y * 256 + x] for y in range(v, b) for x in range(u, r))


sp_config = json.loads((ROOT / 'config/assets/special-disc/title-atlas.json').read_text())
sp_title = next(t for t in sp_config['registered_titles'] if t['label'] == 'ROBOTS SPECIFICATIONS')
main_offsets = list(range(0x1DE5E, 0x1DF7C, 22))
assert len(main_offsets) == 13
sources = [
    ('original', 'rom/original.iso', 'build/iso/zh-release-original/current-original.iso'),
    ('best', 'rom/best.iso', 'build/iso/zh-release-best/current-best.iso'),
    ('sp', 'rom/Super Robot Taisen Z - Special Disc [J].iso', 'build/iso/special-disc/sp-current.iso'),
]
report = dict(schema_version=1, audited_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              status='regression_confirmed_by_static_iso_readback; repair_not_applied',
              screenshot_iso_identity='not supplied by user',
              glyph=dict(letter='I', page=2, uv=list(RECT), unique_pixel_count=96), editions={})
report['user_evidence'] = dict(path=str((OUT/'user-report.png').relative_to(ROOT)),
    sha256=sha((OUT/'user-report.png').read_bytes()))
report['audit_script_sha256'] = sha(Path(__file__).read_bytes())
main_source = None
for edition, source_path, current_path in sources:
    source, source_lock = read_iso(source_path)
    current, current_lock = read_iso(current_path)
    before, before_container = page(source[KVM])
    after, after_container = page(current[KVM])
    assert before_container == after_container, 'page 2 metadata/CLUT/trailer drift'
    offsets = main_offsets if edition != 'sp' else [r['offset'] for r in sp_title['records']]
    rows = []
    for off in offsets:
        old, new = source[KVP][off:off+22], current[KVP][off:off+22]
        assert old == new and old[0] & 15 == 5 and old[4] & 15 == 2
        uv = list(old[-4:])
        old_pixels, new_pixels = crop(before, uv), crop(after, uv)
        changed = sum(a != b for a, b in zip(old_pixels, new_pixels))
        assert changed == (72 if tuple(uv) == RECT else 0)
        rows.append(dict(offset=off, offset_hex=hex(off), raw_hex=old.hex(), uv=uv,
                         drawing_unchanged=True, changed_index_pixels=changed))
    assert sum(r['changed_index_pixels'] > 0 for r in rows) == (4 if edition == 'sp' else 2)
    report['editions'][edition] = dict(source=source_lock, current=current_lock,
        page2_container_unchanged=True, source_I_sha256=sha(crop(before)),
        current_I_sha256=sha(crop(after)), changed_unique_I_pixels=72,
        title_records=rows)
    if edition == 'original':
        main_source = (source, current, before, after)

assert len({v['source_I_sha256'] for v in report['editions'].values()}) == 1
assert len({v['current_I_sha256'] for v in report['editions'].values()}) == 1
info_path = ROOT / 'work/build/ui-info-atlas-zh/components/KURODATA/KVMDATA.BIN'
info_indices, _ = page(info_path.read_bytes())
assert sha(crop(info_indices)) == report['editions']['original']['current_I_sha256']
report['responsible_component'] = dict(path=str(info_path.relative_to(ROOT)),
    sha256=sha(info_path.read_bytes()), config='config/assets/ui-info-atlas-zh.json',
    source_text='SHIP', translation='机体', write_rect=[80, 0, 49, 16],
    current_I_matches_component_exactly=True)

# Visual comparison only: same linear index-to-gray ramp on both sides, nearest
# sampling from the verified KVP rectangles. This is not a GS/PCSX2 render.
source, current, before, after = main_source
rows = report['editions']['original']['title_records']
width, height = 236, 16
for label, indices in [('source', before), ('current', after)]:
    canvas = bytearray(width * height)
    for row in rows:
        raw = bytes.fromhex(row['raw_hex'])
        x1, _, x2, _ = struct.unpack_from('<4h', raw, 10)
        u, v, r, b = row['uv']
        for y in range(height):
            for x in range(x2 - x1):
                dest = x1 + 252 + x
                if 0 <= dest < width:
                    val = indices[(v + y) * 256 + u + min(r-u-1, x*(r-u)//(x2-x1))]
                    if val:
                        canvas[y*width+dest] = val * 17
    target = WORK / f'{label}-title.png'
    subprocess.run(['magick', '-size', f'{width}x{height}', '-depth', '8', 'gray:-',
                    '-filter', 'point', '-resize', '300%', str(target)], input=canvas, check=True)
subprocess.run(['magick', '-background', '#121212', '-fill', '#eeeeee', '-font', '/System/Library/Fonts/Helvetica.ttc',
                '-pointsize', '19', 'label:SOURCE | original indexed samples',
                str(WORK / 'source-title.png'), 'label:CURRENT | same references, overwritten I',
                str(WORK / 'current-title.png'), 'label:Offline diagnostic - not an emulator screenshot',
                '-gravity', 'West', '-append', '-bordercolor', '#121212', '-border', '16',
                str(OUT / 'comparison.png')], check=True)
report['comparison'] = dict(path=str((OUT/'comparison.png').relative_to(ROOT)),
    kind='offline indexed sample reconstruction; neutral gray ramp; nearest sampling',
    runtime_validation=False)
(OUT / 'readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: dict(changed_I_pixels=v['changed_unique_I_pixels'],
    affected_draws=sum(r['changed_index_pixels'] > 0 for r in v['title_records']))
    for k,v in report['editions'].items()}, indent=2))
