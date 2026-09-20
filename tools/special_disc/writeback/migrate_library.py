"""Bring the main game's finished encyclopedia Chinese into the SP disc's MTVZKN archives.

Every encyclopedia entry is one compressed ZKAN document: tagged fields, text
fields plain length-delimited game text. The project's own parser reads all
795 SP documents. The main game's build is the answer key: its Japanese and
built Chinese archives are compared document by document and field by field,
so for each field kind (ROBO/CHAR/KYWD and tag) a Japanese text maps to the
Chinese bytes the main build wrote, already laid out to that field's width.

An SP field whose Japanese has exactly one Chinese answer for its field kind
takes those bytes; every other field (binary fields, SP-only text, and text
the main game answers two ways) keeps its original bytes. Changed documents are
re-encoded with the project codec, the archive is rebuilt with 16-byte aligned
chunks, and the executable's chunk table for that archive is rewritten. The
archive keeps its size on the disc: the space it saves stays at the end of the
last chunk, which the loader never reads past the compressed stream.

Outputs (work/build/special-disc/components/library/):
  DATA/MTVZKN{RT,PT,KW}.BIN   rebuilt archives
  SLPS_259.20                 executable with the three chunk tables rewritten
  report.json                 answers, coverage per archive, table changes
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
from srwz.library import (  # noqa: E402
    ZKAN_TEXT_TAGS,
    ZKN_WRAPPER_SIZE,
    parse_zkn_decoded_chunk,
    zkan_escape_transform,
)

from special_disc.source import SOURCE_ISO as ISO  # noqa: E402
from special_disc.source import DISC_INVENTORY as LOCKS  # noqa: E402
OG_DISC = ROOT / "work/disc"
OG_BUILD = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                   "/project/work/build/zh-release-full-story/components")
BASE = ROOT / "work/build/special-disc/components/text"  # executable to build on
OUT = ROOT / "work/build/special-disc/components/library"
EXE = "SLPS_259.20"
ARCHIVES = {  # member: (main-game table start, end inclusive), SP table start
    "DATA/MTVZKNRT.BIN": ((0x32B390, 0x32B897), 0x387160),
    "DATA/MTVZKNPT.BIN": ((0x32A810, 0x32AE7B), 0x3865B0),
    "DATA/MTVZKNKW.BIN": ((0x32B980, 0x32BA4F), 0x387770),
}


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


def raw_fields(decoded: bytes) -> tuple[str, list[tuple[str, bytes]]]:
    """(kind, [(tag, field bytes)]) of one decoded ZKN chunk, text not interpreted."""
    wrapper = struct.unpack_from("<8I", decoded, 0)
    size = wrapper[3]
    payload = zkan_escape_transform(decoded[ZKN_WRAPPER_SIZE:ZKN_WRAPPER_SIZE + size])
    assert payload[:4] == b"ZKAN", "not a ZKAN document"
    kind = payload[4:8].decode("ascii")
    data_size = struct.unpack_from("<I", payload, 28)[0]
    cursor, end, fields = 0x20, 0x20 + data_size, []
    while cursor < end:
        tag = payload[cursor:cursor + 4].decode("ascii")
        length = struct.unpack_from("<I", payload, cursor + 4)[0]
        fields.append((tag, payload[cursor + 8:cursor + 8 + length]))
        cursor += 8 + length
    return kind, fields


def serialize(kind: str, version: int, fields: list[tuple[str, bytes]], alignment: int = 16) -> bytes:
    """ZKAN document -> decoded chunk (mirrors library.build_runtime_zkn_decoded_chunk)."""
    records = b"".join(tag.encode("ascii") + struct.pack("<I", len(data)) + data for tag, data in fields)
    payload = (b"ZKAN" + kind.encode("ascii") + struct.pack("<II", version, 0x0C)
               + b"DSIZ" + struct.pack("<I", len(records) + 8) + b"DATA" + struct.pack("<I", len(records))
               + records)
    payload += bytes(((len(payload) + alignment - 1) & -alignment) - len(payload))
    wrapper = struct.pack("<8I", 1, ZKN_WRAPPER_SIZE, 0, len(payload), len(payload), 0, 0, 0)
    return wrapper + zkan_escape_transform(payload)


def chunks_of(data: bytes, offsets) -> list[bytes]:
    return [data[a:b] for a, b in zip(offsets, offsets[1:])]


def main() -> None:
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    base_report = json.loads((BASE / "report.json").read_text())
    exe = bytearray((BASE / EXE).read_bytes())
    assert sha256(bytes(exe)) == base_report["files"][EXE], "text component drift"
    og_exe = (OG_DISC / "SLPS_258.87").read_bytes()
    og_built_exe = (OG_BUILD / "SLPS_258.87").read_bytes()

    report, outputs = {}, {}
    for member, ((table_start, table_end), sp_table) in ARCHIVES.items():
        spec = ExecutableOffsetSpec(name=member, member=member, table_start=table_start, table_end=table_end)
        og_jp = (OG_DISC / member).read_bytes()
        og_zh = (OG_BUILD / member).read_bytes()
        jp_chunks = chunks_of(og_jp, read_executable_archive_offsets(og_exe, spec, len(og_jp)))
        zh_chunks = chunks_of(og_zh, read_executable_archive_offsets(og_built_exe, spec, len(og_zh)))
        assert len(jp_chunks) == len(zh_chunks), member

        # 1. the answer key, per field kind
        answers: dict[tuple[str, str, str], set[bytes]] = collections.defaultdict(set)
        for jp, zh in zip(jp_chunks, zh_chunks):
            document = parse_zkn_decoded_chunk(decode_production(jp).output)
            zh_kind, zh_fields = raw_fields(decode_production(zh).output)
            zh_by_tag = dict(zh_fields)
            assert zh_kind == document.kind
            for field in document.fields:
                if field.text is not None and field.tag in zh_by_tag:
                    answers[(document.kind, field.tag, field.text)].add(zh_by_tag[field.tag])

        # 2. SP documents
        source = read_member(members, locks, member)
        table = sp_offsets(bytes(exe), sp_table, len(source))
        sp_chunks = chunks_of(source, table)
        stored_chunks, counts = [], collections.Counter()
        for index, stored in enumerate(sp_chunks):
            decoded = decode_production(stored)
            document = parse_zkn_decoded_chunk(decoded.output)
            kind, fields = raw_fields(decoded.output)
            new_fields, changed = [], False
            for (tag, data), field in zip(fields, document.fields):
                assert tag == field.tag
                if field.text is None or tag not in ZKAN_TEXT_TAGS:
                    new_fields.append((tag, data))
                    continue
                options = answers.get((kind, tag, field.text))
                if not options:
                    counts["fields without an answer"] += 1
                    new_fields.append((tag, data))
                elif len(options) > 1:
                    counts["fields answered two ways"] += 1
                    new_fields.append((tag, data))
                else:
                    chinese = next(iter(options))
                    counts["fields in Chinese"] += 1
                    changed |= chinese != data
                    new_fields.append((tag, chinese))
            if not changed:
                stored_chunks.append(stored[:decoded.consumed])
                counts["documents unchanged"] += 1
                continue
            rebuilt = serialize(kind, document.version, new_fields)
            encoded = reencode_changed_suffix(stored[:decoded.consumed], rebuilt, strategy="rust-fit",
                                              original_result=decoded)
            assert decode_production(encoded).output == rebuilt, (member, index)
            stored_chunks.append(encoded)
            counts["documents rewritten"] += 1

        # 3. the archive and its table
        output, offsets = bytearray(), []
        for blob in stored_chunks:
            offsets.append(len(output))
            output += blob + bytes((-len(blob)) % 16)
        assert len(output) <= len(source), f"{member} grew: {len(output)} > {len(source)}"
        output += bytes(len(source) - len(output))
        for index, value in enumerate(offsets):
            struct.pack_into("<I", exe, sp_table + 4 * index, value)
        check = sp_offsets(bytes(exe), sp_table, len(output))
        assert check[:-1] == offsets and check[-1] == len(source)
        for index, blob in enumerate(chunks_of(bytes(output), check)):
            got = decode_production(blob).output
            want = decode_production(stored_chunks[index]).output
            assert got == want, (member, index)
        outputs[member] = bytes(output)
        report[member] = dict(documents=len(sp_chunks), table=hex(sp_table), size=len(source),
                              used=sum(len(b) + (-len(b)) % 16 for b in stored_chunks),
                              answers=len(answers),
                              answered_two_ways=sum(1 for v in answers.values() if len(v) > 1),
                              **counts)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "DATA").mkdir(exist_ok=True)
    for member, data in outputs.items():
        (OUT / member).write_bytes(data)
    (OUT / EXE).write_bytes(bytes(exe))
    files = {member: sha256(data) for member, data in outputs.items()}
    files[EXE] = sha256(bytes(exe))
    summary = dict(
        answer_key=dict(japanese=str(OG_DISC.relative_to(ROOT)), chinese=str(OG_BUILD.relative_to(ROOT))),
        archives=report, files=files,
        base_files={EXE: base_report["files"][EXE]},
        original_files={**{member: locks[member] for member in outputs}, EXE: locks[EXE]},
    )
    (OUT / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
