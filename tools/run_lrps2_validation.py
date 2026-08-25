#!/usr/bin/env python3
"""Run a pinned LRPS2/libretro.py automatic runtime scenario."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from srwz.lrps2_runtime import (
        Lrps2RuntimeError,
        load_common_sequence_registry,
        run_validation,
    )
except ModuleNotFoundError:
    from tools.srwz.lrps2_runtime import (
        Lrps2RuntimeError,
        load_common_sequence_registry,
        run_validation,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON_SEQUENCE_REGISTRY = (
    PROJECT_ROOT / "config" / "runtime" / "lrps2-common-sequences.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run frame-timed LRPS2 input and screenshot assertions. Runtime "
            "artifacts are written under ignored work/runtime/."
        )
    )
    route = parser.add_mutually_exclusive_group()
    route.add_argument(
        "--sequence",
        help="named common sequence from config/runtime/lrps2-common-sequences.json",
    )
    route.add_argument("--scenario", type=Path)
    parser.add_argument(
        "--list-sequences",
        action="store_true",
        help="list named common sequences and exit",
    )
    parser.add_argument(
        "--append-input-sequence",
        action="append",
        default=[],
        type=Path,
        metavar="JSON",
        help=(
            "append a relative custom button/capture sequence; may be supplied "
            "more than once"
        ),
    )
    parser.add_argument("--core", type=Path)
    parser.add_argument("--expected-core-sha256")
    parser.add_argument("--system-directory", type=Path)
    parser.add_argument("--iso", type=Path)
    parser.add_argument("--expected-iso-sha256")
    parser.add_argument("--memory-card", type=Path)
    parser.add_argument("--expected-memory-card-sha256")
    parser.add_argument("--output-directory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        common_sequences = load_common_sequence_registry(COMMON_SEQUENCE_REGISTRY)
        if args.list_sequences:
            for name, entry in common_sequences.items():
                buttons = ", ".join(entry["buttons"])
                print(f"{name:10s} [{buttons}] {entry['description']}")
            return 0
        if args.scenario is not None:
            scenario_path = args.scenario
        else:
            sequence_name = args.sequence or "load"
            try:
                scenario_path = common_sequences[sequence_name]["scenario_path"]
            except KeyError as exc:
                available = ", ".join(common_sequences)
                raise Lrps2RuntimeError(
                    f"unknown common sequence {sequence_name!r}; available: {available}"
                ) from exc
        receipt = run_validation(
            project_root=PROJECT_ROOT,
            scenario_path=scenario_path,
            core_override=args.core,
            core_sha256_override=args.expected_core_sha256,
            system_directory_override=args.system_directory,
            iso_override=args.iso,
            iso_sha256_override=args.expected_iso_sha256,
            memory_card_override=args.memory_card,
            memory_card_sha256_override=args.expected_memory_card_sha256,
            custom_input_sequence_paths=args.append_input_sequence,
            output_directory=args.output_directory,
        )
    except (Lrps2RuntimeError, OSError, RuntimeError) as exc:
        print(f"LRPS2 validation failed: {exc}")
        return 1
    print(f"LRPS2 validation passed: {receipt['output_directory']}")
    for sequence in receipt["custom_input_sequences"]:
        print(
            f"  custom sequence {sequence['sequence_id']}: sha256={sequence['sha256']}"
        )
    for capture in receipt["captures"]:
        print(
            f"  frame {capture['frame']:5d} {capture['id']}: "
            f"{capture['width']}x{capture['height']} "
            f"dhash={capture['dhash']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
