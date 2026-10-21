"""Copy the current frozen six-label LIBRARY image into SP's own TIM2 slot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.nisv_library_menu import build_nisv_library_menu
from srwz.tim2 import scan_tim2
from srwz.tim2_writeback import swizzle_psmt8, unswizzle_psmt8
from special_disc.writeback.install_font import sp_offsets

ROOT = Path(__file__).resolve().parents[3]
MEMBER = 'DATA/NISVDATA.BIN'
TABLE = 0x384A00


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _shared_menu(root):
    path = root / 'config/library/v0.2.0.json'
    scope = json.loads(path.read_text())
    contract = scope['library_menu_runtime_tim2']
    source = (root / scope['source_member_locks'][MEMBER]['path']).read_bytes()
    font_lock = json.loads((root / 'config/fonts/zh-localization-font.json').read_text())['primary']
    lock_data = (root / font_lock['font_lock']).read_bytes()
    if _sha(lock_data) != font_lock['font_lock_sha256']:
        raise ValueError('SP LIBRARY font lock drift')
    font = json.loads(lock_data)['font']
    font_path = root / font['path']
    if font_path.stat().st_size != font['size'] or _sha(font_path.read_bytes()) != font['sha256']:
        raise ValueError('SP LIBRARY font drift')
    if _sha(source) != scope['source_member_locks'][MEMBER]['sha256']:
        raise ValueError('SP LIBRARY main source drift')
    built, report = build_nisv_library_menu(source, contract, font_path=font_path, project_root=root)
    target = contract['target']
    decoded = decode_production(built[target['stored_start']:target['stored_end']]).output
    record = scan_tim2(decoded)[target['record_index']]
    return decoded[record.offset:record.end], contract, {
        'scope_sha256': _sha(path.read_bytes()),
        'render_snapshot': contract['writeback']['render_snapshot'],
        'labels': contract['labels'],
        'point_size': contract['writeback']['point_size'],
        'shared_record_sha256': _sha(decoded[record.offset:record.end]),
    }


def _expected(archive, executable, source_archive, root):
    shared, contract, report = _shared_menu(root)
    offsets = sp_offsets(executable, TABLE, len(archive))
    a, b = offsets[:2]
    if len(archive) != len(source_archive):
        raise ValueError('SP LIBRARY archive size drift')
    source = decode_production(source_archive[a:b]).output
    matches = [r for r in scan_tim2(source)
               if _sha(source[r.offset:r.end]) == contract['target']['record_sha256']]
    if len(matches) != 1:
        raise ValueError('SP LIBRARY source TIM2 identity drift')
    record = matches[0]
    result = decode_production(archive[a:b])
    current = result.output
    records = scan_tim2(current)
    if record not in records:
        raise ValueError('SP LIBRARY TIM2 metadata drift')
    picture = record.pictures[0]
    start = picture.offset + picture.header_size
    end = start + picture.image_size
    shared_picture = scan_tim2(shared)[0].pictures[0]
    shared_start = shared_picture.offset + shared_picture.header_size
    if (picture.width, picture.height, picture.image_type) != (256, 256, 5):
        raise ValueError('SP LIBRARY texture geometry drift')
    if current[end:record.end] != shared[shared_start + picture.image_size:]:
        raise ValueError('SP LIBRARY palette drift')
    indexes = bytearray(unswizzle_psmt8(current[start:end], 256, 256))
    desired = unswizzle_psmt8(shared[shared_start:shared_start + picture.image_size], 256, 256)
    for mask in contract['writeback']['masks']:
        for y in range(mask['y'], mask['y'] + mask['height']):
            lo = y * 256 + mask['x']
            indexes[lo:lo + mask['width']] = desired[lo:lo + mask['width']]
    new = current[:start] + swizzle_psmt8(bytes(indexes), 256, 256) + current[end:]
    report.update(chunk_index=0, record_offset=record.offset, record_size=record.size,
                  output_record_sha256=_sha(new[record.offset:record.end]),
                  non_label_pixels_preserved=True, palette_and_metadata_preserved=True,
                  non_target_chunks_preserved=True, archive_size_preserved=True)
    return new, result, a, b, report


def apply_library_menu(archive, executable, source_archive, *, root=ROOT):
    new, result, a, b, report = _expected(archive, executable, source_archive, root)
    if new == result.output:
        return archive, report
    encoded = reencode_changed_suffix(
        archive[a:a + result.consumed], new, strategy='rust-fit',
        original_result=result, max_output_size=b-a)
    if len(encoded) > b-a or decode_production(encoded).output != new:
        raise ValueError('SP LIBRARY compressed slot roundtrip failed')
    output = archive[:a] + encoded + bytes(b-a-len(encoded)) + archive[b:]
    return output, report


def verify_library_menu(archive, executable, source_archive, *, root=ROOT):
    expected, result, _, _, report = _expected(archive, executable, source_archive, root)
    if result.output != expected:
        raise ValueError('SP LIBRARY frozen label readback drift')
    return report
