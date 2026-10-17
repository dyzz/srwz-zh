#!/usr/bin/env python3
"""Apply the 2026-10-17 main-game (Original/BEST) old-rendering decisions.

Decisions: config/editorial/main-old-renderings-20261017.json. Same mechanics as
apply_name_unification_20261017.py: raw-text rules over corpus/zh (main + SP) and
the live library overrides, targeted per-record edits, and glossary rewrites that
keep the old form as deprecated. Run with --check to report without writing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_name_unification_20261017 import (  # noqa: E402
    CONFIG_TEXT, CORPUS, GLOSSARY, ROOT, _edit_term_span, scope_of,
)

NOTE_RECORD = "config/editorial/main-old-renderings-20261017.json"

# (pattern, replacement, scope): "all" = main + SP corpora, "main" = main game only.
RULES: list[tuple[str, str, str]] = [
    ("艾岱尔", "艾黛尔", "all"),                                   # m01
    ("总统一阁，", "总帅，", "main"),                               # m02
    ("上级大尉", "上级上尉", "main"),                               # m03
    ("S、STAR[ 　]3，", "星、星3号，", "main"),                 # m05
    ("STAR[ 　]1，", "星1号，", "main"),
    ("强攻型魅影", "强攻魅影", "all"),                              # m06
    ("巨剑魅影", "剑装魅影", "all"),                                # m07
    ("盖纳B（黑色）", "盖纳B（黑方）", "all"),                       # m08
    # m09: kept as 荷粒子炮 (fixed weapon slot holds 4 hanzi)
    ("低反动炮", "低后坐炮", "all"),                                # m10 (slot capacity: 低后坐炮)
    ("Big[ \u3000]O·最终舞台", "BigO·FinalStage", "all"),            # m12 (slot capacity: no spaces)
    ("宇宙大帝神西格玛", "宇宙大帝巨神Σ", "all"),                    # m13
    ("灵魂凯歌", "魂之凯歌", "main"),                               # m14
    ("灵魂角色扮演者", "灵魂的Cosplayer", "main"),                   # m15
    ("弹药筒", "弹匣", "all"),                                      # m16
    ("双重飞碟", "双重斯派扎", "all"),                              # m17
    ("我方回合", "我方阶段", "all"),                                # m18
]

# m04: lines where Boss's followers address him; 波士 → 老大 inside these records only.
FOLLOWER_LINES = {
    "corpus/zh/story-dialogue/stage-045.json": ["story/045/dialogue/01.20/0002"],
    "corpus/zh/story-dialogue/stage-047.json": ["story/047/dialogue/01.23/0003", "story/047/dialogue/01.28/0000"],
    "corpus/zh/story-dialogue/stage-064.json": ["story/064/dialogue/02.01/0098"],
    "corpus/zh/story-dialogue/stage-065.json": ["story/065/dialogue/01.03/0003"],
    "corpus/zh/battle/srvc-lines.json": ["battle:16920"],
}

GLOSSARY_CHANGES = {
    "part/force-silhouette": "强攻魅影",       # m06
    "part/cartridge": "弹匣",                  # m16
    "weapon/0505": "XM47特里斯坦",             # m11
    "episode/aquarion-18": "灵魂的Cosplayer",  # m15
}
GLOSSARY_SUBSTRING = ("艾岱尔", "艾黛尔")    # m01: every term whose definition contains the name


def apply_rules(write: bool) -> dict:
    report = {}
    for path in sorted(CORPUS.rglob("*.json")) + CONFIG_TEXT:
        text = original = path.read_text(encoding="utf-8")
        scope = scope_of(path) if path.is_relative_to(CORPUS) else "main"
        # baseline_translation records the SP disc's pre-override text: never rewrite it
        kept = []
        def hold(match):
            kept.append(match.group(0))
            return f"\x00BASELINE{len(kept) - 1}\x00"
        text = re.sub(r'"baseline_translation": "(?:[^"\\]|\\.)*"', hold, text)
        for pattern, repl, rule_scope in RULES:
            if rule_scope not in ("all", scope):
                continue
            text, n = re.subn(pattern, repl, text)
            if n:
                report.setdefault(pattern, {})[path.relative_to(ROOT).as_posix()] = n
        text = re.sub("\x00BASELINE(\\d+)\x00", lambda m: kept[int(m.group(1))], text)
        if write and text != original:
            path.write_text(text, encoding="utf-8")
    return report


def apply_follower_lines(write: bool) -> dict:
    report = {}
    for rel, ids in FOLLOWER_LINES.items():
        path = ROOT / rel
        raw = path.read_text(encoding="utf-8")
        for entry_id in ids:
            start = raw.index(f'"id": "{entry_id}"')
            m = re.compile(r'"translation": "((?:[^"\\]|\\.)*)"').search(raw, start)
            old = m.group(1)
            if "波士" not in old:
                if "老大" in old:
                    continue  # already applied
                raise SystemExit(f"follower line has no 波士: {entry_id}")
            new = old.replace("波士", "老大")
            raw = raw[:m.start(1)] + new + raw[m.end(1):]
            report[entry_id] = (json.loads(f'"{old}"'), json.loads(f'"{new}"'))
        if write:
            path.write_text(raw, encoding="utf-8")
    return report


def apply_glossary(write: bool) -> dict:
    done = {}
    for path in sorted(GLOSSARY.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        terms = json.loads(raw).get("terms", [])
        changes = {t["id"]: GLOSSARY_CHANGES[t["id"]] for t in terms if t["id"] in GLOSSARY_CHANGES}
        old, new = GLOSSARY_SUBSTRING
        changes.update({t["id"]: t["translation"].replace(old, new) for t in terms
                        if old in t.get("translation", "")})
        touched = False
        for term_id, value in changes.items():
            # a term id may appear more than once in one file (components supplement it)
            starts = [m.start() for m in re.finditer(r'"id":\s*"' + re.escape(term_id) + '"', raw)]
            for start in reversed(starts):
                head = raw[:start]
                cut = head.rfind("{")
                edited, previous = _edit_term_span(raw[cut:], term_id, value)
                raw = raw[:cut] + edited
                if previous != value:
                    done[term_id] = (previous, value, path.name)
                    touched = True
        if touched:
            # the shared helper appends the 10-17 name-unification note; point it at this record
            raw = raw.replace("2026-10-17 本篇／BEST／SP 译名统一（config/editorial/name-unification-20261017.json）。",
                              f"2026-10-17 本篇旧译统一（{NOTE_RECORD}）。")
            current = {t["id"]: t for t in json.loads(raw)["terms"]}
            for term_id, value in changes.items():
                if current[term_id]["translation"] != value:
                    raise SystemExit(f"glossary rewrite mismatch: {term_id}")
            if write:
                path.write_text(raw, encoding="utf-8")
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only")
    write = not parser.parse_args().check
    report = dict(rules=apply_rules(write), follower_lines=apply_follower_lines(write),
                  glossary=apply_glossary(write))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
