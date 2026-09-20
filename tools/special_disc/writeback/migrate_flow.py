"""Bring the main game's Scenario Chart overviews and episode titles into SP's flow.bin.

flow.bin is STAGE chunk 0 (it starts at offset 0, so no table is needed to find
it). The Library's Scenario Chart shows it: for the main game's chart
(「剧情流程 Z」) a chapter opens as 「第N話「title」」 above its overview, and SP
carries all of that main-game data in its own flow.bin:

  * 110 overviews through a pointer table at 0x14864 (main game: 0x10DD4). The
    text is the main game's, in allocations of the same size, and the main
    build rewrote each one inside its allocation. So every allocation is
    replaced by the bytes the main build left in the same allocation.
  * 110 main-game episode records of 0x70 bytes from 0x14B10 (「第N話」 at
    +0x10, a 64-byte title at +0x20, binary fields around them). The main
    game has no such table; its chart titles are the COMPDATA stage names, so a
    title takes the Chinese the main build wrote for the same Japanese stage
    name in COMPDATA. Where COMPDATA has two answers (a song title kept in
    Japanese in one place), the reviewed stage-name corpus decides, encoded
    with the main game's stored-text codebook. 「第N話」 stays as the main
    game shows it.

flow.bin is then re-encoded and must fit its STAGE slot (HB.BIN keeps every
offset); the space it saves stays in the slot.

Outputs (work/build/special-disc/components/flow/):
  DATA/STAGE.BIN   STAGE with chunk 0 rewritten in its slot
  report.json      what changed, the slot use and the readback check
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srwz.codec import decode_production, reencode_changed_suffix  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.text import decode_text, load_text_table  # noqa: E402
import migrate_compdata as compdata  # noqa: E402
from migrate_slps_text import encoding_tables  # noqa: E402
from srwz.text import encode_text  # noqa: E402

from special_disc.source import SOURCE_ISO as ISO  # noqa: E402
from special_disc.source import DISC_INVENTORY as LOCKS  # noqa: E402
TABLE = ROOT / "vendor/upstream-python/project/tbl_all.json"
OG_JAPANESE = ROOT / "work/disc/DATA/STAGE.BIN"
OG_CHINESE = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                     "/project/work/build/zh-release-full-story/components/DATA/STAGE.BIN")
OUT = ROOT / "work/build/special-disc/components/flow"
STAGE, HB = "DATA/STAGE.BIN", "HEDBDY/HB.BIN"
HB_TABLE = 0x5170
OG_BASE, SD_BASE = 0x7566F0, 0x8045F0
OG_OVERVIEWS, SD_OVERVIEWS, OVERVIEW_COUNT = 0x10DD4, 0x14864, 110
EPISODES, EPISODE_COUNT, EPISODE_SIZE = 0x14B10, 110, 0x70
TITLE = (0x20, 0x60)  # 64-byte title field; +0x10 holds 「第N話」, +0x60 binary


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(members, locks, name: str) -> bytes:
    m = members[name]
    with ISO.open("rb") as f:
        f.seek(m.extent_lba * 2048)
        data = f.read(m.size)
    assert sha256(data) == locks[name], f"{name} lock drift"
    return data


def compdata_answers(table) -> dict[str, set[bytes]]:
    """Japanese -> Chinese bytes over every COMPDATA pointer slot of the main game."""
    japanese = decode_production(compdata.OG_JAPANESE.read_bytes()).output
    chinese = decode_production(compdata.OG_CHINESE.read_bytes()).output
    answers = collections.defaultdict(set)
    for offset, target in compdata.pointer_targets(japanese, compdata.OG_BASE):
        text = compdata.text_at(japanese, target, table)
        word = struct.unpack_from("<I", chinese, offset)[0]
        if text is None or not compdata.OG_BASE <= word < compdata.OG_BASE + len(chinese):
            continue
        start = word - compdata.OG_BASE
        answers[text.text].add(chinese[start:chinese.index(0, start)])
    return answers


def main() -> None:
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    table = load_text_table(TABLE)
    og_jp = decode_production(OG_JAPANESE.read_bytes()).output
    og_zh = decode_production(OG_CHINESE.read_bytes()).output
    stage = read_member(members, locks, STAGE)
    hb = read_member(members, locks, HB)
    slot = struct.unpack_from("<I", hb, HB_TABLE + 4)[0]
    assert struct.unpack_from("<I", hb, HB_TABLE)[0] == 0
    result = decode_production(stage[:slot])
    flow = bytearray(result.output)

    # 1. overviews: same Japanese, same allocation size, the main build's bytes
    overviews = 0
    for k in range(OVERVIEW_COUNT):
        og_ptr = struct.unpack_from("<I", og_jp, OG_OVERVIEWS + 4 * k)[0] - OG_BASE
        zh_ptr = struct.unpack_from("<I", og_zh, OG_OVERVIEWS + 4 * k)[0] - OG_BASE
        sd_ptr = struct.unpack_from("<I", flow, SD_OVERVIEWS + 4 * k)[0] - SD_BASE
        japanese = decode_text(og_jp, og_ptr, table)
        ours = decode_text(bytes(flow), sd_ptr, table)
        assert ours.text == japanese.text, f"overview {k} differs from the main game"
        assert zh_ptr == og_ptr, f"overview {k}: the main build moved it"
        span = japanese.consumed
        flow[sd_ptr:sd_ptr + span] = og_zh[zh_ptr:zh_ptr + span]
        overviews += 1

    # 2. episode titles: the main game's COMPDATA stage names
    answers = compdata_answers(table)
    _table, _menu, story, _readback = encoding_tables()
    corpus = json.loads((ROOT / "corpus/zh/menu/stage-names.json").read_text(encoding="utf-8"))
    stage_names = {e["source_text_sha256"]: e["translation"] for e in corpus["entries"] if e.get("translation")}
    titles, left, from_corpus = 0, [], 0
    assert struct.unpack_from('<I', flow, 0x17C94)[0] == SD_BASE + EPISODES + 0x10, 'Z chart table pointer drift'
    assert struct.unpack_from('<h', flow, EPISODES + EPISODE_COUNT * EPISODE_SIZE + 0x60)[0] == 70, 'Z chart terminator drift'
    for k in range(EPISODE_COUNT):
        assert struct.unpack_from('<h', flow, EPISODES + k * EPISODE_SIZE + 0x60)[0] != 70, 'Z chart ended early'
        a = EPISODES + k * EPISODE_SIZE
        field = bytes(flow[a + TITLE[0]:a + TITLE[1]])
        end = field.index(0)
        assert not any(field[end:]), f"episode {k}: title field is not zero-padded"
        text = decode_text(field, 0, table).text
        options = answers.get(text)
        if options and len(options) == 1:
            chinese = next(iter(options))
        elif hashlib.sha256(text.encode("utf-8")).hexdigest() in stage_names:
            chinese = encode_text(stage_names[hashlib.sha256(text.encode("utf-8")).hexdigest()], table,
                                  overrides=story)
            from_corpus += 1
        else:
            left.append(text)
            continue
        assert len(chinese) + 1 <= len(field), f"episode {k}: title does not fit"
        flow[a + TITLE[0]:a + TITLE[1]] = chinese + bytes(len(field) - len(chinese))
        titles += 1

    assert titles == EPISODE_COUNT and not left, f'Incomplete Z titles: {titles}/{EPISODE_COUNT}: {left}'

    # 3. the codec, inside chunk 0's slot
    encoded = reencode_changed_suffix(stage[:result.consumed], bytes(flow), strategy="rust-maximum",
                                      original_result=result)
    assert decode_production(encoded).output == bytes(flow), "flow.bin does not read back"
    assert len(encoded) <= slot, f"flow.bin needs {len(encoded)} > slot {slot}"
    output = bytearray(stage)
    output[:slot] = encoded + bytes(slot - len(encoded))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "DATA").mkdir(exist_ok=True)
    (OUT / STAGE).write_bytes(bytes(output))
    report = dict(overviews=overviews, episode_titles=titles, titles_from_corpus=from_corpus, titles_left=left,
                  slot=slot, encoded=len(encoded), headroom=slot - len(encoded), decoded=len(flow),
                  answer_key=dict(stage_japanese=str(OG_JAPANESE.relative_to(ROOT)),
                                  stage_chinese=str(OG_CHINESE.relative_to(ROOT)),
                                  titles="main-game COMPDATA stage names (migrate_compdata answer key)"),
                  files={STAGE: sha256(bytes(output))}, original_files={STAGE: locks[STAGE]})
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("answer_key", "files", "original_files")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
