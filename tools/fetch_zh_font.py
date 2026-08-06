#!/usr/bin/env python3
"""Fetch the project-wide Chinese font flavor and explicit fallbacks."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.font_flavor import FontFlavorError, load_font_flavor_reference
from srwz.font_source import FontSourceError, fetch_font_lock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_FLAVOR = "config/fonts/zh-localization-font.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the single global Chinese font source and every explicit "
            "missing-glyph fallback into ignored work/font-source/."
        )
    )
    parser.add_argument("--flavor", default=DEFAULT_FLAVOR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        flavor = load_font_flavor_reference(PROJECT_ROOT, args.flavor)
        locks = [
            flavor["font_lock"],
            *[
                reference["font_lock"]
                for reference in flavor["unsupported_character_fallbacks"]
            ],
        ]
        outputs = []
        seen = set()
        for reference in locks:
            if reference in seen:
                continue
            seen.add(reference)
            outputs.extend(
                fetch_font_lock(
                    PROJECT_ROOT,
                    WORK_ROOT,
                    PROJECT_ROOT / reference,
                    force=args.force,
                )
            )
    except (FontFlavorError, FontSourceError, KeyError) as error:
        raise SystemExit(str(error)) from error
    print(f"font flavor: {flavor['flavor_id']}")
    for output in outputs:
        print(f"[OK] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
