#!/usr/bin/env python3
"""Check stored main-game dialogue against its locale's font, frame, and structural rules.

Use --locale all for all three corpora. A near-boundary uncertain ink verdict needs
a runtime check; it does not establish that a line is clipped.
"""

from __future__ import annotations

import argparse
import json
import shutil
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
from srwz.build_layout import dialogue_scene, stored_geometry_issues
from srwz.chinese_layout import dialogue_layout_issues, load_layout_profiles  # noqa: E402


def check(stages: set[int] | None, locale: str = "zh") -> list[tuple[str, tuple[str, ...]]]:
    if locale == "zh":
        profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]
    else:
        from zh_hant.preflight import layout_dir
        regional = layout_dir("hk" if locale.endswith("-hk") else "tw")
        try:
            profile = load_layout_profiles(regional / PROFILES_PATH.name)["story_dialogue"]
        finally:
            shutil.rmtree(regional)
    link_ids = keyword_link_ids()
    problems = []
    for path in sorted((DIALOGUE_ROOT.parents[1]/locale/"story-dialogue").glob("stage-*.json")):
        stage = int(path.stem.split("-")[1])
        if stages and stage not in stages:
            continue
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
        geometry = {}
        for scene in ("story", "story_map"):
            geometry.update(stored_geometry_issues(
                [(e["id"], e["translation"], e["id"] in link_ids) for e in entries
                 if dialogue_scene(e["id"]) == scene], scene, ink_font="hans" if locale=="zh" else "hant"))
        for entry in entries:
            issues = dialogue_layout_issues(
                entry["translation"],
                profile=profile,
                stage_keyword_links=entry["id"] in link_ids,
                check_width=False,
            ) + geometry.get(entry["id"], ())
            if issues:
                problems.append((entry["id"], issues))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--stage", type=int, action="append", help="limit to these stage file numbers"
    )
    parser.add_argument("--locale", choices=["zh","zh-hant","zh-hant-hk","all"], default="zh")
    args = parser.parse_args()
    locales = ("zh","zh-hant","zh-hant-hk") if args.locale=="all" else (args.locale,)
    problems = [(f"{locale} {key}", reasons) for locale in locales
                for key, reasons in check(set(args.stage) if args.stage else None, locale)]
    for entry_id, issues in problems:
        print(f"{entry_id}: {'; '.join(issues)}")
    if problems:
        print(
            f"{len(problems)} dialogue records have geometry or structural findings",
            file=sys.stderr,
        )
        return 1
    print("story dialogue layout: all records final")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
