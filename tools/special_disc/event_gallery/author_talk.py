"""Author the gallery's map-dialogue sections from the Original STAGE scripts.

The gallery replays Original stage events on the SP engine. Their map dialogue
(script op 0x0f n) lives in the Original STAGE chunk's dialogue block, which the
SP disc does not carry. This tool reads that block from the locked Japanese
Original disc, keeps each record's native structure (record type, expression,
speaking pilot, section header and control records), maps the speaking pilot to
its SP definition, and pairs every line with the reviewed Chinese translation
from ``corpus/zh`` (speaker names from ``story-speakers.json``).

The output ``config/products/special-disc/event-gallery-talk.json`` is the only
input the build reads; the build encodes the text with the SP codebook.
Usage: author_talk.py [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "tools")]

from srwz.codec import decode_production  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets  # noqa: E402
from srwz.stage import STAGE_BASE_ADDRESS, _read_block_references  # noqa: E402
from srwz.text import decode_text, load_text_table  # noqa: E402

ORIGINAL_ISO = ROOT / "build/iso/sources/original.iso"
SP_ISO = ROOT / "build/iso/sources/Super Robot Taisen Z - Special Disc [J].iso"
# Dialogue control records 0x3a n / 0x3b n play and wait for CCC voice n
# (e.g. 万丈's "世のため人のため" in STAGE069 section 21). The two discs number
# their CCC clips differently, so n is remapped to the SP clip with the same audio.
VOICE_RECORDS = (0x3A, 0x3B)
JP_TABLE = ROOT / "vendor/upstream-python/project/tbl_all.json"
OUT = ROOT / "config/products/special-disc/event-gallery-talk.json"
ID_MAP = ROOT / "work/analysis/sp-event-fidelity-20261013/id-map.json"

# Scene -> (stage index, map-dialogue section ids replayed inside the clip, in
# script order). Section n is the target of the scene's original "0x0f n"; a
# (section, lines) pair keeps only the first lines and closes the section there
# (STAGE002 section 17 continues into 丹泽尔's route choice, which is gameplay).
SCENES: dict[str, tuple[int, list]] = {
    "effect-273": (2, [10, 11, 12, 13, 14, 15, 16, (17, 4)]),
    "effect-255": (126, [31, 33, 34, 36]),
    "effect-256": (21, [26, 27, 28, 29, 30, 31, 32]),
    "effect-257": (117, [21, 22, 23]),
    "effect-258": (128, [53, 54, 55, 56]),
    "effect-259": (107, [60, 61, 62, 63, 64, 65]),
    "effect-264": (7, [17, 18, 19, 20, 21, 22, 23]),
    "effect-265": (107, [42, 43, 44]),
    "effect-266": (26, [19, 20, 21, 22]),
    "effect-267": (43, [22, 23]),
    "effect-268": (47, [0, 1, 2, 3, 4, 5, 6]),
    "effect-269": (47, [13, 14, 15, 16, 17]),
    "effect-282": (69, [17, 18, 19, 21, 22]),
}

# "$n" expands to the SP save's protagonist name (Rand on the review card), so a
# route-specific scene names its protagonist explicitly.
PROTAGONIST = {"effect-273": "节子", "effect-282": "节子", "effect-264": "节子"}


def stage_chunk(index: int) -> bytes:
    members = member_map(scan_iso9660(ORIGINAL_ISO))

    def read(name: str) -> bytes:
        member = members[name]
        with ORIGINAL_ISO.open("rb") as disc:
            disc.seek(member.extent_lba * 2048)
            return disc.read(member.size)

    stage, hb = read("DATA/STAGE.BIN"), read("HEDBDY/HB.BIN")
    spec = ExecutableOffsetSpec(name="HEDBDY/HB.BIN STAGE offsets", member="HEDBDY/HB.BIN",
                                table_start=30320, table_end=31144)
    offsets = read_executable_archive_offsets(hb, spec, len(stage))
    return decode_production(stage[offsets[index]:offsets[index + 1]]).output


def dialogue_sections(data: bytes) -> dict[int, int]:
    """Section id -> chunk offset for the map-dialogue block (the largest one)."""
    best: dict[int, int] = {}
    for reference in _read_block_references(data, base_address=STAGE_BASE_ADDRESS):
        table, count = struct.unpack_from("<II", data, reference)
        table -= STAGE_BASE_ADDRESS
        if not 0 < table < len(data) or count > 512:
            continue
        found = {}
        for k in range(count):
            address, section = struct.unpack_from("<II", data, table + 8 * k)
            if 0 < address - STAGE_BASE_ADDRESS < len(data):
                found[section] = address - STAGE_BASE_ADDRESS
        if len(found) > len(best):
            best = found
    return best


class VoiceMap:
    """Original CCC id -> SP CCC id with byte-identical audio."""

    def __init__(self):
        self.discs = {}
        self.cache: dict[int, int] = {}

    def _disc(self, path: Path):
        if path not in self.discs:
            members = member_map(scan_iso9660(path))
            with path.open("rb") as stream:
                entry = members["SOUND/CCC.MSH"]
                stream.seek(entry.extent_lba * 2048)
                directory = stream.read(entry.size)
            self.discs[path] = (members["SOUND/CCC.MSB"].extent_lba * 2048, directory)
        return self.discs[path]

    def _clip(self, path: Path, index: int) -> bytes:
        base, directory = self._disc(path)
        size, offset = struct.unpack_from("<II", directory, 12 + 8 * index)
        with path.open("rb") as stream:
            stream.seek(base + offset)
            return stream.read(size)

    def sp(self, original: int) -> int:
        if original not in self.cache:
            clip = self._clip(ORIGINAL_ISO, original)
            _, directory = self._disc(SP_ISO)
            count = struct.unpack_from("<I", directory, 8)[0]
            for index in range(count):
                if struct.unpack_from("<I", directory, 12 + 8 * index)[0] == len(clip) and \
                        self._clip(SP_ISO, index) == clip:
                    self.cache[original] = index
                    break
            else:
                raise ValueError(f"Original CCC voice {original} has no identical clip on the SP disc")
        return self.cache[original]


def pilot_map() -> dict[int, int]:
    rows = json.loads(ID_MAP.read_text(encoding="utf-8"))
    return {r["original"]: r["sp"] for r in rows if r["kind"] == "pilot"}


def resolve_pilot(original: int, mapping: dict[int, int]) -> int:
    if original in mapping:
        return mapping[original]
    sys.path.insert(0, str(ID_MAP.parent))
    import names  # analysis helper: same-name ordinal + byte similarity
    return names.resolve("pilot", original)["sp"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    jp = load_text_table(JP_TABLE)
    speakers = {e["source_text_sha256"]: e["translation"]
                for e in json.loads((ROOT / "corpus/zh/story-speakers.json").read_text(encoding="utf-8"))["entries"]
                if e.get("translation")}
    mapping = pilot_map()
    voices = VoiceMap()
    scenes = {}
    for scene, (stage, wanted) in SCENES.items():
        data = stage_chunk(stage)
        corpus = {e["id"]: e for e in json.loads(
            (ROOT / f"corpus/zh/story-dialogue/stage-{stage:03d}.json").read_text(encoding="utf-8"))["entries"]}
        located = dialogue_sections(data)
        sections = []
        for spec in wanted:
            section, limit = spec if isinstance(spec, tuple) else (spec, None)
            offset = located[section]
            header = list(struct.unpack_from("<8I", data, offset))
            records, line, position = [], 0, offset + 0x20
            while True:
                words = list(struct.unpack_from("<8I", data, position))
                if words[0] == 0x7E:
                    break
                if limit is not None and line == limit:
                    records.append({"words": [0x16, 0, 0, 0, 0, 0, 0, 0]})
                    break
                if words[4] > STAGE_BASE_ADDRESS:
                    text_at = words[4] - STAGE_BASE_ADDRESS
                    speaker = decode_text(data, text_at, jp, stop_at_newline=True)
                    message = decode_text(data, speaker.end, jp) if speaker.terminator == "newline" else None
                    entry_id = f"story/{stage:03d}/dialogue/01.{section + 1:02d}/{line:04d}"
                    row = corpus.get(entry_id)
                    if row is None or not row.get("translation"):
                        raise ValueError(f"{scene}: no reviewed translation for {entry_id}")
                    speaker_zh = speakers.get(hashlib.sha256(speaker.text.encode()).hexdigest()) if message else ""
                    if message and not speaker_zh:
                        raise ValueError(f"{entry_id}: speaker {speaker.text!r} has no translation")
                    text = row["translation"]
                    if "$n" in speaker_zh + text:
                        if scene not in PROTAGONIST:
                            raise ValueError(f"{entry_id}: $n needs a PROTAGONIST entry for {scene}")
                        speaker_zh = speaker_zh.replace("$n", PROTAGONIST[scene])
                        text = text.replace("$n", PROTAGONIST[scene])
                    records.append({
                        # +16 is the text (written at build); a stage address in +20..+28
                        # (keyword link, e.g. 《恐龙帝国》) means nothing in SP memory.
                        "words": words[:4] + [0] + [w if w < STAGE_BASE_ADDRESS else 0 for w in words[5:]],
                        "pilot_original": words[3],
                        "pilot_sp": resolve_pilot(words[3], mapping),
                        "speaker": speaker_zh,
                        "text": text,
                        "source": {"id": entry_id, "speaker": speaker.text,
                                   "japanese": (message or speaker).text},
                    })
                    line += 1
                else:
                    if words[0] >= 0x60 and words[0] not in (0x60, 0x61):
                        raise ValueError(f"{scene}: unexpected control record {words[0]:#x}")
                    if words[0] in VOICE_RECORDS:
                        records.append({"words": [words[0], voices.sp(words[1])] + words[2:],
                                        "voice_original": words[1]})
                    else:
                        records.append({"words": words})
                position += 32
            sections.append({"section": section, "offset": hex(offset), "header": header, "records": records,
                             **({"lines_kept": limit} if limit is not None else {})})
        scenes[scene] = {"stage": stage, "sections": sections}
    output = {
        "schema_version": 1,
        "source": {"disc": "build/iso/sources/original.iso", "stage_base": hex(STAGE_BASE_ADDRESS),
                   "japanese_table": str(JP_TABLE.relative_to(ROOT)),
                   "translations": "corpus/zh/story-dialogue/stage-NNN.json + corpus/zh/story-speakers.json"},
        "record_format": "32-byte records: +0 type (1 = line, 0x16 section end, 0x7e terminator), +4 expression, "
                         "+8 1, +12 speaking pilot (SP id written at build), +16 text pointer (speaker\\nline)",
        "scenes": scenes,
    }
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: [s["section"] for s in v["sections"]] for k, v in scenes.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
