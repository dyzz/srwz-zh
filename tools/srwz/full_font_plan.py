"""Audit the final SRWZ Chinese-owned sequential font-slot plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from .font import (
    ASCII_FIRST,
    ASCII_LAST,
    GLYPH_COUNT,
    SHIFT_JIS_TRAILS,
    ascii_glyph_index,
    is_cjk_unified_ideograph,
    standard_code_for_glyph_index,
    standard_glyph_index,
)


class FullFontPlanError(ValueError):
    """The final full-font plan or its translation inventory is invalid."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FullFontPlanError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise FullFontPlanError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, raw: object, *, context: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise FullFontPlanError(f"{context} must be a non-empty path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise FullFontPlanError(f"{context} must be project-relative")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise FullFontPlanError(f"{context} escapes the project root") from error
    return path


def _translation_values(value: object, field: str) -> Iterable[str]:
    if isinstance(value, dict):
        translation = value.get(field)
        if isinstance(translation, str):
            yield translation
        for key, child in value.items():
            if key != field:
                yield from _translation_values(child, field)
    elif isinstance(value, list):
        for child in value:
            yield from _translation_values(child, field)


def _sequence_sha256(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def audit_full_chinese_font_plan(project_root: Path, config_path: Path) -> dict:
    """Return a hash-only capacity plan for replacing the original font atlas."""

    project_root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise FullFontPlanError("unsupported full-font plan schema")
    plan_id = config.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise FullFontPlanError("full-font plan needs plan_id")

    policy = config.get("slot_policy")
    if not isinstance(policy, dict):
        raise FullFontPlanError("full-font plan needs slot_policy")
    expected_policy = {
        "mode": "contiguous-standard-renderer-slots",
        "first_glyph_index": 0,
        "last_glyph_index": GLYPH_COUNT - 1,
        "first_translation_glyph_index": 287,
        "reserve_printable_ascii_glyphs": True,
        "preserve_original_japanese_glyphs": False,
        "unassigned_slots_are_blank": True,
        "registry_policy": "append-only-after-initial-seed",
    }
    if policy != expected_policy:
        raise FullFontPlanError("full-font slot policy drift")

    codes = tuple(
        standard_code_for_glyph_index(glyph_index)
        for glyph_index in range(GLYPH_COUNT)
    )
    if any(
        standard_glyph_index(code) != glyph_index
        for glyph_index, code in enumerate(codes)
    ):
        raise FullFontPlanError("standard renderer slot inverse is incomplete")

    ascii_glyphs = frozenset(
        ascii_glyph_index(code) for code in range(ASCII_FIRST, ASCII_LAST + 1)
    )
    first_translation_glyph_index = policy["first_translation_glyph_index"]
    if max(ascii_glyphs) >= first_translation_glyph_index:
        raise FullFontPlanError("full-font translation range overlaps ASCII glyphs")
    translation_slots = tuple(range(first_translation_glyph_index, GLYPH_COUNT))

    corpus = config.get("corpus")
    if not isinstance(corpus, dict):
        raise FullFontPlanError("full-font plan needs corpus selection")
    corpus_root = _project_path(
        project_root,
        corpus.get("root"),
        context="full-font corpus root",
    )
    pattern = corpus.get("glob")
    field = corpus.get("translation_field")
    if not corpus_root.is_dir():
        raise FullFontPlanError("full-font corpus root is not a directory")
    if not isinstance(pattern, str) or not pattern:
        raise FullFontPlanError("full-font corpus glob is invalid")
    if not isinstance(field, str) or not field:
        raise FullFontPlanError("full-font translation field is invalid")

    files = tuple(sorted(path for path in corpus_root.glob(pattern) if path.is_file()))
    translations = []
    input_rows = []
    for path in files:
        document = _json_object(path)
        values = tuple(_translation_values(document, field))
        if not values:
            continue
        translations.extend(values)
        relative = str(path.relative_to(project_root))
        input_rows.append(
            f"{relative}\t{hashlib.sha256(path.read_bytes()).hexdigest()}\t{len(values)}"
        )
    if not translations:
        raise FullFontPlanError("full-font corpus selection is empty")

    literal_characters = set("".join(translations))
    ignored_controls = {"\n", "\r", "\t"}
    printable_ascii = {
        character
        for character in literal_characters
        if ASCII_FIRST <= ord(character) <= ASCII_LAST
    }
    double_byte_characters = tuple(
        sorted(
            character
            for character in literal_characters
            if character not in ignored_controls
            and not ASCII_FIRST <= ord(character) <= ASCII_LAST
        )
    )
    cjk_count = sum(is_cjk_unified_ideograph(character) for character in double_byte_characters)
    required = len(double_byte_characters)
    available = len(translation_slots)
    if required > available:
        raise FullFontPlanError(
            f"full-font corpus exceeds sequential capacity: {required} > {available}"
        )

    raw_trail_codes = sum((code & 0xFF) not in SHIFT_JIS_TRAILS for code in codes)
    first_slot = translation_slots[0]
    last_used_slot = translation_slots[required - 1] if required else None
    runtime = config.get("runtime_boundary")
    if not isinstance(runtime, dict) or runtime.get("status") != "static_plan_runtime_pending":
        raise FullFontPlanError("full-font runtime boundary is invalid")

    return {
        "schema_version": 1,
        "status": "static_full_chinese_font_capacity_validated_runtime_pending",
        "content_policy": "Counts, hashes, geometry and runtime gates only; translation strings and game font bytes are not embedded.",
        "plan_id": plan_id,
        "scope": config.get("scope"),
        "inputs": {
            "config": {
                "path": str(config_path.relative_to(project_root)),
                "size": config_path.stat().st_size,
                "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            },
            "corpus": {
                "root": str(corpus_root.relative_to(project_root)),
                "file_count": len(input_rows),
                "translation_entry_count": len(translations),
                "inventory_sha256": _sequence_sha256(input_rows),
            },
        },
        "renderer_geometry": {
            "glyph_count": GLYPH_COUNT,
            "row_stride": 192,
            "first_code": f"{codes[0]:04X}",
            "first_row_last_code": f"{codes[191]:04X}",
            "second_row_first_code": f"{codes[192]:04X}",
            "last_code": f"{codes[-1]:04X}",
            "code_to_glyph_round_trip_exact": True,
            "raw_trail_code_count": raw_trail_codes,
        },
        "reserved_slots": {
            "printable_ascii_character_count": ASCII_LAST - ASCII_FIRST + 1,
            "printable_ascii_glyph_count": len(ascii_glyphs),
            "printable_ascii_glyph_indices_sha256": _sequence_sha256(
                str(index) for index in sorted(ascii_glyphs)
            ),
            "original_japanese_glyph_count": 0,
            "blank_non_ascii_prefix_glyph_count": (
                first_translation_glyph_index - len(ascii_glyphs)
            ),
        },
        "translation_inventory": {
            "unique_printable_ascii_character_count": len(printable_ascii),
            "unique_double_byte_character_count": required,
            "unique_cjk_ideograph_count": cjk_count,
            "unique_non_cjk_double_byte_character_count": required - cjk_count,
            "unique_double_byte_characters_sha256": _sequence_sha256(
                double_byte_characters
            ),
        },
        "capacity": {
            "sequential_translation_slot_count": available,
            "current_required_slot_count": required,
            "current_remaining_slot_count": available - required,
            "current_corpus_fits": True,
            "first_translation_glyph_index": first_slot,
            "first_translation_code": f"{codes[first_slot]:04X}",
            "last_seeded_translation_glyph_index": last_used_slot,
        },
        "allocation_policy": {
            "mode": policy["mode"],
            "registry_policy": policy["registry_policy"],
            "original_japanese_glyphs_preserved": False,
            "unassigned_slots_are_blank": True,
            "note": "Start at glyph 287 (code 829F), allocate every later renderer glyph index contiguously, freeze the initial registry, then append without renumbering.",
        },
        "runtime": runtime,
        "acceptance": {
            "all_4480_glyphs_have_a_standard_renderer_code": True,
            "printable_ascii_slots_are_reserved": True,
            "original_japanese_glyph_identity_is_not_a_capacity_gate": True,
            "current_translation_inventory_fits": True,
            "runtime_promotion_remains_pending": True,
        },
    }


__all__ = ["FullFontPlanError", "audit_full_chinese_font_plan"]
