#!/usr/bin/env python3
"""Re-break main-game map dialogue that overruns the tactical-map box.

Only records wider than the map limit change, using balanced rows so the
narrower box does not leave one-character tails.

    python3 tools/text_layout/reflow_map_dialogue.py [--write --batch-id ID]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))

from check_story_dialogue_layout import DIALOGUE_ROOT, keyword_link_ids  # noqa: E402
from srwz.build_layout import SCENE_WIDTH_LIMITS, dialogue_scene  # noqa: E402
from srwz.js_layout import layout_batch  # noqa: E402

OPTIONS = {"typography": "proportional", "chinesePunctuation": "compact"}
LIMIT = SCENE_WIDTH_LIMITS["story_map"]


def batched(requests, size=256):
    results = []
    for start in range(0, len(requests), size):
        results.extend(layout_batch(requests[start:start + size]))
    return results


def reflowed(entries, link_ids):
    """Return {id: new translation} for map records wider than the map box."""
    rows = [e for e in entries if dialogue_scene(e["id"]) == "story_map" and e.get("translation")]
    measured = batched([dict(action="measure", scene="story", text=e["translation"],
                             options=dict(OPTIONS, keywordLinks=e["id"] in link_ids)) for e in rows])
    over = []
    for entry, response in zip(rows, measured):
        if not response["ok"]:
            raise SystemExit(f"{entry['id']}: {response['error']}")
        if max(row["occupiedPx"] for row in response["result"]["rows"]) > LIMIT:
            over.append(entry)
    laid_out = batched([dict(action="layout", scene="story_map", text=e["translation"],
                             options=dict(OPTIONS, keywordLinks=e["id"] in link_ids,
                                          maxLines=3, packing="balanced_width")) for e in over])
    changes = {}
    for entry, response in zip(over, laid_out):
        if not response["ok"]:
            raise SystemExit(f"{entry['id']}: {response['error']}")
        changes[entry["id"]] = response["result"]["text"]
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--batch-id", default="map-dialogue-width-20261110")
    args = parser.parse_args()
    link_ids = keyword_link_ids()
    total, files = 0, {}
    for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        changes = reflowed(document["entries"], link_ids)
        total += len(changes)
        if args.write and changes:
            for entry in document["entries"]:
                if entry["id"] in changes:
                    entry["translation"] = changes[entry["id"]]
            data = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            path.write_text(data, encoding="utf-8")
            files[path.name] = dict(records=len(changes),
                                    sha256=hashlib.sha256(data.encode()).hexdigest())
    print(f"map dialogue records re-broken: {total}" + ("" if args.write else " (dry run)"))
    if args.write:
        batch = dict(batch_id=args.batch_id, limit_px=LIMIT, packing="balanced_width",
                     records=total, files=files)
        output = PROJECT_ROOT / "config/editorial" / f"{args.batch_id}.json"
        output.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
