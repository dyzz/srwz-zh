"""Bring the main game's finished COMPDATA Chinese into the SP disc's COMPDATA.BN.

COMPDATA is a code/data overlay (main game loaded at 0x6D6800, SP at 0x764F80)
whose tables all moved in SP and two record strides changed, so nothing can be
patched by offset. Instead the main game's own build is used as the answer key:

  * the Japanese main-game COMPDATA and the built Chinese one are compared
    pointer slot by pointer slot (every word that points into the overlay at a
    string): the Japanese string at a slot and the Chinese bytes the main build
    left at that same slot form one pair. The Chinese bytes are copied as they
    are, so every production decision (codebook, width tags, relocations) comes
    along exactly.
  * pilot names are inline fields (display/family/given at +2/+23/+46); the
    main game's records are compared field by field the same way.

In SP every string a pointer reaches, and every pilot name field, whose
Japanese has exactly one Chinese answer in the main game is rewritten in place:
inside its own bytes (plus the alignment zeros after it that no other string
starts in), terminated, the rest cleared. Nothing moves and no pointer changes.
A Japanese string the main game translates two ways is usually two strings
(マジンガーＺ as a unit name and as a work title); when SP holds as many copies,
they pair up in address order. Otherwise the answer given in the same table
(unit names, weapons ...) settles it when unique; failing both, it is reported
and left as it is, like a Chinese answer that does not fit.

The overlay is then re-encoded with the project codec. Its decoded size is
fixed, and the compressed file keeps its size on the disc (the stream is padded
with zeros after its end, which the loader never reads), so it must not grow.

Outputs (work/build/special-disc/components/compdata/):
  DATA/COMPDATA.BN   the overlay with the reusable text in Chinese
  report.json        pairs, coverage, what was left and why, codec sizes
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
from srwz.text import SrwzTextError, decode_text, load_text_table  # noqa: E402

ISO = ROOT / "rom/Super Robot Taisen Z - Special Disc [J].iso"
LOCKS = ROOT / "config/products/special-disc/disc-inventory.json"
TABLE = ROOT / "vendor/upstream-python/project/tbl_all.json"
OG_JAPANESE = ROOT / "work/disc/DATA/COMPDATA.BN"
# the main game's finished Original build (2026-09-17, v0.4.2 release chain)
OG_CHINESE = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                     "/project/work/build/zh-release-full-story/components/DATA/COMPDATA.BN")
OUT = ROOT / "work/build/special-disc/components/compdata"
MEMBER = "DATA/COMPDATA.BN"
OG_BASE, SD_BASE = 0x6D6800, 0x764F80
# pilot records: (start, stride, count); name fields (offset, capacity) are the same in both
OG_PILOTS, SD_PILOTS = (0x2160, 176, 933), (0x2B50, 178, 969)
PILOT_FIELDS = (("display", 2, 21), ("family", 23, 23), ("given", 46, 23))
# Where each table starts, main game -> SP (reports/battle.md §2). A string the main game
# translates two ways is settled by the answer given in the same table.
REGIONS = (
    ("battle lines", 0x0904, 0x1204), ("parts", 0x18FC, 0x22EC), ("pilots", 0x2160, 0x2B50),
    ("weapons", 0x328A0, 0x35A80), ("special abilities", 0x4C8E0, 0x54980), ("units", 0x4CAE4, 0x54B94),
    ("stage names", 0x5E150, 0x68630), ("search/leadership", 0x60790, 0x69260),
    ("abilities 2/buttons", 0x61120, 0x69D30),
)


def region_of(offset: int, edition: int) -> str:
    """edition 1 = main game, 2 = SP; strings before the first table count as 'head'."""
    name = "head"
    for label, *starts in REGIONS:
        if offset >= starts[edition - 1]:
            name = label
    return name


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(members, locks, name: str) -> bytes:
    m = members[name]
    with ISO.open("rb") as f:
        f.seek(m.extent_lba * 2048)
        data = f.read(m.size)
    assert sha256(data) == locks[name], f"{name} lock drift"
    return data


def text_at(data: bytes, offset: int, table):
    """A NUL-terminated, fully known string at offset with at least one Japanese character."""
    try:
        decoded = decode_text(data, offset, table)
    except SrwzTextError:
        return None
    if decoded.terminator != "nul" or not decoded.text or decoded.unknown_code_count:
        return None
    if not any(ord(ch) >= 0x3000 for ch in decoded.text):
        return None
    return decoded


def pointer_targets(data: bytes, base: int):
    for offset in range(0, len(data) - 3, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if base <= word < base + len(data):
            yield offset, word - base


def field_text(record: bytes, offset: int, capacity: int) -> bytes:
    raw = record[offset:offset + capacity]
    end = raw.find(b"\0")
    return raw if end < 0 else raw[:end]


def main() -> None:
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    table = load_text_table(TABLE)
    og_japanese = decode_production(OG_JAPANESE.read_bytes()).output
    og_chinese = decode_production(OG_CHINESE.read_bytes()).output
    assert len(og_japanese) == len(og_chinese)
    sd_stored = read_member(members, locks, MEMBER)
    sd_result = decode_production(sd_stored)
    sd = bytearray(sd_result.output)

    # 1. the answer key: Japanese string -> Chinese bytes, slot by slot
    answers: dict[str, set[bytes]] = collections.defaultdict(set)
    by_region: dict[tuple[str, str], set[bytes]] = collections.defaultdict(set)
    by_string: dict[str, dict[int, set[bytes]]] = collections.defaultdict(lambda: collections.defaultdict(set))
    slots = 0
    for offset, target in pointer_targets(og_japanese, OG_BASE):
        japanese = text_at(og_japanese, target, table)
        if japanese is None:
            continue
        word = struct.unpack_from("<I", og_chinese, offset)[0]
        if not OG_BASE <= word < OG_BASE + len(og_chinese):
            continue  # the main build changed this word: not a string pointer there
        start = word - OG_BASE
        chinese = og_chinese[start:og_chinese.index(0, start)]
        answers[japanese.text].add(chinese)
        by_region[(region_of(offset, 1), japanese.text)].add(chinese)
        by_string[japanese.text][target].add(chinese)
        slots += 1
    names: dict[bytes, set[bytes]] = collections.defaultdict(set)
    start, stride, count = OG_PILOTS
    for index in range(count):
        a = start + index * stride
        for _name, offset, capacity in PILOT_FIELDS:
            japanese = field_text(og_japanese[a:a + stride], offset, capacity)
            if japanese:
                names[japanese].add(field_text(og_chinese[a:a + stride], offset, capacity))

    # 2. SP strings reached by pointers
    targets, references = {}, collections.Counter()
    regions_of_target: dict[int, set[str]] = collections.defaultdict(set)
    for slot, target in pointer_targets(bytes(sd), SD_BASE):
        references[target] += 1
        regions_of_target[target].add(region_of(slot, 2))
        if target not in targets:
            decoded = text_at(bytes(sd), target, table)
            if decoded is not None:
                targets[target] = decoded
    starts = set(targets)
    # The same Japanese can be several strings (マジンガーＺ as a unit name and as a work title).
    # When SP holds as many copies as the main game, they pair up in address order.
    sp_copies: dict[str, list[int]] = collections.defaultdict(list)
    for target in sorted(targets):
        sp_copies[targets[target].text].append(target)
    by_copy: dict[int, bytes] = {}
    for text, copies in sp_copies.items():
        og_copies = by_string.get(text, {})
        if len(answers.get(text, ())) > 1 and len(og_copies) == len(copies) \
                and all(len(v) == 1 for v in og_copies.values()):
            for sp_target, og_target in zip(copies, sorted(og_copies)):
                by_copy[sp_target] = next(iter(og_copies[og_target]))
    written, left = [], collections.Counter()
    samples = collections.defaultdict(list)
    for target in sorted(targets):
        decoded = targets[target]
        options = answers.get(decoded.text)
        if not options:
            left["no answer in the main game"] += 1
            continue
        if len(decoded.text) < 2 and references[target] < 2:
            # one character reached by one word could be a data run that decodes as text
            left["single character, single reference"] += 1
            continue
        if len(options) > 1 and target in by_copy:
            options = {by_copy[target]}
            left["settled by copy order"] += 1
        if len(options) > 1:
            local = set().union(*(by_region.get((r, decoded.text), set()) for r in regions_of_target[target]))
            if len(local) != 1:
                left["translated two ways in the main game"] += 1
                samples["ambiguous"].append(decoded.text)
                continue
            options = local
            left["settled by table"] += 1
        chinese = next(iter(options))
        end = target + decoded.consumed  # the NUL included
        while end < len(sd) and end % 4 and sd[end] == 0 and end not in starts:
            end += 1
        if len(chinese) + 1 > end - target:
            left["does not fit"] += 1
            samples["does not fit"].append(decoded.text)
            continue
        if chinese == bytes(sd[target:target + len(chinese)]) and sd[target + len(chinese)] == 0:
            left["already the same bytes"] += 1
            continue
        sd[target:end] = chinese + bytes(end - target - len(chinese))
        written.append(dict(offset=hex(target), japanese=decoded.text, chinese=chinese.hex()))

    # 3. SP pilot name fields
    start, stride, count = SD_PILOTS
    fields_written = 0
    for index in range(count):
        a = start + index * stride
        for _name, offset, capacity in PILOT_FIELDS:
            japanese = field_text(bytes(sd[a:a + stride]), offset, capacity)
            options = names.get(japanese)
            if not japanese or not options:
                continue
            if len(options) > 1:
                left["pilot name translated two ways"] += 1
                continue
            chinese = next(iter(options))
            if len(chinese) > capacity or chinese == japanese:
                continue
            sd[a + offset:a + offset + capacity] = chinese + bytes(capacity - len(chinese))
            fields_written += 1

    # 4. readback, then the codec
    for row in written:
        target = int(row["offset"], 16)
        chinese = bytes.fromhex(row["chinese"])
        assert bytes(sd[target:target + len(chinese) + 1]) == chinese + b"\0", row
    assert len(sd) == len(sd_result.output)
    encoded = reencode_changed_suffix(sd_stored, bytes(sd), strategy="rust-maximum", original_result=sd_result)
    assert decode_production(encoded).output == bytes(sd), "COMPDATA does not read back"
    assert len(encoded) <= len(sd_stored), f"COMPDATA grew: {len(encoded)} > {len(sd_stored)}"
    stored = encoded + bytes(len(sd_stored) - len(encoded))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "DATA").mkdir(exist_ok=True)
    (OUT / MEMBER).write_bytes(stored)
    report = dict(
        answer_key=dict(japanese=str(OG_JAPANESE.relative_to(ROOT)), japanese_sha256=sha256(OG_JAPANESE.read_bytes()),
                        chinese=str(OG_CHINESE.relative_to(ROOT)), chinese_sha256=sha256(OG_CHINESE.read_bytes()),
                        pointer_slots=slots, japanese_strings=len(answers),
                        translated_two_ways=sorted(k for k, v in answers.items() if len(v) > 1),
                        pilot_names=len(names)),
        strings=dict(reached_by_pointers=len(targets), rewritten=len(written), pilot_fields_rewritten=fields_written,
                     left=dict(left)),
        left_samples={k: v[:20] for k, v in samples.items()},
        codec=dict(original=len(sd_stored), encoded=len(encoded), padding=len(sd_stored) - len(encoded),
                   decoded=len(sd)),
        files={MEMBER: sha256(stored)}, original_files={MEMBER: locks[MEMBER]},
    )
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("strings", "codec")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
