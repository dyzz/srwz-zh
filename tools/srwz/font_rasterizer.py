"""Uniform rasterization primitives for the global Chinese font."""

from __future__ import annotations

import subprocess
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


def _run_rasterizer(command: list[str], character: str) -> bytes:
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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


def rasterize_character(
    executable: str,
    font_path: Path,
    character: str,
    rasterizer: Mapping,
) -> tuple[bytes, bytes, bytes]:
    """Render one 24x24 glyph with the release-wide geometry policy."""

    if not isinstance(character, str) or len(character) != 1:
        raise FontRasterizerError("glyph rasterization needs one character")
    hinting = rasterizer.get("hinting")
    antialias = rasterizer.get("antialias")
    if not isinstance(hinting, bool) or not isinstance(antialias, bool):
        raise FontRasterizerError("rasterizer hinting/antialias lock is invalid")
    point_size = rasterizer_point_size(character, rasterizer)
    if character == " ":
        gray = bytes(GLYPH_WIDTH * GLYPH_HEIGHT)
    else:
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
                executable,
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
                "gray:-",
            ]
        else:
            command = [
                executable,
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
                "gray:-",
            ]
        gray = _run_rasterizer(command, character)
    pixels = quantize_gray_4bpp(gray)
    return gray, pixels, encode_glyph(pixels)


__all__ = [
    "FontRasterizerError",
    "quantize_gray_4bpp",
    "rasterize_character",
    "rasterizer_point_size",
]
