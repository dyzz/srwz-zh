"""Bring the main game's finished Chinese names into SP's demo and map-name files.

  BTL/OP.BIN, BTL/ST.BIN   title-idle and Battle Theatre demos. Speaker names sit
                           in 20-byte cells on a 16-byte grid (+0x0C), plain
                           CP932 and zero-padded; SP merges the main game's three
                           OP files into one and adds ST, so cells are found with
                           the main game's own cell test run over the whole file.
  MAP/MAPNAME.BIN          map names in 256-byte slots (200 in SP, 195 main game).

A name takes the Chinese bytes the main build wrote for the same Japanese in
the same kind of file (its OP cells, its MAPNAME slots); a name the main files
do not contain takes the finished corpus translation (story speakers and the
main game's display names; map names), encoded with the main game's stored-text
codebook. Every other byte stays; a name that does not fit is reported.

Outputs (work/build/special-disc/components/names/): the three files and report.json.
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srwz import auto_demo  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.text import decode_text, encode_text  # noqa: E402
from migrate_slps_text import encoding_tables  # noqa: E402

from special_disc.source import SOURCE_ISO as ISO  # noqa: E402
from special_disc.source import DISC_INVENTORY as LOCKS  # noqa: E402
OG_DISC = ROOT / "work/disc"
OG_BUILD = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                   "/project/work/build/zh-release-full-story/components")
CORPUS = ROOT / "corpus/zh"
OUT = ROOT / "work/build/special-disc/components/names"
CELL = auto_demo.NAME_FIELD_CAPACITY
MAP_SLOT = 256


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(members, locks, name: str) -> bytes:
    m = members[name]
    with ISO.open("rb") as f:
        f.seek(m.extent_lba * 2048)
        data = f.read(m.size)
    assert sha256(data) == locks[name], f"{name} lock drift"
    return data


def name_cells(data: bytes, start: int = 0):
    """The main game's cell test (auto_demo.discover_auto_demo_name_slots) over a whole file."""
    for offset in range(start + 0x0C, len(data) - CELL + 1, 0x10):
        field = data[offset:offset + CELL]
        end = field.find(b"\0")
        if end <= 0 or any(field[end:]):
            continue
        try:
            text = field[:end].decode("cp932")
        except UnicodeDecodeError:
            continue
        if auto_demo._contains_japanese_name_character(text):
            yield offset, text


def corpus_names() -> dict[str, str]:
    speakers = json.loads((CORPUS / "story-speakers.json").read_text(encoding="utf-8"))
    by_hash = {}
    for entry in speakers["entries"]:
        if entry.get("translation"):
            by_hash.setdefault(entry["source_text_sha256"], entry["translation"])
    remaining = json.loads((CORPUS / "menu/remaining-ui.json").read_text(encoding="utf-8"))
    for source, translation in remaining.get("display_names_by_source_text", {}).items():
        by_hash.setdefault(hashlib.sha256(source.encode("utf-8")).hexdigest(), translation)
    return by_hash


def main() -> None:
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    table, _menu, story, readback = encoding_tables()
    corpus = corpus_names()
    report, outputs = {}, {}

    # demo name cells: the answer key from the main game's three OP files
    answers: dict[str, set[bytes]] = collections.defaultdict(set)
    for index in range(3):
        japanese = (OG_DISC / f"BTL/OP{index}.BIN").read_bytes()
        seg = (OG_DISC / f"BTL/OP{index}.SEG").read_bytes()
        chinese = (OG_BUILD / f"BTL/OP{index}.BIN").read_bytes()
        for slot in auto_demo.discover_auto_demo_name_slots(japanese, seg):
            answers[slot.source_text].add(chinese[slot.offset:slot.offset + CELL].split(b"\0")[0])
    for member in ("BTL/OP.BIN", "BTL/ST.BIN"):
        source = read_member(members, locks, member)
        output = bytearray(source)
        counts, missing = collections.Counter(), collections.Counter()
        for offset, text in name_cells(source):
            options = answers.get(text)
            if options and len(options) == 1:
                chinese, route = next(iter(options)), "main-game demo"
            else:
                translation = corpus.get(hashlib.sha256(text.encode("utf-8")).hexdigest())
                if not translation:
                    missing[text] += 1
                    continue
                chinese, route = encode_text(translation.replace(" ", "　"), table, overrides=story), "corpus"
            if len(chinese) + 1 > CELL:
                missing[f"{text} (does not fit)"] += 1
                continue
            output[offset:offset + CELL] = chinese + bytes(CELL - len(chinese))
            assert decode_text(bytes(output), offset, readback).terminator == "nul"
            counts[route] += 1
        outputs[member] = bytes(output)
        report[member] = dict(cells=sum(counts.values()) + sum(missing.values()), **counts,
                              without_translation=dict(missing.most_common(20)))

    # map names: 256-byte slots
    japanese = (OG_DISC / "MAP/MAPNAME.BIN").read_bytes()
    chinese = (OG_BUILD / "MAP/MAPNAME.BIN").read_bytes()
    map_answers: dict[bytes, set[bytes]] = collections.defaultdict(set)
    for a in range(0, len(japanese), MAP_SLOT):
        name = japanese[a:a + MAP_SLOT].split(b"\0")[0]
        if name:
            map_answers[name].add(chinese[a:a + MAP_SLOT].split(b"\0")[0])
    names = json.loads((CORPUS / "menu/ui-name-tables.json").read_text(encoding="utf-8"))["map_names"]
    map_corpus = {row["source"]: row["translation"] for row in names if row.get("translation")}
    source = read_member(members, locks, "MAP/MAPNAME.BIN")
    output = bytearray(source)
    counts, missing = collections.Counter(), []
    for a in range(0, len(source), MAP_SLOT):
        raw = source[a:a + MAP_SLOT].split(b"\0")[0]
        if not raw:
            continue
        options = map_answers.get(raw)
        if options and len(options) == 1:
            new, route = next(iter(options)), "main-game map names"
        else:
            text = decode_text(raw + b"\0", 0, table).text
            if text not in map_corpus:
                missing.append(text)
                continue
            new, route = encode_text(map_corpus[text], table, overrides=story), "corpus"
        if new == raw:
            counts["already the same"] += 1
            continue
        assert len(new) < MAP_SLOT
        output[a:a + MAP_SLOT] = new + bytes(MAP_SLOT - len(new))
        counts[route] += 1
    outputs["MAP/MAPNAME.BIN"] = bytes(output)
    report["MAP/MAPNAME.BIN"] = dict(slots=len(source) // MAP_SLOT, **counts, without_translation=missing[:30])

    OUT.mkdir(parents=True, exist_ok=True)
    for member, data in outputs.items():
        (OUT / member).parent.mkdir(parents=True, exist_ok=True)
        (OUT / member).write_bytes(data)
    summary = dict(report=report, files={m: sha256(d) for m, d in outputs.items()},
                   original_files={m: locks[m] for m in outputs})
    (OUT / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
