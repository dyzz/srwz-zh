#!/usr/bin/env python3
"""Measure maximum COMPDATA compression without saving encoded game bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from srwz.codec import decode, reencode_changed_suffix
from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_SOURCE = WORK_ROOT / "disc/DATA/COMPDATA.BN"
DEFAULT_OUTPUT = WORK_ROOT / "research/codec/compdata-maximum-sizes.json"
DEFAULT_CANDIDATES = {
    "p1-opening-names": (
        WORK_ROOT / "build/ui-p1-core/components/DATA/COMPDATA.BN"
    ),
    "p2-researched-display-names": (
        WORK_ROOT / "build/ui-p2-display-names/components/DATA/COMPDATA.BN"
    ),
    "p10-database-fixed-core": (
        WORK_ROOT
        / "build/ui-p10-database-fixed-core/components/DATA/COMPDATA.BN"
    ),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_candidate(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name or not raw_path:
        raise argparse.ArgumentTypeError("candidate must be NAME=PATH")
    if Path(name).name != name:
        raise argparse.ArgumentTypeError("candidate name must be one path segment")
    return name, Path(raw_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-encode decoded COMPDATA candidates with the deliberately "
            "expensive maximum strategy and save metrics only."
        )
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--candidate",
        action="append",
        type=parse_candidate,
        help="NAME=PATH; repeat as needed. Defaults to P1, P2 and P10.",
    )
    parser.add_argument("--maximum-size", type=int, default=145408)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def measure(
    *,
    name: str,
    path: Path,
    original_stream: bytes,
    maximum_size: int,
) -> dict:
    candidate_stream = path.read_bytes()
    original = decode(original_stream)
    candidate = decode(candidate_stream)
    if candidate.consumed != len(candidate_stream):
        raise ValueError(f"{name}: input candidate has trailing bytes")
    if len(candidate.output) != len(original.output):
        raise ValueError(f"{name}: decoded COMPDATA size changed")

    print(
        f"measuring {name}: current={len(candidate_stream)}",
        flush=True,
    )
    started = time.monotonic()
    encoded = reencode_changed_suffix(
        original_stream,
        candidate.output,
        strategy="maximum",
        min_match_length=2,
        max_match_chain=256,
    )
    elapsed = time.monotonic() - started

    events = []
    round_trip = decode(encoded, trace_sink=events.append)
    blocks = [event for event in events if event["kind"] == "block"]
    static_game_grammar = (
        round_trip.output == candidate.output
        and round_trip.consumed == len(encoded)
        and all(int(block["literal_count"]) >= 1 for block in blocks)
        and all(
            int(block["match_count"]) >= 1
            or (
                int(block["output_offset"])
                + int(block["literal_count"])
                == len(round_trip.output)
            )
            for block in blocks
        )
    )
    preserved_prefix_size = next(
        (
            index
            for index, (before, after) in enumerate(
                zip(original_stream, encoded)
            )
            if before != after
        ),
        min(len(original_stream), len(encoded)),
    )
    result = {
        "id": name,
        "path": str(path.resolve().relative_to(PROJECT_ROOT)),
        "input_size": len(candidate_stream),
        "input_sha256": sha256_bytes(candidate_stream),
        "decoded_size": len(candidate.output),
        "decoded_sha256": sha256_bytes(candidate.output),
        "maximum_size": len(encoded),
        "maximum_sha256": sha256_bytes(encoded),
        "size_delta": len(encoded) - len(candidate_stream),
        "sector_budget": maximum_size,
        "budget_headroom": maximum_size - len(encoded),
        "within_sector_budget": len(encoded) <= maximum_size,
        "preserved_compressed_prefix_size": preserved_prefix_size,
        "round_trip_exact": round_trip.output == candidate.output,
        "fully_consumed": round_trip.consumed == len(encoded),
        "static_game_decoder_grammar_compatible": static_game_grammar,
        "elapsed_seconds": round(elapsed, 3),
    }
    print(
        f"measured {name}: maximum={len(encoded)} "
        f"headroom={result['budget_headroom']} "
        f"seconds={result['elapsed_seconds']}",
        flush=True,
    )
    return result


def main() -> int:
    args = parse_args()
    if args.maximum_size <= 0:
        raise SystemExit("--maximum-size must be positive")
    source_path = args.source.resolve()
    if not source_path.is_file():
        raise SystemExit(f"source not found: {source_path}")
    candidates = (
        dict(args.candidate)
        if args.candidate
        else DEFAULT_CANDIDATES
    )
    for name, path in candidates.items():
        resolved = path.resolve()
        if not resolved.is_file():
            raise SystemExit(f"candidate not found: {name}={resolved}")
        candidates[name] = resolved

    output_path = require_work_output(
        args.json_output.resolve(),
        WORK_ROOT,
    )
    if output_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output_path}")

    original_stream = source_path.read_bytes()
    original = decode(original_stream)
    results = [
        measure(
            name=name,
            path=path,
            original_stream=original_stream,
            maximum_size=args.maximum_size,
        )
        for name, path in candidates.items()
    ]
    report = {
        "schema_version": 1,
        "status": "maximum_compdata_sizes_measured_runtime_pending",
        "content_policy": (
            "Hashes and aggregate sizes only. Re-encoded and decoded game "
            "bytes are not saved."
        ),
        "source": {
            "path": str(source_path.relative_to(PROJECT_ROOT)),
            "size": len(original_stream),
            "sha256": sha256_bytes(original_stream),
            "decoded_size": len(original.output),
            "decoded_sha256": sha256_bytes(original.output),
        },
        "strategy": {
            "name": "maximum",
            "minimum_match_length": 2,
            "configured_match_chain": 256,
            "gain_search_chain": 65535,
            "lazy_biases": list(range(9)),
            "global_optimality_proven": False,
        },
        "sector_budget": {
            "maximum_size": args.maximum_size,
            "sector_size": 2048,
            "maximum_sectors": (args.maximum_size + 2047) // 2048,
        },
        "candidates": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
