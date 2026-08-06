#!/usr/bin/env python3
"""Build a byte-free first-five-stage font/codebook readiness proposal."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from srwz.canary import rasterize_character, rasterizer_point_size
from srwz.font_profile import FontProfileError, load_font_profile
from srwz.font_source import (
    FontSourceError,
    font_source_metadata,
    load_font_lock,
    verify_font_fallbacks,
    verify_font_lock_files,
)
from srwz.font import (
    GLYPH_SIZE,
    decode_vt1_font_segment,
    glyph_index_for_code,
    is_cjk_unified_ideograph,
    read_extended_glyph_table,
    raw_standard_allocation_candidates,
    safe_standard_allocation_candidates,
    sha256_bytes,
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
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
CODEBOOK = PROJECT_ROOT / "config/encoding/codebook.json"
ALLOCATION_REGISTRY = PROJECT_ROOT / "config/encoding/first-five-allocations.json"
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
    parser.add_argument(
        "--stages",
        default="1-5",
        help="Comma-separated stage indices or inclusive ranges (default: 1-5).",
    )
    parser.add_argument(
        "--allocation-registry",
        type=Path,
        default=ALLOCATION_REGISTRY,
        help="Append-only allocation ledger (default: first-five ledger).",
    )
    parser.add_argument(
        "--font-config",
        type=Path,
        default=FONT_CONFIG,
        help="Font profile used for the raster lock (default: first-five profile).",
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


def _stage_indices(value: str) -> tuple[int, ...]:
    stages: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            raise SystemExit("empty item in --stages")
        if "-" in item:
            first_text, last_text = item.split("-", 1)
            first = int(first_text)
            last = int(last_text)
            if first > last:
                raise SystemExit(f"descending stage range: {item}")
            stages.update(range(first, last + 1))
        else:
            stages.add(int(item))
    if not stages or min(stages) < 1 or max(stages) > 204:
        raise SystemExit("--stages must select indices from 1 through 204")
    return tuple(sorted(stages))


def _translation_documents(stages: tuple[int, ...]) -> tuple[tuple[str, dict], ...]:
    documents = []
    selected = set(stages)
    for stage in stages:
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
            (PROJECT_ROOT / f"corpus/zh/{name}.json").read_text(encoding="utf-8")
        )
        document = {
            **document,
            "entries": [
                entry
                for entry in document["entries"]
                if int(entry["id"].split("/")[1]) in selected
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
    stages = _stage_indices(args.stages)
    allocation_registry_path = args.allocation_registry.resolve()
    font_config_path = args.font_config.resolve()
    legacy_first_five = stages == (1, 2, 3, 4, 5)
    allocation_id_prefix = "first-five" if legacy_first_five else "story-stages"
    allocation_owner = (
        "story/stages-001-005"
        if legacy_first_five
        else f"story/stages-{stages[0]:03d}-{stages[-1]:03d}"
    )
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
    for _, document in _translation_documents(stages):
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

    try:
        profile = load_font_profile(PROJECT_ROOT, font_config_path)
        rasterizer = profile["rasterizer"]
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
    font_path = locked_paths["font"]
    vt1 = (WORK_ROOT / "disc/DATA/VT1.BIN").read_bytes()
    original_font = decode_vt1_font_segment(slps, vt1).decoded

    legacy_candidates, expansion_candidates = safe_standard_allocation_candidates(
        table,
        extended_entries,
        reserved_codes=existing_codes,
        reserved_glyphs=existing_glyphs,
    )
    raw_candidates = raw_standard_allocation_candidates(
        table,
        extended_entries,
        reserved_codes=existing_codes,
        reserved_glyphs=existing_glyphs,
    )
    candidates = (*legacy_candidates, *expansion_candidates, *raw_candidates)
    allocation_registry = json.loads(
        allocation_registry_path.read_text(encoding="utf-8")
    )
    if allocation_registry.get("schema_version") != 1:
        raise SystemExit("unsupported first-five allocation registry")
    allocation_characters = tuple(allocation_registry["allocated_characters"])
    if len(allocation_characters) != len(set(allocation_characters)):
        raise SystemExit("first-five allocation registry has duplicates")
    retired_characters = set(allocation_registry.get("retired_characters", []))
    if not retired_characters <= set(allocation_characters):
        raise SystemExit("retired first-five allocation is not registered")
    unregistered = sorted(set(missing) - set(allocation_characters))
    if unregistered:
        raise SystemExit(
            "new story characters must be appended to the allocation registry: "
            f"{''.join(unregistered)}"
        )
    if len(candidates) < len(allocation_characters):
        raise SystemExit(
            "insufficient safe candidates for allocation registry: "
            f"{len(candidates)} < {len(allocation_characters)}"
        )
    allocation_by_character = dict(zip(allocation_characters, candidates))

    assignments = []
    for character in missing:
        code, glyph_index = allocation_by_character[character]
        gray, pixels, packed = rasterize_character(
            rasterizer["executable"],
            fallback_font_paths.get(character, font_path),
            character,
            rasterizer,
        )
        if not character.isspace() and not any(packed):
            raise SystemExit(
                "visible glyph raster is empty; add an explicit global "
                f"fallback for {character!r}"
            )
        start = glyph_index * GLYPH_SIZE
        preimage = original_font[start : start + GLYPH_SIZE]
        assignments.append(
            {
                "id": f"{allocation_id_prefix}-u{ord(character):04x}",
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "mapping": "standard",
                "status": "proposed_allocation",
                "allocation": {
                    "owner": allocation_owner,
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
        if not is_cjk_unified_ideograph(character) or character in allocated_characters:
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
            fallback_font_paths.get(character, font_path),
            character,
            rasterizer,
        )
        if not character.isspace() and not any(packed):
            raise SystemExit(
                "visible glyph raster is empty; add an explicit global "
                f"fallback for {character!r}"
            )
        start = glyph_index * GLYPH_SIZE
        preimage = original_font[start : start + GLYPH_SIZE]
        reraster_existing.append(
            {
                "id": f"{allocation_id_prefix}-reraster-u{ord(character):04x}",
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "mapping": mapping,
                "status": "proposed_reraster",
                "allocation": {
                    "owner": allocation_owner,
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
    assigned_glyphs = [assignment["glyph_index"] for assignment in assignments]
    if len(assigned_glyphs) != len(set(assigned_glyphs)):
        raise SystemExit("font proposal assigns one glyph slot more than once")

    proposal = {
        "schema_version": 1,
        "proposal_id": (
            "srwz-first-five-unified-font-v3"
            if legacy_first_five
            else f"srwz-story-stages-{stages[0]:03d}-{stages[-1]:03d}-unified-font-v1"
        ),
        "status": "static_proposal_not_runtime_verified",
        "stage_indices": list(stages),
        "font_source": font_source_metadata(font_lock),
        **(
            {"font_flavor": profile["font_flavor"]}
            if profile["font_flavor"] is not None
            else {}
        ),
        "unsupported_character_fallbacks": list(fallback_font_reports),
        "selection_policy": profile["scope"],
        "rasterizer": rasterizer,
        "allocation_registry": {
            "id": allocation_registry["registry_id"],
            "sha256": sha256_bytes(allocation_registry_path.read_bytes()),
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
        "stage_indices": list(stages),
        "translation_entry_count": entry_count,
        "unique_character_count": len(character_counts),
        "base_encodable_character_count": (len(character_counts) - len(missing)),
        "missing_character_count": len(missing),
        "missing_character_occurrence_count": sum(
            character_counts[character] for character in missing
        ),
        "safe_candidate_slot_count": len(candidates),
        "legacy_safe_candidate_slot_count": len(legacy_candidates),
        "expanded_standard_candidate_slot_count": len(expansion_candidates),
        "raw_standard_candidate_slot_count": len(raw_candidates),
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
        **(
            {"font_flavor": proposal["font_flavor"]}
            if proposal.get("font_flavor") is not None
            else {}
        ),
        "unsupported_character_fallbacks": proposal[
            "unsupported_character_fallbacks"
        ],
        "selection_policy": profile["scope"],
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
