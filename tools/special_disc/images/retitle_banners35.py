"""Chinese titles for Special Theatre banners 3 and 5 on their locally painted plates.

Banner 3 (設定資料集 -> 设定资料集): black glyphs, cream glow, soft shadow.
Banner 5 (壁紙一覧 -> 壁纸一览): white glyphs, dark violet shadow.
Both titles keep their character count, so every Chinese glyph takes the
cell of the Japanese glyph it replaces; the underline is already in the
painted plate (jobs/aid-banner-<k>/clean.png, local_paint.py).

The title style (shadow offset/blur/colour, glow, fill colour) is fitted on
the original banner over its painted plate. Font: the project font, sized
on the characters both titles share (weight 3/4 px, chosen by eye), then quantized to the
banner's palette bank.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage, optimize

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_ai_banners import palette_bank  # noqa: E402
from rebuild_banner1 import quantize  # noqa: E402

FONT_LOCK = json.loads((ROOT / "config/fonts/harmonyos-sans-sc.lock.json").read_text())["font"]
FONT = ROOT / FONT_LOCK["path"]
W, H = 620, 78
SS = 8
BANNERS = {
    3: dict(ja="設定資料集", zh="设定资料集", dark_text=True, shared={1: "定", 3: "料", 4: "集"}),
    5: dict(ja="壁紙一覧", zh="壁纸一览", dark_text=False, shared={0: "壁"}),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def glyph_mask(banner, clean, box, dark_text):
    lum_b, lum_c = banner.mean(-1), clean.mean(-1)
    diff = (lum_c - lum_b) if dark_text else (lum_b - lum_c)
    zone = np.zeros((H, W), bool)
    zone[box[1]:box[3], box[0]:box[2]] = True
    # Dark titles also carry a dark shadow; only the solid fill counts as glyph.
    mask = (diff > (110 if dark_text else 60)) & zone
    lab, n = ndimage.label(mask, np.ones((3, 3)))
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    return np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= 4])


def glyph_cells(mask, count):
    """Split the title into `count` glyph cells by the widest column gaps."""
    cols = mask.any(0)
    xs = np.where(cols)[0]
    gaps = []
    x = xs[0]
    while x <= xs[-1]:
        if not cols[x]:
            start = x
            while not cols[x]:
                x += 1
            gaps.append((x - start, start, x))
        x += 1
    cuts = sorted(sorted(gaps, reverse=True)[:count - 1], key=lambda g: g[1])
    edges = [xs[0]] + [g for c in cuts for g in (c[1], c[2])] + [xs[-1] + 1]
    cells = []
    for i in range(count):
        x0, x1 = edges[2 * i], edges[2 * i + 1]
        ys = np.where(mask[:, x0:x1].any(1))[0]
        cells.append((int(x0), int(ys.min()), int(x1), int(ys.max()) + 1))
    return cells


def shift(img, dy, dx):
    return np.roll(np.roll(img, dy, 0), dx, 1)


def compose(clean, fill, p, offset):
    fill_rgb, g_sx, g_sy, g_gain, g_max, g_rgb, s_sigma, s_op, s_rgb = (
        p[0:3], p[3], p[4], p[5], p[6], p[7:10], p[10], p[11], p[12:15])
    shadow = cv2.GaussianBlur(shift(fill, *offset), (0, 0), max(s_sigma, 0.3))
    a_s = np.clip(s_op * shadow, 0, 1)[..., None]
    out = clean * (1 - a_s) + s_rgb * a_s
    glow = cv2.GaussianBlur(fill, (0, 0), sigmaX=max(g_sx, 0.3), sigmaY=max(g_sy, 0.3))
    a_g = np.clip(g_gain * glow, 0, g_max)[..., None]
    out = out * (1 - a_g) + g_rgb * a_g
    a_f = fill[..., None]
    return out * (1 - a_f) + fill_rgb * a_f


def fit_style(banner, clean, fill, region):
    lo = [0, 0, 0, 0.5, 0.5, 0, 0, 0, 0, 0, 0.3, 0, 0, 0, 0]
    hi = [255, 255, 255, 8, 8, 10, 1, 255, 255, 255, 4, 3, 255, 255, 255]
    best = None
    for offset in ((0, 0), (1, 1), (2, 1), (2, 2), (1, 2), (3, 2), (2, 0), (3, 1)):
        def residual(p):
            return (compose(clean, fill, p, offset) - banner)[region].ravel()
        start = [128, 128, 128, 2, 2, 1, 0.5, 128, 128, 128, 1.5, 0.8, 128, 128, 128]
        fit = optimize.least_squares(residual, start, bounds=(lo, hi), loss="soft_l1", f_scale=20, max_nfev=300)
        mae = float(np.abs(residual(fit.x)).mean())
        if best is None or mae < best[2]:
            best = (fit.x, offset, mae)
    return best


def render_glyph(ch, em_x, em_y, stroke):
    font = ImageFont.truetype(str(FONT), round(em_x * SS))
    size = round(em_x * SS * 2)
    layer = Image.new("L", (size, size), 0)
    ImageDraw.Draw(layer).text((SS * 4, SS * 4), ch, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    a = np.asarray(layer)
    ys, xs = np.where(a > 127)
    crop = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    # squash vertically by em_y/em_x, then down to banner pixels
    h = max(1, round(crop.shape[0] * em_y / em_x))
    squashed = np.asarray(Image.fromarray(crop).resize((crop.shape[1], h), Image.BOX))
    return squashed


def place(mask, glyph, cx, top):
    """Put a supersampled glyph (SS px per banner px) centred on cx with its ink starting at `top`."""
    small_w = glyph.shape[1] / SS
    x0 = cx - small_w / 2
    canvas = Image.new("L", (W * SS, H * SS), 0)
    canvas.paste(Image.fromarray(glyph), (round(x0 * SS), round(top * SS)))
    return np.maximum(mask, np.asarray(canvas.resize((W, H), Image.BOX), np.float32) / 255.0)


def calibrate(cells, shared, stroke):
    """em sizes that reproduce the shared glyphs' cell size."""
    sx, sy = [], []
    for i, ch in shared.items():
        x0, y0, x1, y1 = cells[i]
        g = render_glyph(ch, 40.0, 40.0, stroke)
        sx.append((x1 - x0) / (g.shape[1] / SS) * 40.0)
        sy.append((y1 - y0) / (g.shape[0] / SS) * 40.0)
    return float(np.median(sx)), float(np.median(sy))


def main() -> None:
    assert sha256(FONT.read_bytes()) == FONT_LOCK["sha256"]
    manifest = json.loads((OUT / "manifest.json").read_text())
    report = {}
    for k, meta in BANNERS.items():
        job = OUT / "jobs" / f"aid-banner-{k}"
        texture = np.asarray(Image.open(job / "source.png").convert("RGBA")).copy()
        banner = texture[:H, :W, :3].astype(np.float64)
        alpha = texture[:H, :W, 3] > 0
        clean = np.asarray(Image.open(job / "clean.png").convert("RGBA"))[:H, :W, :3].astype(np.float64)
        box = [j for j in manifest["jobs"] if j["slug"] == f"aid-banner-{k}"][0]["mask_boxes"][0]
        ja = glyph_mask(banner, clean, box, meta["dark_text"])
        cells = glyph_cells(ja, len(meta["ja"]))
        fill_ja = cv2.GaussianBlur(ja.astype(np.float32), (0, 0), 0.5).astype(np.float64)
        region = np.zeros((H, W), bool)
        region[box[1]:box[3], box[0]:box[2]] = True
        region &= alpha
        params, offset, mae = fit_style(banner, clean, fill_ja, region)
        # 3/4 px outline: matching the ink area exactly closes the counters of 资/览/壁, so the
        # weight was chosen by eye from 1/2, 3/4 and 1 px (2026-09-17).
        stroke = 6
        best = (0, stroke, calibrate(cells, meta["shared"], stroke))
        _, stroke, em = best
        top = int(np.median([c[1] for i, c in enumerate(cells) if i in meta["shared"]]))
        bottom = int(np.median([c[3] for i, c in enumerate(cells) if i in meta["shared"]]))
        zh_mask = np.zeros((H, W), np.float32)
        for (x0, y0, x1, y1), ch in zip(cells, meta["zh"]):
            g = render_glyph(ch, em[0], em[1], stroke)
            h = g.shape[0] / SS
            glyph_top = top + ((bottom - top) - h) / 2 if ch != "一" else y0 + (y1 - y0 - h) / 2
            zh_mask = place(zh_mask, g, (x0 + x1) / 2, glyph_top)
        zh_fill = cv2.GaussianBlur((zh_mask > 0.5).astype(np.float32), (0, 0), 0.5).astype(np.float64)
        styled = np.clip(compose(clean, zh_fill, params, offset), 0, 255)
        palette = palette_bank(k - 1)
        q = quantize(styled, palette)
        final = texture.copy()
        reach = ndimage.binary_dilation((zh_fill > 0.01) | ja, np.ones((15, 15))) & region
        final[:H, :W, :3][reach] = q[reach]
        # outside the title reach the painted plate itself (already palette colours)
        painted = np.asarray(Image.open(job / "clean.png").convert("RGBA"))
        keep_clean = region & ~reach
        final[:H, :W, :3][keep_clean] = painted[:H, :W, :3][keep_clean]
        assert (final[..., 3] == texture[..., 3]).all()
        opaque = {tuple(c[:3]) for c in palette if c[3] == 255}
        final[:H, :W, :3][alpha] = quantize(final[:H, :W, :3][alpha].reshape(-1, 1, 3), palette).reshape(-1, 3)
        assert all(tuple(p) in opaque for p in final[:H, :W, :3][alpha])
        Image.fromarray(final).save(job / "final-zh.png")
        check = compose(clean, fill_ja, params, offset)
        for name, img in (("preview-ja.png", texture[:H, :W, :3]), ("preview-zh.png", final[:H, :W, :3]),
                          ("style-check.png", np.clip(check, 0, 255).astype(np.uint8))):
            bg = np.full((H, W, 3), 40, np.uint8)
            vis = np.where(alpha[..., None], img, bg).astype(np.uint8)
            Image.fromarray(vis).resize((W * 2, H * 2), Image.NEAREST).save(job / name)
        report[k] = dict(ja=meta["ja"], zh=meta["zh"], cells=cells, style_fit_mae=round(mae, 2),
                         shadow_offset=list(offset), style=[round(float(v), 3) for v in params],
                         font=FONT_LOCK["path"], em_px_xy=[round(em[0], 2), round(em[1], 2)], stroke_px=stroke / SS,
                         palette_bank=k - 1, final_sha256=sha256((job / "final-zh.png").read_bytes()))
        (job / "rebuild.json").write_text(json.dumps(report[k], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
