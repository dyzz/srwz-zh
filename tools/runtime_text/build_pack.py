#!/usr/bin/env python3
"""Build the SRWZ runtime-text pack for the special ARMSX2 build (SLPS-25887).

The pack lets an unmodified Japanese disc show the released Chinese story text.
For every STAGE dialogue record it stores the release-encoded Chinese string,
keyed by the record's offset in the original decoded STAGE overlay.  Every
two-byte code whose release glyph differs from the Japanese glyph is moved to a
private code that the original disc never uses; the emulator supplies those
glyph bitmaps at runtime, so the Japanese font and UI stay intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.codec import decode_production as decode  # noqa: E402
from srwz.font import (  # noqa: E402
    EXTENDED_CODE_START,
    GLYPH_SIZE as GLYPH_BYTES,
    decode_vt1_font_segment,
    glyph_index_for_code,
    read_extended_glyph_table,
)
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660  # noqa: E402
from srwz.iso_layout import (  # noqa: E402
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.stage import parse_stage, read_stage_function_addresses  # noqa: E402
from srwz.display_names import load_display_name_source, parse_display_names  # noqa: E402
from srwz.srvc import parse_srvc_archive, parse_srvc_archive_with_layout  # noqa: E402
from srwz.text import TextTable, load_text_table  # noqa: E402

SERIAL = "SLPS-25887"
STAGE_BASE = 0x7566F0
STAGE_NAME_OFFSET = 0x30
# Renderer constants compared by the speaker-style recognizer (FUN_00220e70).
QUOTE_CONSTANTS = {0x43C7D8: 0x9141, 0x43C7E0: 0x8169}
# Codes the renderer treats specially or that keep the original glyph.
NATIVE_CODES = {0x8140}
NATIVE_RANGES = ((0x824F, 0x829E),)  # full-width digits and Latin (narrow mode)
PRIVATE_LEADS = tuple(range(0x99, 0xA0)) + tuple(range(0xE0, 0xFC))
PRIVATE_TRAILS = tuple(range(0x40, 0x7F)) + tuple(range(0x80, 0xFD))
HB_SPEC = dict(table_start=30320, table_end=31144)
# Protagonist default names: the runtime name-token table ($n, $f, $l, $F, ...)
# holds these strings unless the player renamed the character.  Values that
# match byte for byte are replaced with the release's Chinese default.
NAME_DEFAULTS = {
    "ランド": "兰德",
    "トラビス": "特拉维斯",
    "ランド・トラビス": "兰德·特拉维斯",
    "セツコ": "节子",
    "オハラ": "小原",
    "セツコ・オハラ": "小原节子",
}


def iso_member(iso: Path, name: str) -> bytes:
    member = member_map(scan_iso9660(iso))[name]
    with iso.open("rb") as handle:
        handle.seek(member.extent_lba * SECTOR_SIZE)
        return handle.read(member.size)


def stage_chunks(slps: bytes, hb: bytes, stage: bytes) -> list[bytes]:
    spec = ExecutableOffsetSpec(name="HB STAGE offsets", member="HEDBDY/HB.BIN", **HB_SPEC)
    offsets = read_executable_archive_offsets(hb, spec, len(stage))
    return [decode(stage[a:b]).output for a, b in zip(offsets, offsets[1:])]


def raw_string(data: bytes, offset: int) -> bytes:
    end = data.index(b"\0", offset)
    return data[offset:end]


def tokens(raw: bytes):
    """Yield (kind, bytes) using the SRWZ text tokenizer rules."""
    i = 0
    while i < len(raw):
        code = raw[i]
        if 0x31 <= code <= 0x35:
            yield "tag", raw[i:i + 2]
            i += 2
        elif 0x80 <= code <= 0x9F or 0xE0 <= code <= 0xEA:
            yield "code", raw[i:i + 2]
            i += 2
        else:
            yield "byte", raw[i:i + 1]
            i += 1


def fnv1a32(data: bytes) -> int:
    value = 0x811C9DC5
    for byte in data:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def release_default_names(jp_slps: bytes, zh_slps: bytes, decode_release) -> list[tuple[bytes, bytes]]:
    """Find each Japanese default name in the stock ELF and read the release
    ELF's string at the same offset (the release keeps the string layout)."""
    result = []
    for japanese, chinese in NAME_DEFAULTS.items():
        needle = b"\0" + japanese.encode("cp932") + b"\0"
        start = 0
        while True:
            found = jp_slps.find(needle, start)
            if found < 0:
                raise SystemExit(f"release default name not found: {japanese}")
            offset = found + 1
            raw = zh_slps[offset:zh_slps.index(b"\0", offset)]
            if decode_release(raw) == chinese:
                result.append((japanese.encode("cp932"), raw))
                break
            start = found + 1
    return result


def release_table(table: TextTable, assignments: dict) -> TextTable:
    characters = dict(table.characters)
    for group in ("primary_assignments", "surface_alias_assignments", "source_compatibility_assignments"):
        characters.update({int(row["code"], 16): row["character"] for row in assignments[group]})
    for extension in assignments.get("extensions", []):
        characters.update({int(row["code"], 16): row["character"] for row in extension.get("assignments", [])})
    return TextTable(characters, table.tags)


def battle_line_pairs(iso: Path, rel: Path, table: TextTable, zh_table: TextTable) -> dict[bytes, bytes]:
    """Japanese SRVC line bytes -> release bytes, paired by (chunk, record)."""
    words = lambda data: tuple(struct.unpack(f"<{len(data) // 4}I", data))  # noqa: E731
    jp_bin, zh_bin = iso_member(iso, "BTL/SRVC.BIN"), (rel / "BTL/SRVC.BIN").read_bytes()
    jp_chunks = parse_srvc_archive(jp_bin, words(iso_member(iso, "BTL/SRVC.SEG")), table)
    zh_chunks = parse_srvc_archive_with_layout(
        zh_bin, words((rel / "BTL/SRVC.SEG").read_bytes()), jp_chunks, zh_table)
    pairs: dict[bytes, bytes] = {}
    for jp_chunk, zh_chunk in zip(jp_chunks, zh_chunks):
        if len(jp_chunk.records) != len(zh_chunk.records):
            raise SystemExit(f"SRVC chunk {jp_chunk.chunk_index} record count drift")
        for jp, zh in zip(jp_chunk.records, zh_chunk.records):
            key = jp_bin[jp.archive_text_start:jp.archive_text_end].rstrip(b"\0")
            value = zh_bin[zh.archive_text_start:zh.archive_text_end].rstrip(b"\0")
            if pairs.setdefault(key, value) != value:
                raise SystemExit(f"SRVC translation conflict in chunk {jp_chunk.chunk_index}")
    return pairs


def pilot_name_pairs(rel: Path, zh_table: TextTable) -> dict[bytes, bytes]:
    """Japanese COMPDATA pilot name bytes -> release bytes (first wins)."""
    config, jp_data, jp_parsed, _ = load_display_name_source(
        PROJECT_ROOT, PROJECT_ROOT / "config/display-names/compdata.json")
    zh_data = decode((rel / "DATA/COMPDATA.BN").read_bytes()).output
    zh_parsed = parse_display_names(zh_data, zh_table, config, verify_text_preimages=False)
    zh_entries = {entry.entry_id: entry for entry in zh_parsed.pilot_entries}
    pairs: dict[bytes, bytes] = {}
    for entry in jp_parsed.pilot_entries:
        zh = zh_entries[entry.entry_id]
        key = raw_string(jp_data, entry.target_offset)
        if key:
            pairs.setdefault(key, raw_string(zh_data, zh.target_offset))
    return pairs


def text_map_section(tag: bytes, pairs: list[tuple[bytes, bytes]]) -> bytes:
    """{tag, u32 count, {u32 fnv1a32(jp), u16 jp_len, u16 zh_len, zh bytes}}"""
    blob = bytearray(tag + struct.pack("<I", len(pairs)))
    for japanese, chinese in pairs:
        blob += struct.pack("<IHH", fnv1a32(japanese), len(japanese), len(chinese)) + chinese
    return bytes(blob)


def binary_pack(codes, glyph_blob, constants, stages, names=(), battle=(), pilots=()) -> bytes:
    """Serialize the pack read by the emulator (all integers little-endian).

    header  "SRWZRTX1", u32 stage_base, u32 name_offset, u32 glyph_count,
            u32 glyph_bytes, u32 constant_count, u32 stage_count
    codes   u16[glyph_count]           private code of each glyph ordinal
    glyphs  glyph_count * glyph_bytes  4-bpp 24x24 bitmaps
    consts  {u32 address, u16 code (big-endian byte order in memory), u16 0}
    stages  {char name[16], u32 record_count, {u32 offset, u32 fnv1a32(source),
             u16 length, bytes[length]}...}
    """
    blob = bytearray(b"SRWZRTX1")
    blob += struct.pack("<6I", STAGE_BASE, STAGE_NAME_OFFSET, len(codes),
                        GLYPH_BYTES, len(constants), len(stages))
    blob += struct.pack(f"<{len(codes)}H", *codes)
    blob += glyph_blob
    for address, code in constants:
        blob += struct.pack("<IHH", address, code, 0)
    for name, records in stages:
        blob += name.encode("ascii").ljust(16, b"\0")[:16]
        blob += struct.pack("<I", len(records))
        for offset, digest, payload in records:
            blob += struct.pack("<IIH", offset, digest, len(payload)) + payload
    # Optional trailing section: default-name replacements {u8 len, jp, u8 len, zh}.
    blob += b"NAME" + struct.pack("<I", len(names))
    for japanese, chinese in names:
        blob += bytes([len(japanese)]) + japanese + bytes([len(chinese)]) + chinese
    blob += text_map_section(b"BATL", list(battle))
    blob += text_map_section(b"PLNM", list(pilots))
    return bytes(blob)


class PrivateCodes:
    """Private code allocation that stays stable across pack versions.

    The private code of a release glyph is ``free[release_glyph_index]``.  The
    release font registry is append-only, so a code already stored in game
    memory (savestates, Back Log) keeps meaning the same character.
    """

    def __init__(self, jp_ext_codes: set[int]):
        self.free = [
            (lead << 8) | trail
            for lead in PRIVATE_LEADS
            for trail in PRIVATE_TRAILS
            if ((lead << 8) | trail) >= EXTENDED_CODE_START
            and ((lead << 8) | trail) not in jp_ext_codes
        ]
        self.by_index: dict[int, tuple[int, bytes, str]] = {}

    def code_for(self, glyph_index: int, bitmap: bytes, character: str) -> int:
        if glyph_index >= len(self.free):
            raise SystemExit("private code space exhausted")
        entry = self.by_index.get(glyph_index)
        if entry is None:
            entry = (self.free[glyph_index], bitmap, character)
            self.by_index[glyph_index] = entry
        return entry[0]

    @property
    def codes(self) -> list[int]:
        return [self.by_index[i][0] for i in sorted(self.by_index)]

    @property
    def glyphs(self) -> list[bytes]:
        return [self.by_index[i][1] for i in sorted(self.by_index)]

    @property
    def characters(self) -> list[str]:
        return [self.by_index[i][2] for i in sorted(self.by_index)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", default="rom/original.iso")
    parser.add_argument("--release-root", default="work/build/zh-release-full-story/components")
    parser.add_argument("--table", default="vendor/upstream-python/project/tbl_all.json")
    parser.add_argument("--out", default="work/build/runtime-text-pack/SLPS-25887")
    parser.add_argument("--stages", default="", help="comma-separated chunk indices (default all)")
    args = parser.parse_args()

    iso = PROJECT_ROOT / args.iso
    rel = PROJECT_ROOT / args.release_root
    out = PROJECT_ROOT / args.out
    table = load_text_table(PROJECT_ROOT / args.table)

    jp_slps = iso_member(iso, "SLPS_258.87")
    jp_chunks = stage_chunks(jp_slps, iso_member(iso, "HEDBDY/HB.BIN"), iso_member(iso, "DATA/STAGE.BIN"))
    zh_slps = (rel / "SLPS_258.87").read_bytes()
    zh_chunks = stage_chunks(zh_slps, (rel / "HEDBDY/HB.BIN").read_bytes(), (rel / "DATA/STAGE.BIN").read_bytes())
    jp_font = decode_vt1_font_segment(jp_slps, iso_member(iso, "DATA/VT1.BIN")).decoded
    zh_font = decode_vt1_font_segment(zh_slps, (rel / "DATA/VT1.BIN").read_bytes()).decoded
    jp_ext = read_extended_glyph_table(jp_slps)
    zh_ext = read_extended_glyph_table(zh_slps)
    jp_functions = read_stage_function_addresses(jp_slps)
    zh_functions = read_stage_function_addresses(zh_slps)

    def glyph(font: bytes, ext, code: int) -> bytes:
        index = glyph_index_for_code(code, ext)
        return font[index * GLYPH_BYTES:(index + 1) * GLYPH_BYTES]

    private = PrivateCodes({entry.code for entry in jp_ext})
    assignments = json.loads((PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json").read_text())
    release_characters = {}
    for group in ("primary_assignments", "surface_alias_assignments", "source_compatibility_assignments"):
        for row in assignments[group]:
            release_characters.setdefault(int(row["code"], 16), row["character"])
    for extension in assignments.get("extensions", []):
        for row in extension.get("assignments", []):
            release_characters.setdefault(int(row["code"], 16), row["character"])
    transcoded: dict[int, int] = {}

    def transcode_code(code: int) -> int:
        if code in NATIVE_CODES or any(lo <= code <= hi for lo, hi in NATIVE_RANGES):
            return code
        if code not in transcoded:
            bitmap = glyph(zh_font, zh_ext, code)
            try:
                same = glyph(jp_font, jp_ext, code) == bitmap
            except ValueError:
                same = False
            transcoded[code] = code if same else private.code_for(
                glyph_index_for_code(code, zh_ext), bitmap, release_characters.get(code, ""))
        return transcoded[code]

    def transcode(raw: bytes) -> bytes:
        result = bytearray()
        for kind, chunk in tokens(raw):
            if kind == "code":
                result += struct.pack(">H", transcode_code(struct.unpack(">H", chunk)[0]))
            else:
                result += chunk
        return bytes(result)

    selected = (
        [int(value) for value in args.stages.split(",")] if args.stages
        else range(len(jp_chunks))
    )
    (out / "story").mkdir(parents=True, exist_ok=True)
    binary_stages = []
    stages_manifest = {}
    record_total = 0
    for index in selected:
        jp_data, zh_data = jp_chunks[index], zh_chunks[index]
        jp_parsed = parse_stage(jp_data, table, stage_index=index, function_address=jp_functions[index])
        if not jp_parsed.dialogue_count:
            continue
        zh_parsed = parse_stage(zh_data, table, stage_index=index, function_address=zh_functions[index])
        zh_offsets = {e.entry_id: e.text_offset for e in zh_parsed.entries if e.kind == "dialogue"}
        name = jp_data[STAGE_NAME_OFFSET:STAGE_NAME_OFFSET + 0x20].split(b"\0", 1)[0].decode("ascii")
        records = {}
        for entry in jp_parsed.entries:
            if entry.kind != "dialogue" or entry.entry_id not in zh_offsets:
                continue
            source = raw_string(jp_data, entry.text_offset)
            target = transcode(raw_string(zh_data, zh_offsets[entry.entry_id]))
            records[entry.text_offset] = {
                "o": entry.text_offset,
                "h": f"{fnv1a32(source):08x}",
                "z": target.hex(),
                "id": entry.entry_id,
            }
        path = f"story/stage-{index:03d}.json"
        (out / path).write_text(json.dumps({
            "stage": index, "name": name,
            "records": [records[key] for key in sorted(records)],
        }, ensure_ascii=False, separators=(",", ":")))
        stages_manifest[name] = path
        binary_stages.append((name, [
            (key, int(records[key]["h"], 16), bytes.fromhex(records[key]["z"]))
            for key in sorted(records)
        ]))
        record_total += len(records)

    constants = {}
    binary_constants = []
    for address, release_code in QUOTE_CONSTANTS.items():
        code = transcode_code(release_code)
        constants[f"0x{address:06X}"] = f"{code:04X}"
        binary_constants.append((address, code))
    def decode_release(raw: bytes) -> str:
        out, i = "", 0
        while i < len(raw):
            if raw[i] >= 0x80:
                code = (raw[i] << 8) | raw[i + 1]
                out += release_characters.get(code, "?")
                i += 2
            else:
                out += chr(raw[i])
                i += 1
        return out

    names = [(jp, transcode(zh)) for jp, zh in release_default_names(jp_slps, zh_slps, decode_release)]
    zh_table = release_table(table, assignments)
    battle = [(jp, transcode(zh)) for jp, zh in battle_line_pairs(iso, rel, table, zh_table).items()]
    pilots = [(jp, transcode(zh)) for jp, zh in pilot_name_pairs(rel, zh_table).items()]
    glyph_blob = b"".join(private.glyphs)
    (out / "glyphs.bin").write_bytes(glyph_blob)
    (out / "pack.bin").write_bytes(binary_pack(
        private.codes, glyph_blob, binary_constants, binary_stages, names, battle, pilots))
    manifest = {
        "schema": 1,
        "serial": SERIAL,
        "stage_base": f"0x{STAGE_BASE:06X}",
        "stage_name_offset": STAGE_NAME_OFFSET,
        "glyph_bytes": GLYPH_BYTES,
        "glyph_file": "glyphs.bin",
        "glyph_sha256": hashlib.sha256(glyph_blob).hexdigest(),
        "private_codes": [f"{code:04X}" for code in private.codes],
        "private_characters": "".join(c or "\uFFFD" for c in private.characters),
        "max_record_bytes": max((len(p) for _, rows in binary_stages for _, _, p in rows), default=0),
        "quote_constants": constants,
        "default_names": {jp.decode("cp932"): zh.hex() for jp, zh in names},
        "battle_line_count": len(battle),
        "pilot_name_count": len(pilots),
        "stages": stages_manifest,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"battle_lines={len(battle)} pilot_names={len(pilots)} "
          f"stages={len(stages_manifest)} records={record_total} "
          f"private_glyphs={len(private.glyphs)} free={len(private.free)} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
