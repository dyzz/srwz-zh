"""Walk every trailing punctuation to its exact clip boundary on the Best candidate.

Usage (from srwz-zh): python3 docs/issue-assets/battle-line-breaks-20261109/boundary.py SCRATCH_DIR
For each tail: reference ink offset, then advance = limit, limit + 1 and 484, on SW and Metal 4x.
"""
import itertools
import json
import struct
import subprocess
import sys
from pathlib import Path

sys.path[:0] = ['tools', 'tools/special_disc/writeback']
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from migrate_slps_text import encoding_tables
from srwz.armsx2_runtime import Armsx2Session
from srwz.text import encode_text, two_byte_visible_spaces

S = Path(sys.argv[1]).resolve()
root = Path.cwd()
here = root / 'docs/issue-assets/battle-line-breaks-20261109'
base = root / 'work/runtime/armsx2/battle-punct-overflow-20261109'
out = base / 'boundary'
out.mkdir(parents=True, exist_ok=True)
iso = root / 'build/iso/test/integrated-best.iso'
card = root / 'work/runtime/armsx2/release-skip-20261108/best/save/Mcd001.ps2'
BUF, CAP = 0x5FE5B8, 96
enc, _, codes, _ = encoding_tables()

OFFSET = {'”': -8, '）': -8, '？': -6, '》': -6, '：': -7, '】': -7,
          '。': -9, '、': -10, '，': -12, '；': -12, '！': -13}
EXTRA = ['…', '—']
TAILS = list(OFFSET) + EXTRA
FILLERS = [''.join(p) for n in range(0, 4) for p in itertools.product('il1AWg0', repeat=n)]


def measure(texts):
    (S / 'b.in.json').write_text(json.dumps(texts, ensure_ascii=False))
    subprocess.check_call(['node', str(here / 'measure.mjs'), str(S / 'b.in.json'), str(S / 'b.out.json')])
    return json.loads((S / 'b.out.json').read_text())


def prefix(row):
    return '“' if row == 0 else '“短\n　'


def find_text(tail, row, targets):
    """Find a filler string for each wanted advance, measured by the shared engine."""
    pool = []
    for n in range(13, 23):
        for f in FILLERS:
            left = n // 2
            pool.append(prefix(row) + '国' * left + f + '国' * (n - left) + tail)
    found = {}
    for text, m in zip(pool, measure(pool)):
        if isinstance(m, dict) or len(m) != row + 1:
            continue
        adv = m[row]['adv']
        if adv in targets and adv not in found:
            found[adv] = (text, m)
    missing = [t for t in targets if t not in found]
    if missing:
        raise SystemExit(f'no filler for {tail!r} row {row}: {missing}')
    return found


cases = []
for tail in TAILS:
    ref_text = '“国国国国国' + tail
    ref = measure([ref_text])[0]
    cases.append(dict(tail=tail, row=0, kind='ref', adv=ref[0]['adv'], text=ref_text, meas=ref))
for tail in TAILS:
    limit = 480 - OFFSET.get(tail, 0)
    wanted = {'limit': limit, 'limit+1': limit + 1, '484': 484} if tail in OFFSET else {'484': 484}
    found = find_text(tail, 0, set(wanted.values()))
    for kind, adv in wanted.items():
        cases.append(dict(tail=tail, row=0, kind=kind, adv=adv, text=found[adv][0], meas=found[adv][1]))
for tail in ['”', '，']:
    limit = 480 - OFFSET[tail]
    found = find_text(tail, 1, {limit, limit + 1})
    for kind, adv in (('limit', limit), ('limit+1', limit + 1)):
        cases.append(dict(tail=tail, row=1, kind=kind, adv=adv, text=found[adv][0], meas=found[adv][1]))
print('cases', len(cases), flush=True)


def ink_right(img, blank, scale):
    h = img.shape[0]
    top = int(h * 380 / 448)
    d = np.abs(img[top:] - blank[top:]).sum(axis=2) > 24
    cols = np.where(d.any(axis=0))[0]
    return int(cols.max()) if len(cols) else None


def load_png(path):
    return np.asarray(Image.open(path).convert('RGB')).astype(int)


results, strips = [], []
for renderer, scale in (('sw', 1), ('metal', 4)):
    kw = {'renderer': 'metal', 'upscale': 4} if renderer == 'metal' else {}
    d = out / renderer
    d.mkdir(exist_ok=True)
    with Armsx2Session(iso, card, d, **kw) as vm:
        vm.run(5)

        def play(raw, name):
            vm.cmd('load ' + str(base / 'matrix/base.p2s'))
            vm.cmd(f'poke {BUF:x} ' + raw.ljust(CAP, b'\0').hex())
            vm.run(3)
            vm.cmd('trace 13ab50 name=g s0:20')
            vm.run(1)
            t = d / 'x.jsonl'
            vm.cmd(f'tracedump {t}')
            vm.cmd('untrace')
            recs = [struct.unpack('<hhhhHHhh', vm.read_ram(int(json.loads(l)['s0'], 16), 20)[:16])
                    for l in t.read_text().splitlines()]
            vm.shot(name)
            return recs

        play(b'\0', 'blank')
        blank = load_png(d / 'blank.png')
        width = blank.shape[1]
        ref_off = {}
        for i, c in enumerate(cases):
            raw = encode_text(two_byte_visible_spaces(c['text']), enc, overrides=codes, terminate=True)
            assert len(raw) <= CAP, (c['text'], len(raw))
            name = f'c{i:03d}'
            recs = play(raw, name)
            rows = {}
            for r in recs:
                if r[3] >= 78:
                    rows.setdefault((r[3] - 78) // 12, []).append(r)
            geometry = True
            for ri, row in enumerate(c['meas']):
                got = sorted((q[2] + 160, q[6], q[7], q[3] - 84 - 12 * ri) for q in rows.get(ri, []))
                exp = sorted((x, w, h, yo) for _, x, w, h, _, yo in row['g'])
                geometry &= got == exp
            img = load_png(d / f'{name}.png')
            right = ink_right(img, blank, scale)
            origin = (160 + c['adv']) * scale
            if c['kind'] == 'ref':
                ref_off[c['tail']] = right + 1 - origin
            off = ref_off[c['tail']]
            predicted = origin + off
            # Metal 4x lands about one native pixel right of the reference near the edge: judge it by the edge itself.
            complete = right < width - 1 if renderer == 'metal' else predicted <= width and right == predicted - 1
            rec = dict(renderer=renderer, tail=c['tail'], row=c['row'], kind=c['kind'], adv=c['adv'],
                       text=c['text'], offset=off / scale, ink_right=right, predicted_right=predicted - 1,
                       width=width, complete=complete, clipped_by=max(0, predicted - width), geometry=geometry)
            results.append(rec)
            if renderer == 'metal' and c['kind'] == '484':
                strips.append((c['tail'], complete, Image.open(d / f'{name}.png').convert('RGB').crop(
                    (width - 800, int(img.shape[0] * 380 / 448), width, img.shape[0]))))
            print(renderer, c['tail'], c['row'], c['kind'], c['adv'], 'off', off / scale, 'right', right,
                  'pred', predicted - 1, 'complete' if complete else 'clipped', 'geom', geometry, flush=True)

(here / 'boundary.json').write_text(json.dumps(results, ensure_ascii=False, indent=0))
font = ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc', 30)
w, h = strips[0][2].size
sheet = Image.new('RGB', (w, (h + 44) * len(strips)), (18, 18, 22))
draw = ImageDraw.Draw(sheet)
for i, (tail, ok, crop) in enumerate(strips):
    y = i * (h + 44)
    draw.text((10, y + 4), f'tail {tail}  advance 484 (+22), right edge = screen edge  {"complete" if ok else "CLIPPED"}',
              fill=(235, 235, 235), font=font)
    sheet.paste(crop, (0, y + 44))
sheet.save(here / 'boundary-484-sheet.png')
print('done', sheet.size)
