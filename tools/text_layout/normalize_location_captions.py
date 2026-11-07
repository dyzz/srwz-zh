#!/usr/bin/env python3
"""Store every place caption (〜基地　通路〜) in its final form, or check that it is.

Main-game and Special Disc captions use one mark and are centred on the
window (see srwz.chinese_layout.location_caption).  Spaces inside a caption are left alone: the 2026-10-21 term
sweep kept them as they are.  Rerun after a corpus writeback:

    python3 tools/text_layout/normalize_location_captions.py --check
    python3 tools/text_layout/normalize_location_captions.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))

from rebalance_story_dialogue import DIALOGUE_ROOT, source_dialogue_index  # noqa: E402
from srwz.chinese_layout import LOCATION_CAPTION_MARKS, location_caption  # noqa: E402

SP_PATH = PROJECT_ROOT / "corpus/zh/special-disc/story-dialogue.json"
BATCH_PATH = PROJECT_ROOT / "config/editorial/location-captions-20261107.json"
BON_MARCHE = "月光号小卖部‘<z>Bon March</z>é’"
# Captions whose wording, not only their form, was wrong.
BODY_FIXES = {
    "story/143/dialogue/02.01/0003": "诺克斯　市区",
    "story/029/dialogue/02.01/0109": BON_MARCHE,
    "story/029/dialogue/02.02/0141": BON_MARCHE,
}


def is_caption(source: str) -> bool:
    return source.lstrip("　").startswith("〜")


def final_text(entry_id: str, translation: str) -> str:
    final = location_caption(BODY_FIXES.get(entry_id, translation))
    body = final[final.index("〜") + 1 : -1]
    if any(mark in body for mark in LOCATION_CAPTION_MARKS) or "\n" in final:
        raise SystemExit(f"{entry_id}: caption body needs a manual fix: {final!r}")
    return final


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write == args.check:
        parser.error("choose --check or --write")

    sources = source_dialogue_index()
    changes: list[dict] = []
    total = 0
    documents: list[tuple[Path, dict, str]] = []
    for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        documents.append((path, data, raw))
        for entry in data["entries"]:
            meta = sources.get(entry["id"])
            if meta and is_caption(meta["text"]):
                total += 1
                final = final_text(entry["id"], entry["translation"])
                if final != entry["translation"]:
                    changes.append({"id": entry["id"], "before": entry["translation"], "after": final})
                    entry["translation"] = final
    raw = SP_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    documents.append((SP_PATH, data, raw))
    for entry in data["entries"]:
        if is_caption(entry["source_text"]):
            total += 1
            final = final_text(entry["id"], entry["translation"])
            if final != entry["translation"]:
                changes.append({"id": entry["id"], "before": entry["translation"], "after": final})
                entry["translation"] = final

    print(f"{total} captions, {len(changes)} to change")
    if args.check:
        for change in changes[:20]:
            print(f"{change['id']}: {change['before']!r} -> {change['after']!r}")
        return 1 if changes else 0
    for path, document, raw in documents:
        text = dump(document)
        if text != raw:
            path.write_text(text, encoding="utf-8")
    if changes:
        BATCH_PATH.write_text(dump({
            "schema_version": 1,
            "batch_id": "location-captions-20261107",
            "decidedBy": "user",
            "reason": "地点标题统一为〜，按 ARMSX2 实测的窗口中心居中（奇数宽度用半格 space），修正诺克斯与月光号小卖部；标题内空格按 2026-10-21 决定保持现状。",
            "counts": {"captions": total, "changed": len(changes)},
            "changes": changes,
        }), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
