"""Fit the user's AI-cleaned heading plate and preview the five Chinese headings.

Input: the plate the user cleaned with AI (2172x724 RGBA, transparent outside).
Outputs in jobs/heading-plate/:
  ai-original.png         byte copy of the user's file (provenance)
  clean.png               512x64 plate at the original position, hole-free original alpha
  trial-zh.png            original Japanese headings vs Chinese trial (RGBA preview)
  trial-zh-palette.png    same trial quantized to each heading's own 256-colour palette
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production  # noqa: E402
from srwz.tim2 import parse_tim2  # noqa: E402

AI_SOURCE = OUT / "inputs/heading-plate.png"
JOB = OUT / "jobs" / "heading-plate"
FONT = ROOT / "work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf"
SD = ROOT / "work/disc/special-disc"
TD = ROOT / "work/analysis/sp-texture-diff-20260912"
AID = ROOT / "work/analysis/sp-aiddata-images-20260912"
PLATE_BOX = (4, 5, 420, 52)  # original plate, x0 y0 x1 y1

HEADINGS = [
    # (label, Japanese, proposed Chinese, preview png, palette source)
    ("VT1 #173", "エクストラステージ", "额外关卡", 173, ("vt1", 36)),
    ("VT1 #175", "ストーリーモード", "剧情模式", 175, ("vt1", 38)),
    ("VT1 #180", "チャレンジバトル", "挑战模式", 180, ("vt1", 45)),
    ("VT1 #187", "バトルビューワー", "战斗鉴赏", 187, ("vt1", 57)),
    ("AIDDATA 块2", "スペシャルシアター", "特别剧场", None, ("aid", 2)),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plate_alpha() -> np.ndarray:
    """Union of the five originals' shapes with pin-holes filled (they are identical)."""
    changes = json.loads((TD / "comparison.json").read_text())["changes"]
    paths = [TD / changes[i]["sp_preview"]["file"] for _, _, _, i, _ in HEADINGS if i is not None]
    paths.append(AID / "images/block-002-tim2-02-picture-00.png")
    shapes = [ndimage.binary_fill_holes(np.asarray(Image.open(p).convert("RGBA"))[..., 3] > 0) for p in paths]
    if not all((s == shapes[0]).all() for s in shapes):
        raise SystemExit("heading plate shapes differ")
    return shapes[0]


def fit_plate(alpha_shape: np.ndarray) -> Image.Image:
    ai = np.asarray(Image.open(JOB / "ai-original.png").convert("RGBA")).astype(np.float64)
    ys, xs = np.where(ai[..., 3] > 128)
    crop = ai[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
    crop[..., :3] *= crop[..., 3:4] / 255.0  # premultiply before resampling
    w, h = PLATE_BOX[2] - PLATE_BOX[0], PLATE_BOX[3] - PLATE_BOX[1]
    chans = [np.asarray(Image.fromarray(crop[..., c].astype(np.float32), mode="F").resize((w, h), Image.LANCZOS))
             for c in range(4)]
    small = np.stack(chans, axis=-1)
    a = np.clip(small[..., 3], 1e-6, 255)
    rgb = np.clip(small[..., :3] * 255.0 / a[..., None], 0, 255)
    canvas = np.zeros((64, 512, 4), np.uint8)
    canvas[PLATE_BOX[1]:PLATE_BOX[3], PLATE_BOX[0]:PLATE_BOX[2], :3] = rgb.round().astype(np.uint8)
    canvas[..., 3] = np.where(alpha_shape, 255, 0)
    canvas[~alpha_shape, :3] = 0
    return Image.fromarray(canvas)


def draw_title(plate: Image.Image, text: str, tracking_px: int = 3, centered: bool = False) -> Image.Image:
    """Light warm-grey glyphs, dark 1-2 px rim and a soft lower-right shadow, left aligned at x=61."""
    scale = 4
    font = ImageFont.truetype(str(FONT), 33 * scale)
    layer = Image.new("RGBA", (512 * scale, 64 * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, top = 61 * scale, 12 * scale
    bbox = d.textbbox((0, 0), text, font=font)
    y = top - bbox[1]
    tracking = tracking_px * scale
    if centered:
        # Centre the whole run (glyph advances plus gaps) on the plate.
        width = sum(d.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)
        x = (PLATE_BOX[0] + PLATE_BOX[2]) / 2 * scale - width / 2
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow)
    cx = x
    for ch in text:
        ds.text((cx + 2 * scale, y + 2 * scale), ch, font=font, fill=(20, 20, 20, 150),
                stroke_width=int(1.5 * scale), stroke_fill=(20, 20, 20, 150))
        d.text((cx, y), ch, font=font, fill=(222, 218, 216, 255),
               stroke_width=int(1.5 * scale), stroke_fill=(38, 38, 38, 255))
        cx += d.textlength(ch, font=font) + tracking
    shadow = shadow.filter(ImageFilter.GaussianBlur(1.5 * scale))
    shadow.alpha_composite(layer)
    small = shadow.resize((512, 64), Image.LANCZOS)
    out = plate.copy()
    out.alpha_composite(small)
    # Keep the plate's silhouette.
    out.putalpha(plate.split()[3])
    return out


def palette_of(source) -> np.ndarray:
    kind, index = source
    if kind == "vt1":
        exe = (SD / "SLPS_259.20").read_bytes()
        data = (SD / "DATA/VT1.BIN").read_bytes()
        pos, offs = 0x353790, []
        while True:
            v = struct.unpack_from("<I", exe, pos)[0]
            offs.append(v)
            pos += 4
            if v == len(data):
                break
        decoded = decode_production(data[offs[index]:offs[index + 1]]).output
        tim = parse_tim2(decoded)
        base = 0
    else:
        tim_bytes = (AID / "tim2/block-002-tim2-02.tm2").read_bytes()
        tim, decoded, base = parse_tim2(tim_bytes), tim_bytes, 0
    q = tim.pictures[0]
    a = base + q.offset + q.header_size + q.image_size
    pal = decoded[a:a + q.clut_size]
    colours = np.frombuffer(pal, np.uint8).reshape(-1, 4).astype(np.int32)
    colours[:, 3] = np.minimum(255, colours[:, 3] * 2)
    return colours


def quantize(im: Image.Image, palette: np.ndarray) -> Image.Image:
    arr = np.asarray(im).astype(np.int32)
    flat = arr.reshape(-1, 4)
    opaque = palette[palette[:, 3] >= 128]
    out = np.zeros_like(flat)
    idx = flat[:, 3] >= 128
    px = flat[idx][:, :3]
    best = np.empty(len(px), np.int64)
    for start in range(0, len(px), 4096):
        chunk = px[start:start + 4096]
        dist = ((chunk[:, None, :] - opaque[None, :, :3]) ** 2).sum(-1)
        best[start:start + 4096] = dist.argmin(1)
    out[idx] = opaque[best]
    return Image.fromarray(out.reshape(arr.shape).astype(np.uint8))


def main() -> None:
    target = JOB / "ai-original.png"
    if not target.exists() or sha256(target) != sha256(AI_SOURCE):
        shutil.copyfile(AI_SOURCE, target)
    shape = plate_alpha()
    plate = fit_plate(shape)
    plate.save(JOB / "clean.png")

    changes = json.loads((TD / "comparison.json").read_text())["changes"]
    rows_rgba, rows_pal = [], []
    for label, ja, zh, idx, pal_src in HEADINGS:
        original = Image.open(TD / changes[idx]["sp_preview"]["file"] if idx is not None
                              else AID / "images/block-002-tim2-02-picture-00.png").convert("RGBA")
        trial = draw_title(plate, zh)
        rows_rgba.append((label, ja, zh, original, trial))
        rows_pal.append((label, ja, zh, original, quantize(trial, palette_of(pal_src))))

    def sheet(rows, path):
        crop = (0, 0, 428, 58)
        s = 2
        w, h = 428 * s, 58 * s
        canvas = Image.new("RGBA", (w * 2 + 12, (h + 6) * len(rows)), (24, 26, 30, 255))
        for k, (_label, _ja, _zh, a, b) in enumerate(rows):
            for col, im in enumerate((a, b)):
                bg = Image.new("RGBA", im.size, (24, 26, 30, 255))
                bg.alpha_composite(im)
                canvas.paste(bg.crop(crop).resize((w, h), Image.LANCZOS), (col * (w + 12), k * (h + 6)))
        canvas.save(path)

    sheet(rows_rgba, JOB / "trial-zh.png")
    sheet(rows_pal, JOB / "trial-zh-palette.png")
    # Variant: wider letter spacing so four characters span more of the plate.
    spaced = [(label, ja, zh, original, quantize(draw_title(plate, zh, tracking_px=16), palette_of(pal_src)))
              for (label, ja, zh, original, _t), (_l, _j, _z, _i, pal_src) in zip(rows_rgba, HEADINGS)]
    sheet(spaced, JOB / "trial-zh-spaced-palette.png")
    # User choice 2026-09-17: wider spacing, centred on the plate.
    centred = []
    for (label, ja, zh, original, _t), (_l, _j, _z, _i, pal_src) in zip(rows_rgba, HEADINGS):
        final = quantize(draw_title(plate, zh, tracking_px=16, centered=True), palette_of(pal_src))
        final.save(JOB / f"final-{_l.replace(' ', '-').replace('#', '')}.png")
        centred.append((label, ja, zh, original, final))
    sheet(centred, JOB / "trial-zh-centred-palette.png")
    for label, ja, zh, _a, b in rows_rgba:
        print(label, ja, "->", zh)
    print("ai-original sha256", sha256(target))


if __name__ == "__main__":
    main()
