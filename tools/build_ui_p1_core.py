#!/usr/bin/env python3
"""Build the integrated P1 core UI component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_integration import (
    UiIntegrationError,
    build_ui_p1_core_component,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/ui-integration/p1-core.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compose the validated title, P0 menu, display-name, P1 font "
            "and world-history layers into one deterministic component."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--force", action="store_true")
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
        "compdata": output_root / "DATA/COMPDATA.BN",
    }
    report_path = output_root / "component-validation.json"
    existing = [path for path in (*paths.values(), report_path) if path.exists()]
    if existing and not args.force:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        outputs, report = build_ui_p1_core_component(
            PROJECT_ROOT,
            config_path,
        )
    except (KeyError, UiIntegrationError) as error:
        raise SystemExit(str(error)) from error
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(outputs[name])
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI P1 core component:",
        f"menu={report['ratchet']['actual']['p0_slps_covered_entry_count']}",
        f"names={report['ratchet']['actual']['p0_display_name_entry_count']}",
        f"history={report['ratchet']['actual']['world_history_entry_count']}",
        "title=4",
        "runtime=pending",
    )
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
