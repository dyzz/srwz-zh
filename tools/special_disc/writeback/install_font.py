"""Install the project's Chinese font into the SP disc's VT1 archive.

SP's VT1 font chunk (index 3) is byte-identical to the main game's Japanese
one, so the Chinese font stream the main game already builds is reused as is:

  work/build/zh-release-font/components/DATA/VT1.BIN chunk 2   (629,104 bytes)

It does not fit SP's 599,344-byte slot. The main game solves this by growing the
font backward into the zero tail of the preceding chunk; in SP the preceding
chunk is a 66.8 MB audio block that SP adds, and it has only 1,031 zero bytes.
So the audio block itself is moved back 29,760 bytes into chunk 1's zero tail
(356,850 bytes there, all proven zero), which frees exactly the room the font
needs. The archive keeps its size, every other chunk keeps its bytes and
offset, and only two executable table entries change (chunk 2 and chunk 3).

Outputs (work/build/special-disc/components/font/):
  DATA/VT1.BIN   VT1 with the moved audio block and the Chinese font
  SLPS_259.20    executable with VT1 table entries 2 and 3 updated
  report.json    hashes, the borrowed range, and the decode checks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets  # noqa: E402

from special_disc.source import SOURCE_ISO as ISO  # noqa: E402
from special_disc.source import DISC_INVENTORY as LOCKS  # noqa: E402
OUT = ROOT / "work/build/special-disc/components/font"
EXE = "SLPS_259.20"
VT1 = "DATA/VT1.BIN"
VT1_TABLE = 0x353790
FONT_CHUNK = 3  # SP: 0 compressed block, 1 audio, 2 SP's own audio, 3 font
AUDIO_CHUNK = 2
# the main game's finished Chinese font component
ZH_COMPONENTS = ROOT / "work/build/zh-release-font/components"
ZH_FONT_CHUNK = 2
def _font_glyphs() -> int:
    """Glyph count of the active release font profile: the stock 4,480, or a larger font_capacity (the
    Traditional build of the dual disc: 4,992 glyphs with the linear area)."""
    import json
    profile = json.loads((ROOT / "config/fonts/zh-release-font.json").read_text(encoding="utf-8"))
    return (profile.get("font_capacity") or {}).get("glyph_count", 4480)


FONT_DECODED_SIZE = _font_glyphs() * 288      # 1,290,240 for the stock 4,480 glyphs
JAPANESE_FONT_SHA256 = "e68a24df2daaf16f472e55e0ba9b2282752bb70225aedc0bbb8aeef7713662bd"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(members, locks, name: str) -> bytes:
    m = members[name]
    with ISO.open("rb") as f:
        f.seek(m.extent_lba * 2048)
        data = f.read(m.size)
    assert sha256(data) == locks[name], f"{name} lock drift"
    return data


def sp_offsets(exe: bytes, start: int, size: int) -> list[int]:
    """SP's tables are start offsets terminated by the archive size."""
    values, pos = [], start
    while True:
        value = struct.unpack_from("<I", exe, pos)[0]
        values.append(value)
        pos += 4
        if value == size:
            return values


def replace_font_slot(vt1: bytes, exe: bytes, font: bytes, expected_sha256: str) -> bytes:
    """Refresh the font inside an already allocated slot, preserving all offsets."""
    offsets = sp_offsets(exe, VT1_TABLE, len(vt1))
    if offsets != sorted(set(offsets)) or offsets[0] != 0:
        raise ValueError('SP font archive offsets invalid')
    start, end = offsets[FONT_CHUNK:FONT_CHUNK + 2]
    decoded = decode_production(font)
    if len(decoded.output) != FONT_DECODED_SIZE or sha256(decoded.output) != expected_sha256:
        raise ValueError('SP replacement font identity drift')
    payload = font[:decoded.consumed]
    if len(payload) > end - start:
        raise ValueError('SP replacement font exceeds existing slot; explicit layout migration required')
    output = vt1[:start] + payload + bytes(end - start - len(payload)) + vt1[end:]
    if len(output) != len(vt1) or decode_production(output[start:end]).output != decoded.output:
        raise ValueError('SP replacement font readback drift')
    return output


# SP ELF file offsets in the native code/data segment (VA 0x100000 at 0x980).
FONT_BUFFER_WORD = 0x4524E8 - 0x100000 + 0x980
GLYPH_FALLBACK = 0x13B3FC - 0x100000 + 0x980
STOCK_FONT_BYTES = 4480 * 288
SUPPORTED_FONT_BYTES = (STOCK_FONT_BYTES, 4800 * 288, 4992 * 288)


def configure_font_loader(executable: bytearray, decoded_bytes: int) -> None:
    """Match the EE allocation and glyph lookup to the decoded SP font."""
    if decoded_bytes not in SUPPORTED_FONT_BYTES:
        raise ValueError(f'unsupported SP font size: {decoded_bytes}')
    capacity, = struct.unpack_from('<I', executable, FONT_BUFFER_WORD)
    lookup = struct.unpack_from('<II', executable, GLYPH_FALLBACK)
    native = (0x1000000C, 0xA4200062)
    linear = (0x10000002, 0x90240061)
    if capacity not in SUPPORTED_FONT_BYTES or lookup not in (native, linear):
        raise ValueError('SP font loader preimage drift')
    struct.pack_into('<I', executable, FONT_BUFFER_WORD, decoded_bytes)
    struct.pack_into('<II', executable, GLYPH_FALLBACK,
                     *(linear if decoded_bytes > STOCK_FONT_BYTES else native))


def replace_font_with_relocation(vt1: bytes, exe: bytes, font: bytes, expected_sha256: str):
    """Grow only into verified zero padding before the preceding raw audio block."""
    offsets = sp_offsets(exe, VT1_TABLE, len(vt1))
    if offsets != sorted(set(offsets)) or offsets[0] != 0:
        raise ValueError('SP font archive offsets invalid')
    decoded = decode_production(font)
    if len(decoded.output) != FONT_DECODED_SIZE or sha256(decoded.output) != expected_sha256:
        raise ValueError('SP replacement font identity drift')
    audio_start, start, end = offsets[AUDIO_CHUNK:FONT_CHUNK + 2]
    needed = (decoded.consumed + 15) // 16 * 16
    borrow = max(0, needed - (end - start))
    executable = bytearray(exe)
    configure_font_loader(executable, len(decoded.output))
    if not borrow:
        return replace_font_slot(vt1, exe, font, expected_sha256), bytes(executable), {'borrowed_bytes': 0}
    if audio_start - borrow < offsets[AUDIO_CHUNK - 1] or any(vt1[audio_start - borrow:audio_start]):
        raise ValueError('SP font growth would overwrite nonzero donor bytes')
    audio = vt1[audio_start:start]
    output = bytearray(vt1)
    output[audio_start - borrow:start - borrow] = audio
    output[start - borrow:end] = font[:decoded.consumed] + bytes(needed - decoded.consumed)
    for index in (AUDIO_CHUNK, FONT_CHUNK):
        struct.pack_into('<I', executable, VT1_TABLE + index * 4, offsets[index] - borrow)
    after = sp_offsets(executable, VT1_TABLE, len(output))
    if (len(output) != len(vt1) or after[:AUDIO_CHUNK] != offsets[:AUDIO_CHUNK]
            or after[FONT_CHUNK + 1:] != offsets[FONT_CHUNK + 1:]
            or output[:audio_start - borrow] != vt1[:audio_start - borrow]
            or output[end:] != vt1[end:]
            or output[after[AUDIO_CHUNK]:after[FONT_CHUNK]] != audio
            or decode_production(output[after[FONT_CHUNK]:end]).output != decoded.output):
        raise ValueError('SP relocated font/audio readback drift')
    return bytes(output), bytes(executable), {
        'borrowed_bytes': borrow, 'donor_tail_zero': True,
        'audio_sha256': sha256(audio), 'audio_bytes_preserved': True,
        'archive_size_preserved': True, 'following_offsets_preserved': True,
        'old_audio_start': audio_start, 'new_audio_start': after[AUDIO_CHUNK],
        'old_font_start': start, 'new_font_start': after[FONT_CHUNK],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ZH_COMPONENTS)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    source_root, output_root = args.source.resolve(), args.output.resolve()
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    exe = bytearray(read_member(members, locks, EXE))
    vt1 = read_member(members, locks, VT1)
    table = sp_offsets(exe, VT1_TABLE, len(vt1))

    # 1. the Chinese font stream, taken from the main game's font component
    zh_exe = (source_root / EXE.replace("259.20", "258.87")).read_bytes()
    zh_vt1 = (source_root / VT1).read_bytes()
    zh_table = read_executable_archive_offsets(zh_exe, CORE_ARCHIVE_SPECS["VT1.BIN"], len(zh_vt1))
    font = zh_vt1[zh_table[ZH_FONT_CHUNK]:zh_table[ZH_FONT_CHUNK + 1]]
    font_decoded = decode_production(font)
    assert len(font_decoded.output) == FONT_DECODED_SIZE, len(font_decoded.output)
    assert sha256(font_decoded.output) != JAPANESE_FONT_SHA256, "the component still holds the Japanese font"
    font = font[:font_decoded.consumed]

    # 2. SP's own font chunk must be the Japanese one this replaces
    japanese = decode_production(vt1[table[FONT_CHUNK]:table[FONT_CHUNK + 1]])
    assert sha256(japanese.output) == JAPANESE_FONT_SHA256, "SP font chunk is not the known Japanese font"

    # 3. move the audio block back so the font slot grows to fit
    slot = table[FONT_CHUNK + 1] - table[FONT_CHUNK]
    needed = (len(font) + 15) // 16 * 16
    borrow = needed - slot
    assert borrow > 0 and borrow % 16 == 0, (needed, slot)
    audio_start, audio_end = table[AUDIO_CHUNK], table[AUDIO_CHUNK + 1]
    donor = vt1[audio_start - borrow:audio_start]
    assert not any(donor), "the preceding chunk's tail is not zero"
    audio = vt1[audio_start:audio_end]
    out = bytearray(vt1)
    out[audio_start - borrow:audio_end - borrow] = audio
    out[audio_end - borrow:table[FONT_CHUNK + 1]] = font + bytes(needed - len(font))
    assert len(out) == len(vt1), "VT1 changed size"

    configure_font_loader(exe, len(font_decoded.output))

    # 4. two table entries move with it
    for index in (AUDIO_CHUNK, FONT_CHUNK):
        struct.pack_into("<I", exe, VT1_TABLE + 4 * index, table[index] - borrow)
    patched = sp_offsets(bytes(exe), VT1_TABLE, len(out))
    assert patched[:AUDIO_CHUNK] == table[:AUDIO_CHUNK], "earlier chunks moved"
    assert patched[FONT_CHUNK + 1:] == table[FONT_CHUNK + 1:], "later chunks moved"

    # 5. read every chunk back through the patched table
    checked = 0
    for index in range(len(patched) - 1):
        blob = bytes(out[patched[index]:patched[index + 1]])
        if index == FONT_CHUNK:
            assert decode_production(blob).output == font_decoded.output, "font did not read back"
            checked += 1
            continue
        if index == AUDIO_CHUNK:  # raw audio, not a codec stream: compare the bytes
            assert blob == audio, "the moved audio block changed"
            checked += 1
            continue
        was = vt1[table[index]:table[index + 1]]
        if index == AUDIO_CHUNK - 1:  # the donor keeps its payload, only zero padding is gone
            assert blob == was[:len(was) - borrow], "donor payload changed"
            continue
        assert blob == was, f"chunk {index} changed"
    assert checked == 2

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "DATA").mkdir(exist_ok=True)
    (output_root / VT1).write_bytes(bytes(out))
    (output_root / EXE).write_bytes(bytes(exe))
    (output_root / 'font.bin').write_bytes(font)
    report = dict(
        iso=str(ISO.relative_to(ROOT)),
        font=dict(source=str((source_root / VT1).relative_to(ROOT)), chunk=ZH_FONT_CHUNK,
                  compressed=len(font), allocated=needed, decoded=len(font_decoded.output),
                  decoded_sha256=sha256(font_decoded.output)),
        move=dict(chunk=AUDIO_CHUNK, bytes=borrow, from_offset=hex(audio_start), to_offset=hex(audio_start - borrow),
                  donor_chunk=AUDIO_CHUNK - 1, donor_tail_zero=True,
                  japanese_font_slot=slot, table_offset=hex(VT1_TABLE),
                  table_entries={str(i): dict(old=hex(table[i]), new=hex(patched[i])) for i in (AUDIO_CHUNK, FONT_CHUNK)}),
        verified=dict(chunks=len(patched) - 1, unchanged_chunks=len(patched) - 3,
                      decoded_chunks=checked, japanese_font_sha256=JAPANESE_FONT_SHA256),
        files={VT1: sha256(bytes(out)), EXE: sha256(bytes(exe))},
        original_files={VT1: locks[VT1], EXE: locks[EXE]},
    )
    (output_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
