#!/usr/bin/env python3
"""Dry-run real STAGE and MTV_PROS writers entirely in memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from srwz.archive import load_offset_layout, slice_archive
from srwz.codec import decode
from srwz.diagnostics import require_work_output
from srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    read_executable_archive_offsets,
)
from srwz.summary import parse_summary
from srwz.text import load_text_table
from srwz.writers import (
    build_executable_offset_patch_plan,
    build_summary_patch_plan,
    rebuild_codec_archive,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DISC_ROOT = WORK_ROOT / "disc"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Decode real archives, exercise fixed-allocation text plans, "
            "re-encode every chunk, rebuild aligned archives and verify "
            "the resulting SLPS offset table in memory."
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
        "--text-table",
        type=Path,
        default=(
            PROJECT_ROOT
            / "vendor"
            / "upstream-python"
            / "project"
            / "tbl_all.json"
        ),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=WORK_ROOT / "writeback" / "archive-rebuild-validation.json",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")

    executable_path = DISC_ROOT / "SLPS_258.87"
    executable = executable_path.read_bytes()

    stage_path = DISC_ROOT / "DATA" / "STAGE.BIN"
    stage_source = stage_path.read_bytes()
    stage_layout = load_offset_layout(args.stage_layout)
    stage_decoded = tuple(
        decode(chunk).output
        for chunk in slice_archive(stage_source, stage_layout)
    )
    stage_rebuilt = rebuild_codec_archive(
        stage_decoded,
        strategy=args.strategy,
    )
    stage_table = b"".join(
        struct.pack("<I", offset) for offset in stage_rebuilt.offsets
    )
    print(
        "stage:",
        f"chunks={stage_rebuilt.chunk_count}",
        f"old={len(stage_source)}",
        f"new={len(stage_rebuilt.data)}",
    )

    mtv_path = DISC_ROOT / "DATA" / "MTV_PROS.BIN"
    mtv_source = mtv_path.read_bytes()
    mtv_spec = CORE_ARCHIVE_SPECS["MTV_PROS.BIN"]
    mtv_offsets = read_executable_archive_offsets(
        executable,
        mtv_spec,
        len(mtv_source),
    )
    table = load_text_table(args.text_table)
    mtv_decoded = []
    summary_entry_count = 0
    summary_plan_operation_count = 0
    summary_identity_exact_count = 0
    for chunk_index, (start, end) in enumerate(
        zip(mtv_offsets, mtv_offsets[1:])
    ):
        decoded = decode(mtv_source[start:end]).output
        parsed = parse_summary(
            decoded,
            table,
            chunk_index=chunk_index,
        )
        replacements = {
            entry.entry_id: entry.text for entry in parsed.entries
        }
        plan = build_summary_patch_plan(
            decoded,
            table,
            chunk_index=chunk_index,
            replacements=replacements,
        )
        written = plan.apply(decoded)
        parse_summary(written, table, chunk_index=chunk_index)
        summary_entry_count += len(parsed.entries)
        summary_plan_operation_count += len(plan.operations)
        summary_identity_exact_count += written == decoded
        mtv_decoded.append(written)

    mtv_rebuilt = rebuild_codec_archive(
        mtv_decoded,
        strategy=args.strategy,
    )
    offset_plan = build_executable_offset_patch_plan(
        executable,
        mtv_spec,
        mtv_rebuilt.offsets,
    )
    patched_executable = offset_plan.apply(executable)
    reread_offsets = read_executable_archive_offsets(
        patched_executable,
        mtv_spec,
        len(mtv_rebuilt.data),
    )
    if reread_offsets != mtv_rebuilt.offsets:
        raise RuntimeError("rebuilt MTV_PROS offsets failed SLPS reread")
    print(
        "mtv_pros:",
        f"chunks={mtv_rebuilt.chunk_count}",
        f"entries={summary_entry_count}",
        f"old={len(mtv_source)}",
        f"new={len(mtv_rebuilt.data)}",
    )

    report = {
        "schema_version": 1,
        "content_policy": (
            "Hashes, counts and aggregate sizes only. Rebuilt game bytes "
            "remain in memory and are not saved."
        ),
        "strategy": args.strategy,
        "runtime_acceptance": "not tested",
        "sources": {
            "SLPS_258.87": sha256_bytes(executable),
            "DATA/STAGE.BIN": sha256_bytes(stage_source),
            "DATA/MTV_PROS.BIN": sha256_bytes(mtv_source),
        },
        "stage": {
            "source_size": len(stage_source),
            "source_sha256": sha256_bytes(stage_source),
            "rebuilt": stage_rebuilt.to_metadata(),
            "decoded_round_trip_exact_count": stage_rebuilt.chunk_count,
            "stage_offset_table_size": len(stage_table),
            "stage_offset_table_sha256": sha256_bytes(stage_table),
            "stage_offset_target": (
                "HEDBDY/HB.BIN + 0x7670; source member not present in work/"
            ),
        },
        "mtv_pros": {
            "source_size": len(mtv_source),
            "source_sha256": sha256_bytes(mtv_source),
            "summary_entry_count": summary_entry_count,
            "summary_plan_operation_count": summary_plan_operation_count,
            "summary_identity_exact_chunk_count": (
                summary_identity_exact_count
            ),
            "rebuilt": mtv_rebuilt.to_metadata(),
            "decoded_round_trip_exact_count": mtv_rebuilt.chunk_count,
            "slps_offset_plan": offset_plan.to_metadata(),
            "slps_offset_reread_exact": True,
            "patched_slps_sha256": sha256_bytes(patched_executable),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"json: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
