#!/usr/bin/env python3
"""Strictly scan every compressed stream in the original STAGE.BIN."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from srwz.archive import (
    ArchiveLayoutError,
    load_offset_layout,
    slice_archive,
    verify_archive,
)
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
DEFAULT_ARCHIVE = WORK_ROOT / "disc" / "DATA" / "STAGE.BIN"
DEFAULT_LAYOUT = PROJECT_ROOT / "config" / "stage-offsets.json"
DEFAULT_JSON_OUTPUT = WORK_ROOT / "stage" / "codec-scan.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Decode all stage chunks and save byte-free scan metadata."
    )
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-output-size", type=int, default=DEFAULT_MAX_OUTPUT_SIZE)
    parser.add_argument(
        "--max-coded-integer-bytes",
        type=int,
        default=DEFAULT_MAX_CODED_INTEGER_BYTES,
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    return parser.parse_args()


def distribution(values) -> dict:
    return {
        str(key): count
        for key, count in sorted(Counter(values).items())
    }


def range_summary(values) -> dict:
    values = list(values)
    if not values:
        return {"min": None, "max": None, "total": 0}
    return {"min": min(values), "max": max(values), "total": sum(values)}


def main() -> int:
    args = parse_args()
    archive_path = args.archive.resolve()
    layout_path = args.layout.resolve()

    try:
        output_path = require_work_output(args.json_output, WORK_ROOT)
        if output_path.exists() and not args.force:
            raise FileExistsError(
                f"refusing to replace existing scan: {output_path}"
            )
        layout = load_offset_layout(layout_path)
        verify_archive(archive_path, layout)
        archive_data = archive_path.read_bytes()
    except (
        ArchiveLayoutError,
        FileExistsError,
        FileNotFoundError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    successes = []
    failures = []
    for index, chunk in enumerate(slice_archive(archive_data, layout)):
        chunk_start = layout.offsets[index]
        collector = TraceCollector(0)
        try:
            result = decode(
                chunk,
                max_output_size=args.max_output_size,
                max_coded_integer_bytes=args.max_coded_integer_bytes,
                max_tokens=args.max_tokens,
                trace_sink=collector,
            )
            trailing = chunk[result.consumed:]
            successes.append(
                {
                    "index": index,
                    "archive_offset": chunk_start,
                    "slice_size": len(chunk),
                    "sha256": hashlib.sha256(chunk).hexdigest(),
                    "declared_size": result.declared_size,
                    "flags": result.flags,
                    "header_size": result.header_size,
                    "metadata": dict(result.metadata),
                    "consumed": result.consumed,
                    "padding": len(trailing),
                    "padding_all_zero": all(byte == 0 for byte in trailing),
                    "statistics": collector.statistics(),
                }
            )
        except SrwzCodecError as error:
            local_offset = error.offset
            failures.append(
                {
                    "index": index,
                    "archive_offset": chunk_start,
                    "slice_size": len(chunk),
                    "error": str(error),
                    "input_offset": local_offset,
                    "absolute_archive_offset": (
                        None if local_offset is None else chunk_start + local_offset
                    ),
                }
            )

    padding_values = [row["padding"] for row in successes]
    summary = {
        "chunk_count": layout.chunk_count,
        "success_count": len(successes),
        "failure_count": len(failures),
        "flags_distribution": distribution(row["flags"] for row in successes),
        "unknown_header_1_distribution": distribution(
            row["metadata"]["header_unknown_1"] for row in successes
        ),
        "declared_size": range_summary(
            row["declared_size"] for row in successes
        ),
        "consumed": range_summary(row["consumed"] for row in successes),
        "padding": {
            **range_summary(padding_values),
            "distribution": distribution(padding_values),
            "non_zero_tail_count": sum(
                not row["padding_all_zero"] for row in successes
            ),
        },
        "statistics": {
            "block_count": sum(
                row["statistics"]["block_count"] for row in successes
            ),
            "match_token_count": sum(
                row["statistics"]["match_token_count"] for row in successes
            ),
            "literal_bytes": sum(
                row["statistics"]["literal_bytes"] for row in successes
            ),
            "match_bytes": sum(
                row["statistics"]["match_bytes"] for row in successes
            ),
        },
    }
    document = {
        "schema_version": 1,
        "content_policy": (
            "Metadata and hashes only; no compressed bytes, literals, or decoded output."
        ),
        "archive": {
            "path": str(archive_path),
            "size": len(archive_data),
            "sha256": hashlib.sha256(archive_data).hexdigest(),
        },
        "layout": str(layout_path),
        "summary": summary,
        "chunks": successes,
        "failures": failures,
    }

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"scan: chunks={layout.chunk_count} success={len(successes)} "
        f"failure={len(failures)}"
    )
    print(f"flags: {summary['flags_distribution']}")
    print(
        f"declared: min={summary['declared_size']['min']} "
        f"max={summary['declared_size']['max']} "
        f"total={summary['declared_size']['total']}"
    )
    print(
        f"padding: total={summary['padding']['total']} "
        f"non_zero_tails={summary['padding']['non_zero_tail_count']}"
    )
    print(f"json: {output_path}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
