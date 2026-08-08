#!/usr/bin/env python3
"""Append newly demanded characters to the global release-font snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.font import (
    glyph_index_for_code,
    is_conditional_width_code,
    read_extended_glyph_table,
    sha256_bytes,
)
from srwz.release_font_policy import (
    ReleaseFontPolicyError,
    validate_new_character_allocations,
)
from srwz.text import (
    ORIGINAL_FULLWIDTH_ASCII,
    load_text_table,
    original_fullwidth_ascii_overrides,
)
from srwz.release_font import (
    ReleaseFontError,
    assignment_index,
    rendered_characters,
    selected_translation_tree_entries,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/zh-release-font.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit all corpus/zh translations and append only newly demanded "
            "character mappings. Existing character/code/glyph rows never move."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the extended snapshot and refresh its profile ratchets.",
    )
    return parser.parse_args()


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit(f"unsupported JSON document: {path}")
    return document


def _write(path: Path, document: dict) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _mapping_sha256(rows: list[dict]) -> str:
    return sha256_bytes(
        json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = _load(config_path)
    snapshot_path = PROJECT_ROOT / config["allocation_snapshot"]["path"]
    snapshot_bytes = snapshot_path.read_bytes()
    if sha256_bytes(snapshot_bytes) != config["allocation_snapshot"]["sha256"]:
        raise SystemExit("release allocation snapshot SHA-256 drift")
    snapshot = json.loads(snapshot_bytes.decode("utf-8"))
    primary = snapshot.get("primary_assignments")
    aliases = snapshot.get("surface_alias_assignments")
    compatibility = snapshot.get("source_compatibility_assignments", [])
    if (
        not isinstance(primary, list)
        or not isinstance(aliases, list)
        or not isinstance(compatibility, list)
    ):
        raise SystemExit("release allocation snapshot is malformed")
    if _mapping_sha256(compatibility) != snapshot.get(
        "source_compatibility_mapping_sha256"
    ):
        raise SystemExit("release source-compatibility mapping drift")
    before_primary = json.dumps(
        primary,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    base_path = PROJECT_ROOT / config["base_font_config"]["path"]
    base = _load(base_path)
    encoding = base.get("encoding_baseline")
    if not isinstance(encoding, dict):
        raise SystemExit("global font base has no encoding baseline")
    table_path = PROJECT_ROOT / encoding["text_table"]["path"]
    codebook_path = PROJECT_ROOT / encoding["base_codebook"]["path"]
    if (
        sha256_bytes(table_path.read_bytes())
        != encoding["text_table"]["sha256"]
        or sha256_bytes(codebook_path.read_bytes())
        != encoding["base_codebook"]["sha256"]
    ):
        raise SystemExit("global font encoding baseline SHA-256 drift")
    table = load_text_table(table_path)
    base_codebook = assignment_index(codebook_path)

    try:
        entries, _entry_scenes, selection = (
            selected_translation_tree_entries(PROJECT_ROOT, config)
        )
    except ReleaseFontError as error:
        raise SystemExit(str(error)) from error
    demanded = {
        character
        for entry in entries.values()
        for character in rendered_characters(entry["translation"])
    }
    preserved = {" ", "\u3000"}
    visible_ascii = config.get("visible_ascii_policy", {})
    if visible_ascii.get("preserve_original_glyphs") is True:
        preserved.update(ORIGINAL_FULLWIDTH_ASCII)
        ascii_codes = original_fullwidth_ascii_overrides(table)
        preserved.update(table.characters[code] for code in ascii_codes.values())
    if visible_ascii.get("preserve_raw_ascii_punctuation") is True:
        preserved.update(
            chr(code)
            for code in range(0x21, 0x7F)
            if not chr(code).isalnum()
        )

    primary_by_character = {row["character"]: row for row in primary}
    missing = sorted(demanded - set(primary_by_character) - preserved)
    occupied_codes = {
        int(row["code"], 16)
        for row in (*primary, *aliases, *compatibility)
    }
    occupied_glyphs = {
        row["glyph_index"] for row in (*primary, *aliases, *compatibility)
    }
    occupied_codes.update(
        assignment["code_value"] for assignment in base_codebook.values()
    )
    occupied_glyphs.update(
        assignment["glyph_index"] for assignment in base_codebook.values()
    )

    source_slps = (WORK_ROOT / "disc/SLPS_258.87").read_bytes()
    extended = read_extended_glyph_table(source_slps)
    trusted_candidates = snapshot.get("remaining_allocation_candidates")
    if (
        not isinstance(trusted_candidates, list)
        or _mapping_sha256(trusted_candidates)
        != snapshot.get("remaining_allocation_candidates_sha256")
    ):
        raise SystemExit("trusted release candidate pool drift")
    try:
        validate_new_character_allocations(
            config,
            snapshot,
            primary,
            trusted_candidates,
        )
    except ReleaseFontPolicyError as error:
        raise SystemExit(str(error)) from error
    allocation_candidates = [
        (
            int(row["code"], 16),
            row["glyph_index"],
            row["mapping"],
            row.get("source_character"),
        )
        for row in trusted_candidates
    ]
    added = []
    allocation_additions = 0
    reraster_additions = 0
    for character in missing:
        code = table.inverse_characters.get(character)
        glyph_index = None
        if (
            code is not None
            and not is_conditional_width_code(code)
            and code not in occupied_codes
        ):
            try:
                candidate_glyph = glyph_index_for_code(code, extended)
            except ValueError:
                candidate_glyph = None
            if (
                candidate_glyph is not None
                and candidate_glyph not in occupied_glyphs
            ):
                glyph_index = candidate_glyph
        if glyph_index is not None:
            row = {
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "mapping": "pinned_text_table",
            }
            reraster_additions += 1
        else:
            while allocation_candidates:
                code, glyph_index, mapping, source_character = (
                    allocation_candidates.pop(0)
                )
                if code not in occupied_codes and glyph_index not in occupied_glyphs:
                    break
            else:
                raise SystemExit(
                    "global release font has no remaining safe allocation "
                    f"candidate for {character!r}"
                )
            row = {
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "mapping": mapping,
            }
            if source_character is not None:
                row["source_character"] = source_character
            allocation_additions += 1
        if is_conditional_width_code(code):
            raise SystemExit(
                "new global character assignment entered the renderer's "
                f"single-character mode range: {character!r}=0x{code:04X}"
            )
        occupied_codes.add(code)
        occupied_glyphs.add(glyph_index)
        primary.append(row)
        added.append(row)

    if json.dumps(
        primary[: len(primary) - len(added) if added else len(primary)],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) != before_primary:
        raise SystemExit("existing global release mappings changed")
    remaining_rows = [
        {
            "code": f"{code:04X}",
            "glyph_index": glyph_index,
            "mapping": mapping,
            **(
                {"source_character": source_character}
                if source_character is not None
                else {}
            ),
        }
        for code, glyph_index, mapping, source_character in allocation_candidates
        if code not in occupied_codes and glyph_index not in occupied_glyphs
    ]
    remaining = len(remaining_rows)
    print(
        "global release snapshot audit:",
        f"entries={selection['unique_entry_count']}",
        f"new={len(added)}",
        f"allocations={allocation_additions}",
        f"reraster={reraster_additions}",
        f"remaining={remaining}",
    )
    if added:
        print(
            "new mappings:",
            " ".join(
                f"{row['character']}={row['code']}/{row['glyph_index']}"
                for row in added
            ),
        )
    if not args.apply:
        if added:
            raise SystemExit("new characters found; review and rerun with --apply")
        if remaining != config["expected"]["remaining_candidate_slot_count"]:
            raise SystemExit("remaining release candidate-count ratchet drift")
        return 0

    if not added:
        print("snapshot unchanged")
        return 0
    snapshot["primary_assignment_count"] = len(primary)
    snapshot["allocation_assignment_count"] += allocation_additions
    snapshot["reraster_existing_assignment_count"] += reraster_additions
    snapshot["primary_mapping_sha256"] = _mapping_sha256(primary)
    snapshot["remaining_allocation_candidates"] = remaining_rows
    snapshot["remaining_allocation_candidate_count"] = len(remaining_rows)
    snapshot["remaining_allocation_candidates_sha256"] = _mapping_sha256(
        remaining_rows
    )
    extensions = snapshot.setdefault("extensions", [])
    extensions.append(
        {
            "selection_sha256": selection["selection_sha256"],
            "assignment_count": len(added),
            "allocation_assignment_count": allocation_additions,
            "reraster_existing_assignment_count": reraster_additions,
            "assignments": added,
        }
    )
    _write(snapshot_path, snapshot)
    snapshot_sha256 = sha256_bytes(snapshot_path.read_bytes())
    config["allocation_snapshot"]["sha256"] = snapshot_sha256
    expected = config["expected"]
    expected["primary_assignment_count"] = len(primary)
    expected["allocation_assignment_count"] = snapshot[
        "allocation_assignment_count"
    ]
    expected["reraster_existing_assignment_count"] = snapshot[
        "reraster_existing_assignment_count"
    ]
    expected["remaining_candidate_slot_count"] = remaining
    _write(config_path, config)
    print(f"snapshot updated: {snapshot_path}")
    print(f"profile updated: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
