#!/usr/bin/env python3
"""Paint the five Original texture groups. Run explicitly when editing their artwork."""
from __future__ import annotations

import argparse
import base64
import hashlib
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw

from author_textures import Author, HAND_DRAWN, HELP_TITLES, ROOT, SELECT_HEADING_BANDS, dump, load_json
from assemble_dual import Disc
from kvm_text import FONT, _exe, render
from srwz.imagemagick import render_grayscale_text_mask

ASSETS = ROOT / 'config/assets'
OUTPUT = ROOT / 'build/zh-hant/hand-drawn-review'


def thaw(doc, field):
    return zlib.decompress(base64.b64decode(doc[field]))


def crop(plane, stride, rect):
    x, y, w, h = rect
    return b''.join(plane[r * stride + x:r * stride + x + w] for r in range(y, y + h))


def atlas_tile(atlas, page, rect):
    start = page * 33344 + 64
    return crop(bytes(i for b in atlas[start:start + 32768] for i in (b & 15, b >> 4)), 256, rect)


def help_title(text, w, h, stroke, bold, fill_threshold):
    # Use independent coverage masks for CLUT 3, then center the visible bounds.
    stride = w + 12
    style = dict(width=stride, height=h + 12, point_size=17, character_spacing=1.4,
                 supersample_factor=4, stroke_gray='white', fill_stroke_width=bold)
    fill = render_grayscale_text_mask(_exe(), FONT, text, stroke_width=0, **style)
    outline = render_grayscale_text_mask(_exe(), FONT, text, stroke_width=stroke, **style)
    indices = bytes(8 + round(7 * f / 255) if f >= fill_threshold else round(7 * o / 255) if o >= 45 else 0
                    for f, o in zip(fill, outline))
    ink = Image.frombytes('L', (stride, h + 12), indices)
    glyph = ink.crop(ink.getbbox())
    if glyph.width > w - 2 or glyph.height > h - 1:
        raise ValueError(f'{text}: {glyph.size} does not leave a border in {(w, h)}')
    cell = Image.new('L', (w, h))
    cell.paste(glyph, ((w - glyph.width) // 2, (h - glyph.height) // 2))
    return cell.tobytes()


def contact_sheet(group, rows):
    scale = 4
    stride = max(132, max(w for w, _, *_ in rows) * scale + 24)
    sheet = Image.new('RGB', (stride * 3, 30 + sum(h * scale + 12 for _, h, *_ in rows)), '#20242a')
    label = ImageDraw.Draw(sheet)
    for i, name in enumerate(('Simplified', 'Previous Traditional', 'New Traditional')):
        label.text((stride * i + 12, 8), name, fill='white')
    y = 28
    for w, h, *panels in rows:
        for i, pixels in enumerate(panels):
            panel = Image.frombytes('L', (w, h), bytes(v * 17 for v in pixels))
            sheet.paste(panel.resize((w * scale, h * scale), Image.Resampling.NEAREST), (stride * i + 12, y))
        y += h * scale + 12
    sheet.save(OUTPUT / f'{group}.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clone', type=Path, default=ROOT / 'build/zh-hant/project-tc')
    parser.add_argument('--compare', action='store_true', help='write review sheets from the captured baseline')
    args = parser.parse_args()
    author = Author(args.clone)
    baseline = ROOT / 'build/iso/test/zh-hant-dual-before-hand-drawn.iso'
    sc_atlas = Disc(ROOT / 'rom/original.iso').read('KURODATA/KVMDATA.BIN')
    tc_atlas = None
    if args.compare:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        previous = OUTPUT / 'previous-overlay/config/assets'
        previous_sections = load_json(OUTPUT / 'previous-sections.json')
        receipt = load_json(baseline.with_suffix('.receipt.json'))
        atlas_member = receipt['copied_members']['KURODATA/KVMDATA.BIN']
        with baseline.open('rb') as stream:
            stream.seek(atlas_member['tc_lba'] * 2048)
            tc_atlas = stream.read(atlas_member['tc_bytes'])
        sc_atlas = Disc(ROOT / 'build/iso/test/zh-hant-sc-before-hand-drawn.iso').read('KURODATA/KVMDATA.BIN')
    palette = struct.unpack_from('<16H', sc_atlas, 2 * 33344 + 64 + 32768)
    gray = [(v & 31) * 255 / 31 for v in palette]
    index_lut = bytes(min(range(16), key=lambda index: abs(gray[index] - v)) for v in range(256))
    rounded_gray = [round(value) for value in gray]
    clarity_lut = bytes(min(range(16), key=lambda index: abs(rounded_gray[index] - v)) for v in range(256))

    def prior_asset(rel):
        return load_json(previous / rel) if args.compare else None

    entries = {}
    sheets = {}

    def paint(group, key, text, w, h, old_sc, old_tc, source, params, pixels):
        ident = f'{group}/{key}'
        entries[ident] = dict(text=text, size=[w, h], source=source, parameters=params,
                              sha256=hashlib.sha256(pixels).hexdigest(),
                              indices_zlib_base64=base64.b64encode(zlib.compress(pixels, 9)).decode('ascii'))
        if args.compare:
            sheets.setdefault(group, []).append((w, h, old_sc, old_tc, pixels))

    sc = load_json(ASSETS / 'title-menu-zh.json')
    tc = prior_asset('title-menu-zh.json')
    for i, (label, sc_mask) in enumerate(zip(sc['labels'], sc['masks'])):
        text = author.text(label['translation'])
        params = dict(point_size=(21, 21, 20, 21)[i], stroke_gray=255, stroke_width=(1.25, 1.25, 0.9, 1.25)[i],
                      fill_stroke_width=0.5, dy=(2, 2, 3, 3)[i], spacing=(1, 0, 2, 1)[i], mode='gray')
        paint('title-menu', label['source'], text, 128, 32,
              bytes(v // 17 for v in thaw(sc_mask, 'zlib_base64')),
              bytes(v // 17 for v in thaw(tc['masks'][i], 'zlib_base64')) if tc else None,
              'Fallback tuned against frozen Original title-menu masks', params, render(text, 128, 32, **params))

    sc = load_json(ASSETS / 'ui-text-clarity.json')['profiles']['original']['cells']
    tc = prior_asset('ui-text-clarity.json')
    specs = {c['id']: c for c in load_json(ASSETS / 'ui-headings-zh.json')['cells']}
    for i, cell in enumerate(sc):
        key = cell['id']
        spec = specs[key]
        text = author.text(spec['text'])
        w, h = cell['rect'][2:]
        original = thaw(cell, 'after_zlib_base64')
        params = dict(point_size=spec['render']['point_size'], stroke_gray='#505050',
                      stroke_width=0.65, supersample_factor=4)
        pixels = original if text == spec['text'] else render_grayscale_text_mask(
            _exe(), FONT, text, width=w, height=h, **params).translate(clarity_lut)
        previous_tile = thaw(tc['profiles']['original']['cells'][i], 'after_zlib_base64') if tc else None
        paint('clarity', key, text, w, h, original, previous_tile,
              'Codex 2026-11-08 render_cells.py: 4x box filter and nearest stock CLUT entry', params, pixels)

    for sc_text, rect in HELP_TITLES.items():
        text = author.text(sc_text)
        w, h = rect[2:]
        params = dict(stroke=1.35, bold=0.65, fill_threshold=110)
        paint('help', sc_text, text, w, h, atlas_tile(sc_atlas, 3, rect), atlas_tile(tc_atlas, 3, rect) if tc_atlas else None,
              'Recovered 2026-11-09 build_review.py: wide canvas, separate outline and fill indices, center occupied bounds',
              dict(point_size=17, spacing=1.4, outline_threshold=45, **params), help_title(text, w, h, **params))

    sc = load_json(ASSETS / 'ui-battle-select-titles-zh.json')
    tc = prior_asset('ui-battle-select-titles-zh.json')
    tiles = {}
    battle_style = dict(width=108, height=36, point_size=18, stroke_gray='#404040',
                        stroke_width=0.45, character_spacing=1, supersample_factor=4)
    for title in sc['labels']:
        traditional = author.text(title)
        line = render_grayscale_text_mask(_exe(), FONT, traditional, **battle_style)
        for ch, start in zip(title, (16, 35, 54, 73)):
            tiles[ch] = crop(line, 108, (start, 8, 19, 18))

    for i, (ch, cell) in enumerate(zip('排选择阵型队员机体列师', sc['cells'])):
        text = author.text(ch)
        if text == ch:
            continue
        w, h = cell['rect'][2:]
        glyph = Image.frombytes('L', (19, h), tiles[ch])
        bounds = glyph.point(lambda v: index_lut[v]).getbbox()
        glyph = glyph.crop((bounds[0], 0, bounds[2], h))
        tile = Image.new('L', (w, h))
        painted_width = min(w, glyph.width)
        if painted_width < glyph.width:
            glyph = glyph.resize((painted_width, h), Image.Resampling.BOX)
        tile.paste(glyph, ((w - painted_width) // 2, 0))
        paint('battle-select', ch, text, w, h, thaw(cell, 'indices_zlib_base64'),
              thaw(tc['cells'][i], 'indices_zlib_base64') if tc else None,
              'Codex 2026-11-09 build_aligned_titles.py: 18 pt line, shared baseline, stock page 2 CLUT',
              dict(battle_style, source_width=bounds[2] - bounds[0], painted_width=painted_width),
              tile.tobytes().translate(index_lut))

    rel = 'config/full-story-components.json'
    for key in ('scenario_select_effect', 'mode_select_effect'):
        sc = load_json(ROOT / rel)[key]['select_heading']
        tc = author.section(rel, key)['select_heading']
        previous = previous_sections[f'{rel}#{key}']['value']['select_heading'] if args.compare else None
        for band, rect in SELECT_HEADING_BANDS.items():
            x, y, w, h = rect
            band_top = 0 if band == 'plain' else 24
            params = dict(point_size=17, stroke_gray=255, stroke_width=0 if band == 'plain' else 2.5,
                          fill_stroke_width=0, dx=-4, spacing=1, mode='gray')
            pixels = render(tc['text'], 88, 24, **params)
            cell_rect = (x, y - band_top, w, h)
            tile = crop(pixels, 88, cell_rect)
            if sum(tile) != sum(pixels):
                raise ValueError(f'{key}/{band}: title extends outside the texture patch')
            paint('opening', f'{key}/{band}', tc['text'], w, h, crop(thaw(sc, 'indices_zlib_base64'), 256, rect),
                  crop(thaw(previous, 'indices_zlib_base64'), 256, rect) if previous else None,
                  'Codex 2026-11-09 build_opening.py: 88x24 plain and bold masks',
                  dict(params, canvas=[88, 24]), tile)

    dump(HAND_DRAWN, dict(schema_version=1, font=FONT.name, font_sha256=hashlib.sha256(FONT.read_bytes()).hexdigest(),
                          entries=entries))
    for group, rows in sheets.items():
        contact_sheet(group, rows)


if __name__ == '__main__':
    main()
