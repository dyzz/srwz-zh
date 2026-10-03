"""Restore native menu words after moving their Chinese consumers to frozen blank cells."""
import base64
import hashlib
import json
import zlib
from pathlib import Path

from .tim2 import parse_tim2

CONFIG = 'config/assets/ui-menu-native-restore.json'
SLOTS = (0, 1, 2, 3, 4, 5, 5, 5, 5, 3)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def decode(raw):
    return zlib.decompress(base64.b64decode(raw, validate=True))


def positions(rect):
    x, y, w, h = rect
    require(0 <= x < x+w <= 255 and 0 <= y < y+h <= 255, 'menu cell bounds')
    return [yy*256+xx for yy in range(y, y+h) for xx in range(x, x+w)]


def pages(atlas, config):
    indices, ranges = {}, {}
    for page in config['pages']:
        a, b, n = page['start'], page['end'], page['index']
        require(n not in indices and 0 <= a < b <= len(atlas), 'menu page bounds')
        p = parse_tim2(atlas[a:b]).pictures[0]
        s, size = p.offset+p.header_size, p.image_size
        require((p.width, p.height, p.image_type, s, size) == (256, 256, 4, 64, 32768),
                'menu texture format drift')
        require(sha(atlas[a:a+s]+atlas[a+s+size:b]) == page['container_sha256'],
                'menu header/CLUT/trailer drift')
        indices[n] = bytearray(v for byte in atlas[a+s:a+s+size] for v in (byte&15, byte>>4))
        ranges[n] = (a+s, a+s+size)
    return indices, ranges


def load(root, edition):
    raw = (root/CONFIG).read_bytes()
    c = json.loads(raw)['profiles'][edition]
    return c, dict(config_sha256=sha(raw), profile=edition,
                   restored_chunks=c['restored_chunks'], moved_cells=len(c['cells'])-1,
                   runtime='pending')


def apply_menu_restore(atlas, drawings, root: Path, edition='original', config=None):
    c, report = load(root, edition) if config is None else (config, {})
    require(len(atlas) == c['atlas_size'] and len(drawings) == c['drawings_size'], 'menu member size drift')
    require(sha(atlas) in (c['before']['atlas'], c['after']['atlas']) and
            sha(drawings) in (c['before']['drawings'], c['after']['drawings']), 'menu input identity drift')
    indices, ranges = pages(atlas, c)
    occupied = {p['index']: decode(p['protected_uv_zlib_base64']) for p in c['pages']}
    owned = {n:set() for n in indices}
    for cell in c['cells']:
        n, pos = cell['page'], positions(cell['rect'])
        require(not owned[n].intersection(pos), 'menu cells overlap')
        owned[n].update(pos)
        pixels = decode(cell['indices_zlib_base64'])
        require(len(pixels) == len(pos) and max(pixels) <= 15 and sha(pixels) == cell['sha256'],
                'menu frozen pixels drift')
        if cell['kind'] == 'relocate':
            mask = occupied[n]
            require(len(mask) == 65536 and not any(mask[i] for i in pos), 'menu cell overlaps native/current UV')
            require(cell['before_sha256'] == sha(bytes(len(pos))), 'menu relocation is not blank')
            require(any(1 <= v <= 7 for v in pixels) and any(8 <= v <= 15 for v in pixels),
                    'menu indexed fill/outline layer missing')
        else:
            require(cell['kind'] == 'native_restore' and cell['source_indices_sha256'] == cell['sha256'],
                    'menu native source identity drift')
        require(sha(bytes(indices[n][i] for i in pos)) in (cell['before_sha256'], cell['sha256']),
                'menu pixel preimage drift')
        for i, value in zip(pos, pixels):
            indices[n][i] = value
    out = bytearray(atlas)
    for n, idx in indices.items():
        a, b = ranges[n]
        out[a:b] = bytes(idx[i] | idx[i+1]<<4 for i in range(0, len(idx), 2))
    draw = bytearray(drawings); claimed = set()
    for patch in c['patches']:
        off = patch['offset']; before, after = bytes.fromhex(patch['before_hex']), bytes.fromhex(patch['after_hex'])
        require(len(before) == len(after) in (16, 22, 34, 50) and 0 <= off <= len(draw)-len(after),
                'menu draw bounds/type drift')
        span = set(range(off, off+len(after)))
        require(not claimed.intersection(span), 'menu draw ownership overlap'); claimed.update(span)
        require(drawings[off:off+len(after)] in (before, after), 'menu draw preimage drift')
        if len(before) == 16:
            require(before[:8] == after[:8], 'menu separator header changed')
        else:
            require(before[:4] == after[:4] and before[5:10] == after[5:10]
                    and before[4]&0xf0 == after[4]&0xf0, 'menu flags/material/colour changed')
        if patch['operation'] == 'relocate':
            expected = bytearray(before); expected[4] = after[4]; expected[-4:] = after[-4:]
            require(after == expected, 'menu relocated geometry changed')
            texture, clut = after[4]&15, after[4]>>4
            require(texture < 10 and clut < 10 and
                    (texture == clut or SLOTS[texture] != SLOTS[clut]), 'menu texture/CLUT slot collision')
        else:
            require(patch['operation'] == 'native_restore' and patch['native_hex'] == patch['after_hex'],
                    'menu native drawing drift')
        draw[off:off+len(after)] = after
    result = bytes(out), bytes(draw)
    require(sha(result[0]) == c['after']['atlas'] and sha(result[1]) == c['after']['drawings'],
            'menu output identity drift')
    return *result, report


def verify_menu_restore(atlas, drawings, root: Path, edition='original'):
    c, report = load(root, edition)
    require(sha(atlas) == c['after']['atlas'] and sha(drawings) == c['after']['drawings'],
            'menu final member identity drift')
    indices, _ = pages(atlas, c)
    for cell in c['cells']:
        require(sha(bytes(indices[cell['page']][i] for i in positions(cell['rect']))) == cell['sha256'],
                'menu final frozen pixels drift')
    for patch in c['patches']:
        expected = bytes.fromhex(patch['after_hex'])
        require(drawings[patch['offset']:patch['offset']+len(expected)] == expected, 'menu final drawing drift')
    return report
