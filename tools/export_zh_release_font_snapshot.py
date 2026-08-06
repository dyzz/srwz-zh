#!/usr/bin/env python3
"""Flatten the historical font proposal chain into one release mapping."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-time migration helper: combine a final primary proposal and "
            "its surface aliases into the canonical global release snapshot."
        )
    )
    parser.add_argument("--primary-proposal", type=Path, required=True)
    parser.add_argument("--alias-proposal", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "config/encoding/zh-release-font-assignments.json",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_rows(assignments: object, *, aliases: bool = False) -> list[dict]:
    if not isinstance(assignments, list):
        raise SystemExit("proposal assignment collection is malformed")
    keys = ["character", "code", "glyph_index", "mapping"]
    if aliases:
        keys.append("primary_code")
    rows = []
    for assignment in assignments:
        if not isinstance(assignment, dict) or any(
            key not in assignment for key in keys
        ):
            raise SystemExit("proposal assignment is malformed")
        row = {key: assignment[key] for key in keys}
        if "source_character" in assignment:
            row["source_character"] = assignment["source_character"]
        rows.append(row)
    return rows


def _mapping_sha256(rows: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def main() -> int:
    args = parse_args()
    primary_path = args.primary_proposal.resolve()
    alias_path = args.alias_proposal.resolve()
    output_path = args.output.resolve()
    if output_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output_path}")
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    aliases = json.loads(alias_path.read_text(encoding="utf-8"))
    primary_rows = _mapping_rows(primary.get("assignments"))
    historical_primary_rows = _mapping_rows(aliases.get("assignments"))
    alias_rows = _mapping_rows(
        aliases.get("surface_alias_assignments"),
        aliases=True,
    )
    remaining_candidates = primary.get("remaining_allocation_candidates")
    if not isinstance(remaining_candidates, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("code"), str)
        or not isinstance(row.get("glyph_index"), int)
        or not isinstance(row.get("mapping"), str)
        for row in remaining_candidates
    ):
        raise SystemExit("primary proposal has no trusted remaining candidates")
    all_codes = [row["code"] for row in (*primary_rows, *alias_rows)]
    all_glyphs = [row["glyph_index"] for row in (*primary_rows, *alias_rows)]
    primary_characters = [row["character"] for row in primary_rows]
    if (
        len(primary_characters) != len(set(primary_characters))
        or len(all_codes) != len(set(all_codes))
        or len(all_glyphs) != len(set(all_glyphs))
    ):
        raise SystemExit("flattened release mapping has a collision")
    if any(
        row["code"] in set(all_codes)
        or row["glyph_index"] in set(all_glyphs)
        for row in remaining_candidates
    ):
        raise SystemExit("remaining release candidate collides with an assignment")
    current_by_character = {
        row["character"]: row for row in primary_rows
    }
    if any(
        current_by_character.get(row["character"]) != row
        for row in historical_primary_rows
    ):
        raise SystemExit("historical primary mapping changed during flattening")

    document = {
        "schema_version": 1,
        "snapshot_id": "srwz-zh-release-font-assignments-v1",
        "policy": (
            "Canonical character-to-code-to-glyph mapping for every Chinese "
            "localization surface. Add future menu, story and battle-dialogue "
            "coverage here without creating another font profile layer."
        ),
        "allocation_assignment_count": primary[
            "allocation_assignment_count"
        ],
        "reraster_existing_assignment_count": primary[
            "reraster_existing_assignment_count"
        ],
        "primary_assignment_count": len(primary_rows),
        "surface_alias_assignment_count": len(alias_rows),
        "primary_mapping_sha256": _mapping_sha256(primary_rows),
        "surface_alias_mapping_sha256": _mapping_sha256(alias_rows),
        "remaining_allocation_candidate_count": len(remaining_candidates),
        "remaining_allocation_candidates_sha256": _mapping_sha256(
            remaining_candidates
        ),
        "primary_assignments": primary_rows,
        "surface_alias_assignments": alias_rows,
        "remaining_allocation_candidates": remaining_candidates,
        "migration": {
            "mode": "flatten-historical-p-chain-once",
            "primary_proposal": {
                "path": str(primary_path.relative_to(PROJECT_ROOT)),
                "sha256": _sha256(primary_path),
                "proposal_id": primary.get("proposal_id"),
            },
            "alias_proposal": {
                "path": str(alias_path.relative_to(PROJECT_ROOT)),
                "sha256": _sha256(alias_path),
                "proposal_id": aliases.get("proposal_id"),
            },
            "preserved_historical_primary_assignment_count": len(
                historical_primary_rows
            ),
            "preserved_historical_primary_mapping_sha256": _mapping_sha256(
                historical_primary_rows
            ),
            "added_global_assignment_count": (
                len(primary_rows) - len(historical_primary_rows)
            ),
            "active_build_dependency": False,
            "reason": (
                "These paths document the one-time migration only. The active "
                "release build consumes this self-contained snapshot."
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "release mapping snapshot:",
        f"primary={len(primary_rows)}",
        f"aliases={len(alias_rows)}",
        f"output={output_path}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
