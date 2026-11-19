#!/usr/bin/env python3
"""Author the Traditional SP menu atlas: the text cells SP's own image chain writes into KVMDATA, in Traditional.

SP's image chain (write_image_labels.py: settlement labels, command headings, title atlas, bazaar heading, menu
restore with its clarity cells and help titles, battle SELECT tiles, atlas overlap) seals every step with hashes of
the atlas it receives, down to whole-member identities. The Traditional build keeps that chain exactly as the
Simplified one (same configs, same seals) and adds one last step: a frozen xor delta from the chain's Simplified
result to the Traditional one (config/assets/special-disc/menu-atlas-zh-hant.json, present only in the Traditional
clone). The verifier takes the delta off first and re-reads the Simplified chain as before.

Where the Traditional pixels come from:
  * cells SP copied from the Original's Simplified atlas (clarity cells, help-title halves, the intermission title
    face): found there as exact crops; the Traditional Original's pixels at the same place;
  * clarity cells SP placed elsewhere (key, help): the Original's reviewed Traditional cells
    (config/zh-hant/hand-drawn/original.json), checked against the Simplified cell they replace;
  * SP's own cells: the DATA HELP item word (fitted to the Simplified word, re-rendered) and the two settlement
    labels (write_image_labels' renderer with the Traditional corpus text);
  * the Original's own Simplified -> Traditional atlas delta that SP's baseline inherits (sp_textures.py, held out of
    the baseline because the chain seals the whole atlas it receives), wherever the chain left those pixels.

The battle SELECT tiles are the exception: the final-ISO typography check reads them from the atlas, so their
Traditional versions replace the tiles in the clone's own contract (battle_select below) and the chain installs them.

Usage: sp_menu_atlas.py CLONE --simplified SC_ORIGINAL_COMPONENTS --traditional TC_ORIGINAL_COMPONENTS [--review DIR]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CONFIG = 'config/assets/special-disc/menu-atlas-zh-hant.json'
HELD_KVM = 'build/zh-hant-sp/kvmdata-traditional-delta.bin'      # sp_textures.py --hold (sp_tc_baseline.py)
KVM, KVP = 'KURODATA/KVMDATA.BIN', 'KURODATA/KVPDATA.BIN'
PAGE, IMAGE = 33344, 64
BATTLE_STYLE = dict(width=108, height=36, point_size=18, stroke_gray='#404040', stroke_width=0.45,
                    character_spacing=1, supersample_factor=4)       # paint_hand_drawn.py battle SELECT line
HALVES = {'戰': ((12, 13), 54), '艦': ((14, 15), 73)}               # SP tile indexes, line start of the glyph
LABELS = (('sd/image/kvmdata/结算提示图集/0', (144, 24, 255, 47)), ('sd/image/kvmdata/结算提示图集/1', (0, 72, 71, 95)))

sha = lambda b: hashlib.sha256(b).hexdigest()
unz = lambda t: zlib.decompress(base64.b64decode(t))
z = lambda b: base64.b64encode(zlib.compress(b, 9)).decode('ascii')


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def pixels(atlas: bytes, n: int) -> bytearray:
    o = n * PAGE + IMAGE
    return bytearray(v for b in atlas[o:o + 32768] for v in (b & 15, b >> 4))


def crop(px, rect, stride=256) -> bytes:
    x, y, w, h = rect
    return b''.join(bytes(px[(y + j) * stride + x:(y + j) * stride + x + w]) for j in range(h))


def paste(px, rect, tile: bytes, stride=256) -> None:
    x, y, w, h = rect
    for j in range(h):
        px[(y + j) * stride + x:(y + j) * stride + x + w] = tile[j * w:(j + 1) * w]


def find(pages, tile: bytes, w: int, h: int) -> list[tuple[int, int, int]]:
    """Every (page, x, y) where the Original atlas holds exactly this tile."""
    found, first = [], tile[:w]
    for n, px in enumerate(pages):
        for y in range(257 - h):
            row = bytes(px[y * 256:(y + 1) * 256])
            x = row.find(first)
            while 0 <= x <= 256 - w:
                if crop(px, (x, y, w, h)) == tile:
                    found.append((n, x, y))
                x = row.find(first, x + 1)
    return found

SELECT_CONFIG = 'config/assets/special-disc/battle-select-titles-zh.json'


def battle_select(c: Path, og_sc: bytes, sc_pages, tc_pages, notes) -> None:
    """Battle SELECT tiles: the final-ISO typography check reads them from the atlas, so the Traditional ones go into
    the clone's own contract (and the chain installs them) instead of the final delta. Glyphs SP copied from the
    Original's battle SELECT page take the Traditional Original's tile at the same place; 戰 / 艦, which SP builds from
    halves, are drawn in the line style of the others and split at the Simplified halves' widths."""
    from kvm_text import FONT, _exe
    from srwz.imagemagick import render_grayscale_text_mask
    from locks import refresh_locks
    doc = load(ROOT / SELECT_CONFIG)                                     # the Simplified contract
    halves = {k for pair, _ in HALVES.values() for k in pair}
    tiles = {}
    for i, cell in enumerate(doc['cells']):
        if i in halves:
            continue
        w, h = cell['rect'][2:]
        tile = unz(cell['indices_zlib_base64'])
        hits = find(sc_pages, tile, w, h)
        traditional = {crop(tc_pages[m], (x, y, w, h)) for m, x, y in hits}
        if len(traditional) > 1:
            raise SystemExit(f'battle SELECT {i}: Original copies differ in Traditional')
        if traditional:
            tiles[i] = traditional.pop()
            notes.append((f'battle-select/{i}', 'Original crop' if tiles[i] != tile else 'same in Traditional', hits[0]))
        elif i == len(doc['cells']) - 1 and w == 48:
            notes.append((f'battle-select/{i}', 'Latin (SHIP)', None))     # SP's native SHIP restored
        else:
            raise SystemExit(f'battle SELECT {i}: no Traditional source')
    palette = struct.unpack_from('<16H', og_sc, 2 * PAGE + IMAGE + 32768)
    gray = [(v & 31) * 255 / 31 for v in palette]
    lut = bytes(min(range(16), key=lambda i: abs(gray[i] - v)) for v in range(256))
    line = render_grayscale_text_mask(_exe(), FONT, '選擇戰艦', **BATTLE_STYLE).translate(lut)
    for ch, ((left, right), start) in HALVES.items():
        lc, rc = doc['cells'][left], doc['cells'][right]
        lw, rw, h = lc['rect'][2], rc['rect'][2], lc['rect'][3]
        glyph = crop(line, (start, 8, 19, h), stride=108)
        cols = [i for i in range(19) if any(glyph[j * 19 + i] for j in range(h))]
        g0, g1 = cols[0], cols[-1] + 1
        total = lw + rw
        if g1 - g0 > total:
            raise SystemExit(f'{ch}: {g1 - g0} px does not fit {total}')
        pad = (total - (g1 - g0)) // 2
        full = bytes(glyph[j * 19 + g0 + i - pad] if 0 <= i - pad < g1 - g0 else 0
                     for j in range(h) for i in range(total))
        tiles[left], tiles[right] = crop(full, (0, 0, lw, h), stride=total), crop(full, (lw, 0, rw, h), stride=total)
        notes.append((f'battle-select/{left}+{right}', 'rendered', ch))
    for i, tile in tiles.items():
        doc['cells'][i].update(sha256=sha(tile), indices_zlib_base64=z(tile))
    doc['labels'] = ['選擇陣型', '排列隊員', '選擇機體', '選擇機師', '選擇戰艦']
    doc['scope'] += ' (Traditional build: tools/zh_hant/sp_menu_atlas.py)'
    (c / SELECT_CONFIG).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('battle SELECT tiles in Traditional; locks refreshed:', refresh_locks(c, [SELECT_CONFIG]), flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('clone', type=Path)
    p.add_argument('--simplified', type=Path, required=True)
    p.add_argument('--traditional', type=Path, required=True)
    p.add_argument('--review', type=Path)
    a = p.parse_args()
    c = a.clone.resolve()
    (c / CONFIG).unlink(missing_ok=True)
    sys.path[:0] = [str(c / 'tools'), str(c / 'tools/special_disc/writeback'), str(HERE)]
    og_sc, og_tc = (a.simplified / KVM).read_bytes(), (a.traditional / KVM).read_bytes()
    sc_pages = [pixels(og_sc, n) for n in range(10)]
    tc_pages = [pixels(og_tc, n) for n in range(10)]
    notes = []
    battle_select(c, og_sc, sc_pages, tc_pages, notes)
    chain = c / 'build/zh-hant-sp/menu-atlas-simplified'
    r = subprocess.run([sys.executable, 'tools/special_disc/writeback/write_image_labels.py', '--output', str(chain)],
                       cwd=c, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('write_image_labels failed:\n' + (r.stdout + r.stderr)[-3000:])
    simplified = (chain / KVM).read_bytes()
    pages = {n: pixels(simplified, n) for n in range(10)}
    out = {n: bytearray(px) for n, px in pages.items()}
    cells = []

    def put(name, n, rect, tile, text=None):
        before = crop(out[n], rect)
        if tile != before:
            paste(out[n], rect, tile)
            cells.append(dict(name=name, page=n, rect=list(rect), **({'text': text} if text else {}),
                              before=z(before), after=z(tile)))

    # 1. cells copied from the Original's Simplified atlas
    assets = c / 'config/assets'
    targets = []
    for cell in load(assets / 'ui-text-clarity.json')['profiles']['sp']['cells']:
        targets.append((f"clarity/{cell['id']}", cell['page'], cell['rect']))
    help_cfg = load(assets / 'special-disc/item-help-title.json')
    targets += [(f'item-help/{i}', help_cfg['page'], rect) for i, rect in enumerate(help_cfg['cells'])]
    face = load(assets / 'special-disc/menu-atlas-overlap.json')['title_face']
    u0, v0, u1, v1 = face['uv']
    targets.append(('overlap/title-face', face['page'], [u0, v0, u1 - u0, v1 - v0]))
    hand = load(ROOT / 'config/zh-hant/hand-drawn/original.json')['entries']
    sc_clarity = {cell['id']: cell for cell in load(ROOT / 'config/assets/ui-text-clarity.json')['profiles']['original']['cells']}
    last = {}
    for name, n, rect in targets:
        tile = crop(pages[n], rect)
        if not any(tile):
            continue
        hits = find(sc_pages, tile, rect[2], rect[3])
        group = name.split('/')[0]
        if len({crop(tc_pages[m], (x, y, rect[2], rect[3])) for m, x, y in hits}) > 1:
            # the same Simplified cell in two Original titles drawn apart in Traditional (说明 of 按键说明 and of
            # 项目说明): the one beside the group's previous source (the same title)
            if group not in last:
                raise SystemExit(f'{name}: the Original holds this cell in titles that differ in Traditional')
            pm, px_, py = last[group]
            hits = sorted(hits, key=lambda h: (h[0] != pm, abs(h[2] - py), abs(h[1] - px_)))[:1]
        traditional = {crop(tc_pages[m], (x, y, rect[2], rect[3])) for m, x, y in hits} - {tile}
        if hits:
            last[group] = hits[0]
        if traditional:
            put(name, n, rect, traditional.pop()); notes.append((name, 'Original crop', hits[0]))
            continue
        if hits:
            notes.append((name, 'same in Traditional', hits[0]))
            continue
        # 2. clarity cells SP placed elsewhere: the Original's reviewed Traditional cell
        kind = name.split('/', 1)[1]
        if name.startswith('clarity/') and kind in sc_clarity and sha(tile) == sc_clarity[kind]['after_sha256']:
            art = hand[f'clarity/{kind}']
            put(name, n, rect, unz(art['indices_zlib_base64']), art['text']); notes.append((name, 'reviewed cell', art['text']))
            continue
        raise SystemExit(f'{name}: no Traditional source for this Simplified cell')

    # 3. SP's DATA HELP item word, split into four gutter slices
    from kvm_text import FONT, _exe, fit, render
    title_cfg = load(assets / 'special-disc/title-atlas.json')
    W, H = 46, 20
    word = bytearray(W * H)
    for cell in title_cfg['cells']:
        x, y, w, h = cell['rect']; u, v, _, _ = cell['uv']; sx, sy, sw, sh = cell['source_rect']
        frozen = unz(cell['indices_zlib_base64'])
        if crop(pages[cell['page']], cell['rect']) != frozen:
            raise SystemExit(f"title {cell['id']}: the chain output does not hold the frozen slice")
        for j in range(sh):
            word[(sy + j) * W + sx:(sy + j) * W + sx + sw] = frozen[(v - y + j) * w + u - x:(v - y + j) * w + u - x + sw]
    fits = {m: fit('项目', bytes(word), W, H, shears=(0, 8, 10, 12, 14, 16), mode=m) for m in ('roles', 'gray')}
    mode = max(fits, key=lambda m: fits[m][0])
    score, params = fits[mode]
    tc_word = render('項目', W, H, mode=mode, **params)
    notes.append(('title/item word', f'fit {score:.3f} ({mode})', params))
    for cell in title_cfg['cells']:
        x, y, w, h = cell['rect']; u, v, _, _ = cell['uv']; sx, sy, _, _ = cell['source_rect']
        tile = bytes(tc_word[(sy + j - (v - y)) * W + sx + i - (u - x)]
                     if 0 <= sx + i - (u - x) < W and 0 <= sy + j - (v - y) < H else 0
                     for j in range(h) for i in range(w))
        put(f"title/{cell['id']}", cell['page'], cell['rect'], tile, '項目')

    # 5. settlement labels (KVMDATA chunk 11): write_image_labels' renderer, Traditional corpus text
    import write_image_labels as wil
    from special_disc.baselines import baseline_iso
    from srwz.tim2 import parse_tim2
    writer = wil.Writer(baseline_iso('text-canary'), c / 'work/build/special-disc/text-candidate/font/proposal.json')
    base = writer.member(KVM)
    off = wil.sd.table_offsets(writer.exe, 0x39DF10, len(base))
    ca, cb = off[11:13]
    pic = parse_tim2(base[ca:cb]).pictures[0]
    start = ca + pic.offset + pic.header_size
    logical = bytes(v for b in base[start:start + pic.image_size] for v in (b & 15, b >> 4))
    font_lock = load(c / 'config/fonts/harmonyos-sans-sc-light.lock.json')['font']
    font = c / font_lock['path']
    texts = {}
    for corpus in ('corpus/zh/special-disc/frame-text.json', 'corpus/zh-hant/special-disc/frame-text.json'):
        rows = {l: e['translation'] for e in load(ROOT / corpus)['entries'] for l in e['locations']}
        texts[corpus] = [rows[t] for t, _ in LABELS]
    labelled = {}
    for corpus, words in texts.items():
        edited = logical
        for (target, box), text in zip(LABELS, words):
            edited, _ = wil.render(edited, 256, 256, box, text, font, 20)
        labelled[corpus] = edited
    current = bytes(v for b in simplified[start:start + pic.image_size] for v in (b & 15, b >> 4))
    if labelled['corpus/zh/special-disc/frame-text.json'] != current:
        raise SystemExit('settlement labels: the renderer does not reproduce the Simplified chunk')
    settle = bytearray(simplified)
    tc_labels = labelled['corpus/zh-hant/special-disc/frame-text.json']
    settle[start:start + pic.image_size] = bytes(tc_labels[i] | tc_labels[i + 1] << 4 for i in range(0, len(tc_labels), 2))
    notes.append(('settlement labels', texts['corpus/zh-hant/special-disc/frame-text.json'], None))

    # 6. the Original's own Simplified -> Traditional atlas delta (sp_textures.py, held out of the baseline because
    # the chain seals the whole atlas it receives): each changed region where the chain left the baseline's pixels
    held_path = c / HELD_KVM
    if held_path.exists():
        from sp_textures import mask_regions
        component = (c / 'work/build/special-disc/components/textures' / KVM).read_bytes()
        held = held_path.read_bytes()
        areas = [(n * PAGE + IMAGE, n * PAGE + IMAGE + 32768) for n in range(10)] + [(start, start + pic.image_size)]
        if len(held) != len(component) or any(not any(lo <= i < hi for lo, hi in areas)
                                               for i, (x, y) in enumerate(zip(component, held)) if x != y):
            raise SystemExit('held KVMDATA delta changes bytes outside the atlas pictures')
        surfaces = [(f'page {n}', pages[n], out[n], pixels(component, n), pixels(held, n)) for n in range(10)]
        unpack = lambda raw: bytearray(v for b in raw for v in (b & 15, b >> 4))
        settled = unpack(settle[start:start + pic.image_size])
        surfaces.append(('settlement chunk', unpack(simplified[start:start + pic.image_size]), settled,
                         unpack(component[start:start + pic.image_size]), unpack(held[start:start + pic.image_size])))
        kept = 0
        for label, chain_px, target, base_px, tc_px in surfaces:
            for x0, y0, x1, y1 in mask_regions({(i % 256, i // 256) for i in range(65536) if base_px[i] != tc_px[i]}, 256, 256):
                rect = (x0, y0, x1 - x0, y1 - y0)
                if crop(chain_px, rect) != crop(base_px, rect) or crop(target, rect) != crop(chain_px, rect):
                    kept += 1                                          # the chain (or a cell above) owns it
                    continue
                paste(target, rect, crop(tc_px, rect))
                if label != 'settlement chunk':
                    cells.append(dict(name=f'texture-delta/{label}', page=int(label.split()[1]), rect=list(rect),
                                      before=z(crop(base_px, rect)), after=z(crop(tc_px, rect))))
                notes.append((f'texture delta {label}', 'Original Traditional', rect))
        settle[start:start + pic.image_size] = bytes(settled[i] | settled[i + 1] << 4 for i in range(0, len(settled), 2))
        notes.append(('texture delta', f'{kept} regions left to the chain', None))

    # the Traditional atlas, as xor blocks over the chain's Simplified result
    result = bytearray(settle)
    for n, px in out.items():
        o = n * PAGE + IMAGE
        result[o:o + 32768] = bytes(px[i] | px[i + 1] << 4 for i in range(0, 65536, 2))
    runs, s = [], None
    for i, (x, y) in enumerate(zip(simplified, result)):
        if x != y and s is None:
            s = i
        elif x == y and s is not None:
            if runs and s - runs[-1][1] < 64:
                runs[-1] = (runs[-1][0], i)
            else:
                runs.append((s, i))
            s = None
    blocks = [dict(offset=lo, size=hi - lo, before_sha256=sha(simplified[lo:hi]), after_sha256=sha(bytes(result[lo:hi])),
                   xor_zlib_base64=z(bytes(x ^ y for x, y in zip(simplified[lo:hi], result[lo:hi]))))
              for lo, hi in runs]
    doc = dict(schema_version=1,
               scope='Traditional build only: Simplified SP image chain result -> Traditional text cells '
                     '(tools/zh_hant/sp_menu_atlas.py). Applied after the atlas overlap, removed first by the verifier.',
               simplified_atlas_sha256=sha(simplified), traditional_atlas_sha256=sha(bytes(result)),
               cells=[{k: v for k, v in cell.items() if k not in ('before', 'after')} for cell in cells],
               atlas=blocks, drawings=[])
    (c / CONFIG).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for name, how, where in notes:
        print(f'{name}: {how}' + (f' {where}' if where else ''))
    print(f'Traditional SP menu atlas: {len(cells)} cells, {len(blocks)} blocks, settlement labels', flush=True)
    if a.review:
        from PIL import Image
        a.review.mkdir(parents=True, exist_ok=True)
        rows = [(cell['name'], unz(cell['before']), unz(cell['after']), cell['rect'][2], cell['rect'][3]) for cell in cells]
        rows.append(('settlement', current, bytes(v for b in settle[start:start + pic.image_size] for v in (b & 15, b >> 4)), 256, 256))
        width = max(2 * w + 12 for _, _, _, w, _ in rows) * 3
        sheet = Image.new('L', (width, sum(h * 3 + 6 for *_, h in rows)), 60)
        y = 0
        for name, before, after, w, h in rows:
            for k, data in enumerate((before, after)):
                im = Image.frombytes('L', (w, h), bytes(v * 17 for v in data)).resize((w * 3, h * 3), Image.NEAREST)
                sheet.paste(im, (k * (w * 3 + 12), y))
            y += h * 3 + 6
        sheet.save(a.review / 'menu-atlas.png')


if __name__ == '__main__':
    main()
