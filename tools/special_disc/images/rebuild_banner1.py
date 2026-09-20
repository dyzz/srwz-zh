"""Rebuild Special Theatre banner 1 from its in-game source art and retitle it.

The art of banner 1 (中断メッセージ集) is the 640x448 RGB24 picture at KVMDATA
raw TIM2 0x25C4C0 (also in Original), found by find_banner_sources_sift.py.
The banner is that picture blurred (sigma 1.3), resampled by a fixed affine,
plus a title layer: black glyphs, a black 2px underline and a cream outer glow
(blur of the glyph mask, gain, clamp, normal blend). All of this is fitted
against the original banner here and re-checked on every run.

Outputs in jobs/aid-banner-1/ (user confirmed the title 中断对话合集, 2026-09-17):
  clean.png          text-free banner, original pixels outside the title layer
  final-zh.png       Chinese banner, quantized to the banner's own palette bank
  rebuild-check.png  original / title model / clean / Chinese (2x)
  rebuild.json       fitted parameters, layout and provenance
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
from srwz.tim2 import parse_tim2  # noqa: E402
from srwz.tim2_writeback import _csm1_palette_offset  # noqa: E402

JOB = OUT / "jobs" / "aid-banner-1"
TD = ROOT / "work/analysis/sp-texture-diff-20260912"
AID = ROOT / "work/analysis/sp-aiddata-images-20260912"
SOURCE_RECORD = "0d77983e1b8341cb4deda3b385ec0fc702a221bac4a593433edad126cdce12b4"  # KVMDATA raw TIM2 @0x25C4C0
BANNER_TIM2 = AID / "tim2/block-002-tim2-01.tm2"
# Project-wide Chinese font (config/fonts/zh-localization-font.json).
FONT_LOCK = json.loads((ROOT / "config/fonts/harmonyos-sans-sc.lock.json").read_text())["font"]
FONT = ROOT / FONT_LOCK["path"]
W, H = 620, 78  # art area of the 1024x128 texture
# Banner pixel -> source pixel (SIFT + masked ECC, 2026-09-17).
AFFINE = np.array([[1.0186, 0.0002, 5.5558], [-0.0001, 1.1427, 192.3057]], np.float32)
SOURCE_BLUR = 1.3
FREE = (16, 222)  # the title layer lies inside y >= 16, x >= 222
# Title layer of the original (measured on the banner).
GLYPH_BOXES = [(278, 35, 310, 65), (317, 35, 352, 65), (356, 37, 383, 64), (387, 41, 413, 65),
               (417, 36, 449, 65), (453, 49, 483, 53), (487, 35, 518, 65), (521, 35, 557, 65)]
UNDERLINE_ROWS = (65, 67)
UNDERLINE_RIGHT = 600  # exclusive
UNDERLINE_LEAD = 44  # underline starts this far left of the first glyph
INK = np.array([9.0, 9.0, 8.0])
# Chinese layout. Size, baseline and weight are calibrated on 中/断/集, which both titles share.
SHARED = {"中": (278, 35, 310, 65), "断": (317, 35, 352, 65), "集": (521, 35, 557, 65)}
PITCH = 39.5  # kanji pitch of the original
RIGHT_INK = 557  # right edge of 集, same as the original
SS = 8
EDGE_GAIN = 1.6  # steeper coverage ramp, closer to the original's hard glyph edges


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_art() -> np.ndarray:
    rec = (TD / "tim2" / f"{SOURCE_RECORD}.tm2").read_bytes()
    assert sha256(rec) == SOURCE_RECORD
    q = parse_tim2(rec).pictures[0]
    assert (q.width, q.height, q.image_type) == (640, 448, 2)
    a = q.offset + q.header_size
    return np.frombuffer(rec[a:a + q.image_size], np.uint8).reshape(448, 640, 3).astype(np.float32)


def banner_palette() -> np.ndarray:
    """Bank 0 of the shared CLUT (banner 1), RGBA with PS2 alpha doubled."""
    rec = BANNER_TIM2.read_bytes()
    q = parse_tim2(rec).pictures[0]
    a = q.offset + q.header_size + q.image_size
    clut = rec[a:a + q.clut_size]
    assert len(clut) == 5 * 1024
    bank = clut[:1024]
    out = []
    for n in range(256):
        c = bank[_csm1_palette_offset(n) * 4:][:4]
        out.append((c[0], c[1], c[2], min(255, c[3] * 2)))
    return np.array(out, np.int32)


def quantize(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    opaque = palette[palette[:, 3] == 255][:, :3]
    flat = rgb.reshape(-1, 3).astype(np.int32)
    best = np.empty(len(flat), np.int64)
    for s in range(0, len(flat), 4096):
        chunk = flat[s:s + 4096]
        best[s:s + 4096] = ((chunk[:, None, :] - opaque[None]) ** 2).sum(-1).argmin(1)
    return opaque[best].reshape(rgb.shape).astype(np.uint8)


def art_model(banner: np.ndarray, free: np.ndarray):
    src = cv2.GaussianBlur(source_art(), (0, 0), SOURCE_BLUR)
    warped = cv2.warpAffine(src, AFFINE, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    fits = [np.polyfit(warped[..., c][free], banner[..., c][free], 1) for c in range(3)]
    model = np.stack([fits[c][0] * warped[..., c] + fits[c][1] for c in range(3)], -1)
    return model.astype(np.float64), [[round(float(v), 4) for v in f] for f in fits]


def original_title_mask(banner: np.ndarray, model: np.ndarray) -> np.ndarray:
    """Black glyph and underline pixels of the Japanese title."""
    lum, mlum = banner.mean(-1), model.mean(-1)
    glow = (lum - mlum) > 12
    glow[:, :200] = False
    glow[:FREE[0]] = False
    glow = ndimage.binary_closing(glow, np.ones((5, 5)), iterations=2)
    lab, n = ndimage.label(glow)
    glow = lab == 1 + int(np.argmax(ndimage.sum(glow, lab, range(1, n + 1))))
    hull = ndimage.binary_fill_holes(ndimage.binary_closing(glow, np.ones((9, 9)), iterations=2))
    dark = hull & (lum < 70)
    dark[UNDERLINE_ROWS[0]:UNDERLINE_ROWS[1]] = False
    lab, n = ndimage.label(dark, np.ones((3, 3)))
    keep = np.zeros(n + 1, bool)
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        cy, cx = (sl[0].start + sl[0].stop) / 2, (sl[1].start + sl[1].stop) / 2
        keep[i] = any(x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1 for x0, y0, x1, y1 in GLYPH_BOXES)
    mask = keep[lab].astype(np.float64)
    first = min(b[0] for b in GLYPH_BOXES)
    mask[UNDERLINE_ROWS[0]:UNDERLINE_ROWS[1], first - UNDERLINE_LEAD:UNDERLINE_RIGHT] = 1.0
    return mask


def glow_alpha(mask: np.ndarray, p) -> np.ndarray:
    sx, sy, k, gmax = p
    return np.clip(k * cv2.GaussianBlur(mask, (0, 0), sigmaX=sx, sigmaY=sy), 0, gmax)


def fit_glow(banner, model, mask, sel):
    from scipy import optimize
    B, Mo = banner[sel], model[sel]

    def colour(g):
        return (g * (B - (1 - g) * Mo)).sum(0) / np.maximum((g ** 2).sum(0), 1e-9)

    def loss(p):
        g = glow_alpha(mask, p)[sel][:, None]
        return float(np.abs((1 - g) * Mo + g * colour(g) - B).mean())

    r = optimize.minimize(loss, [6, 5, 3.6, 0.73], method="Nelder-Mead",
                          options=dict(maxiter=800, xatol=1e-4, fatol=1e-5))
    g = glow_alpha(mask, r.x)[sel][:, None]
    return [round(float(v), 4) for v in r.x], np.round(colour(g), 2), r.fun


def compose(base: np.ndarray, mask: np.ndarray, glow_p, glow_c) -> np.ndarray:
    g = glow_alpha(mask, glow_p)[..., None]
    out = (1 - g) * base + g * glow_c
    cov = mask[..., None]
    return (1 - cov) * out + cov * INK


def ink_box(ch: str, em_x: float, stroke: int):
    """Ink box of one glyph relative to the PIL 'la' pen, in banner pixels (x) and em-x units (y)."""
    font = ImageFont.truetype(str(FONT), round(em_x * SS))
    probe = Image.new("L", (round(em_x * SS * 3), round(em_x * SS * 3)), 0)
    ImageDraw.Draw(probe).text((SS * 8, SS * 8), ch, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    ys, xs = np.where(np.asarray(probe) > 127)
    return ((xs.min() - SS * 8) / SS, (xs.max() + 1 - SS * 8) / SS,
            (ys.min() - SS * 8) / SS, (ys.max() + 1 - SS * 8) / SS)


def calibrate(stroke: int):
    """em_x, em_y and pen top that put the shared kanji on the original glyph boxes."""
    em_x, em_y = 38.0, 32.0
    for _ in range(4):
        sx, sy = [], []
        for ch, (x0, y0, x1, y1) in SHARED.items():
            a, b, c, d = ink_box(ch, em_x, stroke)
            sx.append((x1 - x0) / (b - a))
            sy.append((y1 - y0) / ((d - c) * em_y / em_x))
        em_x *= float(np.median(sx))
        em_y *= float(np.median(sy))
    pen_top = float(np.median([y0 - ink_box(ch, em_x, stroke)[2] * em_y / em_x for ch, (_x0, y0, _x1, _y1) in SHARED.items()]))
    return em_x, em_y, pen_top


def shared_ink(stroke: int) -> float:
    """Coverage of 中 and 集 rendered with this stroke, for comparison with the original ink."""
    em_x, em_y, pen_top = calibrate(stroke)
    total = 0.0
    for ch in ("中", "集"):
        font = ImageFont.truetype(str(FONT), round(em_x * SS))
        tall = round(80 * SS * em_x / em_y)
        layer = Image.new("L", (60 * SS, tall), 0)
        ImageDraw.Draw(layer).text((8 * SS, 4 * SS), ch, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
        small = np.asarray(layer.resize((60, 80), Image.BOX), np.float64) / 255.0
        total += float((np.clip((small - 0.5) * EDGE_GAIN + 0.5, 0, 1) * (small > 0)).sum())
    return total


def chinese_mask(text: str, stroke: int, calibration, edge_gain: float = EDGE_GAIN):
    em_x, em_y, pen_top = calibration
    font = ImageFont.truetype(str(FONT), round(em_x * SS))
    tall = round(H * SS * em_x / em_y)
    layer = Image.new("L", (W * SS, tall), 0)
    d = ImageDraw.Draw(layer)
    last = text[-1]
    probe = Image.new("L", (SS * 100, SS * 100), 0)
    ImageDraw.Draw(probe).text((0, 0), last, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    right_bearing_ink = np.where(np.asarray(probe).max(0) > 127)[0].max() + 1  # ink right, 1/SS px
    pen_last = RIGHT_INK - right_bearing_ink / SS
    pens = [pen_last - PITCH * (len(text) - 1 - i) for i in range(len(text))]
    y = pen_top * SS * em_x / em_y
    for ch, px in zip(text, pens):
        d.text((px * SS, y), ch, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    small = np.asarray(layer.resize((W, H), Image.BOX), np.float64) / 255.0
    small = np.clip((small - 0.5) * edge_gain + 0.5, 0, 1) * (small > 0)
    ink_cols = np.where(small.max(0) > 0.5)[0]
    first = int(ink_cols.min())
    mask = small.copy()
    mask[UNDERLINE_ROWS[0]:UNDERLINE_ROWS[1], first - UNDERLINE_LEAD:UNDERLINE_RIGHT] = 1.0
    layout = dict(em_px_xy=[round(em_x, 2), round(em_y, 2)], pen_top=round(pen_top, 2),
                  pens=[round(p, 2) for p in pens], ink_left=first, ink_right=int(ink_cols.max()) + 1,
                  underline=[first - UNDERLINE_LEAD, UNDERLINE_RIGHT - 1, *UNDERLINE_ROWS])
    return mask, layout


def main() -> None:
    assert sha256(FONT.read_bytes()) == FONT_LOCK["sha256"]
    texture = np.asarray(Image.open(JOB / "source.png").convert("RGBA")).copy()
    banner = texture[:H, :W, :3].astype(np.float64)
    alpha = texture[:H, :W, 3] > 0
    free = alpha.copy()
    free[FREE[0]:, FREE[1]:] = False
    free[:, UNDERLINE_RIGHT:] = False
    model, colour_fit = art_model(banner, free)
    art_mae = float(np.abs(model - banner)[free].mean())
    assert art_mae < 3.5, art_mae

    ja_mask = original_title_mask(banner, model)
    sel = alpha & ~ndimage.binary_dilation(ja_mask > 0, np.ones((3, 3)))
    sel[:FREE[0]] = False
    sel[:, :200] = False
    sel[:, UNDERLINE_RIGHT + 2:] = False
    glow_p, glow_c, glow_mae = fit_glow(banner, model, ja_mask, sel)
    assert glow_mae < 5.5, glow_mae

    # Validation: the fitted title layer on the rebuilt art against the real banner.
    ja_model = compose(model, ja_mask, glow_p, glow_c)
    title_zone = glow_alpha(ja_mask, glow_p) > 0.004
    title_zone |= ja_mask > 0
    title_mae = float(np.abs(ja_model - banner)[title_zone & alpha].mean())

    # Clean art: rebuilt pixels where the title layer reaches, original pixels elsewhere.
    zone = ndimage.binary_dilation(title_zone, np.ones((3, 3))) & alpha
    clean = banner.copy()
    clean[zone] = model[zone]
    clean_rgba = texture.copy()
    clean_rgba[:H, :W, :3] = np.clip(np.rint(clean), 0, 255).astype(np.uint8)
    Image.fromarray(clean_rgba).save(JOB / "clean.png")

    palette = banner_palette()
    original_ink = float(sum(ja_mask[y0:y1, x0:x1].sum() for ch, (x0, y0, x1, y1) in SHARED.items() if ch != "断"))
    stroke = min(range(0, 13), key=lambda st: abs(shared_ink(st) - original_ink))
    zh_mask, layout = chinese_mask("中断对话合集", stroke, calibrate(stroke))
    zh = compose(clean, zh_mask, glow_p, glow_c)
    zh_zone = (glow_alpha(zh_mask, glow_p) > 0.004) | (zh_mask > 0) | zone
    final = texture.copy()
    region = final[:H, :W, :3]
    q = quantize(np.clip(zh, 0, 255), palette)
    region[zh_zone & alpha] = q[zh_zone & alpha]
    Image.fromarray(final).save(JOB / "final-zh.png")
    palette_rgb = {tuple(c[:3]) for c in palette if c[3] == 255}
    assert all(tuple(p) in palette_rgb for p in final[:H, :W, :3][alpha])

    def show(rgb):
        bg = np.full((H, W, 3), 40.0)
        a = alpha[..., None]
        return np.where(a, np.clip(rgb, 0, 255), bg).astype(np.uint8)

    rows = [show(banner), show(ja_model), show(clean), show(final[:H, :W, :3])]
    gap = np.full((6, W, 3), 24, np.uint8)
    sheet = np.vstack([r for pair in zip(rows, [gap] * 4) for r in pair][:-1])
    Image.fromarray(sheet).resize((W * 2, sheet.shape[0] * 2), Image.NEAREST).save(JOB / "rebuild-check.png")

    report = dict(
        source=dict(archive="KURODATA/KVMDATA.BIN", tim2="raw @0x25C4C0 picture 0, 640x448 RGB24",
                    record_sha256=SOURCE_RECORD, also_in_original=True),
        banner=dict(target="AID_DATA/AIDDATA.BIN block 2 TIM2 1 picture 0, palette bank 0",
                    source_png_sha256=sha256((JOB / "source.png").read_bytes())),
        art=dict(affine_banner_to_source=AFFINE.astype(float).round(4).tolist(), source_blur_sigma=SOURCE_BLUR,
                 colour_fit_per_channel=colour_fit, mae_outside_title=round(art_mae, 2)),
        title_layer=dict(ink_rgb=INK.tolist(), glow_blur_sigma_xy=glow_p[:2], glow_gain=glow_p[2],
                         glow_max=glow_p[3], glow_rgb=glow_c.tolist(), glow_fit_mae=round(glow_mae, 2),
                         japanese_title_model_mae=round(title_mae, 2),
                         underline_rows=list(UNDERLINE_ROWS), underline_right_exclusive=UNDERLINE_RIGHT,
                         underline_lead=UNDERLINE_LEAD),
        chinese=dict(text="中断对话合集", confirmed="2026-09-17",
                     font=f"{FONT_LOCK['path']} (project font)", font_sha256=FONT_LOCK["sha256"],
                     pitch_px=PITCH, stroke_px=stroke / SS, edge_gain=EDGE_GAIN,
                     shared_ink_original=round(original_ink, 1), shared_ink_chinese=round(shared_ink(stroke), 1),
                     right_ink=RIGHT_INK, **layout),
        outputs=dict(clean_sha256=sha256((JOB / "clean.png").read_bytes()),
                     final_zh_sha256=sha256((JOB / "final-zh.png").read_bytes()),
                     final_zh_quantized_to="palette bank 0 opaque entries; alpha unchanged"),
    )
    (JOB / "rebuild.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
