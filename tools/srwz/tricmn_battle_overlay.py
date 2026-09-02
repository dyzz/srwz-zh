"""Deterministic indexed localization for the TRICMN battle overlays."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from .font_flavor import (
    font_flavor_metadata,
    load_font_flavor_reference,
    verify_font_flavor_files,
)
from .imagemagick import (
    box_downsample_grayscale,
    imagemagick_version,
    render_grayscale_text_mask,
    require_imagemagick,
)
from .gs_indexed_texture import (
    GSIndexedTextureError,
    inverse_quantize_tex1_bilinear,
    simulate_tex1_bilinear_continuous_rgba,
)
from .patch_audit import sha256_bytes, summarize_diff
from .psmt4 import swizzle_psmt4, unswizzle_psmt4
from .tim2 import parse_tim2


class TricmnBattleOverlayError(ValueError):
    """The TRICMN source or localized output violates its locked contract."""


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TricmnBattleOverlayError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise TricmnBattleOverlayError(f"JSON root must be an object: {path}")
    return value


def _path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise TricmnBattleOverlayError("project path must be non-empty")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise TricmnBattleOverlayError(f"path escapes project root: {raw}") from error
    return path


def _lock(root: Path, path: Path, data: bytes | None = None) -> dict:
    payload = path.read_bytes() if data is None else data
    return {
        "path": str(path.resolve().relative_to(root.resolve())),
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _integer(raw: object, label: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise TricmnBattleOverlayError(f"{label} must be an integer")
    return raw


def _palette_ramp(
    raw: object,
    *,
    default: tuple[int, ...],
    allowed: set[int],
    label: str,
) -> tuple[int, ...]:
    if raw is None:
        return default
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(value, int) or isinstance(value, bool) for value in raw)
    ):
        raise TricmnBattleOverlayError(f"{label} must be a non-empty integer list")
    values = tuple(raw)
    if len(set(values)) != len(values) or any(value not in allowed for value in values):
        raise TricmnBattleOverlayError(f"{label} uses invalid palette indexes")
    return values


def _rect(
    raw: object,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(not isinstance(value, int) or isinstance(value, bool) for value in raw)
    ):
        raise TricmnBattleOverlayError("label rectangle must contain four integers")
    x, y, rect_width, rect_height = raw
    if (
        x < 0
        or y < 0
        or rect_width <= 0
        or rect_height <= 0
        or x + rect_width > width
        or y + rect_height > height
    ):
        raise TricmnBattleOverlayError(f"label rectangle is outside the atlas: {raw}")
    return x, y, rect_width, rect_height


def _rect_indexes(
    indexes: bytes,
    *,
    picture_width: int,
    rect: tuple[int, int, int, int],
) -> bytes:
    x, y, width, height = rect
    return b"".join(
        indexes[row * picture_width + x : row * picture_width + x + width]
        for row in range(y, y + height)
    )


def _ink_bounds(mask: bytes, width: int) -> tuple[int, int, int, int]:
    points = [index for index, value in enumerate(mask) if value]
    if not points:
        raise TricmnBattleOverlayError("rendered text mask has no ink")
    return (
        min(index % width for index in points),
        min(index // width for index in points),
        max(index % width for index in points) + 1,
        max(index // width for index in points) + 1,
    )


def _character_column_spans(
    mask: bytes,
    *,
    width: int,
    height: int,
) -> tuple[tuple[int, int], ...]:
    """Split a rendered fill mask into stable left-to-right character spans.

    The compact status labels have positive inter-character spacing, so every
    glyph occupies one contiguous run of columns in the fill mask. Bound each
    character at the midpoint of the adjacent empty gap; this lets a material
    adjustment address one glyph without hard-coding texture coordinates or
    touching its neighbouring letters.
    """

    if len(mask) != width * height:
        raise TricmnBattleOverlayError("character span mask geometry drift")
    occupied = [
        any(mask[row * width + column] for row in range(height))
        for column in range(width)
    ]
    runs = []
    start = None
    for column, value in enumerate((*occupied, False)):
        if value and start is None:
            start = column
        elif not value and start is not None:
            runs.append((start, column))
            start = None
    if not runs:
        raise TricmnBattleOverlayError("rendered fill has no character columns")
    boundaries = [0]
    for previous, current in zip(runs, runs[1:]):
        boundaries.append((previous[1] + current[0]) // 2)
    boundaries.append(width)
    return tuple(zip(boundaries, boundaries[1:]))


def _add_indexed_glow(
    mask: bytes,
    *,
    width: int,
    height: int,
    radius: int,
) -> bytes:
    """Add a deterministic radial feather outside an antialiased outline.

    TRICMN stores the soft edge in the indexed image rather than generating a
    runtime blur.  The old iterative 3x3 maximum filter measured distance with
    square (Chebyshev) neighbourhoods, which made the outer edge visibly boxy
    after the game enlarged the texture.  Spread only from the original mask,
    use Euclidean support, and square the falloff so the added pixels stay in
    the low-alpha end of the preserved CLUT ramp.
    """

    if radius == 0:
        return mask
    if not 1 <= radius <= 6:
        raise TricmnBattleOverlayError("indexed glow radius must be between 0 and 6")
    output = bytearray(mask)
    radius_squared = radius * radius
    scale = 256
    falloff_denominator = (radius + 1) * scale
    falloff_denominator_squared = falloff_denominator * falloff_denominator
    offsets = []
    for delta_y in range(-radius, radius + 1):
        for delta_x in range(-radius, radius + 1):
            distance_squared = delta_x * delta_x + delta_y * delta_y
            if distance_squared == 0 or distance_squared > radius_squared:
                continue
            distance = math.isqrt(distance_squared * scale * scale)
            falloff = falloff_denominator - distance
            offsets.append((delta_x, delta_y, falloff * falloff))

    for source_y in range(height):
        for source_x in range(width):
            source_coverage = mask[source_y * width + source_x]
            if source_coverage == 0:
                continue
            for delta_x, delta_y, falloff_squared in offsets:
                target_x = source_x + delta_x
                target_y = source_y + delta_y
                if not (0 <= target_x < width and 0 <= target_y < height):
                    continue
                coverage = (
                    source_coverage * falloff_squared
                    + falloff_denominator_squared // 2
                ) // falloff_denominator_squared
                target = target_y * width + target_x
                if coverage > output[target]:
                    output[target] = coverage
    return bytes(output)


def _csm1_offset(index: int) -> int:
    return (index & 0xE7) | ((index & 0x08) << 1) | ((index & 0x10) >> 1)


def _palette_color(clut: bytes, bank: int, index: int) -> bytes:
    offset = _csm1_offset(bank * 16 + index) * 4
    return clut[offset : offset + 4]


def _render_bank(indexes: bytes, clut: bytes, bank: int) -> bytes:
    width = 512
    height = 256
    output = bytearray(width * height * 4)
    for pixel, index in enumerate(indexes):
        color = _palette_color(clut, bank, index)
        alpha = min(255, color[3] * 2)
        x = pixel % width
        y = pixel // width
        background = 48 if ((x // 8 + y // 8) & 1) == 0 else 64
        target = pixel * 4
        output[target : target + 4] = bytes(
            (
                (color[0] * alpha + background * (255 - alpha) + 127) // 255,
                (color[1] * alpha + background * (255 - alpha) + 127) // 255,
                (color[2] * alpha + background * (255 - alpha) + 127) // 255,
                255,
            )
        )
    return bytes(output)


def render_palette_montage(pictures: Sequence[bytes], clut: bytes) -> bytes:
    """Render the localized text pictures under every shared CLUT bank."""

    if not pictures:
        raise TricmnBattleOverlayError("TRICMN preview requires at least one picture")

    panel_width = 512
    panel_height = 256 * len(pictures)
    columns = 4
    rows = 7
    output_width = panel_width * columns
    output_height = panel_height * rows
    output = bytearray(output_width * output_height * 4)
    for bank in range(28):
        x_offset = (bank % columns) * panel_width
        y_offset = (bank // columns) * panel_height
        for picture_index, indexes in enumerate(pictures):
            panel = _render_bank(indexes, clut, bank)
            picture_y = y_offset + picture_index * 256
            for y in range(256):
                source = y * panel_width * 4
                target = ((picture_y + y) * output_width + x_offset) * 4
                output[target : target + panel_width * 4] = panel[
                    source : source + panel_width * 4
                ]
    return bytes(output)


def _render_label_masks(
    executable: str,
    font_path: Path,
    text: str,
    rect: tuple[int, int, int, int],
    render: Mapping[str, object],
    target_ink_width: int | None = None,
) -> tuple[
    bytes,
    bytes,
    int,
    tuple[int, int, int, int],
    bytes | None,
    bytes | None,
    int,
    float,
]:
    _x, _y, width, height = rect
    point_size = _integer(render.get("point_size"), "point size")
    supersample = _integer(render.get("supersample_factor"), "supersample factor")
    horizontal_alignment = render.get("horizontal_alignment", "left")
    if horizontal_alignment not in {"left", "center"}:
        raise TricmnBattleOverlayError(
            "horizontal alignment must be left or center"
        )
    glow_radius = _integer(render.get("glow_radius", 0), "glow radius")
    vector_effects = render.get("vector_effects_before_downsample", False)
    if not isinstance(vector_effects, bool):
        raise TricmnBattleOverlayError(
            "vector effects before downsample must be a boolean"
        )
    base_character_spacing = float(render.get("character_spacing", 0))
    common = {
        "executable": executable,
        "font": font_path,
        "text": text,
        "width": width,
        "height": height,
        "point_size": point_size,
        "italic_shear_degrees": float(render.get("italic_shear_degrees", 0)),
        "supersample_factor": supersample,
        "fill_stroke_width": float(render.get("fill_stroke_width", 0)),
        "character_spacing": base_character_spacing,
    }

    effective_character_spacing = base_character_spacing
    distributed_shifts: list[int] | None = None
    if target_ink_width is not None:
        maximum_target_width = width - 2
        if not 1 <= target_ink_width <= maximum_target_width:
            raise TricmnBattleOverlayError(
                "source-matched target ink width escaped its fixed rectangle"
            )
        glyph_bounds = []
        for character in text:
            glyph_common = dict(common)
            glyph_common["text"] = character
            glyph = render_grayscale_text_mask(
                stroke_gray="white",
                stroke_width=float(render.get("outline_stroke_width", 0)),
                **glyph_common,
            )
            glyph = _add_indexed_glow(
                glyph,
                width=width,
                height=height,
                radius=glow_radius,
            )
            glyph_bounds.append(_ink_bounds(glyph, width))
        group_left = (width - target_ink_width) // 2
        if len(glyph_bounds) == 1:
            placements = [
                group_left
                + (target_ink_width - (glyph_bounds[0][2] - glyph_bounds[0][0]))
                // 2
            ]
        else:
            first_width = glyph_bounds[0][2] - glyph_bounds[0][0]
            last_width = glyph_bounds[-1][2] - glyph_bounds[-1][0]
            first_center = group_left + first_width / 2.0
            last_center = group_left + target_ink_width - last_width / 2.0
            placements = []
            for character_index, bounds in enumerate(glyph_bounds):
                glyph_width = bounds[2] - bounds[0]
                center = first_center + (
                    (last_center - first_center)
                    * character_index
                    / (len(glyph_bounds) - 1)
                )
                placements.append(round(center - glyph_width / 2.0))
        distributed_shifts = [
            placement - bounds[0]
            for placement, bounds in zip(placements, glyph_bounds)
        ]
        if len(glyph_bounds) > 1:
            effective_character_spacing = (
                target_ink_width
                - sum(bounds[2] - bounds[0] for bounds in glyph_bounds)
            ) / (len(glyph_bounds) - 1)

    def render_mask(
        *,
        stroke_gray: str,
        stroke_width: float,
        preserve_supersample: bool,
    ) -> bytes:
        if distributed_shifts is None:
            return render_grayscale_text_mask(
                stroke_gray=stroke_gray,
                stroke_width=stroke_width,
                preserve_supersample=preserve_supersample,
                **common,
            )
        scale = supersample if preserve_supersample else 1
        canvas_width = width * scale
        canvas_height = height * scale
        merged = bytearray(canvas_width * canvas_height)
        for character, shift in zip(text, distributed_shifts):
            glyph_common = dict(common)
            glyph_common["text"] = character
            glyph = render_grayscale_text_mask(
                stroke_gray=stroke_gray,
                stroke_width=stroke_width,
                preserve_supersample=preserve_supersample,
                **glyph_common,
            )
            scaled_shift = shift * scale
            for local_y in range(canvas_height):
                row = local_y * canvas_width
                for local_x in range(canvas_width):
                    value = glyph[row + local_x]
                    target_x = local_x + scaled_shift
                    if value and 0 <= target_x < canvas_width:
                        target = row + target_x
                        if value > merged[target]:
                            merged[target] = value
        return bytes(merged)

    if distributed_shifts is None:
        provisional = render_mask(
            stroke_gray="white",
            stroke_width=float(render.get("outline_stroke_width", 0)),
            preserve_supersample=False,
        )
        provisional = _add_indexed_glow(
            provisional,
            width=width,
            height=height,
            radius=glow_radius,
        )
        provisional_bounds = _ink_bounds(provisional, width)
        provisional_left = provisional_bounds[0]
        if horizontal_alignment == "left":
            desired_left = _integer(render.get("ink_left"), "ink left")
        else:
            provisional_width = provisional_bounds[2] - provisional_bounds[0]
            desired_left = (width - provisional_width) // 2
        horizontal_offset = desired_left - provisional_left
        common["horizontal_offset"] = horizontal_offset
    else:
        desired_left = (width - target_ink_width) // 2
        horizontal_offset = 0

    vector_outline_mask = None
    vector_fill_mask = None
    if vector_effects:
        vector_outline_mask = render_mask(
            stroke_gray="white",
            stroke_width=float(render.get("outline_stroke_width", 0)),
            preserve_supersample=True,
        )
        outline_mask = box_downsample_grayscale(
            vector_outline_mask,
            width=width,
            height=height,
            factor=supersample,
        )
        vector_fill_mask = render_mask(
            stroke_gray="black",
            stroke_width=0,
            preserve_supersample=True,
        )
        fill_mask = box_downsample_grayscale(
            vector_fill_mask,
            width=width,
            height=height,
            factor=supersample,
        )
    else:
        outline_mask = render_mask(
            stroke_gray="white",
            stroke_width=float(render.get("outline_stroke_width", 0)),
            preserve_supersample=False,
        )
        fill_mask = render_mask(
            stroke_gray="black",
            stroke_width=0,
            preserve_supersample=False,
        )
    outline_mask = _add_indexed_glow(
        outline_mask,
        width=width,
        height=height,
        radius=glow_radius,
    )
    outline_bounds = _ink_bounds(outline_mask, width)
    fill_bounds = _ink_bounds(fill_mask, width)
    if outline_bounds[0] != desired_left or not (
        0 <= outline_bounds[1] < outline_bounds[3] <= height
        and 0 <= fill_bounds[0] < fill_bounds[2] <= width
        and 0 <= fill_bounds[1] < fill_bounds[3] <= height
    ):
        raise TricmnBattleOverlayError("rendered text escaped its fixed rectangle")
    if outline_bounds[2] == width:
        raise TricmnBattleOverlayError("rendered text touches the right rectangle edge")
    return (
        outline_mask,
        fill_mask,
        horizontal_offset,
        outline_bounds,
        vector_outline_mask,
        vector_fill_mask,
        supersample,
        effective_character_spacing,
    )


def _ramp_offset(
    coverage: int,
    *,
    maximum: int,
    ramp_length: int,
    power: int,
) -> int:
    if maximum <= 0 or ramp_length <= 0 or not 1 <= power <= 4:
        raise TricmnBattleOverlayError("indexed palette ramp parameters are invalid")
    numerator = coverage**power * (ramp_length - 1)
    denominator = maximum**power
    return min((numerator + denominator // 2) // denominator, ramp_length - 1)


def _scaled_source_index_counts(
    source_rect: bytes,
    *,
    output_ink_pixel_count: int,
    palette_indexes: tuple[int, ...],
) -> dict[int, int]:
    """Scale a source label's complete index histogram to a new glyph mask.

    TRICMN's stock labels are not flat fill plus an independent outline.  The
    authored 1..15 pattern contains a bevel, a lower-right inner shadow, and a
    directional extrusion.  Retaining the source histogram prevents a new
    glyph from collapsing most of its face to index 15 even when its geometry
    differs from the Japanese source.
    """

    if output_ink_pixel_count <= 0 or not palette_indexes:
        raise TricmnBattleOverlayError("source histogram target is empty")
    source_counts = Counter(
        value for value in source_rect if value in set(palette_indexes)
    )
    source_total = sum(source_counts.values())
    if source_total <= 0:
        raise TricmnBattleOverlayError("source label has no indexed style pixels")

    scaled = {}
    remainders = []
    assigned = 0
    for index in palette_indexes:
        numerator = source_counts[index] * output_ink_pixel_count
        count, remainder = divmod(numerator, source_total)
        scaled[index] = count
        assigned += count
        remainders.append((remainder, source_counts[index], -index, index))
    for _remainder, _source_count, _negative_index, index in sorted(
        remainders, reverse=True
    )[: output_ink_pixel_count - assigned]:
        scaled[index] += 1
    if sum(scaled.values()) != output_ink_pixel_count:
        raise TricmnBattleOverlayError("scaled source histogram does not close")
    return scaled


def _directional_extrusion_silhouette(
    outline_mask: bytes,
    *,
    width: int,
    height: int,
    shadow_offset_x: int,
    shadow_offset_y: int,
) -> bytes:
    """Extrude a coverage mask continuously towards the lower right."""

    if len(outline_mask) != width * height:
        raise TricmnBattleOverlayError("directional extrusion mask geometry drift")
    if not 0 <= shadow_offset_x <= 32 or not 0 <= shadow_offset_y <= 32:
        raise TricmnBattleOverlayError("directional shadow offset is invalid")
    if shadow_offset_x == 0 and shadow_offset_y == 0:
        raise TricmnBattleOverlayError("directional shadow must have an offset")

    silhouette = bytearray(outline_mask)
    steps = max(shadow_offset_x, shadow_offset_y)
    for step in range(1, steps + 1):
        delta_x = (shadow_offset_x * step + steps - 1) // steps
        delta_y = (shadow_offset_y * step + steps - 1) // steps
        for source_y in range(height):
            target_y = source_y + delta_y
            if target_y >= height:
                continue
            for source_x in range(width):
                coverage = outline_mask[source_y * width + source_x]
                target_x = source_x + delta_x
                if coverage == 0 or target_x >= width:
                    continue
                target = target_y * width + target_x
                if coverage > silhouette[target]:
                    silhouette[target] = coverage
    return bytes(silhouette)


def _chamfer_distance_to_state(
    mask: bytes,
    *,
    width: int,
    height: int,
    target_nonzero: bool,
    maximum_pixels: int,
) -> list[int]:
    """Return a capped 8-neighbour distance field in 1/256-pixel units.

    TRICMN ultimately stores only palette indexes, but the authored titles were
    clearly shaded as continuous relief before they were rasterized.  This
    compact chamfer field lets the deterministic builder reconstruct that
    continuous surface without introducing a Blender/runtime dependency.
    """

    if len(mask) != width * height:
        raise TricmnBattleOverlayError("height-field mask geometry drift")
    if maximum_pixels <= 0:
        raise TricmnBattleOverlayError("height-field distance cap must be positive")
    axial = 256
    diagonal = 362
    cap = (maximum_pixels + 1) * axial
    distances = [
        0 if bool(value) == target_nonzero else cap
        for value in mask
    ]

    for y in range(height):
        row = y * width
        for x in range(width):
            local = row + x
            best = distances[local]
            if x:
                best = min(best, distances[local - 1] + axial)
            if y:
                best = min(best, distances[local - width] + axial)
                if x:
                    best = min(best, distances[local - width - 1] + diagonal)
                if x + 1 < width:
                    best = min(best, distances[local - width + 1] + diagonal)
            distances[local] = min(best, cap)

    for y in range(height - 1, -1, -1):
        row = y * width
        for x in range(width - 1, -1, -1):
            local = row + x
            best = distances[local]
            if x + 1 < width:
                best = min(best, distances[local + 1] + axial)
            if y + 1 < height:
                best = min(best, distances[local + width] + axial)
                if x:
                    best = min(best, distances[local + width - 1] + diagonal)
                if x + 1 < width:
                    best = min(best, distances[local + width + 1] + diagonal)
            distances[local] = min(best, cap)
    return distances


def _box_downsample_weighted_scores(
    scores: Sequence[int],
    coverage: bytes,
    *,
    width: int,
    height: int,
    factor: int,
) -> list[int]:
    """Downsample a continuous surface score once, weighted by its coverage."""

    high_width = width * factor
    high_height = height * factor
    if (
        factor <= 1
        or len(scores) != high_width * high_height
        or len(coverage) != high_width * high_height
    ):
        raise TricmnBattleOverlayError("height-field score geometry drift")
    output = [0] * (width * height)
    for target_y in range(height):
        for target_x in range(width):
            weighted = 0
            total_coverage = 0
            for source_y in range(target_y * factor, (target_y + 1) * factor):
                source = source_y * high_width + target_x * factor
                for delta_x in range(factor):
                    local = source + delta_x
                    weight = coverage[local]
                    weighted += scores[local] * weight
                    total_coverage += weight
            if total_coverage:
                output[target_y * width + target_x] = (
                    weighted + total_coverage // 2
                ) // total_coverage
    return output


def _heightfield_wordart_surface(
    vector_outline_mask: bytes,
    vector_fill_mask: bytes,
    *,
    width: int,
    height: int,
    factor: int,
    shadow_offset_x: int,
    shadow_offset_y: int,
    glow_radius: int,
    bevel_width: float,
    relief_strength: float,
    ambient: float,
    diffuse: float,
    specular: float,
) -> dict[str, object]:
    """Render an orthographic embossed WordArt surface before rasterization.

    The face is treated as a real height field.  Its boundary distance becomes
    elevation, local derivatives become a surface normal, and a fixed upper-
    left light shades that normal.  The outline is then extruded continuously
    down-right and a separate low-coverage rim is constructed outside it.
    Only after all three surfaces exist are coverage and lighting reduced to
    the native 4bpp texel grid.
    """

    high_width = width * factor
    high_height = height * factor
    expected = high_width * high_height
    if (
        factor <= 1
        or len(vector_outline_mask) != expected
        or len(vector_fill_mask) != expected
    ):
        raise TricmnBattleOverlayError("height-field vector geometry drift")
    if not 0.5 <= bevel_width <= 4.0:
        raise TricmnBattleOverlayError("height-field bevel width is invalid")
    if not 0.1 <= relief_strength <= 8.0:
        raise TricmnBattleOverlayError("height-field relief strength is invalid")
    if any(value < 0 or value > 1 for value in (ambient, diffuse, specular)):
        raise TricmnBattleOverlayError("height-field light coefficients are invalid")
    if ambient + diffuse + specular <= 0:
        raise TricmnBattleOverlayError("height-field light is empty")

    steps = max(shadow_offset_x, shadow_offset_y) * factor
    if steps <= 0:
        raise TricmnBattleOverlayError("height-field extrusion depth is empty")
    extruded = bytearray(vector_outline_mask)
    extrusion_depth = [0] * expected
    for step in range(1, steps + 1):
        delta_x = (shadow_offset_x * factor * step + steps - 1) // steps
        delta_y = (shadow_offset_y * factor * step + steps - 1) // steps
        for source_y in range(high_height):
            target_y = source_y + delta_y
            if target_y >= high_height:
                continue
            source_row = source_y * high_width
            target_row = target_y * high_width
            for source_x in range(high_width):
                coverage = vector_outline_mask[source_row + source_x]
                target_x = source_x + delta_x
                if coverage == 0 or target_x >= high_width:
                    continue
                target = target_row + target_x
                if coverage > extruded[target]:
                    extruded[target] = coverage
                if step > extrusion_depth[target]:
                    extrusion_depth[target] = step

    halo_width = max(1, glow_radius * factor)
    distance_to_extrusion = _chamfer_distance_to_state(
        bytes(extruded),
        width=high_width,
        height=high_height,
        target_nonzero=True,
        maximum_pixels=halo_width + 1,
    )
    full_silhouette = bytearray(extruded)
    halo_coverage = bytearray(expected)
    halo_limit = halo_width * 256
    for local, distance in enumerate(distance_to_extrusion):
        if extruded[local] or distance > halo_limit:
            continue
        coverage = max(1, 255 - (distance * 255) // (halo_limit + 256))
        halo_coverage[local] = coverage
        full_silhouette[local] = max(full_silhouette[local], coverage)

    bevel_pixels = max(1, int(round(bevel_width * factor)))
    distance_inside_face = _chamfer_distance_to_state(
        vector_fill_mask,
        width=high_width,
        height=high_height,
        target_nonzero=False,
        maximum_pixels=bevel_pixels + 1,
    )
    height_field = [0.0] * expected
    face_plateau = bytearray(expected)
    bevel_limit = bevel_pixels * 256
    for local, coverage in enumerate(vector_fill_mask):
        if not coverage:
            continue
        rise = min(1.0, distance_inside_face[local] / bevel_limit)
        height_field[local] = rise * coverage / 255.0
        if distance_inside_face[local] >= bevel_limit:
            face_plateau[local] = coverage

    # Unit light from upper-left and towards the viewer.
    light_x = -0.52
    light_y = -0.52
    light_z = math.sqrt(max(0.0, 1.0 - light_x * light_x - light_y * light_y))
    face_scores = [0] * expected
    side_scores = [0] * expected
    halo_scores = [0] * expected

    def height_at(sample_x: int, sample_y: int) -> float:
        if 0 <= sample_x < high_width and 0 <= sample_y < high_height:
            return height_field[sample_y * high_width + sample_x]
        return 0.0

    for y in range(high_height):
        row = y * high_width
        for x in range(high_width):
            local = row + x
            face_coverage = vector_fill_mask[local]
            if face_coverage:
                slope_x = (
                    height_at(x + 1, y) - height_at(x - 1, y)
                ) * relief_strength
                slope_y = (
                    height_at(x, y + 1) - height_at(x, y - 1)
                ) * relief_strength
                normal_length = math.sqrt(
                    slope_x * slope_x + slope_y * slope_y + 1.0
                )
                normal_x = -slope_x / normal_length
                normal_y = -slope_y / normal_length
                normal_z = 1.0 / normal_length
                lambert = max(
                    0.0,
                    normal_x * light_x + normal_y * light_y + normal_z * light_z,
                )
                intensity = min(
                    1.0,
                    ambient + diffuse * lambert + specular * lambert**8,
                )
                face_scores[local] = int(round(intensity * 65535))

            if extruded[local] and not face_coverage:
                depth = extrusion_depth[local]
                depth_light = 1.0 - 0.72 * depth / max(1, steps)
                # Keep the authored front outline readable while the far end
                # of the down-right extrusion falls into the deepest ramp.
                side_scores[local] = int(round(max(0.0, depth_light) * 65535))
            if halo_coverage[local]:
                halo_scores[local] = halo_coverage[local] * 257

    core_silhouette = bytes(extruded)
    return {
        "full_silhouette": box_downsample_grayscale(
            bytes(full_silhouette), width=width, height=height, factor=factor
        ),
        "core_silhouette": box_downsample_grayscale(
            core_silhouette, width=width, height=height, factor=factor
        ),
        "face_mask": box_downsample_grayscale(
            vector_fill_mask, width=width, height=height, factor=factor
        ),
        "face_plateau_mask": box_downsample_grayscale(
            bytes(face_plateau), width=width, height=height, factor=factor
        ),
        "halo_coverage": box_downsample_grayscale(
            bytes(halo_coverage), width=width, height=height, factor=factor
        ),
        "face_scores": _box_downsample_weighted_scores(
            face_scores,
            vector_fill_mask,
            width=width,
            height=height,
            factor=factor,
        ),
        "side_scores": _box_downsample_weighted_scores(
            side_scores,
            core_silhouette,
            width=width,
            height=height,
            factor=factor,
        ),
        "halo_scores": _box_downsample_weighted_scores(
            halo_scores,
            bytes(halo_coverage),
            width=width,
            height=height,
            factor=factor,
        ),
        "bevel_width_supersampled_pixels": bevel_pixels,
        "extrusion_depth_supersampled_pixels": steps,
        "halo_width_supersampled_pixels": halo_width,
        "light_vector": [light_x, light_y, light_z],
    }


def _directional_bevel_scores(
    outline_mask: bytes,
    fill_mask: bytes,
    *,
    width: int,
    height: int,
    shadow_offset_x: int,
    shadow_offset_y: int,
) -> tuple[bytes, list[int]]:
    """Build the stock-style lower-right extrusion and bevel ordering.

    The score is only an ordering authority.  Final palette quantities come
    from the locked Japanese source rectangle, so the generated glyph keeps
    the original label's complete 1..15 tone balance.  A top-left light source
    raises the face score on that edge and lowers it on the bottom/right edge.
    """

    expected = width * height
    if len(outline_mask) != expected or len(fill_mask) != expected:
        raise TricmnBattleOverlayError("directional bevel mask geometry drift")
    if not 0 <= shadow_offset_x <= 4 or not 0 <= shadow_offset_y <= 4:
        raise TricmnBattleOverlayError("directional shadow offset is invalid")
    silhouette = _directional_extrusion_silhouette(
        outline_mask,
        width=width,
        height=height,
        shadow_offset_x=shadow_offset_x,
        shadow_offset_y=shadow_offset_y,
    )

    def sample(mask: bytes, x: int, y: int) -> int:
        if 0 <= x < width and 0 <= y < height:
            return mask[y * width + x]
        return 0

    def inside_distance(x: int, y: int) -> int:
        # A compact Chebyshev distance is enough for these 17..32px labels.
        # It keeps the bright plateau in the middle of each stroke and confines
        # the bevel to its actual edge instead of shading an entire lower half.
        for radius in range(1, 5):
            for delta_y in range(-radius, radius + 1):
                for delta_x in range(-radius, radius + 1):
                    if max(abs(delta_x), abs(delta_y)) != radius:
                        continue
                    if sample(fill_mask, x + delta_x, y + delta_y) == 0:
                        return radius
        return 5

    scores = [0] * expected
    for y in range(height):
        for x in range(width):
            local = y * width + x
            fill = fill_mask[local]
            if fill:
                # Positive gradient means the solid part continues towards
                # bottom-right: this is the stock top/left highlight.  A
                # negative gradient marks the authored lower-right bevel.
                forward = (
                    sample(fill_mask, x + 1, y)
                    + sample(fill_mask, x, y + 1)
                    + sample(fill_mask, x + 1, y + 1)
                )
                backward = (
                    sample(fill_mask, x - 1, y)
                    + sample(fill_mask, x, y - 1)
                    + sample(fill_mask, x - 1, y - 1)
                )
                gradient = (forward - backward) // 3
                scores[local] = (
                    inside_distance(x, y) * 1024 + fill + 2 * gradient
                )
            elif silhouette[local]:
                scores[local] = 3 * silhouette[local]
    return bytes(silhouette), scores


def _outer_edge_mask(mask: bytes, *, width: int, height: int) -> bytes:
    """Return the one-pixel outer boundary of a non-zero indexed silhouette."""

    if len(mask) != width * height:
        raise TricmnBattleOverlayError("outer-edge mask geometry drift")
    output = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            local = y * width + x
            if mask[local] == 0:
                continue
            for neighbour_y in range(y - 1, y + 2):
                for neighbour_x in range(x - 1, x + 2):
                    if neighbour_x == x and neighbour_y == y:
                        continue
                    if (
                        neighbour_x < 0
                        or neighbour_x >= width
                        or neighbour_y < 0
                        or neighbour_y >= height
                        or mask[neighbour_y * width + neighbour_x] == 0
                    ):
                        output[local] = 1
                        break
                if output[local]:
                    break
    return bytes(output)


def _coverage_floor(mask: bytes, *, minimum: int) -> bytes:
    """Remove sub-pixel fragments that cannot survive the indexed runtime scale.

    ImageMagick's supersampled text mask deliberately retains very faint edge
    coverage. In TRICMN every non-zero texel must nevertheless become one of
    the sixteen solid CLUT indexes. Promoting those almost-empty texels to the
    stock bright rim produces isolated square sparks after the game enlarges
    the atlas. Keep the useful antialiasing, but discard only the configured
    low-coverage tail before the WordArt zones are classified.
    """

    if not 0 <= minimum <= 254:
        raise TricmnBattleOverlayError("coverage floor must be between 0 and 254")
    return bytes(value if value >= minimum else 0 for value in mask)


def _directional_mask_gradient(
    mask: bytes,
    *,
    width: int,
    height: int,
    x: int,
    y: int,
) -> int:
    """Measure whether solid coverage lies down-right or up-left of a pixel."""

    if len(mask) != width * height:
        raise TricmnBattleOverlayError("directional gradient mask geometry drift")

    def sample(sample_x: int, sample_y: int) -> int:
        if 0 <= sample_x < width and 0 <= sample_y < height:
            return mask[sample_y * width + sample_x]
        return 0

    forward = sample(x + 1, y) + sample(x, y + 1) + sample(x + 1, y + 1)
    backward = sample(x - 1, y) + sample(x, y - 1) + sample(x - 1, y - 1)
    return (forward - backward) // 3


def _connected_mask_fringe(
    full_mask: bytes,
    core_mask: bytes,
    *,
    width: int,
    height: int,
) -> tuple[int, ...]:
    """Return faint full-mask pixels directly adjoining the retained core.

    This keeps genuine supersampled edge coverage while rejecting detached
    glow fragments.  The returned texels form the antialias transition outside
    the opaque WordArt rim; they never replace the locked face/side/halo zones.
    """

    if len(full_mask) != width * height or len(core_mask) != width * height:
        raise TricmnBattleOverlayError("connected fringe mask geometry drift")
    output = []
    for local, coverage in enumerate(full_mask):
        if coverage == 0 or core_mask[local]:
            continue
        x = local % width
        y = local // width
        connected = False
        for neighbour_y in range(max(0, y - 1), min(height, y + 2)):
            for neighbour_x in range(max(0, x - 1), min(width, x + 2)):
                if core_mask[neighbour_y * width + neighbour_x]:
                    connected = True
                    break
            if connected:
                break
        if connected:
            output.append(local)
    return tuple(output)


def _pixel_edge_filter_coverage(
    full_mask: bytes,
    core_mask: bytes,
    *,
    width: int,
    height: int,
    radius: int,
    coverage_ceiling: int,
) -> bytes:
    """Extend only the indexed outer fringe with a small tent filter.

    The native TRICMN texel cannot store independent alpha coverage, so a
    conventional RGBA blur would either destroy palette semantics or soften
    the raised face and its extrusion together.  Instead, convolve the final
    coverage mask in pixel space and retain the result only outside the locked
    core silhouette.  The caller later maps these added coverage samples onto
    the source Japanese light-rim indexes; no dark side-wall index can leak
    into the antialias fringe.
    """

    if len(full_mask) != width * height or len(core_mask) != width * height:
        raise TricmnBattleOverlayError("pixel edge-filter geometry drift")
    if radius == 0:
        return full_mask
    if not 1 <= radius <= 2:
        raise TricmnBattleOverlayError(
            "pixel edge-filter radius must be between 0 and 2"
        )
    if not 1 <= coverage_ceiling <= 254:
        raise TricmnBattleOverlayError(
            "pixel edge-filter coverage ceiling must be between 1 and 254"
        )

    axis_weights = [radius + 1 - abs(delta) for delta in range(-radius, radius + 1)]
    denominator = sum(axis_weights) ** 2
    output = bytearray(full_mask)
    for y in range(height):
        for x in range(width):
            local = y * width + x
            # Existing coverage already came from the 8x vector raster.  Do
            # not blur or brighten it again.  Add only a missing sample on the
            # lit top/left side; the lower-right extrusion keeps its authored
            # depth and cannot grow a second opaque halo.
            if core_mask[local] or full_mask[local]:
                continue
            if _directional_mask_gradient(
                core_mask,
                width=width,
                height=height,
                x=x,
                y=y,
            ) <= 0:
                continue
            weighted = 0
            for delta_y, weight_y in zip(
                range(-radius, radius + 1), axis_weights
            ):
                sample_y = y + delta_y
                if not 0 <= sample_y < height:
                    continue
                row = sample_y * width
                for delta_x, weight_x in zip(
                    range(-radius, radius + 1), axis_weights
                ):
                    sample_x = x + delta_x
                    if not 0 <= sample_x < width:
                        continue
                    weighted += (
                        full_mask[row + sample_x] * weight_x * weight_y
                    )
            filtered = (weighted + denominator // 2) // denominator
            if filtered:
                # Express the new sample inside the same low-coverage interval
                # as the existing supersampled fringe.  The later CLUT mapper
                # will therefore choose 9/11/12, never the solid index 14.
                output[local] = max(
                    1,
                    (filtered * coverage_ceiling + 127) // 255,
                )
    return bytes(output)


def _boundary_depths(
    mask: bytes,
    *,
    width: int,
    height: int,
    maximum: int,
) -> tuple[int, ...]:
    """Measure each occupied texel's Chebyshev depth from transparency."""

    if len(mask) != width * height:
        raise TricmnBattleOverlayError("boundary-depth mask geometry drift")
    if maximum <= 0:
        raise TricmnBattleOverlayError("boundary-depth maximum must be positive")
    depths = [0] * (width * height)
    for y in range(height):
        for x in range(width):
            local = y * width + x
            if not mask[local]:
                continue
            assigned = maximum + 1
            for radius in range(1, maximum + 1):
                found = False
                for delta_y in range(-radius, radius + 1):
                    for delta_x in range(-radius, radius + 1):
                        if max(abs(delta_x), abs(delta_y)) != radius:
                            continue
                        sample_x = x + delta_x
                        sample_y = y + delta_y
                        if (
                            sample_x < 0
                            or sample_x >= width
                            or sample_y < 0
                            or sample_y >= height
                            or not mask[sample_y * width + sample_x]
                        ):
                            assigned = radius
                            found = True
                            break
                    if found:
                        break
                if found:
                    break
            depths[local] = assigned
    return tuple(depths)


def _upper_left_exposed_at_depth(
    mask: bytes,
    *,
    width: int,
    height: int,
    x: int,
    y: int,
    depth: int,
) -> bool:
    """Return whether a boundary layer opens towards top, left or top-left."""

    if len(mask) != width * height:
        raise TricmnBattleOverlayError("upper-left exposure mask geometry drift")
    if depth <= 0:
        raise TricmnBattleOverlayError("upper-left exposure depth must be positive")

    def transparent(sample_x: int, sample_y: int) -> bool:
        return (
            sample_x < 0
            or sample_x >= width
            or sample_y < 0
            or sample_y >= height
            or not mask[sample_y * width + sample_x]
        )

    return any(
        transparent(sample_x, sample_y)
        for sample_x, sample_y in (
            (x - depth, y),
            (x, y - depth),
            (x - depth, y - depth),
        )
    )


def _source_quantile_assignments(
    locals_: Sequence[int],
    scores: Sequence[int],
    source_counts: Mapping[int, int],
) -> dict[int, int]:
    """Map coherent spatial-score groups onto a source palette distribution.

    The former renderer split an equal-score plateau merely to reproduce exact
    index counts. At 4x runtime scale those arbitrary cuts became visible as
    diagonal chips across an otherwise flat face. A WordArt-style surface is
    spatially coherent: pixels with the same geometric role must use the same
    palette index. The source histogram remains the tone authority, but it is
    sampled by score-group midpoint instead of enforced as an exact quota.
    """

    if not locals_:
        raise TricmnBattleOverlayError("spatial palette zone is empty")
    if any(local < 0 or local >= len(scores) for local in locals_):
        raise TricmnBattleOverlayError("spatial palette local is outside scores")
    palette_counts = {
        index: count for index, count in sorted(source_counts.items()) if count > 0
    }
    source_total = sum(palette_counts.values())
    if source_total <= 0:
        raise TricmnBattleOverlayError("source spatial palette zone is empty")

    groups: dict[int, list[int]] = {}
    for local in locals_:
        groups.setdefault(scores[local], []).append(local)

    output: dict[int, int] = {}
    output_total = len(locals_)
    consumed = 0
    denominator = 2 * output_total
    for score in sorted(groups):
        group = groups[score]
        # Compare the output group's midpoint quantile with the source CDF
        # using integers so deterministic builds do not depend on floats.
        target = (2 * consumed + len(group)) * source_total
        cumulative = 0
        chosen = next(reversed(palette_counts))
        for palette_index, count in palette_counts.items():
            cumulative += count
            if cumulative * denominator >= target:
                chosen = palette_index
                break
        for local in group:
            output[local] = chosen
        consumed += len(group)

    if len(output) != output_total:
        raise TricmnBattleOverlayError("spatial palette assignment did not close")
    return output


def _source_soft_fringe_assignments(
    locals_: Sequence[int],
    coverage: bytes,
    source_counts: Mapping[int, int],
    *,
    coverage_ceiling: int,
    reserved_inner_rim_index: int | None,
) -> dict[int, int]:
    """Encode sub-pixel coverage with the source light-rim index ramp.

    A TRICMN texel stores one CLUT index, not an independent coverage value.
    The supersampled fringe therefore has to express coverage through the
    source light-rim tones.  Keep the brightest source index for the solid
    inner rim and spread the remaining source indexes monotonically across
    the faint coverage range.  This preserves a 0 -> soft light -> bright rim
    transition instead of promoting every top-facing fringe texel to the
    fully opaque flat-top index.
    """

    if not locals_:
        return {}
    if coverage_ceiling <= 0:
        raise TricmnBattleOverlayError("soft fringe coverage ceiling is invalid")
    if any(local < 0 or local >= len(coverage) for local in locals_):
        raise TricmnBattleOverlayError("soft fringe local is outside coverage")
    ramp = [
        index
        for index, count in sorted(source_counts.items())
        if count > 0 and index != reserved_inner_rim_index
    ]
    if not ramp:
        ramp = [
            index for index, count in sorted(source_counts.items()) if count > 0
        ]
    if not ramp:
        raise TricmnBattleOverlayError("source soft fringe palette is empty")

    output = {}
    for local in locals_:
        value = min(coverage_ceiling, max(1, coverage[local]))
        ramp_offset = min(
            len(ramp) - 1,
            (value * len(ramp) - 1) // coverage_ceiling,
        )
        output[local] = ramp[ramp_offset]
    return output


def _source_continuous_score_assignments(
    locals_: Sequence[int],
    scores: Sequence[int],
    source_counts: Mapping[int, int],
) -> dict[int, int]:
    """Map a continuous geometric surface onto the source palette ramp.

    Height-field side walls often contain a broad, perfectly flat front
    outline.  A histogram-quantile mapper can assign that entire equal-score
    plateau to one arbitrary dark index.  Use the actual score range instead:
    deep extrusion maps to the low source indexes and the face-adjacent wall
    maps to the high source indexes. Equal geometry still remains coherent,
    but a fully lit wall can no longer collapse into an almost-black band.
    """

    if not locals_:
        raise TricmnBattleOverlayError("continuous palette zone is empty")
    if any(local < 0 or local >= len(scores) for local in locals_):
        raise TricmnBattleOverlayError(
            "continuous palette local is outside scores"
        )
    ramp = [
        index for index, count in sorted(source_counts.items()) if count > 0
    ]
    if not ramp:
        raise TricmnBattleOverlayError("source continuous palette is empty")
    minimum = min(scores[local] for local in locals_)
    maximum = max(scores[local] for local in locals_)
    if minimum == maximum:
        return {local: ramp[-1] for local in locals_}
    span = maximum - minimum
    output = {}
    for local in locals_:
        ramp_offset = (
            (scores[local] - minimum) * (len(ramp) - 1) + span // 2
        ) // span
        output[local] = ramp[ramp_offset]
    return output


def _small_palette_components(
    assignments: Mapping[int, int],
    *,
    width: int,
    height: int,
    palette_indexes: set[int],
    minimum_size: int,
) -> list[tuple[int, ...]]:
    """Return isolated palette islands smaller than the authored minimum."""

    if minimum_size <= 1:
        return []
    pending = {
        local
        for local, palette_index in assignments.items()
        if palette_index in palette_indexes
    }
    components = []
    while pending:
        start = min(pending)
        pending.remove(start)
        component = [start]
        queue = [start]
        while queue:
            local = queue.pop()
            x = local % width
            y = local // width
            for neighbour_y in range(max(0, y - 1), min(height, y + 2)):
                for neighbour_x in range(max(0, x - 1), min(width, x + 2)):
                    neighbour = neighbour_y * width + neighbour_x
                    if neighbour in pending:
                        pending.remove(neighbour)
                        component.append(neighbour)
                        queue.append(neighbour)
        if len(component) < minimum_size:
            components.append(tuple(sorted(component)))
    return components


def _runtime_palette(clut: bytes, bank: int) -> tuple[tuple[float, ...], ...]:
    """Return the sixteen CLUT colours as the GS exposes them to filtering."""

    colors = []
    for index in range(16):
        color = _palette_color(clut, bank, index)
        colors.append(
            (
                float(color[0]),
                float(color[1]),
                float(color[2]),
                float(min(255, color[3] * 2)),
            )
        )
    return tuple(colors)


def _rgba_luminance(color: Sequence[float]) -> float:
    return (54.0 * color[0] + 183.0 * color[1] + 19.0 * color[2]) / 256.0


def _interpolate_palette_path(
    palette: Sequence[Sequence[float]],
    palette_indexes: Sequence[int],
    position: float,
) -> tuple[float, float, float, float]:
    """Interpolate a continuous target colour along an allowed index ramp."""

    ordered = tuple(
        sorted(
            dict.fromkeys(palette_indexes),
            key=lambda index: (_rgba_luminance(palette[index]), index),
        )
    )
    if not ordered:
        raise TricmnBattleOverlayError("continuous target palette path is empty")
    if len(ordered) == 1:
        return tuple(palette[ordered[0]])
    scaled = max(0.0, min(1.0, position)) * (len(ordered) - 1)
    left = min(len(ordered) - 1, int(math.floor(scaled)))
    right = min(len(ordered) - 1, left + 1)
    fraction = scaled - left
    return tuple(
        palette[ordered[left]][channel] * (1.0 - fraction)
        + palette[ordered[right]][channel] * fraction
        for channel in range(4)
    )


def _interpolate_weighted_palette_quantile(
    palette: Sequence[Sequence[float]],
    source_counts: Mapping[int, int],
    quantile: float,
) -> tuple[float, float, float, float]:
    """Sample a continuous ramp while retaining the JP index distribution.

    A plain min/max normalization spreads face lighting evenly across 8..15
    and turns a stock face whose pixels are predominantly index 15 into middle
    grey.  Treat the source histogram as weighted colour anchors instead: the
    large white-face bin stays broad, while interpolation between anchor
    centres removes hard palette terraces.
    """

    ordered = tuple(
        sorted(
            (
                (index, count)
                for index, count in source_counts.items()
                if count > 0
            ),
            key=lambda item: (_rgba_luminance(palette[item[0]]), item[0]),
        )
    )
    if not ordered:
        raise TricmnBattleOverlayError(
            "continuous target weighted palette path is empty"
        )
    if len(ordered) == 1:
        return tuple(palette[ordered[0][0]])
    total = sum(count for _index, count in ordered)
    cumulative = 0
    anchors = []
    for index, count in ordered:
        anchors.append(((cumulative + count / 2.0) / total, index))
        cumulative += count
    position = max(0.0, min(1.0, quantile))
    if position <= anchors[0][0]:
        return tuple(palette[anchors[0][1]])
    if position >= anchors[-1][0]:
        return tuple(palette[anchors[-1][1]])
    for (left_position, left_index), (right_position, right_index) in zip(
        anchors, anchors[1:]
    ):
        if position > right_position:
            continue
        fraction = (position - left_position) / (
            right_position - left_position
        )
        return tuple(
            palette[left_index][channel] * (1.0 - fraction)
            + palette[right_index][channel] * fraction
            for channel in range(4)
        )
    raise TricmnBattleOverlayError(
        "continuous target weighted palette interpolation did not close"
    )


def _continuous_wordart_target(
    *,
    width: int,
    height: int,
    assignments: Mapping[int, int],
    output_zones: Mapping[str, Sequence[int]],
    zone_scores: Mapping[str, Sequence[int]],
    source_zone_counts: Mapping[str, Counter],
    anti_alias: Sequence[int],
    edge_filtered_coverage: bytes,
    coverage_floor: int,
    flat_top_output_locals: Sequence[int],
    flat_face_output_locals: Sequence[int],
    upper_left_highlight: Sequence[int],
    upper_left_minimum_index: int,
    palette: Sequence[Sequence[float]],
) -> tuple[float, ...]:
    """Build the ideal continuous embossed image before PSMT4 quantization.

    The height-field and direction scores remain the lighting authority.  This
    target intentionally contains colours between CLUT entries; the inverse
    TEX1 stage later finds the legal native index arrangement whose filtered
    display best approximates it.
    """

    expected = width * height
    target = [0.0] * (expected * 4)
    for zone_name in ("halo", "side", "face"):
        locals_ = tuple(output_zones[zone_name])
        scores = zone_scores[zone_name]
        if not locals_ or len(scores) != expected:
            raise TricmnBattleOverlayError("continuous target zone geometry drift")
        ordered_locals = sorted(locals_, key=lambda local: (scores[local], local))
        score_quantiles = {}
        start = 0
        denominator = max(1, len(ordered_locals) - 1)
        while start < len(ordered_locals):
            end = start + 1
            score = scores[ordered_locals[start]]
            while (
                end < len(ordered_locals)
                and scores[ordered_locals[end]] == score
            ):
                end += 1
            score_quantiles[score] = (
                (start + end - 1) / 2.0 / denominator
            )
            start = end
        for local in locals_:
            color = _interpolate_weighted_palette_quantile(
                palette,
                source_zone_counts[zone_name],
                score_quantiles[scores[local]],
            )
            target[local * 4 : local * 4 + 4] = color

    # The outside fringe is authored as fractional coverage in the ideal
    # image.  Its legal PSMT4 preimage can only use the source light-rim
    # indexes, so TEX1 itself supplies the remaining subpixel transition.
    soft_path = (0, *sorted(source_zone_counts["halo"]))
    ceiling = max(1, coverage_floor - 1)
    for local in anti_alias:
        position = edge_filtered_coverage[local] / ceiling
        color = _interpolate_palette_path(palette, soft_path, position)
        target[local * 4 : local * 4 + 4] = color

    for local in flat_top_output_locals:
        palette_index = assignments[local]
        target[local * 4 : local * 4 + 4] = palette[palette_index]
    for local in flat_face_output_locals:
        palette_index = assignments[local]
        target[local * 4 : local * 4 + 4] = palette[palette_index]
    if upper_left_minimum_index:
        minimum_color = palette[upper_left_minimum_index]
        minimum_luma = _rgba_luminance(minimum_color)
        for local in upper_left_highlight:
            current = target[local * 4 : local * 4 + 4]
            if _rgba_luminance(current) < minimum_luma:
                target[local * 4 : local * 4 + 4] = minimum_color
    return tuple(target)


def _distance_to_mask(
    mask: bytes,
    *,
    width: int,
    height: int,
    x: int,
    y: int,
    maximum: int = 6,
) -> int:
    """Return a compact Chebyshev distance to a non-zero mask pixel."""

    for radius in range(1, maximum + 1):
        for delta_y in range(-radius, radius + 1):
            for delta_x in range(-radius, radius + 1):
                if max(abs(delta_x), abs(delta_y)) != radius:
                    continue
                sample_x = x + delta_x
                sample_y = y + delta_y
                if (
                    0 <= sample_x < width
                    and 0 <= sample_y < height
                    and mask[sample_y * width + sample_x]
                ):
                    return radius
    return maximum + 1


def _paint_indexed_masks(
    indexes: bytearray,
    *,
    picture_width: int,
    rect: tuple[int, int, int, int],
    source_rect: bytes,
    outline_mask: bytes,
    fill_mask: bytes,
    outline_indexes: tuple[int, ...],
    fill_indexes: tuple[int, ...],
    outline_ramp_power: int,
    fill_ramp_power: int,
    render_style: str,
    shadow_offset_x: int,
    shadow_offset_y: int,
    coverage_floor: int,
    side_direction_weight: int,
    halo_direction_weight: int,
    upper_left_highlight_minimum_index: int,
    bright_edge_character_indexes: tuple[int, ...],
    bright_edge_minimum_index: int,
    glow_radius: int,
    vector_outline_mask: bytes | None,
    vector_fill_mask: bytes | None,
    vector_effect_scale: int,
    dark_component_minimum_pixels: int,
    indexed_edge_filter_radius: int,
    heightfield_bevel_width: float,
    heightfield_relief_strength: float,
    heightfield_ambient: float,
    heightfield_diffuse: float,
    heightfield_specular: float,
    heightfield_flat_top_rim: bool,
    heightfield_flat_face: bool,
    inverse_tex1_palette: Sequence[Sequence[float]] | None,
    inverse_tex1_scale: int,
    inverse_tex1_passes: int,
    inverse_tex1_adjacency_threshold: float,
    inverse_tex1_adjacency_weight: float,
) -> dict:
    x, y, width, height = rect
    expected = width * height
    if len(outline_mask) != expected or len(fill_mask) != expected:
        raise TricmnBattleOverlayError("render mask geometry drift")

    outline_only = [
        value
        for offset, value in enumerate(outline_mask)
        if value and not fill_mask[offset]
    ]
    visible_fill = [value for value in fill_mask if value]
    if not outline_only or not visible_fill:
        raise TricmnBattleOverlayError("render requires non-empty outline and fill")
    outline_max = max(outline_only)
    fill_max = max(visible_fill)
    layer_counts = {"outline": Counter(), "fill": Counter()}
    output_ink = bytearray(expected)
    layered_heightfield = render_style == "source_wordart_3d_index_layers"
    dark_core_wordart = render_style in {
        "source_wordart_3d_dark_core",
        "source_wordart_tight_down_dark_core_layers",
    }
    tight_down_layers = render_style in {
        "source_wordart_tight_down_layers",
        "source_wordart_tight_down_dark_core_layers",
    }
    if render_style in {
        "source_wordart_3d",
        "source_wordart_3d_dark_core",
        "source_wordart_3d_heightfield",
        "source_wordart_3d_index_layers",
        "source_wordart_tight_down_layers",
        "source_wordart_tight_down_dark_core_layers",
    }:
        filtered_outline_mask = _coverage_floor(
            outline_mask,
            minimum=coverage_floor,
        )
        heightfield_report = None
        heightfield_core_silhouette = None
        heightfield_face_plateau_mask = None
        heightfield_halo_scores = None
        heightfield_side_scores = None
        if render_style in {
            "source_wordart_3d_heightfield",
            "source_wordart_3d_index_layers",
        }:
            if vector_outline_mask is None or vector_fill_mask is None:
                raise TricmnBattleOverlayError(
                    "height-field WordArt requires supersampled outline and fill"
                )
            surface = _heightfield_wordart_surface(
                vector_outline_mask,
                vector_fill_mask,
                width=width,
                height=height,
                factor=vector_effect_scale,
                shadow_offset_x=shadow_offset_x,
                shadow_offset_y=shadow_offset_y,
                glow_radius=glow_radius,
                bevel_width=heightfield_bevel_width,
                relief_strength=heightfield_relief_strength,
                ambient=heightfield_ambient,
                diffuse=heightfield_diffuse,
                specular=heightfield_specular,
            )
            full_silhouette = surface["full_silhouette"]
            heightfield_core_silhouette = _coverage_floor(
                surface["core_silhouette"], minimum=coverage_floor
            )
            fill_mask = surface["face_mask"]
            heightfield_face_plateau_mask = surface["face_plateau_mask"]
            scores = surface["face_scores"]
            heightfield_halo_scores = surface["halo_scores"]
            heightfield_side_scores = surface["side_scores"]
            heightfield_report = {
                key: value
                for key, value in surface.items()
                if key
                in {
                    "bevel_width_supersampled_pixels",
                    "extrusion_depth_supersampled_pixels",
                    "halo_width_supersampled_pixels",
                    "light_vector",
                }
            }
            silhouette = _coverage_floor(
                full_silhouette,
                minimum=coverage_floor,
            )
        else:
            _native_silhouette, scores = _directional_bevel_scores(
                filtered_outline_mask,
                fill_mask,
                width=width,
                height=height,
                shadow_offset_x=shadow_offset_x,
                shadow_offset_y=shadow_offset_y,
            )
        if (
            render_style
            in {
                "source_wordart_3d",
                "source_wordart_3d_dark_core",
                "source_wordart_tight_down_layers",
                "source_wordart_tight_down_dark_core_layers",
            }
            and vector_outline_mask is not None
        ):
            vector_width = width * vector_effect_scale
            vector_height = height * vector_effect_scale
            if (
                vector_effect_scale <= 1
                or len(vector_outline_mask) != vector_width * vector_height
            ):
                raise TricmnBattleOverlayError(
                    "vector effect mask geometry drift"
                )
            vector_silhouette = _directional_extrusion_silhouette(
                vector_outline_mask,
                width=vector_width,
                height=vector_height,
                shadow_offset_x=shadow_offset_x * vector_effect_scale,
                shadow_offset_y=shadow_offset_y * vector_effect_scale,
            )
            full_silhouette = box_downsample_grayscale(
                vector_silhouette,
                width=width,
                height=height,
                factor=vector_effect_scale,
            )
            full_silhouette = _add_indexed_glow(
                full_silhouette,
                width=width,
                height=height,
                radius=glow_radius,
            )
            silhouette = _coverage_floor(
                full_silhouette,
                minimum=coverage_floor,
            )
        elif render_style in {
            "source_wordart_3d",
            "source_wordart_3d_dark_core",
            "source_wordart_tight_down_layers",
            "source_wordart_tight_down_dark_core_layers",
        }:
            full_silhouette, _full_scores = _directional_bevel_scores(
                outline_mask,
                fill_mask,
                width=width,
                height=height,
                shadow_offset_x=shadow_offset_x,
                shadow_offset_y=shadow_offset_y,
            )
            silhouette, scores = _directional_bevel_scores(
                filtered_outline_mask,
                fill_mask,
                width=width,
                height=height,
                shadow_offset_x=shadow_offset_x,
                shadow_offset_y=shadow_offset_y,
            )
        core_visible = [
            local for local, coverage in enumerate(silhouette) if coverage
        ]
        unfiltered_anti_alias = _connected_mask_fringe(
            full_silhouette,
            silhouette,
            width=width,
            height=height,
        )
        edge_filtered_coverage = _pixel_edge_filter_coverage(
            full_silhouette,
            silhouette,
            width=width,
            height=height,
            radius=indexed_edge_filter_radius,
            coverage_ceiling=max(1, coverage_floor - 1),
        )
        anti_alias = _connected_mask_fringe(
            edge_filtered_coverage,
            silhouette,
            width=width,
            height=height,
        )
        unfiltered_anti_alias_set = set(unfiltered_anti_alias)
        edge_filter_added = tuple(
            local for local in anti_alias if local not in unfiltered_anti_alias_set
        )
        edge_filter_coverage_changed = tuple(
            local
            for local in anti_alias
            if edge_filtered_coverage[local] != full_silhouette[local]
        )
        visible = [*core_visible, *anti_alias]
        source_ink = bytes(value != 0 for value in source_rect)
        source_edge = _outer_edge_mask(source_ink, width=width, height=height)
        output_edge = _outer_edge_mask(silhouette, width=width, height=height)

        # The stock atlas is an old WordArt-style extrusion, not a monotonic
        # outline ramp. Its outermost boundary is a light reflected rim, the
        # dark 1..7 side wall sits *inside* that rim, and the 8..15 face ends in
        # a broad white plateau. Derive each source zone independently so all
        # shared CLUT banks retain that deliberately non-monotonic structure.
        observed_source_zone_counts = {
            "halo": Counter(
                value
                for local, value in enumerate(source_rect)
                if source_edge[local] and value
            ),
            "side": Counter(
                value
                for local, value in enumerate(source_rect)
                if not source_edge[local] and value in outline_indexes
            ),
            "face": Counter(
                value
                for local, value in enumerate(source_rect)
                if not source_edge[local] and value in fill_indexes
            ),
        }
        source_zone_counts = observed_source_zone_counts
        semantic_index_roles = None
        if tight_down_layers:
            if len(outline_indexes) != 7 or len(fill_indexes) != 8:
                raise TricmnBattleOverlayError(
                    "tight-down WordArt requires the native 1..7/8..15 index roles"
                )
            semantic_halo_indexes = outline_indexes[:4]
            semantic_side_indexes = (
                outline_indexes if dark_core_wordart else outline_indexes[4:]
            )
            semantic_index_roles = {
                "transparent": [0],
                "attached_halo": list(semantic_halo_indexes),
                (
                    "dark_stroke"
                    if dark_core_wordart
                    else "downward_side"
                ): list(semantic_side_indexes),
                "raised_face": list(fill_indexes),
            }
            source_zone_counts = {
                "halo": Counter(
                    value for value in source_rect if value in semantic_halo_indexes
                ),
                "side": Counter(
                    value for value in source_rect if value in semantic_side_indexes
                ),
                "face": Counter(
                    value for value in source_rect if value in fill_indexes
                ),
            }
        if any(not counts for counts in source_zone_counts.values()):
            raise TricmnBattleOverlayError(
                "source WordArt zones require halo, side and face indexes"
            )
        source_depths = _boundary_depths(
            source_ink,
            width=width,
            height=height,
            maximum=3,
        )
        semantic_halo_boundary_counts = None
        semantic_halo_fringe_counts = None
        semantic_halo_reserved_inner_index = None
        if tight_down_layers:
            # The stock 24px ability labels use the translucent 1..4 ramp by
            # boundary depth, not as one interchangeable outline histogram.
            # Indexes 1..3 dominate the outer boundary while the brighter 4
            # sits mainly one texel farther in.  Preserve that topology so a
            # wider filtered fringe becomes darker and softer instead of
            # promoting opaque index 4 onto the complete outer edge.
            semantic_halo_boundary_counts = Counter(
                source_rect[local]
                for local, depth in enumerate(source_depths)
                if depth == 1
                and source_rect[local] in semantic_halo_indexes
            )
            if not semantic_halo_boundary_counts:
                raise TricmnBattleOverlayError(
                    "tight-down WordArt source has no semantic halo boundary"
                )
            semantic_halo_reserved_inner_index = max(
                semantic_halo_boundary_counts
            )
            semantic_halo_fringe_counts = Counter(
                {
                    index: count
                    for index, count in semantic_halo_boundary_counts.items()
                    if index != semantic_halo_reserved_inner_index
                }
            )
            if not semantic_halo_fringe_counts:
                raise TricmnBattleOverlayError(
                    "tight-down WordArt source has no soft outer halo ramp"
                )

        if heightfield_core_silhouette is not None:
            output_zones = {
                "halo": [
                    local
                    for local in core_visible
                    if output_edge[local] or not heightfield_core_silhouette[local]
                ],
                "face": [
                    local
                    for local in core_visible
                    if (
                        not output_edge[local]
                        and heightfield_core_silhouette[local]
                        and fill_mask[local]
                    )
                ],
                "side": [
                    local
                    for local in core_visible
                    if (
                        not output_edge[local]
                        and heightfield_core_silhouette[local]
                        and not fill_mask[local]
                    )
                ],
                "anti_alias": list(anti_alias),
            }
        elif dark_core_wordart:
            # The compact status banners use the inverse material layout of
            # the large attack titles: the glyph body is the dark 1..7 layer
            # and the surrounding bevel is the bright 8..15 layer.  Preserve
            # that topology directly instead of letting a solid Chinese font
            # turn the complete glyph body into a noisy white face.
            output_zones = {
                "halo": [local for local in core_visible if output_edge[local]],
                "face": [
                    local
                    for local in core_visible
                    if not output_edge[local] and not fill_mask[local]
                ],
                "side": [
                    local
                    for local in core_visible
                    if not output_edge[local] and fill_mask[local]
                ],
                "anti_alias": list(anti_alias),
            }
        else:
            output_zones = {
                "halo": [local for local in core_visible if output_edge[local]],
                "face": [
                    local
                    for local in core_visible
                    if not output_edge[local] and fill_mask[local]
                ],
                "side": [
                    local
                    for local in core_visible
                    if not output_edge[local] and not fill_mask[local]
                ],
                "anti_alias": list(anti_alias),
            }
        if any(not output_zones[zone_name] for zone_name in ("halo", "side", "face")):
            raise TricmnBattleOverlayError(
                "output WordArt zones require halo, side and face pixels"
            )
        zone_scores = {
            "halo": (
                heightfield_halo_scores
                if heightfield_halo_scores is not None
                else [0] * expected
            ),
            "face": scores,
            "side": (
                heightfield_side_scores
                if heightfield_side_scores is not None
                else [0] * expected
            ),
        }
        for local in output_zones["halo"]:
            if heightfield_halo_scores is not None:
                if zone_scores["halo"][local] == 0:
                    zone_scores["halo"][local] = full_silhouette[local] * 257
                continue
            local_x = local % width
            local_y = local // width
            gradient = _directional_mask_gradient(
                silhouette,
                width=width,
                height=height,
                x=local_x,
                y=local_y,
            )
            # The stock outer reflection is shallowest at top-left and most
            # visible below/right of the dark extrusion. Reverse the local
            # silhouette gradient so the higher light-rim indexes gather on
            # that lower-right edge instead of ringing the glyph uniformly.
            zone_scores["halo"][local] = (
                silhouette[local] - halo_direction_weight * gradient
            )
        for local in output_zones["side"]:
            local_x = local % width
            local_y = local // width
            distance = _distance_to_mask(
                fill_mask,
                width=width,
                height=height,
                x=local_x,
                y=local_y,
            )
            gradient = _directional_mask_gradient(
                fill_mask,
                width=width,
                height=height,
                x=local_x,
                y=local_y,
            )
            # The side wall is darkest near its outer reflected rim and rises
            # towards the white face. A down-right fill gradient identifies
            # the top-left bevel; its inverse identifies the deep lower-right
            # extrusion seen in the Japanese WordArt texture.
            if heightfield_side_scores is not None:
                # Use distance from the raised face as the primary depth axis.
                # The downsampled height-field score supplies the continuous
                # secondary light variation inside each depth band.
                zone_scores["side"][local] = (
                    (8 - min(distance, 7)) * 65536
                    + heightfield_side_scores[local]
                    + silhouette[local]
                    + side_direction_weight * gradient
                )
            else:
                zone_scores["side"][local] = (
                    (8 - min(distance, 7)) * 1024
                    + silhouette[local]
                    + side_direction_weight * gradient
                )

        heightfield_side_score_counts = (
            Counter(
                zone_scores["side"][local]
                for local in output_zones["side"]
            )
            if heightfield_report is not None
            else Counter()
        )

        if layered_heightfield:
            if inverse_tex1_palette is not None:
                raise TricmnBattleOverlayError(
                    "index-layer WordArt must not use TEX1 inverse quantization"
                )
            if heightfield_core_silhouette is None:
                raise TricmnBattleOverlayError(
                    "index-layer WordArt requires a height-field core"
                )

            # Build the native PSMT4 image as ordered material layers.  Palette
            # indexes are semantic roles here, not interchangeable greys: 1..7
            # are the recessed extrusion, 12 is the soft outer transition, 14
            # is the reflected hard rim, 13 is the face bevel and 15 is the
            # flat raised plateau.  Each mask is assigned once as a whole
            # layer, so no result-level pixel repair or display-space inverse
            # search can introduce a dark index on the outside edge afterwards.
            source_light_counts = {
                index: count
                for index, count in source_zone_counts["halo"].items()
                if index in fill_indexes
            }
            if len(source_light_counts) < 2:
                raise TricmnBattleOverlayError(
                    "source WordArt needs distinct soft-rim and hard-rim indexes"
                )
            # A few source glyph corners contain isolated brighter/darker
            # transition texels.  They are coverage samples, not additional
            # material layers, so choosing merely by numeric index can promote
            # a two-pixel outlier into the complete anti-alias fringe.  Infer
            # the two rim roles from their source populations instead: the
            # dominant light layer is the hard reflected rim and the dominant
            # remaining light layer is the soft outside transition.
            hard_rim_index = max(
                source_light_counts,
                key=lambda index: (source_light_counts[index], index),
            )
            soft_fringe_index = max(
                (
                    index
                    for index in source_light_counts
                    if index != hard_rim_index
                ),
                key=lambda index: (source_light_counts[index], index),
            )
            flat_face_index = max(source_zone_counts["face"])
            if flat_face_index != max(fill_indexes):
                raise TricmnBattleOverlayError(
                    "source WordArt flat face does not use the brightest index"
                )
            face_rim_counts = {
                index: count
                for index, count in source_zone_counts["face"].items()
                if index in fill_indexes and index != flat_face_index and count > 0
            }
            if not face_rim_counts:
                raise TricmnBattleOverlayError(
                    "source WordArt face needs a secondary light index"
                )
            face_rim_index = max(
                face_rim_counts,
                key=lambda index: (face_rim_counts[index], index),
            )
            if heightfield_face_plateau_mask is None:
                raise TricmnBattleOverlayError(
                    "index-layer WordArt requires a flat-face plateau mask"
                )
            source_face_layer_counts = {
                face_rim_index: sum(face_rim_counts.values()),
                flat_face_index: source_zone_counts["face"][flat_face_index],
            }
            face_layer_assignments = _source_quantile_assignments(
                output_zones["face"],
                heightfield_face_plateau_mask,
                source_face_layer_counts,
            )
            flat_face_locals = {
                local
                for local, palette_index in face_layer_assignments.items()
                if palette_index == flat_face_index
            }
            face_rim_locals = set(face_layer_assignments) - flat_face_locals
            if not flat_face_locals or not face_rim_locals:
                raise TricmnBattleOverlayError(
                    "index-layer WordArt face rim and plateau must both be visible"
                )

            assignments = _source_continuous_score_assignments(
                output_zones["side"],
                zone_scores["side"],
                {index: 1 for index in outline_indexes},
            )
            assignments.update(
                {local: soft_fringe_index for local in output_zones["anti_alias"]}
            )
            assignments.update(
                {local: hard_rim_index for local in output_zones["halo"]}
            )
            assignments.update(face_layer_assignments)
            if len(assignments) != len(visible):
                raise TricmnBattleOverlayError(
                    "index-layer WordArt assignments did not close"
                )

            source_depths = _boundary_depths(
                source_ink,
                width=width,
                height=height,
                maximum=3,
            )
            source_index_depth_counts = {
                palette_index: Counter(
                    source_depths[local]
                    for local, value in enumerate(source_rect)
                    if value == palette_index
                )
                for palette_index in sorted((*outline_indexes, *fill_indexes))
            }
            output_assignment_mask = bytes(
                local in assignments for local in range(expected)
            )
            output_depths = _boundary_depths(
                output_assignment_mask,
                width=width,
                height=height,
                maximum=3,
            )
            outer_boundary_counts = Counter(
                assignments[local]
                for local, depth in enumerate(output_depths)
                if depth == 1
            )
            if not outer_boundary_counts or not set(outer_boundary_counts) <= {
                soft_fringe_index,
                hard_rim_index,
            }:
                raise TricmnBattleOverlayError(
                    "index-layer WordArt put a dark index on the outer boundary"
                )
            dark_depths = [
                output_depths[local]
                for local, palette_index in assignments.items()
                if palette_index in outline_indexes
            ]
            if not dark_depths or min(dark_depths) <= 1:
                raise TricmnBattleOverlayError(
                    "index-layer WordArt extrusion reached the outer boundary"
                )

            zone_output_counts = {
                zone_name: Counter(assignments[local] for local in locals_)
                for zone_name, locals_ in output_zones.items()
            }
            for local in visible:
                palette_index = assignments[local]
                local_x = local % width
                local_y = local // width
                indexes[(y + local_y) * picture_width + x + local_x] = palette_index
                output_ink[local] = 1
                layer = "outline" if palette_index in outline_indexes else "fill"
                layer_counts[layer][palette_index] += 1

            return {
                "render_style": render_style,
                "dark_core_material_layout": dark_core_wordart,
                "shadow_offset": [shadow_offset_x, shadow_offset_y],
                "coverage_floor": coverage_floor,
                "side_direction_weight": side_direction_weight,
                "halo_direction_weight": halo_direction_weight,
                "vector_effects_before_downsample": vector_outline_mask is not None,
                "vector_effect_scale": vector_effect_scale,
                "vector_outline_mask_sha256": sha256_bytes(vector_outline_mask),
                "vector_fill_mask_sha256": sha256_bytes(vector_fill_mask),
                "heightfield_surface": heightfield_report,
                "heightfield_palette_quantization_uses_source_zones": False,
                "heightfield_side_uses_continuous_source_ramp": True,
                "heightfield_side_score_unique_count": len(
                    heightfield_side_score_counts
                ),
                "heightfield_flat_top_rim": True,
                "heightfield_flat_top_palette_index": hard_rim_index,
                "heightfield_flat_top_output_pixel_count": len(
                    output_zones["halo"]
                ),
                "heightfield_face_rim_palette_index": face_rim_index,
                "heightfield_face_rim_output_pixel_count": len(face_rim_locals),
                "heightfield_face_layer_source_index_counts": {
                    str(index): count
                    for index, count in sorted(source_face_layer_counts.items())
                },
                "heightfield_flat_face": True,
                "heightfield_flat_face_palette_index": flat_face_index,
                "heightfield_flat_face_output_pixel_count": len(flat_face_locals),
                "inverse_tex1_enabled": False,
                "inverse_tex1": None,
                "indexed_edge_filter_radius": indexed_edge_filter_radius,
                "indexed_edge_filter_enabled": indexed_edge_filter_radius > 0,
                "indexed_edge_filter_added_pixel_count": len(edge_filter_added),
                "indexed_edge_filter_changed_coverage_pixel_count": len(
                    edge_filter_coverage_changed
                ),
                "anti_alias_uses_source_soft_coverage_ramp": False,
                "anti_alias_output_index_counts": {
                    str(index): count
                    for index, count in sorted(
                        zone_output_counts["anti_alias"].items()
                    )
                },
                "index_layer_sequence": [
                    "transparent:0",
                    f"extrusion:{outline_indexes[0]}..{outline_indexes[-1]}",
                    f"soft-fringe:{soft_fringe_index}",
                    f"hard-rim:{hard_rim_index}",
                    f"face-rim:{face_rim_index}",
                    f"flat-face:{flat_face_index}",
                ],
                "index_layers_constructed_before_writeback": True,
                "result_level_pixel_repair_enabled": False,
                "outer_boundary_uses_light_indexes_only": True,
                "outer_boundary_output_index_counts": {
                    str(index): count
                    for index, count in sorted(outer_boundary_counts.items())
                },
                "dark_index_minimum_boundary_depth": min(dark_depths),
                "source_zone_index_counts": {
                    zone_name: {
                        str(index): count
                        for index, count in sorted(counts.items())
                    }
                    for zone_name, counts in source_zone_counts.items()
                },
                "source_index_boundary_depth_counts": {
                    str(index): {
                        str(depth): count
                        for depth, count in sorted(counts.items())
                    }
                    for index, counts in source_index_depth_counts.items()
                },
                "output_zone_pixel_counts": {
                    zone_name: len(locals_)
                    for zone_name, locals_ in output_zones.items()
                },
                "output_zone_index_counts": {
                    zone_name: {
                        str(index): count
                        for index, count in sorted(counts.items())
                    }
                    for zone_name, counts in zone_output_counts.items()
                },
                "outline_mask_sha256": sha256_bytes(outline_mask),
                "outline_mask_nonzero_pixel_count": sum(
                    value > 0 for value in outline_mask
                ),
                "outline_only_pixel_count": len(outline_only),
                "fill_mask_sha256": sha256_bytes(fill_mask),
                "fill_mask_nonzero_pixel_count": len(visible_fill),
                "output_ink_mask_sha256": sha256_bytes(output_ink),
                "output_ink_pixel_count": sum(output_ink),
                "indexed_layer_counts": {
                    layer: {
                        str(index): count
                        for index, count in sorted(counts.items())
                    }
                    for layer, counts in layer_counts.items()
                },
            }

        assignments = {}
        for zone_name in ("halo", "side", "face"):
            if heightfield_report is not None and zone_name == "side":
                assignments.update(
                    _source_continuous_score_assignments(
                        output_zones[zone_name],
                        zone_scores[zone_name],
                        source_zone_counts[zone_name],
                    )
                )
            else:
                assignments.update(
                    _source_quantile_assignments(
                        output_zones[zone_name],
                        zone_scores[zone_name],
                        (
                            semantic_halo_boundary_counts
                            if tight_down_layers and zone_name == "halo"
                            else source_zone_counts[zone_name]
                        ),
                    )
                )
        if anti_alias:
            if tight_down_layers:
                assignments.update(
                    _source_soft_fringe_assignments(
                        anti_alias,
                        edge_filtered_coverage,
                        semantic_halo_boundary_counts,
                        coverage_ceiling=max(1, coverage_floor - 1),
                        reserved_inner_rim_index=(
                            semantic_halo_reserved_inner_index
                        ),
                    )
                )
            elif heightfield_report is not None:
                assignments.update(
                    _source_soft_fringe_assignments(
                        anti_alias,
                        edge_filtered_coverage,
                        source_zone_counts["halo"],
                        coverage_ceiling=max(1, coverage_floor - 1),
                        reserved_inner_rim_index=max(
                            source_zone_counts["halo"]
                        ),
                    )
                )
            else:
                assignments.update(
                    _source_quantile_assignments(
                        anti_alias,
                        edge_filtered_coverage,
                        source_zone_counts["halo"],
                    )
                )

        # The Japanese texture uses a measurable two-layer reflected rim: its
        # first boundary layer is entirely 8..15, and its second layer remains
        # majority-light before the dark extrusion starts. Preserve that
        # per-label ratio instead of guessing a larger stroke radius, which
        # would incorrectly turn the extra pixels into more 1..7 side wall.
        source_index_depth_counts = {
            palette_index: Counter(
                source_depths[local]
                for local, value in enumerate(source_rect)
                if value == palette_index
            )
            for palette_index in sorted((*outline_indexes, *fill_indexes))
        }
        output_assignment_mask = bytes(
            local in assignments for local in range(expected)
        )
        output_depths = _boundary_depths(
            output_assignment_mask,
            width=width,
            height=height,
            maximum=3,
        )
        semantic_outer_boundary_reassigned_count = 0
        if tight_down_layers:
            semantic_outer_boundary = [
                local
                for local, depth in enumerate(output_depths)
                if depth == 1
            ]
            semantic_outer_scores = bytearray(expected)
            for local in semantic_outer_boundary:
                semantic_outer_scores[local] = (
                    edge_filtered_coverage[local]
                    if edge_filtered_coverage[local]
                    else full_silhouette[local]
                )
            semantic_outer_assignments = _source_quantile_assignments(
                semantic_outer_boundary,
                semantic_outer_scores,
                semantic_halo_fringe_counts,
            )
            semantic_outer_boundary_reassigned_count = sum(
                assignments[local] != palette_index
                for local, palette_index in semantic_outer_assignments.items()
            )
            assignments.update(semantic_outer_assignments)
        bright_edge_character_spans: tuple[tuple[int, int], ...] = ()
        bright_edge_selected_spans: tuple[tuple[int, int], ...] = ()
        bright_edge_promoted_locals: tuple[int, ...] = ()
        if bright_edge_character_indexes:
            if not dark_core_wordart:
                raise TricmnBattleOverlayError(
                    "per-character bright edge requires dark-core WordArt"
                )
            if bright_edge_minimum_index not in fill_indexes:
                raise TricmnBattleOverlayError(
                    "per-character bright edge must use the light palette ramp"
                )
            bright_edge_character_spans = _character_column_spans(
                fill_mask,
                width=width,
                height=height,
            )
            if max(bright_edge_character_indexes) >= len(
                bright_edge_character_spans
            ):
                raise TricmnBattleOverlayError(
                    "per-character bright edge index exceeds rendered text"
                )
            bright_edge_selected_spans = tuple(
                bright_edge_character_spans[index]
                for index in bright_edge_character_indexes
            )
            bright_edge_promoted_locals = tuple(
                local
                for local in output_zones["halo"]
                if assignments[local] in fill_indexes
                and assignments[local] < bright_edge_minimum_index
                and any(
                    left <= local % width < right
                    for left, right in bright_edge_selected_spans
                )
            )
            for local in bright_edge_promoted_locals:
                assignments[local] = bright_edge_minimum_index
        boundary_profiles = {}
        boundary_lightened_pixel_count = 0
        for depth in (1, 2):
            source_locals = [
                local for local, value in enumerate(source_depths) if value == depth
            ]
            output_locals = [
                local for local, value in enumerate(output_depths) if value == depth
            ]
            source_light_counts = (
                Counter()
                if tight_down_layers
                else Counter(
                    source_rect[local]
                    for local in source_locals
                    if source_rect[local] in fill_indexes
                )
            )
            source_total = len(source_locals)
            output_total = len(output_locals)
            target_light = (
                (sum(source_light_counts.values()) * output_total + source_total // 2)
                // source_total
                if source_total and output_total
                else 0
            )
            before_light = sum(
                assignments[local] in fill_indexes for local in output_locals
            )
            candidates = [
                local
                for local in output_locals
                if assignments[local] in outline_indexes
            ]
            candidates.sort(
                key=lambda local: (
                    _directional_mask_gradient(
                        fill_mask,
                        width=width,
                        height=height,
                        x=local % width,
                        y=local // width,
                    ),
                    full_silhouette[local],
                    -(local // width),
                    -local,
                ),
                reverse=True,
            )
            convert = candidates[: max(0, target_light - before_light)]
            if convert and source_light_counts:
                conversion_scores = [0] * expected
                for rank, local in enumerate(convert):
                    conversion_scores[local] = len(convert) - rank
                assignments.update(
                    _source_quantile_assignments(
                        convert,
                        conversion_scores,
                        source_light_counts,
                    )
                )
            boundary_lightened_pixel_count += len(convert)
            after_light = sum(
                assignments[local] in fill_indexes for local in output_locals
            )
            boundary_profiles[str(depth)] = {
                "source_total": source_total,
                "source_light": sum(source_light_counts.values()),
                "output_total": output_total,
                "target_light": target_light,
                "output_light_before_balance": before_light,
                "output_light_after_balance": after_light,
                "dark_pixels_converted_to_source_light_indexes": len(convert),
                "source_light_index_counts": {
                    str(index): count
                    for index, count in sorted(source_light_counts.items())
                },
            }

        upper_left_minimum_index = upper_left_highlight_minimum_index
        if upper_left_minimum_index not in (0, *fill_indexes):
            raise TricmnBattleOverlayError(
                "upper-left highlight minimum index must be zero or use the light ramp"
            )
        upper_left_source_counts = Counter(
            {
                index: count
                for index, count in source_zone_counts["halo"].items()
                if upper_left_minimum_index
                and index >= upper_left_minimum_index
            }
        )
        if upper_left_minimum_index and not upper_left_source_counts:
            raise TricmnBattleOverlayError(
                "source halo has no upper-left highlight indexes"
            )
        anti_alias_set = set(anti_alias)
        upper_left_highlight = [
            local
            for local, palette_index in assignments.items()
            if local not in anti_alias_set
            and upper_left_minimum_index
            and 1 <= output_depths[local] <= 3
            and palette_index < upper_left_minimum_index
            and _upper_left_exposed_at_depth(
                output_assignment_mask,
                width=width,
                height=height,
                x=local % width,
                y=local // width,
                depth=output_depths[local],
            )
        ]
        if upper_left_highlight:
            upper_left_scores = [0] * expected
            for local in upper_left_highlight:
                upper_left_scores[local] = (
                    (4 - output_depths[local]) * 1024
                    + full_silhouette[local]
                )
            assignments.update(
                _source_quantile_assignments(
                    upper_left_highlight,
                    upper_left_scores,
                    upper_left_source_counts,
                )
            )
        flat_top_source_counts = Counter()
        flat_top_output_locals: list[int] = []
        flat_top_palette_index = None
        if heightfield_report is not None and heightfield_flat_top_rim:
            for local, palette_index in enumerate(source_rect):
                if source_depths[local] != 1 or palette_index not in fill_indexes:
                    continue
                local_x = local % width
                local_y = local // width
                if local_y == 0 or not source_ink[(local_y - 1) * width + local_x]:
                    flat_top_source_counts[palette_index] += 1
            if not flat_top_source_counts:
                raise TricmnBattleOverlayError(
                    "source WordArt has no top-facing light rim"
                )
            flat_top_palette_index = max(
                flat_top_source_counts,
                key=lambda index: (flat_top_source_counts[index], index),
            )
            for local in assignments:
                if (
                    local in anti_alias_set
                    or not heightfield_core_silhouette[local]
                ):
                    continue
                local_x = local % width
                local_y = local // width
                if (
                    local_y == 0
                    or not heightfield_core_silhouette[
                        (local_y - 1) * width + local_x
                    ]
                ):
                    assignments[local] = flat_top_palette_index
                    flat_top_output_locals.append(local)
        flat_face_source_counts = Counter()
        flat_face_output_locals: list[int] = []
        flat_face_palette_index = None
        if heightfield_report is not None and heightfield_flat_face:
            if heightfield_face_plateau_mask is None:
                raise TricmnBattleOverlayError(
                    "flat-face WordArt requires a height-field plateau mask"
                )
            flat_face_source_counts.update(source_zone_counts["face"])
            if not flat_face_source_counts:
                raise TricmnBattleOverlayError(
                    "source WordArt has no raised-face plateau"
                )
            flat_face_palette_index = max(
                flat_face_source_counts,
                key=lambda index: (flat_face_source_counts[index], index),
            )
            flat_face_output_locals = [
                local
                for local in output_zones["face"]
                if heightfield_face_plateau_mask[local] >= 128
            ]
            if not flat_face_output_locals:
                raise TricmnBattleOverlayError(
                    "localized WordArt has no raised-face plateau"
                )
            for local in flat_face_output_locals:
                assignments[local] = flat_face_palette_index
        if anti_alias and heightfield_report is not None:
            # Directional highlights and the flat-top pass operate on the
            # solid rim only.  Reassert the coverage-derived outer transition
            # afterwards so no later boundary operation can harden it.
            assignments.update(
                _source_soft_fringe_assignments(
                    anti_alias,
                    edge_filtered_coverage,
                    source_zone_counts["halo"],
                    coverage_ceiling=max(1, coverage_floor - 1),
                    reserved_inner_rim_index=max(
                        source_zone_counts["halo"]
                    ),
                )
            )
        small_dark_components = _small_palette_components(
            assignments,
            width=width,
            height=height,
            palette_indexes=set(outline_indexes),
            minimum_size=dark_component_minimum_pixels,
        )
        dark_speckle_pixels_converted = 0
        dark_speckle_cleaned_locals: set[int] = set()
        for component in small_dark_components:
            neighbouring_light = Counter()
            for local in component:
                local_x = local % width
                local_y = local // width
                for neighbour_y in range(
                    max(0, local_y - 1), min(height, local_y + 2)
                ):
                    for neighbour_x in range(
                        max(0, local_x - 1), min(width, local_x + 2)
                    ):
                        neighbour = neighbour_y * width + neighbour_x
                        palette_index = assignments.get(neighbour, 0)
                        if palette_index in fill_indexes:
                            neighbouring_light[palette_index] += 1
            if neighbouring_light:
                replacement = max(
                    neighbouring_light,
                    key=lambda index: (neighbouring_light[index], index),
                )
            else:
                replacement = max(
                    source_zone_counts["halo"],
                    key=lambda index: (
                        source_zone_counts["halo"][index],
                        index,
                    ),
                )
            for local in component:
                assignments[local] = replacement
                dark_speckle_cleaned_locals.add(local)
                dark_speckle_pixels_converted += 1
        remaining_small_dark_components = _small_palette_components(
            assignments,
            width=width,
            height=height,
            palette_indexes=set(outline_indexes),
            minimum_size=dark_component_minimum_pixels,
        )
        if remaining_small_dark_components:
            raise TricmnBattleOverlayError(
                "dark speckle cleanup did not close"
            )

        inverse_tex1_report = None
        if inverse_tex1_palette is not None:
            inverse_layer_projection_count = 0
            inverse_halo_choices = tuple(sorted(source_zone_counts["halo"]))
            for local in output_zones["halo"]:
                current_index = assignments[local]
                if current_index in inverse_halo_choices:
                    continue
                current_luma = _rgba_luminance(
                    inverse_tex1_palette[current_index]
                )
                assignments[local] = min(
                    inverse_halo_choices,
                    key=lambda index: (
                        abs(
                            _rgba_luminance(inverse_tex1_palette[index])
                            - current_luma
                        ),
                        index,
                    ),
                )
                dark_speckle_cleaned_locals.add(local)
                inverse_layer_projection_count += 1
            inverse_dark_topology = {
                local: assignments[local] in outline_indexes
                for local in visible
            }
            native_target = _continuous_wordart_target(
                width=width,
                height=height,
                assignments=assignments,
                output_zones=output_zones,
                zone_scores=zone_scores,
                source_zone_counts=source_zone_counts,
                anti_alias=anti_alias,
                edge_filtered_coverage=edge_filtered_coverage,
                coverage_floor=coverage_floor,
                flat_top_output_locals=flat_top_output_locals,
                flat_face_output_locals=flat_face_output_locals,
                upper_left_highlight=upper_left_highlight,
                upper_left_minimum_index=upper_left_minimum_index,
                palette=inverse_tex1_palette,
            )
            target_display = simulate_tex1_bilinear_continuous_rgba(
                native_target,
                width=width,
                height=height,
                scale=inverse_tex1_scale,
            )
            initial_indexes = bytes(
                assignments.get(local, 0) for local in range(expected)
            )
            allowed_indexes: dict[int, tuple[int, ...]] = {}
            halo_choices = tuple(sorted(source_zone_counts["halo"]))
            soft_halo_choices = tuple(
                index for index in halo_choices if index != max(halo_choices)
            )
            for zone_name in ("halo", "face", "side"):
                if zone_name == "halo":
                    base_choices = halo_choices
                elif zone_name == "face":
                    base_choices = fill_indexes
                else:
                    base_choices = outline_indexes
                for local in output_zones[zone_name]:
                    allowed_indexes[local] = tuple(
                        dict.fromkeys((*base_choices, assignments[local]))
                    )
            for local in anti_alias:
                allowed_indexes[local] = tuple(
                    dict.fromkeys((*soft_halo_choices, assignments[local]))
                )
            if upper_left_minimum_index:
                upper_left_choices = tuple(
                    index
                    for index in fill_indexes
                    if index >= upper_left_minimum_index
                )
                for local in upper_left_highlight:
                    existing_choices = allowed_indexes[local]
                    highlighted_choices = tuple(
                        index
                        for index in existing_choices
                        if index in upper_left_choices
                    )
                    allowed_indexes[local] = tuple(
                        dict.fromkeys(
                            (*highlighted_choices, assignments[local])
                        )
                    )
            for local in flat_top_output_locals:
                allowed_indexes[local] = (assignments[local],)
            for local in flat_face_output_locals:
                allowed_indexes[local] = (assignments[local],)
            # Cleanup is a hard topology constraint, not an aesthetic hint.
            # Reopening those sites to the dark side ramp lets coordinate
            # descent recreate exactly the isolated black pixels removed just
            # above, even when its display-space MSE becomes microscopically
            # lower.  Keep the projected light value fixed.
            for local in dark_speckle_cleaned_locals:
                allowed_indexes[local] = (assignments[local],)
            # Keep the authored layer topology exact.  A PSMT4 index is not a
            # free RGB sample: 1..7 are the recessed/side ramp while 8..15 are
            # the reflected rim and raised face.  Allowing one texel to cross
            # that boundary can improve aggregate MSE but produces a visible
            # one-pixel black notch after TEX1 filtering.
            for local, choices in tuple(allowed_indexes.items()):
                dark = inverse_dark_topology[local]
                same_layer = tuple(
                    index
                    for index in choices
                    if (index in outline_indexes) == dark
                )
                if assignments[local] not in same_layer:
                    raise TricmnBattleOverlayError(
                        "TEX1 inverse layer-topology lock rejected source index"
                    )
                allowed_indexes[local] = same_layer
            protected_edges = []
            visible_set = set(visible)
            for local in visible:
                local_x = local % width
                local_y = local // width
                for other in (
                    local + 1 if local_x + 1 < width else -1,
                    local + width if local_y + 1 < height else -1,
                ):
                    if (
                        other in visible_set
                        and min(output_depths[local], output_depths[other]) <= 2
                    ):
                        protected_edges.append((local, other))
            try:
                optimized, inverse_report = inverse_quantize_tex1_bilinear(
                    target_display,
                    initial_indexes,
                    width=width,
                    height=height,
                    palette=inverse_tex1_palette,
                    allowed_indexes=allowed_indexes,
                    scale=inverse_tex1_scale,
                    passes=inverse_tex1_passes,
                    adjacency_threshold=inverse_tex1_adjacency_threshold,
                    adjacency_weight=inverse_tex1_adjacency_weight,
                    protected_edges=protected_edges,
                    protected_adjacency_threshold=(
                        inverse_tex1_adjacency_threshold
                    ),
                )
            except GSIndexedTextureError as error:
                raise TricmnBattleOverlayError(
                    f"TEX1 inverse quantization failed: {error}"
                ) from error
            for local in visible:
                assignments[local] = optimized[local]
            inverse_tex1_report = {
                "scale": inverse_report.scale,
                "passes_requested": inverse_report.passes_requested,
                "passes_completed": inverse_report.passes_completed,
                "changed_texels": inverse_report.changed_texels,
                "initial_weighted_mse": inverse_report.initial_weighted_mse,
                "final_weighted_mse": inverse_report.final_weighted_mse,
                "abrupt_pairs_before": inverse_report.abrupt_pairs_before,
                "abrupt_pairs_after": inverse_report.abrupt_pairs_after,
                "protected_edge_count": len(protected_edges),
                "protected_abrupt_pairs_before": (
                    inverse_report.protected_abrupt_pairs_before
                ),
                "protected_abrupt_pairs_after": (
                    inverse_report.protected_abrupt_pairs_after
                ),
                "protected_abrupt_pairs_monotonic": True,
                "pre_inverse_layer_projection_count": (
                    inverse_layer_projection_count
                ),
                "palette_resolved_before_bilinear": True,
                "source_silhouette_locked": True,
                "flat_top_locked": True,
                "flat_face_locked": True,
            }

            post_inverse_dark_components = _small_palette_components(
                assignments,
                width=width,
                height=height,
                palette_indexes=set(outline_indexes),
                minimum_size=dark_component_minimum_pixels,
            )
            if post_inverse_dark_components:
                component_sizes = tuple(
                    len(component) for component in post_inverse_dark_components
                )
                component_origins = tuple(
                    (component[0] % width, component[0] // width)
                    for component in post_inverse_dark_components
                )
                raise TricmnBattleOverlayError(
                    "TEX1 inverse quantization introduced dark speckles: "
                    f"sizes={component_sizes}, origins={component_origins}"
                )
        for depth, profile in boundary_profiles.items():
            depth_value = int(depth)
            depth_locals = [
                local
                for local, value in enumerate(output_depths)
                if value == depth_value
            ]
            profile["output_light_after_directional_guard"] = sum(
                assignments[local] in fill_indexes for local in depth_locals
            )

        zone_output_counts = {
            zone_name: Counter(assignments[local] for local in locals_)
            for zone_name, locals_ in output_zones.items()
        }
        outer_boundary_output_counts = Counter(
            assignments[local]
            for local, depth in enumerate(output_depths)
            if depth == 1
        )
        outer_boundary_uses_semantic_halo_only = (
            tight_down_layers
            and set(outer_boundary_output_counts)
            <= set(source_zone_counts["halo"])
        )
        for local in visible:
            palette_index = assignments[local]
            local_x = local % width
            local_y = local // width
            indexes[(y + local_y) * picture_width + x + local_x] = palette_index
            output_ink[local] = 1
            layer = "outline" if palette_index in outline_indexes else "fill"
            layer_counts[layer][palette_index] += 1

        core_actual_counts = Counter(
            assignments[local] for local in core_visible
        )
        ideal_counts = _scaled_source_index_counts(
            source_rect,
            output_ink_pixel_count=len(core_visible),
            palette_indexes=tuple(sorted((*outline_indexes, *fill_indexes))),
        )
        return {
            "render_style": render_style,
            "dark_core_material_layout": dark_core_wordart,
            "semantic_index_roles_locked": tight_down_layers,
            "semantic_index_roles": semantic_index_roles,
            "semantic_halo_uses_source_boundary_depth_profile": (
                tight_down_layers
            ),
            "semantic_halo_source_boundary_index_counts": (
                {
                    str(index): count
                    for index, count in sorted(
                        semantic_halo_boundary_counts.items()
                    )
                }
                if semantic_halo_boundary_counts is not None
                else None
            ),
            "semantic_halo_outer_fringe_index_counts": (
                {
                    str(index): count
                    for index, count in sorted(
                        semantic_halo_fringe_counts.items()
                    )
                }
                if semantic_halo_fringe_counts is not None
                else None
            ),
            "semantic_halo_reserved_inner_index": (
                semantic_halo_reserved_inner_index
            ),
            "semantic_outer_boundary_reassigned_count": (
                semantic_outer_boundary_reassigned_count
            ),
            "index_layer_sequence": (
                [
                    "transparent:0",
                    f"attached-halo:{outline_indexes[0]}..{outline_indexes[3]}",
                    (
                        f"dark-stroke:{outline_indexes[0]}..{outline_indexes[-1]}"
                        if dark_core_wordart
                        else f"downward-side:{outline_indexes[4]}..{outline_indexes[-1]}"
                    ),
                    f"raised-face:{fill_indexes[0]}..{fill_indexes[-1]}",
                ]
                if tight_down_layers
                else None
            ),
            "shadow_offset": [shadow_offset_x, shadow_offset_y],
            "coverage_floor": coverage_floor,
            "side_direction_weight": side_direction_weight,
            "halo_direction_weight": halo_direction_weight,
            "anti_alias_uses_connected_low_coverage_fringe": True,
            "anti_alias_uses_source_halo_quantiles": (
                heightfield_report is None
            ),
            "anti_alias_uses_source_soft_coverage_ramp": (
                heightfield_report is not None
            ),
            "anti_alias_reserved_inner_rim_index": (
                max(source_zone_counts["halo"])
                if heightfield_report is not None and anti_alias
                else None
            ),
            "anti_alias_output_index_counts": {
                str(index): count
                for index, count in sorted(
                    Counter(assignments[local] for local in anti_alias).items()
                )
            },
            "indexed_edge_filter_radius": indexed_edge_filter_radius,
            "indexed_edge_filter_enabled": indexed_edge_filter_radius > 0,
            "indexed_edge_filter_added_pixel_count": len(edge_filter_added),
            "indexed_edge_filter_changed_coverage_pixel_count": len(
                edge_filter_coverage_changed
            ),
            "indexed_edge_filter_added_output_index_counts": {
                str(index): count
                for index, count in sorted(
                    Counter(assignments[local] for local in edge_filter_added).items()
                )
            },
            "vector_effects_before_downsample": vector_outline_mask is not None,
            "vector_effect_scale": (
                vector_effect_scale if vector_outline_mask is not None else 1
            ),
            "vector_outline_mask_sha256": (
                sha256_bytes(vector_outline_mask)
                if vector_outline_mask is not None
                else None
            ),
            "vector_fill_mask_sha256": (
                sha256_bytes(vector_fill_mask)
                if vector_fill_mask is not None
                else None
            ),
            "heightfield_surface": heightfield_report,
            "heightfield_palette_quantization_uses_source_zones": (
                heightfield_report is not None
            ),
            "heightfield_side_score_unique_count": len(
                heightfield_side_score_counts
            ),
            "heightfield_side_score_largest_equal_group": max(
                heightfield_side_score_counts.values(), default=0
            ),
            "heightfield_side_score_most_common": (
                heightfield_side_score_counts.most_common(1)[0][0]
                if heightfield_side_score_counts
                else None
            ),
            "heightfield_side_uses_continuous_source_ramp": (
                heightfield_report is not None
            ),
            "heightfield_flat_top_rim": heightfield_flat_top_rim,
            "heightfield_flat_top_source_index_counts": {
                str(index): count
                for index, count in sorted(flat_top_source_counts.items())
            },
            "heightfield_flat_top_palette_index": flat_top_palette_index,
            "heightfield_flat_top_output_pixel_count": len(
                flat_top_output_locals
            ),
            "heightfield_flat_face": heightfield_flat_face,
            "heightfield_flat_face_source_index_counts": {
                str(index): count
                for index, count in sorted(flat_face_source_counts.items())
            },
            "heightfield_flat_face_palette_index": flat_face_palette_index,
            "heightfield_flat_face_output_pixel_count": len(
                flat_face_output_locals
            ),
            "inverse_tex1_enabled": inverse_tex1_palette is not None,
            "inverse_tex1": inverse_tex1_report,
            "dark_component_minimum_pixels": dark_component_minimum_pixels,
            "dark_speckle_component_count": len(small_dark_components),
            "dark_speckle_pixels_converted_to_light": (
                dark_speckle_pixels_converted
            ),
            "dark_speckle_components_remaining": 0,
            "source_boundary_light_balance": boundary_profiles,
            "boundary_lightened_pixel_count": boundary_lightened_pixel_count,
            "upper_left_highlight_minimum_index": upper_left_minimum_index,
            "upper_left_highlight_pixel_count": len(upper_left_highlight),
            "upper_left_highlight_output_index_counts": {
                str(index): count
                for index, count in sorted(
                    Counter(assignments[local] for local in upper_left_highlight).items()
                )
            },
            "bright_edge_character_indexes": list(
                bright_edge_character_indexes
            ),
            "bright_edge_character_spans": [
                list(span) for span in bright_edge_character_spans
            ],
            "bright_edge_selected_spans": [
                list(span) for span in bright_edge_selected_spans
            ],
            "bright_edge_minimum_index": bright_edge_minimum_index,
            "bright_edge_promoted_pixel_count": len(
                bright_edge_promoted_locals
            ),
            "bright_edge_output_index_counts": {
                str(index): count
                for index, count in sorted(
                    Counter(
                        assignments[local]
                        for local in output_zones["halo"]
                        if any(
                            left <= local % width < right
                            for left, right in bright_edge_selected_spans
                        )
                    ).items()
                )
            },
            "source_histogram_scaled_exact": core_actual_counts == ideal_counts,
            "source_histogram_used_as_zone_quantile_reference": True,
            "equal_spatial_score_groups_share_one_index": True,
            "source_histogram_ideal_counts": {
                str(index): count for index, count in sorted(ideal_counts.items())
            },
            "source_zone_index_counts": {
                zone_name: {
                    str(index): count for index, count in sorted(counts.items())
                }
                for zone_name, counts in source_zone_counts.items()
            },
            "observed_source_zone_index_counts": {
                zone_name: {
                    str(index): count for index, count in sorted(counts.items())
                }
                for zone_name, counts in observed_source_zone_counts.items()
            },
            "outer_boundary_output_index_counts": {
                str(index): count
                for index, count in sorted(outer_boundary_output_counts.items())
            },
            "outer_boundary_uses_semantic_halo_only": (
                outer_boundary_uses_semantic_halo_only
            ),
            "source_index_boundary_depth_counts": {
                str(index): {
                    str(depth): count
                    for depth, count in sorted(counts.items())
                }
                for index, counts in source_index_depth_counts.items()
            },
            "output_zone_pixel_counts": {
                zone_name: len(locals_)
                for zone_name, locals_ in output_zones.items()
            },
            "output_zone_index_counts": {
                zone_name: {
                    str(index): count for index, count in sorted(counts.items())
                }
                for zone_name, counts in zone_output_counts.items()
            },
            "outline_mask_sha256": sha256_bytes(outline_mask),
            "outline_mask_nonzero_pixel_count": sum(
                value > 0 for value in outline_mask
            ),
            "outline_only_pixel_count": len(outline_only),
            "fill_mask_sha256": sha256_bytes(fill_mask),
            "fill_mask_nonzero_pixel_count": len(visible_fill),
            "output_ink_mask_sha256": sha256_bytes(output_ink),
            "output_ink_pixel_count": sum(output_ink),
            "indexed_layer_counts": {
                layer: {
                    str(index): count for index, count in sorted(counts.items())
                }
                for layer, counts in layer_counts.items()
            },
        }
    if render_style != "separate_layers":
        raise TricmnBattleOverlayError("unknown TRICMN indexed render style")
    for local, (outline, fill) in enumerate(zip(outline_mask, fill_mask)):
        if fill:
            ramp = fill_indexes
            coverage = fill
            maximum = fill_max
            power = fill_ramp_power
            layer = "fill"
        elif outline:
            ramp = outline_indexes
            coverage = outline
            maximum = outline_max
            power = outline_ramp_power
            layer = "outline"
        else:
            continue
        ramp_offset = _ramp_offset(
            coverage,
            maximum=maximum,
            ramp_length=len(ramp),
            power=power,
        )
        palette_index = ramp[ramp_offset]
        local_x = local % width
        local_y = local // width
        indexes[(y + local_y) * picture_width + x + local_x] = palette_index
        output_ink[local] = 1
        layer_counts[layer][palette_index] += 1

    return {
        "outline_mask_sha256": sha256_bytes(outline_mask),
        "outline_mask_nonzero_pixel_count": sum(
            value > 0 for value in outline_mask
        ),
        "outline_only_pixel_count": len(outline_only),
        "fill_mask_sha256": sha256_bytes(fill_mask),
        "fill_mask_nonzero_pixel_count": len(visible_fill),
        "output_ink_mask_sha256": sha256_bytes(output_ink),
        "output_ink_pixel_count": sum(output_ink),
        "indexed_layer_counts": {
            layer: {
                str(index): count for index, count in sorted(counts.items())
            }
            for layer, counts in layer_counts.items()
        },
    }


def _apply_label(
    indexes: bytearray,
    original_indexes: bytes,
    *,
    picture_width: int,
    rect: tuple[int, int, int, int],
    outline_mask: bytes,
    fill_mask: bytes,
    background_index: int,
    outline_indexes: tuple[int, ...],
    fill_indexes: tuple[int, ...],
    outline_ramp_power: int,
    fill_ramp_power: int,
    render_style: str,
    shadow_offset_x: int,
    shadow_offset_y: int,
    coverage_floor: int,
    side_direction_weight: int,
    halo_direction_weight: int,
    upper_left_highlight_minimum_index: int,
    bright_edge_character_indexes: tuple[int, ...],
    bright_edge_minimum_index: int,
    glow_radius: int,
    vector_outline_mask: bytes | None,
    vector_fill_mask: bytes | None,
    vector_effect_scale: int,
    dark_component_minimum_pixels: int,
    indexed_edge_filter_radius: int,
    heightfield_bevel_width: float,
    heightfield_relief_strength: float,
    heightfield_ambient: float,
    heightfield_diffuse: float,
    heightfield_specular: float,
    heightfield_flat_top_rim: bool,
    heightfield_flat_face: bool,
    inverse_tex1_palette: Sequence[Sequence[float]] | None,
    inverse_tex1_scale: int,
    inverse_tex1_passes: int,
    inverse_tex1_adjacency_threshold: float,
    inverse_tex1_adjacency_weight: float,
) -> dict:
    x, y, width, height = rect
    expected = width * height
    if len(outline_mask) != expected or len(fill_mask) != expected:
        raise TricmnBattleOverlayError("render mask geometry drift")

    source_rect = _rect_indexes(
        original_indexes,
        picture_width=picture_width,
        rect=rect,
    )
    source_ink = bytes(value != background_index for value in source_rect)
    if not any(source_ink):
        raise TricmnBattleOverlayError("source label mask is empty")

    # Erase only original glyph nibbles. Transparent padding remains untouched,
    # which is essential for the NO-target row: its lower neighbour starts on
    # the immediately following scanline.
    for local, occupied in enumerate(source_ink):
        if occupied:
            local_x = local % width
            local_y = local // width
            indexes[(y + local_y) * picture_width + x + local_x] = background_index

    paint_report = _paint_indexed_masks(
        indexes,
        picture_width=picture_width,
        rect=rect,
        source_rect=source_rect,
        outline_mask=outline_mask,
        fill_mask=fill_mask,
        outline_indexes=outline_indexes,
        fill_indexes=fill_indexes,
        outline_ramp_power=outline_ramp_power,
        fill_ramp_power=fill_ramp_power,
        render_style=render_style,
        shadow_offset_x=shadow_offset_x,
        shadow_offset_y=shadow_offset_y,
        coverage_floor=coverage_floor,
        side_direction_weight=side_direction_weight,
        halo_direction_weight=halo_direction_weight,
        upper_left_highlight_minimum_index=upper_left_highlight_minimum_index,
        bright_edge_character_indexes=bright_edge_character_indexes,
        bright_edge_minimum_index=bright_edge_minimum_index,
        glow_radius=glow_radius,
        vector_outline_mask=vector_outline_mask,
        vector_fill_mask=vector_fill_mask,
        vector_effect_scale=vector_effect_scale,
        dark_component_minimum_pixels=dark_component_minimum_pixels,
        indexed_edge_filter_radius=indexed_edge_filter_radius,
        heightfield_bevel_width=heightfield_bevel_width,
        heightfield_relief_strength=heightfield_relief_strength,
        heightfield_ambient=heightfield_ambient,
        heightfield_diffuse=heightfield_diffuse,
        heightfield_specular=heightfield_specular,
        heightfield_flat_top_rim=heightfield_flat_top_rim,
        heightfield_flat_face=heightfield_flat_face,
        inverse_tex1_palette=inverse_tex1_palette,
        inverse_tex1_scale=inverse_tex1_scale,
        inverse_tex1_passes=inverse_tex1_passes,
        inverse_tex1_adjacency_threshold=inverse_tex1_adjacency_threshold,
        inverse_tex1_adjacency_weight=inverse_tex1_adjacency_weight,
    )
    output_ink = bytes(
        value != background_index
        for value in _rect_indexes(
            bytes(indexes), picture_width=picture_width, rect=rect
        )
    )

    # Any original glyph pixel not reused by the replacement must now be the
    # transparent index. This proves there are no Japanese edge remnants.
    for local, occupied in enumerate(source_ink):
        if occupied and not output_ink[local]:
            local_x = local % width
            local_y = local // width
            if indexes[(y + local_y) * picture_width + x + local_x] != background_index:
                raise TricmnBattleOverlayError("source label residue survived erase")

    output_rect = _rect_indexes(
        bytes(indexes),
        picture_width=picture_width,
        rect=rect,
    )
    return {
        "source_indexes_sha256": sha256_bytes(source_rect),
        "source_index_counts": {
            str(index): count for index, count in sorted(Counter(source_rect).items())
        },
        "source_ink_mask_sha256": sha256_bytes(source_ink),
        "source_ink_pixel_count": sum(source_ink),
        **paint_report,
        "output_indexes_sha256": sha256_bytes(output_rect),
        "output_index_counts": {
            str(index): count for index, count in sorted(Counter(output_rect).items())
        },
        "source_residue_outside_output_ink_absent": True,
    }


def build_tricmn_battle_overlay(
    project_root: Path,
    config_path: Path,
    *,
    enforce_expected: bool = True,
) -> tuple[bytes, bytes, bytes, dict]:
    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json(config_path)
    if config.get("schema_version") != 1:
        raise TricmnBattleOverlayError("unsupported TRICMN battle-overlay schema")

    source_ref = config.get("source")
    seg_ref = config.get("seg")
    tim2_contract = config.get("tim2")
    if not all(isinstance(value, Mapping) for value in (source_ref, seg_ref, tim2_contract)):
        raise TricmnBattleOverlayError("TRICMN source contract is incomplete")
    source_path = _path(root, source_ref.get("path"))
    seg_path = _path(root, seg_ref.get("path"))
    source = source_path.read_bytes()
    seg = seg_path.read_bytes()
    if (
        len(source) != source_ref.get("size")
        or sha256_bytes(source) != source_ref.get("sha256")
        or len(seg) != seg_ref.get("size")
        or sha256_bytes(seg) != seg_ref.get("sha256")
    ):
        raise TricmnBattleOverlayError("original TRICMN source drift")
    expected_seg_offsets = tuple(seg_ref.get("offsets", []))
    actual_seg_offsets = tuple(
        int.from_bytes(seg[offset : offset + 4], "little")
        for offset in range(0, len(seg), 4)
    )
    if actual_seg_offsets != expected_seg_offsets:
        raise TricmnBattleOverlayError("TRICMN SEG boundary drift")

    record_offset = _integer(tim2_contract.get("record_offset"), "TIM2 offset")
    record = parse_tim2(source, offset=record_offset)
    if len(record.pictures) != 4 or record.size != tim2_contract.get("record_size"):
        raise TricmnBattleOverlayError("TRICMN TIM2 record layout drift")
    picture_contracts = tim2_contract.get("pictures")
    if not isinstance(picture_contracts, list) or len(picture_contracts) != 4:
        raise TricmnBattleOverlayError("TRICMN picture contract is incomplete")

    image_ranges: list[tuple[int, int]] = []
    original_indexes: list[bytes] = []
    for picture_index, (picture, contract) in enumerate(
        zip(record.pictures, picture_contracts)
    ):
        if not isinstance(contract, Mapping):
            raise TricmnBattleOverlayError("TRICMN picture contract is malformed")
        image_start = picture.offset + picture.header_size
        image_end = image_start + picture.image_size
        if (
            picture.width != contract.get("width")
            or picture.height != contract.get("height")
            or picture.image_type != 4
            or picture.image_size != contract.get("image_size")
            or image_start != contract.get("image_offset")
            or picture.uses_shared_clut is not bool(contract.get("uses_shared_clut"))
        ):
            raise TricmnBattleOverlayError(
                f"TRICMN picture {picture_index} metadata drift"
            )
        image_ranges.append((image_start, image_end))
        original_indexes.append(
            unswizzle_psmt4(
                source[image_start:image_end],
                picture.width,
                picture.height,
                row_major_pages=True,
            )
        )

    first_picture = record.pictures[0]
    clut_offset = image_ranges[0][1]
    clut_end = clut_offset + first_picture.clut_size
    clut = source[clut_offset:clut_end]
    bank_count = first_picture.clut_color_count // 16
    background_index = _integer(
        tim2_contract.get("background_index"), "background index"
    )
    outline_indexes = tuple(tim2_contract.get("outline_indexes", []))
    fill_indexes = tuple(tim2_contract.get("fill_indexes", []))
    if (
        clut_offset != tim2_contract.get("clut_offset")
        or len(clut) != tim2_contract.get("clut_size")
        or bank_count != tim2_contract.get("palette_bank_count")
        or background_index != 0
        or outline_indexes != tuple(range(1, 8))
        or fill_indexes != tuple(range(8, 16))
    ):
        raise TricmnBattleOverlayError("TRICMN palette contract drift")

    palette_audit = []
    for bank in range(bank_count):
        colors = [_palette_color(clut, bank, index) for index in range(16)]
        if len(colors[background_index]) != 4 or colors[background_index][3] != 0:
            raise TricmnBattleOverlayError(
                f"TRICMN palette bank {bank} background is not transparent"
            )
        if any(colors[index][3] == 0 for index in (*outline_indexes, *fill_indexes)):
            raise TricmnBattleOverlayError(
                f"TRICMN palette bank {bank} text layer is transparent"
            )
        palette_audit.append(
            {
                "bank": bank,
                "background_rgba": colors[0].hex(),
                "foreground_alpha_values": sorted(
                    {colors[index][3] for index in (*outline_indexes, *fill_indexes)}
                ),
                "indexes": [
                    {
                        "index": index,
                        "role": (
                            "transparent"
                            if index == background_index
                            else "side"
                            if index in outline_indexes
                            else "light"
                        ),
                        "tim2_raw_rgba": color.hex(),
                        "tim2_raw_alpha": color[3],
                        "runtime_rgba": bytes(
                            (*color[:3], min(255, color[3] * 2))
                        ).hex(),
                        "runtime_alpha": min(255, color[3] * 2),
                    }
                    for index, color in enumerate(colors)
                ],
            }
        )

    corpus_ref = config.get("corpus")
    if not isinstance(corpus_ref, Mapping):
        raise TricmnBattleOverlayError("TRICMN corpus reference is missing")
    corpus_path = _path(root, corpus_ref.get("path"))
    corpus_data = corpus_path.read_bytes()
    corpus = json.loads(corpus_data.decode("utf-8"))
    entries = corpus.get("entries") if isinstance(corpus, dict) else None
    if not isinstance(entries, list):
        raise TricmnBattleOverlayError("TRICMN corpus entries are invalid")
    entries_by_id = {
        item.get("id"): item for item in entries if isinstance(item, Mapping)
    }
    if len(entries_by_id) != len(entries):
        raise TricmnBattleOverlayError("TRICMN corpus entry IDs are not unique")

    default_font_flavor_reference = config.get("font_flavor")
    flavor = load_font_flavor_reference(root, default_font_flavor_reference)
    _font_lock, font_files, _fallback_paths, fallback_reports = verify_font_flavor_files(
        root, root / "work", flavor
    )
    font_path = font_files["font"]
    executable = require_imagemagick()
    labels = config.get("labels")
    if not isinstance(labels, list) or len(labels) != len(entries):
        raise TricmnBattleOverlayError("TRICMN label inventory is incomplete")
    render_profiles = config.get("render_profiles")
    if not isinstance(render_profiles, Mapping):
        raise TricmnBattleOverlayError("TRICMN render profiles are missing")
    font_flavors = {
        default_font_flavor_reference: {
            "flavor": flavor,
            "font_path": font_path,
            "fallback_reports": fallback_reports,
        }
    }
    for profile_id, profile in render_profiles.items():
        if not isinstance(profile_id, str) or not isinstance(profile, Mapping):
            raise TricmnBattleOverlayError(
                "TRICMN render profile font selection is malformed"
            )
        reference = profile.get("font_flavor")
        if reference is None or reference in font_flavors:
            continue
        if not isinstance(reference, str) or not reference:
            raise TricmnBattleOverlayError(
                f"TRICMN render profile font flavor is invalid: {profile_id}"
            )
        profile_flavor = load_font_flavor_reference(root, reference)
        (
            _profile_font_lock,
            profile_font_files,
            _profile_fallback_paths,
            profile_fallback_reports,
        ) = verify_font_flavor_files(root, root / "work", profile_flavor)
        font_flavors[reference] = {
            "flavor": profile_flavor,
            "font_path": profile_font_files["font"],
            "fallback_reports": profile_fallback_reports,
        }
    frame_profiles = config.get("frame_profiles", {})
    if not isinstance(frame_profiles, Mapping):
        raise TricmnBattleOverlayError("TRICMN frame profiles are malformed")
    marker_profiles = config.get("marker_profiles", {})
    if not isinstance(marker_profiles, Mapping):
        raise TricmnBattleOverlayError("TRICMN marker profiles are malformed")

    edited_indexes = [bytearray(indexes) for indexes in original_indexes]
    occupied: dict[int, set[tuple[int, int]]] = {}
    label_reports = []
    for spec in labels:
        if not isinstance(spec, Mapping):
            raise TricmnBattleOverlayError("TRICMN label spec is malformed")
        entry_id = spec.get("entry_id")
        entry = entries_by_id.get(entry_id)
        if (
            not isinstance(entry, Mapping)
            or entry.get("editorial_status") != corpus_ref.get("minimum_editorial_status")
        ):
            raise TricmnBattleOverlayError(f"TRICMN translation is not reviewed: {entry_id}")
        text = entry.get("translation")
        if not isinstance(text, str) or not text or "\n" in text or "\r" in text:
            raise TricmnBattleOverlayError(f"TRICMN translation is invalid: {entry_id}")
        picture_index = _integer(spec.get("picture_index"), "picture index")
        if not 0 <= picture_index < 3:
            raise TricmnBattleOverlayError("only TRICMN text pictures 0, 1 and 2 may be edited")
        picture = record.pictures[picture_index]
        rect = _rect(spec.get("rect"), width=picture.width, height=picture.height)
        x, y, width, height = rect
        source_rect = _rect_indexes(
            original_indexes[picture_index],
            picture_width=picture.width,
            rect=rect,
        )
        source_points = [
            index
            for index, value in enumerate(source_rect)
            if value != background_index
        ]
        source_bounds = (
            min(index % width for index in source_points),
            min(index // width for index in source_points),
            max(index % width for index in source_points) + 1,
            max(index // width for index in source_points) + 1,
        )
        frame_profile_id = spec.get("frame_profile")
        marker_profile_id = spec.get("marker_profile")
        if frame_profile_id is not None and marker_profile_id is not None:
            raise TricmnBattleOverlayError(
                f"TRICMN label cannot use both frame and marker profiles: {entry_id}"
            )
        frame_report = None
        marker_report = None
        marker_template = None
        edit_rect = rect
        if frame_profile_id is not None:
            frame_profile = frame_profiles.get(frame_profile_id)
            if not isinstance(frame_profile_id, str) or not isinstance(
                frame_profile, Mapping
            ):
                raise TricmnBattleOverlayError(
                    f"TRICMN frame profile is missing: {entry_id}"
                )
            slot_x = _integer(frame_profile.get("slot_x"), "frame slot x")
            slot_width = _integer(
                frame_profile.get("slot_width"), "frame slot width"
            )
            slot_height = _integer(
                frame_profile.get("slot_height"), "frame slot height"
            )
            template_y = _integer(
                frame_profile.get("template_y"), "frame template y"
            )
            inset = frame_profile.get("text_inset")
            if (
                not isinstance(inset, list)
                or len(inset) != 4
                or any(not isinstance(value, int) for value in inset)
            ):
                raise TricmnBattleOverlayError("TRICMN frame text inset is malformed")
            edit_rect = _rect(
                [slot_x, y - inset[1], slot_width, slot_height],
                width=picture.width,
                height=picture.height,
            )
            expected_text_rect = (
                edit_rect[0] + inset[0],
                edit_rect[1] + inset[1],
                inset[2],
                inset[3],
            )
            if rect != expected_text_rect:
                raise TricmnBattleOverlayError(
                    f"TRICMN frame/text geometry drift: {entry_id}"
                )
            template_rect = _rect(
                [slot_x, template_y, slot_width, slot_height],
                width=picture.width,
                height=picture.height,
            )
            source_slot = _rect_indexes(
                original_indexes[picture_index],
                picture_width=picture.width,
                rect=edit_rect,
            )
            template_slot = _rect_indexes(
                original_indexes[picture_index],
                picture_width=picture.width,
                rect=template_rect,
            )
            if len(source_slot) != len(template_slot):
                raise TricmnBattleOverlayError("TRICMN frame template geometry drift")
            for local_y in range(slot_height):
                source_offset = local_y * slot_width
                target = (edit_rect[1] + local_y) * picture.width + edit_rect[0]
                edited_indexes[picture_index][target : target + slot_width] = (
                    template_slot[source_offset : source_offset + slot_width]
                )
            outer_differences = []
            for local, (source_value, template_value) in enumerate(
                zip(source_slot, template_slot)
            ):
                local_x = local % slot_width
                local_y = local // slot_width
                inside_text = (
                    inset[0] <= local_x < inset[0] + inset[2]
                    and inset[1] <= local_y < inset[1] + inset[3]
                )
                if not inside_text and source_value != template_value:
                    outer_differences.append(local)
            frame_report = {
                "profile": frame_profile_id,
                "slot_rect": list(edit_rect),
                "template_rect": list(template_rect),
                "source_text_spill_outside_text_rect_pixel_count": len(
                    outer_differences
                ),
                "source_text_spill_indexes_sha256": sha256_bytes(
                    b"".join(index.to_bytes(2, "little") for index in outer_differences)
                ),
            }
        if marker_profile_id is not None:
            marker_profile = marker_profiles.get(marker_profile_id)
            if not isinstance(marker_profile_id, str) or not isinstance(
                marker_profile, Mapping
            ):
                raise TricmnBattleOverlayError(
                    f"TRICMN marker profile is missing: {entry_id}"
                )
            slot_x = _integer(marker_profile.get("slot_x"), "marker slot x")
            slot_width = _integer(
                marker_profile.get("slot_width"), "marker slot width"
            )
            slot_height = _integer(
                marker_profile.get("slot_height"), "marker slot height"
            )
            inset = marker_profile.get("text_inset")
            marker_rect_raw = marker_profile.get("marker_rect")
            source_template = marker_profile.get("source_template")
            if (
                not isinstance(inset, list)
                or len(inset) != 4
                or any(not isinstance(value, int) for value in inset)
                or not isinstance(marker_rect_raw, list)
                or len(marker_rect_raw) != 4
                or any(not isinstance(value, int) for value in marker_rect_raw)
                or not isinstance(source_template, Mapping)
            ):
                raise TricmnBattleOverlayError(
                    "TRICMN marker geometry is malformed"
                )
            edit_rect = _rect(
                [slot_x, y - inset[1], slot_width, slot_height],
                width=picture.width,
                height=picture.height,
            )
            expected_text_rect = (
                edit_rect[0] + inset[0],
                edit_rect[1] + inset[1],
                inset[2],
                inset[3],
            )
            if rect != expected_text_rect:
                raise TricmnBattleOverlayError(
                    f"TRICMN marker/text geometry drift: {entry_id}"
                )
            marker_rect = _rect(
                [
                    edit_rect[0] + marker_rect_raw[0],
                    edit_rect[1] + marker_rect_raw[1],
                    marker_rect_raw[2],
                    marker_rect_raw[3],
                ],
                width=picture.width,
                height=picture.height,
            )
            source_picture_index = _integer(
                source_template.get("picture_index"),
                "marker source picture index",
            )
            if not 0 <= source_picture_index < len(original_indexes):
                raise TricmnBattleOverlayError(
                    f"TRICMN marker source picture is invalid: {entry_id}"
                )
            source_picture = record.pictures[source_picture_index]
            source_x = _integer(source_template.get("x"), "marker source x")
            source_y = _integer(source_template.get("y"), "marker source y")
            source_width = _integer(
                source_template.get("width"), "marker source width"
            )
            source_height = _integer(
                source_template.get("height"), "marker source height"
            )
            source_row_count = _integer(
                source_template.get("row_count"), "marker source row count"
            )
            source_row_stride = _integer(
                source_template.get("row_stride"), "marker source row stride"
            )
            if (
                source_row_count < 2
                or source_row_stride <= 0
                or marker_rect[2:] != (source_width, source_height)
            ):
                raise TricmnBattleOverlayError(
                    f"TRICMN repeated marker source geometry drift: {entry_id}"
                )
            source_samples = []
            source_sample_rects = []
            for source_row in range(source_row_count):
                source_rect = _rect(
                    [
                        source_x,
                        source_y + source_row * source_row_stride,
                        source_width,
                        source_height,
                    ],
                    width=source_picture.width,
                    height=source_picture.height,
                )
                source_sample_rects.append(list(source_rect))
                source_samples.append(
                    _rect_indexes(
                        original_indexes[source_picture_index],
                        picture_width=source_picture.width,
                        rect=source_rect,
                    )
                )
            majority_template = bytearray(source_width * source_height)
            ambiguous_source_pixels = 0
            ambiguous_foreground_pixels = 0
            for local in range(len(majority_template)):
                counts = Counter(sample[local] for sample in source_samples)
                if len(counts) > 1:
                    ambiguous_source_pixels += 1
                # The ten stock markers share one geometry but contain small
                # palette-tone variations.  Clearing every non-identical
                # sample punches transparent holes through the tip shadow.
                # Keep the modal source index; in an exact tie prefer the
                # higher (lighter) source index so a boundary cannot acquire
                # a new isolated dark texel.
                chosen = max(counts, key=lambda value: (counts[value], value))
                majority_template[local] = chosen
                if len(counts) > 1 and chosen != background_index:
                    ambiguous_foreground_pixels += 1
            marker_template = bytes(majority_template)
            marker_ink = bytes(
                value != background_index for value in marker_template
            )
            if not any(marker_ink):
                raise TricmnBattleOverlayError(
                    f"TRICMN repeated marker source is empty: {entry_id}"
                )
            source_slot = _rect_indexes(
                original_indexes[picture_index],
                picture_width=picture.width,
                rect=edit_rect,
            )
            for local_y in range(slot_height):
                target = (edit_rect[1] + local_y) * picture.width + edit_rect[0]
                edited_indexes[picture_index][target : target + slot_width] = bytes(
                    [background_index]
                ) * slot_width
            for local_y in range(marker_rect[3]):
                source_offset = local_y * marker_rect[2]
                target = (
                    (marker_rect[1] + local_y) * picture.width + marker_rect[0]
                )
                edited_indexes[picture_index][
                    target : target + marker_rect[2]
                ] = marker_template[
                    source_offset : source_offset + marker_rect[2]
                ]
            marker_report = {
                "profile": marker_profile_id,
                "slot_rect": list(edit_rect),
                "text_rect": list(rect),
                "marker_rect": list(marker_rect),
                "source_slot_indexes_sha256": sha256_bytes(source_slot),
                "source_slot_ink_pixel_count": sum(
                    value != background_index for value in source_slot
                ),
                "source_slot_cleared_before_redraw": True,
                "source_template_picture_index": source_picture_index,
                "source_template_sample_rects": source_sample_rects,
                "source_template_samples_sha256": sha256_bytes(
                    b"".join(source_samples)
                ),
                "source_template_indexes_sha256": sha256_bytes(marker_template),
                "source_template_ambiguous_pixel_count": ambiguous_source_pixels,
                "source_template_ambiguous_foreground_pixel_count": (
                    ambiguous_foreground_pixels
                ),
                "source_template_resolution": (
                    "per_pixel_majority_with_higher_index_tiebreak"
                ),
                "render_ink_bounds": list(
                    _ink_bounds(marker_ink, marker_rect[2])
                ),
                "output_ink_pixel_count": sum(marker_ink),
                "source_marker_template_copied_byte_exact": True,
            }
        pixels = {
            (xx, yy)
            for yy in range(edit_rect[1], edit_rect[1] + edit_rect[3])
            for xx in range(edit_rect[0], edit_rect[0] + edit_rect[2])
        }
        picture_occupied = occupied.setdefault(picture_index, set())
        if picture_occupied & pixels:
            raise TricmnBattleOverlayError(f"TRICMN label rectangles overlap: {entry_id}")
        picture_occupied.update(pixels)
        profile_id = spec.get("render_profile")
        profile = render_profiles.get(profile_id)
        if not isinstance(profile_id, str) or not isinstance(profile, Mapping):
            raise TricmnBattleOverlayError(
                f"TRICMN label render profile is missing: {entry_id}"
            )
        render = dict(profile)
        override = spec.get("render")
        if override is not None:
            if not isinstance(override, Mapping):
                raise TricmnBattleOverlayError("TRICMN label render override is malformed")
            render.update(override)
        match_source_ink_width = render.get("match_source_ink_width", False)
        if not isinstance(match_source_ink_width, bool):
            raise TricmnBattleOverlayError(
                f"TRICMN source-width matching switch is malformed: {entry_id}"
            )
        source_target_ink_width = None
        if match_source_ink_width:
            source_target_ink_width = min(
                source_bounds[2] - source_bounds[0], width - 2
            )
        render_font_flavor_reference = render.get(
            "font_flavor", default_font_flavor_reference
        )
        render_font = font_flavors.get(render_font_flavor_reference)
        if render_font is None:
            raise TricmnBattleOverlayError(
                f"TRICMN label font flavor was not declared by its profile: {entry_id}"
            )
        render_font_path = render_font["font_path"]
        outline_ramp_power = _integer(
            render.get("outline_ramp_power", 1), "outline ramp power"
        )
        fill_ramp_power = _integer(
            render.get("fill_ramp_power", 1), "fill ramp power"
        )
        render_style = render.get("render_style", "separate_layers")
        shadow_offset = render.get("shadow_offset", [0, 0])
        if (
            not isinstance(render_style, str)
            or not isinstance(shadow_offset, list)
            or len(shadow_offset) != 2
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in shadow_offset
            )
        ):
            raise TricmnBattleOverlayError(
                f"TRICMN indexed render style is malformed: {entry_id}"
            )
        shadow_offset_x, shadow_offset_y = shadow_offset
        coverage_floor = _integer(
            render.get("coverage_floor", 0), "coverage floor"
        )
        side_direction_weight = _integer(
            render.get("side_direction_weight", 0), "side direction weight"
        )
        halo_direction_weight = _integer(
            render.get("halo_direction_weight", 0), "halo direction weight"
        )
        upper_left_highlight_minimum_index = _integer(
            render.get("upper_left_highlight_minimum_index", 0),
            "upper-left highlight minimum index",
        )
        bright_edge_character_indexes_raw = render.get(
            "bright_edge_character_indexes", []
        )
        if (
            not isinstance(bright_edge_character_indexes_raw, list)
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for value in bright_edge_character_indexes_raw
            )
            or len(set(bright_edge_character_indexes_raw))
            != len(bright_edge_character_indexes_raw)
        ):
            raise TricmnBattleOverlayError(
                f"TRICMN bright-edge character selection is malformed: {entry_id}"
            )
        bright_edge_character_indexes = tuple(
            bright_edge_character_indexes_raw
        )
        bright_edge_minimum_index = _integer(
            render.get("bright_edge_minimum_index", 0),
            "bright-edge minimum index",
        )
        if bool(bright_edge_character_indexes) != bool(
            bright_edge_minimum_index
        ):
            raise TricmnBattleOverlayError(
                f"TRICMN bright-edge tuning is incomplete: {entry_id}"
            )
        dark_component_minimum_pixels = _integer(
            render.get("dark_component_minimum_pixels", 1),
            "dark component minimum pixels",
        )
        indexed_edge_filter_radius = _integer(
            render.get("indexed_edge_filter_radius", 0),
            "indexed edge-filter radius",
        )
        heightfield_flat_top_rim = render.get(
            "heightfield_flat_top_rim", False
        )
        heightfield_flat_face = render.get("heightfield_flat_face", False)
        inverse_tex1_enabled = render.get("inverse_tex1_enabled", False)
        if not isinstance(heightfield_flat_top_rim, bool):
            raise TricmnBattleOverlayError(
                f"TRICMN flat-top height-field switch is malformed: {entry_id}"
            )
        if not isinstance(heightfield_flat_face, bool):
            raise TricmnBattleOverlayError(
                f"TRICMN flat-face height-field switch is malformed: {entry_id}"
            )
        if not isinstance(inverse_tex1_enabled, bool):
            raise TricmnBattleOverlayError(
                f"TRICMN TEX1 inverse switch is malformed: {entry_id}"
            )
        inverse_tex1_palette_bank = _integer(
            render.get("inverse_tex1_palette_bank", 10),
            "TEX1 inverse palette bank",
        )
        inverse_tex1_scale = _integer(
            render.get("inverse_tex1_scale", 4),
            "TEX1 inverse scale",
        )
        inverse_tex1_passes = _integer(
            render.get("inverse_tex1_passes", 2),
            "TEX1 inverse passes",
        )
        inverse_tex1_adjacency_threshold = float(
            render.get("inverse_tex1_adjacency_threshold", 64.0)
        )
        inverse_tex1_adjacency_weight = float(
            render.get("inverse_tex1_adjacency_weight", 2.0)
        )
        if (
            not 0 <= coverage_floor <= 254
            or not 0 <= side_direction_weight <= 8
            or not 0 <= halo_direction_weight <= 8
            or not 1 <= dark_component_minimum_pixels <= 8
            or not 0 <= indexed_edge_filter_radius <= 2
            or not 0 <= inverse_tex1_palette_bank < bank_count
            or not 2 <= inverse_tex1_scale <= 8
            or not 1 <= inverse_tex1_passes <= 4
            or not 0 <= inverse_tex1_adjacency_threshold <= 255
            or not 0 <= inverse_tex1_adjacency_weight <= 256
        ):
            raise TricmnBattleOverlayError(
                f"TRICMN WordArt tuning is outside its safe range: {entry_id}"
            )
        render_outline_indexes = _palette_ramp(
            render.get("outline_palette_indexes"),
            default=outline_indexes,
            allowed=set((*outline_indexes, *fill_indexes)),
            label="outline palette indexes",
        )
        render_fill_indexes = _palette_ramp(
            render.get("fill_palette_indexes"),
            default=fill_indexes,
            allowed=set((*outline_indexes, *fill_indexes)),
            label="fill palette indexes",
        )
        if set(render_outline_indexes) & set(render_fill_indexes):
            raise TricmnBattleOverlayError(
                f"TRICMN outline/fill palette ramps overlap: {entry_id}"
            )
        (
            outline_mask,
            fill_mask,
            horizontal_offset,
            render_ink_bounds,
            vector_outline_mask,
            vector_fill_mask,
            vector_effect_scale,
            effective_character_spacing,
        ) = _render_label_masks(
            executable,
            render_font_path,
            text,
            rect,
            render,
            target_ink_width=source_target_ink_width,
        )
        try:
            layer_report = _apply_label(
                edited_indexes[picture_index],
                original_indexes[picture_index],
                picture_width=picture.width,
                rect=rect,
                outline_mask=outline_mask,
                fill_mask=fill_mask,
                background_index=background_index,
                outline_indexes=render_outline_indexes,
                fill_indexes=render_fill_indexes,
                outline_ramp_power=outline_ramp_power,
                fill_ramp_power=fill_ramp_power,
                render_style=render_style,
                shadow_offset_x=shadow_offset_x,
                shadow_offset_y=shadow_offset_y,
                coverage_floor=coverage_floor,
                side_direction_weight=side_direction_weight,
                halo_direction_weight=halo_direction_weight,
                upper_left_highlight_minimum_index=(
                    upper_left_highlight_minimum_index
                ),
                bright_edge_character_indexes=(
                    bright_edge_character_indexes
                ),
                bright_edge_minimum_index=bright_edge_minimum_index,
                glow_radius=_integer(
                    render.get("glow_radius", 0), "glow radius"
                ),
                vector_outline_mask=vector_outline_mask,
                vector_fill_mask=vector_fill_mask,
                vector_effect_scale=vector_effect_scale,
                dark_component_minimum_pixels=(
                    dark_component_minimum_pixels
                ),
                indexed_edge_filter_radius=indexed_edge_filter_radius,
                heightfield_bevel_width=float(
                    render.get("heightfield_bevel_width", 1.5)
                ),
                heightfield_relief_strength=float(
                    render.get("heightfield_relief_strength", 1.25)
                ),
                heightfield_ambient=float(
                    render.get("heightfield_ambient", 0.42)
                ),
                heightfield_diffuse=float(
                    render.get("heightfield_diffuse", 0.48)
                ),
                heightfield_specular=float(
                    render.get("heightfield_specular", 0.10)
                ),
                heightfield_flat_top_rim=heightfield_flat_top_rim,
                heightfield_flat_face=heightfield_flat_face,
                inverse_tex1_palette=(
                    _runtime_palette(clut, inverse_tex1_palette_bank)
                    if inverse_tex1_enabled
                    else None
                ),
                inverse_tex1_scale=inverse_tex1_scale,
                inverse_tex1_passes=inverse_tex1_passes,
                inverse_tex1_adjacency_threshold=(
                    inverse_tex1_adjacency_threshold
                ),
                inverse_tex1_adjacency_weight=(
                    inverse_tex1_adjacency_weight
                ),
            )
        except TricmnBattleOverlayError as error:
            raise TricmnBattleOverlayError(f"{entry_id}: {error}") from error
        if frame_report is not None:
            output_slot = _rect_indexes(
                bytes(edited_indexes[picture_index]),
                picture_width=picture.width,
                rect=edit_rect,
            )
            template_slot = _rect_indexes(
                original_indexes[picture_index],
                picture_width=picture.width,
                rect=tuple(frame_report["template_rect"]),
            )
            inset = frame_profiles[frame_profile_id]["text_inset"]
            for local, (output_value, template_value) in enumerate(
                zip(output_slot, template_slot)
            ):
                local_x = local % edit_rect[2]
                local_y = local // edit_rect[2]
                inside_text = (
                    inset[0] <= local_x < inset[0] + inset[2]
                    and inset[1] <= local_y < inset[1] + inset[3]
                )
                if not inside_text and output_value != template_value:
                    raise TricmnBattleOverlayError(
                        f"TRICMN frame was not restored exactly: {entry_id}"
                    )
            frame_report["output_frame_matches_empty_template_byte_exact"] = True
        if marker_report is not None:
            if marker_template is None:
                raise TricmnBattleOverlayError(
                    f"TRICMN marker template was not prepared: {entry_id}"
                )
            output_slot = _rect_indexes(
                bytes(edited_indexes[picture_index]),
                picture_width=picture.width,
                rect=edit_rect,
            )
            output_marker = _rect_indexes(
                bytes(edited_indexes[picture_index]),
                picture_width=picture.width,
                rect=tuple(marker_report["marker_rect"]),
            )
            if output_marker != marker_template:
                raise TricmnBattleOverlayError(
                    f"TRICMN source marker copy drift: {entry_id}"
                )
            marker_local = marker_profiles[marker_profile_id]["marker_rect"]
            text_local = marker_profiles[marker_profile_id]["text_inset"]
            for local, value in enumerate(output_slot):
                local_x = local % edit_rect[2]
                local_y = local // edit_rect[2]
                inside_marker = (
                    marker_local[0] <= local_x < marker_local[0] + marker_local[2]
                    and marker_local[1] <= local_y < marker_local[1] + marker_local[3]
                )
                inside_text = (
                    text_local[0] <= local_x < text_local[0] + text_local[2]
                    and text_local[1] <= local_y < text_local[1] + text_local[3]
                )
                if not inside_marker and not inside_text and value != background_index:
                    raise TricmnBattleOverlayError(
                        f"TRICMN marker gap retained source residue: {entry_id}"
                    )
            marker_report["noncontent_pixels_transparent"] = True
        label_reports.append(
            {
                "entry_id": entry_id,
                "source_text": entry.get("source_text"),
                "translation": text,
                "picture_index": picture_index,
                "rect": list(rect),
                "source_ink_bounds": list(source_bounds),
                "render_ink_bounds": list(render_ink_bounds),
                "horizontal_offset": horizontal_offset,
                "source_target_ink_width": source_target_ink_width,
                "effective_character_spacing": effective_character_spacing,
                "render_profile": profile_id,
                "render": dict(render),
                "font_flavor": font_flavor_metadata(render_font["flavor"]),
                "font_file_sha256": sha256_bytes(render_font_path.read_bytes()),
                "fill_mask_opaque_pixel_count": sum(
                    value == 255 for value in fill_mask
                ),
                "fill_mask_partial_coverage_pixel_count": sum(
                    0 < value < 255 for value in fill_mask
                ),
                "frame_template": frame_report,
                "marker": marker_report,
                **layer_report,
            }
        )

    atlas_inventory = config.get("atlas_inventory")
    if not isinstance(atlas_inventory, list) or len(atlas_inventory) != 6:
        raise TricmnBattleOverlayError("TRICMN six-picture atlas inventory is incomplete")
    inventory_records = {record.offset: record}
    labels_per_picture = Counter(item["picture_index"] for item in label_reports)
    inventory_keys: set[tuple[int, int]] = set()
    inventory_report = []
    for item in atlas_inventory:
        if not isinstance(item, Mapping):
            raise TricmnBattleOverlayError("TRICMN atlas inventory item is malformed")
        inventory_record_offset = _integer(
            item.get("record_offset"), "inventory TIM2 offset"
        )
        inventory_picture_index = _integer(
            item.get("picture_index"), "inventory picture index"
        )
        inventory_record = inventory_records.get(inventory_record_offset)
        if inventory_record is None:
            inventory_record = parse_tim2(source, offset=inventory_record_offset)
            inventory_records[inventory_record_offset] = inventory_record
        key = (inventory_record_offset, inventory_picture_index)
        if key in inventory_keys or not 0 <= inventory_picture_index < len(
            inventory_record.pictures
        ):
            raise TricmnBattleOverlayError("TRICMN atlas inventory key is invalid")
        inventory_keys.add(key)
        inventory_picture = inventory_record.pictures[inventory_picture_index]
        inventory_start = inventory_picture.offset + inventory_picture.header_size
        inventory_indexes = unswizzle_psmt4(
            source[inventory_start : inventory_start + inventory_picture.image_size],
            inventory_picture.width,
            inventory_picture.height,
            row_major_pages=True,
        )
        actual_hash = sha256_bytes(inventory_indexes)
        actual_label_count = (
            labels_per_picture[inventory_picture_index]
            if inventory_record_offset == record.offset
            else 0
        )
        classification = item.get("classification")
        if (
            not isinstance(classification, str)
            or actual_hash != item.get("source_indexes_sha256")
            or actual_label_count != item.get("label_count")
        ):
            raise TricmnBattleOverlayError("TRICMN atlas inventory drift")
        inventory_report.append(
            {
                "record_offset": inventory_record_offset,
                "picture_index": inventory_picture_index,
                "classification": classification,
                "source_indexes_sha256": actual_hash,
                "label_count": actual_label_count,
            }
        )
    expected_inventory_keys = {
        (inventory_record.offset, picture_index)
        for inventory_record in inventory_records.values()
        for picture_index in range(len(inventory_record.pictures))
    }
    if inventory_keys != expected_inventory_keys:
        raise TricmnBattleOverlayError("TRICMN atlas inventory does not cover all pictures")

    edited = [bytes(indexes) for indexes in edited_indexes]
    changed_pixels_by_picture = []
    for picture_index in range(4):
        changed_pixels = [
            index
            for index, pair in enumerate(
                zip(original_indexes[picture_index], edited[picture_index])
            )
            if pair[0] != pair[1]
        ]
        allowed = occupied.get(picture_index, set())
        if picture_index < 3 and not changed_pixels:
            raise TricmnBattleOverlayError(
                f"TRICMN picture {picture_index} was not localized"
            )
        if any(
            (index % record.pictures[picture_index].width,
             index // record.pictures[picture_index].width) not in allowed
            for index in changed_pixels
        ):
            raise TricmnBattleOverlayError(
                f"TRICMN picture {picture_index} delta escaped target rectangles"
            )
        changed_pixels_by_picture.append(changed_pixels)

    output = bytearray(source)
    for picture_index in range(3):
        start, end = image_ranges[picture_index]
        output[start:end] = swizzle_psmt4(
            edited[picture_index],
            record.pictures[picture_index].width,
            record.pictures[picture_index].height,
            row_major_pages=True,
        )
        if unswizzle_psmt4(
            bytes(output[start:end]),
            record.pictures[picture_index].width,
            record.pictures[picture_index].height,
            row_major_pages=True,
        ) != edited[picture_index]:
            raise TricmnBattleOverlayError(
                f"TRICMN picture {picture_index} writeback round-trip failed"
            )

    protected = bytearray(len(source))
    for start, end in image_ranges[:3]:
        protected[start:end] = b"\x01" * (end - start)
    if bytes(value for index, value in enumerate(source) if not protected[index]) != bytes(
        value for index, value in enumerate(output) if not protected[index]
    ):
        raise TricmnBattleOverlayError("TRICMN metadata, CLUT or animation bytes changed")
    if (
        len(output) != len(source)
        or bytes(output[clut_offset:clut_end]) != clut
        or edited[3] != original_indexes[3]
    ):
        raise TricmnBattleOverlayError("TRICMN fixed-size or preserved-picture contract failed")

    reference_preview = render_palette_montage(
        original_indexes[:3], clut
    )
    localized_preview = render_palette_montage(edited[:3], clut)
    expected = config.get("expected", {})
    label_preimages = {
        item["entry_id"]: item["source_indexes_sha256"] for item in label_reports
    }
    source_ink_masks = {
        item["entry_id"]: item["source_ink_mask_sha256"] for item in label_reports
    }
    render_masks = {
        item["entry_id"]: {
            "outline": item["outline_mask_sha256"],
            "fill": item["fill_mask_sha256"],
            **(
                {
                    "marker_source_template": item["marker"][
                        "source_template_indexes_sha256"
                    ],
                }
                if item["marker"] is not None
                else {}
            ),
        }
        for item in label_reports
    }

    def contract_hash(value: object) -> str:
        return sha256_bytes(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    actual_expected = {
        "source_picture_indexes_sha256": [
            sha256_bytes(indexes) for indexes in original_indexes
        ],
        "source_clut_sha256": sha256_bytes(clut),
        "label_contract_count": len(label_reports),
        "label_preimages_contract_sha256": contract_hash(label_preimages),
        "source_ink_masks_contract_sha256": contract_hash(source_ink_masks),
        "render_masks_contract_sha256": contract_hash(render_masks),
        "output_picture_indexes_sha256": [
            sha256_bytes(indexes) for indexes in edited
        ],
        "output_member_sha256": sha256_bytes(bytes(output)),
        "reference_preview_sha256": sha256_bytes(reference_preview),
        "localized_preview_sha256": sha256_bytes(localized_preview),
    }
    if enforce_expected and expected != actual_expected:
        raise TricmnBattleOverlayError("TRICMN frozen expected values drift")

    report = {
        "schema_version": 1,
        "status": "tricmn_battle_overlay_static_validated_runtime_pending",
        "profile_id": config.get("profile_id"),
        "scope": config.get("scope"),
        "inputs": {
            "config": _lock(root, config_path),
            "source_bin": _lock(root, source_path, source),
            "source_seg": _lock(root, seg_path, seg),
            "corpus": _lock(root, corpus_path, corpus_data),
            "font_flavor": _lock(root, root / flavor["path"]),
            "font_file": _lock(root, font_path),
            **{
                key: lock
                for index, (_reference, item) in enumerate(
                    (
                        (reference, item)
                        for reference, item in sorted(font_flavors.items())
                        if reference != default_font_flavor_reference
                    ),
                    start=1,
                )
                for key, lock in (
                    (
                        f"profile_font_flavor_{index}",
                        _lock(root, root / item["flavor"]["path"]),
                    ),
                    (
                        f"profile_font_file_{index}",
                        _lock(root, item["font_path"]),
                    ),
                )
            },
        },
        "font": font_flavor_metadata(flavor),
        "profile_fonts": [
            {
                "reference": reference,
                "font": font_flavor_metadata(item["flavor"]),
            }
            for reference, item in sorted(font_flavors.items())
            if reference != default_font_flavor_reference
        ],
        "seg": {
            "size": len(seg),
            "sha256": sha256_bytes(seg),
            "offsets": list(actual_seg_offsets),
            "preserved_byte_exact": True,
        },
        "atlas": {
            "record_offset": record.offset,
            "record_size": record.size,
            "picture_count": len(record.pictures),
            "complete_six_picture_inventory": inventory_report,
            "image_ranges": [list(item) for item in image_ranges],
            "clut_offset": clut_offset,
            "clut_size": len(clut),
            "palette_bank_count": bank_count,
            "palette_audit": palette_audit,
            "labels": label_reports,
            "changed_logical_pixel_counts": [
                len(indexes) for indexes in changed_pixels_by_picture
            ],
            "changed_logical_pixel_indexes_sha256": [
                sha256_bytes(
                    b"".join(index.to_bytes(4, "little") for index in indexes)
                )
                for indexes in changed_pixels_by_picture
            ],
            "non_target_logical_indexes_preserved_byte_exact": True,
            "picture_3_preserved_byte_exact": True,
            "non_text_record_at_89840_preserved_byte_exact": True,
            "tim2_headers_preserved_byte_exact": True,
            "clut_preserved_byte_exact": True,
            "background_transparent_in_all_palette_banks": True,
            "foreground_nontransparent_in_all_palette_banks": True,
        },
        "toolchain": {
            "imagemagick": imagemagick_version(executable),
            "font_fallbacks": list(fallback_reports),
        },
        "expected": actual_expected,
        "output_diff": summarize_diff(source, bytes(output)).to_mapping(),
        "outputs": {
            source_ref.get("member"): {
                "path": str(
                    (
                        _path(root, config["outputs"]["component_root"])
                        / source_ref.get("member")
                    ).relative_to(root)
                ),
                "size": len(output),
                "sha256": sha256_bytes(bytes(output)),
            }
        },
        "acceptance": {
            "reviewed_translation_inventory_complete": len(label_reports) == len(entries),
            "all_six_atlas_pictures_classified": len(inventory_report) == 6,
            "source_glyph_erase_uses_exact_nontransparent_masks": all(
                item["source_residue_outside_output_ink_absent"]
                for item in label_reports
            ),
            "ability_frames_restored_from_empty_source_templates": all(
                item["frame_template"] is None
                or item["frame_template"][
                    "output_frame_matches_empty_template_byte_exact"
                ]
                for item in label_reports
            ),
            "status_markers_copied_from_source_after_full_slot_clear": all(
                item["marker"] is None
                or (
                    item["marker"]["source_slot_cleared_before_redraw"]
                    and item["marker"]["noncontent_pixels_transparent"]
                    and item["marker"][
                        "source_marker_template_copied_byte_exact"
                    ]
                )
                for item in label_reports
            ),
            "replacement_ink_stays_inside_locked_rectangles": True,
            "palette_and_alpha_preserved": True,
            "non_target_logical_pixels_preserved": True,
            "unmodified_pictures_preserved": True,
            "tim2_headers_and_clut_preserved": True,
            "seg_preserved": True,
            "member_size_preserved": len(output) == len(source),
        },
        "runtime": {
            "status": "not_tested",
            "reason": (
                "Static indexed-texture proof only; exact-ISO PCSX2 battle-entry "
                "captures for left and right overlays remain pending."
            ),
            "required_flows": [
                "capture_TRI_formation_at_upper_left",
                "capture_center_formation_at_upper_left",
                "capture_wide_formation_at_upper_left",
                "capture_attack_support_and_defense_prompts",
                "capture_no_target_unavailable_reasons_and_right_side_status_routes",
                "capture_barrier_armor_evasion_and_special_defense_prompts",
                "repeat_entries_to_cover_random_TRICMN_animation_members_2_3_4",
                "confirm_fades_and_all_runtime_palette_banks_keep_transparency",
            ],
        },
    }
    if not all(report["acceptance"].values()):
        raise TricmnBattleOverlayError("TRICMN component acceptance failed")
    return bytes(output), reference_preview, localized_preview, report


__all__ = [
    "TricmnBattleOverlayError",
    "build_tricmn_battle_overlay",
    "render_palette_montage",
]
