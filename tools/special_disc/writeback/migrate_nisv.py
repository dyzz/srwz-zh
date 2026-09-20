"""Bring the main game's finished NISVDATA Chinese into the SP disc.

NISVDATA holds 7 compressed chunks. The main game's build is again the answer
key (its Japanese and built Chinese archives chunk by chunk); every chunk is
rewritten inside its own SP slot, so no offset in the executable changes.

  chunk 5  tutorial pages: SP's decoded chunk is identical to the main game's
           Japanese one, so the main game's finished Chinese chunk is used.
  chunk 6  Strategy Q&A: one metadata allocation, then 102 fixed page
           allocations. The main build kept every allocation's size, so an SP
           page byte-identical to the main game's Japanese page of the same
           number becomes the main game's Chinese page; the metadata strings
           (sequential, NUL-terminated) are paired by ordinal the same way.
           Pages and strings SP changed keep their Japanese.
  chunk 4  squad-name suggestions: 28-byte name slots in 286-byte records; a
           name whose Japanese has exactly one Chinese answer in the main game
           takes those bytes, every other byte of the record stays.
  chunk 0  the Library menu container: SP moved the six-label picture to
           another record, byte-identical to the main game's. Every block the
           main build changed in its chunk 0 is found in SP's chunk 0 by its
           exact Japanese bytes and replaced by the main build's bytes.

Outputs (work/build/special-disc/components/nisv/):
  DATA/NISVDATA.BIN   the archive with chunks 0 and 4-6 rewritten in their slots
  report.json         what changed per chunk, slot use, the readback check
"""
from __future__ import annotations

import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production, reencode_changed_suffix  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets  # noqa: E402
from srwz.text import decode_text, load_text_table  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_textures import blocks, runs  # noqa: E402

from special_disc.source import SOURCE_ISO as ISO  # noqa: E402
from special_disc.source import DISC_INVENTORY as LOCKS  # noqa: E402
TABLE = ROOT / "vendor/upstream-python/project/tbl_all.json"
OG_DISC = ROOT / "work/disc"
OG_BUILD = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                   "/project/work/build/zh-release-full-story/components")
OUT = ROOT / "work/build/special-disc/components/nisv"
MEMBER = "DATA/NISVDATA.BIN"
OG_SPEC = ExecutableOffsetSpec(name="NISV", member=MEMBER, table_start=0x328E90, table_end=0x328EAC)
SP_TABLE = 0x384A00
SQUAD_BASE, SQUAD_STRIDE, SQUAD_NAME = 0x22, 286, 28
QA_METADATA_TEXT = 0x476
QA_METADATA_STRINGS = 4 + 26 + 102 + 4 + 26 + 102


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
    values, pos = [], start
    while True:
        value = struct.unpack_from("<I", exe, pos)[0]
        values.append(value)
        pos += 4
        if value == size:
            return values


def allocations(chunk: bytes) -> list[tuple[int, int]]:
    """Strategy Q&A allocations as absolute (start, size) in the decoded chunk."""
    count, base = struct.unpack_from("<II", chunk, 0)
    return [(base + offset, size) for offset, size in
            (struct.unpack_from("<II", chunk, 8 + 8 * index) for index in range(count))]


def metadata_strings(chunk: bytes, start: int, size: int) -> list[bytes]:
    cursor, strings = QA_METADATA_TEXT, []
    for _ in range(QA_METADATA_STRINGS):
        end = chunk.index(0, cursor, start + size)
        strings.append(chunk[cursor:end])
        cursor = end + 1
    return strings


def main() -> None:
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    table = load_text_table(TABLE)
    og_jp = (OG_DISC / MEMBER).read_bytes()
    og_zh = (OG_BUILD / MEMBER).read_bytes()
    og_jp_table = read_executable_archive_offsets((OG_DISC / "SLPS_258.87").read_bytes(), OG_SPEC, len(og_jp))
    og_zh_table = read_executable_archive_offsets((OG_BUILD / "SLPS_258.87").read_bytes(), OG_SPEC, len(og_zh))
    source = read_member(members, locks, MEMBER)
    sp_table = sp_offsets(read_member(members, locks, "SLPS_259.20"), SP_TABLE, len(source))

    def og_chunk(archive: bytes, offsets, index: int) -> bytes:
        return decode_production(archive[offsets[index]:offsets[index + 1]]).output

    output = bytearray(source)
    report = {}

    def put(index: int, decoded_new: bytes, stored_old: bytes, result) -> dict:
        slot = sp_table[index + 1] - sp_table[index]
        encoded = reencode_changed_suffix(stored_old[:result.consumed], decoded_new, strategy="rust-maximum",
                                          original_result=result)
        assert decode_production(encoded).output == decoded_new, index
        assert len(encoded) <= slot, f"chunk {index} needs {len(encoded)} > slot {slot}"
        output[sp_table[index]:sp_table[index + 1]] = encoded + bytes(slot - len(encoded))
        return dict(slot=slot, encoded=len(encoded), headroom=slot - len(encoded))

    # chunk 5: tutorial, identical to the main game's Japanese
    stored5 = source[sp_table[5]:sp_table[6]]
    assert decode_production(stored5).output == og_chunk(og_jp, og_jp_table, 5), "tutorial differs from the main game"
    zh5 = og_chunk(og_zh, og_zh_table, 5)
    report["tutorial (chunk 5)"] = dict(put(5, zh5, stored5, decode_production(stored5)), pages="all 10")

    # chunk 6: Strategy Q&A
    stored6 = source[sp_table[6]:sp_table[7]]
    result6 = decode_production(stored6)
    sp6 = bytearray(result6.output)
    jp6, zh6 = og_chunk(og_jp, og_jp_table, 6), og_chunk(og_zh, og_zh_table, 6)
    sp_alloc, jp_alloc, zh_alloc = allocations(bytes(sp6)), allocations(jp6), allocations(zh6)
    assert jp_alloc == zh_alloc and len(sp_alloc) == len(jp_alloc)
    pages_copied, pages_kept = 0, []
    for number in range(1, len(sp_alloc)):
        (s, size), (j, jsize) = sp_alloc[number], jp_alloc[number]
        if size == jsize and bytes(sp6[s:s + size]) == jp6[j:j + jsize]:
            sp6[s:s + size] = zh6[j:j + jsize]
            pages_copied += 1
        else:
            pages_kept.append(number)
    # metadata: prefix stays, strings paired by ordinal, zero padding to the allocation size
    (ms, msize), (js, jsize) = sp_alloc[0], jp_alloc[0]
    sp_meta = metadata_strings(bytes(sp6), ms, msize)
    jp_meta, zh_meta = metadata_strings(jp6, js, jsize), metadata_strings(zh6, js, jsize)
    strings = [zh_meta[k] if sp_meta[k] == jp_meta[k] else sp_meta[k] for k in range(QA_METADATA_STRINGS)]
    blob = b"".join(value + b"\0" for value in strings)
    assert QA_METADATA_TEXT + len(blob) <= ms + msize, "Q&A metadata does not fit its allocation"
    sp6[QA_METADATA_TEXT:ms + msize] = blob + bytes(ms + msize - QA_METADATA_TEXT - len(blob))
    report["strategy Q&A (chunk 6)"] = dict(put(6, bytes(sp6), stored6, result6), pages=len(sp_alloc) - 1,
                                            pages_in_chinese=pages_copied, pages_kept_japanese=pages_kept,
                                            metadata_strings_in_chinese=sum(1 for k in range(QA_METADATA_STRINGS)
                                                                            if sp_meta[k] == jp_meta[k]),
                                            metadata_strings=QA_METADATA_STRINGS)

    # chunk 4: squad-name suggestions
    jp4, zh4 = og_chunk(og_jp, og_jp_table, 4), og_chunk(og_zh, og_zh_table, 4)
    answers = collections.defaultdict(set)
    for index in range(struct.unpack_from("<H", jp4, 0x20)[0]):
        a = SQUAD_BASE + index * SQUAD_STRIDE
        japanese = jp4[a:a + SQUAD_NAME].split(b"\0")[0]
        answers[japanese].add(zh4[a:a + SQUAD_NAME].split(b"\0")[0])
    stored4 = source[sp_table[4]:sp_table[5]]
    result4 = decode_production(stored4)
    sp4 = bytearray(result4.output)
    count = struct.unpack_from("<H", sp4, 0x20)[0]
    written, left = 0, []
    for index in range(count):
        a = SQUAD_BASE + index * SQUAD_STRIDE
        japanese = bytes(sp4[a:a + SQUAD_NAME]).split(b"\0")[0]
        options = answers.get(japanese)
        if not options or len(options) != 1:
            left.append(decode_text(japanese + b"\0", 0, table).text)
            continue
        chinese = next(iter(options))
        sp4[a:a + SQUAD_NAME] = chinese + bytes(SQUAD_NAME - len(chinese))
        written += 1
    report["squad names (chunk 4)"] = dict(put(4, bytes(sp4), stored4, result4), names=count,
                                           in_chinese=written, kept_japanese=left)

    # chunk 0: the Library menu labels, found by their exact Japanese bytes
    jp0, zh0 = og_chunk(og_jp, og_jp_table, 0), og_chunk(og_zh, og_zh_table, 0)
    stored0 = source[sp_table[0]:sp_table[1]]
    result0 = decode_production(stored0)
    sp0 = bytearray(result0.output)
    placed, unplaced = 0, 0
    for a, b in blocks(runs(jp0, zh0)):
        needle = jp0[a:b]
        if len(needle) >= 128 and sp0.count(needle) == 1:
            at = sp0.find(needle)
            sp0[at:at + len(needle)] = zh0[a:b]
            placed += 1
        else:
            unplaced += 1
    report["library menu (chunk 0)"] = dict(put(0, bytes(sp0), stored0, result0),
                                            blocks_placed=placed, blocks_not_found=unplaced)

    # readback: every chunk through the (unchanged) table
    for index in range(len(sp_table) - 1):
        blob = bytes(output[sp_table[index]:sp_table[index + 1]])
        if index not in (0, 4, 5, 6):
            assert blob == source[sp_table[index]:sp_table[index + 1]], index
    assert len(output) == len(source)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "DATA").mkdir(exist_ok=True)
    (OUT / MEMBER).write_bytes(bytes(output))
    summary = dict(answer_key=dict(japanese=str((OG_DISC / MEMBER).relative_to(ROOT)),
                                   chinese=str((OG_BUILD / MEMBER).relative_to(ROOT))),
                   chunks=report, files={MEMBER: sha256(bytes(output))}, original_files={MEMBER: locks[MEMBER]})
    (OUT / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
