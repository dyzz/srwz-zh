"""Add the approved standalone 指令 title to SP's four standalone COMMAND titles.

SP's atlas has no blank cell left, so the title goes into the top-left of page 6:
the Japanese インター prefix there lost its only consumer when the setup title
moved to the complete Chinese text. The face is the main game's approved 38x18
tile, stored upright. The soft black border is rebuilt from that face exactly as
in the main game, stored 27 px wide instead of 35 so both fit beside the shared
minus sign; the on-screen quad is unchanged.

Usage: author.py ATLAS DRAWINGS NATIVE_DRAWINGS   (members of an SP image whose page 6 holds the
menu-atlas-overlap output from before this title). Rewrites config/assets/special-disc/menu-atlas-overlap.json.
"""
import base64, hashlib, json, struct, sys, zlib
from pathlib import Path

import numpy as np
from PIL import Image

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / 'tools'))
from srwz.ui_menu_restore import decode

sha = lambda b: hashlib.sha256(bytes(b)).hexdigest()
pack = lambda b: base64.b64encode(zlib.compress(bytes(b), 9)).decode()
atlas, drawings, native_drawings = (Path(p).read_bytes() for p in sys.argv[1:4])
path = root / 'config/assets/special-disc/menu-atlas-overlap.json'
config = json.loads(path.read_bytes())
main = json.loads((root / 'config/assets/ui-command-title-zh.json').read_bytes())
PAGE, DEAD = 6, (0, 0, 67, 31)   # x, y, w, h no current drawing samples
# neutral (data management popup), silver (sortie setup), gold (unit menu), yellow (map menu)
CHUNKS = {162: 24032, 163: 24144, 167: 24912, 168: 25024}
# The native word is anchored to the left of its window. The short Chinese title is
# moved to the measured window centre instead (screen px, ARMSX2 captures of the
# sortie, unit and map menus). The data management popup keeps the main game's place.
CENTRE_SHIFT = {162: 0, 163: 34, 167: 4, 168: 28}

block = config['atlas'][0]
start, size = block['offset'], block['size']
assert start == PAGE * 33344 + 64 and size == 32 * 128
current = atlas[start:start + size]
assert sha(current) == block['after_sha256'], 'page 6 is not the pre-title overlap output (already authored?)'
before = bytes(a ^ b for a, b in zip(current, decode(block['xor_zlib_base64'])))
assert sha(before) == block['before_sha256']

rows = np.array([v for byte in current for v in (byte & 15, byte >> 4)], dtype=np.uint8).reshape(32, 256)
x0, y0, w0, h0 = DEAD
rows[y0:y0 + h0, x0:x0 + w0] = 0

face_cell, border_cell = main['cells']
assert (face_cell['role'], border_cell['role']) == ('face', 'border')
tile = np.frombuffer(decode(face_cell['indices_zlib_base64']), dtype=np.uint8).reshape(38, 18)
line = np.rot90(tile)                                # upright 38x18 face
h, w = line.shape
clut = 4 * 33344 + 64 + 32768
gray = [(v & 31) * 255 / 31 for v in struct.unpack_from('<16H', atlas, clut)]
palette = [min(range(16), key=lambda i: abs(gray[i] - v)) for v in range(256)]

def border(width):
    radius = 3
    coverage = np.array([round(gray[v]) for v in line.flat], dtype=np.uint8).reshape(h, w)
    coverage[coverage < 32] = 0
    expanded = np.zeros((h + 2 * radius, w + 2 * radius), dtype=np.uint8)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                dst = expanded[radius + dy:radius + dy + h, radius + dx:radius + dx + w]
                np.maximum(dst, coverage, out=dst)
    compact = np.array(Image.fromarray(expanded).resize((width, 19), Image.Resampling.BOX))
    compact[compact < 44] = 0
    return np.array([palette[v] for v in compact.flat], dtype=np.uint8).reshape(compact.shape)

# The same recipe must reproduce the main game's stored border before it is reused.
assert sha(border(35).tobytes()) == border_cell['sha256'], 'border recipe drift'
cells = {'face': (1, 1, line), 'border': (40, 1, border(27))}
for x, y, pixels in cells.values():
    ph, pw = pixels.shape
    assert x0 <= x and x + pw <= x0 + w0 and y0 <= y and y + ph <= y0 + h0
    assert not rows[y:y + ph, x:x + pw].any()
    rows[y:y + ph, x:x + pw] = pixels
flat = rows.reshape(-1)
after = bytes(int(a) | int(b) << 4 for a, b in zip(flat[::2], flat[1::2]))
block.update(after_sha256=sha(after), xor_zlib_base64=pack(a ^ b for a, b in zip(before, after)))

approved = bytes.fromhex(main['drawing']['after_hex'])
entries = []
for chunk, offset in CHUNKS.items():
    native = native_drawings[offset:offset + 68]
    record = bytearray(native)
    for i, role in enumerate(('border', 'face')):
        at = i * 34
        x, y, pixels = cells[role]
        ph, pw = pixels.shape
        # Keep each SP title's own tint and opacity; take the approved quad, moved to
        # the native title origin (the wider menus sit 6 px further right), then centred.
        assert native[at:at + 4] == approved[at:at + 4] and native[at + 4] == 0x44 and native[at + 9] == approved[at + 9]
        record[at + 4] = 0x40 | PAGE                  # page 6 texels, page 4 heading ramp
        g = list(struct.unpack_from('<10h', approved, at + 10))
        if role == 'face':                           # undo the main game's rotated winding
            g = g[:2] + g[-2:] + g[2:-2]
        dx = struct.unpack_from('<h', native, at + 10)[0] - (52 if role == 'border' else 50) + CENTRE_SHIFT[chunk]
        g[0::2] = [v + dx for v in g[0::2]]
        struct.pack_into('<10h', record, at + 10, *g)
        record[at + 30:at + 34] = bytes((x, y, x + pw, y + ph))
    assert drawings[offset:offset + 68] in (native, bytes(record)), f'chunk {chunk} is neither native nor authored'
    entries.append(dict(offset=offset, size=68, before_sha256=sha(native), after_sha256=sha(record),
                        xor_zlib_base64=pack(a ^ b for a, b in zip(native, record))))
    print(chunk, record.hex())
owned = {e['offset'] for e in entries}
config['drawings'] = sorted([d for d in config['drawings'] if d['offset'] not in owned] + entries,
                            key=lambda d: d['offset'])
config['scope'] = ('SP numeric minus restoration; standalone gold challenge setup title; '
                   'standalone COMMAND → 指令 in chunks 162, 163, 167 and 168')
config['command_title'] = dict(
    page=PAGE, chunks=CHUNKS, centre_shift=CENTRE_SHIFT, reclaimed_rect=list(DEAD),
    face=dict(uv=[1, 1, 1 + w, 1 + h], sha256=sha(line.tobytes()), source='config/assets/ui-command-title-zh.json'),
    border=dict(uv=[40, 1, 67, 20], sha256=sha(cells['border'][2].tobytes()), stored_width=27, main_stored_width=35))
path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
print('atlas', block['after_sha256'])
