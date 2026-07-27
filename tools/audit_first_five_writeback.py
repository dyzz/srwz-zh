#!/usr/bin/env python3
"""Build a byte-free first-five-stage font/codebook readiness proposal."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from srwz.canary import rasterize_character, rasterizer_point_size
from srwz.font_source import (
    FontSourceError,
    load_font_lock,
    verify_font_lock_files,
)
from srwz.font import (
    ASCII_FIRST,
    ASCII_LAST,
    GLYPH_SIZE,
    SHIFT_JIS_TRAILS,
    STANDARD_LEAD_END,
    STANDARD_LEAD_START,
    ascii_glyph_index,
    decode_vt1_font_segment,
    extended_glyph_mapping,
    glyph_index_for_code,
    inventory_codebook,
    is_cjk_unified_ideograph,
    read_extended_glyph_table,
    sha256_bytes,
    standard_glyph_index,
)
from srwz.text import (
    PRINTABLE_ASCII,
    SrwzTextEncodeError,
    control_notation_positions,
    encode_text,
    load_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
TEXT_TABLE = (
    PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
)
CODEBOOK = PROJECT_ROOT / "config/encoding/codebook.json"
ALLOCATION_REGISTRY = (
    PROJECT_ROOT / "config/encoding/first-five-allocations.json"
)
FONT_CONFIG = PROJECT_ROOT / "config/fonts/first-five-font.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit first-five-stage encodability and propose deterministic "
            "standard-glyph assignments without modifying game files."
        )
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=WORK_ROOT / "writeback/first-five-readiness.json",
    )
    parser.add_argument(
        "--proposal",
        type=Path,
        default=WORK_ROOT / "writeback/first-five-codebook-proposal.json",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _bounded_work_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(WORK_ROOT.resolve())
    except ValueError as error:
        raise SystemExit(f"output must remain under work/: {path}") from error
    return resolved


def _translation_documents() -> tuple[tuple[str, dict], ...]:
    documents = []
    for stage in range(1, 6):
        documents.append(
            (
                f"dialogue-{stage:03d}",
                json.loads(
                    (
                        PROJECT_ROOT
                        / f"corpus/zh/story-dialogue/stage-{stage:03d}.json"
                    ).read_text(encoding="utf-8")
                ),
            )
        )
    for name in ("story-speakers", "story-conditions"):
        document = json.loads(
            (PROJECT_ROOT / f"corpus/zh/{name}.json").read_text(
                encoding="utf-8"
            )
        )
        document = {
            **document,
            "entries": [
                entry
                for entry in document["entries"]
                if int(entry["id"].split("/")[1]) <= 5
            ],
        }
        documents.append((name, document))
    return tuple(documents)


def _existing_overrides() -> tuple[dict[str, int], set[int], set[int]]:
    document = json.loads(CODEBOOK.read_text(encoding="utf-8"))
    overrides = {}
    codes = set()
    glyphs = set()
    for assignment in document["assignments"]:
        code = int(assignment["code"], 16)
        overrides[assignment["character"]] = code
        codes.add(code)
        glyphs.add(assignment["glyph_index"])
    return overrides, codes, glyphs


def main() -> int:
    args = parse_args()
    report_path = _bounded_work_path(args.report)
    proposal_path = _bounded_work_path(args.proposal)
    for output in (report_path, proposal_path):
        if output.exists() and not args.force:
            raise SystemExit(f"output exists; use --force: {output}")

    table = load_text_table(TEXT_TABLE)
    overrides, existing_codes, existing_glyphs = _existing_overrides()
    character_counts: Counter[str] = Counter()
    character_stages: defaultdict[str, set[int]] = defaultdict(set)
    entry_count = 0
    for _, document in _translation_documents():
        for entry in document["entries"]:
            stage = int(entry["id"].split("/")[1])
            entry_count += 1
            text = entry["translation"]
            controls = control_notation_positions(text)
            for position, character in enumerate(text):
                if position in controls:
                    continue
                character_counts[character] += 1
                character_stages[character].add(stage)

    slps = (WORK_ROOT / "disc/SLPS_258.87").read_bytes()
    extended_entries = read_extended_glyph_table(slps)
    missing = []
    for character in sorted(character_counts):
        if character in overrides:
            continue
        if character in PRINTABLE_ASCII:
            missing.append(character)
            continue
        code = table.inverse_characters.get(character)
        if code is not None:
            try:
                glyph_index_for_code(code, extended_entries)
            except ValueError:
                missing.append(character)
            continue
        try:
            encode_text(character, table, overrides=overrides)
        except SrwzTextEncodeError:
            missing.append(character)

    font_config = json.loads(FONT_CONFIG.read_text(encoding="utf-8"))
    if font_config.get("schema_version") != 1:
        raise SystemExit("unsupported first-five font config")
    rasterizer = font_config["rasterizer"]
    try:
        font_lock = load_font_lock(
            PROJECT_ROOT / font_config["font_lock"]
        )
        locked_paths = verify_font_lock_files(
            PROJECT_ROOT,
            WORK_ROOT,
            font_lock,
        )
    except FontSourceError as error:
        raise SystemExit(str(error)) from error
    font_path = locked_paths["font"]
    vt1 = (WORK_ROOT / "disc/DATA/VT1.BIN").read_bytes()
    original_font = decode_vt1_font_segment(slps, vt1).decoded

    used_glyphs = set()
    for code in table.characters:
        try:
            used_glyphs.add(glyph_index_for_code(code, extended_entries))
        except ValueError:
            pass
    used_glyphs.update(
        ascii_glyph_index(code)
        for code in range(ASCII_FIRST, ASCII_LAST + 1)
    )
    used_glyphs.update(extended_glyph_mapping(extended_entries).values())
    used_glyphs.update(existing_glyphs)

    legacy_candidate_codes = tuple(
        inventory_codebook(table).candidate_unmapped_codes
    )
    legacy_candidate_set = set(legacy_candidate_codes)
    expansion_candidate_codes = tuple(
        (lead << 8) | trail
        for lead in range(STANDARD_LEAD_START, STANDARD_LEAD_END + 1)
        for trail in SHIFT_JIS_TRAILS
        if (lead << 8) | trail not in table.characters
        and (lead << 8) | trail not in legacy_candidate_set
    )

    def usable_candidates(codes: tuple[int, ...]) -> list[tuple[int, int]]:
        result = []
        for code in codes:
            if code in existing_codes:
                continue
            try:
                glyph_index = standard_glyph_index(code)
            except ValueError:
                continue
            if glyph_index in used_glyphs:
                continue
            result.append((code, glyph_index))
        return result

    legacy_candidates = usable_candidates(legacy_candidate_codes)
    expansion_candidates = usable_candidates(expansion_candidate_codes)
    candidates = legacy_candidates + expansion_candidates
    allocation_registry = json.loads(
        ALLOCATION_REGISTRY.read_text(encoding="utf-8")
    )
    if allocation_registry.get("schema_version") != 1:
        raise SystemExit("unsupported first-five allocation registry")
    allocation_characters = tuple(
        allocation_registry["allocated_characters"]
    )
    if len(allocation_characters) != len(set(allocation_characters)):
        raise SystemExit("first-five allocation registry has duplicates")
    retired_characters = set(
        allocation_registry.get("retired_characters", [])
    )
    if not retired_characters <= set(allocation_characters):
        raise SystemExit("retired first-five allocation is not registered")
    unregistered = sorted(set(missing) - set(allocation_characters))
    if unregistered:
        raise SystemExit(
            "new first-five characters must be appended to the allocation "
            f"registry: {''.join(unregistered)}"
        )
    if len(candidates) < len(allocation_characters):
        raise SystemExit(
            "insufficient safe candidates for allocation registry: "
            f"{len(candidates)} < {len(allocation_characters)}"
        )
    allocation_by_character = dict(
        zip(allocation_characters, candidates)
    )

    assignments = []
    for character in missing:
        code, glyph_index = allocation_by_character[character]
        gray, pixels, packed = rasterize_character(
            rasterizer["executable"],
            font_path,
            character,
            rasterizer,
        )
        start = glyph_index * GLYPH_SIZE
        preimage = original_font[start:start + GLYPH_SIZE]
        assignments.append(
            {
                "id": f"first-five-u{ord(character):04x}",
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "mapping": "standard",
                "status": "proposed_allocation",
                "allocation": {
                    "owner": "story/stages-001-005",
                    "basis": (
                        "not referenced by pinned text table, ASCII renderer "
                        "mapping, executable extended table, or existing "
                        "codebook assignments"
                    ),
                    "source_occurrences": character_counts[character],
                    "stage_indices": sorted(character_stages[character]),
                    "glyph_preimage_sha256": sha256_bytes(preimage),
                },
                "raster": {
                    "point_size": rasterizer_point_size(
                        character,
                        rasterizer,
                    ),
                    "raw_gray_sha256": sha256_bytes(gray),
                    "pixels_4bpp_sha256": sha256_bytes(pixels),
                    "packed_glyph_sha256": sha256_bytes(packed),
                },
            }
        )

    allocated_characters = set(missing)
    reraster_existing = []
    for character in sorted(character_counts):
        if (
            not is_cjk_unified_ideograph(character)
            or character in allocated_characters
        ):
            continue
        if character in overrides:
            code = overrides[character]
            mapping = "existing_codebook"
        else:
            code = table.inverse_characters.get(character)
            mapping = "pinned_text_table"
        if code is None:
            continue
        try:
            glyph_index = glyph_index_for_code(code, extended_entries)
        except ValueError:
            continue
        gray, pixels, packed = rasterize_character(
            rasterizer["executable"],
            font_path,
            character,
            rasterizer,
        )
        start = glyph_index * GLYPH_SIZE
        preimage = original_font[start:start + GLYPH_SIZE]
        reraster_existing.append(
            {
                "id": f"first-five-reraster-u{ord(character):04x}",
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "mapping": mapping,
                "status": "proposed_reraster",
                "allocation": {
                    "owner": "story/stages-001-005",
                    "basis": (
                        "existing reachable glyph used by selected Chinese "
                        "translations; rerasterized to avoid mixed font "
                        "sources within one line"
                    ),
                    "source_occurrences": character_counts[character],
                    "stage_indices": sorted(character_stages[character]),
                    "glyph_preimage_sha256": sha256_bytes(preimage),
                },
                "raster": {
                    "point_size": rasterizer_point_size(
                        character,
                        rasterizer,
                    ),
                    "raw_gray_sha256": sha256_bytes(gray),
                    "pixels_4bpp_sha256": sha256_bytes(pixels),
                    "packed_glyph_sha256": sha256_bytes(packed),
                },
            }
        )
    assignments.extend(reraster_existing)
    assignments.sort(
        key=lambda assignment: (
            assignment["glyph_index"],
            assignment["code"],
            assignment["character"],
        )
    )
    assigned_glyphs = [
        assignment["glyph_index"] for assignment in assignments
    ]
    if len(assigned_glyphs) != len(set(assigned_glyphs)):
        raise SystemExit("font proposal assigns one glyph slot more than once")

    proposal = {
        "schema_version": 1,
        "proposal_id": "srwz-first-five-unified-font-v3",
        "status": "static_proposal_not_runtime_verified",
        "stage_indices": [1, 2, 3, 4, 5],
        "font_source": {
            "family": font_lock["family"],
            "version": font_lock["version"],
            "commit": font_lock["commit"],
            "font_sha256": font_lock["font"]["sha256"],
            "license_spdx": font_lock["license"]["spdx"],
            "license_sha256": font_lock["license"]["sha256"],
        },
        "selection_policy": font_config["scope"],
        "rasterizer": rasterizer,
        "allocation_registry": {
            "id": allocation_registry["registry_id"],
            "sha256": sha256_bytes(ALLOCATION_REGISTRY.read_bytes()),
            "registered_character_count": len(allocation_characters),
            "active_character_count": len(missing),
            "retired_characters": sorted(retired_characters),
        },
        "allocation_assignment_count": len(missing),
        "reraster_existing_assignment_count": len(reraster_existing),
        "assignments": assignments,
    }
    report = {
        "schema_version": 1,
        "status": "capacity_passed_allocation_proposed",
        "stage_indices": [1, 2, 3, 4, 5],
        "translation_entry_count": entry_count,
        "unique_character_count": len(character_counts),
        "base_encodable_character_count": (
            len(character_counts) - len(missing)
        ),
        "missing_character_count": len(missing),
        "missing_character_occurrence_count": sum(
            character_counts[character] for character in missing
        ),
        "safe_candidate_slot_count": len(candidates),
        "legacy_safe_candidate_slot_count": len(legacy_candidates),
        "expanded_standard_candidate_slot_count": len(
            expansion_candidates
        ),
        "assigned_candidate_slot_count": len(missing),
        "registered_candidate_slot_count": len(allocation_characters),
        "retired_candidate_slot_count": len(retired_characters),
        "remaining_candidate_slot_count": (
            len(candidates) - len(allocation_characters)
        ),
        "allocation_registry": proposal["allocation_registry"],
        "reraster_existing_han_count": len(reraster_existing),
        "font_assignment_count": len(assignments),
        "font_source": proposal["font_source"],
        "selection_policy": font_config["scope"],
        "rasterizer": rasterizer,
        "font_decoded_sha256": sha256_bytes(original_font),
        "proposal": str(proposal_path),
        "runtime_acceptance": "not tested",
    }
    for output, document in (
        (proposal_path, proposal),
        (report_path, report),
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
