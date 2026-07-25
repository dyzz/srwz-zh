#!/usr/bin/env python3
"""Round-trip the clean-room encoder over real localization streams."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from srwz.archive import load_offset_layout, slice_archive
from srwz.codec import decode, encode, flags_for_size
from srwz.codec_contract import SrwzCodecError
from srwz.diagnostics import require_work_output
from srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    read_executable_archive_offsets,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DISC_ROOT = WORK_ROOT / "disc"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Decode, clean-room encode and decode again without saving "
            "encoded or decoded game bytes."
        )
    )
    parser.add_argument(
        "--strategy",
        choices=("literal", "greedy"),
        default="greedy",
    )
    parser.add_argument(
        "--stage-layout",
        type=Path,
        default=PROJECT_ROOT / "config" / "stage-offsets.json",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=WORK_ROOT / "encoder" / "encoder-validation.json",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def validate_stream(
    *,
    domain: str,
    identifier: str,
    compressed_slice: bytes,
    strategy: str,
    reconstruction_safe: bool,
) -> dict:
    original = decode(compressed_slice)
    trailing = compressed_slice[original.consumed:]
    encoded = encode(original.output, strategy=strategy)
    runtime_grammar = {
        "block_count": 0,
        "minimum_literal_count": None,
        "zero_literal_block_count": 0,
        "nonfinal_zero_match_block_count": 0,
    }

    def inspect_block(event) -> None:
        if event["kind"] != "block":
            return
        literal_count = int(event["literal_count"])
        match_count = int(event["match_count"])
        runtime_grammar["block_count"] += 1
        minimum = runtime_grammar["minimum_literal_count"]
        runtime_grammar["minimum_literal_count"] = (
            literal_count
            if minimum is None
            else min(minimum, literal_count)
        )
        runtime_grammar["zero_literal_block_count"] += int(
            literal_count == 0
        )
        runtime_grammar["nonfinal_zero_match_block_count"] += int(
            match_count == 0
            and int(event["output_offset"]) + literal_count
            < len(original.output)
        )

    round_trip = decode(encoded, trace_sink=inspect_block)
    exact = round_trip.output == original.output
    game_grammar_compatible = (
        runtime_grammar["zero_literal_block_count"] == 0
        and runtime_grammar["nonfinal_zero_match_block_count"] == 0
    )
    deterministic_flags = flags_for_size(len(original.output))
    return {
        "domain": domain,
        "id": identifier,
        "classification": (
            "complete_stream"
            if reconstruction_safe
            else "stream_prefix_with_preserved_outer_tail"
        ),
        "reconstruction_safe": reconstruction_safe,
        "slice_size": len(compressed_slice),
        "slice_sha256": sha256_bytes(compressed_slice),
        "original_consumed": original.consumed,
        "original_padding": len(trailing),
        "original_padding_all_zero": all(value == 0 for value in trailing),
        "decoded_size": len(original.output),
        "decoded_sha256": sha256_bytes(original.output),
        "original_flags": original.flags,
        "selected_flags": round_trip.flags,
        "expected_flags_for_size": deterministic_flags,
        "flags_match_original": round_trip.flags == original.flags,
        "encoded_size": len(encoded),
        "encoded_sha256": sha256_bytes(encoded),
        "round_trip_exact": exact,
        "game_runtime_grammar": {
            **runtime_grammar,
            "compatible": game_grammar_compatible,
        },
    }


def _archive_slices(
    executable: bytes,
    archive: bytes,
    spec_name: str,
):
    offsets = read_executable_archive_offsets(
        executable,
        CORE_ARCHIVE_SPECS[spec_name],
        len(archive),
    )
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        yield index, archive[start:end]


def aggregate(records) -> dict:
    by_domain = defaultdict(list)
    for record in records:
        by_domain[record["domain"]].append(record)
    domains = {}
    for domain, values in sorted(by_domain.items()):
        tested = [value for value in values if "round_trip_exact" in value]
        domains[domain] = {
            "record_count": len(values),
            "tested_stream_count": len(tested),
            "round_trip_exact_count": sum(
                value["round_trip_exact"] for value in tested
            ),
            "game_runtime_grammar_compatible_count": sum(
                value["game_runtime_grammar"]["compatible"]
                for value in tested
            ),
            "encoded_block_count": sum(
                value["game_runtime_grammar"]["block_count"]
                for value in tested
            ),
            "zero_literal_block_count": sum(
                value["game_runtime_grammar"][
                    "zero_literal_block_count"
                ]
                for value in tested
            ),
            "nonfinal_zero_match_block_count": sum(
                value["game_runtime_grammar"][
                    "nonfinal_zero_match_block_count"
                ]
                for value in tested
            ),
            "reconstruction_safe_count": sum(
                value.get("reconstruction_safe", False) for value in tested
            ),
            "decoded_size": sum(
                value.get("decoded_size", 0) for value in tested
            ),
            "original_consumed": sum(
                value.get("original_consumed", 0) for value in tested
            ),
            "encoded_size": sum(
                value.get("encoded_size", 0) for value in tested
            ),
            "flags_match_original_count": sum(
                value.get("flags_match_original", False) for value in tested
            ),
            "unsupported_count": sum(
                value.get("classification") == "not_decoded_as_stream"
                for value in values
            ),
        }
    return domains


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")

    executable = (DISC_ROOT / "SLPS_258.87").read_bytes()
    records = []

    stage_path = DISC_ROOT / "DATA" / "STAGE.BIN"
    stage_data = stage_path.read_bytes()
    stage_layout = load_offset_layout(args.stage_layout)
    for index, chunk in enumerate(slice_archive(stage_data, stage_layout)):
        records.append(
            validate_stream(
                domain="stage",
                identifier=f"{index:03d}",
                compressed_slice=chunk,
                strategy=args.strategy,
                reconstruction_safe=True,
            )
        )
    print(f"stage: {stage_layout.chunk_count} streams")

    compdata = (DISC_ROOT / "DATA" / "COMPDATA.BN").read_bytes()
    records.append(
        validate_stream(
            domain="compdata",
            identifier="00",
            compressed_slice=compdata,
            strategy=args.strategy,
            reconstruction_safe=True,
        )
    )
    print("compdata: 1 stream")

    mtv_pros = (DISC_ROOT / "DATA" / "MTV_PROS.BIN").read_bytes()
    mtv_count = 0
    for index, chunk in _archive_slices(
        executable,
        mtv_pros,
        "MTV_PROS.BIN",
    ):
        records.append(
            validate_stream(
                domain="mtv_pros",
                identifier=f"{index:02d}",
                compressed_slice=chunk,
                strategy=args.strategy,
                reconstruction_safe=True,
            )
        )
        mtv_count += 1
    print(f"mtv_pros: {mtv_count} streams")

    vt1 = (DISC_ROOT / "DATA" / "VT1.BIN").read_bytes()
    vt1_counts = Counter()
    for index, chunk in _archive_slices(executable, vt1, "VT1.BIN"):
        try:
            decoded = decode(chunk)
        except SrwzCodecError as error:
            records.append(
                {
                    "domain": "vt1",
                    "id": f"{index:02d}",
                    "classification": "not_decoded_as_stream",
                    "slice_size": len(chunk),
                    "slice_sha256": sha256_bytes(chunk),
                    "error": str(error),
                    "error_offset": error.offset,
                }
            )
            vt1_counts["not_decoded_as_stream"] += 1
            continue
        trailing = chunk[decoded.consumed:]
        reconstruction_safe = all(value == 0 for value in trailing)
        classification = (
            "complete_stream"
            if reconstruction_safe
            else "stream_prefix_with_preserved_outer_tail"
        )
        vt1_counts[classification] += 1
        records.append(
            validate_stream(
                domain="vt1",
                identifier=f"{index:02d}",
                compressed_slice=chunk,
                strategy=args.strategy,
                reconstruction_safe=reconstruction_safe,
            )
        )
    print(
        "vt1:",
        " ".join(
            f"{name}={count}" for name, count in sorted(vt1_counts.items())
        ),
    )

    domains = aggregate(records)
    tested = [
        record for record in records if "round_trip_exact" in record
    ]
    failures = [
        record
        for record in tested
        if (
            not record["round_trip_exact"]
            or not record["game_runtime_grammar"]["compatible"]
        )
    ]
    report = {
        "schema_version": 1,
        "content_policy": (
            "Hashes and aggregate sizes only; encoded and decoded game bytes "
            "are not saved."
        ),
        "strategy": args.strategy,
        "encoder_contract": {
            "header_unknown_1": 0,
            "flags_rule": (
                "smallest observed odd flag whose power-of-two window "
                "covers the decoded size, capped at 8 MiB"
            ),
            "archive_padding": "not emitted by codec encoder",
            "game_core_virtual_address": "0x001C6D70",
            "literal_copy_loop_virtual_address": "0x001C6DE8",
            "game_runtime_grammar": {
                "literal_count": "at least one in every block",
                "match_count": (
                    "at least one unless literals finish declared output"
                ),
                "reason": (
                    "the original game uses post-tested literal and match "
                    "copy loops"
                ),
            },
            "runtime_acceptance": (
                "grammar checked here; PCSX2/PINE acceptance is separate"
            ),
        },
        "sources": {
            "SLPS_258.87": sha256_bytes(executable),
            "DATA/STAGE.BIN": sha256_bytes(stage_data),
            "DATA/COMPDATA.BN": sha256_bytes(compdata),
            "DATA/MTV_PROS.BIN": sha256_bytes(mtv_pros),
            "DATA/VT1.BIN": sha256_bytes(vt1),
        },
        "totals": {
            "record_count": len(records),
            "tested_stream_count": len(tested),
            "round_trip_exact_count": sum(
                record["round_trip_exact"] for record in tested
            ),
            "game_runtime_grammar_compatible_count": sum(
                record["game_runtime_grammar"]["compatible"]
                for record in tested
            ),
            "encoded_block_count": sum(
                record["game_runtime_grammar"]["block_count"]
                for record in tested
            ),
            "zero_literal_block_count": sum(
                record["game_runtime_grammar"][
                    "zero_literal_block_count"
                ]
                for record in tested
            ),
            "nonfinal_zero_match_block_count": sum(
                record["game_runtime_grammar"][
                    "nonfinal_zero_match_block_count"
                ]
                for record in tested
            ),
            "failure_count": len(failures),
            "decoded_size": sum(
                record["decoded_size"] for record in tested
            ),
            "original_consumed": sum(
                record["original_consumed"] for record in tested
            ),
            "encoded_size": sum(
                record["encoded_size"] for record in tested
            ),
            "flags_match_original_count": sum(
                record["flags_match_original"] for record in tested
            ),
        },
        "domains": domains,
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"round-trip: {report['totals']['round_trip_exact_count']}/"
        f"{report['totals']['tested_stream_count']} exact; "
        f"flags={report['totals']['flags_match_original_count']}/"
        f"{report['totals']['tested_stream_count']}"
    )
    print(f"json: {output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
