"""Paint out the Japanese text on the four simple-background SP images.

The user confirmed on 2026-09-17 that these four do not need AI:
  hsfc-chart-title-sp      banner rows are flat colours
  nisv-sound-select-title  banner rows are flat; only non-banner pixels are replaced
  aid-banner-3             paper background; underline continues on both sides
  aid-banner-5             dark background; the underline starts inside the text box

Writes jobs/<slug>/clean.png, before-after.png and diff.png for review.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
JOBS = OUT / "jobs"


def load(slug: str) -> Image.Image:
    return Image.open(JOBS / slug / "source.png").convert("RGBA")


def box_of(slug: str) -> tuple[int, int, int, int]:
    manifest = json.loads((OUT / "manifest.json").read_text())
    for job in manifest["jobs"]:
        if job["slug"] == slug:
            return tuple(job["mask_boxes"][0])
    raise KeyError(slug)


def row_median(px, xs, y):
    samples = [px[x, y] for x in xs]
    return tuple(int(median(channel)) for channel in zip(*samples))


def lerp(a, b, t):
    return tuple(round(p + (q - p) * t) for p, q in zip(a, b))


def paint_row_flat(slug: str, sample_x: int) -> Image.Image:
    """Rows inside the banner are single colours: copy the row colour across the box."""
    im = load(slug)
    px = im.load()
    x0, y0, x1, y1 = box_of(slug)
    for y in range(y0, y1):
        colour = px[sample_x, y]
        for x in range(x0, x1):
            px[x, y] = colour
    return im


def paint_non_palette(slug: str, sample_x: int, palette_region) -> Image.Image:
    """Flat-fill the banner body; near the slanted right end keep banner-coloured pixels.

    Text anti-aliasing reuses some border colours, so inside the flat body every
    pixel is reset to the row colour. Only the last few pixels before the edge
    highlight (203, 89, 1) keep the palette rule.
    """
    im = load(slug)
    px = im.load()
    x0, y0, x1, y1 = box_of(slug)
    palette = set()
    for (rx0, ry0, rx1, ry1) in palette_region:
        for y in range(ry0, ry1):
            for x in range(rx0, rx1):
                if px[x, y][3] > 16:
                    palette.add(px[x, y])
    for y in range(y0, y1):
        colour = px[sample_x, y]
        edges = [x for x in range(150, 227) if px[x, y] == (203, 89, 1, 255)]
        flat_until = (max(edges) - 4) if edges else x1
        for x in range(x0, x1):
            if x < flat_until or px[x, y] not in palette:
                px[x, y] = colour
    return im


def paint_interpolated(slug: str, left_xs, right_xs, *, band=None, vertical: int = 0) -> Image.Image:
    """Row-wise interpolation between clean samples on both sides of the box.

    band = (y_from, y_to, x_from, x_to, sample_xs) fills an underline that starts
    inside the box with the clean underline colour of each row.
    """
    im = load(slug)
    px = im.load()
    x0, y0, x1, y1 = box_of(slug)
    src = load(slug).load()
    top_of_band = band[0] if band else y1
    for y in range(y0, y1):
        if vertical and y < top_of_band:
            rows = range(max(y0, y - vertical), min(top_of_band, y + vertical + 1))
            left = tuple(int(median(c)) for c in zip(*[src[x, r] for r in rows for x in left_xs]))
            right = tuple(int(median(c)) for c in zip(*[src[x, r] for r in rows for x in right_xs]))
        else:
            left = row_median(src, left_xs, y)
            right = row_median(src, right_xs, y)
        underline = None
        if band and band[0] <= y < band[1]:
            underline = row_median(src, band[4], y)
        for x in range(x0, x1):
            if underline is not None:
                # Glyphs only reach the underline rows inside the underline span;
                # keep the original pixels (including the shadow tail) elsewhere.
                if band[2] <= x < band[3]:
                    px[x, y] = underline
            else:
                px[x, y] = lerp(left, right, (x - x0 + 1) / (x1 - x0 + 1))
    return im


def save(slug: str, clean: Image.Image) -> None:
    folder = JOBS / slug
    clean.save(folder / "clean.png")
    src = load(slug)
    x0, y0, x1, y1 = box_of(slug)
    pad = 12
    crop = (max(0, x0 - pad * 4), max(0, y0 - pad), min(src.width, x1 + pad * 4), min(src.height, y1 + pad))
    a = src.crop(crop)
    b = clean.crop(crop)
    scale = 2
    w, h = a.width * scale, a.height * scale
    sheet = Image.new("RGBA", (w, h * 2 + 6), (30, 32, 38, 255))
    for k, part in enumerate((a, b)):
        bg = Image.new("RGBA", part.size, (46, 50, 58, 255))
        bg.alpha_composite(part)
        sheet.paste(bg.resize((w, h), Image.NEAREST), (0, k * (h + 6)))
    sheet.save(folder / "before-after.png")
    diff = ImageChops.difference(src, clean).convert("L").point(lambda v: 255 if v else 0)
    diff.save(folder / "diff.png")
    outside = ImageChops.difference(src, clean).crop((0, 0, src.width, src.height))
    changed = [(x, y) for y in range(src.height) for x in range(src.width)
               if outside.getpixel((x, y)) != (0, 0, 0, 0) and not (x0 <= x < x1 and y0 <= y < y1)]
    if changed:
        raise SystemExit(f"{slug}: pixels outside the box changed: {changed[:5]}")


save("hsfc-chart-title-sp", paint_row_flat("hsfc-chart-title-sp", sample_x=6))
save("nisv-sound-select-title", paint_non_palette(
    "nisv-sound-select-title", sample_x=4,
    palette_region=[(0, 0, 14, 41), (208, 0, 227, 41)]))
save("aid-banner-3", paint_interpolated(
    "aid-banner-3", left_xs=range(342, 351), right_xs=range(571, 581)))
save("aid-banner-5", paint_interpolated(
    "aid-banner-5", left_xs=range(344, 353), right_xs=range(607, 613),
    band=(63, 74, 360, 600, range(566, 597)), vertical=4))
print("painted 4 images")
