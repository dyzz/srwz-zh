"""Install frozen SP title cells and their own KVP references as one component.

The indexed atlas remains a shared resource: source letters, numeric cells,
CLUTs and deferred effects are never erased. Optional bitmap strips include
neighbouring texels as gutters, so filtering sees the same edge samples.
Production builds never rasterize text or depend on authoring scratch files.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import zlib
from pathlib import Path

from srwz.tim2 import parse_tim2

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'config/assets/special-disc/title-atlas.json'
SLOTS = (0, 1, 2, 3, 4, 5, 5, 5, 5, 3)
SIZES = {5: 22, 7: 34}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def decode(value):
    return zlib.decompress(base64.b64decode(value, validate=True))


def positions(rect):
    x, y, w, h = rect
    require(0 <= x < x + w <= 256 and 0 <= y < y + h <= 256, 'SP title rectangle bounds')
    return [yy * 256 + xx for yy in range(y, y + h) for xx in range(x, x + w)]


def apply_title_atlas(atlas: bytes, drawings: bytes, config=None):
    """Validate every preimage, then return paired same-size members and a receipt."""
    raw_config = CONFIG.read_bytes() if config is None else json.dumps(config, sort_keys=True).encode()
    config = json.loads(raw_config) if config is None else config
    require(len(atlas) == config['atlas_size'] and len(drawings) == config['drawings_size'],
            'SP title member size drift')
    out = bytearray(atlas)
    indices, image_ranges = {}, {}
    for page in config['pages']:
        n, a, b = page['index'], page['start'], page['end']
        require(n not in indices and 0 <= n < 10 and 0 <= a < b <= len(atlas), 'SP title page bounds')
        chunk = atlas[a:b]
        p = parse_tim2(chunk).pictures[0]
        require((p.width, p.height, p.image_type) == (256, 256, 4), 'SP title texture format drift')
        s, size = p.offset + p.header_size, p.image_size
        require((s, size) == (page['image_start'], page['image_size']), 'SP title image bounds drift')
        require(sha(chunk[:s] + chunk[s + size:]) == page['container_sha256'],
                'SP title header/CLUT/trailer drift')
        indices[n] = bytearray(v for byte in chunk[s:s + size] for v in (byte & 15, byte >> 4))
        image_ranges[n] = (a + s, a + s + size)
    for cell in config['reused_cells']:
        require(sha(bytes(indices[cell['page']][i] for i in positions(cell['rect']))) == cell['sha256'],
                f"SP reused title cell drift: {cell['id']}")
    reservations = {r['page']: decode(r['occupied_mask_zlib_base64']) for r in config['source_reservations']}
    owned = {p: set() for p in indices}
    for cell in config.get('retired_cells', []):
        n = cell['page']
        pos = positions(cell['rect'])
        mask = reservations[n]
        require(len(mask) == 65536 and not any(mask[i] for i in pos),
                'SP retired title overlaps protected source pixels/UV')
        require(not owned[n].intersection(pos), 'SP retired title cells overlap')
        owned[n].update(pos)
        require(cell['before_sha256'] == sha(bytes(len(pos))), 'SP retired title baseline is not empty')
        require(sha(bytes(indices[n][i] for i in pos)) in (cell['before_sha256'], cell['sha256']),
                f"SP retired title pixel preimage drift: {cell['id']}")
        for i in pos:
            indices[n][i] = 0
    cells = {}
    for cell in config['cells']:
        n, id = cell['page'], cell['id']
        require(id not in cells, 'SP title duplicate cell ID')
        pos = positions(cell['rect'])
        mask = reservations[n]
        require(len(mask) == 65536 and not any(mask[i] for i in pos), 'SP title overlaps protected source pixels/UV')
        require(not owned[n].intersection(pos), 'SP title cells overlap')
        owned[n].update(pos)
        pixels = decode(cell['indices_zlib_base64'])
        require(len(pixels) == len(pos) and max(pixels) <= 15 and sha(pixels) == cell['sha256'],
                'SP title frozen indices drift')
        require(sha(bytes(indices[n][i] for i in pos)) in (cell['before_sha256'], cell['sha256']),
                f'SP title pixel preimage drift: {id}')
        x, y, w, h = cell['rect']; u, v, right, bottom = cell['uv']
        require(x <= u < right <= x + w and y <= v < bottom <= y + h, 'SP title UV outside owned cell')
        for i, value in zip(pos, pixels):
            indices[n][i] = value
        cells[id] = (n, cell['uv'])
    cells.update({c['id']: (c['page'], [c['rect'][0], c['rect'][1],
                  c['rect'][0] + c['rect'][2], c['rect'][1] + c['rect'][3]]) for c in config['reused_cells']})
    draw_out = bytearray(drawings)
    claimed = set()
    for patch in config['patches']:
        offset, ty = patch['offset'], patch['type']
        before, after = bytes.fromhex(patch['before_hex']), bytes.fromhex(patch['after_hex'])
        require(ty in SIZES and len(before) == len(after) == SIZES[ty] and before[0] & 15 == ty,
                'SP title record type/size drift')
        require(0 <= offset <= len(drawings) - len(after), 'SP title record bounds')
        require(patch['chunk'] not in config['deferred_chunks'], 'SP deferred effect modification')
        pos = set(range(offset, offset + len(after)))
        require(not claimed.intersection(pos), 'SP title patch overlap')
        claimed.update(pos)
        require(before[:4] == after[:4] and before[4] & 0xf0 == after[4] & 0xf0
                and before[5:10] == after[5:10], 'SP title flags/material/colour changed')
        if patch['operation'] == 'restore':
            require(after == before, 'SP withdrawn title must restore exact baseline')
        elif patch['operation'] == 'collapse':
            require(after[10:-4] == bytes(len(after) - 14) and after[-4:] == before[-4:]
                    and before[:10] == after[:10], 'SP collapsed title record invalid')
        elif patch['operation'] == 'retarget':
            page, uv = cells[patch['token']]
            sample = patch.get('sample_uv', uv)
            require(len(sample) == 4 and uv[0] <= sample[0] < sample[2] <= uv[2]
                    and uv[1] <= sample[1] < sample[3] <= uv[3],
                    'SP title sample outside owned cell')
            require(after[4] & 15 == page and list(after[-4:]) == sample, 'SP title cell reference drift')
            clut = after[4] >> 4
            require(clut < len(SLOTS) and (clut == page or SLOTS[clut] != SLOTS[page]),
                    'SP title texture/CLUT VRAM slot collision')
        else:
            raise ValueError('SP title unknown operation')
        previous = [bytes.fromhex(value) for value in patch.get('previous_hex', [])]
        require(all(len(value) == len(before) and value[:4] == before[:4]
                    and value[4] & 0xf0 == before[4] & 0xf0 and value[5:10] == before[5:10]
                    for value in previous), 'SP title previous revision flags/material/colour drift')
        require(drawings[offset:offset + len(after)] in (before, after, *previous),
                f'SP title draw preimage drift at {offset:#x}')
        draw_out[offset:offset + len(after)] = after
    for record in config['number_protection']:
        a, b = record['start'], record['end']
        require(sha(drawings[a:b]) == record['sha256'] and draw_out[a:b] == drawings[a:b],
                'SP numeric drawing changed')
    n = config['number_texture_protection']
    require(sha(bytes(indices[n['page']][i] for i in positions(n['rect']))) == n['sha256'],
            'SP numeric texture changed')
    for n, idx in indices.items():
        a, b = image_ranges[n]
        out[a:b] = bytes(idx[i] | idx[i + 1] << 4 for i in range(0, len(idx), 2))
    return bytes(out), bytes(draw_out), dict(status='static_verified_runtime_pending',
        config_sha256=sha(raw_config),cells=len(config['cells']),
        drawing_records=sum(p['operation'] != 'restore' for p in config['patches']),
        restored_drawing_records=sum(p['operation'] == 'restore' for p in config['patches']),
        title_chunks=sorted({p['chunk'] for p in config['patches'] if p['operation'] != 'restore'}),
        restored_title_chunks=sorted({p['chunk'] for p in config['patches'] if p['operation'] == 'restore'}),
        numeric_pixels_records_and_code_preserved=True,shared_source_pixels_preserved=True,
        files={'KURODATA/KVMDATA.BIN':sha(out),'KURODATA/KVPDATA.BIN':sha(draw_out)})
