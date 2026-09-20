"""Terms beyond the glossary: the main game's data names, the SD system-text drafts, and SD-only terms.

  reference_terms()        name pairs the main game already renders (COMPDATA / exe translation memory)
                           plus the SD system text drafted on 2026-09-18 (battle-viewer unit and pilot
                           lists, weapon names): used as preferred, not binding, renderings
  python3 terms.py draft   SD-only katakana / Latin terms that nothing above covers, drafted by the
                           model from their contexts -> sd-terms-draft.json; reviewed into sd-terms.json,
                           whose entries are binding like approved glossary terms
"""
from __future__ import annotations

import collections
import glob
import json
import pickle
import re
import sys

from common import EXPORT, HERE, ROOT, SITE, CharacterSheets, glossary_terms, load_json

TM = ROOT / "work/analysis/sp-system-text-20260918/tm.pkl"
SYSTEM_TEXT = ROOT / "corpus/zh/special-disc/system-text.json"
NAME_LIKE = re.compile(r"[ァ-ヺー・＝－−Ａ-Ｚａ-ｚ０-９一-龥々]+")
DASHES = str.maketrans({"−": "－"})


def reference_terms() -> list[dict]:
    pairs: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for jp, found in pickle.loads(TM.read_bytes()).items():
        for (source, zh), n in found.items():
            if source in ("compdata", "exe") and NAME_LIKE.fullmatch(jp) and len(jp) >= 2 and "{" not in zh:
                pairs[jp.translate(DASHES)][zh] += n
    for e in load_json(SYSTEM_TEXT)["entries"]:
        jp, zh = e["source_text"].strip("「」"), e["translation"].strip("“”")
        jp = re.sub(r"（[０-９0-9ｎn]+）$", "", jp)
        zh = re.sub(r"（[０-９0-9ｎn]+）$", "", zh)
        if NAME_LIKE.fullmatch(jp) and 2 <= len(jp) <= 20 and zh:
            pairs[jp.translate(DASHES)][zh] += 1
    return [dict(id=f"ref/{jp}", sources=[jp], zh=found.most_common(1)[0][0], required=False,
                 explicit_only=False, status="reference", category="本篇数据名")
            for jp, found in pairs.items() if re.search(r"[ァ-ヺＡ-Ｚａ-ｚ]", jp)]  # names, not plain kanji words


def sd_terms() -> list[dict]:
    path = HERE / "sd-terms.json"
    if not path.exists():
        return []
    return [dict(id=f"sd/{t['jp']}", sources=[t["jp"], *t.get("variants", [])], zh=t["zh"], required=True,
                 explicit_only=False, status="sd-draft", category=t.get("category"))
            for t in load_json(path) if t.get("zh")]


# names that are also common words: listed as a hint, never enforced
NON_BINDING = {"ボス": "波士（仅指《魔神Z》的波士本人；泛指“老大、头目、首领”时照常翻译）",
               "元気": "元气（仅指精神指令；日常用语“元気”照常翻译）"}


def all_terms() -> list[dict]:
    """Approved glossary first, then SD-only terms, the rest of the glossary, reference names; one rendering
    per Japanese form. SD terms may override unapproved glossary entries (organization/orb says 奥布士兵,
    the main game writes 奥布 in 563 lines)."""
    out, seen = [], set()
    glossary = glossary_terms()
    approved = [t for t in glossary if t.get("status") == "approved"]
    rest = [t for t in glossary if t.get("status") != "approved"]
    for t in approved + sd_terms() + rest + reference_terms():
        sources = [s for s in t["sources"] if s not in seen]
        if not sources:
            continue
        seen.update(sources)
        hint = [s for s in sources if s in NON_BINDING]
        if hint:
            out.append({**t, "sources": hint, "zh": NON_BINDING[hint[0]], "required": False})
            sources = [s for s in sources if s not in NON_BINDING]
        if sources:
            out.append({**t, "sources": sources})
    return out


WORD = re.compile(r"[ァ-ヺー・＝]{3,}|[Ａ-Ｚ][Ａ-Ｚａ-ｚ０-９－−]+")


def candidates(min_count: int = 2) -> list[dict]:
    known = set()
    for t in all_terms():
        known.update(t["sources"])
    sheets = CharacterSheets()
    known.update(sheets.names)
    known.update(sheets.roster)
    count, contexts = collections.Counter(), collections.defaultdict(list)
    for folder in ("01-剧情模式", "02-挑战模式"):
        for path in sorted(glob.glob(str(EXPORT / folder / "*.json"))):
            doc = load_json(path)
            for rows in doc["sections"].values():
                for r in rows:
                    if r.get("status") != "新译":
                        continue
                    for w in WORD.findall(r["source"].translate(DASHES)):
                        w = w.strip("・")
                        if len(w) < 3 or w in known or any(w in k for k in known if len(k) > len(w)):
                            continue
                        count[w] += 1
                        if len(contexts[w]) < 3:
                            contexts[w].append(r["source"].replace("\n", ""))
    words = [w for w, n in count.most_common() if n >= min_count]
    main = collections.defaultdict(list)  # the main game's reviewed lines using the word, with their Chinese
    for path in sorted(glob.glob(str(SITE / "stages/stage-*.json"))):
        for d in load_json(path)["dialogues"]:
            if not d.get("translation"):
                continue
            for w in words:
                if w in d["sourceText"] and len(main[w]) < 3:
                    main[w].append(dict(jp=d["sourceText"].replace("\n", ""), zh=d["translation"].replace("\n", "")))
    return [dict(jp=w, count=count[w], contexts=contexts[w], **({"main_game": main[w]} if main[w] else {}))
            for w in words]


SYSTEM = """你在为《超级机器人大战Z 特别篇》的汉化整理术语。输入是特别篇新文本里出现、项目词表还没有的片假名或字母词，每个附出现次数和上下文。
有 main_game 的，是正篇汉化里用过这个词的台词（日文与定稿中文），必须沿用正篇的译法。
对每个词判断：
- kind：专有名词（人名、机体、组织、地名、系统/计划名、作品内概念）写 term；普通外来语（メンバー、チャンス、データ等）写 common；
- zh：有 main_game 时写正篇用的译法；否则 term 给出中文译名（参照各原作的通行中文译名与《机战Z》正篇汉化习惯；机体名、组织名常用意译或音译加类名；无把握的原创名按音译）；common 给出语境里的常用译法；
- category：人名/机体/组织/地名/系统/概念/其他；
- note：依据或疑点，简短。
只输出 JSON：{"terms":[{"jp":"…","kind":"term|common","zh":"…","category":"…","note":"…"}]}，按输入顺序每词一条。"""


def draft() -> None:
    from api import chat, parse_json
    todo = candidates()
    out = []
    for i in range(0, len(todo), 40):
        part = todo[i:i + 40]
        call = chat([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps(dict(words=part), ensure_ascii=False)}])
        got = {t["jp"]: t for t in parse_json(call.text)["terms"]}
        out.extend(dict(**w, model=got.get(w["jp"])) for w in part)
        print(f"{i + len(part)}/{len(todo)}", file=sys.stderr)
    (HERE / "sd-terms-draft.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(len(out), "candidates drafted")


if __name__ == "__main__":
    {"draft": draft}[sys.argv[1]]()
