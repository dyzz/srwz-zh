#!/usr/bin/env python3
"""Apply the 2026-10-17 本篇／BEST／SP name unification (config/editorial/name-unification-20261017.json).

Corpus text is edited in place on the raw JSON so unrelated formatting stays byte-identical.
Pilot name fields go through remaining-ui.json (shared JA → zh map plus per-field overrides),
glossary definitions are rewritten with the old form kept as deprecated.
Run with --check to report what would change without writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus/zh"
GLOSSARY = ROOT / "corpus/glossary"
REMAINING = CORPUS / "menu/remaining-ui.json"
COMMON_WORDS = ROOT / "config/text-layout/zh-story-common-words.txt"
# Live library text overrides applied on top of corpus/zh/library (main game).
CONFIG_TEXT = [ROOT / "config/library/v0.2-editorial-overrides.json"]

# 克莱因 is Lacus/Siegel Clyne (→ 克莱茵) except Klein Sandman of GRAVION.
KLEIN_SANDMAN = r"(?!(?:\\n)?　?·?(?:\\n)?　?桑德曼)"

# (pattern, replacement, scope) — scope "all" = main + SP corpora, "sp" = SP corpora only, "main" = main only.
RULES: list[tuple[str, str, str]] = [
    # people, body text follows the decided form
    ("克莱因" + KLEIN_SANDMAN, "克莱茵", "all"),
    ("弗拉加", "弗拉格", "all"),
    ("哈勒赫", "哈雷", "all"),
    ("马里埃拉", "玛丽埃拉", "all"),
    ("梅多索", "梅德索", "all"),
    ("佩尔哈·佩(?!伊)", "佩尔哈·佩伊", "all"),
    ("斯梅塔纳", "斯梅塔娜", "all"),
    ("塔尔荷·(?:由基|优基)", "塔尔荷·优纪", "all"),
    ("梅梅·米德加尔德", "米姆·米德加尔德", "all"),
    ("梅迪克·赫尔特", "梅迪克·科尔特", "all"),
    ("蒙泽", "蒙扎", "all"),
    ("梅莉贝儿·卡洁特", "梅莉贝儿·加吉特", "all"),
    ("乌纳特·爱玛·塞兰", "乌纳特·艾玛·塞兰", "all"),
    ("鲁布尔·王·达拉", "鲁布尔·翁·达拉", "all"),
    ("卡琳·弗里克", "卡林·弗里克", "all"),
    ("廷普·沙龙", "廷普·沙隆", "all"),
    ("高安·桑德·莱茵福特", "高安·莱因福德", "all"),
    ("西特兰·比(?![一-龥])", "西特兰·维", "all"),
    ("米娅·劳金", "米娅·拉乌金", "all"),
    ("齐格·埃里克迈尔", "齐格·艾里克迈亚", "all"),
    ("卡缪·比丹", "卡缪·维丹", "all"),
    ("阿萨基姆·德温", "阿萨基姆·杜文", "all"),
    ("马德克", "玛多克", "all"),
    ("野马(?=II|Ⅱ|队)", "布隆科", "all"),
    ("贝鲁那尔", "贝尔纳尔", "all"),
    ("奥克莱", "奥克雷", "all"),
    # SP battle-viewer soldier labels
    ("(联邦军|扎夫特|革命军|奇拉姆|DC)兵(?=（)", r"\1士兵", "sp"),
    ("所属不明兵", "身份不明士兵", "sp"),
    # units
    ("新帕尔萨班", "新燃烧脉冲号", "all"),
    ("巴尔迪·普莱兹", "勇者突进号", "all"),
    ("阳光号", "履带游侠号", "all"),
    ("桑巴德", "赞波鸟", "all"),
    ("桑布鲁", "赞波牛", "all"),
    ("桑贝斯", "赞波座", "all"),
    ("赞波王牌", "赞波ACE", "all"),
    ("机械战士", "装甲怪兽", "all"),
    ("强攻型机械天使·阿尔法", "阿克艾里昂·阿尔法", "all"),
    ("阿克艾里昂欧米伽", "阿克艾里昂·欧米伽", "all"),
    ("月神战机", "月亮战机", "all"),
    ("月神阿克艾里昂", "月亮阿克艾里昂", "all"),
    # terms
    ("斯菲亚", "珠玉", "sp"),
    ("乌尔古斯克", "乌鲁古斯克", "all"),
    ("盖塔队", "盖塔小队", "all"),
    ("超重神将达到", "格兰维昂将达到", "sp"),
    ("EX-HARD模式下无法", "EX困难模式下无法", "sp"),
]

# Shared JA → zh pilot-name map (remaining-ui.json display_names_by_source_text).
NAME_MAP = {
    "ドーウィン": "杜文", "ギム": "基姆", "ビダン": "维丹", "ビジョウ": "比琼", "セアック": "瑟亚克",
    "ル・クルーゼ": "鲁·克鲁泽", "ロンド": "朗特", "キスラー": "基斯拉", "メンテナー": "曼泰纳",
    "サード・ラインフォード": "莱因福德", "レーン": "琳", "ヒューズ": "修兹", "ボルジャーノ": "波佳诺",
    "エリクマイヤー": "艾里克迈亚", "ラウジン": "拉乌金", "グーニー": "格尼", "アッカマン": "阿克曼",
    "カクーラー": "卡库勒", "ファラオ": "法拉奥", "クーリック": "库利克", "ラオ・ザビ": "拉欧·扎比",
    "ブルターク": "布尔达克", "コリッシュ": "库利修", "メムマ": "梅姆马", "シャローン": "沙隆",
    "ビィ": "维", "ナダ": "纳达", "クン": "库恩", "ブロンコ": "布隆科", "ウッダー": "伍德",
    "ユーキ": "优纪", "クライン": "克莱茵", "コダマ": "古塔玛",
}
# Per-field overrides where one JA spelling belongs to several people (index decimal, field).
FIELD_OVERRIDES = [
    (311, "family", "エイジ", "艾吉", "ポゥ・エイジ的姓；红英司保持“英司”。"),
    (312, "family", "エイジ", "艾吉", "ポゥ・エイジ的姓；红英司保持“英司”。"),
    (300, "family", "ゲイン", "格恩", "ミハエル・ゲイン的姓；该隐·比琼的名保持“该隐”。"),
    (527, "family", "レーン", "雷恩", "マルチナ・レーン保持“雷恩”（2026-10-17 用户决定），辛西亚改“琳”。"),
    (572, "given", "クライン", "克莱因", "克莱因·桑德曼（GRAVION）不随拉克丝·克莱茵改名。"),
    (573, "given", "クライン", "克莱因", "克莱因·桑德曼（GRAVION）不随拉克丝·克莱茵改名。"),
]
# Glossary definitions whose canonical form changes (id → new translation).
GLOSSARY_CHANGES = {
    "people/sid-munzer-full": "希德·蒙扎",
    "people/guin-sard-lineford-full": "高安·莱因福德",
    "people/meme-midgard-full": "米姆·米德加尔德",
    "people/teteth-halleh-full": "特泰丝·哈雷",
    "people/merrybell-gadget-full": "梅莉贝儿·加吉特",
    "unit/bronco-ii": "布隆科II",
    "organization/bronco-team": "布隆科队",
    "people/speaker-5105ef42feec": "玛多克",
}
NOTE = "2026-10-17 本篇／BEST／SP 译名统一（config/editorial/name-unification-20261017.json）。"
# Parts description (d01): main follows the SP wording.
D01 = ("月光洲编辑的杂志\\n创刊第一号。稀有品。", "月光洲编辑的杂志创刊号。\\n稀有品。")
D01_FLAT = ("月光洲编辑的杂志创刊第一号。稀有品。", "月光洲编辑的杂志创刊号。稀有品。")


def scope_of(path: Path) -> str:
    rel = path.relative_to(CORPUS).as_posix()
    return "sp" if rel.startswith("special-disc/") or rel.startswith("library/sp-") else "main"


def apply_rules(write: bool) -> dict:
    report = {}
    for path in sorted(CORPUS.rglob("*.json")) + CONFIG_TEXT:
        text = original = path.read_text(encoding="utf-8")
        scope = scope_of(path) if path.is_relative_to(CORPUS) else "main"
        for pattern, repl, rule_scope in RULES:
            if rule_scope not in ("all", scope):
                continue
            if path == REMAINING and pattern.startswith("克莱因"):
                continue  # pilot names go through NAME_MAP / FIELD_OVERRIDES (Klein Sandman keeps 克莱因)
            text, n = re.subn(pattern, repl, text)
            if n:
                report.setdefault(pattern, {}).setdefault(path.relative_to(ROOT).as_posix(), 0)
                report[pattern][path.relative_to(ROOT).as_posix()] += n
        if scope == "main":
            for old, new in (D01, D01_FLAT):
                if old in text:
                    report.setdefault("d01", {})[path.relative_to(ROOT).as_posix()] = text.count(old)
                    text = text.replace(old, new)
        if write and text != original:
            path.write_text(text, encoding="utf-8")
    return report


def apply_names(write: bool) -> dict:
    raw = REMAINING.read_text(encoding="utf-8")
    doc = json.loads(raw)
    names = doc["display_names_by_source_text"]
    changed = {}
    for ja, zh in NAME_MAP.items():
        if ja not in names:
            raise SystemExit(f"pilot name key missing: {ja}")
        if names[ja] != zh:
            changed[ja] = (names[ja], zh)
            # the JSON map is one "key": "value" per line; edit that line only
            line = f'"{ja}": "{names[ja]}"'
            if raw.count(line) != 1:
                raise SystemExit(f"cannot locate unique pilot-name line for {ja}")
            raw = raw.replace(line, f'"{ja}": "{zh}"')
    overrides = doc["pilot_name_overrides"]
    have = {o["id"] for o in overrides}
    added = []
    for index, field, ja, zh, reason in FIELD_OVERRIDES:
        entry_id = f"display-name/pilot/{index:04d}/{field}"
        if entry_id in have:
            continue
        added.append(dict(id=entry_id, source_text_sha256=hashlib.sha256(ja.encode("utf-8")).hexdigest(),
                          translation=zh, reason=reason))
    if write:
        if added:
            doc2 = json.loads(raw)
            doc2["pilot_name_overrides"].extend(added)
            # keep the file's existing layout for everything except the override list
            old_block = json.dumps(doc["pilot_name_overrides"], ensure_ascii=False, indent=2)
            new_block = json.dumps(doc2["pilot_name_overrides"], ensure_ascii=False, indent=2)
            indented_old = old_block.replace("\n", "\n  ")
            indented_new = new_block.replace("\n", "\n  ")
            if raw.count(indented_old) != 1:
                raise SystemExit("cannot locate pilot_name_overrides block")
            raw = raw.replace(indented_old, indented_new)
            if json.loads(raw)["pilot_name_overrides"] != doc2["pilot_name_overrides"]:
                raise SystemExit("pilot_name_overrides rewrite mismatch")
        REMAINING.write_text(raw, encoding="utf-8")
    return dict(map_changed=changed, overrides_added=[a["id"] for a in added])


def _edit_term_span(raw: str, term_id: str, new: str) -> tuple[str, str]:
    """Edit one glossary term in place, keeping the file's own layout (files mix one-line and indented terms)."""
    m = re.search(r'"id":\s*"' + re.escape(term_id) + '"', raw)
    if not m:
        raise SystemExit(f"glossary term not found: {term_id}")
    start = raw.rfind("{", 0, m.start())
    nxt = re.search(r'"id":\s*"', raw[m.end():])
    end = m.end() + (nxt.start() if nxt else len(raw) - m.end())
    span = raw[start:end]
    tm = re.search(r'("translation":\s*")((?:[^"\\]|\\.)*)(")', span)
    old = json.loads('"' + tm.group(2) + '"')
    span = span[:tm.start(2)] + new + span[tm.end(2):]
    dm = re.search(r'("deprecated_translations":\s*)(\[[^\]]*\])', span)
    if dm:
        dep = [d for d in json.loads(dm.group(2)) if d != new]
        sep = ", " if '", "' in dm.group(2) else ","
        if old not in dep:
            dep.append(old)
        arr = "[" + sep.join(json.dumps(d, ensure_ascii=False) for d in dep) + "]"
        span = span[:dm.start(2)] + arr + span[dm.end(2):]
    else:
        colon = '":"' if '"translation":"' in span else '": "'
        tm2 = re.search(r'"translation":\s*"(?:[^"\\]|\\.)*"', span)
        joiner = "," if colon == '":"' else ",\n" + " " * (len(span[:tm2.start()]) - len(span[:tm2.start()].rstrip(" ")))
        span = span[:tm2.end()] + joiner + '"deprecated_translations"' + colon[1:-1] + json.dumps([old], ensure_ascii=False) + span[tm2.end():]
    nm = re.search(r'("notes":\s*")((?:[^"\\]|\\.)*)(")', span)
    if nm:
        span = span[:nm.end(2)] + json.dumps(" " + NOTE, ensure_ascii=False)[1:-1] + span[nm.end(2):]
    return raw[:start] + span + raw[end:], old


def apply_glossary(write: bool) -> dict:
    done = {}
    for path in sorted(GLOSSARY.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        ids = {t.get("id") for t in json.loads(raw).get("terms", [])}
        touched = False
        for term_id, new in GLOSSARY_CHANGES.items():
            if term_id not in ids:
                continue
            raw, old = _edit_term_span(raw, term_id, new)
            if old != new:
                done[term_id] = (old, new, path.name)
                touched = True
        if touched:
            terms = {t["id"]: t for t in json.loads(raw)["terms"]}
            for term_id in GLOSSARY_CHANGES:
                if term_id in terms and terms[term_id]["translation"] != GLOSSARY_CHANGES[term_id]:
                    raise SystemExit(f"glossary rewrite mismatch: {term_id}")
            if write:
                path.write_text(raw, encoding="utf-8")
    return done


def apply_word_list(write: bool) -> list[str]:
    words = COMMON_WORDS.read_text(encoding="utf-8").splitlines()
    add = [w for w in ("克莱茵",) if w not in words]
    if write and add:
        COMMON_WORDS.write_text("\n".join(words + add) + "\n", encoding="utf-8")
    return add


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true", help="report only")
    write = not p.parse_args().check
    report = dict(rules=apply_rules(write), names=apply_names(write), glossary=apply_glossary(write),
                  word_list=apply_word_list(write))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
