"""Shared fail-closed policies for the flattened Chinese release font."""

from __future__ import annotations

from typing import Mapping, Sequence

from .font import is_conditional_width_code


class ReleaseFontPolicyError(ValueError):
    """The global release-font allocation policy or snapshot has drifted."""


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
) -> dict[str, int]:
    """Validate every post-migration assignment and future candidate.

    Historical primary rows remain immutable. New rows may reclaim any
    unoccupied standard two-byte renderer position, including Japanese source
    codes and positions in the conditional-width range.
    """

    policy = config.get("new_character_allocation_policy")
    if (
        not isinstance(policy, Mapping)
        or policy.get("required_width_class")
        != "renderer_addressable_double_byte"
        or policy.get("reclaim_unused_japanese_positions") is not True
        or policy.get("conditional_width_positions_allowed") is not True
    ):
        raise ReleaseFontPolicyError(
            "global new-character allocation policy drift"
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
    }


__all__ = [
    "ReleaseFontPolicyError",
    "validate_new_character_allocations",
]
