#!/usr/bin/env python3
"""Inspect one SRWZ compressed chunk without writing decoded game data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from srwz.codec import (
    DEFAULT_MAX_CODED_INTEGER_BYTES,
    DEFAULT_MAX_OUTPUT_SIZE,
    DEFAULT_MAX_TOKENS,
    decode,
)
from srwz.codec_contract import SrwzCodecError
from srwz.diagnostics import TraceCollector, require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
MAX_TRACE_EVENTS = 10_000


def bounded_event_limit(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= MAX_TRACE_EVENTS:
        raise argparse.ArgumentTypeError(
            f"must be between 0 and {MAX_TRACE_EVENTS}"
        )
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Decode and inspect one SRWZ chunk without saving its output."
    )
    parser.add_argument("chunk", type=Path)
    parser.add_argument(
        "--json-trace",
        type=Path,
        help="write a bounded metadata-only trace below work/",
    )
    parser.add_argument(
        "--max-trace-events",
        type=bounded_event_limit,
        default=256,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-output-size", type=int, default=DEFAULT_MAX_OUTPUT_SIZE)
    parser.add_argument(
        "--max-coded-integer-bytes",
        type=int,
        default=DEFAULT_MAX_CODED_INTEGER_BYTES,
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    chunk_path = args.chunk.resolve()
    if not chunk_path.is_file():
        print(f"error: chunk not found: {chunk_path}", file=sys.stderr)
        return 2

    try:
        data = chunk_path.read_bytes()
        collector = TraceCollector(args.max_trace_events)
        result = decode(
            data,
            max_output_size=args.max_output_size,
            max_coded_integer_bytes=args.max_coded_integer_bytes,
            max_tokens=args.max_tokens,
            trace_sink=collector,
        )
    except (OSError, SrwzCodecError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    trailing = data[result.consumed:]
    statistics = collector.statistics()
    print(
        f"header: declared={result.declared_size} flags={result.flags} "
        f"window={result.metadata['window_size']} bytes={result.header_size}"
    )
    print(
        f"stream: input={len(data)} consumed={result.consumed} "
        f"padding={len(trailing)} padding_all_zero={all(byte == 0 for byte in trailing)}"
    )
    print(
        f"blocks/tokens: blocks={statistics['block_count']} "
        f"matches={statistics['match_token_count']} "
        f"literal_bytes={statistics['literal_bytes']} "
        f"match_bytes={statistics['match_bytes']}"
    )
    print(
        f"extensions/maxima: distance={statistics['extended_distance_count']} "
        f"length={statistics['extended_length_count']} "
        f"max_distance={statistics['max_match_distance']} "
        f"max_length={statistics['max_match_length']}"
    )

    if args.json_trace is not None:
        try:
            trace_path = require_work_output(args.json_trace, WORK_ROOT)
            if trace_path.exists() and not args.force:
                raise FileExistsError(
                    f"refusing to replace existing trace: {trace_path}"
                )
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            document = {
                "schema_version": 1,
                "content_policy": (
                    "Metadata-only bounded trace; no literal bytes or decoded output."
                ),
                "input": {
                    "path": str(chunk_path),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                },
                "result": {
                    "declared_size": result.declared_size,
                    "flags": result.flags,
                    "header_size": result.header_size,
                    "metadata": dict(result.metadata),
                    "consumed": result.consumed,
                    "padding": len(trailing),
                    "padding_all_zero": all(byte == 0 for byte in trailing),
                },
                "statistics": statistics,
                "trace": collector.bounded_trace(),
            }
            trace_path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except (FileExistsError, OSError, ValueError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(f"trace: {trace_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
