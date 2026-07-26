#!/usr/bin/env python3
"""Build the no-hook, opening-screen Simplified Chinese static canary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.canary import CanaryError, build_static_canary
from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config" / "canary" / "minimal-slps-font.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replace two pinned blank VT1 glyphs and two fixed-size SLPS "
            "characters in one fixed-size opening-screen string using only "
            "the original renderer path. No ISO is built."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--print-output-locks",
        action="store_true",
        help="Development-only: print computed locks without enforcing them.",
    )
    return parser.parse_args()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    outputs = {
        name: require_work_output(_resolve(path), WORK_ROOT)
        for name, path in config["outputs"].items()
    }
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not args.force and not args.print_output_locks:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        slps, vt1, preview, report = build_static_canary(
            PROJECT_ROOT,
            args.config,
            enforce_expected_outputs=not args.print_output_locks,
        )
    except CanaryError as error:
        raise SystemExit(f"canary build failed: {error}") from error

    if args.print_output_locks:
        locks = {
            "decoded_font_sha256": report["decoded_font"]["output_sha256"],
            "encoded_font": {
                "size": report["vt1_output"]["replaced_encoded_size"],
                "sha256": report["vt1_output"][
                    "replaced_encoded_sha256"
                ],
            },
            "slps": {
                "size": report["slps_output"]["size"],
                "sha256": report["slps_output"]["sha256"],
                "diff_count": report["slps_output"]["diff"]["diff_count"],
                "offsets_sha256": report["slps_output"]["diff"][
                    "offsets_sha256"
                ],
            },
            "vt1": {
                "size": report["vt1_output"]["size"],
                "sha256": report["vt1_output"]["sha256"],
            },
            "preview": {"sha256": report["preview_sha256"]},
        }
        print(json.dumps(locks, indent=2))
        return 0

    payloads = {
        "slps": slps,
        "vt1": vt1,
        "preview": preview,
        "report": (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    for name, output in outputs.items():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payloads[name])
        print(f"{name}: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
