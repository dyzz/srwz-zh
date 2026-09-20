"""Export the Special Disc's text, module by module, for translation.

Modules (the user's split, 2026-09-18):
  01 剧情模式    Story Mode: 21 episodes (STAGE chunks, COMPDATA titles,
                 flow.bin synopses and chart titles, HSFC chart summaries),
                 group intros (VT1 chunk 40, executable), narrations
                 (MTZSPROS), data link, new map names
  02 挑战模式    Challenge Battle: 18 missions (STAGE chunks, VT1 chunk 50
                 briefings, HSFC summaries), objectives and results
  03 资料库补漏  Library gaps left after the migration: encyclopedia fields
                 without an answer, changed Strategy Q&A pages, squad names,
                 chart key help, COMPDATA unit/pilot names
  04 系统播报    Z Report records (none in SD, see the module README),
                 intermission tickers, pop-up notices
  05 系统说明文字 executable and COMPDATA UI/help text still in Japanese,
                 suspend messages not yet written, image text still to draw

Everything is read from the original SD disc; "still in Japanese" is judged
against the migrated preview components under work/build/sd-*-component
(a string is done when the component changed its bytes, or when the main
game keeps the same Japanese bytes too). Existing main-game translations are
looked up by sha256 of the Japanese, exactly as the corpus keys them.

Read-only: nothing under corpus/, config/, tools/ or any ISO is written.
Output: out/ next to this script (README, per-module JSON/Markdown, CSV).
"""
from __future__ import annotations

import collections
import csv
import datetime
import difflib
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "work/review/special-disc/text-export"
WRITEBACK = ROOT / "tools/special_disc/writeback"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(WRITEBACK))

from srwz.codec import decode_production  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.library import ZKAN_TEXT_TAGS, parse_zkn_decoded_chunk  # noqa: E402
from srwz.nisv_strategy_qa import QA_DATA_BASE, QA_METADATA_GROUPS, _parse_page  # noqa: E402
from srwz.summary import parse_summary  # noqa: E402
from srwz.text import (  # noqa: E402
    CONTROL_NOTATION,
    SrwzTextError,
    decode_text,
    load_text_table,
    normalize_original_fullwidth_ascii,
)
import srwz.stage as stock_stage  # noqa: E402
import srwz.stage_formations as stage_formations  # noqa: E402
import migrate_compdata as mc  # noqa: E402
import migrate_slps_text as mst  # noqa: E402
from special_disc.writeback.exe_data_guard import NON_TEXT_WORDS  # noqa: E402

ISO = ROOT / "rom/Super Robot Taisen Z - Special Disc [J].iso"
LOCKS = ROOT / "config/products/special-disc/disc-inventory.json"
EXE_STRINGS = ROOT / "config/products/special-disc/ui/exe_strings.json"
CORPUS = ROOT / "corpus/zh"
OUT = HERE / "out"
EXE = "SLPS_259.20"
# the member each migrated component left behind (build_preview.py stacks them in this order)
PREVIEW = {
    EXE: "work/build/special-disc/components/system-text/SLPS_259.20",
    "DATA/COMPDATA.BN": "work/build/special-disc/components/system-text/DATA/COMPDATA.BN",
    "DATA/NISVDATA.BIN": "work/build/special-disc/components/nisv/DATA/NISVDATA.BIN",
    "DATA/STAGE.BIN": "work/build/special-disc/components/system-text/DATA/STAGE.BIN",
    "MAP/MAPNAME.BIN": "work/build/special-disc/components/names/MAP/MAPNAME.BIN",
    "DATA/MTVZKNRT.BIN": "work/build/special-disc/components/library/DATA/MTVZKNRT.BIN",
    "DATA/MTVZKNPT.BIN": "work/build/special-disc/components/library/DATA/MTVZKNPT.BIN",
    "DATA/MTVZKNKW.BIN": "work/build/special-disc/components/library/DATA/MTVZKNKW.BIN",
}

# ---- SD layout (reports/stage.md, reports/library.md, reports/ui.md)
SD_STAGE_BASE = 0x8045F0
SD_FUNCTION_TABLE = (0x358980, 0x358A90)
HB_STAGE_TABLE = 0x5170
COMPDATA_BASE = 0x764F80
STAGE_NAME_RECORDS = (0x7CD5B0 - COMPDATA_BASE, 48, 65)
FLOW_SYNOPSES = (0x74B4, 21)
FLOW_EPISODES = (0x7500, 0x70, 21)
FLOW_KEY_HELP = (0x17E00, 0x17F40)
HSFC_TABLE, HSFC_SUMMARIES = 0x3AE8A0, (0xE6, 0x42, 3, 66)
MTZSPROS_TABLE = 0x387880
VT1_TABLE = 0x353790
VT1_PAGES = {40: 9, 50: 7}  # chunk -> lines per entry (28 full-width columns each)
NISV_TABLE = 0x384A00
SQUAD_BASE, SQUAD_STRIDE, SQUAD_NAME = 0x22, 286, 28
MAPNAME_SLOT, MAPNAME_COUNT = 256, 200
ZKN = {  # member: (SD table, label, main-game table start/end)
    "DATA/MTVZKNRT.BIN": (0x387160, "robot", (0x32B390, 0x32B897)),
    "DATA/MTVZKNPT.BIN": (0x3865B0, "character", (0x32A810, 0x32AE7B)),
    "DATA/MTVZKNKW.BIN": (0x387770, "keyword", (0x32B980, 0x32BA4F)),
}
ZKN_KIND = {"robot": "机体图鉴", "character": "人物事典", "keyword": "用语事典"}
ZKN_TAG = {"RBTN": "机体名", "PLTN": "驾驶员", "SRCE": "出处", "DSCR": "说明", "DSC2": "说明2",
           "CHFN": "全名", "CHNN": "通称", "ACTR": "声优", "KANA": "读音", "HEIT": "身高",
           "PRDC": "制作", "NAME": "名称"}
PILOTS = (0x2B50, 178, 969)
PILOT_FIELDS = (("display", 2, 21), ("family", 23, 23), ("given", 46, 23))

GROUPS = {1: "アナザーサイド　レコード", 2: "バックストーリー　メモリー", 3: "グローリー・スター　レポート",
          4: "ビーター・サービス　業務日誌", 5: "シークレット　エピローグ"}
GROUP_TAG = {1: "ASR", 2: "BSM", 3: "GSR", 4: "BSW", 5: "SE"}
DIFFICULTY = {1: "NORMAL", 2: "HARD", 3: "EX-HARD"}
NARRATION_GROUP = {0: (1, "开场"), 1: (1, "结尾"), 2: (2, "开场"), 3: (2, "结尾"), 4: (3, "开场"), 5: (3, "结尾"),
                   6: (4, "开场"), 7: (4, "结尾"), 8: (5, "开场"), 9: (5, "结尾")}

# executable string areas (SD file offsets) -> (module, category)
EXE_TEXT_AREAS = ((0x375C00, 0x375E00), (0x3A7F00, 0x3C5180))
SUSPEND_AREA = (0x3B8BE0, 0x3BE700)
EXE_AREAS = (
    (0x375C00, 0x375E00, "05", "舰船名"),
    (0x3A7F00, 0x3AD000, "05", "通用界面／技能说明"),
    (0x3AD000, 0x3AE000, "05", "记忆卡与存档名"),
    (0x3AE000, 0x3B5000, "05", "通用界面（其他）"),
    (0x3B5000, 0x3B51A0, "05", "额外关卡菜单说明"),
    (0x3B51A0, 0x3B5200, "01", "数据链接"),
    (0x3B5200, 0x3B5888, "05", "特别剧场：中断对话标题"),
    (0x3B5888, 0x3B58B8, "05", "特别剧场：影片标题"),
    (0x3B58B8, 0x3B6738, "05", "特别剧场：设定资料标题"),
    (0x3B6738, 0x3B7530, "05", "特别剧场：壁纸名"),
    (0x3B7530, 0x3B77A0, "05", "特别剧场：战斗剧场作品名"),
    (0x3B77A0, 0x3B8BE0, "05", "特别剧场：菜单／说明／幻灯片"),
    (0x3BE700, 0x3C2E00, "05", "通用界面（其他）"),
    (0x3C2E00, 0x3C4400, "05", "战斗鉴赏"),
    (0x3C4400, 0x3C4CD0, "01", "剧情模式菜单"),
    (0x3C4CD0, 0x3C5068, "02", "挑战模式"),
    (0x3C5068, 0x3C5180, "05", "战斗鉴赏"),
)
# not player text: a developer message, a width-measuring template and data runs that decode as kanji
EXE_NOT_TEXT = {0x3B7D90, 0x3B8100, 0x3B86D4, 0x3B0C1C, 0x3B1DD8, 0x3B1FDC, 0x3B346C} | set(NON_TEXT_WORDS)
# pop-up notices shown during play go to module 04
EXE_NOTICES = {
    0x3B22A0: "挑战模式中选择自动编成时",
    0x3BE830: "机体登录通知（第 1 行）",
    0x3BE860: "机体登录通知（第 2 行）",
    0x3BE890: "机体登录通知：登录的机体名",
    0x3BE8B0: "机体登录通知：登录的机体名",
    0x3BEFA0: "通关后保存",
}
# COMPDATA (SD decoded offsets) -> (module, category); first match wins, else by table region
COMPDATA_AREAS = (
    (0x853E0, 0x85E20, "03", "BGM 曲名"),
    (0x85E20, 0x88660, None, "排序键（推测不显示）"),
    (0x88660, 0x888D0, "03", "作品名"),
    (0x888D0, 0x89000, "03", "用语名"),
    (0x93350, 0x960A0, "05", "战斗鉴赏：帮助说明"),
    (0x960A0, 0x97E00, "05", "指令说明"),
    (0x97E00, 0x98270, "01", "数据链接"),
    (0x98270, 0x98290, "02", "挑战模式"),
    (0x98290, 0x98710, "05", "战斗鉴赏：界面"),
    (0x98710, 0xA0000, "05", "战斗鉴赏：机体／驾驶员列表"),
)
COMPDATA_REGION = {
    "battle lines": ("05", "撤退台词"),
    "units": ("03", "机体名"),
    "weapons": ("05", "武器名"),
    "special abilities": ("05", "特殊能力"),
    "search/leadership": ("05", "帮助说明"),
    "abilities 2/buttons": ("05", "帮助说明"),
    "stage names": (None, "关卡名"),  # carried by the episode files
}
# image text still to be drawn (docs/SPECIAL_DISC_PLAN.md §2.2, reports/ui.md §4/§6)
IMAGE_TEXT = (
    ("01", "KVMDATA 块 11", "结算提示图集", ["プロローグ", "遂行中"], "「までクリア！」沿用本篇中文"),
    ("01", "MAPMODEL 成员 195–197", "世界地图标题（新）",
     ["北アメリア大陸　新地球連邦軍ニューアーク基地", "北アメリア大陸中央部", "北アメリア大陸　新地球連邦軍マッコーネル基地"],
     "副标题「- SUPER ROBOT WARS Z Special Disc -」保留英文"),
    ("05", "KVMDATA 块 8", "战斗鉴赏图集",
     ["戦闘開始", "援護", "攻撃", "防御", "再", "戦艦", "攻", "反", "量産", "全種", "地上系", "空中", "宇宙", "分類"],
     "另有英文标签保留"),
    ("05", "VT1 块 53", "战斗鉴赏按钮", ["トライ", "シングル"], "其余按钮已完成；这两个出处未确认，暂保留日文"),
    ("05", "AIDDATA 块 2", "特别剧场横幅（译名暂用）", ["設定資料集", "壁紙一覧"], "暂作“设定资料集”“壁纸一览”"),
    ("05", "VT1 块 28", "标题副标题条", ["スペシャルディスク"], "暂作“特别篇”，待定名"),
)

KANA = re.compile(r"[\u3041-\u30FF]")
JAPANESE = re.compile(r"[\u3041-\u30FF\u3400-\u9FFF]")
TODAY = datetime.date(2026, 9, 18).isoformat()
READBACK = None  # the Chinese runtime text table, set in main()

STATUS_NEW = "新译"
STATUS_REUSE = "可复用"
STATUS_PENDING_WRITE = "可复用·未写入"
STATUS_CHOOSE = "待选定"
STATUS_EDIT = "改稿"  # SD edited a main-game text: reference given
STATUS_TEMPLATE = "套用"  # a numbered variant of a name the main game already translates
STATUS_KEEP = "保留"  # English / placeholders: normally kept
NOT_NEW = (STATUS_REUSE, STATUS_PENDING_WRITE, STATUS_TEMPLATE, STATUS_KEEP)
# 「name（n）」: the name part may already have a Chinese form
NUMBERED = re.compile(r"^(?P<base>.+?)(?P<sep>[　 ]?)(?P<num>（[０-９0-9]+）)$")
# the executable keeps the episode blurbs as fixed lines; these ranges are read as one paragraph each
SPLIT_LINES = ((0x3C46C0, 0x3C4780), (0x3C4780, 0x3C4850), (0x3C4850, 0x3C4920), (0x3C4920, 0x3C49E0),
               (0x3C49E0, 0x3C4AA0), (0x3C4AA0, 0x3C4B70), (0x3C4B70, 0x3C4BD0))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def visible(text: str) -> int:
    return len(CONTROL_NOTATION.sub("", text).replace("\n", ""))


def shows_as_chinese(text: str, shown: str) -> bool:
    """The Chinese font already shows this Japanese string as the same simplified characters.

    shown is the string decoded through the Chinese runtime table. It must carry
    no kana, equal the Japanese once full-width letters and digits are folded
    (the font draws them half-width), and use GB2312 characters only, so a
    Japanese or traditional form that the font kept is not taken for Chinese.
    """
    if KANA.search(shown) or normalize_original_fullwidth_ascii(shown) != normalize_original_fullwidth_ascii(text):
        return False
    for ch in shown:
        if "㐀" <= ch <= "鿿":
            try:
                ch.encode("gb2312")
            except UnicodeEncodeError:
                return False
    return True


def numbered(row: dict, corpus) -> dict:
    """「name（n）」 whose name part is known: suggest the Chinese name with the same number."""
    match = NUMBERED.match(row["source"])
    if row["status"] != STATUS_NEW or not match:
        return row
    base = corpus.name(match["base"])
    if not base:
        return row
    row.update(status=STATUS_TEMPLATE, translation=base + match["sep"] + match["num"],
               note=f"「{match['base']}」已有译名「{base}」，按编号套用")
    return row


# ------------------------------------------------------------------ inputs
class Disc:
    def __init__(self):
        self.locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
        self.members = member_map(scan_iso9660(ISO))
        self.cache = {}

    def original(self, name: str) -> bytes:
        if name not in self.cache:
            m = self.members[name]
            with ISO.open("rb") as f:
                f.seek(m.extent_lba * 2048)
                data = f.read(m.size)
            assert sha256(data) == self.locks[name], f"{name}: SD disc member drifted"
            self.cache[name] = data
        return self.cache[name]

    @staticmethod
    def preview(name: str) -> bytes:
        return (ROOT / PREVIEW[name]).read_bytes()


def table_offsets(exe: bytes, start: int, size: int) -> list[int]:
    values, pos = [], start
    while True:
        value = struct.unpack_from("<I", exe, pos)[0]
        values.append(value)
        pos += 4
        if value == size:
            return values
        assert len(values) < 5000, hex(start)


def chunk(data: bytes, offsets: list[int], index: int) -> bytes:
    return decode_production(data[offsets[index]:offsets[index + 1]]).output


def sd_stage_module():
    """Shared parser selects SP control records and conditions by explicit base."""
    return stock_stage


class Corpus:
    """sha256(Japanese) -> Chinese, per kind, from the finished main-game corpora."""

    def __init__(self, table):
        def load(path):
            return json.loads((CORPUS / path).read_text(encoding="utf-8"))

        self.dialogue = collections.defaultdict(list)
        for path in sorted((CORPUS / "story-dialogue").glob("stage-*.json")):
            for e in json.loads(path.read_text(encoding="utf-8"))["entries"]:
                if e.get("translation") and e["translation"] not in self.dialogue[e["source_text_sha256"]]:
                    self.dialogue[e["source_text_sha256"]].append(e["translation"])
        self.speakers = {}
        for e in load("story-speakers.json")["entries"]:
            if e.get("translation"):
                self.speakers.setdefault(e["source_text_sha256"], e["translation"])
        self.conditions = collections.defaultdict(list)
        for e in load("story-conditions.json")["entries"]:
            if e.get("translation") and e["translation"] not in self.conditions[e["source_text_sha256"]]:
                self.conditions[e["source_text_sha256"]].append(e["translation"])
        self.tickers = {e["source_text"]: e["translation"] for e in load("story-tickers.json")["entries"]}
        self.system = {}
        for e in load("story-system-dialogue.json")["entries"]:
            if e.get("translation"):
                self.system.setdefault(e["source_text_sha256"], e)
        formations = load("menu/stage-default-formations.json")
        self.formations = dict(formations["translations_by_source_text"])
        for source, value in formations["accepted_current_translations_by_source_text"].items():
            self.formations.setdefault(source, value[0] if isinstance(value, list) else value)
        self.stage_names = {e["source_text_sha256"]: e["translation"]
                            for e in load("menu/stage-names.json")["entries"] if e.get("translation")}
        self.library = {e["source_text_sha256"]: e["translation"]
                        for e in load("library/v0.2-reviewed.json")["entries"] if e.get("translation")}
        names = load("menu/ui-name-tables.json")
        self.names = {e["source_text_sha256"]: e["translation"]
                      for group in ("squad_names", "map_names") for e in names[group] if e.get("translation")}
        qa = load("menu/nisv-strategy-qa.json")
        self.qa_pages = {p["page"]: p for p in qa["pages"]}
        self.any, _report = mst.corpus_index(table)
        self.compdata = {}  # main-game COMPDATA answers (unit, weapon, BGM names), filled by compdata_leftovers

    def name(self, text: str):
        """Any known Chinese for a short name (speakers, library, UI tables)."""
        h = sha256_text(text)
        for source in (self.speakers, self.names, self.library, self.any):
            if h in source:
                return source[h]
        return self.compdata.get(text) or self.formations.get(text)


def entry(entry_id, kind, source, *, status=None, translation="", **extra) -> dict:
    row = dict(id=entry_id, kind=kind, source=source, source_sha256=sha256_text(source),
               chars=visible(source), status=status or STATUS_NEW, translation=translation)
    row.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return row


def reuse(row_id, kind, source, candidates, **extra) -> dict:
    candidates = [c for c in candidates if c]
    if not candidates:
        return entry(row_id, kind, source, **extra)
    if len(candidates) == 1:
        return entry(row_id, kind, source, status=STATUS_REUSE, translation=candidates[0], **extra)
    return entry(row_id, kind, source, status=STATUS_REUSE, translation=candidates[0],
                 alternatives=candidates[1:], note="主篇对同一原文有多种译法，已取第一种", **extra)


# ------------------------------------------------------------------ STAGE (modules 01, 02, 04)
def stage_data(disc: Disc, table, corpus: Corpus) -> dict:
    stage = disc.original("DATA/STAGE.BIN")
    hb = disc.original("HEDBDY/HB.BIN")
    exe = disc.original(EXE)
    offsets = table_offsets(hb, HB_STAGE_TABLE, len(stage))
    decoded = [chunk(stage, offsets, i) for i in range(len(offsets) - 1)]
    names = [d[0x30:0x50].split(b"\0", 1)[0].decode("ascii") for d in decoded]
    sd_stage = sd_stage_module()
    functions = sd_stage.read_stage_function_addresses(exe, start=SD_FUNCTION_TABLE[0], end=SD_FUNCTION_TABLE[1])

    compdata = decode_production(disc.original("DATA/COMPDATA.BN")).output
    start, stride, count = STAGE_NAME_RECORDS
    records = []
    for r in range(count):
        words = struct.unpack_from("<12I", compdata, start + stride * r)
        title = decode_text(compdata, words[0] - COMPDATA_BASE, table)
        records.append(dict(record=r, chunk=r + 1, file=names[r + 1], title=title.text,
                            title_offset=words[0] - COMPDATA_BASE, title_bytes=title.consumed,
                            group=words[1] & 0xFF, slot=(words[1] >> 8) & 0xFF, seq=words[7] & 0xFFFF))

    flow = decoded[0]
    synopses = []
    for k in range(FLOW_SYNOPSES[1]):
        pointer = struct.unpack_from("<I", flow, FLOW_SYNOPSES[0] + 4 * k)[0] - SD_STAGE_BASE
        text = decode_text(flow, pointer, table)
        synopses.append(dict(ordinal=k, offset=pointer, text=text.text, size=text.consumed))
    chart = {}
    at, size, n = FLOW_EPISODES
    for k in range(n):
        rec = flow[at + size * k: at + size * (k + 1)]
        chapter = decode_text(rec, 0x10, table, end=0x20).text
        title = decode_text(rec, 0x20, table, end=0x60).text
        chunk_index, seq = struct.unpack_from("<H", rec, 0x60)[0], struct.unpack_from("<H", rec, 0x66)[0]
        chart[chunk_index] = dict(record=k, chapter=chapter, title=title, seq=seq, offset=at + size * k + 0x20)

    hsfc = disc.original("DATA/HSFC.BIN")
    hsfc0 = chunk(hsfc, table_offsets(exe, HSFC_TABLE, len(hsfc)), 0)
    first, cell, cells, count = HSFC_SUMMARIES
    summaries = {}
    for k in range(count):
        lines = []
        for c in range(cells):
            o = first + (k * cells + c) * cell
            lines.append(decode_text(hsfc0[o:o + cell], 0, table).text)
        summaries[k + 1] = dict(record=k, lines=lines, offset=first + k * cells * cell)

    stages = {}
    for index, data in enumerate(decoded):
        if index == 0:
            continue
        try:
            parsed = sd_stage.parse_stage(data, table, stage_index=index, function_address=functions[index],
                                          base_address=SD_STAGE_BASE)
        except sd_stage.StageParseError:
            continue  # stg_901 (developer script) uses another format
        speakers = {e.speaker_id: e.text for e in parsed.entries if e.kind == "speaker"}
        rows = []
        for e in parsed.entries:
            if e.kind == "dialogue":
                op = None
                if e.pointer_offset is not None:
                    op = struct.unpack_from("<I", data, e.pointer_offset - 16)[0]
                rows.append(dict(kind="scene_label" if op in (0x10, 0x11, 0x12) else "dialogue", id=e.entry_id,
                                 section=e.section, text=e.text, speaker=speakers.get(e.speaker_id, ""), op=op))
            elif e.kind == "condition":
                rows.append(dict(kind="condition", id=e.entry_id, section=e.section, text=e.text))
        found_tickers, found_formations = tickers(data, table), formations(data, table, index)
        owned = set()
        for e in parsed.entries:
            if e.text_offset is not None:
                owned.update(range(e.text_offset, decode_text(data, e.text_offset, table).end))
        for offset, _text in found_tickers:
            owned.update(range(offset, offset + 140))
        for offset, _text, consumed in found_formations:
            owned.update(range(offset, offset + consumed))
        stages[index] = dict(rows=rows, speakers=speakers, tickers=found_tickers, formations=found_formations,
                             residue=residue(data, table, owned))
    return dict(decoded=decoded, names=names, records=records, synopses=synopses, chart=chart,
                summaries=summaries, stages=stages, flow=flow)


def residue(data: bytes, table, owned: set[int]) -> list[tuple[int, str, int]]:
    """Japanese strings a pointer reaches that no known owner (dialogue, condition, ticker, formation) claims.

    This is how the Z Report question was settled for SD: the main game's Z
    Report records (6, -1, -1, pointer) are one such pointer; SD has none, and
    what is left here is listed with its stage for review.
    """
    found = {}
    for position in range(0, len(data) - 3, 4):
        target = struct.unpack_from("<I", data, position)[0] - SD_STAGE_BASE
        if not 0 < target < len(data) or target in owned or target in found or data[target - 1] != 0:
            continue
        try:
            text = decode_text(data, target, table, end=min(len(data), target + 400))
        except SrwzTextError:
            continue
        if (text.terminator == "nul" and not text.unknown_code_count and len(text.text) >= 2
                and JAPANESE.search(text.text) and plausible(text.text, table)):
            found[target] = (target, text.text, text.consumed)
    return sorted(found.values())


def z_report_records(data: bytes) -> int:
    """The main game's Z Report record shape: 6, -1, -1, then a pointer into the chunk."""
    count = 0
    for position in range(0, len(data) - 15, 4):
        if struct.unpack_from("<III", data, position) == (6, 0xFFFFFFFF, 0xFFFFFFFF):
            target = struct.unpack_from("<I", data, position + 12)[0] - SD_STAGE_BASE
            count += 0 <= target < len(data)
    return count


def tickers(data: bytes, table) -> list[tuple[int, str]]:
    """Intermission ticker slots: six 0xFF bytes, a word, then a 140-byte text slot (aux_scan.py)."""
    found = []
    for offset in range(12, len(data), 4):
        if offset + 140 > len(data) or data[offset - 10:offset - 4] != b"\xff" * 6:
            continue
        try:
            text = decode_text(data, offset, table, end=offset + 140)
        except SrwzTextError:
            continue
        if (text.terminator != "nul" or text.unknown_code_count or not JAPANESE.search(text.text)
                or any(data[text.end:offset + 140]) or (offset + 140 < len(data) and data[offset + 140] == 0)):
            continue
        found.append((offset, text.text))
    return found


def formations(data: bytes, table, index: int) -> list[tuple[int, str, int]]:
    """Squad and unit names by the project's structural scanners run with the SD base (approximate)."""
    stage_formations.STAGE_BASE_ADDRESS = SD_STAGE_BASE
    sf = stage_formations
    groups = list(sf._scan_structural_formation_groups(data, table, stage_index=index))
    groups += list(sf._scan_structural_record_groups(data, table, stage_index=index))
    occupied = {c.offset for g in groups for c in g.cells}
    for g in sf._scan_layout(data, table, stage_index=index, layout="slot32", slot_size=32, stride=32):
        cells = [c for c in g.cells if c.offset not in occupied]
        if cells:
            groups.append(sf.FormationGroup(stage_index=index, layout="slot32", slot_size=32, stride=32,
                                            cells=tuple(cells)))
    try:
        groups += list(sf._scan_packed8_groups(data, table, stage_index=index, source_texts=None, owner_data=data))
    except Exception:  # noqa: BLE001 - the packed-8 probe is best effort, as in aux_scan.py
        pass
    seen, out = set(), []
    for g in groups:
        for c in g.cells:
            if c.offset not in seen:
                seen.add(c.offset)
                out.append((c.offset, c.source_text, c.source_consumed))
    return sorted(out)


def stage_rows(index: int, st: dict, corpus: Corpus, prefix: str) -> list[dict]:
    rows = []
    for r in st["rows"]:
        rid = prefix + r["id"].split("/", 2)[2]
        if r["kind"] == "condition":
            rows.append(reuse(rid, "condition", r["text"], corpus.conditions.get(sha256_text(r["text"]), []),
                              section=r["section"]))
            continue
        speaker = r["speaker"]
        extra = dict(section=r["section"])
        if speaker:
            extra.update(speaker=speaker, speaker_zh=corpus.name(speaker))
        rows.append(reuse(rid, r["kind"], r["text"], corpus.dialogue.get(sha256_text(r["text"]), []), **extra))
    return rows


def speaker_rows(index: int, st: dict, corpus: Corpus, prefix: str) -> list[dict]:
    rows = []
    for sid, text in sorted(st["speakers"].items()):
        if not text.strip("　 "):
            continue  # blank speaker lines (narration boxes)
        known = corpus.speakers.get(sha256_text(text)) or corpus.name(text)
        rows.append(entry(f"{prefix}speaker/{sid:03d}", "speaker", text,
                          status=STATUS_REUSE if known else STATUS_NEW, translation=known or ""))
    return rows


def residue_rows(st: dict, corpus: Corpus, prefix: str) -> list[dict]:
    rows = []
    for offset, text, consumed in st["residue"]:
        known = corpus.name(text)
        rows.append(entry(f"{prefix}text/{offset:05X}", "stage_text", text, status=STATUS_REUSE if known else STATUS_NEW,
                          translation=known or "", max_bytes=consumed, location=f"块内 0x{offset:05X}",
                          note="被指针引用、但不属于对白／条件／编队的字符串，用途待确认"))
    return rows


def formation_rows(index: int, st: dict, corpus: Corpus, prefix: str) -> list[dict]:
    """One row per distinct name; every cell it occupies is listed, the smallest slot is the limit."""
    cells = collections.defaultdict(list)
    for offset, text, consumed in st["formations"]:
        cells[text].append((offset, consumed))
    rows = []
    for text, places in cells.items():
        known = corpus.formations.get(text) or corpus.name(text)
        rows.append(entry(f"{prefix}formation/{places[0][0]:05X}", "formation_name", text,
                          status=STATUS_REUSE if known else STATUS_NEW, translation=known or "",
                          max_bytes=min(c for _o, c in places), occurrences=len(places),
                          offsets=[f"{index:03d}:0x{o:05X}" for o, _c in places]))
    return rows


# ------------------------------------------------------------------ executable and COMPDATA leftovers
def exe_leftovers(disc: Disc, table, readback, corpus: Corpus) -> dict:
    """Executable strings the migrated preview still shows in Japanese, classified."""
    original, preview = disc.original(EXE), disc.preview(EXE)
    inventory = json.loads(EXE_STRINGS.read_text(encoding="utf-8"))
    rows = {}
    for group in ("referenced", "unreferenced"):
        for row in inventory["SD"][group]:
            rows.setdefault(row["off"], dict(row, referenced=group == "referenced"))
    og_rows = collections.defaultdict(list)
    for group in ("referenced", "unreferenced"):
        for row in inventory["OG"][group]:
            og_rows[row["text"]].append(row["off"])
    og_jp, og_zh = mst.OG_EXE.read_bytes(), mst.OG_CHINESE_EXE.read_bytes()

    out, skipped = [], collections.Counter()
    for offset in sorted(rows):
        row = rows[offset]
        if not any(a <= offset < b for a, b in EXE_TEXT_AREAS) or SUSPEND_AREA[0] <= offset < SUSPEND_AREA[1]:
            continue
        text = row["text"]
        if not plausible(text, table) or not JAPANESE.search(text):
            continue
        if offset and original[offset - 1] != 0:
            skipped["mid-string reference"] += 1
            continue
        if offset in EXE_NOT_TEXT:
            skipped["developer string or data run"] += 1
            continue
        decoded = decode_text(original, offset, table)
        if decoded.text != text:
            continue
        if preview[offset:offset + decoded.consumed] != original[offset:offset + decoded.consumed]:
            skipped["already Chinese in the preview"] += 1
            continue
        if re.fullmatch(r"[ー―－\-\s　０-９0-9％%sd：:（）()＜＞・．.,、一]+", text):
            skipped["placeholder"] += 1
            continue
        shown = decode_text(preview, offset, readback).text
        if shows_as_chinese(text, shown):
            skipped["same characters in Chinese"] += 1
            continue
        places = sorted(set(og_rows.get(text, [])))
        answers, kept = [], 0
        for o in places:
            d = decode_text(og_jp, o, table)
            if og_zh[o:o + d.consumed] != og_jp[o:o + d.consumed]:
                zh = decode_text(og_zh, o, readback).text
                if zh not in answers:
                    answers.append(zh)
            else:
                kept += 1
        if places and not answers:
            skipped["main game keeps the same Japanese"] += 1
            continue
        module, category = next(((m, c) for a, b, m, c in EXE_AREAS if a <= offset < b), ("05", "其他"))
        if offset in EXE_NOTICES:
            module, category = "04", "弹出通知"
        extra = dict(location=f"{EXE} 0x{offset:06X}", max_bytes=decoded.consumed, category=category)
        rid = f"sd/exe/{offset:06X}"
        if answers:
            row_out = entry(rid, "ui", text, status=STATUS_CHOOSE, translation=answers[0], alternatives=answers[1:],
                            note="主篇有译文但未能自动迁移（多种译法或放不下），请选定", **extra)
        else:
            known = corpus.any.get(sha256_text(text))
            row_out = entry(rid, "ui", text, status=STATUS_REUSE if known else STATUS_NEW,
                            translation=known or "", **extra)
        if offset in EXE_NOTICES:
            row_out["context"] = EXE_NOTICES[offset]
        split = next((f"0x{a:06X}" for a, b in SPLIT_LINES if a <= offset < b), None)
        if split:
            row_out["context"] = f"段落 {split} 的一行"
            row_out["note"] = "主程序按行存放的一段说明（每行约 32 个全角字），与同段相邻几行连读"
        row_out["module"] = module
        out.append(numbered(row_out, corpus))
    return dict(rows=collapse_wallpapers(out), skipped=skipped)


def collapse_wallpapers(rows: list[dict]) -> list[dict]:
    """「壁紙００１」…「壁紙２２３」: one formula, one row."""
    walls = [r for r in rows if r.get("category") == "特别剧场：壁纸名" and re.fullmatch(r"壁紙[０-９]{3}", r["source"])]
    if not walls:
        return rows
    first = dict(walls[0])
    first.update(id="sd/exe/wallpaper-names", kind="template",
                 locations=[r["location"] for r in walls],
                 note=f"同一格式共 {len(walls)} 条（{walls[0]['source']}–{walls[-1]['source']}），"
                      "定下“壁紙”的译法后按编号生成")
    keep = [r for r in rows if r not in walls]
    keep.insert(rows.index(walls[0]), first)
    return keep


def plausible(text: str, table) -> bool:
    """ui/plaus.py: rejects binary data that happens to decode (half-width kana, ASCII junk, level-2 runs)."""
    core = re.sub(r"%[-+ 0#]*\d*(?:\.\d+)?[diouxXsScfeEgG]|\$[cflnF]", "",
                  re.sub(r"@?<[a-z0-9]+:[0-9A-F]{2}>", "", text))
    jp = [ch for ch in core if ord(ch) >= 0x80 and ch != "\n"]
    if not jp or any(0xFF61 <= ord(ch) <= 0xFF9F for ch in core):
        return False
    letters = sum(1 for ch in core if ch.isascii() and ch.isalpha())
    if any(ch.isascii() and not ch.isalnum() and ch not in " \n.,!?:;-/()[]" for ch in core):
        return False
    if letters and len(jp) < 3:
        return False
    level2 = sum(1 for ch in jp if table.inverse_characters.get(ch, 0) >= 0x989F)
    if level2 and (len(jp) < 4 or level2 / len(jp) > 0.25):
        return False
    if len(jp) <= 2 and any(ch.isascii() and ch.isalnum() for ch in core):
        return False
    return True


def suspend_leftovers(disc: Disc, table, corpus: Corpus) -> list[dict]:
    """Special Theatre suspend messages the preview has not rewritten (all have main-game Chinese)."""
    original, preview = disc.original(EXE), disc.preview(EXE)
    rows, position = [], SUSPEND_AREA[0]
    while position < SUSPEND_AREA[1]:
        if original[position] == 0:
            position += 1
            continue
        try:
            speaker = decode_text(original, position, table, stop_at_newline=True)
        except SrwzTextError:
            position += 1
            continue
        if speaker.terminator != "newline" or not speaker.text:
            position = original.index(0, position) + 1
            continue
        message = decode_text(original, speaker.end, table)
        if preview[position:message.end] == original[position:message.end]:
            known = corpus.system.get(sha256_text(message.text))
            rows.append(entry(f"sd/exe/{position:06X}", "suspend_message", message.text,
                              status=STATUS_PENDING_WRITE if known else STATUS_NEW,
                              translation=known["translation"] if known else "",
                              speaker=speaker.text, speaker_zh=known["speaker"] if known else corpus.name(speaker.text),
                              location=f"{EXE} 0x{position:06X}", category="特别剧场：中断对话", module="05"))
        position = message.end
    return rows


def compdata_leftovers(disc: Disc, table, readback, corpus: Corpus) -> dict:
    original = decode_production(disc.original("DATA/COMPDATA.BN")).output
    preview = decode_production(disc.preview("DATA/COMPDATA.BN")).output
    og_jp = decode_production(mc.OG_JAPANESE.read_bytes()).output
    og_zh = decode_production(mc.OG_CHINESE.read_bytes()).output
    # slot by slot, as migrate_compdata.py: the main build may have moved a string, so follow its pointer
    answers = collections.defaultdict(list)
    og_kept = set()
    for slot, target in mc.pointer_targets(og_jp, mc.OG_BASE):
        text = mc.text_at(og_jp, target, table)
        if text is None:
            continue
        word = struct.unpack_from("<I", og_zh, slot)[0]
        if not mc.OG_BASE <= word < mc.OG_BASE + len(og_zh):
            continue
        start = word - mc.OG_BASE
        chinese = og_zh[start:og_zh.index(0, start)]
        if chinese == og_jp[target:target + text.consumed - 1]:
            og_kept.add(text.text)
            continue
        zh = decode_text(chinese + b"\0", 0, readback).text
        if zh and zh not in answers[text.text]:
            answers[text.text].append(zh)
    corpus.compdata.update({text: options[0] for text, options in answers.items() if len(options) == 1})
    references = collections.defaultdict(list)
    for slot, target in mc.pointer_targets(original, COMPDATA_BASE):
        references[target].append(slot)
    still_referenced = {target for _slot, target in mc.pointer_targets(preview, COMPDATA_BASE)}

    rows, skipped = [], collections.Counter()
    for target in sorted(references):
        text = mc.text_at(original, target, table)
        if text is None:
            continue
        if target and original[target - 1] != 0:
            skipped["mid-string reference"] += 1
            continue
        if len(text.text) < 2 or any(0xFF61 <= ord(ch) <= 0xFF9F for ch in text.text):
            skipped["single character or half-width"] += 1
            continue
        if preview[target:target + text.consumed] != original[target:target + text.consumed]:
            skipped["already Chinese in the preview"] += 1
            continue
        if target not in still_referenced:
            skipped["pointers moved to a Chinese string"] += 1
            continue
        region = collections.Counter(mc.region_of(s, 2) for s in references[target]).most_common(1)[0][0]
        module, category = next(((m, c) for a, b, m, c in COMPDATA_AREAS if a <= target < b),
                                COMPDATA_REGION.get(region, ("05", "其他")))
        if category.startswith("排序键"):
            skipped["sort keys (kana, not displayed)"] += 1
            continue
        if module is None:
            continue  # stage names: episode files
        if region == "head" or region == "pilots":
            skipped["data before the first table"] += 1
            continue
        if text.text in og_kept and text.text not in answers:
            skipped["main game keeps the same Japanese"] += 1
            continue
        if re.fullmatch(r"[ー―－\-\s　０-９0-9％：:（）()＜＞・．.,、一]+", text.text):
            skipped["placeholder"] += 1
            continue
        if shows_as_chinese(text.text, decode_text(preview, target, readback).text):
            skipped["same characters in Chinese"] += 1
            continue
        extra = dict(location=f"COMPDATA.BN 解压 0x{target:05X}", max_bytes=text.consumed, category=category,
                     module=module)
        rid = f"sd/compdata/{target:05X}"
        if text.text in answers:
            options = answers[text.text]
            rows.append(entry(rid, "ui", text.text, status=STATUS_CHOOSE, translation=options[0],
                              alternatives=options[1:], note="主篇有译文但未能自动迁移（多种译法或放不下），请选定",
                              **extra))
        else:
            known = corpus.any.get(sha256_text(text.text))
            rows.append(numbered(entry(rid, "ui", text.text, status=STATUS_REUSE if known else STATUS_NEW,
                                       translation=known or "", **extra), corpus))

    # pilot name fields (inline, not pointed to)
    start, stride, count = PILOTS
    for index in range(count):
        a = start + index * stride
        for field, offset, capacity in PILOT_FIELDS:
            raw = original[a + offset:a + offset + capacity]
            raw = raw[:raw.find(b"\0")] if b"\0" in raw else raw
            if not raw or preview[a + offset:a + offset + len(raw)] != raw:
                continue
            try:
                text = decode_text(raw + b"\0", 0, table).text
            except SrwzTextError:
                continue
            if not JAPANESE.search(text):
                continue
            if shows_as_chinese(text, decode_text(raw + b"\0", 0, readback).text):
                skipped["same characters in Chinese"] += 1
                continue
            known = corpus.name(text)
            rows.append(entry(f"sd/compdata/pilot/{index:03d}/{field}", "pilot_name", text,
                              status=STATUS_REUSE if known else STATUS_NEW, translation=known or "",
                              location=f"COMPDATA.BN 驾驶员记录 {index}（{field}）", max_bytes=capacity,
                              category="驾驶员名", module="03"))
    return dict(rows=rows, skipped=skipped, compdata=original, preview=preview)


# ------------------------------------------------------------------ library (module 03)
def library_gaps(disc: Disc, table, corpus: Corpus) -> list[dict]:
    """Encyclopedia text fields the migration could not answer, with the closest main-game field as reference."""
    import migrate_library as ml
    from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
    exe = disc.original(EXE)
    og_exe = (ml.OG_DISC / "SLPS_258.87").read_bytes()
    og_built = (ml.OG_BUILD / "SLPS_258.87").read_bytes()
    rows = []
    for member, (sd_table, label, (t0, t1)) in ZKN.items():
        spec = ExecutableOffsetSpec(name=member, member=member, table_start=t0, table_end=t1)
        og_jp = (ml.OG_DISC / member).read_bytes()
        og_zh = (ml.OG_BUILD / member).read_bytes()
        jp_chunks = ml.chunks_of(og_jp, read_executable_archive_offsets(og_exe, spec, len(og_jp)))
        zh_chunks = ml.chunks_of(og_zh, read_executable_archive_offsets(og_built, spec, len(og_zh)))
        answers = collections.defaultdict(set)
        og_docs = []
        for jp, zh in zip(jp_chunks, zh_chunks):
            document = parse_zkn_decoded_chunk(decode_production(jp).output)
            _kind, zh_fields = ml.raw_fields(decode_production(zh).output)
            zh_by_tag = dict(zh_fields)
            fields = {}
            for field in document.fields:
                if field.text is not None and field.tag in zh_by_tag:
                    answers[(document.kind, field.tag, field.text)].add(zh_by_tag[field.tag])
                if field.text is not None:
                    fields[field.tag] = field.text
            og_docs.append(fields)
        source = disc.original(member)
        offsets = table_offsets(exe, sd_table, len(source))
        for index, stored in enumerate(ml.chunks_of(source, offsets)):
            document = parse_zkn_decoded_chunk(decode_production(stored).output)
            fields = {f.tag: f.text for f in document.fields if f.text is not None}
            title = fields.get("RBTN") or fields.get("CHFN") or fields.get("CHNN") or fields.get("NAME") or ""
            for field in document.fields:
                if field.text is None or field.tag not in ZKAN_TEXT_TAGS or not field.text.strip():
                    continue
                options = answers.get((document.kind, field.tag, field.text))
                if options and len(options) == 1:
                    continue
                reference = best_reference(field.tag, field.text, title, og_docs, corpus)
                rid = f"sd/library/{label}/{index:03d}/{field.tag}"
                extra = dict(location=f"{member} 条目 {index}", entry_title=title,
                             entry_title_zh=corpus.library.get(sha256_text(title)),
                             field=ZKN_TAG.get(field.tag, field.tag), category=ZKN_KIND[label], module="03")
                if options:
                    extra["note"] = "主篇同一原文有多种译法"
                if reference and reference["trivial"] and reference["main_game_translation"]:
                    extra["note"] = "SD 只改了换行、空格或「・」，主篇译文可直接沿用"
                    rows.append(entry(rid, "library_field", field.text, status=STATUS_REUSE,
                                      translation=reference["main_game_translation"], reference=reference, **extra))
                elif reference:
                    rows.append(entry(rid, "library_field", field.text, status=STATUS_EDIT,
                                      reference=reference, **extra))
                else:
                    known = corpus.library.get(sha256_text(field.text))
                    rows.append(entry(rid, "library_field", field.text,
                                      status=STATUS_REUSE if known else STATUS_NEW,
                                      translation=known or "", **extra))
    return rows


def best_reference(tag: str, text: str, title: str, og_docs: list[dict], corpus: Corpus):
    """The main-game field this SD text edits (same tag, same entry name first, then any entry)."""
    best, best_ratio = None, 0.0
    same_title = [d for d in og_docs if title and title in d.values()]
    for pool in (same_title, og_docs):
        for doc in pool:
            other = doc.get(tag)
            if not other or other == text:
                continue
            ratio = difflib.SequenceMatcher(a=other, b=text, autojunk=False).ratio()
            if ratio > best_ratio:
                best, best_ratio = other, ratio
        if best_ratio >= 0.6:
            break
    if best is None or best_ratio < 0.6:
        return None
    return dict(main_game_source=best, main_game_translation=corpus.library.get(sha256_text(best), ""),
                similarity=round(best_ratio, 3), diff=compact_diff(best, text), trivial=trivial_change(best, text))


def trivial_change(old: str, new: str) -> bool:
    """Only line breaks, spaces or 「・」 differ: the Chinese is laid out afresh anyway."""
    strip = lambda s: re.sub(r"[\n\u3000 ・]", "", s)  # noqa: E731
    return strip(old) == strip(new)


def compact_diff(old: str, new: str) -> str:
    """The changed spans only, line breaks ignored: …context[-removed-]{+added+}context…"""
    a, b = old.replace("\n", ""), new.replace("\n", "")
    parts = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        span = (f"[-{a[a0:a1]}-]" if a1 > a0 else "") + (f"{{+{b[b0:b1]}+}}" if b1 > b0 else "")
        parts.append(f"…{b[max(0, b0 - 8):b0]}{span}{b[b1:b1 + 8]}…")
    return "；".join(parts) if parts else "（仅换行不同）"


def qa_lines(records: list[tuple[int, str]]) -> str:
    """Positioned records -> page text: records on the same row join, a new row starts a new line."""
    lines, row, current = [], None, ""
    for y, text in records:
        if row is not None and y != row:
            lines.append(current)
            current = ""
        row = y
        current += text
    lines.append(current)
    return "\n".join(line for line in lines if line)


def qa_gaps(disc: Disc, table, corpus: Corpus) -> list[dict]:
    """Strategy Q&A pages and metadata strings the preview keeps in Japanese.

    Page text is stored as positioned fragments cut wherever the colour or the
    line changes, and the main game's Chinese flows across those fragments, so
    a page is exported whole: the SD page, the main game's page of the same
    number in Japanese and Chinese, and what SD changed.
    """
    exe = disc.original(EXE)
    source = disc.original("DATA/NISVDATA.BIN")
    offsets = table_offsets(exe, NISV_TABLE, len(source))
    sd6 = chunk(source, offsets, 6)
    pv6 = chunk(disc.preview("DATA/NISVDATA.BIN"), offsets, 6)
    qa = json.loads((CORPUS / "menu/nisv-strategy-qa.json").read_text(encoding="utf-8"))
    rows = []
    count, base = struct.unpack_from("<II", sd6, 0)

    def metadata(chunk_bytes):
        cursor, strings = 0x476, []
        for _ in range(sum(n for _g, n in QA_METADATA_GROUPS)):
            end = chunk_bytes.index(0, cursor)
            strings.append(chunk_bytes[cursor:end])
            cursor = end + 1
        return strings

    group_zh = {"categories": "大类", "topics": "小类", "questions": "问题标题", "category_summaries": "大类概要",
                "topic_summaries": "小类概要", "keyword_summaries": "关键词概要"}
    labels = [(g, k) for g, n in QA_METADATA_GROUPS for k in range(n)]
    sd_meta, pv_meta = metadata(sd6), metadata(pv6)
    questions = {}
    for (group, k), raw, shown in zip(labels, sd_meta, pv_meta):
        text = raw.decode("cp932")
        if group == "questions":
            questions[k + 1] = text
        if raw != shown or not JAPANESE.search(text):
            continue
        og = qa["metadata"][group][k]
        extra = dict(location=f"NISVDATA 块 6 元数据 {group}[{k}]", category=f"攻略Q&A：{group_zh[group]}", module="03")
        reference = dict(main_game_source=og["source"], main_game_translation=og["translation"],
                         diff=compact_diff(og["source"], text), trivial=trivial_change(og["source"], text))
        if reference["trivial"]:
            rows.append(entry(f"sd/nisv/qa/metadata/{group}/{k:03d}", "qa_metadata", text, status=STATUS_REUSE,
                              translation=og["translation"], reference=reference,
                              note="SD 只改了空格或「・」，主篇译文可直接沿用", **extra))
        else:
            rows.append(entry(f"sd/nisv/qa/metadata/{group}/{k:03d}", "qa_metadata", text, status=STATUS_EDIT,
                              reference=reference, **extra))
    for number in range(1, count):
        rel, size = struct.unpack_from("<II", sd6, 8 + 8 * number)
        page = _parse_page(sd6, base + rel, size)
        prel, psize = struct.unpack_from("<II", pv6, 8 + 8 * number)
        preview_page = _parse_page(pv6, base + prel, psize)
        if [r["raw"] for r in page["records"]] != [r["raw"] for r in preview_page["records"]]:
            continue
        text = qa_lines([(r["y"], r["raw"].decode("cp932")) for r in page["records"]])
        og = corpus.qa_pages.get(number)
        extra = dict(location=f"NISVDATA 块 6 第 {number} 页（{len(page['records'])} 个记录）", page=number,
                     question=questions.get(number, ""), category="攻略Q&A：正文（整页）", module="03",
                     note="正文按显示行拼接；写回时整页重新排版，颜色段落沿用原记录")
        if og:
            og_source = qa_lines([(r["position"][1], r["source"]) for r in og["records"]])
            og_zh = qa_lines([(r["position"][1], r.get("translation", "")) for r in og["records"]])
            ratio = difflib.SequenceMatcher(a=og_source.replace("\n", ""), b=text.replace("\n", ""),
                                            autojunk=False).ratio()
            extra["reference"] = dict(main_game_source=og_source, main_game_translation=og_zh,
                                      similarity=round(ratio, 3), diff=compact_diff(og_source, text),
                                      trivial=trivial_change(og_source, text))
        status = STATUS_EDIT if og and extra["reference"]["similarity"] >= 0.6 else STATUS_NEW
        rows.append(entry(f"sd/nisv/qa/page/{number:03d}", "qa_page", text, status=status, **extra))
    return rows


def squad_gaps(disc: Disc, table, corpus: Corpus) -> list[dict]:
    exe = disc.original(EXE)
    source = disc.original("DATA/NISVDATA.BIN")
    offsets = table_offsets(exe, NISV_TABLE, len(source))
    sd4, pv4 = chunk(source, offsets, 4), chunk(disc.preview("DATA/NISVDATA.BIN"), offsets, 4)
    rows = []
    for index in range(struct.unpack_from("<H", sd4, 0x20)[0]):
        a = SQUAD_BASE + index * SQUAD_STRIDE
        raw = sd4[a:a + SQUAD_NAME].split(b"\0")[0]
        if pv4[a:a + len(raw)] != raw:
            continue
        text = decode_text(raw + b"\0", 0, table).text
        if shows_as_chinese(text, decode_text(raw + b"\0", 0, READBACK).text):
            continue
        known = corpus.name(text)
        rows.append(entry(f"sd/nisv/squad/{index:03d}", "squad_name", text,
                          status=STATUS_REUSE if known else STATUS_NEW, translation=known or "",
                          location=f"NISVDATA 块 4 记录 {index}", max_bytes=SQUAD_NAME, category="小队名候选",
                          module="03"))
    return rows


def flow_key_help(disc: Disc, table, story: dict) -> list[dict]:
    """Key-help strings of the Scenario Chart (「：決定」…), found through the pointers to them."""
    flow = story["flow"]
    stage = disc.preview("DATA/STAGE.BIN")
    offsets = table_offsets(disc.original("HEDBDY/HB.BIN"), HB_STAGE_TABLE, len(stage))
    preview_flow = chunk(stage, offsets, 0)
    targets = set()
    for position in range(0, len(flow) - 3, 4):
        target = struct.unpack_from("<I", flow, position)[0] - SD_STAGE_BASE
        if FLOW_KEY_HELP[0] <= target < FLOW_KEY_HELP[1]:
            targets.add(target)
    rows = []
    for target in sorted(targets):
        text = decode_text(flow, target, table)
        if text.terminator != "nul" or not JAPANESE.search(text.text):
            continue
        if preview_flow[target:target + text.consumed] != flow[target:target + text.consumed]:
            continue
        rows.append(entry(f"sd/flow/key/{target:05X}", "ui", text.text,
                          location=f"STAGE 块 0（flow.bin）0x{target:05X}", max_bytes=text.consumed,
                          category="剧情流程：按键说明", module="03"))
    return rows


# ------------------------------------------------------------------ module builders
def vt1_pages(disc: Disc) -> dict[int, list[list[str]]]:
    exe = disc.original(EXE)
    vt1 = disc.original("DATA/VT1.BIN")
    offsets = table_offsets(exe, VT1_TABLE, len(vt1))
    pages = {}
    for index, per_entry in VT1_PAGES.items():
        lines = chunk(vt1, offsets, index).decode("cp932").split("\n")
        while lines and not lines[-1]:
            lines.pop()
        assert len(lines) % per_entry == 0, (index, len(lines))
        pages[index] = [lines[k:k + per_entry] for k in range(0, len(lines), per_entry)]
    return pages


def page_text(lines: list[str]) -> str:
    """Fixed 28-column lines -> the paragraph text (trailing full-width padding removed, breaks kept)."""
    return "\n".join(line.rstrip("\u3000") for line in lines).strip("\n")


def build_story(disc, table, corpus, story, exe_rows, cd_rows, pages) -> dict:
    files = []
    records = [r for r in story["records"] if 1 <= r["group"] <= 5 and r["chunk"] <= 29 and r["title"] != "予備"]
    episodes = collections.OrderedDict()
    for r in sorted(records, key=lambda r: (r["seq"], r["chunk"])):
        episodes.setdefault(r["seq"], []).append(r)
    group_counter = collections.Counter()
    synopsis_width = max(len(line) for item in story["synopses"] for line in item["text"].split("\n"))
    for seq, recs in episodes.items():
        head = recs[0]
        group = head["group"]
        group_counter[group] += 1
        chart = story["chart"].get(head["chunk"]) or next((story["chart"][r["chunk"]] for r in recs
                                                           if r["chunk"] in story["chart"]), None)
        chapter = chart["chapter"] if chart else ""
        prefix = f"sd/story/{head['chunk']:03d}/"
        meta = []
        title = head["title"]
        meta.append(entry(f"sd/stage-name/{head['chunk']:03d}", "episode_title", title,
                          status=STATUS_REUSE if sha256_text(title) in corpus.stage_names else STATUS_NEW,
                          translation=corpus.stage_names.get(sha256_text(title), ""),
                          location=f"COMPDATA.BN 解压 0x{head['title_offset']:05X}", max_bytes=head["title_bytes"],
                          note="同一话名也出现在 VT1 块 9 的关卡标题图和流程图话名栏"))
        if chart:
            meta.append(entry(f"sd/flow/episode/{chart['record']:02d}", "chart_title", chart["title"],
                              status=STATUS_REUSE if sha256_text(chart["title"]) in corpus.stage_names else STATUS_NEW,
                              translation=corpus.stage_names.get(sha256_text(chart["title"]), ""),
                              location=f"STAGE 块 0（flow.bin）0x{chart['offset']:05X}", max_bytes=64,
                              context=f"流程图章节标签「{chapter}」"))
        synopsis = story["synopses"][seq - 1]
        meta.append(entry(f"sd/flow/synopsis/{seq:02d}", "synopsis", synopsis["text"],
                          location=f"STAGE 块 0（flow.bin）0x{synopsis['offset']:05X}", max_bytes=synopsis["size"],
                          note=f"资料库「剧情流程 Special Disc」打开本话时显示；原文每行至多 {synopsis_width} 个全角字，按行存放"))
        chunks = []
        for r in recs:
            st = story["stages"].get(r["chunk"])
            summary = story["summaries"].get(r["chunk"])
            if summary:
                meta.append(entry(f"sd/hsfc/{summary['record']:02d}", "chart_summary", "\n".join(summary["lines"]),
                                  location=f"HSFC 块 0 记录 {summary['record']}（{r['file']}）",
                                  max_bytes=HSFC_SUMMARIES[1], note="流程图节点简介：3 行，每行一格 66 字节（约 32 个全角字）"))
            if st:
                chunks.append((r, st))
        body = dict(meta=meta, speakers=[], formations=[], conditions=[], other=[], dialogue=[])
        for r, st in chunks:
            p = f"sd/story/{r['chunk']:03d}/"
            rows = stage_rows(r["chunk"], st, corpus, p)
            for row in rows:
                row["chunk"] = r["file"]
            body["conditions"] += [x for x in rows if x["kind"] == "condition"]
            body["dialogue"] += [x for x in rows if x["kind"] != "condition"]
            body["speakers"] += speaker_rows(r["chunk"], st, corpus, p)
            body["formations"] += formation_rows(r["chunk"], st, corpus, p)
            body["other"] += residue_rows(st, corpus, p)
        body["speakers"] = dedupe(body["speakers"])
        body["formations"] = merge_formations(body["formations"])
        name = f"ep{seq:02d}-{GROUP_TAG[group]}{group_counter[group]}-{head['file'][:-4]}"
        files.append(dict(
            name=name,
            title=f"第 {seq} 话 {title}（{GROUPS[group]}·{chapter or '第' + str(group_counter[group]) + '話'}）",
            info=dict(episode=seq, group=GROUPS[group], chapter=chapter,
                      chunks=[f"{r['chunk']:03d} {r['file']}" for r in recs]),
            sections=body))

    # common: groups, intros, narration, data link, maps, image text
    common = dict(groups=[], intros=[], narration=[], datalink=[], menu=[], maps=[], images=[])
    intro = pages[40]
    common["datalink"].append(entry("sd/vt1/40/0", "vt1_page", page_text(intro[0][1:]), heading=intro[0][0].strip("\u3000"),
                                    location="VT1 块 40 第 0 段（9 行×28 全角列）", max_chars_per_line=28,
                                    note="固定格：1 行标题＋8 行正文，每行 28 个全角字；最后一行是确认问句"))
    for k in range(1, len(intro)):
        common["intros"].append(entry(f"sd/vt1/40/{k}", "vt1_page", page_text(intro[k][1:]),
                                      heading=intro[k][0].strip("\u3000"),
                                      location=f"VT1 块 40 第 {k} 段（9 行×28 全角列）", max_chars_per_line=28,
                                      note="组简介（选组画面）：1 行组名＋8 行正文，每行 28 个全角字"))
    for g, text in GROUPS.items():
        common["groups"].append(entry(f"sd/group/{g}", "group_name", text, note=f"组 {GROUP_TAG[g]}，界面多处使用（带「」或定宽补空）"))
    mt = disc.original("DATA/MTZSPROS.BIN")
    mt_offsets = table_offsets(disc.original(EXE), MTZSPROS_TABLE, len(mt))
    for k in range(len(mt_offsets) - 1):
        result = parse_summary(chunk(mt, mt_offsets, k), table, chunk_index=k)
        g, when = NARRATION_GROUP.get(k, (0, ""))
        for e_index, e in enumerate(result.entries):
            common["narration"].append(entry(f"sd/mtzspros/{k:02d}/{e_index}", "narration", e.text,
                                             location=f"MTZSPROS 块 {k}", group=GROUPS.get(g, ""),
                                             context=f"{GROUP_TAG.get(g, '')} {when}旁白（背景图 MTZSPROP）",
                                             note="全角空格与换行按原文排；本篇 MTV_PROS 同类写回器按两字节空格规则"))
    for row in exe_rows:
        if row.get("module") == "01":
            (common["datalink"] if row["category"] == "数据链接" else common["menu"]).append(row)
    for row in cd_rows:
        if row.get("module") == "01":
            common["datalink"].append(row)
    mapname = disc.original("MAP/MAPNAME.BIN")
    preview_map = disc.preview("MAP/MAPNAME.BIN")
    for index in range(MAPNAME_COUNT):
        a = index * MAPNAME_SLOT
        raw = mapname[a:a + MAPNAME_SLOT].split(b"\0")[0]
        if not raw or preview_map[a:a + len(raw)] != raw:
            continue
        text = decode_text(raw + b"\0", 0, table).text
        if text.startswith("■") or "ダミー" in text or "Ｄｕｍｍｙ" in text:
            continue
        if shows_as_chinese(text, decode_text(raw + b"\0", 0, READBACK).text):
            continue
        common["maps"].append(numbered(entry(f"sd/mapname/{index:03d}", "map_name", text,
                                             location=f"MAPNAME 槽 {index}", max_bytes=MAPNAME_SLOT,
                                             note="地图名（SD 新增）"), corpus))
    common["images"] = image_rows("01")
    return dict(files=files, common=common)


def build_challenge(disc, table, corpus, story, exe_rows, cd_rows, pages) -> dict:
    files = []
    records = [r for r in story["records"] if 39 <= r["chunk"] <= 56]
    briefings = pages[50]
    for number, r in enumerate(sorted(records, key=lambda r: r["chunk"])):
        st = story["stages"].get(r["chunk"])
        p = f"sd/challenge/{r['chunk']:03d}/"
        meta = [entry(f"sd/stage-name/{r['chunk']:03d}", "episode_title", r["title"], status=STATUS_KEEP,
                      location=f"COMPDATA.BN 解压 0x{r['title_offset']:05X}", max_bytes=r["title_bytes"],
                      note="英文任务名，同类图片（NORMAL/HARD/EX-HARD、MISSION1–6）也是英文")]
        brief = briefings[number]
        meta.append(entry(f"sd/vt1/50/{number}", "vt1_page", page_text(brief), location=f"VT1 块 50 第 {number} 段（7 行×28 全角列）",
                          max_chars_per_line=28, note="任务简报：固定 7 行，每行 28 个全角字"))
        summary = story["summaries"].get(r["chunk"])
        if summary:
            meta.append(entry(f"sd/hsfc/{summary['record']:02d}", "chart_summary", "\n".join(summary["lines"]),
                              location=f"HSFC 块 0 记录 {summary['record']}", max_bytes=HSFC_SUMMARIES[1],
                              note="流程图节点简介：3 行，每行一格 66 字节（约 32 个全角字）"))
        body = dict(meta=meta, speakers=[], formations=[], conditions=[], other=[], dialogue=[])
        if st:
            body["other"] = residue_rows(st, corpus, p)
            rows = stage_rows(r["chunk"], st, corpus, p)
            body["conditions"] = [x for x in rows if x["kind"] == "condition"]
            body["dialogue"] = [x for x in rows if x["kind"] != "condition"]
            body["speakers"] = speaker_rows(r["chunk"], st, corpus, p)
            body["formations"] = formation_rows(r["chunk"], st, corpus, p)
        diff = DIFFICULTY[r["group"]]
        files.append(dict(name=f"m{number + 1:02d}-{diff.lower()}-{r['slot']}-{r['file'][:-4]}",
                          title=f"{diff} MISSION {r['slot']}（{r['file']}）",
                          info=dict(difficulty=diff, mission=r["slot"], chunk=f"{r['chunk']:03d} {r['file']}"),
                          sections=body))
    common = dict(menu=[row for row in exe_rows if row.get("module") == "02"]
                  + [row for row in cd_rows if row.get("module") == "02"])
    return dict(files=files, common=common)


def image_rows(module: str) -> list[dict]:
    rows = []
    for m, where, what, texts, note in IMAGE_TEXT:
        if m != module:
            continue
        for k, text in enumerate(texts):
            rows.append(entry(f"sd/image/{where.split()[0].lower()}/{what}/{k}", "image_text", text, location=where,
                              category=what, note=note))
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for row in rows:
        if row["source"] in seen:
            continue
        seen.add(row["source"])
        out.append(row)
    return out


def merge_formations(rows: list[dict]) -> list[dict]:
    """Formation rows of several chunks (a/b variants): one row per name."""
    by_source = collections.OrderedDict()
    for row in rows:
        kept = by_source.get(row["source"])
        if kept is None:
            by_source[row["source"]] = dict(row)
            continue
        kept["occurrences"] = kept.get("occurrences", 1) + row.get("occurrences", 1)
        kept["max_bytes"] = min(kept["max_bytes"], row["max_bytes"])
        kept["offsets"] = kept.get("offsets", []) + row.get("offsets", [])
    return list(by_source.values())


# ------------------------------------------------------------------ writers
KIND_ZH = {"dialogue": "对白", "scene_label": "场景标签", "condition": "胜败条件", "speaker": "说话人",
           "formation_name": "编队／部队名", "episode_title": "话名", "chart_title": "流程图话名", "synopsis": "梗概",
           "chart_summary": "流程图简介", "vt1_page": "固定格文字", "narration": "旁白", "group_name": "组名",
           "ui": "界面文字", "map_name": "地图名", "image_text": "图片文字", "ticker": "滚动播报",
           "suspend_message": "中断对话", "library_field": "图鉴字段", "qa_metadata": "Q&A 元数据",
           "qa_page": "Q&A 页面", "squad_name": "小队名", "pilot_name": "驾驶员名", "stage_text": "关卡内文字", "template": "格式条目"}


def md_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_cell(text: str) -> str:
    return md_escape(text).replace("|", "\\|").replace("\n", "<br>")


def quote(text: str) -> str:
    return "\n".join("> " + (md_escape(line) if line else "") for line in text.split("\n"))


def stats(rows: list[dict]) -> dict:
    by = collections.Counter(r["status"] for r in rows)
    chars = collections.Counter()
    for r in rows:
        chars[r["status"]] += r["chars"]
    return dict(entries=len(rows), by_status=dict(by), chars_by_status=dict(chars),
                new_unique=len({r["source"] for r in rows if r["status"] == STATUS_NEW}),
                new_unique_chars=sum(visible(t) for t in {r["source"] for r in rows if r["status"] == STATUS_NEW}))


def all_rows(sections: dict) -> list[dict]:
    return [r for rows in sections.values() for r in rows]


def row_md(r: dict) -> str:
    """A generic block for one entry."""
    head = f"`{r['id']}` · {KIND_ZH.get(r['kind'], r['kind'])} · **{r['status']}**"
    bits = []
    for key, label in (("location", "位置"), ("max_bytes", "容量"), ("category", "类别"), ("context", "场合")):
        if r.get(key) is not None and key != "category":
            value = f"{r[key]} 字节（含结尾 0）" if key == "max_bytes" else r[key]
            bits.append(f"{label}：{md_escape(str(value))}")
    if r.get("heading"):
        bits.append(f"标题行：{md_escape(r['heading'])}")
    lines = [head + ("  \n" + " · ".join(bits) if bits else ""), "", quote(r["source"])]
    if r.get("translation"):
        lines += ["", "译文：", "", quote(r["translation"])]
    for alt in r.get("alternatives", []):
        lines += ["", "另一种译法：", "", quote(alt)]
    ref = r.get("reference")
    if ref:
        if ref.get("main_game_translation") and ref["main_game_translation"] != r.get("translation"):
            label = f"主篇同一处的译文（相似度 {ref['similarity']}）" if "similarity" in ref else "主篇同一处的译文"
            lines += ["", label + "：", "", quote(ref["main_game_translation"])]
        lines += ["", "SD 相对主篇的改动（忽略换行；[-删-]{+增+}）：", "", quote(ref["diff"])]
    if r.get("note"):
        lines += ["", f"说明：{md_escape(r['note'])}"]
    return "\n".join(lines)


def table_md(rows: list[dict], columns=("id", "source", "status", "translation", "max_bytes", "note")) -> str:
    header = {"id": "ID", "source": "日文", "status": "状态", "translation": "译文／候选", "max_bytes": "容量(字节)",
              "note": "说明", "category": "类别", "speaker": "说话人", "location": "位置", "context": "场合"}
    out = ["| " + " | ".join(header[c] for c in columns) + " |", "|" + "---|" * len(columns)]
    for r in rows:
        cells = []
        for c in columns:
            value = r.get(c, "")
            if c == "id":
                value = f"`{value}`"
                cells.append(value)
                continue
            if c == "translation" and r.get("alternatives"):
                value = " ／ ".join([r.get("translation", "")] + r["alternatives"])
            cells.append(md_cell(str(value)) if value != "" else "")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def dialogue_md(rows: list[dict]) -> str:
    out, section, chunk_name, last_label = [], None, None, None
    for r in rows:
        if r.get("chunk") != chunk_name and r.get("chunk"):
            chunk_name = r["chunk"]
            out += [f"### {chunk_name}", ""]
            section = None
        if r.get("section") != section:
            section = r.get("section")
            out += [f"#### {section}", ""]
        rid = r["id"].rsplit("/", 2)
        tag = "/".join(rid[-2:])
        if r["kind"] == "scene_label":
            if last_label == (section, r["source"]):
                continue  # each scene label is stored three times in a row
            last_label = (section, r["source"])
            out.append(f"`{tag}` 〔场景标签〕 **{md_escape(r['source'])}**" + (f" → {md_escape(r['translation'])}"
                                                                              if r.get("translation") else ""))
            out.append("")
            continue
        last_label = None
        speaker = r.get("speaker", "")
        zh = f"（{r['speaker_zh']}）" if r.get("speaker_zh") else ""
        out.append(f"`{tag}` **{md_escape(speaker) or '（无说话人）'}**{md_escape(zh)}" +
                   ("　✔ 可复用" if r["status"] == STATUS_REUSE else ""))
        out.append(quote(r["source"]))
        if r.get("translation"):
            out.append(">")
            out.append(quote("→ " + r["translation"]).replace("> → ", "> → ", 1))
        out.append("")
    return "\n".join(out)


def write_episode(folder: Path, module: str, f: dict) -> dict:
    s = f["sections"]
    rows = all_rows(s)
    doc = dict(module=module, file=f["name"], title=f["title"], info=f["info"], generated=TODAY,
               summary=stats(rows), sections=s)
    (folder / f"{f['name']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    st = doc["summary"]
    md = [f"# {md_escape(f['title'])}", "",
          f"条目 {st['entries']}；需新译 {st['by_status'].get(STATUS_NEW, 0)} 条（唯一 {st['new_unique']} 条、"
          f"{st['new_unique_chars']} 字）；可复用 {st['by_status'].get(STATUS_REUSE, 0)} 条。", "",
          "数据块：" + "、".join(f"`{c}`" for c in (f["info"].get("chunks") or [f["info"].get("chunk")])), ""]
    md += ["## 话名、简介", ""] + [row_md(r) + "\n" for r in s["meta"]]
    if s["conditions"]:
        md += ["## 胜败条件", "", table_md(s["conditions"], ("id", "source", "status", "translation")), ""]
    if s["speakers"]:
        md += ["## 说话人", "", table_md(s["speakers"], ("source", "status", "translation")), ""]
    if s["formations"]:
        md += ["## 编队／部队名（静态扫描，近似）", "",
               table_md(s["formations"], ("source", "status", "translation", "max_bytes")), ""]
    if s.get("other"):
        md += ["## 其他文字（用途待确认）", "", table_md(s["other"], ("source", "status", "translation", "max_bytes", "location")), ""]
    if s["dialogue"]:
        md += ["## 对白", "", "按数据中的段顺序排列（不一定是游戏内播放顺序）。✔ 表示主篇已有同一原文的译文。", "",
               dialogue_md(s["dialogue"])]
    (folder / f"{f['name']}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return dict(file=f["name"], title=f["title"], **st)


def write_common(folder: Path, module: str, name: str, title: str, sections: dict, intro: str,
                 section_titles: dict) -> dict:
    rows = all_rows(sections)
    doc = dict(module=module, file=name, title=title, generated=TODAY, summary=stats(rows), sections=sections)
    (folder / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = [f"# {title}", "", intro, ""]
    for key, rows_ in sections.items():
        if not rows_:
            continue
        md += [f"## {section_titles.get(key, key)}（{len(rows_)} 条）", ""]
        short = [r for r in rows_ if len(r["source"]) <= 40 and "\n" not in r["source"] and not r.get("reference")]
        long = [r for r in rows_ if r not in short]
        if short:
            cols = ["id", "source", "status", "translation", "max_bytes", "note"]
            if len({r.get("category") for r in short}) > 1:
                cols.insert(1, "category")
            if any(r.get("speaker") for r in short):
                cols.insert(1, "speaker")
            if any(r.get("context") for r in short):
                cols.insert(-1, "context")
            md += [table_md(short, tuple(cols)), ""]
        md += [row_md(r) + "\n" for r in long]
    (folder / f"{name}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return dict(file=name, title=title, **doc["summary"])


def write_csv(folder: Path, module_rows: list[tuple[str, dict]]) -> None:
    columns = ["file", "section", "id", "kind", "status", "speaker", "source", "translation", "alternatives",
               "reference_source", "reference_translation", "max_bytes", "max_chars_per_line", "location", "category",
               "note"]
    with (folder / "all-entries.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for file_name, sections in module_rows:
            for section, rows in sections.items():
                for r in rows:
                    ref = r.get("reference") or {}
                    writer.writerow([file_name, section, r["id"], KIND_ZH.get(r["kind"], r["kind"]), r["status"],
                                     r.get("speaker", ""), r["source"], r.get("translation", ""),
                                     " ／ ".join(r.get("alternatives", [])), ref.get("main_game_source", ""),
                                     ref.get("main_game_translation", ""), r.get("max_bytes", ""),
                                     r.get("max_chars_per_line", ""), r.get("location", ""), r.get("category", ""),
                                     r.get("note", "")])


def index_md(title: str, intro: str, files: list[dict]) -> str:
    lines = [f"# {title}", "", intro, "",
             "| 文件 | 内容 | 条目 | 需新译（条／唯一字数） | 改稿·待选定 | 已有译文·可套用 | 保留 |",
             "|---|---|---|---|---|---|---|"]
    for f in files:
        by = f["by_status"]
        edit = by.get(STATUS_EDIT, 0) + by.get(STATUS_CHOOSE, 0)
        done = by.get(STATUS_REUSE, 0) + by.get(STATUS_TEMPLATE, 0) + by.get(STATUS_PENDING_WRITE, 0)
        lines.append(f"| [{f['file']}]({f['file']}.md) | {md_cell(f['title'])} | {f['entries']} | "
                     f"{by.get(STATUS_NEW, 0)}／{f['new_unique_chars']} | {edit or ''} | {done or ''} | "
                     f"{by.get(STATUS_KEEP, 0) or ''} |")
    return "\n".join(lines) + "\n"


def by_category(rows: list[dict]) -> dict:
    out = collections.OrderedDict()
    for r in sorted(rows, key=lambda r: (r.get("category", ""), r["id"])):
        out.setdefault(r.get("category") or "其他", []).append(r)
    return out


# ------------------------------------------------------------------ main
def main() -> None:
    disc = Disc()
    table = load_text_table(mc.TABLE)
    global READBACK
    _t, _menu, _story, readback = mst.encoding_tables()
    READBACK = readback
    corpus = Corpus(table)
    story = stage_data(disc, table, corpus)
    pages = vt1_pages(disc)
    cd = compdata_leftovers(disc, table, readback, corpus)  # first: its answers name units for the others
    exe = exe_leftovers(disc, table, readback, corpus)
    suspend = suspend_leftovers(disc, table, corpus)

    if OUT.exists():
        for path in sorted(OUT.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
    OUT.mkdir(parents=True, exist_ok=True)
    overview = []

    # 01 story
    folder = OUT / "01-剧情模式"
    folder.mkdir()
    data = build_story(disc, table, corpus, story, exe["rows"], cd["rows"], pages)
    listing, csv_rows = [], []
    common_titles = dict(groups="组名", intros="组简介（VT1 块 40）", narration="开场／结尾旁白（MTZSPROS）",
                         datalink="数据链接", menu="剧情模式菜单文字（主程序）", maps="新地图名", images="图片文字（待绘制）")
    listing.append(write_common(folder, "01", "00-通用", "剧情模式·通用文字", data["common"],
                                "组名、组简介、开场与结尾旁白、数据链接、剧情模式菜单、新地图名和需要绘制的图片文字。", common_titles))
    csv_rows.append(("00-通用", data["common"]))
    for f in data["files"]:
        listing.append(write_episode(folder, "01", f))
        csv_rows.append((f["name"], f["sections"]))
    write_csv(folder, csv_rows)
    (folder / "README.md").write_text(index_md(
        "01 剧情模式", "21 话，按话号排列（同一话的 a/b 分支和 006/006b 合在一个文件）。每个文件含话名、梗概、流程图简介、"
        "胜败条件、说话人、编队名和全部对白；已有主篇译文的句子标为“可复用”并附译文。", listing), encoding="utf-8")
    overview.append(("01 剧情模式", "01-剧情模式", listing, csv_rows))

    # 02 challenge
    folder = OUT / "02-挑战模式"
    folder.mkdir()
    data = build_challenge(disc, table, corpus, story, exe["rows"], cd["rows"], pages)
    listing, csv_rows = [], []
    listing.append(write_common(folder, "02", "00-通用", "挑战模式·通用文字", data["common"],
                                "任务目标、开放条件、结算项目和挑战确认。", dict(menu="界面文字")))
    csv_rows.append(("00-通用", data["common"]))
    for f in data["files"]:
        listing.append(write_episode(folder, "02", f))
        csv_rows.append((f["name"], f["sections"]))
    write_csv(folder, csv_rows)
    (folder / "README.md").write_text(index_md(
        "02 挑战模式", "NORMAL／HARD／EX-HARD 各 6 关，共 18 关。每关含任务简报（VT1 块 50）、流程图简介、胜败条件、说话人、"
        "编队名和对白。", listing), encoding="utf-8")
    overview.append(("02 挑战模式", "02-挑战模式", listing, csv_rows))

    # 03 library
    folder = OUT / "03-资料库补漏"
    folder.mkdir()
    listing, csv_rows = [], []
    zkn = library_gaps(disc, table, corpus)
    for label in ("robot", "character", "keyword"):
        rows = [r for r in zkn if r["id"].startswith(f"sd/library/{label}/")]
        sections = {"fields": rows}
        name = f"{['robot', 'character', 'keyword'].index(label) + 1:02d}-{ZKN_KIND[label]}"
        listing.append(write_common(folder, "03", name, f"资料库·{ZKN_KIND[label]}（迁移后仍是日文的字段）", sections,
                                    "“改稿”表示 SD 改动了主篇已有的文字：附主篇译文和改动处，照改译文即可；“可复用”是只改了换行、空格或「・」的字段。"
                                    "“新译”是 SD 新增的条目或字段。", dict(fields="字段")))
        csv_rows.append((name, sections))
    qa = qa_gaps(disc, table, corpus)
    sections = dict(metadata=[r for r in qa if r["kind"] == "qa_metadata"],
                    pages=[r for r in qa if r["kind"] == "qa_page"])
    listing.append(write_common(folder, "03", "04-攻略QA", "资料库·攻略 Q&A（SD 改过的 22 页与元数据）", sections,
                                "这些页 SD 改过（或是 SD 新增说明），迁移时整页保留了日文。每页附主篇同一页的中文和"
                                "SD 的改动处（按显示行拼接，忽略换行）；相似度低的页按新译处理。",
                                dict(metadata="问题标题与概要", pages="页面正文（整页）")))
    csv_rows.append(("04-攻略QA", sections))
    other = dict(squads=squad_gaps(disc, table, corpus), keys=flow_key_help(disc, table, story),
                 units=[r for r in cd["rows"] if r.get("module") == "03" and r["kind"] != "pilot_name"],
                 pilots=[r for r in cd["rows"] if r["kind"] == "pilot_name"])
    listing.append(write_common(folder, "03", "05-名称与按键", "资料库·小队名、流程图按键说明、机体／驾驶员名", other,
                                "机体名与驾驶员名来自 COMPDATA，资料库列表、战斗与战斗鉴赏共用。",
                                dict(squads="小队名候选（NISVDATA 块 4）", keys="剧情流程按键说明（flow.bin）",
                                     units="机体名（COMPDATA）", pilots="驾驶员名（COMPDATA）")))
    csv_rows.append(("05-名称与按键", other))
    write_csv(folder, csv_rows)
    (folder / "README.md").write_text(index_md(
        "03 资料库补漏", "迁移后资料库里仍显示日文的部分。SD 的剧情流程文字（梗概、流程图简介）随各话放在 01／02 模块。", listing),
        encoding="utf-8")
    overview.append(("03 资料库补漏", "03-资料库补漏", listing, csv_rows))

    # 04 broadcasts
    folder = OUT / "04-系统播报"
    folder.mkdir()
    listing, csv_rows = [], []
    ticker_rows, seen = [], {}
    preview_stage = disc.preview("DATA/STAGE.BIN")
    stage_offsets = table_offsets(disc.original("HEDBDY/HB.BIN"), HB_STAGE_TABLE, len(preview_stage))
    for index, st in sorted(story["stages"].items()):
        written = chunk(preview_stage, stage_offsets, index) if st["tickers"] else b""
        for offset, text in st["tickers"]:
            if decode_text(written, offset, table).text != text:
                continue  # the preview already carries the Chinese ticker
            where = f"{story['names'][index]}（块 {index}）"
            if text in seen:
                seen[text]["context"] += f"、{where}"
                continue
            known = corpus.tickers.get(text)
            row = entry(f"sd/ticker/{sha256_text(text)[:12]}", "ticker", text,
                        status=STATUS_REUSE if known else STATUS_NEW, translation=known or "",
                        max_bytes=140, context=where, location=f"STAGE 块 {index} 0x{offset:05X} 起的 140 字节槽")
            seen[text] = row
            ticker_rows.append(row)
    z_reports = sum(z_report_records(data) for data in story["decoded"])
    leftovers = [(index, text) for index, st in sorted(story["stages"].items()) if 1 <= index <= 56
                 for _offset, text, _size in st["residue"]]
    sections = dict(z_report=[], tickers=ticker_rows,
                    notices=[r for r in exe["rows"] if r.get("module") == "04"])
    listing.append(write_common(folder, "04", "01-系统播报", "系统播报", sections,
                                f"**Z Report（系统播报记录）：SD 中没有。** 按本篇的记录特征（0x00000006, 0xFFFFFFFF, 0xFFFFFFFF, "
                                f"指向本块的指针）扫描 SD 全部 {len(story['decoded'])} 个 STAGE 块，命中 {z_reports} 条。"
                                f"另把剧情与挑战各块中被指针引用、但不属于对白、条件、说话人、滚动播报、编队名的日文字符串全部列出，"
                                f"共 {len(leftovers)} 条（"
                                + "、".join(f"{story['names'][i]}「{md_escape(t)}」" for i, t in leftovers)
                                + "），已放进对应关卡文件的“其他文字”，其中没有“武装追加”“PP＋”一类的系统通知。\n\n"
                                "本模块因此收录两类最接近的文字：中场画面底部的滚动播报（ticker），以及游戏中弹出的系统通知。",
                                dict(z_report="Z Report", tickers="滚动播报（中场画面底部）", notices="弹出通知（主程序）")))
    csv_rows.append(("01-系统播报", sections))
    write_csv(folder, csv_rows)
    (folder / "README.md").write_text(index_md("04 系统播报", "SD 没有 Z Report 记录，详见文件内说明。", listing),
                                      encoding="utf-8")
    overview.append(("04 系统播报", "04-系统播报", listing, csv_rows))

    # 05 system text
    folder = OUT / "05-系统说明文字"
    folder.mkdir()
    listing, csv_rows = [], []
    ui = [r for r in exe["rows"] if r.get("module") == "05"]
    groups = [
        ("01-特别剧场", "特别剧场：菜单、说明、标题与列表", lambda r: r["category"].startswith("特别剧场")),
        ("02-战斗鉴赏", "战斗鉴赏：界面、帮助与列表", lambda r: r["category"].startswith("战斗鉴赏")),
        ("03-界面与帮助", "通用界面、帮助说明、存档与额外关卡菜单", lambda r: True),
    ]
    remaining = ui + [r for r in cd["rows"] if r.get("module") == "05"]
    for name, title, test in groups:
        picked = [r for r in remaining if test(r)]
        remaining = [r for r in remaining if not test(r)]
        sections = by_category(picked)
        listing.append(write_common(folder, "05", name, title, sections,
                                    "“容量”是原文所占字节（含结尾 0），中文每字 2 字节；超出时需要另行扩容或改写。"
                                    "“待选定”表示主篇有译文但未能自动迁移（多种译法或放不下）。", {}))
        csv_rows.append((name, sections))
    sections = dict(pending=suspend)
    listing.append(write_common(folder, "05", "04-中断对话-待写入", "特别剧场·中断对话（已有译文，预览镜像尚未写入）",
                                sections, "这些中断对话在本篇语料中都有定稿译文，但迁移脚本只处理了主程序 0x3B8BE0–0x3BC000，"
                                "0x3BC000–0x3BE700 这一段没有写入。无需翻译，列出以便核对。", dict(pending="待写入")))
    csv_rows.append(("04-中断对话-待写入", sections))
    sections = dict(images=image_rows("05"))
    listing.append(write_common(folder, "05", "05-图片文字", "需要绘制的图片文字", sections,
                                "程序绘制前需要定下的中文；位置和做法见 docs/SPECIAL_DISC_PLAN.md §2.2。", dict(images="图片文字")))
    csv_rows.append(("05-图片文字", sections))
    write_csv(folder, csv_rows)
    (folder / "README.md").write_text(index_md(
        "05 系统说明文字", "主程序与 COMPDATA 中迁移后仍是日文的界面、帮助和说明文字，以及待写入的中断对话和待绘制的图片文字。",
        listing), encoding="utf-8")
    overview.append(("05 系统说明文字", "05-系统说明文字", listing, csv_rows))

    # README
    skipped = dict(executable=dict(exe["skipped"]), compdata=dict(cd["skipped"]))
    lines = ["# Special Disc 文本分模块导出", "",
             f"{TODAY} 生成。原盘 `{ISO.name}`（Redump 40639），脚本 `export_sd_text.py`。只读导出，未改语料、配置或镜像。", "",
             "状态说明：", "",
             f"- **{STATUS_NEW}**：主篇没有同一原文的译文，需要翻译。",
             f"- **{STATUS_REUSE}**：主篇语料有同一原文（按 sha256 比对）的定稿译文，已填入。",
             f"- **{STATUS_EDIT}**：SD 改动了主篇已有文字，附主篇译文和改动处（主篇原文全文在 JSON 的 reference 字段）。",
             f"- **{STATUS_CHOOSE}**：主篇有译文但不止一种或放不下，迁移时未写入，请选定。",
             f"- **{STATUS_TEMPLATE}**：「名称（n）」一类的编号条目，名称部分已有译名，按编号套用。",
             f"- **{STATUS_PENDING_WRITE}**：已有译文，只是预览镜像还没写入。",
             f"- **{STATUS_KEEP}**：英文或占位文字，按惯例保留。", "",
             "“唯一字数”按去掉换行和控制符后的可见日文字符计，同一模块内同一原文只算一次。每个模块目录另有 "
             "`all-entries.csv`（UTF-8 BOM，可直接用 Excel 打开）；JSON 是完整记录（位置、容量、参考原文等）。", "",
             "“容量”是原文在数据里占的字节（含结尾 0），中文每字 2 字节、半角字母数字 1 字节；剧情对白按整关重排，没有逐句上限。", "",
             "| 模块 | 文件数 | 条目 | 需新译条目 | 需新译唯一字数 | 改稿·待选定 | 已有译文·可套用 | 保留 |",
             "|---|---|---|---|---|---|---|---|"]
    for title, folder_name, files, module_rows in overview:
        rows = [r for _name, sections in module_rows for r in all_rows(sections)]
        by = collections.Counter(r["status"] for r in rows)
        chars = sum(visible(t) for t in {r["source"] for r in rows if r["status"] == STATUS_NEW})
        lines.append(f"| [{title}]({folder_name}/README.md) | {len(files)} | {len(rows)} | {by[STATUS_NEW]} | {chars} | "
                     f"{by[STATUS_EDIT] + by[STATUS_CHOOSE]} | "
                     f"{by[STATUS_REUSE] + by[STATUS_TEMPLATE] + by[STATUS_PENDING_WRITE]} | {by[STATUS_KEEP]} |")
    lines += ["", "## 说明", ""]
    if suspend:
        lines.append(f"- 特别剧场中断对话有 {len(suspend)} 条仍是日文（主篇语料都有定稿译文），列在 05 模块 `04-中断对话-待写入`。")
    lines += ["- SD 的 STAGE 中没有 Z Report 记录，04 模块收滚动播报与弹出通知，理由见该模块说明。",
              "- 已写入预览镜像的系统文字（模块 04／05）以 `corpus/zh/special-disc/system-text.json` 为准，"
              "写回脚本 `tools/special_disc/writeback/write_system_text.py`。", ""]
    lines += ["## 未导出的部分", "",
              "- 本篇也保持日文的字符串（开发用错误信息、`陸`→`陆` 这类字形相同或本篇就不改的文字）、占位符、"
              "COMPDATA 中推测不显示的片假名排序键，以及预览镜像中已经是中文的文字。",
              "- 战斗字幕 SRVC 中 SD 独有的 123 句、COMPDATA 撤退台词中的新句（后者在 05 模块“撤退台词”类别内）。",
              "- 制作人员名单、设定资料图上的说明文字（按既定范围不处理）。", "",
              "跳过计数：", "", "```json", json.dumps(skipped, ensure_ascii=False, indent=1), "```", "",
              "输入：", ""]
    for member, path in PREVIEW.items():
        lines.append(f"- 预览组件 `{path}`（{member}）sha256 `{sha256((ROOT / path).read_bytes())[:16]}…`")
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((OUT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
