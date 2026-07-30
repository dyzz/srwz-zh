#!/usr/bin/env python3
"""Generate bounded COMPDATA token and encoded-cost statistics."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from srwz.codec import (
    ByteReader,
    _greedy_payload,
    decode,
    encode_coded_integer,
    read_coded_integer,
)
from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
ORIGINAL = PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN"
BUTTONS = (
    PROJECT_ROOT
    / "work/build/compdata-step-01a-p0-buttons/components/DATA/COMPDATA.BN"
)
LEGACY_P0 = (
    PROJECT_ROOT
    / "work/build/ui-p0-fixed-compdata/components/DATA/COMPDATA.BN"
)
OPTIMIZED_P0 = (
    PROJECT_ROOT
    / "work/build/compdata-step-02-p0-menu-inplace/components/DATA/COMPDATA.BN"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/review/compdata-compression-comparison.json"
)
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "manifests/compdata-compression-comparison.json"
)
INTERVAL_SIZE = 16 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bucket(value: int, limits: tuple[int, ...]) -> str:
    lower = 1
    for upper in limits:
        if value <= upper:
            return f"{lower}-{upper}"
        lower = upper + 1
    return f"{lower}+"


def inspect_match(raw: bytes, event: dict) -> dict:
    reader = ByteReader(raw[event["input_offset"] :])
    token = reader.read_byte("match token")
    seed = (token & 0x0F) >> 1
    distance_extension_size = 0
    if token & 1 == 0:
        coded = read_coded_integer(
            reader,
            initial_value=seed,
            context="distance",
        )
        distance_extension_size = coded.size
    length_extension_size = 0
    if token >> 4 == 0:
        coded = read_coded_integer(reader, context="length")
        length_extension_size = coded.size
    distance_value = event["distance"] - 1
    canonical = encode_coded_integer(distance_value)
    compact_seed_eligible = (
        len(canonical) > 1 and canonical[0] >> 1 < 8
    )
    return {
        "seed": seed,
        "distance_extended": token & 1 == 0,
        "distance_extension_size": distance_extension_size,
        "length_extension_size": length_extension_size,
        "compact_seed_eligible": compact_seed_eligible,
        "compact_seed_missed": compact_seed_eligible and seed == 0,
    }


def summarize_stream(path: Path) -> dict:
    raw = path.read_bytes()
    events = []
    result = decode(raw, trace_sink=events.append)
    if result.consumed != len(raw):
        raise ValueError(f"stream has trailing bytes: {path}")
    blocks = [event for event in events if event["kind"] == "block"]
    matches = [event for event in events if event["kind"] == "match"]
    match_by_block = []
    current = None
    for event in events:
        if event["kind"] == "block":
            current = []
            match_by_block.append(current)
        elif event["kind"] == "match":
            current.append(event)

    count_extension_bytes = 0
    interval_costs = Counter()
    for index, block in enumerate(blocks):
        input_end = (
            blocks[index + 1]["input_offset"]
            if index + 1 < len(blocks)
            else result.consumed
        )
        output_end = (
            blocks[index + 1]["output_offset"]
            if index + 1 < len(blocks)
            else result.declared_size
        )
        block_matches = match_by_block[index]
        literal_end_input = (
            block_matches[0]["input_offset"]
            if block_matches
            else input_end
        )
        literal_start_input = literal_end_input - block["literal_count"]
        count_extension_bytes += (
            literal_start_input - block["input_offset"] - 1
        )
        interval = block["output_offset"] // INTERVAL_SIZE
        interval_costs[interval] += input_end - block["input_offset"]
        block["output_end"] = output_end

    distance_extensions = 0
    length_extensions = 0
    embedded_seed_count = 0
    eligible_seed_count = 0
    missed_seed_count = 0
    distance_distribution = Counter()
    length_distribution = Counter()
    for event in matches:
        token = inspect_match(raw, event)
        distance_extensions += token["distance_extension_size"]
        length_extensions += token["length_extension_size"]
        embedded_seed_count += (
            token["distance_extended"] and bool(token["seed"])
        )
        eligible_seed_count += token["compact_seed_eligible"]
        missed_seed_count += token["compact_seed_missed"]
        distance_distribution[
            bucket(event["distance"], (8, 127, 1023, 16383, 131071))
        ] += 1
        length_distribution[
            bucket(event["length"], (4, 16, 64, 256, 1024))
        ] += 1

    literal_bytes = sum(block["literal_count"] for block in blocks)
    match_output_bytes = sum(event["length"] for event in matches)
    cost = {
        "header_bytes": result.header_size,
        "block_control_bytes": len(blocks),
        "block_count_coded_integer_bytes": count_extension_bytes,
        "literal_bytes": literal_bytes,
        "match_token_bytes": len(matches),
        "distance_coded_integer_bytes": distance_extensions,
        "length_coded_integer_bytes": length_extensions,
    }
    if sum(cost.values()) != result.consumed:
        raise AssertionError(f"encoded cost does not sum for {path}")

    interval_rows = []
    interval_count = (
        result.declared_size + INTERVAL_SIZE - 1
    ) // INTERVAL_SIZE
    for index in range(interval_count):
        start = index * INTERVAL_SIZE
        interval_rows.append(
            {
                "decoded_start": start,
                "decoded_end": min(
                    result.declared_size,
                    start + INTERVAL_SIZE,
                ),
                "compressed_bytes_by_block_start": interval_costs[index]
                + (result.header_size if index == 0 else 0),
            }
        )

    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "size": len(raw),
        "sha256": sha256_bytes(raw),
        "decoded_size": result.declared_size,
        "decoded_sha256": sha256_bytes(result.output),
        "flags": result.flags,
        "fully_consumed": True,
        "block_count": len(blocks),
        "literal_bytes": literal_bytes,
        "match_count": len(matches),
        "match_output_bytes": match_output_bytes,
        "distance_distribution": dict(distance_distribution),
        "length_distribution": dict(length_distribution),
        "distance_seed": {
            "eligible_count": eligible_seed_count,
            "embedded_nonzero_count": embedded_seed_count,
            "missed_compact_count": missed_seed_count,
        },
        "encoded_cost_bytes": cost,
        "decoded_intervals": interval_rows,
    }


def build_report() -> dict:
    paths = {
        "original": ORIGINAL,
        "p0_buttons_legacy": BUTTONS,
        "p0_full_legacy": LEGACY_P0,
        "p0_full_size_constrained": OPTIMIZED_P0,
    }
    summaries = {
        name: summarize_stream(path) for name, path in paths.items()
    }
    original_raw = ORIGINAL.read_bytes()
    original = decode(original_raw)
    legacy_p0 = decode(LEGACY_P0.read_bytes())
    first_changed = next(
        index
        for index, (before, after) in enumerate(
            zip(original.output, legacy_p0.output)
        )
        if before != after
    )
    blocks = []

    def collect(event):
        if event["kind"] == "block":
            blocks.append(event)

    decode(original_raw, trace_sink=collect)
    boundary = max(
        (
            event
            for event in blocks
            if event["output_offset"] <= first_changed
        ),
        key=lambda event: event["output_offset"],
    )
    prefix_input = boundary["input_offset"]
    prefix_output = boundary["output_offset"]
    trials = []
    for chain in (64, 256, 4096):
        for lazy in (False, True):
            for compact in (False, True):
                payload = _greedy_payload(
                    original.output,
                    window_size=original.metadata["window_size"],
                    min_match_length=4,
                    max_match_chain=chain,
                    prefix_size=prefix_output,
                    lazy_matching=lazy,
                    compact_distance_seed=compact,
                )
                trials.append(
                    {
                        "max_match_chain": chain,
                        "lazy_matching": lazy,
                        "compact_distance_seed": compact,
                        "suffix_size": len(payload),
                        "full_stream_size": prefix_input + len(payload),
                    }
                )

    original_suffix_size = len(original_raw) - prefix_input
    legacy_trial = next(
        item
        for item in trials
        if item["max_match_chain"] == 256
        and item["lazy_matching"] is True
        and item["compact_distance_seed"] is False
    )
    compact_trial = next(
        item
        for item in trials
        if item["max_match_chain"] == 256
        and item["lazy_matching"] is True
        and item["compact_distance_seed"] is True
    )
    old_p0 = summaries["p0_full_legacy"]["size"]
    new_p0 = summaries["p0_full_size_constrained"]["size"]
    return {
        "schema_version": 1,
        "status": "compdata_compression_loss_quantified_and_budget_met",
        "content_policy": (
            "Hashes, aggregate token counts, bounded distributions and "
            "encoded costs only; no game literals or decoded bytes."
        ),
        "streams": summaries,
        "changed_suffix": {
            "decoded_boundary": prefix_output,
            "compressed_boundary": prefix_input,
            "original_stored_suffix_size": original_suffix_size,
            "legacy_reencoded_original_suffix_size": legacy_trial[
                "suffix_size"
            ],
            "compact_reencoded_original_suffix_size": compact_trial[
                "suffix_size"
            ],
            "legacy_gap_to_original": (
                legacy_trial["suffix_size"] - original_suffix_size
            ),
            "compact_gap_to_original": (
                compact_trial["suffix_size"] - original_suffix_size
            ),
            "bytes_recovered_by_compact_distance_seed": (
                legacy_trial["suffix_size"] - compact_trial["suffix_size"]
            ),
        },
        "strategy_trials": trials,
        "p0_budget": {
            "maximum_output_size": 145408,
            "legacy_size": old_p0,
            "legacy_excess": old_p0 - 145408,
            "size_constrained_size": new_p0,
            "size_constrained_headroom": 145408 - new_p0,
            "bytes_reduced": old_p0 - new_p0,
            "later_member_lba_can_remain_unchanged": new_p0 <= 145408,
        },
        "finding": (
            "The dominant loss was not candidate depth. Legacy suffix "
            "tokens omitted the legal three-bit extended-distance seed; "
            "compact seed packing recovers the sector budget, while bounded "
            "64/256-chain candidates are compared by exact serialized size."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_path = require_work_output(args.report.resolve(), WORK_ROOT)
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    report = build_report()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.refresh_manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif json.loads(args.manifest.read_text(encoding="utf-8")) != report:
        raise SystemExit("compression comparison manifest drift")
    print(
        "COMPDATA compression:",
        f"legacy={report['p0_budget']['legacy_size']}",
        f"optimized={report['p0_budget']['size_constrained_size']}",
        f"headroom={report['p0_budget']['size_constrained_headroom']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
