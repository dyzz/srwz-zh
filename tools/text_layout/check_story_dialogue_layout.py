#!/usr/bin/env python3
"""Fail when any story dialogue is not stored in its final 21x3 layout.

This is the same gate the story component builder and the ISO content
verifier apply.  Run it after every writeback into ``corpus/zh/story-dialogue``
(community batches, subtitle reviews, terminology sweeps) before building:

    python3 tools/text_layout/check_story_dialogue_layout.py
    python3 tools/text_layout/check_story_dialogue_layout.py --stage 108 --stage 186

It lists every offending record (overflowing lines, too many lines, or a line
break inside a word or proper name of the profile's unbroken term list) and
exits 1.  Fix them with ``rebalance_story_dialogue.py``; the keyword-link flag
is taken from the Japanese source exactly as the builder does.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))

from rebalance_story_dialogue import (  # noqa: E402
    DIALOGUE_ROOT,
    PROFILES_PATH,
    keyword_link_ids,
)
from srwz.chinese_layout import dialogue_layout_issues, load_layout_profiles  # noqa: E402


def check(stages: set[int] | None) -> list[tuple[str, tuple[str, ...]]]:
    profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]
    link_ids = keyword_link_ids()
    problems = []
    for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
        stage = int(path.stem.split("-")[1])
        if stages and stage not in stages:
            continue
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            issues = dialogue_layout_issues(
                entry["translation"],
                profile=profile,
                stage_keyword_links=entry["id"] in link_ids,
            )
            if issues:
                problems.append((entry["id"], issues))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--stage", type=int, action="append", help="limit to these stage file numbers"
    )
    args = parser.parse_args()
    problems = check(set(args.stage) if args.stage else None)
    for entry_id, issues in problems:
        print(f"{entry_id}: {'; '.join(issues)}")
    if problems:
        print(
            f"{len(problems)} dialogue records are not in final layout; "
            "run tools/text_layout/rebalance_story_dialogue.py",
            file=sys.stderr,
        )
        return 1
    print("story dialogue layout: all records final")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
