"""New-game protagonist profiles: narrow Latin nickname and a shared, re-split slot pair.

The two three-line profiles on the protagonist selection screen sit back to back in
COMPDATA (male 128 bytes, female directly after it) and are reached through two
absolute pointers in a four-entry table. The male profile with the narrow
``“THE HEAT”`` run needs more than its 128 bytes while the female profile needs
less than its own, so the pair is re-split: the female text starts right after
the male text's terminator, with its pointer moved by the same amount. Nothing outside the two original spans and that one pointer
changes.

The corpus keeps the plain text. ``stored_text`` adds the render tags at the
storage boundary.

Size: the stock surface draws the 22 px font cell at 18 px (width/advance 0x12,
nine half-line units high). That down-sampling drops glyph rows and columns
unevenly, so neighbouring hanzi look like different sizes. Both profiles are
therefore stored with a prefix that draws the cell 1:1 (22 x 22); the row pitch
(23 px) and the box (the Japanese rows reach 27 x 18 = 486 px) leave room for
it. The pair may also use the zero padding that follows the female span.
"""

from __future__ import annotations

import re
import struct
from typing import Callable

MALE_OFFSET = 0x7FD20
FEMALE_OFFSET = 0x7FDA0
MALE_POINTER_OFFSET = 0x61630
FEMALE_POINTER_OFFSET = 0x61634
RAW_OFFSETS = (f"0x{MALE_OFFSET:X}", f"0x{FEMALE_OFFSET:X}")

STOCK_ADVANCE = 0x12
SURFACE_ADVANCE = 0x16  # the font cell, drawn 1:1
SURFACE_HEIGHT = 0x0B  # half-line units: 22 lines
LATIN_WIDTH = 0x11
LATIN_ADVANCE = 0x0F
TIGHT_ADVANCE = 0x09
OPENING_QUOTE_ADVANCE = 0x0D
CLOSING_QUOTE_ADVANCE = 0x10
MAX_LINE_PIXELS = 27 * STOCK_ADVANCE
WORD_GAP = "\u3000"

_QUOTED_LATIN = re.compile(r"“([A-Za-z]+(?: [A-Za-z]+)*)”")


class ProtagonistProfileError(ValueError):
    """The profile pair no longer matches the audited layout."""


def _prefix() -> str:
    return (
        f"<width:{SURFACE_ADVANCE:02X}><height:{SURFACE_HEIGHT:02X}>"
        f"<space:{SURFACE_ADVANCE:02X}>"
    )


def _space(value: int) -> str:
    return f"<space:{value:02X}>"


def _width(value: int) -> str:
    return f"<width:{value:02X}>"


def _narrow_run(match: re.Match) -> str:
    words = match.group(1).split(" ")
    parts = [_space(OPENING_QUOTE_ADVANCE), "“", _width(LATIN_WIDTH)]
    for index, word in enumerate(words):
        last = index == len(words) - 1
        parts.append(_space(LATIN_ADVANCE))
        if last:
            # The closing quote's ink sits on the right of its cell: pull it in.
            if len(word) > 1:
                parts.append(word[:-1])
            parts += [_space(TIGHT_ADVANCE), word[-1]]
        else:
            # A raw 0x20 would desync the two-byte glyph pairing: store the word
            # gap as the two-byte blank (0x8140).
            parts += [word, _space(TIGHT_ADVANCE), WORD_GAP]
    parts += [
        _width(SURFACE_ADVANCE),
        _space(CLOSING_QUOTE_ADVANCE),
        "”",
        _space(SURFACE_ADVANCE),
    ]
    return "".join(parts)


def stored_text(text: str) -> str:
    """Return the text as stored: 1:1 glyph size, quoted Latin runs drawn narrow."""

    if not isinstance(text, str) or not text:
        raise ProtagonistProfileError("protagonist profile text is empty")
    if "<" in text or ">" in text:
        raise ProtagonistProfileError(
            "protagonist profile corpus text must not carry render tags"
        )
    return _prefix() + _QUOTED_LATIN.sub(_narrow_run, text)


def line_pixels(text: str) -> list[int]:
    """Drawn width of every row of the plain corpus text on this surface."""

    widths = []
    for row in stored_text(text).split("\n"):
        advance = SURFACE_ADVANCE
        total = 0
        for token in re.split(r"(<[a-z]+:[0-9A-F]{2}>)", row):
            if not token:
                continue
            if token.startswith("<space:"):
                advance = int(token[7:9], 16)
            elif token.startswith("<"):
                continue
            else:
                total += advance * len(token)
        widths.append(total)
    return widths


def _pointers(data: bytes) -> tuple[int, int]:
    return struct.unpack_from("<II", data, MALE_POINTER_OFFSET)


def _original_layout(original: bytes, original_female_consumed: int) -> tuple[int, int]:
    male_pointer, female_pointer = _pointers(original)
    if female_pointer - male_pointer != FEMALE_OFFSET - MALE_OFFSET:
        raise ProtagonistProfileError("protagonist profile pointer table drift")
    region_end = FEMALE_OFFSET + original_female_consumed
    # The zero padding between the female terminator and the next string
    # belongs to the pair too.
    while region_end < len(original) and original[region_end] == 0:
        region_end += 1
    if region_end - FEMALE_OFFSET > 0x100:
        raise ProtagonistProfileError("protagonist profile source span drift")
    return male_pointer, region_end


def apply(
    current: bytes,
    original: bytes,
    male_text: str,
    female_text: str,
    *,
    encode: Callable[[str], bytes],
    decode: Callable[[bytes, int], str],
    original_female_consumed: int,
) -> tuple[bytes, dict]:
    """Write both profiles into the re-split pair and move the female pointer."""

    male_pointer, region_end = _original_layout(original, original_female_consumed)
    if len(current) != len(original):
        raise ProtagonistProfileError("protagonist profile member size drift")
    male_stored = stored_text(male_text)
    female_stored = stored_text(female_text)
    for label, text in (("male", male_text), ("female", female_text)):
        widths = line_pixels(text)
        if len(widths) != 3 or max(widths) > MAX_LINE_PIXELS:
            raise ProtagonistProfileError(
                f"{label} protagonist profile exceeds its three-row box: {widths}"
            )
    male_bytes = encode(male_stored)
    female_bytes = encode(female_stored)
    capacity = region_end - MALE_OFFSET
    if len(male_bytes) + len(female_bytes) > capacity:
        raise ProtagonistProfileError(
            "protagonist profile overflow: "
            f"male {len(male_bytes)} + female {len(female_bytes)} > {capacity}"
        )
    female_offset = MALE_OFFSET + len(male_bytes)
    output = bytearray(current)
    payload = male_bytes + female_bytes
    output[MALE_OFFSET:region_end] = payload + bytes(capacity - len(payload))
    struct.pack_into(
        "<II",
        output,
        MALE_POINTER_OFFSET,
        male_pointer,
        male_pointer + len(male_bytes),
    )
    result = bytes(output)
    report = verify(
        result,
        original,
        male_text,
        female_text,
        decode=decode,
        original_female_consumed=original_female_consumed,
    )
    report["pair_headroom"] = capacity - len(payload)
    return result, report


def verify(
    data: bytes,
    original: bytes,
    male_text: str,
    female_text: str,
    *,
    decode: Callable[[bytes, int], str],
    original_female_consumed: int,
) -> dict:
    """Read both profiles back through the pointers the game follows."""

    male_pointer, region_end = _original_layout(original, original_female_consumed)
    data_male_pointer, data_female_pointer = _pointers(data)
    female_offset = MALE_OFFSET + data_female_pointer - data_male_pointer
    if data_male_pointer != male_pointer or not (
        MALE_OFFSET < female_offset < region_end
    ):
        raise ProtagonistProfileError("protagonist profile pointers drift")
    if decode(data, MALE_OFFSET) != stored_text(male_text):
        raise ProtagonistProfileError("male protagonist profile readback mismatch")
    if decode(data, female_offset) != stored_text(female_text):
        raise ProtagonistProfileError("female protagonist profile readback mismatch")
    if data[female_offset - 1] != 0 or data[region_end - 1] != 0:
        raise ProtagonistProfileError("protagonist profile terminator missing")
    if 0 in data[MALE_OFFSET : female_offset - 1]:
        raise ProtagonistProfileError("male protagonist profile overlaps the female text")
    return {
        "male_offset": f"0x{MALE_OFFSET:X}",
        "female_offset": f"0x{female_offset:X}",
        "female_pointer_delta": female_offset - FEMALE_OFFSET,
        "male_stored_text": stored_text(male_text),
        "male_line_pixels": line_pixels(male_text),
        "female_line_pixels": line_pixels(female_text),
        "region_end": f"0x{region_end:X}",
        "readback_exact": True,
    }
