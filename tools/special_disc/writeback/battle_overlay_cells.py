"""Copy selected frozen battle texts into SP without replacing its atlas/CLUT."""
from pathlib import Path
import hashlib
import json

from build_tricmn_battle_overlays import _frozen_component
from srwz.psmt4 import unswizzle_psmt4, swizzle_psmt4
from srwz.tim2 import parse_tim2

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'config/assets/tricmn-battle-overlays-zh.json'
MEMBER = 'BTL/TRICMN.BIN'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _inputs(profiles, group):
    config = json.loads(CONFIG.read_text())
    payload, _ = _frozen_component(ROOT, CONFIG)
    picture_index, label_count = {'status': (1, 10), 'prompt': (1, 10),
                                  'title': (0, 12), 'ability': (2, 19)}[group]
    picture = config['tim2']['pictures'][picture_index]
    labels = [row for row in config['labels'] if row['render_profile'] in profiles]
    if len(labels) != label_count or any(row['picture_index'] != picture_index for row in labels):
        raise ValueError('SP '+group+' rectangle inventory drift')
    return config, payload, picture, labels


def _indexes(data, config, picture):
    record = parse_tim2(data, offset=config['tim2']['record_offset'])
    actual = record.pictures[config['tim2']['pictures'].index(picture)]
    if (actual.width, actual.height, actual.image_size) != (512, 256, 65536):
        raise ValueError('SP battle atlas geometry drift')
    at = picture['image_offset']
    return unswizzle_psmt4(data[at:at + picture['image_size']], 512, 256, row_major_pages=True)


def verify_cells(data, profiles, group):
    config, frozen, picture, labels = _inputs(profiles, group)
    actual = _indexes(data, config, picture)
    expected = _indexes(frozen, config, picture)
    rows = []
    for label in labels:
        x, y, width, height = label['rect']
        cell = b''.join(actual[(y+j)*512+x:(y+j)*512+x+width] for j in range(height))
        reference = b''.join(expected[(y+j)*512+x:(y+j)*512+x+width] for j in range(height))
        if cell != reference:
            raise ValueError('SP '+group+' cell readback drift: ' + label['entry_id'])
        rows.append(dict(entry_id=label['entry_id'], rect=label['rect'], indexes_sha256=sha(cell)))
    return dict(config_sha256=sha(CONFIG.read_bytes()), snapshot=config['frozen_snapshot'],
                labels=rows, status='static_verified_runtime_pending')


def apply_cells(data, profiles, group):
    config, frozen, picture, labels = _inputs(profiles, group)
    before = _indexes(data, config, picture)
    expected = _indexes(frozen, config, picture)
    edited = bytearray(before)
    owned = set()
    for label in labels:
        x, y, width, height = label['rect']
        for j in range(height):
            start = (y+j)*512+x
            edited[start:start+width] = expected[start:start+width]
            owned.update(range(start, start+width))
    if any(a != b and i not in owned for i, (a, b) in enumerate(zip(before, edited))):
        raise ValueError('SP '+group+' delta escaped text rectangles')
    at, size = picture['image_offset'], picture['image_size']
    out = data[:at] + swizzle_psmt4(edited, 512, 256, row_major_pages=True) + data[at+size:]
    if len(out) != len(data) or out[:at] != data[:at] or out[at+size:] != data[at+size:]:
        raise ValueError('SP battle member metadata changed')
    report = verify_cells(out, profiles, group)
    report.update(input_sha256=sha(data), output_sha256=sha(out),
                  changed_texels=sum(a != b for a, b in zip(before, edited)),
                  non_target_pixels_exact=True, headers_clut_trailing_exact=True)
    return out, report
