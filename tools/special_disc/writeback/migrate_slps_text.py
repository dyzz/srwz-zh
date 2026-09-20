"""Bring the project's finished Chinese into the SP executable's UI strings.

The main game's own built executable is the answer key. Almost every UI string
there was rewritten in place, so at each main-game string offset the Japanese
source and the final Chinese bytes stand side by side; those bytes are copied
as they are, which carries every production decision along exactly (the menu
codes the main build normalises to the current font, surface aliases, width
tags). Nothing is re-encoded for these strings.

The main game translates the same Japanese differently in different places
(パイロット is 驾驶员 in one list and 机师 in another), so the lookup goes by
place first: the SP and main-game string sequences are aligned, and a string
that sits in a run of the same strings in the same order takes the bytes at
that main-game offset. Otherwise a Japanese string takes the main-game answer
if the main game has only one; if it has several, it is left alone.

Japanese that the main executable does not contain at all (speaker names,
terrain names and the like) is looked up by sha256 in the finished corpora and
encoded with the main game's current stored-text codebook. A text-only match
must be referenced by a pointer or by code, or be at least three characters
long, so no data run is taken for text.

Every string is written into its own span only, terminated, the rest cleared:
nothing moves, no pointer changes; what does not fit is reported, never cut.
The Special Theatre suspend messages get their own pass (see suspend_messages).

Outputs (work/build/special-disc/components/text/):
  SLPS_259.20    executable with the reusable UI strings in Chinese
  report.json    coverage by route, skipped strings and the readback check
"""
from __future__ import annotations

import difflib
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.text import (  # noqa: E402
    SrwzTextError,
    augment_text_table,
    decode_text,
    encode_text,
    load_text_table,
    normalize_original_fullwidth_ascii,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)
from srwz.writers import encode_stage_message  # noqa: E402

ISO_LOCKS = ROOT / "config/products/special-disc/disc-inventory.json"
SD_STRINGS = ROOT / "config/products/special-disc/ui/exe_strings.json"
MENU_MAP = ROOT / "config/products/special-disc/ui/menu_map.json"
OG_EXE = ROOT / "work/disc/SLPS_258.87"
# the main game's finished Original build (2026-09-17, v0.4.2 release chain)
OG_CHINESE_EXE = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                         "/project/work/build/zh-release-full-story/components/SLPS_258.87")
FONT_MANIFEST = ROOT / "manifests/zh-release-font-validation.json"
MENU_CODEBOOK = ROOT / "config/encoding/release-menu-codebook.json"
TABLE = ROOT / "vendor/upstream-python/project/tbl_all.json"
CORPUS = ROOT / "corpus"
BASE = ROOT / "work/build/special-disc/components/font"  # executable to build on, if present
OUT = ROOT / "work/build/special-disc/components/text"
EXE = "SLPS_259.20"
# the SP executable's two string areas (reports/ui.md §2)
TEXT_AREAS = ((0x375C00, 0x375E00), (0x3A7F00, 0x3C5180))
# Special Theatre suspend-message scripts (speaker, newline, message) inside the second area.
# All 296 scripts run to 0x3BE6E2; the robot-registration notice follows at 0x3BE830.
SUSPEND_REGION = (0x3B8BE0, 0x3BE700)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def encoding_tables(proposal_path: Path | None = None):
    """The main game's stored-text codebook: font assignments over the base table."""
    table = load_text_table(TABLE)
    if proposal_path is None:
        manifest = json.loads(FONT_MANIFEST.read_text(encoding="utf-8"))
        proposal_path = ROOT / manifest["proposal"]["path"]
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    primary = {a["character"]: int(a["code"], 16) for a in proposal["assignments"]}
    aliases = {a["character"]: int(a["code"], 16)
               for a in proposal.get("surface_alias_assignments", [])}
    codebook = json.loads(MENU_CODEBOOK.read_text(encoding="utf-8"))
    release = {a["character"]: int(a["code"], 16) for a in codebook["assignments"]}
    story = dict(primary)
    story.update(aliases)
    story.update(original_fullwidth_ascii_overrides(table))
    story[" "] = ord(" ")
    # menu text keeps the historical menu assignments on top (main build: _apply_release_menu_text)
    overrides = dict(story)
    overrides.update(release)
    readback = project_runtime_text_table(table, release)
    for extra in (primary, aliases, original_fullwidth_ascii_overrides(table)):
        readback = project_runtime_text_table(readback, extra)
    return table, overrides, story, readback


def corpus_index(table) -> tuple[dict[str, str], dict]:
    """sha256(Japanese) -> Chinese, gathered from the finished main-game corpora."""
    index: dict[str, str] = {}
    stats: dict[str, dict] = {}
    conflicts: list[dict] = []

    def add(source_name: str, rows):
        added = skipped = 0
        for source_hash, translation in rows:
            if not translation:
                skipped += 1
                continue
            previous = index.get(source_hash)
            if previous is None:
                index[source_hash] = translation
                added += 1
            elif previous != translation:
                conflicts.append(dict(source=source_name, hash=source_hash,
                                      kept=previous, dropped=translation))
        stats[source_name] = dict(added=added, without_translation=skipped)

    menu = json.loads((CORPUS / "zh/menu/release-v0.3.json").read_text(encoding="utf-8"))
    add("menu/release-v0.3", ((e["source_text_sha256"], e.get("translation", "")) for e in menu["entries"]))

    system = json.loads((CORPUS / "zh/story-system-dialogue.json").read_text(encoding="utf-8"))
    add("story-system-dialogue", ((e["source_text_sha256"], e.get("translation", ""))
                                  for e in system["entries"]))

    # remaining-ui keeps main-game byte offsets: resolve each to its Japanese text
    remaining = json.loads((CORPUS / "zh/menu/remaining-ui.json").read_text(encoding="utf-8"))
    og = OG_EXE.read_bytes()
    for key in ("slps_by_offset", "slps_context_ui_by_offset"):
        rows = []
        for offset_text, translation in remaining.get(key, {}).items():
            offset = int(offset_text, 16)
            try:
                decoded = decode_text(og, offset, table)
            except SrwzTextError:
                continue
            rows.append((sha256_text(decoded.text), translation))
        add(f"remaining-ui/{key}", rows)
    for key in ("display_names_by_source_text", "atlas_by_source_text"):
        add(f"remaining-ui/{key}", ((sha256_text(source), translation)
                                    for source, translation in remaining.get(key, {}).items()))

    names = json.loads((CORPUS / "zh/menu/ui-name-tables.json").read_text(encoding="utf-8"))
    add("ui-name-tables", ((e["source_text_sha256"], e.get("translation", ""))
                           for group in ("squad_names", "map_names") for e in names.get(group, [])))

    terrain = json.loads((CORPUS / "zh/menu/mapmodel-terrain-names.json").read_text(encoding="utf-8"))
    add("mapmodel-terrain-names", ((sha256_text(e["source"]), e.get("translation", ""))
                                   for e in terrain["entries"]))

    speakers = json.loads((CORPUS / "zh/story-speakers.json").read_text(encoding="utf-8"))
    add("story-speakers", ((e["source_text_sha256"], e.get("translation", ""))
                           for e in speakers["entries"]))

    titles = json.loads((CORPUS / "zh/auto-demo-work-titles.json").read_text(encoding="utf-8"))
    add("auto-demo-work-titles", ((e["source_text_sha256"], e.get("translation", ""))
                                  for e in titles["entries"]))
    return index, dict(sources=stats, entries=len(index), conflicts=conflicts[:20],
                       conflict_count=len(conflicts))


def suspend_messages(exe: bytearray, table, story_overrides) -> dict:
    """Special Theatre suspend messages: "speaker\\nmessage\\0" scripts in the executable.

    They are the main game's chunk-zero quit dialogue, carried over into the SP
    executable. Each one is rewritten like the main build rewrites that
    dialogue: speaker, newline, then the message through encode_stage_message
    (which keeps keyword-link codes), inside the source pair plus the zero
    alignment that follows it.
    """
    corpus = json.loads((CORPUS / "zh/story-system-dialogue.json").read_text(encoding="utf-8"))
    by_hash = {}
    for entry in corpus["entries"]:
        if entry.get("editorial_status") == "reviewed" and entry.get("translation") and entry.get("speaker"):
            by_hash.setdefault(entry["source_text_sha256"], entry)
    start, end = SUSPEND_REGION
    position, found, written, missing, overflow = start, 0, [], [], []
    while position < end:
        if exe[position] == 0:
            position += 1
            continue
        try:
            speaker = decode_text(bytes(exe), position, table, stop_at_newline=True)
        except SrwzTextError:
            position += 1
            continue
        if speaker.terminator != "newline" or not speaker.text:
            position = exe.index(0, position) + 1
            continue
        message = decode_text(bytes(exe), speaker.end, table)
        found += 1
        entry = by_hash.get(sha256_text(message.text))
        region_end = message.end
        while region_end < end and exe[region_end] == 0:
            region_end += 1
        if entry is None:
            missing.append(dict(offset=hex(position), speaker=speaker.text, japanese=message.text))
            position = message.end
            continue
        payload = (encode_text(normalize_original_fullwidth_ascii(entry["speaker"]), table,
                               overrides=story_overrides)
                   + b"\n"
                   + encode_stage_message(table, story_overrides, entry_id=entry["id"],
                                          source_text=message.text,
                                          replacement=normalize_original_fullwidth_ascii(entry["translation"]),
                                          terminate=True))
        if len(payload) > region_end - position:
            overflow.append(dict(offset=hex(position), needs=len(payload), capacity=region_end - position,
                                 japanese=message.text))
            position = message.end
            continue
        exe[position:region_end] = payload + bytes(region_end - position - len(payload))
        written.append(dict(offset=hex(position), id=entry["id"], speaker=entry["speaker"],
                            japanese=message.text, chinese=entry["translation"]))
        position = region_end
    return dict(found=found, rewritten=written, missing=missing, overflow=overflow)


def answer_key(og_rows: list[dict]) -> dict[int, bytes]:
    """Main-game string offset -> the Chinese bytes the main build left there."""
    japanese = OG_EXE.read_bytes()
    chinese = OG_CHINESE_EXE.read_bytes()
    assert len(japanese) == len(chinese)
    key = {}
    for row in og_rows:
        offset = row["off"]
        before = japanese[offset:japanese.index(0, offset)]
        after = chinese[offset:chinese.index(0, offset)]
        if after and after != before:
            key[offset] = after
    return key


def inventory(edition: str) -> list[dict]:
    """Strings found in one executable (ui/exe_strings.py), in file order."""
    rows = json.loads(SD_STRINGS.read_text(encoding="utf-8"))[edition]
    seen = {}
    for group in ("referenced", "unreferenced"):
        for row in rows.get(group, []):
            seen.setdefault(row["off"], dict(row, referenced=group == "referenced"))
    return [seen[offset] for offset in sorted(seen)]


def og_locations() -> dict[int, tuple[str, str]]:
    """Main-game string offset -> (source, Chinese) exactly as the main build writes it.

    The same Japanese is translated differently in different places of the main
    game (layout, context), so a location-exact answer beats the hash lookup.
    Menu entries are written first and remaining-ui last, as in the main build.
    """
    menu = json.loads((CORPUS / "zh/menu/release-v0.3.json").read_text(encoding="utf-8"))
    by_id = {e["id"]: e["translation"] for e in menu["entries"] if e.get("translation")}
    located: dict[int, tuple[str, str]] = {}
    for row in json.loads(MENU_MAP.read_text(encoding="utf-8")):
        translation = by_id.get(row["id"])
        if translation:
            for offset in row["og_targets"]:
                located[offset] = ("menu/release-v0.3", translation)
    remaining = json.loads((CORPUS / "zh/menu/remaining-ui.json").read_text(encoding="utf-8"))
    for key in ("slps_by_offset", "slps_context_ui_by_offset"):
        for offset_text, translation in remaining.get(key, {}).items():
            if translation:
                located[int(offset_text, 16)] = (f"remaining-ui/{key}", translation)
    return located


def align(og: list[dict], sd: list[dict]) -> dict[int, int]:
    """SD offset -> main-game offset for strings in runs that appear in the same order."""
    matcher = difflib.SequenceMatcher(a=[r["text"] for r in og], b=[r["text"] for r in sd], autojunk=False)
    pairs = {}
    for block in matcher.get_matching_blocks():
        if block.size < 2:  # a lone equal string is not evidence of the same place
            continue
        for k in range(block.size):
            pairs[sd[block.b + k]["off"]] = og[block.a + k]["off"]
    return pairs


def main() -> None:
    locks = {m["path"]: m["sha256"] for m in json.loads(ISO_LOCKS.read_text())["sp"]["members"]}
    base = BASE / EXE if (BASE / EXE).exists() else None
    exe = bytearray((base or (OUT / EXE)).read_bytes()) if base else None
    assert exe is not None, "build the font component first (install_font.py)"
    base_report = json.loads((BASE / "report.json").read_text())
    assert base_report["original_files"][EXE] == locks[EXE], "font component built on another disc"

    table, _menu_overrides, story_overrides, readback = encoding_tables()
    index, index_report = corpus_index(table)
    og_rows, sd_rows = inventory("OG"), inventory("SD")
    og_of = align(og_rows, sd_rows)
    key = answer_key(og_rows)
    # every Chinese answer the main game has for a Japanese string, over all its places
    by_text: dict[str, set[bytes]] = {}
    og_text = {row["off"]: row["text"] for row in og_rows}
    for offset, chinese in key.items():
        by_text.setdefault(og_text[offset], set()).add(chinese)

    written, skipped = [], []
    how = {"same place": 0, "only answer": 0, "corpus": 0}
    left = {"no answer": 0, "answered two ways": 0, "short and unreferenced": 0}
    for row in sd_rows:
        offset = row["off"]
        if not any(start <= offset < end for start, end in TEXT_AREAS):
            continue
        if SUSPEND_REGION[0] <= offset < SUSPEND_REGION[1]:
            continue  # the suspend scripts get their own pass below
        try:
            decoded = decode_text(bytes(exe), offset, table)
        except SrwzTextError:
            continue
        if decoded.text != row["text"]:
            continue  # inventory drift: never write what was not inspected
        chinese, text = None, None
        if og_of.get(offset) in key:
            chinese, route = key[og_of[offset]], "same place"
        else:
            options = by_text.get(decoded.text)
            if options and len(options) > 1:
                left["answered two ways"] += 1
                continue
            if options:
                chinese, route = next(iter(options)), "only answer"
            else:
                text = index.get(sha256_text(decoded.text))
                if text is None:
                    left["no answer"] += 1
                    continue
                chinese, route = encode_text(text, table, overrides=story_overrides), "corpus"
            # A string only matched by its text has to look like text in its own right:
            # referenced by a pointer or by code, or long enough that a data run cannot pose as it.
            if not (row.get("ptrs") or row.get("hilo") or len(decoded.text) >= 3):
                left["short and unreferenced"] += 1
                continue
        span = decoded.consumed
        if len(chinese) + 1 > span:
            skipped.append(dict(offset=hex(offset), reason="does not fit", span=span, needs=len(chinese) + 1,
                                route=route, japanese=decoded.text))
            continue
        exe[offset:offset + span] = chinese + bytes(span - len(chinese))
        how[route] += 1
        written.append(dict(offset=hex(offset), route=route,
                            og_offset=hex(og_of[offset]) if offset in og_of else None,
                            japanese=decoded.text, chinese=decode_text(chinese + b"\0", 0, readback).text,
                            corpus_text=text))

    # readback: every rewritten string is exactly the bytes chosen for it, then its terminator
    for row in written:
        offset = int(row["offset"], 16)
        got = decode_text(bytes(exe), offset, readback)
        assert got.text == row["chinese"] and got.terminator == "nul", (row["offset"], got.text)
        if row["corpus_text"] is not None:
            assert got.text == row["corpus_text"], (row["offset"], got.text, row["corpus_text"])

    suspend = suspend_messages(exe, table, story_overrides)
    for row in suspend["rewritten"]:
        offset = int(row["offset"], 16)
        speaker = decode_text(bytes(exe), offset, readback, stop_at_newline=True)
        assert speaker.text == normalize_original_fullwidth_ascii(row["speaker"]), row["offset"]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / EXE).write_bytes(bytes(exe))
    report = dict(
        base=str((BASE / EXE).relative_to(ROOT)),
        corpus=index_report,
        answer_key=dict(japanese=str(OG_EXE.relative_to(ROOT)),
                        chinese=str(OG_CHINESE_EXE.relative_to(ROOT)),
                        chinese_sha256=hashlib.sha256(OG_CHINESE_EXE.read_bytes()).hexdigest(),
                        rewritten_in_main_game=len(key)),
        strings=dict(inventory=len(sd_rows), aligned_to_main_game=len(og_of), rewritten=len(written),
                     by_route=how, left=left, skipped=len(skipped)),
        skipped=skipped[:40],
        suspend_messages=dict(found=suspend["found"], rewritten=len(suspend["rewritten"]),
                              without_translation=suspend["missing"], overflow=suspend["overflow"]),
        samples=[{k: row[k] for k in ("offset", "route", "japanese", "chinese")} for row in written[:25]],
        files={EXE: hashlib.sha256(bytes(exe)).hexdigest()},
        base_files={EXE: base_report["files"][EXE]},
        original_files={EXE: locks[EXE]},
    )
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")
    (OUT / "rewritten.json").write_text(json.dumps(written, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("strings", "suspend_messages")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
