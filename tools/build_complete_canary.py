#!/usr/bin/env python3
"""Build all menu, summary, and story canary replacement components."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.complete_canary import (
    CompleteCanaryError,
    build_complete_canary,
)
from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config" / "canary" / "complete-content.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the complete profile-owned SRWZ menu, MTV_PROS, and "
            "STAGE canary components. No ISO or emulator is executed."
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
    return (PROJECT_ROOT / raw).resolve()


def _isolated_output_paths(config: dict) -> dict[str, dict[str, Path]]:
    raw_profiles = config.get("isolated_outputs", {})
    if not isinstance(raw_profiles, dict):
        raise SystemExit("isolated_outputs must be an object")
    profiles: dict[str, dict[str, Path]] = {}
    for profile_id, raw_outputs in raw_profiles.items():
        if not isinstance(raw_outputs, dict):
            raise SystemExit(
                f"isolated_outputs.{profile_id} must be an object"
            )
        profiles[profile_id] = {
            name: require_work_output(_resolve(path), WORK_ROOT)
            for name, path in raw_outputs.items()
        }
    return profiles


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output_paths = {
        name: require_work_output(_resolve(path), WORK_ROOT)
        for name, path in config["outputs"].items()
    }
    isolated_paths = _isolated_output_paths(config)
    all_output_paths = [
        *output_paths.values(),
        *(
            path
            for outputs in isolated_paths.values()
            for path in outputs.values()
        ),
    ]
    existing = [path for path in all_output_paths if path.exists()]
    if existing and not args.force and not args.print_output_locks:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        outputs, report = build_complete_canary(
            PROJECT_ROOT,
            args.config.resolve(),
            enforce_expected_outputs=not args.print_output_locks,
        )
    except CompleteCanaryError as error:
        raise SystemExit(f"complete canary build failed: {error}") from error

    if args.print_output_locks:
        print(json.dumps(report["outputs"], indent=2))
        return 0

    payloads = {
        "slps": outputs["slps"],
        "vt1": outputs["vt1"],
        "mtv_pros": outputs["mtv_pros"],
        "stage": outputs["stage"],
        "hb": outputs["hb"],
        "preview": outputs["preview"],
        "report": (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    for name, path in output_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payloads[name])
        print(f"{name}: {path}")
    for profile_id, paths in isolated_paths.items():
        for name, path in paths.items():
            if name not in outputs:
                raise SystemExit(
                    f"isolated output {profile_id}.{name} is unknown"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(outputs[name])
            print(f"{profile_id}.{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
