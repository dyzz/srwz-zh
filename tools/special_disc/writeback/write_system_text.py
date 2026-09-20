"""Write the Special Disc system text (modules 04/05) into the executable, COMPDATA and STAGE.

The Chinese comes from corpus/zh/special-disc/system-text.json; every entry is
addressed by id:

  sd/exe/<offset>        a NUL-terminated string in SLPS_259.20
  sd/compdata/<offset>   a string reached by pointers in the decoded COMPDATA
  sd/exe/wallpaper-names one formula, written at every listed offset
  sd/ticker/<hash>       the intermission ticker text, in every STAGE slot holding it

Each string is written inside its own bytes plus the zero alignment after it up
to the next 8-byte boundary, provided no other known string starts there;
nothing moves. A COMPDATA string that still does not fit is pointed at the same
Chinese ending another written string (tail sharing, as the compiler already
does): its pointer words move, its own bytes stay. The preimage of every string
is checked before it is overwritten, every write reads back through the Chinese
runtime table, and changed archives are re-encoded inside their slots.

Built on the latest component of each member (build_preview.py stacks them):
  SLPS_259.20       work/build/special-disc/components/exe-patches
  DATA/COMPDATA.BN  work/build/special-disc/components/compdata
  DATA/STAGE.BIN    work/build/special-disc/components/flow

Outputs (work/build/special-disc/components/system-text/): the three members and report.json.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srwz.codec import decode_production, reencode_changed_suffix  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.text import (  # noqa: E402
    SrwzTextError,
    decode_text,
    encode_text,
    normalize_original_fullwidth_ascii,
    two_byte_visible_spaces,
)
import migrate_compdata as mc  # noqa: E402
import migrate_slps_text as mst  # noqa: E402
from special_disc.writeback.exe_data_guard import require_text_range  # noqa: E402

CORPUS = ROOT / "corpus/zh/special-disc/system-text.json"
FRAME_CORPUS = ROOT / "corpus/zh/special-disc/frame-text.json"
LOCKS = ROOT / "config/products/special-disc/disc-inventory.json"
OUT = ROOT / "work/build/special-disc/components/system-text"
EXE, COMPDATA, STAGE, HB = "SLPS_259.20", "DATA/COMPDATA.BN", "DATA/STAGE.BIN", "HEDBDY/HB.BIN"
BASES = {
    EXE: ROOT / "work/build/special-disc/components/exe-patches",
    COMPDATA: ROOT / "work/build/special-disc/components/compdata",
    STAGE: ROOT / "work/build/special-disc/components/flow",
}
SD_STAGE_BASE, HB_TABLE, TICKER_SLOT = 0x8045F0, 0x5170, 140
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def base(name: str) -> bytes:
    component = BASES[name]
    report = json.loads((component / "report.json").read_text())
    data = (component / name).read_bytes()
    assert sha256(data) == report["files"][name], f"{component.name}: {name} drift"
    return data


def capacity(data, starts: list[int], offset: int, span: int) -> int:
    """The string's bytes plus the zero alignment after it, stopping at the next known string."""
    end = offset + span
    limit = (end + 7) & ~7
    following = [s for s in starts if s > offset]
    if following:
        limit = min(limit, min(following))
    if limit > end and not any(data[end:limit]):
        return limit - offset
    return span


class Writer:
    def __init__(self, table, overrides, readback):
        self.table, self.overrides, self.readback = table, overrides, readback
        self.log = collections.Counter()
        self.skipped = []

    def encode(self, text: str) -> bytes:
        # Visible word separators must be stored as the stock 0x8140 glyph: these
        # renderers consume text as two-byte codes, so a raw one-byte 0x20 shifts
        # the pairing of every glyph that follows it (see srwz.text).
        return encode_text(two_byte_visible_spaces(normalize_original_fullwidth_ascii(text)),
                           self.table, overrides=self.overrides, terminate=True)

    def put(self, data: bytearray, offset: int, source: str, chinese: str, starts, label: str) -> bytes | None:
        """Write one string in place; returns its bytes, or None when it does not fit."""
        if label.startswith("sd/exe/"):
            require_text_range(offset, 1)
        decoded = decode_text(bytes(data), offset, self.table)
        assert decoded.text == source, f"{label}: preimage drift at 0x{offset:X}: {decoded.text!r}"
        payload = self.encode(chinese)
        room = capacity(data, starts, offset, decoded.consumed)
        if label.startswith("sd/exe/"):
            require_text_range(offset, room)
        if len(payload) > room:
            return None
        data[offset:offset + room] = payload + bytes(room - len(payload))
        shown = decode_text(bytes(data), offset, self.readback)
        assert shown.text == two_byte_visible_spaces(
            normalize_original_fullwidth_ascii(chinese)
        ) and shown.terminator == "nul", (label, shown.text)
        self.log["written"] += 1
        return payload


def tickers(data: bytes, table) -> list[tuple[int, str]]:
    """Intermission ticker slots (the export's rule): six 0xFF bytes and a word before a 140-byte text slot."""
    found = []
    for offset in range(12, len(data), 4):
        if offset + TICKER_SLOT > len(data) or data[offset - 10:offset - 4] != b"\xff" * 6:
            continue
        try:
            text = decode_text(data, offset, table, end=offset + TICKER_SLOT)
        except SrwzTextError:
            continue
        if (text.terminator != "nul" or text.unknown_code_count or not re.search(r"[ぁ-ヿ㐀-鿿]", text.text)
                or any(data[text.end:offset + TICKER_SLOT])
                or (offset + TICKER_SLOT < len(data) and data[offset + TICKER_SLOT] == 0)):
            continue
        found.append((offset, text.text))
    return found


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proposal', type=Path)
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args(); OUT = args.output
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    table, _menu, story, readback = mst.encoding_tables(args.proposal)
    writer = Writer(table, story, readback)
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    entries = list(corpus["entries"])

    # The frame-text corpus addresses its strings by `locations` rather than by
    # id; the ones that land in the executable or COMPDATA are the same kind of
    # in-place string this script already writes, so take them here instead of
    # building a second writer. One entry may name several places (the same
    # sentence stored more than once), and each becomes its own record.
    frame = json.loads(FRAME_CORPUS.read_text(encoding="utf-8"))
    known = {e["id"] for e in entries}
    frame_taken = 0
    for e in frame["entries"]:
        for location in e["locations"]:
            if not location.startswith(("sd/exe/", "sd/compdata/")) or location in known:
                continue
            entries.append({**e, "id": location, "locations": [location]})
            known.add(location)
            frame_taken += 1

    by_kind = collections.defaultdict(list)
    for e in entries:
        by_kind[e["id"].split("/")[1]].append(e)

    # ---- executable
    exe_base = base(EXE)
    exe = bytearray(exe_base)
    inventory = json.loads(mst.SD_STRINGS.read_text())["SD"]
    exe_starts = sorted({r["off"] for group in ("referenced", "unreferenced") for r in inventory[group]})
    exe_left = []
    for e in by_kind["exe"]:
        if e["id"] == "sd/exe/wallpaper-names":
            for offset in e["locations"]:
                source = decode_text(bytes(exe), offset, table).text
                number = int(source.translate(FULLWIDTH_DIGITS)[-3:])
                if writer.put(exe, offset, source, e["translation"].format(n=number), exe_starts, e["id"]) is None:
                    exe_left.append(dict(id=e["id"], offset=hex(offset), reason="does not fit"))
            continue
        offset = int(e["id"].split("/")[-1], 16)
        if writer.put(exe, offset, e["source_text"], e["translation"], exe_starts, e["id"]) is None:
            exe_left.append(dict(id=e["id"], reason="does not fit"))

    # ---- COMPDATA
    cd_stored = base(COMPDATA)
    cd_result = decode_production(cd_stored)
    cd = bytearray(cd_result.output)
    pointers = collections.defaultdict(list)
    for slot, target in mc.pointer_targets(bytes(cd), mc.SD_BASE):
        pointers[target].append(slot)
    cd_starts = sorted(pointers)
    written_cd: dict[int, bytes] = {}
    overflow = []
    for e in by_kind["compdata"]:
        offset = int(e["id"].split("/")[-1], 16)
        payload = writer.put(cd, offset, e["source_text"], e["translation"], cd_starts, e["id"])
        if payload is None:
            overflow.append((offset, e))
        else:
            written_cd[offset] = payload
    shared, cd_left = [], []
    for offset, e in overflow:
        want = writer.encode(e["translation"])  # ends with its NUL
        host = next(((o, p) for o, p in sorted(written_cd.items()) if p.endswith(want)), None)
        if host is None:
            cd_left.append(dict(id=e["id"], reason="does not fit, no written string ends with it"))
            continue
        target = host[0] + len(host[1]) - len(want)
        for slot in pointers[offset]:
            struct.pack_into("<I", cd, slot, mc.SD_BASE + target)
        shown = decode_text(bytes(cd), target, readback)
        assert shown.text == two_byte_visible_spaces(
            normalize_original_fullwidth_ascii(e["translation"])
        ), e["id"]
        shared.append(dict(id=e["id"], pointer_slots=[hex(s) for s in pointers[offset]], now=hex(target),
                           ending_of=hex(host[0])))
        writer.log["tail shared"] += 1
    cd_encoded = reencode_changed_suffix(cd_stored[:cd_result.consumed], bytes(cd), strategy="rust-maximum",
                                         original_result=cd_result)
    assert decode_production(cd_encoded).output == bytes(cd), "COMPDATA does not read back"
    assert len(cd_encoded) <= len(cd_stored), f"COMPDATA grew: {len(cd_encoded)} > {len(cd_stored)}"
    cd_out = cd_encoded + bytes(len(cd_stored) - len(cd_encoded))

    # ---- STAGE: intermission tickers
    stage_base = base(STAGE)
    stage = bytearray(stage_base)
    members = member_map(scan_iso9660(mc.ISO))
    hb = mc.read_member(members, locks, HB)
    offsets, pos = [], HB_TABLE
    while True:
        value = struct.unpack_from("<I", hb, pos)[0]
        offsets.append(value)
        pos += 4
        if value == len(stage):
            break
    ticker_zh = {e["source_text"]: e["translation"] for e in by_kind["ticker"]}
    stage_report, ticker_left = [], []
    for index in range(1, len(offsets) - 1):
        a, b = offsets[index], offsets[index + 1]
        result = decode_production(bytes(stage[a:b]))
        data = bytearray(result.output)
        slots = [(o, t) for o, t in tickers(bytes(data), table) if t in ticker_zh]
        if not slots:
            continue
        for offset, text in slots:
            payload = writer.encode(ticker_zh[text])
            assert len(payload) <= TICKER_SLOT, text
            data[offset:offset + TICKER_SLOT] = payload + bytes(TICKER_SLOT - len(payload))
            assert decode_text(bytes(data), offset, readback).text == two_byte_visible_spaces(
                normalize_original_fullwidth_ascii(ticker_zh[text])
            )
        encoded = reencode_changed_suffix(bytes(stage[a:a + result.consumed]), bytes(data), strategy="rust-maximum",
                                          original_result=result)
        assert decode_production(encoded).output == bytes(data), index
        if len(encoded) > b - a:
            ticker_left.append(dict(chunk=index, reason=f"chunk needs {len(encoded)} > slot {b - a}"))
            continue
        stage[a:b] = encoded + bytes(b - a - len(encoded))
        writer.log["ticker slots"] += len(slots)
        stage_report.append(dict(chunk=index, slots=len(slots), slot=b - a, encoded=len(encoded)))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "DATA").mkdir(exist_ok=True)
    outputs = {EXE: bytes(exe), COMPDATA: cd_out, STAGE: bytes(stage)}
    for name, data in outputs.items():
        (OUT / name).write_bytes(data)
    report = dict(
        proposal_sha256=sha256(args.proposal.read_bytes()) if args.proposal else None,
        corpus=dict(path=str(CORPUS.relative_to(ROOT)), sha256=sha256(CORPUS.read_bytes()), entries=len(entries)),
        frame_corpus=dict(path=str(FRAME_CORPUS.relative_to(ROOT)),
                          sha256=sha256(FRAME_CORPUS.read_bytes()), taken=frame_taken),
        written=dict(writer.log),
        left=dict(executable=exe_left, compdata=cd_left, tickers=ticker_left),
        tail_shared=shared,
        compdata_codec=dict(original=len(cd_stored), encoded=len(cd_encoded), padding=len(cd_stored) - len(cd_encoded)),
        stage_chunks=stage_report,
        files={name: sha256(data) for name, data in outputs.items()},
        base_files={EXE: sha256(exe_base), COMPDATA: sha256(cd_stored), STAGE: sha256(stage_base)},
        original_files={name: locks[name] for name in outputs},
    )
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("written", "left", "tail_shared", "compdata_codec", "stage_chunks")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
