"""Uniform rasterization primitives for the global Chinese font."""

from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Mapping, Union

from .font import GLYPH_HEIGHT, GLYPH_WIDTH, encode_glyph


class FontRasterizerError(ValueError):
    """The release rasterizer configuration or output is invalid."""


def quantize_gray_4bpp(gray: bytes) -> bytes:
    """Quantize 8-bit gray to 0..15 with integer round-to-nearest."""

    return bytes((value * 15 + 127) // 255 for value in gray)


def rasterizer_point_size(
    character: str,
    rasterizer: Mapping,
) -> Union[int, float]:
    if not isinstance(character, str) or len(character) != 1:
        raise FontRasterizerError("glyph point-size lookup needs one character")
    point_size = rasterizer.get("point_size")
    if (
        not isinstance(point_size, (int, float))
        or isinstance(point_size, bool)
        or not float("-inf") < point_size < float("inf")
        or point_size <= 0
    ):
        raise FontRasterizerError(
            "rasterizer point size must be a finite positive number"
        )
    corrections = rasterizer.get("optical_corrections", {})
    if not isinstance(corrections, Mapping):
        raise FontRasterizerError(
            "rasterizer optical corrections must be a mapping"
        )
    if corrections:
        raise FontRasterizerError(
            "per-character optical corrections are forbidden"
        )
    return point_size


def _fixed_canvas(rasterizer: Mapping) -> dict | None:
    raw = rasterizer.get("cjk_fixed_canvas")
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {
        "x_offset",
        "y_offset",
        "reason",
    }:
        raise FontRasterizerError("CJK fixed-canvas policy is malformed")
    x_offset = raw["x_offset"]
    y_offset = raw["y_offset"]
    reason = raw["reason"]
    if (
        not isinstance(x_offset, int)
        or isinstance(x_offset, bool)
        or not -GLYPH_WIDTH < x_offset < GLYPH_WIDTH
        or not isinstance(y_offset, int)
        or isinstance(y_offset, bool)
        or not -GLYPH_HEIGHT < y_offset < GLYPH_HEIGHT
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise FontRasterizerError("CJK fixed-canvas policy is invalid")
    if rasterizer.get("optical_corrections"):
        raise FontRasterizerError("CJK fixed canvas forbids optical corrections")
    return dict(raw)


def _bottom_row_drop(rasterizer: Mapping) -> dict | None:
    raw = rasterizer.get("cjk_bottom_row_drop")
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {
        "ink_bottom_row",
        "ink_threshold",
        "rows",
        "reason",
    }:
        raise FontRasterizerError("CJK bottom-row drop policy is malformed")
    bottom, threshold, rows, reason = (
        raw["ink_bottom_row"], raw["ink_threshold"], raw["rows"], raw["reason"])
    if (
        any(not isinstance(value, int) or isinstance(value, bool)
            for value in (bottom, threshold, rows))
        or not 0 <= bottom < GLYPH_HEIGHT
        or not 1 <= threshold <= 15
        or not 1 <= rows < GLYPH_HEIGHT - bottom
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise FontRasterizerError("CJK bottom-row drop policy is invalid")
    if _fixed_canvas(rasterizer) is None:
        raise FontRasterizerError("CJK bottom-row drop needs the fixed canvas")
    return dict(raw)


def _is_cjk_ideograph(character: str) -> bool:
    return "\u4e00" <= character <= "\u9fff" or "\u3400" <= character <= "\u4dbf"


def apply_bottom_row_drop(gray: bytes, character: str, rasterizer: Mapping) -> bytes:
    """Lower an ideograph whose ink stops on the configured row above the common bottom.

    One rule for the whole font, decided from the rendered glyph alone: when the
    lowest row holding ink at or above the threshold is ``ink_bottom_row``, the
    canvas moves down ``rows`` rows. Rows that leave the canvas are empty because
    the ink ended ``rows`` rows above them at most. No per-character table.
    """

    policy = _bottom_row_drop(rasterizer)
    if policy is None or not _is_cjk_ideograph(character):
        return gray
    pixels = quantize_gray_4bpp(gray)
    inked = [
        row for row in range(GLYPH_HEIGHT)
        if any(value >= policy["ink_threshold"]
               for value in pixels[row * GLYPH_WIDTH:(row + 1) * GLYPH_WIDTH])
    ]
    if not inked or inked[-1] != policy["ink_bottom_row"]:
        return gray
    shift = policy["rows"] * GLYPH_WIDTH
    return bytes(shift) + gray[:len(gray) - shift]


def _rasterizer_environment() -> dict[str, str]:
    # Glyph canvases are 24x24: ImageMagick's per-process OpenMP pool only
    # thrashes when many renderers run side by side. Pixels do not depend on it.
    return {**os.environ, "MAGICK_THREAD_LIMIT": os.environ.get("MAGICK_THREAD_LIMIT", "1")}


def _run_rasterizer(command: list[str], character: str) -> bytes:
    try:
        result = subprocess.run(
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_rasterizer_environment(),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode(
            "utf-8", errors="replace"
        )
        raise FontRasterizerError(
            f"rasterizer failed for {character!r}: {detail}"
        ) from error
    if len(result.stdout) != GLYPH_WIDTH * GLYPH_HEIGHT:
        raise FontRasterizerError(
            f"rasterizer returned {len(result.stdout)} bytes for {character!r}"
        )
    return result.stdout


def _glyph_arguments(
    font_path: Path,
    character: str,
    rasterizer: Mapping,
) -> list[str]:
    """The ImageMagick pipeline that renders one glyph, without executable and output."""

    if not isinstance(character, str) or len(character) != 1:
        raise FontRasterizerError("glyph rasterization needs one character")
    hinting = rasterizer.get("hinting")
    antialias = rasterizer.get("antialias")
    if not isinstance(hinting, bool) or not isinstance(antialias, bool):
        raise FontRasterizerError("rasterizer hinting/antialias lock is invalid")
    point_size = rasterizer_point_size(character, rasterizer)
    fixed = _fixed_canvas(rasterizer)
    common = [
        "-fill",
        "white",
        "-density",
        str(rasterizer["density"]),
        "-units",
        "PixelsPerInch",
        "-font",
        str(font_path),
        "-pointsize",
        str(point_size),
        "-define",
        f"type:hinting={'true' if hinting else 'false'}",
        "-antialias" if antialias else "+antialias",
        "-gravity",
        rasterizer["gravity"],
    ]
    if fixed is not None:
        geometry = f"{fixed['x_offset']:+d}{fixed['y_offset']:+d}"
        command = [
            "-size",
            f"{GLYPH_WIDTH}x{GLYPH_HEIGHT}",
            "xc:black",
            *common,
            "-annotate",
            geometry,
            character,
            "-colorspace",
            "Gray",
            "-depth",
            "8",
        ]
    else:
        command = [
            "-background",
            "black",
            *common,
            "-size",
            f"{GLYPH_WIDTH}x{GLYPH_HEIGHT}",
            f"label:{character}",
            "-colorspace",
            "Gray",
            "-depth",
            "8",
        ]
    return command


def rasterize_character(
    executable: str,
    font_path: Path,
    character: str,
    rasterizer: Mapping,
) -> tuple[bytes, bytes, bytes]:
    """Render one 24x24 glyph with the release-wide geometry policy."""

    arguments = _glyph_arguments(font_path, character, rasterizer)
    if character == " ":
        gray = bytes(GLYPH_WIDTH * GLYPH_HEIGHT)
    else:
        gray = apply_bottom_row_drop(
            _run_rasterizer([executable, *arguments, "gray:-"], character), character, rasterizer)
    pixels = quantize_gray_4bpp(gray)
    return gray, pixels, encode_glyph(pixels)


def rasterize_characters(
    executable: str,
    font_path_for,
    characters,
    rasterizer: Mapping,
    *,
    batch_size: int = 64,
    workers: int = 3,
) -> dict[str, tuple[bytes, bytes, bytes]]:
    """Render many glyphs, ``batch_size`` per ImageMagick process.

    Each glyph keeps its complete single-glyph pipeline inside its own
    parenthesised image group (settings do not leak between groups), and the
    process writes the resulting canvases back to back; the bytes are the ones
    ``rasterize_character`` returns one process at a time. ``font_path_for``
    maps a character to its font file (fallbacks included).
    """
    results: dict[str, tuple[bytes, bytes, bytes]] = {}
    pending = []
    for character in dict.fromkeys(characters):
        if character == " ":
            gray = bytes(GLYPH_WIDTH * GLYPH_HEIGHT)
            pixels = quantize_gray_4bpp(gray)
            results[character] = (gray, pixels, encode_glyph(pixels))
        else:
            pending.append(character)
    size = GLYPH_WIDTH * GLYPH_HEIGHT
    batches = [pending[start:start + max(1, batch_size)]
               for start in range(0, len(pending), max(1, batch_size))]

    def render(batch):
        command = [executable]
        for character in batch:
            command += ["(", *_glyph_arguments(font_path_for(character), character, rasterizer), ")"]
        command.append("gray:-")
        try:
            output = subprocess.run(command, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=_rasterizer_environment()).stdout
        except (OSError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", b"").decode("utf-8", errors="replace")
            raise FontRasterizerError(f"rasterizer failed for {batch!r}: {detail}") from error
        if len(output) != size * len(batch):
            raise FontRasterizerError(
                f"rasterizer returned {len(output)} bytes for {len(batch)} glyphs"
            )
        return output

    # Rendering dominates and scales poorly past a few renderers (measured:
    # 64 glyphs per process, three at once, is the plateau on a 12-core host).
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(batches) or 1))) as pool:
        outputs = list(pool.map(render, batches))
    for batch, output in zip(batches, outputs):
        for index, character in enumerate(batch):
            gray = apply_bottom_row_drop(output[index * size:(index + 1) * size], character, rasterizer)
            pixels = quantize_gray_4bpp(gray)
            results[character] = (gray, pixels, encode_glyph(pixels))
    return results


__all__ = [
    "FontRasterizerError",
    "apply_bottom_row_drop",
    "quantize_gray_4bpp",
    "rasterize_character",
    "rasterize_characters",
    "rasterizer_point_size",
]
