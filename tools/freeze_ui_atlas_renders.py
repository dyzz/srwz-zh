#!/usr/bin/env python3
"""Explicitly render and freeze one reviewed UI-atlas text snapshot.

Normal builds consume the locked snapshot and do not rerasterize localized
labels. Run this command only after an intentional text or render-policy edit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from srwz.ui_atlas_localization import build_ui_atlas_localization
except ModuleNotFoundError:
    from tools.srwz.ui_atlas_localization import build_ui_atlas_localization


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/assets/ui-intermission-atlas-zh.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "config/assets/ui-intermission-atlas-render-snapshot.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicitly rerender and freeze one localized UI atlas."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    output_path = args.output.resolve()
    if output_path.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite without --force: {output_path}")
    snapshot: dict = {}
    payloads, report = build_ui_atlas_localization(
        PROJECT_ROOT,
        WORK_ROOT,
        config_path,
        enforce_expected=False,
        live_render=True,
        render_snapshot_sink=snapshot,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    preview = WORK_ROOT / "refreeze" / report["profile_id"] / "localized.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(payloads["localized_png"])
    print(f"output={output_path}")
    print(f"label_count={len(snapshot['labels'])}")
    print(f"preview={preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
