#!/usr/bin/env python3
"""Fetch and verify the pinned Noto CJK canary font."""

from __future__ import annotations

import argparse
from pathlib import Path

from srwz.font_source import FontSourceError, fetch_font_lock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_LOCK = (
    PROJECT_ROOT / "config" / "fonts" / "noto-sans-cjk-sc.lock.json"
)
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download only the pinned official Noto Sans CJK SC font and "
            "its OFL-1.1 license into ignored work/."
        )
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        outputs = fetch_font_lock(
            PROJECT_ROOT,
            WORK_ROOT,
            args.lock,
            force=args.force,
        )
    except FontSourceError as error:
        raise SystemExit(str(error)) from error
    for output in outputs:
        print(f"[OK] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
