"""Indexed text cells for KVMDATA UI pages (4-bpp, grayscale CLUT: index = gray / 17).

The Simplified cells were drawn with ImageMagick and HarmonyOS Sans SC: a gray stroke under a white fill,
supersampled, optionally row-sheared. ``render`` reproduces that; ``fit`` finds the parameters that best
reproduce an existing Simplified cell (its text known), so the Traditional cell can be drawn the same way.
"""
from __future__ import annotations

import itertools
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.imagemagick import render_grayscale_text_mask, require_imagemagick  # noqa: E402

FONT = ROOT / 'work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf'


@lru_cache(maxsize=None)
def _exe():
    return require_imagemagick()


@lru_cache(maxsize=4096)
def render(text: str, width: int, height: int, point_size: int, stroke_gray: int, stroke_width: float,
           fill_stroke_width: float, shear: float = 0, dx: int = 0, dy: int = 0, spacing: float = 0,
           rotate: int = 0, mode: str = 'roles') -> bytes:
    """Indices (0-15) of one cell.

    mode 'roles' (heading/title cells: 0 transparent, 1-7 outline, 8-15 fill): a fill mask (white, thickened by
    fill_stroke_width) gives 8-15, the stroke ring outside it gives 1-7 scaled by stroke_gray/255*20.
    mode 'gray': one gray-stroke-under-white mask, index = gray / 17.
    ``rotate`` 90/270 draws into a height x width canvas and turns it (vertical labels)."""
    w, h = (height, width) if rotate else (width, height)
    common = dict(width=w, height=h, point_size=point_size, italic_shear_degrees=shear, character_spacing=spacing,
                  supersample_factor=4, horizontal_offset=dx, vertical_offset=dy)
    if mode == 'gray':
        mask = render_grayscale_text_mask(_exe(), FONT, text, stroke_gray=f'gray({stroke_gray})',
                                          stroke_width=stroke_width, fill_stroke_width=fill_stroke_width, **common)
        idx = bytes(min(15, (v + 8) // 17) for v in mask)
    else:
        fill = render_grayscale_text_mask(_exe(), FONT, text, stroke_gray='black', stroke_width=0,
                                          fill_stroke_width=fill_stroke_width, **common)
        ring = render_grayscale_text_mask(_exe(), FONT, text, stroke_gray='white', stroke_width=stroke_width,
                                          fill_stroke_width=fill_stroke_width, **common)
        scale = stroke_gray * 20 / 255
        idx = bytes(min(15, 8 + round(f * 7 / 255)) if f else (max(1, min(7, round(o * scale / 255))) if o else 0)
                    for f, o in zip(fill, ring))
    if rotate == 90:                                   # clockwise: new[y][x] = old[h-1-x][y]
        idx = bytes(idx[(h - 1 - x) * w + y] for y in range(w) for x in range(h))
    elif rotate == 270:
        idx = bytes(idx[x * w + (w - 1 - y)] for y in range(w) for x in range(h))
    return idx


def score(a: bytes, b: bytes) -> float:
    return sum(x == y for x, y in zip(a, b)) / len(a)


def fit(text: str, target: bytes, width: int, height: int, *, sizes=None, rotate=0, shears=(0, 12),
        start: dict | None = None, mode: str = 'roles') -> tuple[float, dict]:
    """Coordinate search for the render parameters that best reproduce ``target``."""
    if sizes is None:
        sizes = range(max(8, min(width, height) - 8), min(width, height) + 4)
    best = dict(point_size=start.get('point_size', sizes[len(sizes) // 2]) if start else list(sizes)[len(list(sizes)) // 2],
                stroke_gray=80, stroke_width=1.0, fill_stroke_width=0.5, shear=0, dx=0, dy=0, spacing=0)
    if start:
        best.update(start)
    space = {'point_size': list(sizes), 'stroke_gray': [80, 128, 160, 200, 255],
             'stroke_width': [0, 0.5, 0.65, 0.85, 1.0, 1.1, 1.25, 1.5, 2.0], 'fill_stroke_width': [0, 0.3, 0.5, 0.85, 1.0],
             'shear': list(shears), 'dx': list(range(-3, 4)), 'dy': list(range(-3, 4)), 'spacing': [-1, 0, 1, 2, 3]}
    cur = score(render(text, width, height, rotate=rotate, mode=mode, **best), target)
    for _ in range(4):
        improved = False
        for key, values in space.items():
            for v in values:
                trial = {**best, key: v}
                try:
                    s = score(render(text, width, height, rotate=rotate, mode=mode, **trial), target)
                except Exception:
                    continue
                if s > cur:
                    cur, best, improved = s, trial, True
        if not improved:
            break
    return cur, best
