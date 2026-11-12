"""HarmonyOS Latin glyph bank for the proportional text scenes.

The proportional scenes (dialogue, scrolls, synopses, library bodies, lists) draw
Latin letters, digits and identifier punctuation from this bank instead of the
stock full-width glyphs; fixed-pitch UI keeps the stock glyphs. Text codes do not
change: the runtime swaps the glyph index while it draws (see proportional_hooks).

The bank lives in the font slots of the Cyrillic codes 0x8440..0x8491, which no
Chinese corpus or codebook row uses. Their glyph indices are 82 consecutive
slots (the renderer's index formula is linear in the trail byte): slot n is the
alphanumeric code 0x824F+n (the native 76-slot layout, gaps stay blank), slots
76..79 are the identifier punctuation, slots 80 and 81 are spare.

Letters and punctuation come from HarmonyOS Sans Condensed through the release
rasterizer itself (same point size, fixed canvas and baseline as the hanzi).
Digits come from the regular-width HarmonyOS Sans SC so numerals keep one wider
advance, and the zero carries a round centre dot (user decisions 2026-11-12).
The two families carry different vertical metrics: rendered the same way the
digits come out a row taller and two rows higher than the capitals. Digits are
therefore drawn supersampled at a locked scale and offset that put them on the
capitals' rows (cap top to baseline), see ``digits`` in the config.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .font import GLYPH_HEIGHT, GLYPH_SIZE, GLYPH_WIDTH, encode_glyph, standard_glyph_index
from .font_rasterizer import _rasterizer_environment, quantize_gray_4bpp, rasterize_characters
import subprocess

CONFIG = "config/fonts/zh-latin-bank.json"
BASE_CODE = 0x8440
LAST_CODE = 0x8491
ALNUM_BASE = 0x824F
ALNUM_SLOTS = 76
PUNCTUATION = "-.'/"
SLOT_COUNT = 82


class LatinBankError(ValueError):
    """The Latin glyph bank contract is violated."""


def slot_characters() -> dict[int, str]:
    """Bank slot -> ASCII character."""

    slots = {}
    for start, first, count in ((0x824F, "0", 10), (0x8260, "A", 26), (0x8281, "a", 26)):
        for offset in range(count):
            slots[start - ALNUM_BASE + offset] = chr(ord(first) + offset)
    for offset, character in enumerate(PUNCTUATION):
        slots[ALNUM_SLOTS + offset] = character
    return slots


def base_glyph_index() -> int:
    base = standard_glyph_index(BASE_CODE)
    if standard_glyph_index(LAST_CODE) - base != SLOT_COUNT - 1:
        raise LatinBankError("Cyrillic glyph slots are not one contiguous run")
    return base


def glyph_indices() -> list[int]:
    base = base_glyph_index()
    return [base + slot for slot in range(SLOT_COUNT)]


def load(root: Path) -> dict:
    path = root / CONFIG
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or config.get("base_code") != f"{BASE_CODE:04X}":
        raise LatinBankError("Latin bank config is malformed")
    for key in ("letters", "digits"):
        source = config["sources"][key]
        lock = json.loads((root / source["font_lock"]).read_text(encoding="utf-8"))
        font = root / lock["font"]["path"]
        if (hashlib.sha256((root / source["font_lock"]).read_bytes()).hexdigest() != source["font_lock_sha256"]
                or hashlib.sha256(font.read_bytes()).hexdigest() != lock["font"]["sha256"]):
            raise LatinBankError(f"Latin bank {key} font source drift")
        source["path"] = font
    if set(config["glyphs"]) != set(slot_characters().values()):
        raise LatinBankError("Latin bank glyph set drift")
    return config


def _dotted(gray: bytes, radius_64: int) -> bytes:
    """Add a round dot at the centre of the glyph's ink box (8x8 supersampling)."""

    pixels = quantize_gray_4bpp(gray)
    columns = [x for x in range(GLYPH_WIDTH) if any(pixels[y * GLYPH_WIDTH + x] >= 8 for y in range(GLYPH_HEIGHT))]
    rows = [y for y in range(GLYPH_HEIGHT) if any(pixels[y * GLYPH_WIDTH + x] >= 8 for x in range(GLYPH_WIDTH))]
    if not columns or not rows:
        raise LatinBankError("cannot dot an empty glyph")
    # Work in 1/128 px so the centre and radius stay exact integers.
    centre_x, centre_y = (columns[0] + columns[-1] + 1) * 64, (rows[0] + rows[-1] + 1) * 64
    radius = radius_64 * 2
    out = bytearray(gray)
    for y in range(GLYPH_HEIGHT):
        for x in range(GLYPH_WIDTH):
            inside = 0
            for sub_y in range(8):
                for sub_x in range(8):
                    dx = x * 128 + sub_x * 16 + 8 - centre_x
                    dy = y * 128 + sub_y * 16 + 8 - centre_y
                    inside += dx * dx + dy * dy <= radius * radius
            if inside:
                out[y * GLYPH_WIDTH + x] = max(out[y * GLYPH_WIDTH + x], (inside * 255 + 32) // 64)
    return bytes(out)


def _digit_gray(character: str, font: Path, rasterizer: Mapping, placement: Mapping, shift_rows: int) -> bytes:
    """Regular-width digit at the capitals' height and baseline (supersampled, box-filtered)."""

    sample = placement["supersample"]
    command = [
        rasterizer["executable"], "-size", f"{GLYPH_WIDTH * sample}x{GLYPH_HEIGHT * sample}", "xc:black",
        "-fill", "white", "-density", str(rasterizer["density"]), "-units", "PixelsPerInch",
        "-font", str(font), "-pointsize", str(rasterizer["point_size"] * sample * placement["scale_1000"] / 1000),
        "-define", "type:hinting=false", "-antialias", "-gravity", rasterizer["gravity"],
        "-annotate", f"+0{placement['y_offset_supersampled'] + shift_rows * sample:+d}", character,
        "-colorspace", "Gray", "-filter", "Box", "-resize", f"{GLYPH_WIDTH}x{GLYPH_HEIGHT}!", "-depth", "8", "gray:-",
    ]
    try:
        gray = subprocess.run(command, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=_rasterizer_environment()).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise LatinBankError(f"digit rasterizer failed for {character!r}") from error
    if len(gray) != GLYPH_WIDTH * GLYPH_HEIGHT:
        raise LatinBankError(f"digit rasterizer returned {len(gray)} bytes for {character!r}")
    return gray


def rasters(root: Path, rasterizer: Mapping, config: Mapping | None = None) -> dict[int, tuple[str, bytes, bytes]]:
    """Bank slot -> (character, raw gray canvas, packed 4bpp glyph)."""

    config = load(root) if config is None else config
    letters, digits = config["sources"]["letters"]["path"], config["sources"]["digits"]["path"]
    characters = slot_characters()
    # The whole bank sits ``baseline_shift_rows`` away from the hanzi canvas offset so
    # descenders (g j p q y reach 5.4 px below the baseline) stay inside the 24-row cell.
    shift_rows = config["baseline_shift_rows"]
    canvas = dict(rasterizer["cjk_fixed_canvas"])
    canvas["y_offset"] += shift_rows
    lifted = {**rasterizer, "cjk_fixed_canvas": canvas}
    rendered = rasterize_characters(
        rasterizer["executable"],
        lambda character: letters,
        [character for character in characters.values() if not character.isdigit()],
        lifted,
    )
    result = {}
    for slot, character in characters.items():
        gray = (_digit_gray(character, digits, rasterizer, config["digits"], shift_rows) if character.isdigit()
                else rendered[character][0])
        if character == "0":
            gray = _dotted(gray, config["zero_dot"]["radius_64"])
        # Solid ink on the first or last row means the glyph is clipped; descenders may
        # end in a faint antialiased trace on the last row.
        if max(gray[:GLYPH_WIDTH]) >= 128 or (max(gray[-GLYPH_WIDTH:]) >= 128 and character not in "gjpqy"):
            raise LatinBankError(f"Latin bank glyph {character!r} touches the cell edge")
        packed = encode_glyph(quantize_gray_4bpp(gray))
        if len(packed) != GLYPH_SIZE:
            raise LatinBankError("Latin bank glyph size mismatch")
        expected = config["glyphs"][character].get("raw_gray_sha256")
        if expected is not None and hashlib.sha256(gray).hexdigest() != expected:
            raise LatinBankError(f"Latin bank raster drift for {character!r}")
        result[slot] = (character, gray, packed)
    return result


def advance_px(config: Mapping, character: str, width: int) -> tuple[int, int]:
    """(bearing, advance) in scene pixels for a glyph drawn in a ``width``-pixel cell.

    The rasterizer centres the advance box in the 24-pixel canvas; the bearing
    removes that padding, the advance is the font's own advance rounded up.
    """

    natural = config["glyphs"][character]["advance_64"]
    bearing = max(0, ((GLYPH_WIDTH * 64 - natural) * width) // (2 * GLYPH_WIDTH * 64))
    advance = max(2, -((-natural * width) // (GLYPH_WIDTH * 64)))
    return bearing, advance


def space_advance(config: Mapping, width: int) -> int:
    natural = config["word_space"]["advance_64"]
    return max(config["word_space"]["minimum_px"] if width >= 20 else config["word_space"]["minimum_px"] - 1,
               (natural * width + GLYPH_WIDTH * 32) // (GLYPH_WIDTH * 64))


__all__ = ["ALNUM_BASE", "ALNUM_SLOTS", "BASE_CODE", "CONFIG", "LatinBankError", "PUNCTUATION", "SLOT_COUNT",
           "advance_px", "base_glyph_index", "glyph_indices", "load", "rasters", "slot_characters", "space_advance"]
