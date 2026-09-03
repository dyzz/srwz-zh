#!/usr/bin/env python3
"""Build a VT1 font and matching SLPS offset-table component."""

from __future__ import annotations

import argparse
import json
import os
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from srwz.font_rasterizer import rasterize_character, rasterizer_point_size
from srwz.codec import decode_production as decode, reencode_changed_suffix
from srwz.diagnostics import require_work_output
from srwz.font import (
    GLYPH_COUNT,
    GLYPH_SIZE,
    ascii_glyph_index,
    decode_vt1_font_segment,
    glyph_raster_metrics,
    glyph_index_for_code,
    read_extended_glyph_table,
    replace_glyph,
    sha256_bytes,
    standard_glyph_index,
)
from srwz.font_profile import FontProfileError, load_font_profile
from srwz.font_source import (
    FontSourceError,
    font_source_metadata,
    load_font_lock,
    verify_font_fallbacks,
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
PROPOSAL = WORK_ROOT / "writeback/zh-release-codebook-proposal.json"
OUTPUT_ROOT = WORK_ROOT / "build/zh-release-font/components"
FONT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"
ALLOCATION_REGISTRY = (
    PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json"
)
MAX_RASTER_WORKERS = 6
DEFAULT_RASTER_WORKERS = min(
    MAX_RASTER_WORKERS,
    max(1, (os.cpu_count() or 1) // 2),
)


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
    parser.add_argument(
        "--raster-workers",
        type=int,
        default=DEFAULT_RASTER_WORKERS,
        help=(
            "Rasterize independent glyphs concurrently; use 1 for the "
            f"serial reference path (default: {DEFAULT_RASTER_WORKERS})."
        ),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.raster_workers < 1:
        parser.error("--raster-workers must be at least 1")
    return args


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
        fallback_font_paths, fallback_font_reports = verify_font_fallbacks(
            PROJECT_ROOT,
            WORK_ROOT,
            profile["unsupported_character_fallbacks"],
        )
    except (FontProfileError, FontSourceError) as error:
        raise SystemExit(str(error)) from error
    if proposal.get("font_source") != font_source_metadata(font_lock):
        raise SystemExit("font proposal source does not match font lock")
    if proposal.get("font_flavor") != profile["font_flavor"]:
        raise SystemExit("font proposal flavor does not match global config")
    if proposal.get("unsupported_character_fallbacks", []) != list(
        fallback_font_reports
    ):
        raise SystemExit("font proposal fallback sources do not match config")
    if proposal.get("selection_policy") != profile["scope"]:
        raise SystemExit("font proposal selection policy drift")
    if proposal.get("allocation_registry", {}).get("sha256") != (
        sha256_bytes(allocation_registry_path.read_bytes())
    ):
        raise SystemExit("font proposal allocation registry drift")
    allocation_registry = json.loads(
        allocation_registry_path.read_text(encoding="utf-8")
    )
    font_path = locked_paths["font"]
    rasterizer = profile["rasterizer"]
    if proposal.get("rasterizer") != rasterizer:
        raise SystemExit("font proposal rasterizer config drift")
    slps_path = WORK_ROOT / "disc/SLPS_258.87"
    vt1_path = WORK_ROOT / "disc/DATA/VT1.BIN"
    source_slps = slps_path.read_bytes()
    source_vt1 = vt1_path.read_bytes()
    original_font = decode_vt1_font_segment(
        source_slps,
        source_vt1,
        decoder=decode,
    )
    modified_font = original_font.decoded
    extended_entries = read_extended_glyph_table(source_slps)
    seen_codes = set()
    seen_glyphs = set()
    glyph_characters = {}
    unchanged_assignment_glyphs = set()
    preserved_source_compatibility_glyphs = set()
    preserved_stock_primary_glyphs = set()
    glyph_reports = []

    primary_assignments = proposal["assignments"]
    surface_alias_assignments = proposal.get("surface_alias_assignments", [])
    if not isinstance(surface_alias_assignments, list):
        raise SystemExit("surface alias assignments are malformed")
    source_compatibility_assignments = proposal.get(
        "source_compatibility_assignments", []
    )
    if not isinstance(source_compatibility_assignments, list):
        raise SystemExit("source compatibility assignments are malformed")
    runtime_ascii_assignments = proposal.get("runtime_ascii_assignments", [])
    if not isinstance(runtime_ascii_assignments, list):
        raise SystemExit("runtime ASCII assignments are malformed")
    all_assignments = [
        *primary_assignments,
        *surface_alias_assignments,
        *source_compatibility_assignments,
        *runtime_ascii_assignments,
    ]

    raster_assignments = [
        assignment
        for assignment in all_assignments
        if assignment.get("preserve_source_glyph") is not True
    ]

    def rasterize_assignment(assignment: dict) -> tuple[bytes, bytes, bytes]:
        character = assignment["character"]
        return rasterize_character(
            rasterizer["executable"],
            fallback_font_paths.get(character, font_path),
            character,
            rasterizer,
        )

    if args.raster_workers == 1:
        raster_results = list(map(rasterize_assignment, raster_assignments))
    else:
        with ThreadPoolExecutor(
            max_workers=min(args.raster_workers, len(raster_assignments)),
            thread_name_prefix="srwz-font-raster",
        ) as executor:
            raster_results = list(
                executor.map(rasterize_assignment, raster_assignments)
            )
    raster_results_by_assignment = {
        id(assignment): result
        for assignment, result in zip(raster_assignments, raster_results)
    }

    for assignment in all_assignments:
        character = assignment["character"]
        code = int(assignment["code"], 16)
        glyph_index = assignment["glyph_index"]
        resolved_glyph_index = (
            ascii_glyph_index(code)
            if assignment.get("mapping")
            in {"printable_ascii", "runtime_ascii_reraster"}
            else glyph_index
            if assignment.get("mapping") == "extended_shared_glyph_alias"
            else glyph_index_for_code(code, extended_entries)
        )
        repeated_runtime_digit_slot = (
            glyph_index in seen_glyphs
            and assignment.get("mapping") == "runtime_ascii_reraster"
            and isinstance(
                assignment.get("overwrites_primary_character"), str
            )
        )
        repeated_shared_glyph_alias = (
            glyph_index in seen_glyphs
            and assignment.get("mapping") == "extended_shared_glyph_alias"
            and glyph_characters.get(glyph_index) == character
        )
        if (
            code in seen_codes
            or (
                glyph_index in seen_glyphs
                and not repeated_runtime_digit_slot
                and not repeated_shared_glyph_alias
            )
            or resolved_glyph_index != glyph_index
            or not 0 <= glyph_index < GLYPH_COUNT
        ):
            raise SystemExit(f"invalid assignment for {character!r}")
        seen_codes.add(code)
        seen_glyphs.add(glyph_index)
        glyph_characters.setdefault(glyph_index, character)
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
        optical_override = assignment.get("optical_override")
        if optical_override is not None:
            raise SystemExit(
                f"character-specific optical override is forbidden for "
                f"{character!r}"
            )
        preserve_source_glyph = assignment.get("preserve_source_glyph") is True
        if preserve_source_glyph:
            preserve_stock_primary = (
                assignment.get("preserve_original_stock_primary") is True
            )
            valid_source_compatibility = (
                assignment in source_compatibility_assignments
                and assignment.get("source_character") == character
                and assignment.get("mapping")
                == "legacy_save_formation_source_compatibility"
            )
            valid_stock_primary = (
                preserve_stock_primary
                and assignment in primary_assignments
                and 0x8140 <= code <= 0x8491
            )
            if not (valid_source_compatibility or valid_stock_primary):
                raise SystemExit(
                    f"invalid source-glyph preservation request for {character!r}"
                )
            packed = before
            actual_raster = {
                "mode": "preserve_original_iso_glyph",
                "packed_glyph_sha256": sha256_bytes(before),
            }
            if valid_source_compatibility:
                preserved_source_compatibility_glyphs.add(glyph_index)
            else:
                preserved_stock_primary_glyphs.add(glyph_index)
        else:
            assignment_rasterizer = rasterizer
            gray, pixels, packed = raster_results_by_assignment[id(assignment)]
            if not character.isspace() and not any(packed):
                raise SystemExit(
                    "visible glyph raster is empty; add an explicit global "
                    f"fallback for {character!r}"
                )
            actual_raster = {
                "point_size": rasterizer_point_size(
                    character,
                    assignment_rasterizer,
                ),
                "raw_gray_sha256": sha256_bytes(gray),
                "pixels_4bpp_sha256": sha256_bytes(pixels),
                "packed_glyph_sha256": sha256_bytes(packed),
            }
            if "metrics" in assignment["raster"]:
                actual_raster["metrics"] = glyph_raster_metrics(pixels)
        if actual_raster != assignment["raster"]:
            raise SystemExit(f"raster lock drift for {character!r}")
        if before == packed:
            unchanged_assignment_glyphs.add(glyph_index)
        if not preserve_source_glyph:
            modified_font = replace_glyph(modified_font, glyph_index, pixels)
        glyph_reports.append(
            {
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "glyph_preimage_sha256": expected_preimage,
                **actual_raster,
                **(
                    {"optical_override": optical_override}
                    if optical_override is not None
                    else {}
                ),
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

    clean_migrations = [
        extension["clean_default_width_cjk_primary_migration"]
        for extension in allocation_registry.get("extensions", [])
        if "clean_default_width_cjk_primary_migration" in extension
    ]
    if len(clean_migrations) != 1:
        raise SystemExit("clean CJK-primary migration contract is absent")
    restored_low_slots = [
        row
        for row in clean_migrations[0]["migrations"]
        if 0x8140 <= int(row["from_code"], 16) <= 0x8491
    ]
    expected_restored_low_slots = clean_migrations[0].get(
        "restored_low_zone_cjk_slot_count", 0
    ) + clean_migrations[0].get("restored_low_zone_nonstock_slot_count", 0)
    if len(restored_low_slots) != expected_restored_low_slots:
        raise SystemExit("clean CJK-primary restored-slot inventory drift")
    for row in restored_low_slots:
        glyph_index = row["from_glyph_index"]
        start = glyph_index * GLYPH_SIZE
        end = start + GLYPH_SIZE
        if modified_font[start:end] != original_font.decoded[start:end]:
            raise SystemExit(
                "low-zone stock glyph was not restored: "
                f"{row['from_code']}={row['character']}"
            )
    low_zone_glyph_indices = []
    for code in range(0x8140, 0x8492):
        try:
            glyph_index = standard_glyph_index(code)
        except ValueError:
            continue
        low_zone_glyph_indices.append(glyph_index)
        start = glyph_index * GLYPH_SIZE
        end = start + GLYPH_SIZE
        if modified_font[start:end] != original_font.decoded[start:end]:
            raise SystemExit(
                f"complete low-zone glyph restoration failed: {code:04X}"
            )

    spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
    old_offsets = read_executable_archive_offsets(
        source_slps,
        spec,
        len(source_vt1),
    )
    index = 2
    source_stream = source_vt1[old_offsets[index] : old_offsets[index + 1]]
    codec = profile["codec"]
    encoded_font = reencode_changed_suffix(
        source_stream,
        modified_font,
        strategy=codec["strategy"],
        min_match_length=codec["min_match_length"],
        max_match_chain=codec["max_match_chain"],
        lazy_matching=codec["lazy_matching"],
    )
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
    extended_alias_reports = []
    if any(
        assignment.get("mapping") == "extended_shared_glyph_alias"
        for assignment in surface_alias_assignments
    ):
        patched_slps = bytearray(rebuilt_slps)
        source_entries_by_offset = {
            entry.table_offset: entry for entry in extended_entries
        }
        for assignment in surface_alias_assignments:
            if assignment.get("mapping") != "extended_shared_glyph_alias":
                continue
            table_offset = assignment.get("extended_table_offset")
            source_code_text = assignment.get("extended_table_source_code")
            source_entry = source_entries_by_offset.get(table_offset)
            if (
                source_entry is None
                or not isinstance(source_code_text, str)
                or source_entry.code != int(source_code_text, 16)
                or source_entry.code >= 0x989F
            ):
                raise SystemExit("extended shared glyph alias preimage drift")
            glyph_index = assignment["glyph_index"]
            row, packed_position = divmod(glyph_index, 224)
            if not 0 <= row <= 0x7F or not 0 <= packed_position <= 0xFF:
                raise SystemExit("extended shared glyph alias index overflow")
            struct.pack_into(
                "<HbB",
                patched_slps,
                table_offset,
                int(assignment["code"], 16),
                row,
                packed_position,
            )
            extended_alias_reports.append(
                {
                    "character": assignment["character"],
                    "code": assignment["code"],
                    "glyph_index": glyph_index,
                    "table_offset": table_offset,
                    "replaced_unreachable_code": source_code_text,
                }
            )
        rebuilt_slps = bytes(patched_slps)
        reread_extended = {
            entry.code: entry.glyph_index
            for entry in read_extended_glyph_table(rebuilt_slps)
        }
        if any(
            reread_extended.get(int(item["code"], 16)) != item["glyph_index"]
            for item in extended_alias_reports
        ):
            raise SystemExit("extended shared glyph aliases fail SLPS reread")
    if (
        read_executable_archive_offsets(
            rebuilt_slps,
            spec,
            len(rebuilt_vt1),
        )
        != rebuilt_offsets
    ):
        raise SystemExit("VT1 offsets fail SLPS reread")
    reread_font = decode_vt1_font_segment(
        rebuilt_slps,
        rebuilt_vt1,
        decoder=decode,
    )
    if reread_font.decoded != modified_font:
        raise SystemExit("rebuilt VT1 font reread mismatch")

    report = {
        "schema_version": 1,
        "status": "offline_font_validated_runtime_not_tested",
        "assignment_count": len(glyph_reports),
        "primary_assignment_count": len(primary_assignments),
        "surface_alias_assignment_count": len(surface_alias_assignments),
        "source_compatibility_assignment_count": len(
            source_compatibility_assignments
        ),
        "preserved_source_compatibility_glyph_count": len(
            preserved_source_compatibility_glyphs
        ),
        "source_compatibility_glyphs_byte_exact_to_original_iso": (
            len(preserved_source_compatibility_glyphs)
            == len(source_compatibility_assignments)
        ),
        "preserved_stock_primary_glyph_count": len(
            preserved_stock_primary_glyphs
        ),
        "restored_low_zone_stock_glyph_count": len(restored_low_slots),
        "low_zone_stock_glyphs_byte_exact_to_original_iso": True,
        "complete_low_zone_stock_glyph_count": len(low_zone_glyph_indices),
        "complete_low_zone_byte_exact_to_original_iso": True,
        "runtime_ascii_assignment_count": len(runtime_ascii_assignments),
        "allocation_assignment_count": proposal["allocation_assignment_count"],
        "reraster_existing_assignment_count": proposal[
            "reraster_existing_assignment_count"
        ],
        "changed_glyph_count": len(changed_glyphs),
        "unchanged_assignment_count": len(unchanged_assignment_glyphs),
        "allocation_registry": proposal["allocation_registry"],
        "font_source": proposal["font_source"],
        **(
            {"font_flavor": proposal["font_flavor"]}
            if proposal.get("font_flavor") is not None
            else {}
        ),
        "unsupported_character_fallbacks": proposal.get(
            "unsupported_character_fallbacks",
            [],
        ),
        "selection_policy": proposal["selection_policy"],
        "rasterizer": rasterizer,
        **(
            {"surface_safe_aliases": proposal["surface_safe_aliases"]}
            if surface_alias_assignments
            else {}
        ),
        **(
            {"runtime_ascii_reraster": proposal["runtime_ascii_reraster"]}
            if runtime_ascii_assignments
            else {}
        ),
        "glyphs": glyph_reports,
        "extended_shared_glyph_aliases": {
            "assignment_count": len(extended_alias_reports),
            "aliases": extended_alias_reports,
            "source_standard_codes_remain_formula_addressable": True,
            "slps_table_reread_exact": True,
        },
        "font": {
            "decoded_size": len(modified_font),
            "source_decoded_sha256": sha256_bytes(original_font.decoded),
            "output_decoded_sha256": sha256_bytes(modified_font),
            "source_encoded_size": original_font.consumed,
            "output_encoded_size": len(encoded_font),
            "selected_encoder_strategy": codec["strategy"],
            "min_match_length": codec["min_match_length"],
            "max_match_chain": codec["max_match_chain"],
            "lazy_matching": codec["lazy_matching"],
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
