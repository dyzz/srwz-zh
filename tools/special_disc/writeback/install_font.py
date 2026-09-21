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
FONT_DECODED_SIZE = 1290240
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
