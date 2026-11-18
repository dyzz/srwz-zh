"""Author SP Traditional picture inputs with the September image recipes and retained plates.

Run from any directory using Python with Pillow, NumPy, OpenCV and SciPy.
The build consumes only the frozen outputs, not the authoring workspace.
"""
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / 'tools/special_disc/images'
sys.path[:0] = [str(IMAGES), str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
import apply_heading_plate as heading
import rebuild_banner1 as banner
import rebuild_hsfc105 as chart
import render_buttons as buttons
import retitle_banners35 as cells
import retitle_hsfc110_nisv128 as titles
import retitle_logo as logo
import build_preview as preview
from special_disc.event_gallery import author_banner as gallery

KIT = preview.KIT
JOBS = buttons.OUT / 'jobs'
DEST = ROOT / 'config/zh-hant/hand-drawn/sp'
REVIEW = ROOT / 'build/zh-hant/sp-pictures-review'
WORK = ROOT / 'build/zh-hant/sp-picture-authoring'
TC = DEST / 'config/assets/special-disc/preview'
GALLERY = Path('tools/special_disc/event_gallery/assets')


def metadata(slug, filename='rebuild.json'):
    return json.loads((JOBS / slug / filename).read_text())


def pair(name, left, right):
    canvas = Image.new('RGB', (left.width + right.width + 12, max(left.height, right.height) + 24), '#272a30')
    d = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(buttons.FONT), 14)
    for x, label, im in [(0, '简体', left), (left.width + 12, '繁體', right)]:
        d.text((x + 5, 1), label, fill='white', font=font)
        im = im.convert('RGBA')
        canvas.paste(im, (x, 24), im)
    canvas.save(REVIEW / (name + '.png'))


def records():
    """Recover just the native records needed by the original recipes from the source disc."""
    members = preview.member_map(preview.scan_iso9660(preview.ISO))
    exe = (ROOT / 'work/disc/special-disc/SLPS_259.20').read_bytes()
    result = {}
    with preview.ISO.open('rb') as f:
        cached = {}
        for name, off, tim, pic, bank, layout, rel, _ in preview.EDITS:
            if (name, off) not in cached:
                member = members[name]
                table = preview.offsets(exe, preview.TABLES[name], member.size)
                end = table[table.index(off) + 1]
                f.seek(member.extent_lba * 2048 + off)
                cached[name, off] = preview.decode_production(f.read(end - off)).output
            data = cached[name, off][tim:]
            result[rel] = data[:preview.parse_tim2(data).size]
    return result


def atlas(slug, names):
    report = metadata(slug, 'render.json')
    sc = np.load(KIT / slug / 'final-zh-indexes.npy')
    pal = np.load(KIT / slug / 'final-zh-palette.npy')
    source = np.array(Image.open(JOBS / slug / 'source.png').convert('RGBA'))
    opaque = source[..., 3] > 0
    assert buttons.sha256((buttons.PLATES / 'ai-original.png').read_bytes()) == buttons.AI_SHA256
    final = np.zeros(source.shape[:2] + (3,), np.float64)
    boxes = next(j['mask_boxes'] for j in json.loads((JOBS.parent / 'manifest.json').read_text())['jobs']
                 if j['slug'] == slug)
    for entry, text in zip(report['buttons'], names, strict=True):
        col, row = entry['tile']
        tiles = [source[buttons.tile_slice(col, row, s)] for s in range(5)]
        for s, tile in enumerate(tiles):
            buttons.FITS[s, (tile[..., 3] > 0).tobytes()] = entry['plates'][s]
        faces, masks, _ = buttons.button_faces(tiles)
        if entry['text'] is None:
            region = buttons.label_box(boxes, col, row, 0)
            xs = np.where(region & (tiles[0][..., :3].max(2) < 32))[1]
            centre = (xs.min() + xs.max() + 1) / 2
        else:
            box = entry['japanese_ink']
            centre = (box[0] + box[2]) / 2
        fill, _ = buttons.label_coverage(text, centre)
        for s, face in enumerate(faces):
            st = report['label_style'][str(s)]
            params = np.array([*st['glow_rgb'], st['glow_opacity'], *st['rim_rgb'], *st['rim_weights'],
                               *st['fill_rgb'], st['fill_opacity']])
            styled = buttons.compose_label(fill, face, params, st['glow_sigma'])
            final[buttons.tile_slice(col, row, s)] = face + masks[s][..., None] * (styled - face)
    entries, ids = buttons.fit_palette(final[opaque])
    palette = np.zeros_like(pal)
    palette[1:, :3] = entries
    palette[1:, 3] = 255
    out = np.zeros_like(sc)
    out[opaque] = ids + 1
    assert np.array_equal(palette[out][..., 3], pal[sc][..., 3])
    np.save(TC / slug / 'final-zh-indexes.npy', out)
    np.save(TC / slug / 'final-zh-palette.npy', palette)
    pair(slug, Image.fromarray(pal[sc][:400]), Image.fromarray(palette[out][:400]))


def author_banners(native):
    for k, text in [(1, '中斷對話合集'), (2, '影片集'), (3, '設定資料集'), (4, '戰鬥劇場'), (5, '壁紙一覽')]:
        slug = 'aid-banner-' + str(k)
        rel = Path(slug) / 'final-zh.png'
        sc = Image.open(KIT / rel).convert('RGBA')
        final = np.array(sc)
        if k != 2:
            rec = native[str(rel)]
            pal = preview.palette_rgba(rec, 0, k - 1, k - 1)
            meta = metadata(slug)
            if k == 4:
                # Two AI-painted originals have no text-free intermediate. Inpaint the dark
                # ink inside the title rectangle, preserving the artwork and original underline.
                clean = np.array(sc)[:78, :620, :3].copy()
                zone = clean[31:66, 400:568]
                mask = cv2.dilate((zone.max(2) < 95).astype('uint8'), np.ones((5, 5), 'uint8'))
                zone[:] = cv2.inpaint(zone, mask, 4, cv2.INPAINT_TELEA)
            else:
                clean = np.array(Image.open(JOBS / slug / 'clean.png'))[:78, :620, :3]
            if k in (1, 4):
                style = metadata('aid-banner-1')['title_layer']
                mask, _ = banner.chinese_mask(text, 9, banner.calibrate(9))
                rgb = banner.compose(clean, mask, [*style['glow_blur_sigma_xy'], style['glow_gain'],
                                                   style['glow_max']], np.array(style['glow_rgb']))
            else:
                mask = np.zeros((78, 620), np.float32)
                boxes = meta['cells']
                shared = cells.BANNERS[k]['shared']
                top, bottom = [np.median([boxes[i][v] for i in shared]) for v in (1, 3)]
                for ch, (x0, y0, x1, y1) in zip(text, boxes, strict=True):
                    glyph = cells.render_glyph(ch, *meta['em_px_xy'], 6)
                    cy = (y0 + y1) / 2 if ch == '一' else (top + bottom) / 2
                    mask = cells.place(mask, glyph, (x0 + x1) / 2, cy - glyph.shape[0] / 16)
                mask = cv2.GaussianBlur((mask > 0.5).astype(np.float32), (0, 0), 0.5)
                rgb = cells.compose(clean, mask, np.array(meta['style']), meta['shadow_offset'])
            q = banner.quantize(np.clip(rgb, 0, 255), pal)
            region = final[:78, :620]
            region[..., :3][region[..., 3] == 255] = q[region[..., 3] == 255]
            Image.fromarray(final).save(TC / rel)
        pair(slug, sc.crop((0, 0, 620, 78)), Image.fromarray(final[:78, :620]))


def chart_clarity(native):
    """Replay the approved November 9 indexed text pass on both tabs."""
    import base64
    import zlib
    config = 'config/assets/special-disc/chart-title-clarity.json'
    doc = json.loads((ROOT / config).read_text())
    for r in doc['records']:
        z = r['tab'] == 'Z'
        slug = 'hsfc-chart-title-z' if z else 'hsfc-chart-title-sp'
        rel = slug + ('/final-zh-indexes.npy' if z else '/final-zh.png')
        rec = native[rel]
        pal = preview.palette_rgba(rec, 0, 0, 0)
        q = preview.parse_tim2(rec).pictures[0]
        a = q.offset + q.header_size
        ja = np.frombuffer(rec[a:a+q.image_size], np.uint8).reshape(q.height, q.width)
        x, y, width, h = r['rect']
        w = 101 if z else width
        face, outline = r['native_fill_index'], r['native_outline_index']
        colors = np.unique(ja[y:y+h, 17:181])
        colors = colors[pal[colors, 3] == 255]
        rgb = pal[:, :3].astype(float)
        views = []
        for folder, text in [(KIT, '剧情流程'), (TC, '劇情流程')]:
            idx, _ = preview.target_indexes(folder / rel, ja, pal)
            bg = idx[y:y+h, 70 if z else 6, None]
            def coverage(stroke):
                data = chart.render_grayscale_text_mask(chart.require_imagemagick(), buttons.FONT, text,
                    width=w, height=h, point_size=r['point_size'], stroke_gray='white', stroke_width=stroke,
                    character_spacing=1.5 if z else 2.6, vertical_offset=1 if z else 0,
                    supersample_factor=4, preserve_supersample=True)
                mask = np.frombuffer(data, np.uint8).reshape(h, 4, w, 4)
                return mask.mean((1,3))[...,None] / 255
            outer, fill = coverage(r['stroke_width']), coverage(0.8 if z else 1.)
            composite = (rgb[bg]*(1-outer) + rgb[outline]*outer)*(1-fill) + rgb[face]*fill
            out = colors[((composite[:,:,None]-rgb[colors])**2).sum(-1).argmin(-1)]
            out = np.where(outer[...,0] == 0, bg, out)
            out[(outer[...,0] == 1) & (fill[...,0] == 0)] = outline
            out[fill[...,0] == 1] = face
            region = idx[y:y+h,x:x+width].copy()
            before = preview.sha256(region.tobytes())
            region[:,:w] = out
            if z:
                region[:,101:] = bg
                region[:,103:] = ja[y:y+h,216:247]
            data = region.tobytes()
            if folder == KIT:
                assert preview.sha256(data) == r['after_sha256'], (slug, 'Simplified clarity replay drift')
            else:
                r.update(before_sha256=[before], after_sha256=preview.sha256(data),
                         after_zlib_base64=base64.b64encode(zlib.compress(data,9)).decode())
            idx[y:y+h,x:x+width] = region
            views.append(Image.fromarray(pal[idx][y-6:y+h+6,:320].astype(np.uint8)))
        pair(slug, *views)
    doc['text'] = '劇情流程'
    (DEST / config).write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n')


def main():
    assert buttons.sha256(buttons.FONT.read_bytes()) == buttons.FONT_LOCK['sha256']
    REVIEW.mkdir(parents=True, exist_ok=True)
    for rel in KIT.iterdir():
        (TC / rel.name).mkdir(parents=True, exist_ok=True)
    native = records()
    for slug, labels in [('vt1-16-title-menu', ['額外關卡', '特別劇場', '資料庫', '戰鬥鑑賞']),
                         ('vt1-30-extra-stage-menu', ['劇情模式', '讀取', '挑戰模式', '繼續']),
                         ('vt1-53-battle-viewer-menu', ['普通', 'TRI', '簡易', '單機'])]:
        atlas(slug, labels)
    for edit, text in zip([e for e in preview.EDITS if e[6].startswith('heading-plate/')],
                          ['額外關卡', '劇情模式', '挑戰模式', '戰鬥鑑賞', '特別劇場'], strict=True):
        rel = edit[6]
        plate = Image.open(JOBS / 'heading-plate/clean.png').convert('RGBA')
        image = heading.quantize(heading.draw_title(plate, text, 16, True), preview.palette_rgba(native[rel], 0, 0, 0))
        image.save(TC / rel)
        pair(Path(rel).stem, Image.open(KIT / rel), image)
    author_banners(native)
    # Run the September title renderer in an isolated output tree.
    titles.OUT = WORK
    WORK.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(JOBS.parent / 'manifest.json', WORK / 'manifest.json')
    for slug in titles.JOBS:
        dest = WORK / 'jobs' / slug
        dest.mkdir(parents=True, exist_ok=True)
        for filename in ('source.png', 'clean.png'):
            shutil.copyfile(JOBS / slug / filename, dest / filename)
    titles.JOBS['hsfc-chart-title-sp']['zh'] = '劇情流程'
    titles.JOBS['nisv-sound-select-title']['zh'] = '音樂選擇'
    titles.palette_of = lambda n: preview.palette_rgba(native[('hsfc-chart-title-sp' if n == 110 else
                                                               'nisv-sound-select-title') + '/final-zh.png'], 0, 0, 0)
    titles.main()
    for slug in titles.JOBS:
        shutil.copyfile(WORK / 'jobs' / slug / 'final-zh.png', TC / slug / 'final-zh.png')
        if slug == 'nisv-sound-select-title':
            pair(slug, Image.open(JOBS / slug / 'preview-zh.png'), Image.open(WORK / 'jobs' / slug / 'preview-zh.png'))
    slug = 'hsfc-chart-title-z'
    rel = slug + '/final-zh-indexes.npy'
    rec = native[rel]
    q = preview.parse_tim2(rec).pictures[0]
    a = q.offset + q.header_size
    idx = np.frombuffer(rec[a:a + q.image_size], np.uint8).reshape(q.height, q.width).copy()
    info = metadata(slug)
    mapping = info['mapping']
    chart.restore_rows(idx, **mapping['restore_box'], background=range(37, 48), glyph_indexes={34, *range(48, 64)})
    box = mapping['text_box']
    style = dict(info['style'])
    style.pop('font')
    mask = chart.render_grayscale_text_mask(chart.require_imagemagick(), buttons.FONT, '劇情流程 Z',
                                             width=box['width'], height=box['height'], **style)
    pal = preview.palette_rgba(rec, 0, 0, 0).astype(np.uint8)
    chart.paint_text(idx, mask, **box, ramp_indexes=mapping['ramp_indexes'], colours=pal)
    np.save(TC / rel, idx)
    chart_clarity(native)
    slug = 'vt1-28-logo'
    rec = native[slug + '/final-zh-p0.npy']
    assert logo.sha256(rec) == logo.RECORD
    logo.TD = WORK
    (WORK / 'tim2').mkdir(exist_ok=True)
    (WORK / 'tim2' / (logo.RECORD + '.tm2')).write_bytes(rec)
    logo.TEXT = '特別篇'
    logo.JOB = WORK / 'jobs' / slug
    logo.main()
    for p in logo.JOB.glob('final-zh-p*.npy'):
        shutil.copyfile(p, TC / slug / p.name)
    pair(slug, Image.open(JOBS / slug / 'preview-zh.png'), Image.open(logo.JOB / 'preview-zh.png'))
    # The separately appended gallery banner is the visible fifth choice.
    assets = ROOT / GALLERY
    gallery.TITLE = '名場面集'
    args = SimpleNamespace(background=assets / 'source/meyrin-impulse-background.png', crop=(0, 220, 2169, 293),
                           matte=(235, 225, 207), outdir=WORK / 'gallery', title_stroke_px=0.75, title_height_scale=1,
                           renderer=IMAGES / 'rebuild_banner1.py', title_style=JOBS / 'aid-banner-1/rebuild.json',
                           shape_template=KIT / 'aid-banner-5/final-zh.png',
                           tim2_template=ROOT / 'work/analysis/sp-aiddata-images-20260912/tim2/block-002-tim2-01.tm2')
    gallery.author(args)
    (DEST / GALLERY).mkdir(parents=True, exist_ok=True)
    for p in args.outdir.iterdir():
        shutil.copyfile(p, DEST / GALLERY / p.name)
    pair('event-gallery', Image.open(assets / 'event-banner-preview@2x.png'), Image.open(args.outdir / 'event-banner-preview@2x.png'))
    snap = json.loads((KIT.parent / 'preview.json').read_text())
    for row in snap['files']:
        p = TC / row['path']
        if p.exists():
            row.update(sha256=preview.sha256(p.read_bytes()), size=p.stat().st_size)
    (TC.parent / 'preview.json').write_text(json.dumps(snap, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
