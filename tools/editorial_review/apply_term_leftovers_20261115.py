#!/usr/bin/env python3
"""Write the user's 2026-11-15 name decisions (0.5.1 term leftovers) into the corpus.

Decisions (review page work/review/term-leftovers-20261114, answered in chat):
ターンタイプ → Turn系机体, アプリリウス → 阿普里利乌斯, アンダーゴレーム → 安达葛雷姆,
コダマ隊 → 古塔玛队 (the surname's current rendering), 因果の鎖 → 因果之链, and the two
same-source song lines of stages 117 / 130 (stage-117 wording, title in English).

Every rewrite is bound to the record's own Japanese source; nothing else in a line
changes and stored line breaks stay where they are.  Gates before writing: the base
text still holds the old rendering, the story / battle layout gates pass on the new
text, and a fresh online-suggestion snapshot is taken (lines with opinions are
written because the user decided the names with those opinions shown; they are
listed in the receipt).  Dry run unless --apply.

    python3 tools/editorial_review/apply_term_leftovers_20261115.py
    python3 tools/editorial_review/apply_term_leftovers_20261115.py --apply
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/text_layout"))
sys.path.insert(0, str(ROOT / "tools/editorial_review"))

import apply_story_polish_20261110 as base  # noqa: E402  (fetch_online, refresh_active_locks, sha)

REVIEW = ROOT / "work/review/term-leftovers-20261114"
RECEIPTS = {"a": ROOT / "config/editorial/term-leftovers-20261115.json",
            "b": ROOT / "config/editorial/term-leftovers-20261115-b.json",
            "c": ROOT / "config/editorial/term-leftovers-20261115-c.json",
            "d": ROOT / "config/editorial/term-leftovers-20261115-d.json"}
JP_BY_SHA = ROOT / "work/review/caption-tilde-20261113/jp-by-sha.json"
LIBRARY_OVERRIDES = ROOT / "config/library/v0.2-editorial-overrides.json"
TAGGED_TURN = "<width:0E><space:0C>Turn<width:16><space:16>"

# group, Japanese term, user's words, [(pattern, replacement)] applied in order
RULES = [
    ("turntype", "ターンタイプ", "ターンタイプ统一Turn系机体吧", [
        # 「ターンタイプのガンダム」: the noun is already there, so 系 alone
        (TAGGED_TURN + "型高达", TAGGED_TURN + "系高达"),
        ("Turn型高达", "Turn系高达"),
        (TAGGED_TURN + "型机体", TAGGED_TURN + "系机体"),
        (re.compile(r"(?:Turn Type|Turn型)机体"), "Turn系机体"),
        (TAGGED_TURN + "型", TAGGED_TURN + "系机体"),
        # 「ターンタイプのモビルスーツ」 is one noun phrase; 机体 already says モビルスーツ
        (re.compile(r"(?:Turn Type|Turn型|逆式)的MS"), "Turn系机体"),
        ("Turn Type\n　MS的", "Turn系机体\n　的"),
        ("倒A型之间", TAGGED_TURN + "系机体之间"),
        (re.compile(r"Turn Type|Turn型|逆式"), "Turn系机体"),
    ]),
    ("aprilius", "アプリリウス", "アプリリウス统一阿普里利乌斯", [
        (re.compile("阿普利里乌斯|阿普利留斯|阿普里琉斯|阿普利乌斯"), "阿普里利乌斯"),
    ]),
    ("golem", "アンダーゴレーム", "アンダーゴレーム 统一 安达葛雷姆", [("安达格雷姆", "安达葛雷姆")]),
    ("kodama", "コダマ隊", "コダマ隊 按照当前名字的翻译统一", [(re.compile("小玉队|柯达玛队"), "古塔玛队")]),
    ("inga", "因果の鎖", "因果の鎖 统一 因果之链", [(re.compile("因果之锁|因果锁链|因果的锁链"), "因果之链")]),
    # the two same-source song lines of stages 117 / 130: both take the stage-117 wording, title in English
    ("lyric", "キングゲイナー♪", "メタル〜オ〜バ〜マン、キングゲイナー♪ 用前一个，但是王者盖纳 改英语，和前一句一致", [
        ("King〜King〜王者盖纳♪", "King〜King〜King Gainer♪"),
        ("Metal〜Over〜Man，", "Metal〜O〜ver〜man，"),
        ("王者盖纳♪", "King Gainer♪"),
    ]),
]

# second batch, decided later the same day; the first receipt is referenced by the SP name contract and stays as written
RULES_B = [
    ("lane", "マルチナ・レーン", "辛西娅·琳 ，祖母名字和她统一", [("玛尔蒂娜·雷恩", "玛尔蒂娜·琳")]),
]
EXPLICIT_B = [("corpus/zh/special-disc/story-dialogue.json", "sd/story/029/dialogue/02.01/0007", "lane")]

# third batch: 機関部 by context (the user's rule: ship interior 动力舱, a machine's own power plant 动力系统,
# the engineering department 轮机部), 自警団 → 自警团, 軍警察 → 军警
KIKANBU = {  # id -> (old wording, new wording); every line read with its speaker and scene
    "battle:03281": ("机关部", "动力舱"), "battle:12559": ("机关部", "动力舱"), "battle:19211": ("机关部", "动力舱"),
    "battle:19217": ("机关部", "动力舱"), "battle:23889": ("机关部", "动力舱"),
    "story/075/dialogue/01.15/0009": ("机关部", "动力舱"),
    "battle:07596": ("引擎部", "动力舱"), "battle:07651": ("引擎部", "动力舱"),
    "story/107/dialogue/01.59/0001": ("引擎部", "动力舱"),
    "battle:08290": ("引擎室", "动力舱"), "battle:03449": ("轮机室", "动力舱"),
    "battle:16486": ("动力部", "动力舱"), "story/052/dialogue/01.11/0000": ("动力部", "动力舱"),
    "battle:02355": ("引擎受损", "动力舱受损"), "battle:07012": ("引擎中弹", "动力舱中弹"),
    "battle:07014": ("引擎被打中", "动力舱被打中"), "battle:25419": ("引擎中弹", "动力舱中弹"),
    # 「機関部停止！」 on a sinking ship: the machinery has stopped, not the room
    "battle:17720": ("动力部停止", "动力系统停止"),
    # Kamille in the Mk-II: the suit's own power plant
    "story/058/dialogue/01.11/0000": ("引擎部分", "动力系统"),
}
RULES_C = [
    ("kikanbu", "機関部", "機関部 → 动力舱（按语境：舰船内部区域 动力舱；机体内部动力机构 动力系统；负责动力的部门 轮机部）", KIKANBU),
    ("jikeidan", "自警団", "自警団 → 自警团", [(re.compile("自卫团|警备团|自卫队"), "自警团")]),
    ("gunkei", "軍警察", "軍警察 → 军警", [(re.compile("军警察|宪兵"), "军警")]),
]
EXPLICIT_C = []

# fourth batch: the choices the user exported from the pick page (every row of nine groups, each the
# recommended name), plus one line the first batch left half-done: battle lines store their row break as a
# literal backslash-n, so the 「ターンタイプの／モビルスーツ」 rule written with a real newline missed it.
RULES_D = [
    ("vega", "ベガ", "挑选页：贝加", [("维加", "贝加")]),
    ("gym", "ギム", "挑选页：基姆", [("吉姆", "基姆")]),
    ("skullmoon", "スカルムーン連合", "挑选页：骷髅月联合", [("骷髅月联盟", "骷髅月联合")]),
    ("kenjin", "賢人会議", "挑选页：贤人会议", [(re.compile("贤人会(?!议)"), "贤人会议")]),
    ("gicho", "デュランダル議長", "挑选页：议长", [("迪兰达尔主席", "迪兰达尔议长")]),
    ("keibi", "警備隊", "挑选页：警备队", [("警卫队", "警备队")]),
    ("timewarp", "タイムワープ", "挑选页：时间跳跃", [("时间跃迁", "时间跳跃")]),
    ("samelia", "南アメリア", "挑选页：南阿美利亚", [(re.compile("南亚美利加|南亚美利亚|南美洲"), "南阿美利亚")]),
    ("amelia", "アメリア", "挑选页：阿美利亚", [(re.compile("(?<!南)亚美利加"), "阿美利亚")]),
    ("turntype-fix", "ターンタイプ", "ターンタイプ统一Turn系机体吧（首批漏改的一行）",
     {"battle:14466": ("Turn系机体\\n　MS的力量", "Turn系机体\\n　的力量")}),
]
EXPLICIT_D = []

# records outside the sha-indexed corpus: (file, id key, id, Japanese term that must be in its source, group)
EXPLICIT = [
    ("corpus/zh/special-disc/challenge-dialogue.json", "sd/challenge/043/dialogue/02.01/0008", "golem"),
    ("corpus/zh/special-disc/native-text.json", "sd/nisv/squad/047", "turntype"),
    ("corpus/zh/special-disc/reviewed-non-stage-text.json", "sd/nisv/squad/047", "turntype"),
    ("corpus/zh/special-disc/squad-names.json", "sd/squad-name/115", "turntype"),
]


def rewrite(text: str, pairs) -> str:
    for pattern, replacement in pairs:
        text = pattern.sub(replacement, text) if hasattr(pattern, "sub") else text.replace(pattern, replacement)
    return text


def load(rel: str):
    raw = (ROOT / rel).read_bytes()
    return raw, json.loads(raw)


def serialise(document, raw: bytes) -> bytes:
    """Reproduce the file's own JSON style; refuse a file we cannot round-trip."""
    for kwargs in (dict(indent=2), dict(indent=1), dict(indent=2, separators=(",", ": "))):
        for tail in ("\n", ""):
            if (json.dumps(json.loads(raw), ensure_ascii=False, **kwargs) + tail).encode() == raw:
                return (json.dumps(document, ensure_ascii=False, **kwargs) + tail).encode()
    return b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--online-snapshot", type=Path)
    parser.add_argument("--batch", choices=("a", "b", "c", "d"), default="a")
    args = parser.parse_args()
    global RULES, EXPLICIT
    RECEIPT = RECEIPTS[args.batch]
    if args.batch == "b":
        RULES, EXPLICIT = RULES_B, EXPLICIT_B
    if args.batch == "c":
        RULES, EXPLICIT = RULES_C, EXPLICIT_C
    if args.batch == "d":
        RULES, EXPLICIT = RULES_D, EXPLICIT_D
    if args.apply and RECEIPT.exists():
        raise SystemExit(f"already applied: {RECEIPT.relative_to(ROOT)}")

    by_sha = json.loads(JP_BY_SHA.read_text(encoding="utf-8"))["by_sha"]
    rule = {g: (term, words, pairs) for g, term, words, pairs in RULES}
    docs, raws, planned = {}, {}, []

    def consider(rel, entry, group, japanese):
        term, words, pairs = rule[group]
        # library bodies break rows inside words (タ/ーンタイプ): also test the text with row breaks removed
        if term not in japanese and term not in re.sub(r"\n　?", "", japanese):
            return
        before = entry.get("translation") or ""
        if isinstance(pairs, dict):  # per-record wording
            if entry["id"] not in pairs:
                return
            old, new = pairs[entry["id"]]
            if before.count(old) != 1:
                raise SystemExit(f"{entry['id']}: expected one {old!r}")
            pairs = [(old, new)]
        after = rewrite(before, pairs)
        if after != before:
            planned.append(dict(id=entry["id"], file=rel, group=group, ja=japanese, before=before, after=after, _entry=entry))

    for path in sorted(glob.glob(str(ROOT / "corpus/zh/**/*.json"), recursive=True)):
        rel = os.path.relpath(path, ROOT)
        try:
            raw, document = load(rel)
        except ValueError:
            continue
        if not (isinstance(document, dict) and isinstance(document.get("entries"), list)):
            continue
        docs[rel], raws[rel] = document, raw
        for entry in document["entries"]:
            if not (isinstance(entry, dict) and "id" in entry):
                continue
            japanese = str(by_sha.get(entry.get("source_text_sha256"), ""))
            for group, *_ in RULES:
                consider(rel, entry, group, japanese)
    seen = {(row["file"], row["id"]) for row in planned}
    for rel, identity, group in EXPLICIT:
        entry = next(e for e in docs[rel]["entries"] if e.get("id") == identity)
        if (rel, identity) not in seen:
            consider(rel, entry, group, entry.get("source_text") or "")
            if not planned or planned[-1]["id"] != identity or planned[-1]["file"] != rel:
                raise SystemExit(f"{rel} {identity}: explicit record no longer holds the old rendering")

    # ---- gates
    from rebalance_story_dialogue import PROFILES_PATH, keyword_link_ids
    from srwz.build_layout import stored_geometry_issues
    from srwz.chinese_layout import battle_subtitle_layout_issues, dialogue_layout_issues, load_layout_profiles
    profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]
    links = keyword_link_ids()
    story = [r for r in planned if r["id"].startswith("story/") and "/dialogue/" in r["id"]]
    battle = [r for r in planned if r["id"].startswith("battle:")]
    geometry = {}
    if story:
        geometry.update(stored_geometry_issues([(r["id"], r["after"], r["id"] in links) for r in story], "story"))
    if battle:
        geometry.update(stored_geometry_issues([(r["id"], r["after"], False) for r in battle], "battle"))
    errors = []
    for r in story:
        issues = list(dialogue_layout_issues(r["after"], profile=profile, stage_keyword_links=r["id"] in links, check_width=False))
        issues += list(geometry.get(r["id"], ()))
        errors += [f"{r['id']}: {m}" for m in issues]
    for r in battle:
        errors += [f"{r['id']}: {m}" for m in list(battle_subtitle_layout_issues(r["after"])) + list(geometry.get(r["id"], ()))]
    for r in planned:
        if r["after"].count("\n") != r["before"].count("\n"):
            errors.append(f"{r['id']}: row count changed")

    if args.online_snapshot:
        online = json.loads(args.online_snapshot.read_text(encoding="utf-8"))
    else:
        online = base.fetch_online()
        (REVIEW / "online-snapshot-writeback.json").write_text(json.dumps(online, ensure_ascii=False), encoding="utf-8")
    opinions = defaultdict(list)
    for row in online["all"]:
        opinions[row["targetId"]].append(dict(id=row["id"], by=row.get("displayNameSnapshot"), resolution=row.get("resolution"),
                                              proposed=row.get("proposedTranslation")))
    for r in planned:
        r["online_opinions"] = opinions.get(r["id"], [])
        r["editorial_status"] = r["_entry"].get("editorial_status", "")

    # ---- library override layer: same rewrite on the override of a changed library record
    raw_overrides, overrides = load(str(LIBRARY_OVERRIDES.relative_to(ROOT)))
    changed_library = {r["id"]: r["group"] for r in planned if r["id"].startswith("library-text/")}
    override_edits = []

    def visit(node):
        if isinstance(node, dict):
            identity = node.get("id") or node.get("entry_id")
            if identity in changed_library and isinstance(node.get("translation"), str):
                new = rewrite(node["translation"], rule[changed_library[identity]][2])
                if new != node["translation"]:
                    override_edits.append(dict(id=identity, before=node["translation"], after=new))
                    node["translation"] = new
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(overrides)

    summary = dict(write=len(planned), files=len({r["file"] for r in planned}), by_group=dict(Counter(r["group"] for r in planned)),
                   reviewed=sum(r["editorial_status"] == "reviewed" for r in planned),
                   with_online_opinions=sum(bool(r["online_opinions"]) for r in planned),
                   library_override_edits=len(override_edits),
                   online_snapshot_at=online["fetched_at"], online_snapshot_total=online["total"], gate_errors=len(errors))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for message in errors:
        print("GATE", message)
    public = [{k: v for k, v in r.items() if k != "_entry"} for r in planned]
    if not args.apply:
        (REVIEW / f"writeback-dry-run-{args.batch}.json").write_text(json.dumps(dict(summary=summary, write=public, library_overrides=override_edits, errors=errors),
                                                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 1 if errors else 0
    if errors:
        raise SystemExit("gate errors; nothing written")

    by_file = defaultdict(list)
    for r in planned:
        r["_entry"]["translation"] = r["after"]
        by_file[r["file"]].append(r["id"])
    outputs = {}
    for rel in sorted(by_file):
        data = serialise(docs[rel], raws[rel])
        if not data:
            raise SystemExit(f"{rel}: cannot reproduce the file's JSON style; nothing written")
        outputs[rel] = data
    rel_overrides = str(LIBRARY_OVERRIDES.relative_to(ROOT))
    if override_edits:
        data = serialise(overrides, raw_overrides)
        if not data:
            raise SystemExit(f"{rel_overrides}: cannot reproduce the file's JSON style; nothing written")
        outputs[rel_overrides] = data
    files = []
    for rel, data in outputs.items():
        target = ROOT / rel
        before = target.read_bytes()
        temporary = target.with_suffix(".writeback-tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        files.append(dict(path=rel, entries=len(by_file.get(rel, [])), before_sha256=base.sha(before), after_sha256=base.sha(data)))
    locks = base.refresh_active_locks(set(outputs))
    receipt = dict(
        schema_version=1, review_id=RECEIPT.stem, translation_writeback=True,
        purpose="0.5.1 发布前的译名遗留：五组专名和 117／130 话两句同源歌词按用户在对话中的决定统一。每条改写绑定该记录自己的日文原文，只替换专名，不动其他措辞和换行。",
        authorization={g: words for g, _, words, _ in RULES},
        note="带审阅定稿或线上意见的行一并改写：用户是在挑选页列出这些意见的情况下定的译名。线上意见逐条记在条目里。",
        feedback_snapshot_at=online["fetched_at"], feedback_snapshot_total=online["total"],
        summary=summary, application=dict(files=files, active_lock_updates=locks, site_writeback=False),
        entries=public, library_overrides=override_edits,
    )
    RECEIPT.write_text(base.dump(receipt), encoding="utf-8")
    print(f"wrote {len(planned)} records in {len(files)} files; receipt {RECEIPT.relative_to(ROOT)}; lock files {[l['file'] for l in locks]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
