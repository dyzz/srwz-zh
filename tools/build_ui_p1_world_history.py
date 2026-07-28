#!/usr/bin/env python3
"""Build a configured Chinese MTV_PROS world-history component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.world_history import (
    WorldHistoryError,
    build_world_history_component,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/summary/world-history-component.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Write all 28 Chinese world-history records into MTV_PROS and "
            "compose the result with the configured SLPS/VT1 font component. "
            "No ISO or emulator is executed."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--print-output-locks",
        action="store_true",
        help="Print deterministic locks without writing component files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_root = require_work_output(
        args.output_root or PROJECT_ROOT / config["outputs"]["component_root"],
        WORK_ROOT,
    )
    paths = {
        "slps": output_root / "SLPS_258.87",
        "vt1": output_root / "DATA/VT1.BIN",
        "mtv_pros": output_root / "DATA/MTV_PROS.BIN",
        "report": output_root / "component-validation.json",
    }
    if (
        any(path.exists() for path in paths.values())
        and not args.force
        and not args.print_output_locks
    ):
        raise SystemExit(f"output exists; use --force: {output_root}")
    try:
        outputs, report = build_world_history_component(
            PROJECT_ROOT,
            config_path,
            enforce_expected_outputs=not args.print_output_locks,
        )
    except WorldHistoryError as error:
        raise SystemExit(str(error)) from error
    if args.print_output_locks:
        print(json.dumps(report["outputs"], indent=2))
        return 0
    for name, payload in outputs.items():
        path = paths[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        print(f"{name}: {path}")
    paths["report"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"report: {paths['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
