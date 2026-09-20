"""Cut the 123 new SD battle lines into request batches, each line with its trigger analysis.

Lines are grouped by voice group (the chunk that owns them) so one request sees a character's new lines
together with that character's main-game lines, the lines sharing its candidate (same moment, the
game picks one at random) and every trigger condition: who the opponent or supported ally must be,
the unit, the stage. Input: battle-lines.json from battle_triggers.py.

Output: batches/battle/battle-<nn>.json
"""
from __future__ import annotations

import collections
import json
import re

from common import HERE, CharacterSheets, load_json, relevant_terms
from terms import all_terms

MAX_LINES = 24


def main() -> None:
    rows = load_json(HERE / "battle-lines.json")
    sheets = CharacterSheets()
    terms = all_terms()
    by_speaker = collections.OrderedDict()
    for row in sorted(rows, key=lambda r: (r["occurrences"][0]["speaker"], r["id"])):
        by_speaker.setdefault(row["occurrences"][0]["speaker"], []).append(row)
    batches, batch = [], []
    for group in by_speaker.values():
        if batch and len(batch) + len(group) > MAX_LINES:
            batches.append(batch)
            batch = []
        batch.extend(group)
    if batch:
        batches.append(batch)

    out_dir = HERE / "batches" / "battle"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    for n, batch in enumerate(batches, 1):
        lines, speakers, voice = [], set(), {}
        for row in batch:
            occurrences = []
            for o in row["occurrences"]:
                occurrences.append(dict(
                    speaker=o["speaker"], speaker_zh=o["speaker_zh"], scene=o["scene"], role=o["role"],
                    conditions=o["conditions"], same_candidate=o["same_candidate"][:4]))
                speakers.update(s for s in o["speaker"].split("／") if s and not s.startswith("？"))
            # one entry per distinct trigger: repeated identical occurrences add nothing
            unique = []
            for o in occurrences:
                if o not in unique:
                    unique.append(o)
            lines.append(dict(id=row["id"], jp=row["jp"], occurrence_count=len(row["occurrences"]),
                              occurrences=unique[:6]))
            for sp, known in row.get("speaker_other_lines", {}).items():
                voice.setdefault(sp, known[:8])
        # people named in the trigger conditions: the character's lines about them are the useful samples
        partners = {name for l in lines for o in l["occurrences"] for c in o["conditions"]
                    for name in re.findall(r"([^：／（）\s]+)（", c)}
        texts = [l["jp"] for l in lines] + [c for l in lines for o in l["occurrences"] for c in o["conditions"]]
        payload = dict(
            characters=[sheets.sheet(s, partners=tuple(partners)) for s in sorted(speakers)],
            mentioned=sheets.mentioned([l["jp"] for l in lines], speakers),
            speaker_other_lines=voice,
            terms=relevant_terms(texts + sorted(speakers), terms),
            lines=lines,
        )
        target = out_dir / f"battle-{n:02d}.json"
        target.write_text(json.dumps(dict(batch_id=target.stem, kind="battle", todo_ids=[l["id"] for l in lines],
                                          auto={}, payload=payload), ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
        print(target.name, len(lines), "lines", len(json.dumps(payload, ensure_ascii=False)), "chars")


if __name__ == "__main__":
    main()
