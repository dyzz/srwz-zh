"""Pre-pass: gender and identity of every SD speaker the library cannot place, Chinese names for new ones.

Pronouns need a gender for everyone who speaks or is spoken about. The library profile gives it for
most cast members (他/她 count); the rest (Neo, SD-original characters, generic soldiers, "？？？")
are drafted here by the model from their SD lines and then reviewed by hand into roster.json,
which CharacterSheets reads before anything else.

  python3 roster.py draft    -> roster-draft.json (model output + evidence)
  roster.json                -> reviewed overrides {jp: {zh, gender, identity, zh_status}}
"""
from __future__ import annotations

import collections
import glob
import json
import sys

from api import chat, parse_json
from common import EXPORT, HERE, CharacterSheets, load_json

SYSTEM = """你在为《超级机器人大战Z 特别篇》的汉化整理角色表。对每个日文说话人名，根据其台词、出场话数和资料，判断：
- gender：男 / 女 / 群体（多人或组织）/ 不明（如身份隐藏的“？？？”、旁白）；
- identity：一句中文说明此人是谁（作品、立场、与主要角色的关系），不确定就写“不确定：…”；
- zh：仅当输入的 zh 为空时，给出中文译名建议（参照《机战Z》正篇与各作品通行中文译名，原创角色按片假名音译，职务名意译）；
- basis：判断依据（自称、语气、他人称呼等），简短。
只输出 JSON：{"roster":[{"jp":"…","gender":"…","identity":"…","zh":"…","basis":"…"}]}，按输入顺序每人一条。"""


def speaker_lines() -> tuple[collections.Counter, dict, dict]:
    count, lines, where = collections.Counter(), collections.defaultdict(list), collections.defaultdict(set)
    for folder, pattern in (("01-剧情模式", "ep*.json"), ("02-挑战模式", "m*.json")):
        for path in sorted(glob.glob(str(EXPORT / folder / pattern))):
            doc = load_json(path)
            for r in doc["sections"]["dialogue"]:
                sp = r.get("speaker")
                if not sp or r["kind"] == "scene_label":
                    continue
                count[sp] += 1
                where[sp].add(doc["title"])
                if len(lines[sp]) < 14 and len(r["source"]) > 6:
                    lines[sp].append(r["source"].replace("\n", ""))
    return count, lines, where


def draft() -> None:
    sheets = CharacterSheets()
    count, lines, where = speaker_lines()
    todo = []
    for sp, n in count.most_common():
        if sp == "$n" or not sp.strip():
            continue
        sheet = sheets.sheet(sp)
        if sheet.get("gender") and not sheet["zh"].startswith("（新"):
            continue
        todo.append(dict(jp=sp, zh="" if sheet["zh"].startswith("（新") else sheet["zh"], line_count=n,
                         work=sheet.get("work", ""), profile=sheet.get("profile", ""),
                         episodes=sorted(where[sp])[:4], sd_lines=lines[sp],
                         main_game_lines=[s["zh"] for s in sheet.get("voice_samples", [])]))
    results = []
    for i in range(0, len(todo), 30):
        part = todo[i:i + 30]
        call = chat([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps(dict(speakers=part), ensure_ascii=False)}])
        got = {r["jp"]: r for r in parse_json(call.text)["roster"]}
        for t in part:
            results.append(dict(**{k: t[k] for k in ("jp", "zh", "line_count", "work")}, model=got.get(t["jp"]),
                                evidence=t["sd_lines"][:6]))
        print(f"{i + len(part)}/{len(todo)} tokens {call.prompt_tokens}+{call.completion_tokens}", file=sys.stderr)
    (HERE / "roster-draft.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(results)} speakers drafted")


if __name__ == "__main__":
    {"draft": draft}[sys.argv[1]]()
