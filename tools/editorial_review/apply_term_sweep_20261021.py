#!/usr/bin/env python3
"""Apply the 2026-10-21 term-consistency decisions to the main-game corpus.

Source of the decisions: ``work/review/term-sweep-20261021/README.md`` (§一
clear slips, §二 the user's 23 choices on the decision page).  Each rule binds
to the Japanese source (so 木星船団 or リンクス never match by accident),
rewrites the Chinese wording, and the writer then re-fits story dialogue to
the 21x3 layout, keeps battle lines' literal ``\\n`` breaks, leaves stage
overviews line-for-line (their widths are checked by the builder) and lets
the library builder reflow library bodies.  The library override layer
(``config/library/v0.2-editorial-overrides.json``) receives the same rules.
Special Disc files are not touched (frozen snapshot contract); world-map
titles are textures and are listed as follow-ups instead.

    python3 tools/editorial_review/apply_term_sweep_20261021.py --dry-run
    python3 tools/editorial_review/apply_term_sweep_20261021.py
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/editorial_review"))

from rebalance_story_dialogue import source_dialogue_index  # noqa: E402
from srwz.chinese_layout import dialogue_layout_issues, fit_chinese_dialogue_layout, load_layout_profiles  # noqa: E402
from unify_same_source_dialogue import EDITORIAL_DIR, PROFILES_PATH  # noqa: E402

BATCH_ID = "term-sweep-20261021"
JP_BY_SHA = PROJECT_ROOT / "work/review/term-sweep-20261021/jp-by-sha.json"
LIBRARY_OVERRIDES = PROJECT_ROOT / "config/library/v0.2-editorial-overrides.json"
KANA_RUN = re.compile(r"[ァ-ヺー・]+")
OC = "<width:0E><space:0C>Overcoat<width:16><space:16>"


def kana_run_has(jp: str, term: str) -> bool:
    return any(run == term or term in run.split("・") for run in KANA_RUN.findall(jp))


# (group, japanese condition, [(pattern, replacement)], excluded record ids)
RULES = [
    ("1 塞文堡", lambda jp: "フォートセバーン" in jp, [("福特\n　塞班", "塞文堡"), ("福特塞班", "塞文堡"), ("福特塞文", "塞文堡"), ("塞瓦堡", "塞文堡")], ()),
    ("1 北阿美利亚", lambda jp: "北アメリア" in jp, [("北亚美利加", "北阿美利亚"), ("北美利亚", "北阿美利亚"), ("北美洲", "北阿美利亚"), (re.compile(r"北美(?!利)"), "北阿美利亚")], ()),
    ("1 飞・心露", lambda jp: "フェイ・シンルー" in jp, [("飞·辛路", "飞・心露")], ()),
    ("1 运行图", lambda jp: "ダイヤ" in jp, [("时刻表", "运行图")], ()),
    ("1 亚历克斯·迪诺", lambda jp: "アレックス・ディノ" in jp, [(re.compile(r"亚历克斯(?!·迪诺)"), "亚历克斯·迪诺")], ()),
    ("1 西罗克", lambda jp: "シロッコ" in jp, [("西洛克", "西罗克")], ()),
    ("1 高安", lambda jp: "グエン" in jp, [("古恩", "高安")], ()),
    ("1 太阳号", lambda jp: "ソレイユ" in jp, [("苏蕾尤", "太阳号")], ()),
    ("1 布隆科II", lambda jp: "ブロンコⅡ" in jp, [(re.compile(r"野\n?马\n?II"), "布隆科II")], ()),
    ("1 UN空间站", lambda jp: "ＵＮステーション" in jp, [(re.compile(r"UN站(?!点|空)"), "UN空间站")], ()),
    ("1 上尉", lambda jp: "大尉" in jp, [("大尉", "上尉")], ()),
    ("1 罗多尼亚", lambda jp: "ロドニア" in jp, [("罗德尼亚", "罗多尼亚")], ("world-map/title/134",)),
    ("1 林斯", lambda jp: kana_run_has(jp, "リンス"), [("林克斯", "林斯")], ("library-text/19218238baa0b696",)),
    ("1 钱德拉", lambda jp: "チャンドラ" in jp, [("钱德勒", "钱德拉")], ()),
    ("1 阿加托结晶", lambda jp: "アガト" in jp, [("阿加特的结晶", "阿加托结晶"), ("阿加特结晶", "阿加托结晶")], ()),
    ("2-1 淤能碁吕岛", lambda jp: "オノゴロ" in jp, [("奥诺戈罗岛", "淤能碁吕岛"), ("小野木岛", "淤能碁吕岛")], ()),
    ("2-2 Overcoat", lambda jp: "オーバーコート" in jp and "《" not in jp, [("隐形外套", "透明化的" + OC), ("超能外套", OC), (re.compile(r"(?<!覆)外套"), OC)], ()),
    ("2-3 多兰", lambda jp: kana_run_has(jp, "ドラン"), [("德兰", "多兰")], ()),
    ("2-4 雅邦忍法", lambda jp: "ヤーパンニンポー" in jp, [("日本忍法", "雅邦忍法")], ()),
    ("2-5 超限人对战", lambda jp: "オーバーマンバトル" in jp, [("超限人战斗", "超限人对战")], ()),
    ("2-6 朱庇特利斯", lambda jp: "ジュピトリス" in jp, [(re.compile(r"木星船(?!团|団)"), "朱庇特利斯"), (re.compile(r"朱庇\n?特里斯"), "朱庇特利斯")], ()),
    ("2-7 丑女二人组", lambda jp: "ブスペア" in jp, [("丑女搭档", "丑女二人组")], ()),
    ("2-8 大便部长", lambda jp: "ウンコ" in jp, [("混蛋部长", "大便部长")], ()),
    ("2-9 黑箱", lambda jp: "ブラックボックス" in jp, [("黑匣子", "黑箱")], ()),
    ("2-10 试飞员", lambda jp: "テストパイロット" in jp, [("测试\n　驾驶员", "试飞员"), ("测试驾驶员", "试飞员")], ()),
    ("2-11 驾驶服", lambda jp: "パイロットスーツ" in jp, [("驾驶员服", "驾驶服")], ()),
    ("2-12 锦旗", lambda jp: "ペナント" in jp, [("三角旗", "锦旗")], ()),
    ("2-13 记忆卡", lambda jp: "メモリーカード" in jp, [("存储卡", "记忆卡")], ()),
    ("2-14 中断保存", lambda jp: "途中セーブ" in jp, [("中途存档", "中断保存")], ()),
    ("2-15 快速读档", lambda jp: "クイックスタート" in jp, [("快速开始", "快速读档")], ()),
    ("2-16 均衡方案", lambda jp: "バランスオーダー" in jp, [("平衡指令", "均衡方案")], ()),
    ("2-17 完全抗性", lambda jp: "オールキャンセラー" in jp, [("全取消器", "完全抗性")], ()),
    ("2-18 气力上限突破", lambda jp: "気力限界突破" in jp, [("气力限界突破", "气力上限突破")], ()),
    ("2-19 弹数", lambda jp: "弾数" in jp, [("弹药数", "弹数")], ()),
    ("2-20 第7次", lambda jp: "第７次宇宙戦争" in jp, [("第七次宇宙战争", "第7次宇宙战争")], ()),
    ("2-22 盖塔形态", lambda jp: re.search(r"(?<!ゲッター)(ドラゴン|ライガー|ポセイドン)(?!号|ミサイル)", jp) is not None,
     [(re.compile(r"(?<![盖塔龙骑])龙(?![号马骑])"), "盖塔龙"), (re.compile(r"(?<!盖塔)狮虎(?![号导])"), "盖塔狮虎"), (re.compile(r"(?<!盖塔)波塞冬(?!号)"), "盖塔波塞冬")], ()),
]

GLOSSARY_EDITS = {
    "corpus/glossary/terms-v1.json": {
        "update": {"event/seventh-space-war": {"translation": "第7次宇宙战争", "deprecated_translations": ["第七次宇宙战争"], "status": "approved", "notes": "《机动新世纪高达X》设定。2026-10-21 用户定稿用阿拉伯数字“第7次”，与图鉴数字写法一致。"}},
        "add": [
            {"id": "place/onogoro-island", "source_terms": ["オノゴロ島", "オノゴロ"], "translation": "淤能碁吕岛", "deprecated_translations": ["奥诺戈罗岛", "小野木岛"], "variant_scope": "source_bound", "category": "place", "status": "approved", "domains": ["story", "battle", "library", "menu", "summary"], "enforce": True, "notes": "《机动战士高达SEED DESTINY》奥布的本岛。2026-10-21 用户定稿采用神话原典写法“淤能碁吕岛”。"},
            {"id": "place/heavens-base", "source_terms": ["ヘブンズベース"], "translation": "天堂基地", "deprecated_translations": ["赫文斯基地"], "variant_scope": "source_bound", "category": "place", "status": "approved", "domains": ["story", "battle", "library", "menu", "summary"], "enforce": True, "notes": "《机动战士高达SEED DESTINY》地球联合在冰岛的基地。2026-10-21 用户指出兰德线 4 句音译为“赫文斯基地”，统一为“天堂基地”。"},
        ],
    },
    "corpus/glossary/global-variants-v1.json": {
        "update": {"group/busu-pair": {"translation": "丑女二人组", "deprecated_translations": ["丑女搭档", "布斯佩亚", "武斯佩亚", "胜平队"], "notes": "《无敌超人赞波特3》中胜平给亚纪和美知起的损人绰号。2026-10-21 用户定稿为对白通行的“丑女二人组”。"}},
        "add": [],
    },
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _inline_lists(value, level: int) -> str:
    """indent=2 objects whose scalar lists stay on one line (glossary style)."""

    pad = "  " * level
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{pad}  {json.dumps(k, ensure_ascii=False)}: {_inline_lists(v, level + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list):
        if value and all(not isinstance(v, (dict, list)) for v in value):
            return json.dumps(value, ensure_ascii=False)
        if not value:
            return "[]"
        items = [f"{pad}  {_inline_lists(v, level + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def _compact_entries(document, key: str) -> str:
    """indent=2 skeleton with each entry object compact on one line (menu/glossary style)."""

    head = dict(document)
    entries = head.pop(key)
    skeleton = json.dumps(head, ensure_ascii=False, indent=2)
    body = ",\n".join("    " + json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in entries)
    return skeleton[:-2] + f",\n  {json.dumps(key)}: [\n{body}\n  ]\n}}\n"


def edit_glossary_text(text: str, edits: dict, relative: str) -> tuple[str, list[dict]]:
    """Surgical edits on a hand-formatted glossary file: replace whole term objects in place, append new ones."""

    decoder = json.JSONDecoder()
    log = []
    for term_id, fields in edits["update"].items():
        match = re.search(r'"id":\s*"' + re.escape(term_id) + '"', text)
        if not match:
            raise SystemExit(f"{relative}: term {term_id} not found")
        start = text.rfind("{", 0, match.start())
        obj, length = decoder.raw_decode(text[start:])
        before = dict(obj)
        obj.update(fields)
        compact = "\n" not in text[start : start + length]
        rendered = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else _inline_lists(obj, 2)
        text = text[:start] + rendered + text[start + length :]
        log.append({"file": relative, "id": term_id, "before": before, "after": obj})
    existing_ids = {t["id"] for t in json.loads(text)["terms"]}
    for term in edits["add"]:
        if term["id"] in existing_ids:
            continue
        close = text.rstrip().rfind("]")
        text = text[:close].rstrip() + ",\n    " + _inline_lists(term, 2) + "\n  " + text[close:]
        log.append({"file": relative, "id": term["id"], "before": None, "after": term})
    return text, log


def serializer_for(raw: bytes, document):
    """Return a dumper that reproduces ``raw`` byte for byte, or None."""

    candidates = [dump]
    for key in ("entries", "terms"):
        if isinstance(document, dict) and isinstance(document.get(key), list):
            candidates.append(lambda d, k=key: _compact_entries(d, k))
    candidates.append(lambda d: _inline_lists(d, 0) + "\n")
    for candidate in candidates:
        try:
            if candidate(document).encode("utf-8") == raw:
                return candidate
        except Exception:  # noqa: BLE001 - a style that cannot encode this file is simply not its style
            continue
    return None


def scan(doc):
    if isinstance(doc, dict):
        if ("translation" in doc) and ("source_text_sha256" in doc or "source_text" in doc or "source" in doc):
            yield doc
            return
        for value in doc.values():
            yield from scan(value)
    elif isinstance(doc, list):
        for value in doc:
            yield from scan(value)


def apply_rules(jp: str, zh: str, entry_id: str) -> tuple[str, list[str]]:
    groups = []
    for group, condition, subs, excluded in RULES:
        if entry_id in excluded or not condition(jp):
            continue
        new = zh
        for pattern, replacement in subs:
            new = pattern.sub(replacement, new) if hasattr(pattern, "sub") else new.replace(pattern, replacement)
        if new != zh:
            zh = new
            groups.append(group)
    return zh, groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    japanese = json.loads(JP_BY_SHA.read_text(encoding="utf-8"))
    by_sha, by_id = japanese["by_sha"], japanese["by_id"]
    source_index = source_dialogue_index()
    profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]

    changes, skipped, touched = [], [], {}
    paths = sorted(glob.glob(str(PROJECT_ROOT / "corpus/zh/**/*.json"), recursive=True)) + [str(LIBRARY_OVERRIDES)]
    for path_text in paths:
        path = Path(path_text)
        relative = str(path.relative_to(PROJECT_ROOT))
        if "special-disc" in relative or "world-map-titles" in relative:
            continue
        raw = path.read_bytes()
        document = json.loads(raw)
        writer = serializer_for(raw, document)
        if writer is None:
            skipped.append({"file": relative, "reason": "no byte-exact serializer for this file's JSON style; left untouched"})
            continue
        file_changed = False
        for entry in scan(document):
            zh = entry.get("translation")
            if not isinstance(zh, str) or not zh:
                continue
            entry_id = str(entry.get("id", ""))
            jp = entry.get("source_text") if isinstance(entry.get("source_text"), str) else entry.get("source") if isinstance(entry.get("source"), str) else None
            if not jp:
                jp = by_sha.get(entry.get("source_text_sha256", "")) or by_id.get(entry_id)
            if not jp:
                continue
            new, groups = apply_rules(jp, zh, entry_id)
            if new == zh:
                continue
            note = None
            if relative.startswith("corpus/zh/story-dialogue/"):
                links = source_index.get(entry_id, {}).get("keyword_links", False)
                if dialogue_layout_issues(new, profile=profile, stage_keyword_links=links):
                    new = fit_chinese_dialogue_layout(new, profile=profile, stage_keyword_links=links).text
                    note = "relaid"
                    issues = dialogue_layout_issues(new, profile=profile, stage_keyword_links=links)
                    if issues:
                        skipped.append({"id": entry_id, "file": relative, "reason": f"layout gate: {issues}", "attempted": new})
                        continue
            if relative.endswith("srvc-lines.json") and ("\n" in new or new.count("\\n") != zh.count("\\n")):
                skipped.append({"id": entry_id, "file": relative, "reason": "battle line-break change", "attempted": new})
                continue
            if relative.endswith("stage-overviews.json") and len(new.rstrip("\n").split("\n")) != len(zh.rstrip("\n").split("\n")):
                skipped.append({"id": entry_id, "file": relative, "reason": "overview line count change", "attempted": new})
                continue
            changes.append({"id": entry_id, "file": relative, "groups": groups, "before": zh, "before_sha256": sha256_text(zh), "after": new, "after_sha256": sha256_text(new), "note": note})
            entry["translation"] = new
            if "editorial_status" in entry and entry["editorial_status"] == "draft":
                entry["editorial_status"] = "reviewed"
            file_changed = True
        if file_changed:
            touched[path] = (document, writer)

    # remaining-ui.json keeps raw UI strings by executable offset without a Japanese
    # field; the memory-card dialogs, the pennant part text and the protagonist
    # profile copy are the only ones the decisions touch (all same length or shorter).
    remaining = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
    raw = remaining.read_bytes()
    document = json.loads(raw)
    writer = serializer_for(raw, document)
    if writer is None:
        skipped.append({"file": "corpus/zh/menu/remaining-ui.json", "reason": "no byte-exact serializer"})
    else:
        changed_here = False
        for section in ("slps_context_ui_by_offset", "compdata_direct_by_offset"):
            for offset, value in document.get(section, {}).items():
                if not isinstance(value, str):
                    continue
                new, groups = value, []
                for group, pattern, replacement in (("2-13 记忆卡", "存储卡", "记忆卡"), ("2-12 锦旗", "三角旗", "锦旗"), ("2-10 试飞员", "测试驾驶员", "试飞员")):
                    if pattern in new:
                        new = new.replace(pattern, replacement)
                        groups.append(group)
                if new != value:
                    changes.append({"id": f"remaining-ui/{section}/{offset}", "file": "corpus/zh/menu/remaining-ui.json", "groups": groups, "before": value, "before_sha256": sha256_text(value), "after": new, "after_sha256": sha256_text(new), "note": "ui string, same length or shorter"})
                    document[section][offset] = new
                    changed_here = True
        if changed_here:
            touched[remaining] = (document, writer)

    counts = {
        "changed": len(changes),
        "by_group": dict(collections.Counter(g for c in changes for g in c["groups"])),
        "by_file": dict(collections.Counter(c["file"] for c in changes)),
        "relaid": sum(1 for c in changes if c["note"] == "relaid"),
        "skipped": len(skipped),
        "files_touched": len(touched),
    }
    print(json.dumps(counts, ensure_ascii=False, indent=1))
    for s in skipped:
        print("  skipped", json.dumps(s, ensure_ascii=False)[:200])
    if args.dry_run:
        for c in changes:
            if c["note"] == "relaid":
                print("  relaid", c["id"], "|", c["before"].replace("\n", "/"), "=>", c["after"].replace("\n", "/"))
        return 0

    for path, (document, writer) in touched.items():
        path.write_text(writer(document), encoding="utf-8")
    glossary_log = []
    for relative, edits in GLOSSARY_EDITS.items():
        path = PROJECT_ROOT / relative
        text = path.read_text(encoding="utf-8")
        text, log = edit_glossary_text(text, edits, relative)
        glossary_log.extend(log)
        json.loads(text)  # must still parse
        path.write_text(text, encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "batch_id": BATCH_ID,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "decidedBy": "user",
        "reason": "2026-10-21 全量译名一致性排查（work/review/term-sweep-20261021/README.md）：第一类词表已定稿但语料未统一的明显错误，加上用户在决定页上对 23 组两种写法的选择；SP 语料与世界地图贴图标题不在本批次。",
        "decisions": {"page": "work/review/term-sweep-20261021/decisions-20261021.html", "kept_as_is": ["21 ウォーカーマシン", "23 地点卡片空格"]},
        "counts": counts,
        "changes": changes,
        "skipped": skipped,
        "glossary": glossary_log,
        "follow_ups": [
            "world-map/title/134 罗德尼亚→罗多尼亚：世界地图标题是贴图，需重做贴图与 render snapshot",
            "SP：sd/nisv/qa/page/101、keyword_summaries/100、sd/exe/3B5150 的“中途存档”按 SP 契约另批改为“中断保存”",
            "menu/Compdata/01/0082 强化零件 オーバーコート=外覆装甲 未改（固定容量槽位，与对白 Overcoat 是否统一待定）",
        ],
        "productionWriteback": True,
    }
    out = EDITORIAL_DIR / f"{BATCH_ID}.json"
    out.write_text(dump(receipt), encoding="utf-8")
    print(f"wrote {len(changes)} records into {len(touched)} files, {len(glossary_log)} glossary edits; receipt {out.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
