#!/usr/bin/env python3
"""Explicitly render and freeze reviewed MAPMODEL world-map titles.

Normal builds consume the locked snapshot and never launch ImageMagick.  Run
this command only when the reviewed title corpus, font, or render policy is
intentionally changed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from srwz.world_map_titles import build_world_map_titles
except ModuleNotFoundError:
    from tools.srwz.world_map_titles import build_world_map_titles


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/full-story-components.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "config/world-map-title-render-snapshot.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicitly rerender and freeze reviewed world-map titles."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite without --force: {args.output}")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    snapshot: dict = {}
    preview_root = WORK_ROOT / "refreeze/world-map-title-renders"
    _output, report, _paths = build_world_map_titles(
        PROJECT_ROOT,
        WORK_ROOT,
        config.get("world_map_titles"),
        preview_root=preview_root,
        live_render=True,
        render_snapshot_sink=snapshot,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"output={args.output}")
    print(f"entry_count={len(snapshot['entries'])}")
    print(f"translated_member_count={report['translated_member_count']}")
    print(f"preview={preview_root / 'world-map-titles-contact-sheet.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
