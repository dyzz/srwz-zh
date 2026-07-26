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
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.project import load_build_profile
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
        "--story-profile",
        type=Path,
        default=(
            PROJECT_ROOT
            / "config"
            / "build-profiles"
            / "canary-story.json"
        ),
        help=(
            "profile whose SurfaceSpec owns the HB STAGE offset-table range"
        ),
    )
    parser.add_argument(
        "--source-iso",
        type=Path,
        default=PROJECT_ROOT / "rom" / "srwz.iso",
        help="verified original ISO used to read the HB offset-table member",
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
    story_selection = load_build_profile(
        PROJECT_ROOT,
        args.story_profile.resolve(),
    )
    story_surface = story_selection.single_surface()
    if (
        story_surface.source_member != "DATA/STAGE.BIN"
        or story_surface.offset_table_member is None
        or story_surface.offset_table_start is None
        or story_surface.offset_table_end is None
    ):
        raise RuntimeError(
            "story profile has no STAGE/HB offset-table contract"
        )
    hb_spec = ExecutableOffsetSpec(
        name="DATA/STAGE.BIN",
        member=story_surface.offset_table_member,
        table_start=story_surface.offset_table_start,
        table_end=story_surface.offset_table_end,
    )
    source_iso = args.source_iso.resolve()
    source_image = scan_iso9660(source_iso)
    hb_member = member_map(source_image).get(hb_spec.member)
    if hb_member is None:
        raise RuntimeError(f"source ISO has no {hb_spec.member}")
    with source_iso.open("rb") as source:
        source.seek(hb_member.extent_lba * SECTOR_SIZE)
        hb_source = source.read(hb_member.size)
    if len(hb_source) != hb_member.size:
        raise RuntimeError(f"short ISO member read for {hb_spec.member}")
    source_stage_offsets = read_executable_archive_offsets(
        hb_source,
        hb_spec,
        len(stage_source),
    )
    if source_stage_offsets != stage_layout.offsets:
        raise RuntimeError("source HB offsets differ from pinned STAGE layout")
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
    hb_offset_plan = build_executable_offset_patch_plan(
        hb_source,
        hb_spec,
        stage_rebuilt.offsets,
        source_name=hb_spec.member,
    )
    patched_hb = hb_offset_plan.apply(hb_source)
    if read_executable_archive_offsets(
        patched_hb,
        hb_spec,
        len(stage_rebuilt.data),
    ) != stage_rebuilt.offsets:
        raise RuntimeError("rebuilt STAGE offsets failed HB reread")
    print(
        "stage:",
        f"chunks={stage_rebuilt.chunk_count}",
        f"old={len(stage_source)}",
        f"new={len(stage_rebuilt.data)}",
        "hb_offsets=exact",
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
            hb_spec.member: sha256_bytes(hb_source),
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
                f"{hb_spec.member} + 0x{hb_spec.table_start:X}"
            ),
            "hb_offset_plan": hb_offset_plan.to_metadata(),
            "hb_offset_reread_exact": True,
            "patched_hb_sha256": sha256_bytes(patched_hb),
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
