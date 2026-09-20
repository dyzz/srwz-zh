"""Chinese titles for HSFC #110 and NISVDATA #128 on their locally painted plates.

Both SP titles are dark glyphs with a light yellow outline on a banner whose
rows are flat colours (local_paint.py restored them exactly):
  HSFC #110   シナリオチャート Special Disc -> 剧情流程 Special Disc
              (the English part keeps its original pixels, moved left)
  NISV #128   サウンドセレクト -> 音乐选择 (main-game wording, SP colours)

The fill and outline colours are taken from the Japanese title (dark fill,
2 px light outline, faint outer glow); the Chinese glyphs use the project font
and are quantized to each picture's palette.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import retitle_banners35 as rt  # noqa: E402
from rebuild_banner1 import quantize  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from srwz.tim2 import parse_tim2  # noqa: E402
from srwz.tim2_writeback import _csm1_palette_offset  # noqa: E402

TD = ROOT / "work/analysis/sp-texture-diff-20260912"
SS = 8
JOBS = {
    "hsfc-chart-title-sp": dict(change=110, ja="シナリオチャート", zh="剧情流程", keep_suffix=True, ink_height=None),
    # main game draws 音乐选择 at 26 pt; 24 px ink matches that and the bold kana
    "nisv-sound-select-title": dict(change=128, ja="サウンドセレクト", zh="音乐选择", keep_suffix=False, ink_height=24),
}


def outline_style(clean, fill, fill_rgb, line_rgb, radius=2):
    """Dark glyph, light outline of `radius` px and a faint outer glow in the outline colour."""
    disk = np.hypot(*np.mgrid[-radius:radius + 1, -radius:radius + 1]) <= radius + 0.25
    grown = ndimage.maximum_filter(fill, footprint=disk)
    outline = np.clip(grown - fill, 0, 1)[..., None]
    glow = (0.35 * cv2.GaussianBlur(grown.astype(np.float32), (0, 0), 1.5) * (1 - grown))[..., None]
    out = clean * (1 - glow) + line_rgb * glow
    out = out * (1 - outline) + line_rgb * outline
    return out * (1 - fill[..., None]) + fill_rgb * fill[..., None]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def palette_of(change: int) -> np.ndarray:
    sp = json.loads((TD / "comparison.json").read_text())["changes"][change]["sp"]
    rec = (TD / "tim2" / f"{sp['record_sha256']}.tm2").read_bytes()
    q = parse_tim2(rec).pictures[sp["picture"]]
    a = q.offset + q.header_size + q.image_size
    pal = rec[a:a + q.clut_size][:1024]
    return np.array([[*pal[_csm1_palette_offset(n) * 4:][:3], min(255, pal[_csm1_palette_offset(n) * 4 + 3] * 2)]
                     for n in range(256)], np.int32)


def render_line(text, em, stroke):
    font = ImageFont.truetype(str(rt.FONT), round(em * SS))
    probe = Image.new("L", (round(em * SS * (len(text) + 2)), round(em * SS * 2)), 0)
    ImageDraw.Draw(probe).text((SS * 4, SS * 4), text, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    a = np.asarray(probe)
    ys, xs = np.where(a > 127)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def paste(canvas_shape, glyphs, x0, top):
    h, w = canvas_shape
    big = Image.new("L", (w * SS, h * SS), 0)
    big.paste(Image.fromarray(glyphs), (round(x0 * SS), round(top * SS)))
    return np.asarray(big.resize((w, h), Image.BOX), np.float32) / 255.0


def main() -> None:
    manifest = json.loads((OUT / "manifest.json").read_text())
    report = {}
    for slug, meta in JOBS.items():
        job = OUT / "jobs" / slug
        source = np.asarray(Image.open(job / "source.png").convert("RGBA")).copy()
        painted = np.asarray(Image.open(job / "clean.png").convert("RGBA"))
        H, W = source.shape[:2]
        orig = source[..., :3].astype(np.float64)
        clean = painted[..., :3].astype(np.float64)
        alpha = source[..., 3] > 0
        x0, y0, x1, y1 = [j for j in manifest["jobs"] if j["slug"] == slug][0]["mask_boxes"][0]
        zone = np.zeros((H, W), bool)
        zone[y0:y1, x0:x1] = True
        # The fill is a dark hue close to the banner's brightness: separate it by colour distance.
        light = (orig.mean(-1) - clean.mean(-1) > 40) & zone
        dark = (np.abs(orig - clean).max(-1) > 30) & ~ndimage.binary_dilation(light) & zone
        cols = (dark | light).any(0)
        xs = np.where(cols)[0]
        # the widest gap splits the Japanese title from "Special Disc"
        gaps, x = [], xs[0]
        while x <= xs[-1]:
            if not cols[x]:
                s = x
                while not cols[x]:
                    x += 1
                gaps.append((x - s, s, x))
            x += 1
        title_end = xs[-1] + 1
        suffix = None
        if meta["keep_suffix"]:
            gap = max(gaps)
            title_end = gap[1]
            suffix = (gap[2], xs[-1] + 1, gap[0])
        title = zone.copy()
        title[:, title_end:] = False
        fill_ja = cv2.GaussianBlur((dark & title).astype(np.float32), (0, 0), 0.5).astype(np.float64)
        core = ndimage.binary_erosion(dark & title)
        fill_rgb = np.median(orig[core if core.sum() > 20 else dark & title], axis=0)
        bright = light & title
        line_rgb = np.median(orig[bright & (orig.mean(-1) >= np.percentile(orig[bright].mean(-1), 60))], axis=0)
        ink_rows = np.where((dark & title).any(1))[0]
        ink_cols = np.where((dark & title).any(0))[0]
        # Chinese line: ink height of the kana bodies, starting where the Japanese title started.
        height = meta["ink_height"] or (ink_rows.max() + 1 - ink_rows.min())
        top = (ink_rows.min() + ink_rows.max() + 1) / 2 - height / 2
        em = height / 0.9
        glyphs = render_line(meta["zh"], em, 3)
        scale = height / (glyphs.shape[0] / SS)
        glyphs = np.asarray(Image.fromarray(glyphs).resize((round(glyphs.shape[1] * scale), round(glyphs.shape[0] * scale)), Image.LANCZOS))
        zh_w = glyphs.shape[1] / SS
        if meta["keep_suffix"]:
            start = float(ink_cols.min())
        else:
            start = (ink_cols.min() + ink_cols.max() + 1) / 2 - zh_w / 2
        zh_mask = paste((H, W), glyphs, start, float(top))
        zh_fill = cv2.GaussianBlur((zh_mask > 0.5).astype(np.float32), (0, 0), 0.5).astype(np.float64)
        styled = np.clip(outline_style(clean, zh_fill, fill_rgb, line_rgb), 0, 255)
        out = clean.copy()
        reach = ndimage.binary_dilation(zh_fill > 0.01, np.ones((9, 9))) & zone & alpha
        out[reach] = styled[reach]
        suffix_report = None
        if suffix is not None:
            s0, s1, gap_w = suffix
            new_s0 = int(round(start + zh_w + gap_w))
            width = s1 - s0 + 4
            src = orig[y0:y1, s0 - 2:s0 - 2 + width]
            out[y0:y1, new_s0 - 2:new_s0 - 2 + width] = src
            suffix_report = dict(from_x=int(s0), to_x=new_s0, width=int(s1 - s0))
        palette = palette_of(meta["change"])
        final = source.copy()
        final[..., :3][alpha] = quantize(out[alpha].reshape(-1, 1, 3), palette).reshape(-1, 3)
        # pixels outside the box keep their original values exactly
        final[..., :3][~zone] = source[..., :3][~zone]
        assert (final[..., 3] == source[..., 3]).all()
        opaque = {tuple(c[:3]) for c in palette if c[3] == 255}
        assert all(tuple(p) in opaque for p in final[..., :3][zone & alpha])
        Image.fromarray(final).save(job / "final-zh.png")
        pad = 4
        crop = (slice(max(0, y0 - pad), min(H, y1 + pad)), slice(0, min(W, x1 + 40)))
        for name, img in (("preview-ja.png", source), ("preview-zh.png", final)):
            part = img[crop]
            bg = np.full(part.shape[:2] + (3,), 40, np.uint8)
            vis = np.where(part[..., 3:4] > 0, part[..., :3], bg)
            Image.fromarray(vis).resize((vis.shape[1] * 2, vis.shape[0] * 2), Image.NEAREST).save(job / name)
        report[slug] = dict(ja=meta["ja"], zh=meta["zh"],
                            fill_rgb=np.round(fill_rgb, 1).tolist(), outline_rgb=np.round(line_rgb, 1).tolist(),
                            outline_px=2, font=rt.FONT_LOCK["path"],
                            ink_height=int(height), start_x=round(start, 2), suffix=suffix_report,
                            final_sha256=sha256((job / "final-zh.png").read_bytes()))
        (job / "rebuild.json").write_text(json.dumps(report[slug], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
