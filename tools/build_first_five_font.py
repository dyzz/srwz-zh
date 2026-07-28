#!/usr/bin/env python3
"""Build the first-five-stage VT1 font and SLPS offset-table candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.canary import rasterize_character, rasterizer_point_size
from srwz.codec import decode, reencode_changed_suffix
from srwz.diagnostics import require_work_output
from srwz.font import (
    GLYPH_COUNT,
    GLYPH_SIZE,
    decode_vt1_font_segment,
    glyph_index_for_code,
    read_extended_glyph_table,
    replace_glyph,
    sha256_bytes,
)
from srwz.font_profile import FontProfileError, load_font_profile
from srwz.font_source import (
    FontSourceError,
    load_font_lock,
    verify_font_lock_files,
)
from srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    read_executable_archive_offsets,
)
from srwz.writeback import replace_archive_chunk_with_preceding_zero_slack
from srwz.writers import build_executable_offset_patch_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
PROPOSAL = WORK_ROOT / "writeback/first-five-codebook-proposal.json"
OUTPUT_ROOT = WORK_ROOT / "build/first-five/components"
FONT_CONFIG = PROJECT_ROOT / "config/fonts/first-five-font.json"
ALLOCATION_REGISTRY = PROJECT_ROOT / "config/encoding/first-five-allocations.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", type=Path, default=PROPOSAL)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--font-config", type=Path, default=FONT_CONFIG)
    parser.add_argument(
        "--allocation-registry",
        type=Path,
        default=ALLOCATION_REGISTRY,
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    proposal_path = require_work_output(args.proposal, WORK_ROOT)
    output_root = require_work_output(args.output_root, WORK_ROOT)
    font_config_path = args.font_config.resolve()
    allocation_registry_path = args.allocation_registry.resolve()
    report_path = output_root / "font-validation.json"
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    if proposal.get("status") != "static_proposal_not_runtime_verified":
        raise SystemExit("codebook proposal status is invalid")
    try:
        profile = load_font_profile(PROJECT_ROOT, font_config_path)
        font_lock = load_font_lock(PROJECT_ROOT / profile["font_lock"])
        locked_paths = verify_font_lock_files(
            PROJECT_ROOT,
            WORK_ROOT,
            font_lock,
        )
    except (FontProfileError, FontSourceError) as error:
        raise SystemExit(str(error)) from error
    if proposal.get("font_source") != {
        "family": font_lock["family"],
        "version": font_lock["version"],
        "commit": font_lock["commit"],
        "font_sha256": font_lock["font"]["sha256"],
        "license_spdx": font_lock["license"]["spdx"],
        "license_sha256": font_lock["license"]["sha256"],
    }:
        raise SystemExit("font proposal source does not match font lock")
    if proposal.get("selection_policy") != profile["scope"]:
        raise SystemExit("font proposal selection policy drift")
    if proposal.get("allocation_registry", {}).get("sha256") != (
        sha256_bytes(allocation_registry_path.read_bytes())
    ):
        raise SystemExit("font proposal allocation registry drift")
    font_path = locked_paths["font"]
    rasterizer = profile["rasterizer"]
    if proposal.get("rasterizer") != rasterizer:
        raise SystemExit("font proposal rasterizer config drift")
    slps_path = WORK_ROOT / "disc/SLPS_258.87"
    vt1_path = WORK_ROOT / "disc/DATA/VT1.BIN"
    source_slps = slps_path.read_bytes()
    source_vt1 = vt1_path.read_bytes()
    original_font = decode_vt1_font_segment(source_slps, source_vt1)
    modified_font = original_font.decoded
    extended_entries = read_extended_glyph_table(source_slps)
    seen_codes = set()
    seen_glyphs = set()
    unchanged_assignment_glyphs = set()
    glyph_reports = []

    for assignment in proposal["assignments"]:
        character = assignment["character"]
        code = int(assignment["code"], 16)
        glyph_index = assignment["glyph_index"]
        if (
            code in seen_codes
            or glyph_index in seen_glyphs
            or glyph_index_for_code(code, extended_entries) != glyph_index
            or not 0 <= glyph_index < GLYPH_COUNT
        ):
            raise SystemExit(f"invalid assignment for {character!r}")
        seen_codes.add(code)
        seen_glyphs.add(glyph_index)
        start = glyph_index * GLYPH_SIZE
        before = original_font.decoded[start : start + GLYPH_SIZE]
        expected_preimage = assignment["allocation"]["glyph_preimage_sha256"]
        if sha256_bytes(before) != expected_preimage:
            raise SystemExit(f"glyph preimage drift for {character!r}")
        expected_blank = assignment["allocation"].get("glyph_preimage_all_zero")
        if expected_blank is not None and expected_blank != (not any(before)):
            raise SystemExit(
                f"glyph blank-preimage classification drift for {character!r}"
            )
        gray, pixels, packed = rasterize_character(
            rasterizer["executable"],
            font_path,
            character,
            rasterizer,
        )
        actual_raster = {
            "point_size": rasterizer_point_size(
                character,
                rasterizer,
            ),
            "raw_gray_sha256": sha256_bytes(gray),
            "pixels_4bpp_sha256": sha256_bytes(pixels),
            "packed_glyph_sha256": sha256_bytes(packed),
        }
        if actual_raster != assignment["raster"]:
            raise SystemExit(f"raster lock drift for {character!r}")
        if before == packed:
            unchanged_assignment_glyphs.add(glyph_index)
        modified_font = replace_glyph(modified_font, glyph_index, pixels)
        glyph_reports.append(
            {
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "glyph_preimage_sha256": expected_preimage,
                **actual_raster,
            }
        )

    changed_glyphs = [
        index
        for index in range(GLYPH_COUNT)
        if original_font.decoded[index * GLYPH_SIZE : (index + 1) * GLYPH_SIZE]
        != modified_font[index * GLYPH_SIZE : (index + 1) * GLYPH_SIZE]
    ]
    if changed_glyphs != sorted(seen_glyphs - unchanged_assignment_glyphs):
        raise SystemExit("font changed outside proposed glyph assignments")

    spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
    old_offsets = read_executable_archive_offsets(
        source_slps,
        spec,
        len(source_vt1),
    )
    index = 2
    source_stream = source_vt1[old_offsets[index] : old_offsets[index + 1]]
    greedy_font = reencode_changed_suffix(source_stream, modified_font)
    lazy_font = reencode_changed_suffix(
        source_stream,
        modified_font,
        lazy_matching=True,
    )
    encoded_font = min(
        (greedy_font, lazy_font),
        key=lambda candidate: (len(candidate), candidate),
    )
    selected_strategy = "lazy_greedy" if encoded_font is lazy_font else "greedy"
    round_trip = decode(encoded_font)
    if round_trip.output != modified_font or round_trip.consumed != len(encoded_font):
        raise SystemExit("font codec round-trip mismatch")
    rebuilt_vt1, rebuilt_offsets, padding, borrowed = (
        replace_archive_chunk_with_preceding_zero_slack(
            source_vt1,
            old_offsets,
            chunk_index=index,
            replacement=encoded_font,
        )
    )
    plan = build_executable_offset_patch_plan(
        source_slps,
        spec,
        rebuilt_offsets,
    )
    rebuilt_slps = plan.apply(source_slps)
    if (
        read_executable_archive_offsets(
            rebuilt_slps,
            spec,
            len(rebuilt_vt1),
        )
        != rebuilt_offsets
    ):
        raise SystemExit("VT1 offsets fail SLPS reread")
    reread_font = decode_vt1_font_segment(rebuilt_slps, rebuilt_vt1)
    if reread_font.decoded != modified_font:
        raise SystemExit("rebuilt VT1 font reread mismatch")

    report = {
        "schema_version": 1,
        "status": "offline_font_validated_runtime_not_tested",
        "assignment_count": len(glyph_reports),
        "allocation_assignment_count": proposal["allocation_assignment_count"],
        "reraster_existing_assignment_count": proposal[
            "reraster_existing_assignment_count"
        ],
        "changed_glyph_count": len(changed_glyphs),
        "unchanged_assignment_count": len(unchanged_assignment_glyphs),
        "allocation_registry": proposal["allocation_registry"],
        "font_source": proposal["font_source"],
        "selection_policy": proposal["selection_policy"],
        "rasterizer": rasterizer,
        "glyphs": glyph_reports,
        "font": {
            "decoded_size": len(modified_font),
            "source_decoded_sha256": sha256_bytes(original_font.decoded),
            "output_decoded_sha256": sha256_bytes(modified_font),
            "source_encoded_size": original_font.consumed,
            "output_encoded_size": len(encoded_font),
            "greedy_encoded_size": len(greedy_font),
            "lazy_greedy_encoded_size": len(lazy_font),
            "selected_encoder_strategy": selected_strategy,
            "codec_round_trip_exact": True,
        },
        "archive": {
            "source_size": len(source_vt1),
            "output_size": len(rebuilt_vt1),
            "padding_size": padding,
            "borrowed_preceding_zero_slack": borrowed,
            "offset_reread_exact": True,
        },
        "outputs": {
            "slps": {
                "size": len(rebuilt_slps),
                "sha256": sha256_bytes(rebuilt_slps),
            },
            "vt1": {
                "size": len(rebuilt_vt1),
                "sha256": sha256_bytes(rebuilt_vt1),
            },
        },
        "runtime_acceptance": "not tested",
    }
    for path, data in (
        (output_root / "SLPS_258.87", rebuilt_slps),
        (output_root / "DATA/VT1.BIN", rebuilt_vt1),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"{proposal['proposal_id']} font:",
        f"glyphs={len(glyph_reports)}",
        f"VT1={len(source_vt1)}->{len(rebuilt_vt1)}",
        "round-trip=exact",
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
