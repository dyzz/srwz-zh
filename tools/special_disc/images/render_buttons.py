"""Chinese labels for the three SP menu button atlases (VT1 #156, #171, #185).

Each atlas is one 512x512 PSMT8 picture with one 256-colour palette. A tile is
256x40; 4 buttons x 5 state rows (grey, light green, pale green, bright green,
dark green). The label is a dark fill with a light rim, recoloured per state.

The whole button is drawn from the user's text-free plate
(jobs/button-plates/ai-original.png, one plate per state), with the label added
on top (user, 2026-09-18). Per atlas / button / state:
  1. face: the state's plate, resampled with exact area weights onto the tile,
     its box searched so that its silhouette matches the original button. The
     original alpha is kept; the few opaque pixels the plate misses take the
     nearest plate pixel. Outside the panel every state shows the state-0
     plate, so the frame stays still when the game switches states.
  2. label style: per state, a layered model (glow, 1-3 px rim, fill; each
     with its own colour and opacity) fitted with bounds on the four Japanese
     labels. Only this fit uses a reconstruction of the original panel without
     text (the plate after a quadratic colour map fitted per state, the
     remaining mismatch at the box edges interpolated along each row).
  3. label: project font rendered at 8x and area-averaged, emboldened by
     0.25 px; the label is shifted vertically, and each glyph horizontally, by
     at most half a pixel so that its edges fall on pixel boundaries. It is
     centred where the Japanese label was and styled per state over the face,
     only on the panel. The two labels kept in Japanese are redrawn from their
     original ink.
  4. palette: a new palette for the atlas: index 0 stays the transparent
     entry, the other 255 are k-means colours of the finished pixels (median-cut
     start), no dithering.

Outputs: jobs/button-plates/tiles/*.png (plates at the nominal tile size), and
per atlas jobs/<slug>/final-zh-indexes.npy and final-zh-palette.npy (what the
preview build writes), final-zh.png (the same as RGBA), clean.png (faces
without labels), compare.png, preview-ja.png, preview-zh.png, render.json.
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
from srwz.tim2_writeback import _csm1_palette_offset, unswizzle_psmt8  # noqa: E402

TD = ROOT / "work/analysis/sp-texture-diff-20260912"
PLATES = OUT / "jobs" / "button-plates"
AI_SHA256 = "3143fb40725927beecee418fd0f2f96988152270bef19b90c9052c9efd894035"
AI_TOPS = [65, 251, 437, 623, 809]  # plate rows in the user's image
AI_LEFT, AI_W, AI_H = 73, 1297, 161
FONT_LOCK = json.loads((ROOT / "config/fonts/harmonyos-sans-sc.lock.json").read_text())["font"]
FONT = ROOT / FONT_LOCK["path"]
TW, TH = 256, 40  # tile
PW, PH = 249, 39  # plate silhouette inside a tile, nominally at (3, 1)
ATLASES = [
    (156, "vt1-16-title-menu", ["额外关卡", "特别剧场", "资料库", "战斗鉴赏"]),
    (171, "vt1-30-extra-stage-menu", ["剧情模式", "读取", "挑战模式", "继续"]),
    (185, "vt1-53-battle-viewer-menu", ["普通", "TRI", "简易", "单机"]),
]
# Label order above: (col 0, row 0), (col 0, row 1), (col 1, row 0), (col 1, row 1).
BUTTONS = [(0, 0), (0, 1), (1, 0), (1, 1)]
PENDING = {"简易", "单机"}
# Left in Japanese for now (user, 2026-09-17): where these two appear in game is not known yet.
KEEP_JAPANESE = {("vt1-53-battle-viewer-menu", 0, 1), ("vt1-53-battle-viewer-menu", 1, 1)}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_atlas(idx: int):
    changes = json.loads((TD / "comparison.json").read_text())["changes"]
    rec = (TD / "tim2" / f"{changes[idx]['sp']['record_sha256']}.tm2").read_bytes()
    q = parse_tim2(rec).pictures[0]
    a = q.offset + q.header_size
    indexes = np.frombuffer(unswizzle_psmt8(rec[a:a + q.image_size], 512, 512), np.uint8).reshape(512, 512)
    pal = rec[a + q.image_size:a + q.image_size + q.clut_size]
    colours = np.array([list(pal[_csm1_palette_offset(n) * 4:][:4]) for n in range(256)], np.int32)
    colours[:, 3] = np.minimum(255, colours[:, 3] * 2)
    return indexes, colours, changes[idx]["sp"]


def ai_plates():
    data = (PLATES / "ai-original.png").read_bytes()
    assert sha256(data) == AI_SHA256
    im = cv2.imread(str(PLATES / "ai-original.png"), cv2.IMREAD_UNCHANGED).astype(np.float32)[..., [2, 1, 0, 3]]
    plates = []
    for s, top in enumerate(AI_TOPS):
        crop = im[top:top + AI_H, AI_LEFT:AI_LEFT + AI_W]
        a = crop[..., 3:4] / 255.0
        pm = cv2.resize(crop[..., :3] * a, (PW, PH), interpolation=cv2.INTER_AREA)
        sa = cv2.resize(a[..., 0], (PW, PH), interpolation=cv2.INTER_AREA)
        rgb = pm / np.maximum(sa[..., None], 1e-6)
        plates.append(rgb)
        global PLATE_ALPHA
        if PLATE_ALPHA is None:
            PLATE_ALPHA = sa > 0.5
        out = np.dstack([np.clip(rgb, 0, 255), sa * 255]).astype(np.uint8)
        (PLATES / "tiles").mkdir(exist_ok=True)
        Image.fromarray(out, "RGBA").save(PLATES / "tiles" / f"plate-state{s}.png")
    return plates


def tile_slice(col: int, row: int, state: int):
    y = row * 200 + state * 40
    return slice(y, y + TH), slice(col * 256, col * 256 + TW)


def label_box(boxes, col, row, state, pad=0, pad_y=None):
    """Manifest box of this tile's label in tile coordinates, as a mask."""
    pad_y = pad if pad_y is None else pad_y
    y0 = row * 200 + state * 40
    m = np.zeros((TH, TW), bool)
    for bx0, by0, bx1, by1 in boxes:
        if y0 <= by0 < y0 + TH and col * 256 <= bx0 < col * 256 + TW:
            m[max(0, by0 - y0 - pad_y):min(TH, by1 - y0 + pad_y),
              max(0, bx0 - col * 256 - pad):min(TW, bx1 - col * 256 + pad)] = True
    return m


def shift(mask, dy, dx):
    out = np.zeros_like(mask)
    ys = slice(max(0, dy), TH + min(0, dy))
    yd = slice(max(0, -dy), TH + min(0, -dy))
    xs = slice(max(0, dx), TW + min(0, dx))
    xd = slice(max(0, -dx), TW + min(0, -dx))
    out[ys, xs] = mask[yd, xd]
    return out


def atlas_panel(tiles_by_button, unions, origins, near=6):
    """Panel mask per button, pooled over the four buttons of an atlas.

    A pixel is panel if it changes colour between states in some button where
    no label covers it (aligned by plate origin). The stretch covered by every
    label is bridged per row from panel pixels within `near` px on both sides;
    the outer frame edge also changes colour (anti-aliasing) and is ignored.
    """
    pooled = np.zeros((TH, TW), bool)
    covered = np.ones((TH, TW), bool)
    for b, tiles in tiles_by_button.items():
        base = tiles[0][..., :3].astype(np.int32)
        changed = sum((np.abs(t[..., :3].astype(np.int32) - base).max(-1) > 4).astype(int) for t in tiles[1:])
        known = (changed >= 3) & ~unions[b] & (tiles[0][..., 3] > 0)
        ox, oy = origins[b]
        pooled |= shift(known, -oy, -ox)
        covered &= shift(unions[b], -oy, -ox)
    for y in range(TH):
        xs = np.where(covered[y])[0]
        if not len(xs):
            continue
        b0, b1 = xs[0], xs[-1]
        left = np.where(pooled[y, max(0, b0 - near):b0])[0]
        right = np.where(pooled[y, b1 + 1:b1 + 1 + near])[0]
        if len(left) and len(right):
            pooled[y, b0:b1 + 1] = True
    panels = {}
    for b, tiles in tiles_by_button.items():
        ox, oy = origins[b]
        panels[b] = shift(pooled, oy, ox) & (tiles[0][..., 3] > 0)
    return panels


def smooth_rows(field, hole):
    """Soften row-to-row steps of an interpolated field inside the hole."""
    blurred = cv2.GaussianBlur(field.astype(np.float32), (1, 0), sigmaX=0.1, sigmaY=1.2).astype(np.float64)
    out = field.copy()
    out[hole] = blurred[hole]
    return out


def row_fill(values, hole, valid, span=3, reach=16):
    """Per row, interpolate each hole run between valid pixels just left and right of it."""
    out = values.copy()
    for y in range(TH):
        xs = np.where(hole[y])[0]
        if not len(xs):
            continue
        for run in np.split(xs, np.where(np.diff(xs) > 1)[0] + 1):
            x0, x1 = run[0], run[-1]
            left = [x for x in range(x0 - 1, max(-1, x0 - 1 - reach), -1) if valid[y, x]][:span]
            right = [x for x in range(x1 + 1, min(TW, x1 + 1 + reach)) if valid[y, x]][:span]
            if not left and not right:
                continue
            lv = values[y, left].mean(0) if left else values[y, right].mean(0)
            rv = values[y, right].mean(0) if right else lv
            t = ((np.arange(x0, x1 + 1) - x0 + 1) / (x1 - x0 + 2))[:, None]
            out[y, x0:x1 + 1] = lv * (1 - t) + rv * t
    return out


def plate_panel(plates):
    """Panel pixels of the user's plates (they change between states), at plate scale."""
    base = plates[0]
    changed = sum((np.abs(p - base).max(-1) > 12).astype(int) for p in plates[1:])
    return ndimage.binary_erosion(changed >= 3, np.ones((3, 3)))


PLATE_ALPHA = None


def plate_origin(tile_rgba):
    """Tile position of the plate that best matches the tile silhouette."""
    alpha = tile_rgba[..., 3] > 0
    best = None
    for oy in range(0, TH - PH + 1):
        for ox in range(0, 6):
            placed = np.zeros((TH, TW), bool)
            placed[oy:oy + PH, ox:ox + PW] = PLATE_ALPHA[:TH - oy, :TW - ox]
            iou = (placed & alpha).sum() / max((placed | alpha).sum(), 1)
            if best is None or iou > best[0]:
                best = (iou, ox, oy)
    return best[1], best[2]


def place_plate(plate, tile_rgba):
    """Plate in tile coordinates, at the origin that best matches the tile silhouette."""
    ox, oy = plate_origin(tile_rgba)
    placed = np.zeros((TH, TW, plate.shape[2]), np.float64)
    placed[oy:oy + PH, ox:ox + PW] = plate[:TH - oy, :TW - ox]
    return placed


def colour_terms(rgb):
    x = rgb / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    return np.stack([np.ones_like(r), r, g, b, r * r, g * g, b * b, r * g, g * b, r * b], -1)


def fit_colour_map(pairs):
    """pairs: list of (plate_rgb, original_rgb, mask). Quadratic colour map plate -> original."""
    X = np.vstack([colour_terms(p)[m] for p, o, m in pairs])
    Y = np.vstack([o[m] for p, o, m in pairs])
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    mae = float(np.abs(X @ coef - Y).mean())
    return coef, mae


def clean_tile(tile_rgba, hole, placed, colour_map, placed_panel, panel, borrowed=None):
    """Mapped plate inside the hole, with the boundary mismatch interpolated along each row.

    `borrowed` (rgb, mask) supplies exact pixels copied from another button of
    the same state; they count as known. Where the plate is not panel (its
    rivet or frame drawn a little differently), the nearest plate panel pixel
    to the right is used; rows without any are interpolated from the original.
    """
    orig = tile_rgba[..., :3].astype(np.float64)
    alpha = tile_rgba[..., 3] > 0
    if borrowed is not None:
        rgb, mask = borrowed
        orig = orig.copy()
        orig[mask] = rgb[mask]
        hole = hole & ~mask
    valid = panel & ~hole & alpha
    mapped = colour_terms(placed) @ colour_map
    edge = np.zeros_like(hole)
    for y, x in zip(*np.where(hole & ~placed_panel)):
        right = np.where(placed_panel[y, x + 1:x + 41])[0]
        if len(right):
            mapped[y, x] = mapped[y, x + 1 + right[0]]
        else:
            edge[y, x] = True
    residual = smooth_rows(row_fill(orig - mapped, hole, valid & placed_panel), hole)
    out = orig.copy()
    out[hole] = (mapped + residual)[hole]
    rows = row_fill(orig, edge, valid)
    out[edge] = rows[edge]
    return out


def borrow_from_other_buttons(rgba, holes, panels, unions, button, state, max_mae=6.0):
    """Exact pixels for this button's hole from buttons whose plate matches here."""
    tile = rgba[tile_slice(*button, state)]
    ox, oy = plate_origin(tile)
    hole = holes[button + (state,)]
    rgb = np.zeros((TH, TW, 3), np.float64)
    got = np.zeros((TH, TW), bool)
    donors = []
    for other in BUTTONS:
        if other == button:
            continue
        donor = rgba[tile_slice(*other, state)]
        if plate_origin(donor) != (ox, oy):
            continue  # a button drawn differently; see row_mapped_fill
        free = ~ndimage.binary_dilation(unions[other], np.ones((5, 5))) & (donor[..., 3] > 0)
        common = free & ~ndimage.binary_dilation(unions[button], np.ones((5, 5))) & panels[button] & (tile[..., 3] > 0)
        if common.sum() < 200:
            continue
        mae = float(np.abs(donor[..., :3].astype(np.float64) - tile[..., :3])[common].mean())
        if mae <= max_mae:
            donors.append((mae, donor, free))
    for mae, donor, free in sorted(donors, key=lambda d: d[0]):
        take = hole & free & ~got
        rgb[take] = donor[..., :3][take]
        got |= take
    return rgb, got


def row_mapping(reference_alpha, target_alpha):
    """Target row -> reference row, by aligning the per-row opaque counts (dynamic time warping)."""
    a = target_alpha.sum(1).astype(np.float64)
    b = reference_alpha.sum(1).astype(np.float64)
    n, m = len(a), len(b)
    cost = np.full((n + 1, m + 1), np.inf)
    cost[0, 0] = 0
    for i in range(1, n + 1):
        for j in range(max(1, i - 3), min(m, i + 3) + 1):
            cost[i, j] = abs(a[i - 1] - b[j - 1]) + min(cost[i - 1, j - 1], cost[i - 1, j], cost[i, j - 1])
    i, j, pairs = n, m, []
    while i > 0 and j > 0:
        pairs.append((i - 1, j - 1))
        step = int(np.argmin([cost[i - 1, j - 1], cost[i - 1, j], cost[i, j - 1]]))
        i, j = (i - 1, j - 1) if step == 0 else ((i - 1, j) if step == 1 else (i, j - 1))
    mapping = {}
    for ti, rj in reversed(pairs):
        mapping.setdefault(ti, rj)
    return np.array([mapping[t] for t in range(n)])


def row_mapped_fill(tile_rgba, hole, reference_clean, reference_alpha, panel):
    """Fill the hole of a button drawn a little differently from a clean regular button."""
    dtw = row_mapping(reference_alpha, tile_rgba[..., 3] > 0)
    # A straight line through the aligned rows (below the top frame) avoids repeated or skipped rows.
    t = np.arange(6, TH)
    slope, intercept = np.polyfit(t, dtw[6:], 1)
    rows = np.where(np.arange(TH) < 6, dtw, slope * np.arange(TH) + intercept).clip(0, TH - 1)
    map_y = np.repeat(rows[:, None], TW, 1).astype(np.float32)
    map_x = np.repeat(np.arange(TW, dtype=np.float32)[None, :], TH, 0)
    source = cv2.remap(reference_clean.astype(np.float32), map_x, map_y, cv2.INTER_LINEAR).astype(np.float64)
    orig = tile_rgba[..., :3].astype(np.float64)
    valid = panel & ~hole & (tile_rgba[..., 3] > 0)
    residual = smooth_rows(row_fill(orig - source, hole, valid), hole)
    out = orig.copy()
    out[hole] = (source + residual)[hole]
    return out, rows


def soft(mask: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur((mask > 0.5).astype(np.float32), (0, 0), 0.5)


def rings(fill):
    d1 = ndimage.maximum_filter(fill, 3)
    d2 = ndimage.maximum_filter(fill, 5)
    d3 = ndimage.maximum_filter(fill, 7)
    return np.clip(d1 - fill, 0, 1), np.clip(d2 - d1, 0, 1), np.clip(d3 - d2, 0, 1)


def compose_label(fill, plate, params, glow_sigma):
    cg, og, cr, w, cf, of = (params[0:3], params[3], params[3 + 1:7], params[7:10], params[10:13], params[13])
    a_g = np.clip(og * cv2.GaussianBlur(fill, (0, 0), glow_sigma), 0, 1)[..., None]
    out = plate * (1 - a_g) + cg * a_g
    r1, r2, r3 = rings(fill)
    a_r = np.clip(w[0] * r1 + w[1] * r2 + w[2] * r3, 0, 1)[..., None]
    out = out * (1 - a_r) + cr * a_r
    a_f = (of * fill)[..., None]
    return out * (1 - a_f) + cf * a_f


def fit_style(samples):
    """samples: list of (fill, plate, target, region). Bounded fit of the layered label model."""
    from scipy.optimize import least_squares
    lo = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    hi = [255, 255, 255, 10, 255, 255, 255, 1, 1, 1, 255, 255, 255, 1]
    best = None
    for sigma in (1.5, 2.5, 4.0):
        parts = []
        for f, p, t, r in samples:
            r1, r2, r3 = rings(f)
            parts.append((cv2.GaussianBlur(f, (0, 0), sigma)[r], r1[r], r2[r], r3[r], f[r], p[r], t[r]))
        g, r1, r2, r3, f, p, t = (np.concatenate(x) for x in zip(*parts))

        def residual(x):
            a_g = np.clip(x[3] * g, 0, 1)[:, None]
            out = p * (1 - a_g) + x[0:3] * a_g
            a_r = np.clip(x[7] * r1 + x[8] * r2 + x[9] * r3, 0, 1)[:, None]
            out = out * (1 - a_r) + x[4:7] * a_r
            a_f = (x[13] * f)[:, None]
            return (out * (1 - a_f) + x[10:13] * a_f - t).ravel()

        start = [200, 200, 200, 1, 200, 200, 200, 0.5, 0.3, 0.1, 20, 20, 20, 0.9]
        fit = least_squares(residual, start, bounds=(lo, hi), loss="soft_l1", f_scale=20, max_nfev=2000)
        mae = float(np.abs(residual(fit.x)).mean())
        if best is None or mae < best[2]:
            best = (fit.x, sigma, mae)
    return best


def apply_style(fill, plate, style):
    params, sigma, _mae = style
    return np.clip(compose_label(fill, plate, params, sigma), 0, 255)


def japanese_ink(tile_state0, box, panel):
    lum = tile_state0[..., :3].astype(np.float32).mean(-1)
    ink = (lum < 30) & box & ndimage.binary_erosion(panel, np.ones((3, 3)))
    lab, n = ndimage.label(ink, np.ones((3, 3)))
    sizes = ndimage.sum(ink, lab, range(1, n + 1))
    return np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= 3])


def japanese_fill(tile_state0, box, panel):
    return soft(japanese_ink(tile_state0, box, panel))


def japanese_coverage(tile_state0, box, panel):
    """Anti-aliased ink of an original label: in state 0 a black fill inside a grey halo."""
    ink = japanese_ink(tile_state0, box, panel)
    lum = tile_state0[..., :3].astype(np.float64).mean(-1)
    distance = ndimage.distance_transform_edt(~ink)
    halo = float(lum[(distance > 1) & (distance <= 2)].mean())
    core = float(np.median(lum[ink]))
    edge = (distance > 0) & (distance < 1.5)
    coverage = ink.astype(np.float64)
    coverage[edge] = np.clip((halo - lum[edge]) / (halo - core), 0, 1)
    return coverage, dict(core_luminance=round(core, 1), halo_luminance=round(halo, 1))


def style_fit(slug, rgba, boxes, plates):
    """The per-state label style fitted on the four Japanese labels (see the module docstring)."""
    fills, holes, cleans, unions, origins, tiles_by_button = {}, {}, {}, {}, {}, {}
    for col, row in BUTTONS:
        tiles = [rgba[tile_slice(col, row, s)] for s in range(5)]
        tiles_by_button[col, row] = tiles
        origins[col, row] = plate_origin(tiles[0])
        unions[col, row] = np.logical_or.reduce([label_box(boxes, col, row, s, pad=3) for s in range(5)])
    panels = atlas_panel(tiles_by_button, unions, origins)
    for col, row in BUTTONS:
        fills[col, row] = japanese_fill(tiles_by_button[col, row][0], label_box(boxes, col, row, 0, pad=2), panels[col, row])
    colour_maps = {}
    for s in range(5):
        pairs = []
        for col, row in BUTTONS:
            tile = rgba[tile_slice(col, row, s)]
            far = panels[col, row] & ~ndimage.binary_dilation(unions[col, row], np.ones((9, 9))) & (tile[..., 3] > 0)
            pairs.append((place_plate(plates[s], tile), tile[..., :3].astype(np.float64), far))
        colour_maps[s] = fit_colour_map(pairs)
    panel_of_plate = plate_panel(plates)
    # The box rows stop short of the panel's top and bottom edge lines.
    for col, row in BUTTONS:
        for s in range(5):
            tile = rgba[tile_slice(col, row, s)]
            holes[col, row, s] = label_box(boxes, col, row, s, pad=3, pad_y=1) & panels[col, row] & (tile[..., 3] > 0)
    origin_votes = {}
    for b in BUTTONS:
        origin_votes[origins[b]] = origin_votes.get(origins[b], 0) + 1
    regular_origin = max(origin_votes, key=origin_votes.get)
    irregular = [b for b in BUTTONS if origins[b] != regular_origin]
    for col, row in [b for b in BUTTONS if b not in irregular] + irregular:
        for s in range(5):
            tile = rgba[tile_slice(col, row, s)]
            hole = holes[col, row, s]
            borrowed = borrow_from_other_buttons(rgba, holes, panels, unions, (col, row), s)
            if (col, row) in irregular:
                reference = next(b for b in BUTTONS if b not in irregular)
                ref_tile = rgba[tile_slice(*reference, s)]
                out, _rows = row_mapped_fill(tile, hole, cleans[reference + (s,)], ref_tile[..., 3] > 0, panels[col, row])
            else:
                placed_panel = place_plate(panel_of_plate[..., None].astype(np.float64), tile)[..., 0] > 0.5
                out = clean_tile(tile, hole, place_plate(plates[s], tile), colour_maps[s][0], placed_panel,
                                 panels[col, row], borrowed)
            cleans[col, row, s] = out
    styles, validation = {}, {}
    for s in range(5):
        samples = [(fills[b], cleans[b + (s,)], rgba[tile_slice(*b, s)][..., :3].astype(np.float64), holes[b + (s,)])
                   for b in BUTTONS]
        styles[s] = fit_style(samples)
        errs = []
        for k in range(4):  # leave one button out
            style = fit_style(samples[:k] + samples[k + 1:])
            f, p, t, r = samples[k]
            errs.append(float(np.abs(apply_style(f, p, style) - t)[r].mean()))
        validation[s] = dict(fit_mae=round(styles[s][2], 2), held_out_mae=round(float(np.mean(errs)), 2))
    return styles, validation, fills, panels


# --- the finished buttons: the user's plate, whole ---------------------------------------------

BIG = None
CROP_PAD = 12


def plate_crop(state):
    global BIG
    if BIG is None:
        BIG = cv2.imread(str(PLATES / "ai-original.png"), cv2.IMREAD_UNCHANGED).astype(np.float64)[..., [2, 1, 0, 3]]
        BIG[..., 3] /= 255.0
    top = AI_TOPS[state]
    return BIG[top - CROP_PAD:top + AI_H + CROP_PAD, AI_LEFT - CROP_PAD:AI_LEFT + AI_W + CROP_PAD]


def area_weights(n_out, start, step, n_in):
    """Exact area weights: output cell j averages the source span [start + j*step, start + (j+1)*step)."""
    w = np.zeros((n_out, n_in))
    for j in range(n_out):
        a, b = start + j * step, start + (j + 1) * step
        for i in range(max(0, int(np.floor(a))), min(n_in, int(np.ceil(b)))):
            w[j, i] = max(0.0, min(b, i + 1) - max(a, i))
    return w / step


def resample_plate(state, box, tbox, alpha_only=False):
    """The plate region `box` (x0, y0, x1, y1 in crop coordinates) mapped onto the tile bbox `tbox`."""
    c = plate_crop(state)
    tx0, ty0, tx1, ty1 = tbox
    sx, sy = (box[2] - box[0]) / (tx1 - tx0), (box[3] - box[1]) / (ty1 - ty0)
    wx = area_weights(TW, box[0] - tx0 * sx, sx, c.shape[1])
    wy = area_weights(TH, box[1] - ty0 * sy, sy, c.shape[0])
    alpha = wy @ c[..., 3] @ wx.T
    if alpha_only:
        return None, alpha
    premultiplied = np.stack([wy @ (c[..., k] * c[..., 3]) @ wx.T for k in range(3)], -1)
    return premultiplied, alpha


FITS = {}


def fit_plate(state, tile_alpha):
    """Box of the state's plate whose silhouette (alpha >= 0.5) best matches the tile's opaque pixels."""
    key = (state, tile_alpha.tobytes())
    if key in FITS:
        return FITS[key]
    ys, xs = np.where(tile_alpha)
    tbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    base = [CROP_PAD, CROP_PAD, CROP_PAD + AI_W, CROP_PAD + AI_H]
    cur = list(base)
    for sweep in range(4):  # each box edge in turn, first +-4 source px around the nominal box, then finer
        for k in range(4):
            scores = []
            for d in np.arange(-4, 4.01, 1.0):
                box = list(cur)
                box[k] = base[k] + d if sweep == 0 else cur[k] + d * 0.5 ** sweep
                _, alpha = resample_plate(state, box, tbox, alpha_only=True)
                scores.append((int(((alpha >= 0.5) ^ tile_alpha).sum()), abs(box[k] - cur[k]), box[k]))
            cur[k] = min(scores)[2]
    _, alpha = resample_plate(state, cur, tbox, alpha_only=True)
    FITS[key] = dict(box=[round(float(v), 4) for v in cur], tbox=list(tbox),
                     silhouette_mismatch=int(((alpha >= 0.5) ^ tile_alpha).sum()))
    return FITS[key]


def plate_face(state, tile_alpha):
    """The state's plate on the tile (straight colour); opaque tile pixels it misses take the nearest plate pixel."""
    fit = fit_plate(state, tile_alpha)
    premultiplied, alpha = resample_plate(state, fit["box"], fit["tbox"])
    rgb = premultiplied / np.maximum(alpha, 1e-6)[..., None]
    covered = alpha >= 0.5
    missed = tile_alpha & ~covered
    if missed.any():
        _, (iy, ix) = ndimage.distance_transform_edt(~covered, return_indices=True)
        rgb[missed] = rgb[iy[missed], ix[missed]]
    rgb = np.clip(rgb, 0, 255)
    rgb[~tile_alpha] = 0
    return rgb, int(missed.sum())


def button_faces(tiles):
    """Per state: the state's plate on the panel, the state-0 plate on the frame; and the soft panel mask."""
    faces, masks, report = [], [], []
    for s, tile in enumerate(tiles):
        alpha = tile[..., 3] > 0
        own, missed = plate_face(s, alpha)
        frame, _ = plate_face(0, alpha)
        bright, _ = plate_face(3, alpha)  # the panel is where the bright green state has colour
        chroma = bright.max(-1) - bright.min(-1)
        panel = np.clip((chroma - 20) / 40, 0, 1)
        faces.append(panel[..., None] * own + (1 - panel[..., None]) * frame)
        masks.append(panel)
        report.append(dict(fit_plate(s, alpha), pixels_filled_from_neighbours=missed))
    return faces, masks, report


TEXT_SS = 8
BOLD_PX = 0.25
LABEL_INK_HEIGHT = 21  # nominal Chinese ink height, close to the kana bodies (rows 9-29)
LABEL_CENTRE_Y = 19.0


def label_coverage(text: str, centre_x: float):
    """Anti-aliased label centred on (centre_x, LABEL_CENTRE_Y), its edges pulled onto the pixel grid."""
    height = LABEL_INK_HEIGHT
    em = height / 0.86
    tracking = {2: 0.5, 3: 0.3, 4: 0.15}.get(len(text), 0.1) * em
    if text.isascii():
        em = height / 0.72
        tracking = 0.1 * em
    font = ImageFont.truetype(str(FONT), round(em * TEXT_SS))
    radius = round(BOLD_PX * TEXT_SS)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    pad = 4 * TEXT_SS
    glyphs = []
    for ch in text:
        canvas = Image.new("L", (font.size * 2 + 2 * pad, font.size * 2 + 2 * pad), 0)
        ImageDraw.Draw(canvas).text((pad, pad), ch, font=font, fill=255)
        ink = cv2.dilate((np.asarray(canvas) >= 128).astype(np.uint8), kernel) > 0
        glyphs.append((np.nonzero(ink), font.getlength(ch)))
    ink_top = min(ys.min() for (ys, _), _ in glyphs) - pad
    ink_bottom = max(ys.max() + 1 for (ys, _), _ in glyphs) - pad
    ink_h = (ink_bottom - ink_top) / TEXT_SS
    total = sum(adv for _, adv in glyphs) + tracking * TEXT_SS * (len(text) - 1)
    x_start = centre_x * TEXT_SS - total / 2
    pen_y = (LABEL_CENTRE_Y - ink_h / 2) * TEXT_SS - ink_top
    hi_w, hi_h = TW * TEXT_SS, TH * TEXT_SS

    def render(dy, dxs):
        hi = np.zeros((hi_h, hi_w), np.float32)
        x = x_start
        for ((ys, xs), adv), dx in zip(glyphs, dxs):
            gy = ys + int(round(pen_y + dy)) - pad
            gx = xs + int(round(x + dx)) - pad
            assert gy.min() >= 0 and gx.min() >= 0 and gy.max() < hi_h and gx.max() < hi_w, text
            hi[gy, gx] = 1
            x += adv + tracking * TEXT_SS
        return hi.reshape(TH, TEXT_SS, TW, TEXT_SS).mean((1, 3))

    def soft_pixels(coverage):  # partly covered pixels are what makes small text look blurred
        return float(np.minimum(coverage, 1 - coverage).sum())

    steps = range(-TEXT_SS // 2, TEXT_SS // 2)
    dxs = [0] * len(glyphs)
    dy = min(steps, key=lambda d: soft_pixels(render(d, dxs)))
    for i in range(len(glyphs)):
        dxs[i] = min(steps, key=lambda d: soft_pixels(render(dy, dxs[:i] + [d] + dxs[i + 1:])))
    dy = min(steps, key=lambda d: soft_pixels(render(d, dxs)))
    coverage = render(dy, dxs).astype(np.float64)
    return coverage, dict(em=round(em, 2), tracking=round(tracking, 2), ink_height=round(ink_h, 3), bold_px=BOLD_PX,
                          shift_y=dy / TEXT_SS, shift_x=[d / TEXT_SS for d in dxs],
                          soft_pixels=round(soft_pixels(coverage), 1),
                          soft_pixels_unaligned=round(soft_pixels(render(0, [0] * len(glyphs))), 1))


def fit_palette(rgb, n=255, rounds=16):
    """k-means colours (median-cut start) for the given pixels; returns the colours and each pixel's entry."""
    pixels = np.clip(np.rint(rgb), 0, 255).astype(np.int64)
    uniq, inverse, counts = np.unique(pixels, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.ravel()
    start = Image.fromarray(pixels.reshape(-1, 1, 3).astype(np.uint8)).quantize(n, method=Image.Quantize.MEDIANCUT)
    seed = np.array(start.getpalette(), np.float64).reshape(-1, 3)[:n]
    centres = np.vstack([seed, np.repeat(seed[:1], n - len(seed), 0)]) if len(seed) < n else seed
    u, w = uniq.astype(np.float64), counts.astype(np.float64)

    def nearest(c):
        out = np.empty(len(u), np.int64)
        cc = (c ** 2).sum(1)
        for i in range(0, len(u), 16384):
            out[i:i + 16384] = (cc[None] - 2 * u[i:i + 16384] @ c.T).argmin(1)
        return out

    for _ in range(rounds):
        lab = nearest(centres)
        sums = np.zeros_like(centres)
        np.add.at(sums, lab, u * w[:, None])
        mass = np.bincount(lab, weights=w, minlength=n)
        used = mass > 0
        centres[used] = sums[used] / mass[used, None]
        if (~used).any():  # an unused entry restarts at the worst-served colours
            err = ((u - centres[lab]) ** 2).sum(1) * w
            centres[~used] = u[np.argsort(err)[::-1][:int((~used).sum())]]
    centres = np.clip(np.rint(centres), 0, 255)
    lab = nearest(centres)
    return centres.astype(np.uint8), lab[inverse]


def on_dark(img):
    bg = np.full(img.shape[:2] + (3,), 40, np.uint8)
    return np.where(img[..., 3:4] > 0, img[..., :3], bg)


def main() -> None:
    assert sha256(FONT.read_bytes()) == FONT_LOCK["sha256"]
    plates = ai_plates()
    manifest = json.loads((OUT / "manifest.json").read_text())
    summary = {}
    for idx, slug, labels in ATLASES:
        job = OUT / "jobs" / slug
        boxes = [j for j in manifest["jobs"] if j["slug"] == slug][0]["mask_boxes"]
        indexes, colours, meta = load_atlas(idx)
        rgba = colours[indexes].astype(np.uint8)
        styles, validation, fills, panels = style_fit(slug, rgba, boxes, plates)
        opaque = rgba[..., 3] > 0
        clean = np.zeros((512, 512, 3), np.float64)
        final = np.zeros((512, 512, 3), np.float64)
        report_buttons = []
        for (col, row), text in zip(BUTTONS, labels):
            tiles = [rgba[tile_slice(col, row, s)] for s in range(5)]
            faces, masks, fits = button_faces(tiles)
            if (slug, col, row) in KEEP_JAPANESE:
                coverage, geometry = japanese_coverage(tiles[0], label_box(boxes, col, row, 0, pad=2), panels[col, row])
                entry = dict(tile=[col, row], text=None, kept_japanese=True, redrawn_from_original_ink=geometry)
            else:
                ys, xs = np.where(fills[col, row] > 0.5)
                coverage, geometry = label_coverage(text, (xs.min() + xs.max() + 1) / 2)
                entry = dict(tile=[col, row], text=text, pending=text in PENDING,
                             japanese_ink=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], **geometry)
            for s in range(5):
                sl = tile_slice(col, row, s)
                styled = apply_style(coverage, faces[s], styles[s])
                clean[sl] = faces[s]
                final[sl] = faces[s] + masks[s][..., None] * (styled - faces[s])
            report_buttons.append(dict(entry, plates=fits))
        entries, lab = fit_palette(final[opaque])
        palette = np.zeros((256, 4), np.uint8)
        palette[1:1 + len(entries), :3] = entries
        palette[1:, 3] = 255
        palette[0] = (0, 0, 0, 0)  # the original transparent entry
        assert tuple(colours[0]) == (0, 0, 0, 0) and not (indexes[opaque] == 0).any() and (indexes[~opaque] == 0).all()
        new_indexes = np.zeros((512, 512), np.uint8)
        new_indexes[opaque] = lab + 1
        result = palette[new_indexes]
        assert ((result[..., 3] > 0) == opaque).all()
        error = np.abs(result[..., :3].astype(np.float64) - final)[opaque]
        np.save(job / "final-zh-indexes.npy", new_indexes)
        np.save(job / "final-zh-palette.npy", palette)
        Image.fromarray(result, "RGBA").save(job / "final-zh.png")
        clean_rgba = np.dstack([np.clip(np.rint(clean), 0, 255), rgba[..., 3]]).astype(np.uint8)
        Image.fromarray(clean_rgba, "RGBA").save(job / "clean.png")
        pair = np.hstack([on_dark(rgba[:400]), np.full((400, 12, 3), 255, np.uint8), on_dark(result[:400])])
        Image.fromarray(pair).resize((pair.shape[1] * 2, pair.shape[0] * 2), Image.NEAREST).save(job / "compare.png")
        for name, img in (("preview-ja.png", rgba[:400]), ("preview-zh.png", result[:400])):
            Image.fromarray(on_dark(img)).save(job / name)
        report = dict(
            source=dict(atlas=f"DATA/VT1.BIN {meta['location']}", record_sha256=meta["record_sha256"]),
            plates=dict(file="jobs/button-plates/ai-original.png", sha256=AI_SHA256,
                        placement="each state's plate resampled by area onto the tile, its box searched to match the "
                                  "original silhouette; outside the panel every state shows the state-0 plate"),
            font=dict(path=FONT_LOCK["path"], sha256=FONT_LOCK["sha256"]),
            label_style={s: dict(glow_rgb=[round(float(v), 1) for v in st[0][0:3]], glow_opacity=round(float(st[0][3]), 3),
                                 glow_sigma=st[1], rim_rgb=[round(float(v), 1) for v in st[0][4:7]],
                                 rim_weights=[round(float(v), 3) for v in st[0][7:10]],
                                 fill_rgb=[round(float(v), 1) for v in st[0][10:13]], fill_opacity=round(float(st[0][13]), 3),
                                 **validation[s]) for s, st in styles.items()},
            buttons=report_buttons,
            palette=dict(entries=int(len(entries)), transparent_index=0,
                         mean_abs_error=round(float(error.mean()), 2), p99_abs_error=round(float(np.percentile(error, 99)), 1)),
            outputs={name: sha256((job / name).read_bytes())
                     for name in ("final-zh-indexes.npy", "final-zh-palette.npy", "final-zh.png", "clean.png")},
        )
        (job / "render.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        summary[slug] = dict(validation=validation, palette=report["palette"],
                             labels=[(b["text"], b.get("soft_pixels_unaligned"), b.get("soft_pixels")) for b in report_buttons],
                             silhouette_mismatch=[max(p["silhouette_mismatch"] for p in b["plates"]) for b in report_buttons])
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
