"""Shared fail-closed policies for the flattened Chinese release font."""

from __future__ import annotations

from typing import Mapping, Sequence

from .font import RAW_STANDARD_TRAILS, is_conditional_width_code


DEFAULT_WIDTH_CLASS = "default_width"
CONDITIONAL_WIDTH_CLASS = "conditional_width"
RAW_TRAIL_GAP_CLASS = "raw_trail_gap"


class ReleaseFontPolicyError(ValueError):
    """The global release-font allocation policy or snapshot has drifted."""


def allocation_width_class(code: int) -> str:
    """Classify one renderer-addressable code for new-glyph allocation.

    Raw trail gaps are classified first because codes such as ``0x81FE`` are
    both inside the conditional-width interval and outside valid Shift-JIS.
    They are not eligible for future allocations.
    """

    if not isinstance(code, int):
        raise TypeError("text code must be an integer")
    if not 0 <= code <= 0xFFFF:
        raise ValueError("text code is outside two bytes")
    if (code & 0xFF) in RAW_STANDARD_TRAILS:
        return RAW_TRAIL_GAP_CLASS
    if is_conditional_width_code(code):
        return CONDITIONAL_WIDTH_CLASS
    return DEFAULT_WIDTH_CLASS


def allocation_candidate_priority(code: int) -> tuple[int, int]:
    """Return the stable safe-first ordering for a future candidate code."""

    width_class = allocation_width_class(code)
    rank = {
        DEFAULT_WIDTH_CLASS: 0,
        CONDITIONAL_WIDTH_CLASS: 1,
        RAW_TRAIL_GAP_CLASS: 2,
    }[width_class]
    return rank, code


def _require_renderer_double_byte_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    context: str,
) -> None:
    for row in rows:
        try:
            code = int(row["code"], 16)
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontPolicyError(
                f"{context} has a malformed code"
            ) from error
        if not 0x100 <= code <= 0xFFFF:
            raise ReleaseFontPolicyError(
                f"{context} is not a renderer-addressable "
                f"double-byte code: 0x{code:04X}"
            )


def validate_new_character_allocations(
    config: Mapping[str, object],
    snapshot: Mapping[str, object],
    primary_rows: Sequence[Mapping[str, object]],
    remaining_candidates: Sequence[Mapping[str, object]],
    *,
    surface_alias_rows: Sequence[Mapping[str, object]] = (),
    source_compatibility_rows: Sequence[Mapping[str, object]] = (),
) -> dict[str, int]:
    """Validate every post-migration assignment and future candidate.

    Historical primary rows remain separately frozen. New rows normally use
    default-width two-byte positions. A conditional-width row is accepted only
    with explicit long-text-only evidence; raw-trail slots are never accepted.
    Across every active mapping kind, a character may own at most one
    default-width slot. This is a build-time invariant, not merely an audit.
    """

    policy = config.get("new_character_allocation_policy")
    if (
        not isinstance(policy, Mapping)
        or policy.get("required_width_class")
        != "renderer_addressable_double_byte"
        or policy.get("reclaim_unused_japanese_positions") is not True
        or policy.get("conditional_width_positions_allowed") is not True
        or policy.get("preferred_width_class") != DEFAULT_WIDTH_CLASS
        or policy.get("conditional_width_fallback")
        != "long_text_surface_only_with_audit"
        or policy.get("raw_trail_positions_allowed") is not False
    ):
        raise ReleaseFontPolicyError(
            "global new-character allocation policy drift"
        )
    conditional_exception = policy.get("conditional_width_exception")
    if (
        not isinstance(conditional_exception, Mapping)
        or conditional_exception.get("allowed_surfaces")
        != [
            "story_dialogue",
            "battle_dialogue",
            "story_system_dialogue",
            "library",
        ]
        or conditional_exception.get("forbidden_compact_name_surfaces")
        != ["unit_name", "pilot_or_speaker_name", "part_name"]
        or conditional_exception.get("runtime_reference_character") != "喂"
        or conditional_exception.get("requires_explicit_assignment_metadata")
        is not True
    ):
        raise ReleaseFontPolicyError(
            "conditional-width long-text exception policy drift"
        )

    safe_owners: dict[str, list[str]] = {}
    for group_name, rows in (
        ("primary", primary_rows),
        ("surface_alias", surface_alias_rows),
        ("source_compatibility", source_compatibility_rows),
    ):
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise ReleaseFontPolicyError(
                f"release {group_name} assignments are malformed"
            )
        for row in rows:
            if not isinstance(row, Mapping):
                raise ReleaseFontPolicyError(
                    f"release {group_name} assignment is malformed"
                )
            character = row.get("character")
            try:
                code = int(row["code"], 16)
            except (KeyError, TypeError, ValueError) as error:
                raise ReleaseFontPolicyError(
                    f"release {group_name} assignment has a malformed code"
                ) from error
            if (
                isinstance(character, str)
                and character
                and allocation_width_class(code) == DEFAULT_WIDTH_CLASS
            ):
                safe_owners.setdefault(character, []).append(
                    f"{group_name}:0x{code:04X}"
                )
    safe_duplicates = {
        character: owners
        for character, owners in safe_owners.items()
        if len(owners) > 1
    }
    if safe_duplicates:
        raise ReleaseFontPolicyError(
            "safe/default-width region contains duplicate character "
            f"assignments: {safe_duplicates!r}"
        )

    migration = snapshot.get("migration")
    historical_count = (
        migration.get("preserved_historical_primary_assignment_count")
        if isinstance(migration, Mapping)
        else None
    )
    if (
        not isinstance(historical_count, int)
        or isinstance(historical_count, bool)
        or not 0 <= historical_count <= len(primary_rows)
    ):
        raise ReleaseFontPolicyError(
            "release allocation migration boundary is malformed"
        )

    policy_effective_count = policy.get(
        "policy_effective_primary_assignment_count"
    )
    if (
        not isinstance(policy_effective_count, int)
        or isinstance(policy_effective_count, bool)
        or not historical_count <= policy_effective_count <= len(primary_rows)
    ):
        raise ReleaseFontPolicyError(
            "safe-first allocation policy boundary is malformed"
        )

    guarded_groups = [
        ("global post-migration assignment", primary_rows[historical_count:]),
        ("trusted release allocation candidate", remaining_candidates),
    ]
    extension_assignment_count = 0
    extensions = snapshot.get("extensions", [])
    if not isinstance(extensions, Sequence) or isinstance(
        extensions, (str, bytes)
    ):
        raise ReleaseFontPolicyError("release allocation extensions are malformed")
    for extension in extensions:
        assignments = (
            extension.get("assignments")
            if isinstance(extension, Mapping)
            else None
        )
        if not isinstance(assignments, Sequence) or isinstance(
            assignments, (str, bytes)
        ):
            raise ReleaseFontPolicyError(
                "release allocation extension is malformed"
            )
        extension_assignment_count += len(assignments)
        guarded_groups.append(("global snapshot extension", assignments))

    for context, rows in guarded_groups:
        if any(not isinstance(row, Mapping) for row in rows):
            raise ReleaseFontPolicyError(f"{context} is malformed")
        _require_renderer_double_byte_rows(rows, context=context)

    candidate_codes = [int(row["code"], 16) for row in remaining_candidates]
    candidate_classes = [
        allocation_width_class(code) for code in candidate_codes
    ]
    if RAW_TRAIL_GAP_CLASS in candidate_classes:
        raise ReleaseFontPolicyError(
            "trusted release allocation candidates contain a raw trail gap"
        )
    if CONDITIONAL_WIDTH_CLASS in candidate_classes:
        raise ReleaseFontPolicyError(
            "trusted release allocation candidates contain a forbidden "
            "conditional-width slot"
        )
    candidate_priorities = [
        allocation_candidate_priority(code)[0] for code in candidate_codes
    ]
    if candidate_priorities != sorted(candidate_priorities):
        raise ReleaseFontPolicyError(
            "trusted release allocation candidates are not safe-first"
        )

    future_rows = primary_rows[policy_effective_count:]
    conditional_exception_count = 0
    for row in future_rows:
        code = int(row["code"], 16)
        width_class = allocation_width_class(code)
        if width_class == RAW_TRAIL_GAP_CLASS:
            raise ReleaseFontPolicyError(
                "future release allocation uses a raw trail gap"
            )
        if width_class == CONDITIONAL_WIDTH_CLASS:
            allowed_surfaces = set(conditional_exception["allowed_surfaces"])
            scope = row.get("allocation_scope")
            selection_sha256 = row.get("allocation_selection_sha256")
            if (
                row.get("allocation_width_class") != CONDITIONAL_WIDTH_CLASS
                or row.get("allocation_exception") != "long_text_surface_only"
                or not isinstance(scope, Sequence)
                or isinstance(scope, (str, bytes))
                or not scope
                or any(surface not in allowed_surfaces for surface in scope)
                or row.get("runtime_reference_character") != "喂"
                or not isinstance(selection_sha256, str)
                or len(selection_sha256) != 64
            ):
                raise ReleaseFontPolicyError(
                    "future conditional-width allocation lacks an audited "
                    "long-text-only exception"
                )
            conditional_exception_count += 1

    default_candidate_count = candidate_classes.count(DEFAULT_WIDTH_CLASS)

    conditional_assignment_count = sum(
        is_conditional_width_code(int(row["code"], 16))
        for row in primary_rows[historical_count:]
    )
    conditional_candidate_count = sum(
        is_conditional_width_code(int(row["code"], 16))
        for row in remaining_candidates
    )

    return {
        "guarded_post_migration_assignment_count": (
            len(primary_rows) - historical_count
        ),
        "guarded_extension_assignment_count": extension_assignment_count,
        "remaining_renderer_double_byte_candidate_count": len(
            remaining_candidates
        ),
        "conditional_width_assignment_count": conditional_assignment_count,
        "conditional_width_candidate_count": conditional_candidate_count,
        "default_width_candidate_count": default_candidate_count,
        "raw_trail_candidate_count": candidate_classes.count(
            RAW_TRAIL_GAP_CLASS
        ),
        "safe_first_policy_assignment_count": len(future_rows),
        "conditional_width_exception_assignment_count": (
            conditional_exception_count
        ),
        "safe_region_duplicate_character_count": 0,
    }


__all__ = [
    "CONDITIONAL_WIDTH_CLASS",
    "DEFAULT_WIDTH_CLASS",
    "RAW_TRAIL_GAP_CLASS",
    "ReleaseFontPolicyError",
    "allocation_candidate_priority",
    "allocation_width_class",
    "validate_new_character_allocations",
]
