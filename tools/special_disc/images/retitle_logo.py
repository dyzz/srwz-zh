"""Chinese subtitle for the SP title logo (VT1 chunk 28, 「スペシャルディスク」).

The record holds three 512x256 PSMT4 pictures that share one 64-colour CLUT
(four 16-colour banks, bank = picture index):
  p0  bank 0  the drawn art: the framed band 「スペシャルディスク」, the same
              words set in two lines at the top right, and the stripe parts
  p1  bank 1  the orange glow drawn under it
  p2  bank 2  flame parts, identical to the main game's

Bank 0 is a single ramp: 0 transparent, 1-7 the orange rim (alpha 120-255),
8-10 the yellow fill, so a glyph is just a "tone" field. Both the rim and the
glow are reproduced from the Japanese art instead of being invented:

  * rim/fill: the tone is read off a signed distance to the glyph core, with
    the core shifted and the vertical axis scaled (the rim is wider below and
    right). Shift, scale and the distance -> index table are fitted on the
    Japanese glyphs and must reproduce them closely.
  * glow: p1 is the art's ink dilated and blurred, mapped by a second fitted
    table. It is rewritten as a difference, so everything the text does not
    touch keeps its original index; the band interior is treated as lit so
    that the shorter Chinese line does not leave the band unevenly glowing.

The Chinese line is set in the project font with the logo's italic slant and
the ink height of the kana it replaces.

Outputs in jobs/vt1-28-logo/: clean.png (band without the kana), preview-ja.png,
preview-zh.png, final-zh-p0.npy, final-zh-p1.npy (logical PSMT4 indexes),
rebuild.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
sys.path.insert(0, str(ROOT / "tools"))
from srwz.psmt4 import swizzle_psmt4, unswizzle_psmt4  # noqa: E402
from srwz.tim2 import parse_tim2  # noqa: E402
from srwz.tim2_writeback import _csm1_palette_offset  # noqa: E402

TD = ROOT / "work/analysis/sp-texture-diff-20260912"
JOB = OUT / "jobs" / "vt1-28-logo"
RECORD = "7e7133668e43b92b9d78cc668386034805a1aaa790785aba8bb1a9de8fb8c731"
FONT_LOCK = json.loads((ROOT / "config/fonts/harmonyos-sans-sc.lock.json").read_text())["font"]
FONT = ROOT / FONT_LOCK["path"]
W, H = 512, 256
SS = 8
SHEAR = 0.5  # the frame's own slant is 0.58 px per row; the kana are set to match
TEXT = "特别篇"
# band: the kana ink sits in rows 22-43 between the frame's left block and right bar
BAND_ROWS = (22, 44)
BAND_X = (45, 325)
BAND_INK_X = (53, 314)
BAND_CY = 32.0
BAND = dict(height=17, stroke=0.15, tracking=54, width_scale=1.4)
# The kana carry a 2 px rim. Hanzi of this height have 1 px counters, which a rim
# that wide floods, so the Chinese line reads its tone off a compressed distance.
RIM_SCALE = 1.6
# Top right: the band's own text again, cut in two and moved. The game draws both
# halves back over the band, so the subtitle is painted twice; the copies have to
# keep matching the band or the title shows the text twice, side by side.
BLOCK = dict(rows=(0, 66), x=(345, W))
COPIES = ((304, -16), (160, 16))  # band -> block for the left and the right half
SPLIT_RANGE = (192, 209)  # where the cut may fall: both halves must stay in the block
PIN_HOLE = 3  # transparent specks up to this many pixels are closed, real counters are not
BINS = np.arange(-6, 6.01, 0.5)
GLOW_BINS = np.linspace(0, 1, 41)
GLOW_REGION = (0, 66, 0, 350)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_record():
    data = (TD / "tim2" / f"{RECORD}.tm2").read_bytes()
    assert sha256(data) == RECORD
    record = parse_tim2(data)
    pictures, banks = [], []
    clut = None
    for index, picture in enumerate(record.pictures):
        assert (picture.image_type, picture.width, picture.height) == (4, W, H)
        a = picture.offset + picture.header_size
        pictures.append(np.frombuffer(
            unswizzle_psmt4(data[a:a + picture.image_size], W, H, row_major_pages=True),
            np.uint8).reshape(H, W).copy())
        if picture.clut_size:
            clut = data[a + picture.image_size:a + picture.image_size + picture.clut_size]
        banks.append(np.array([[*clut[_csm1_palette_offset(index * 16 + n) * 4:][:3],
                                min(255, clut[_csm1_palette_offset(index * 16 + n) * 4 + 3] * 2)]
                               for n in range(16)], np.uint8))
    return pictures, banks


def band_masks(p0):
    """Split the band into its frame and the kana inside it."""
    glyph = np.zeros(p0.shape, bool)
    for y in range(*BAND_ROWS):
        row, runs, x = p0[y, :340], [], 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                runs.append((start, x))
            else:
                x += 1
        assert len(runs) >= 2, y  # the frame's left block and right bar
        for start, end in runs[1:-1]:
            glyph[y, start:end] = True
    return glyph


def translate(a, dx, dy):
    """Shift without wrapping."""
    out = np.zeros_like(a)
    out[max(0, dy):H + min(0, dy), max(0, dx):W + min(0, dx)] = \
        a[max(0, -dy):H + min(0, -dy), max(0, -dx):W + min(0, -dx)]
    return out


def block_mask():
    m = np.zeros((H, W), bool)
    m[BLOCK["rows"][0]:BLOCK["rows"][1], BLOCK["x"][0]:BLOCK["x"][1]] = True
    return m


def rebuild_block(text, split):
    """The block as the two halves of the band's text, cut at column `split`."""
    out = np.zeros((H, W), np.uint8)
    for (dx, dy), (x0, x1) in zip(COPIES, ((BAND_X[0], split), (split, BAND_X[1]))):
        part = np.zeros((H, W), np.uint8)
        part[BAND_ROWS[0]:BAND_ROWS[1], x0:x1] = text[BAND_ROWS[0]:BAND_ROWS[1], x0:x1]
        out = np.maximum(out, translate(part, dx, dy))
    return out


def check_copies(p0, glyph):
    """The Japanese block must be exactly the Japanese band text, cut and moved."""
    text = np.where(glyph, p0, 0).astype(np.uint8)
    inside = block_mask()
    want = np.where(inside, p0, 0)
    best = None
    for split in range(*SPLIT_RANGE):
        got = rebuild_block(text, split)
        assert not got[~inside].any(), split
        same = float((got == want).mean())
        if best is None or same > best[0]:
            best = (same, split)
    assert best[0] >= 0.9999, f"the top-right block is not a copy of the band ({best[0]:.4f})"
    return dict(split=best[1], identical=round(best[0], 5))


def split_column(text):
    """Cut the Chinese line where it has no ink, as the Japanese cut falls in a kana gap."""
    ink = text[BAND_ROWS[0]:BAND_ROWS[1]].astype(bool).sum(0)
    candidates = [(int(ink[x]), abs(x - 200), x) for x in range(*SPLIT_RANGE)]
    return min(candidates)[2]


def signed_distance(core, sx, sy, k, scale=4):
    """Signed distance in pixels to `core` shifted by (sx, sy), y axis scaled by k."""
    big = cv2.resize(core.astype(np.uint8), (core.shape[1] * scale, int(round(core.shape[0] * scale * k))),
                     interpolation=cv2.INTER_NEAREST)
    big = cv2.warpAffine(big, np.float32([[1, 0, sx * scale], [0, 1, sy * scale * k]]),
                         (big.shape[1], big.shape[0]), flags=cv2.INTER_NEAREST)
    d = (cv2.distanceTransform(1 - big, cv2.DIST_L2, 3) - cv2.distanceTransform(big, cv2.DIST_L2, 3)) / scale
    return cv2.resize(d, (core.shape[1], core.shape[0]), interpolation=cv2.INTER_AREA)


def fit_tone(p0, glyph):
    """Fit the rim/fill model on the Japanese glyphs: (shift, y scale, distance -> index)."""
    target = np.where(glyph, p0, 0).astype(float)
    core = glyph & (p0 >= 8)
    region = np.zeros(p0.shape, bool)
    region[BAND_ROWS[0]:BAND_ROWS[1], BAND_X[0]:BAND_X[1]] = True
    best = None
    for sx in np.arange(-1.0, 0.51, 0.25):
        for sy in np.arange(-1.0, 0.51, 0.25):
            for k in (0.8, 1.0, 1.2, 1.4):
                d = signed_distance(core, sx, sy, k)
                bucket = np.digitize(d[region], BINS)
                table = np.zeros(len(BINS) + 1)
                seen = []
                for b in range(len(BINS) + 1):
                    m = bucket == b
                    if m.sum() > 3:
                        table[b] = np.median(target[region][m])
                        seen.append(b)
                # Kana strokes are thin, so the deep-inside buckets hold no sample. Leaving them
                # at zero punches transparent holes wherever Chinese strokes cross, so every
                # bucket up to the last observed one is filled from the ones that do have samples.
                table[:seen[0]] = table[seen[0]]
                table[seen[0]:seen[-1] + 1] = np.interp(range(seen[0], seen[-1] + 1), seen, table[seen])
                table[seen[-1] + 1:] = 0
                table = np.round(table)
                error = np.abs(table[np.digitize(d, BINS)][region] - target[region])
                if best is None or error.mean() < best[0]:
                    best = (float(error.mean()), float(sx), float(sy), float(k), table,
                            float((error == 0).mean()))
    assert best[0] <= 0.6, f"rim model does not reproduce the kana (mae {best[0]:.2f})"
    return best


def fit_glow(p0, p1):
    """Fit the glow layer as the art's ink dilated and blurred."""
    ink = p0 > 0
    y0, y1, x0, x1 = GLOW_REGION
    region = np.zeros(p0.shape, bool)
    region[y0:y1, x0:x1] = True
    best = None
    for r in (0, 1, 2, 3):
        source = ndimage.binary_dilation(ink, np.ones((2 * r + 1, 2 * r + 1))) if r else ink
        for sigma in (3, 4, 5, 6, 7, 8, 9, 11, 13):
            g = cv2.GaussianBlur(source.astype(np.float32), (0, 0), sigma)
            bucket = np.digitize(g[region], GLOW_BINS)
            table = np.zeros(len(GLOW_BINS) + 1)
            for b in range(len(GLOW_BINS) + 1):
                m = bucket == b
                if m.sum() > 5:
                    table[b] = np.median(p1[region][m])
            error = np.abs(table[np.digitize(g, GLOW_BINS)][region] - p1[region])
            if best is None or error.mean() < best[0]:
                best = (float(error.mean()), r, sigma, table, float((error <= 1).mean()))
    assert best[0] <= 0.8, f"glow model does not reproduce p1 (mae {best[0]:.2f})"
    return best


def glow_of(ink, r, sigma, table):
    source = ndimage.binary_dilation(ink, np.ones((2 * r + 1, 2 * r + 1))) if r else ink
    g = cv2.GaussianBlur(source.astype(np.float32), (0, 0), sigma)
    return table[np.digitize(g, GLOW_BINS)]


def render_run(text, height, stroke, width_scale, tracking):
    """Supersampled binary mask of one line, ink `height` px tall."""
    size = round(height * SS / 0.72)
    font = ImageFont.truetype(str(FONT), size)
    cells = []
    for ch in text:
        pad = size
        layer = Image.new("L", (size * 2 + 2 * pad, size * 2 + 2 * pad), 0)
        ImageDraw.Draw(layer).text((pad, pad), ch, font=font, fill=255,
                                   stroke_width=round(stroke * SS), stroke_fill=255)
        a = np.asarray(layer)
        ys, xs = np.where(a > 127)
        cells.append((a, int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1))
    top = min(c[1] for c in cells)
    scale = height * SS / (max(c[2] for c in cells) - top)
    glyphs = []
    for a, _y0, _y1, x0, x1 in cells:
        crop = a[top:max(c[2] for c in cells), x0:x1]
        glyphs.append(np.asarray(Image.fromarray(crop).resize(
            (max(1, round(crop.shape[1] * scale * width_scale)), max(1, round(crop.shape[0] * scale))),
            Image.LANCZOS)))
    gap = round(tracking * SS)
    width = sum(g.shape[1] for g in glyphs) + gap * (len(glyphs) - 1)
    run = np.zeros((max(g.shape[0] for g in glyphs), width), np.uint8)
    x = 0
    for g in glyphs:
        run[:g.shape[0], x:x + g.shape[1]] = np.maximum(run[:g.shape[0], x:x + g.shape[1]], g)
        x += g.shape[1] + gap
    return run


def place(run, cx, cy):
    """Shear a supersampled run and sample it onto the texture grid, centred on (cx, cy)."""
    canvas = np.zeros((H * SS, W * SS), np.uint8)
    y0 = round((cy - run.shape[0] / SS / 2) * SS)
    x0 = round((cx - run.shape[1] / SS / 2) * SS)
    canvas[y0:y0 + run.shape[0], x0:x0 + run.shape[1]] = run
    canvas = cv2.warpAffine(canvas, np.float32([[1, -SHEAR, SHEAR * cy * SS], [0, 1, 0]]),
                            (canvas.shape[1], canvas.shape[0]), flags=cv2.INTER_NEAREST)
    return np.asarray(Image.fromarray(canvas).resize((W, H), Image.BOX), np.float32) / 255.0


def composite(p0, p1, banks, background=(52, 40, 92)):
    out = np.ones(p0.shape + (3,)) * np.array(background, float)
    for idx, bank in ((p1, banks[1]), (p0, banks[0])):
        rgba = bank[idx].astype(float)
        a = rgba[..., 3:4] / 255
        out = out * (1 - a) + rgba[..., :3] * a
    return out.astype(np.uint8)


def main() -> None:
    assert sha256(FONT.read_bytes()) == FONT_LOCK["sha256"]
    JOB.mkdir(parents=True, exist_ok=True)
    (p0, p1, p2), banks = load_record()
    glyph = band_masks(p0)
    tone_mae, sx, sy, k, tone_table, tone_exact = fit_tone(p0, glyph)
    glow_mae, glow_r, glow_sigma, glow_table, glow_within1 = fit_glow(p0, p1)

    # 1. the band without its kana, and the copy of it at the top right cleared
    copy_source = check_copies(p0, glyph)
    clean = p0.copy()
    clean[glyph] = 0
    block = np.zeros(p0.shape, bool)
    block[BLOCK["rows"][0]:BLOCK["rows"][1], BLOCK["x"][0]:BLOCK["x"][1]] = True
    cleared_block = int((clean[block] > 0).sum())
    clean[block] = 0

    # 2. the Chinese line inside the band
    run = render_run(TEXT, BAND["height"], BAND["stroke"], BAND["width_scale"], BAND["tracking"])
    coverage = place(run, sum(BAND_INK_X) / 2, BAND_CY)
    tone = tone_table[np.digitize(signed_distance(coverage > 0.5, sx, sy, k) * RIM_SCALE, BINS)].astype(np.uint8)
    zone = np.zeros(p0.shape, bool)
    zone[BAND_ROWS[0]:BAND_ROWS[1], BAND_X[0]:BAND_X[1]] = True
    final0 = clean.copy()
    painted = zone & (tone > 0)
    final0[painted] = tone[painted]
    assert not (tone[~zone] > 0).any(), "the Chinese line reaches outside the band"
    assert not (painted & (clean > 0)).any(), "the Chinese line overlaps the frame"
    # A transparent pixel enclosed by ink shows the background through the glyph. Counters
    # (口, 冊 and so on) are meant to be open; the specks left where strokes nearly meet are
    # not, and at this size they read as black dots in game, so they are closed with the
    # brightest ink around them.
    assert not (coverage > 0.5)[tone == 0].any(), "the Chinese core has transparent pixels"
    inside = final0[BAND_ROWS[0]:BAND_ROWS[1], BAND_X[0]:BAND_X[1]]
    label, count = ndimage.label(ndimage.binary_fill_holes(inside > 0) & (inside == 0))
    pin_holes = []
    for n in range(1, count + 1):
        speck = label == n
        if speck.sum() > PIN_HOLE:
            continue
        inside[speck] = int(inside[ndimage.binary_dilation(speck) & (inside > 0)].max())
        pin_holes.append(int(speck.sum()))
    label, count = ndimage.label(ndimage.binary_fill_holes(inside > 0) & (inside == 0))
    areas = sorted(int(a) for a in ndimage.sum(np.ones_like(label), label, range(1, count + 1)))
    assert all(a > PIN_HOLE for a in areas), f"the band still has pin holes: {areas}"

    # 3. the same line copied into the block, cut where the Chinese has no ink
    split = split_column(final0)
    copies = rebuild_block(np.where(clean > 0, 0, final0), split)
    assert not copies[~block].any(), "the copy falls outside the block"
    final0[copies > 0] = copies[copies > 0]
    zone |= block
    assert (final0[~zone] == p0[~zone]).all()

    # 3. glow: the difference, with the band interior treated as lit either way
    lit = ndimage.binary_fill_holes(p0 > 0) & zone
    before = glow_of((p0 > 0) | lit, glow_r, glow_sigma, glow_table)
    after = glow_of((final0 > 0) | lit, glow_r, glow_sigma, glow_table)
    final1 = np.clip(np.round(p1 + after - before), 0, 15).astype(np.uint8)
    reach = ndimage.binary_dilation(zone, np.ones((4 * glow_sigma + 1,) * 2))
    assert not (final1 != p1)[~reach].any(), "the glow changed away from the edited zones"

    np.save(JOB / "final-zh-p0.npy", final0)
    np.save(JOB / "final-zh-p1.npy", final1)
    Image.fromarray(composite(clean, p1, banks)).save(JOB / "clean.png")
    for name, (a, b) in (("preview-ja.png", (p0, p1)), ("preview-zh.png", (final0, final1))):
        view = composite(a, b, banks)[0:70, 0:512]
        Image.fromarray(view).resize((view.shape[1] * 2, view.shape[0] * 2), Image.NEAREST).save(JOB / name)
    report = dict(
        source=dict(member="DATA/VT1.BIN", location="g028/stream@bafbc70/tim2@0", record_sha256=RECORD,
                    pictures="p0 art (bank 0), p1 glow (bank 1), p2 flames (bank 2, untouched)"),
        text=TEXT, font=FONT_LOCK["path"], shear=SHEAR,
        band=dict(**BAND, rim_scale=RIM_SCALE, centre=[round(sum(BAND_INK_X) / 2, 1), BAND_CY],
                  width=round(run.shape[1] / SS, 1)),
        block=dict(japanese=copy_source, split_column=split, shifts=[list(c) for c in COPIES],
                   note="the game draws both halves back over the band, so the line is painted twice"),
        rim_model=dict(shift=[sx, sy], y_scale=k, mae=round(tone_mae, 3), exact=round(tone_exact, 3),
                       table=tone_table.tolist()),
        glow_model=dict(dilate=glow_r, sigma=glow_sigma, mae=round(glow_mae, 3),
                        within_one_index=round(glow_within1, 3)),
        changed=dict(p0_pixels=int((final0 != p0).sum()), p1_pixels=int((final1 != p1).sum()),
                     pin_holes_closed=pin_holes, open_counters=areas,
                     kana_pixels_removed=int(glyph.sum()), block_pixels_cleared=cleared_block,
                     p0_indexes=sorted(set(np.unique(final0).tolist()))),
        outputs=dict(p0_sha256=sha256(final0.tobytes()), p1_sha256=sha256(final1.tobytes())),
    )
    (JOB / "rebuild.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
