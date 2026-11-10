"""Read the game's own text placement through ARMSX2 runner tracepoints.

The text renderer (Original/Best 0x13A290, SP 0x13AD30) fills one 20-byte sprite
record per glyph: atlas u, v (s16), screen x, y (s16), ... . The record is complete at
GLYPH_RECORD_PC, where the glyph's code is still in scratchpad 0x70000060 and s0
points at the record. Tracing that PC therefore yields every glyph the game draws,
with the position it chose; SetText (a1 = the source line) gives the lines themselves.

Screen x is measured from the screen centre (a dialogue row starts at -240) and each
full-width glyph advances 21 px. Rows are told apart by y and by the frame.
Addresses were found by masked code match against the SP disc and verified on the
current builds (2026-10-30).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODEBOOK_PATH = PROJECT_ROOT / "work" / "writeback" / "zh-release-codebook-proposal.json"

GLYPH_RECORD_PC = {"original": 0x13AB50, "best": 0x13AB50, "sp": 0x13B5F0}
SET_TEXT_PC = {"original": 0x20C9B0, "best": 0x20CD70, "sp": 0x2112D0}
GLYPH_CODE_ADDRESS = 0x70000060
GLYPH_ADVANCE = 21


def trace_commands(edition: str, *, set_text_bytes: int = 160) -> list[str]:
    """Runner commands that arm the glyph-record and SetText tracepoints."""

    if edition not in GLYPH_RECORD_PC:
        raise ValueError(f"unknown edition {edition!r}; expected one of {sorted(GLYPH_RECORD_PC)}")
    return [
        f"trace {GLYPH_RECORD_PC[edition]:x} name=glyph @{GLYPH_CODE_ADDRESS:x}:2 s0:20",
        f"trace {SET_TEXT_PC[edition]:x} name=SetText a1:{set_text_bytes}",
    ]


def load_codebook(path: Path = CODEBOOK_PATH) -> dict[int, str]:
    """Map two-byte text codes to characters (primary, alias and legacy codes)."""

    data = json.loads(path.read_text(encoding="utf-8"))
    table: dict[int, str] = {}
    for key in ("assignments", "surface_alias_assignments", "source_compatibility_assignments"):
        for entry in data.get(key, []):
            table.setdefault(int(entry["code"], 16), entry["character"])
    # Dialogue continuation rows start with this blank glyph instead of 0x8140.
    from .continuation_indent import CODE as continuation_indent_code
    table.setdefault(continuation_indent_code, "\u3000")
    return table


def decode_code(code: int, codebook: Mapping[int, str]) -> str:
    if code in codebook:
        return codebook[code]
    try:
        return bytes([code >> 8, code & 0xFF]).decode("cp932")
    except UnicodeDecodeError:
        return f"[{code:04X}]"


def decode_line(data: bytes, codebook: Mapping[int, str]) -> str:
    """Decode a SetText capture: two-byte codes, 0x0A row breaks, NUL end."""

    out = []
    i = 0
    while i < len(data):
        byte = data[i]
        if byte == 0:
            break
        if byte == 0x0A:
            out.append("\n")
            i += 1
        elif byte >= 0x80 and i + 1 < len(data):
            out.append(decode_code((byte << 8) | data[i + 1], codebook))
            i += 2
        else:
            out.append(chr(byte) if 0x20 <= byte < 0x7F else f"[{byte:02X}]")
            i += 1
    return "".join(out)


@dataclass
class Glyph:
    code: int
    char: str
    x: int
    y: int
    atlas_u: int
    atlas_v: int


@dataclass
class TextRow:
    frame: int
    y: int
    glyphs: list[Glyph] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(g.char for g in self.glyphs)

    @property
    def x_start(self) -> int:
        return self.glyphs[0].x

    @property
    def x_end(self) -> int:
        """Right edge of the last glyph's advance."""
        return self.glyphs[-1].x + GLYPH_ADVANCE

    @property
    def width(self) -> int:
        return self.x_end - self.x_start


def read_hits(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def glyph_rows(hits: Iterable[dict], codebook: Mapping[int, str]) -> list[TextRow]:
    """Group glyph-record hits into rows: same frame, same y, in drawing order."""

    rows: dict[tuple[int, int], TextRow] = {}
    for hit in hits:
        if hit.get("name") != "glyph":
            continue
        mem = hit.get("mem", {})
        code_bytes = bytes.fromhex(mem.get(f"@{GLYPH_CODE_ADDRESS:x}:2", ""))
        record = bytes.fromhex(mem.get("s0:20", ""))
        if len(code_bytes) != 2 or len(record) < 8:
            continue
        (code,) = struct.unpack("<H", code_bytes)
        u, v, x, y = struct.unpack_from("<hhhh", record, 0)
        key = (hit["frame"], y)
        row = rows.setdefault(key, TextRow(frame=hit["frame"], y=y))
        row.glyphs.append(Glyph(code, decode_code(code, codebook), x, y, u, v))
    return list(rows.values())


def set_text_lines(hits: Iterable[dict], codebook: Mapping[int, str]) -> list[tuple[int, str]]:
    """(frame, decoded line) for every SetText call that had a source pointer."""

    lines = []
    for hit in hits:
        if hit.get("name") != "SetText":
            continue
        data = next(iter(hit.get("mem", {}).values()), "")
        if data:
            lines.append((hit["frame"], decode_line(bytes.fromhex(data), codebook)))
    return lines


def unique_rows(rows: Iterable[TextRow]) -> list[TextRow]:
    """Keep the first frame of each distinct row (the game redraws text every frame)."""

    seen = set()
    out = []
    for row in rows:
        key = (row.y, tuple((g.code, g.x) for g in row.glyphs))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out
