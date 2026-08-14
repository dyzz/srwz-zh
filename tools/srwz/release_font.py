"""Corpus selection and coverage audit for the flattened release font."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from .codec import decode_production
from .font import (
    GLYPH_SIZE,
    ascii_glyph_index,
    glyph_index_for_code,
    is_cjk_unified_ideograph,
    sha256_bytes,
)
from .library import SoundTitleSpanLock, verify_sound_title_source
from .text import (
    control_notation_positions,
    control_notation_tokens,
    original_fullwidth_ascii_overrides,
    unrecognized_control_notation_offsets,
)


class ReleaseFontError(ValueError):
    """The global corpus selection or renderer coverage has drifted."""


def _project_path(project_root: Path, reference: str) -> Path:
    if not isinstance(reference, str) or not reference:
        raise ReleaseFontError("project path must be a non-empty string")
    root = project_root.resolve()
    path = (root / reference).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ReleaseFontError(f"path escapes project root: {reference}") from error
    return path


def _hash_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def audit_frozen_formation_compatibility_assignments(
    snapshot: Mapping[str, object],
    freeze: Mapping[str, object],
) -> dict:
    """Fail closed if any approved formation-compatibility mapping moves."""

    expected = freeze.get("expected")
    relocations = freeze.get("relocations")
    retired_aliases = freeze.get("retired_aliases")
    if (
        freeze.get("schema_version") != 1
        or freeze.get("status") != "reviewed_locked"
        or freeze.get("update_policy") != "explicit_refreeze_only"
        or freeze.get("source_snapshot_id") != snapshot.get("snapshot_id")
        or not isinstance(expected, Mapping)
        or not isinstance(relocations, list)
        or not isinstance(retired_aliases, list)
    ):
        raise ReleaseFontError(
            "frozen formation affected-character contract is invalid"
        )

    frozen_rows = {
        "relocations": relocations,
        "retired_aliases": retired_aliases,
    }
    frozen_mapping_sha256 = sha256_bytes(
        json.dumps(
            frozen_rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    rows = [*relocations, *retired_aliases]
    characters = [
        row.get("character") for row in rows if isinstance(row, Mapping)
    ]
    primary_count = sum(
        isinstance(row, Mapping)
        and row.get("current_assignment_kind") == "primary"
        for row in rows
    )
    alias_count = sum(
        isinstance(row, Mapping)
        and row.get("current_assignment_kind") == "surface_alias"
        for row in rows
    )
    if (
        len(relocations) != expected.get("relocation_count")
        or len(retired_aliases) != expected.get("retired_alias_count")
        or len(rows) != expected.get("affected_character_count")
        or len(set(characters)) != len(rows)
        or primary_count != expected.get("current_primary_assignment_count")
        or alias_count
        != expected.get("current_surface_alias_assignment_count")
        or frozen_mapping_sha256 != expected.get("frozen_mapping_sha256")
    ):
        raise ReleaseFontError(
            "frozen formation affected-character inventory drift"
        )

    extensions = snapshot.get("extensions")
    if not isinstance(extensions, list):
        raise ReleaseFontError("release font snapshot extensions are invalid")
    contracts = [
        extension["legacy_save_formation_compatibility"]
        for extension in extensions
        if isinstance(extension, Mapping)
        and "legacy_save_formation_compatibility" in extension
    ]
    if len(contracts) != 1 or not isinstance(contracts[0], Mapping):
        raise ReleaseFontError(
            "release font snapshot must have exactly one legacy formation contract"
        )
    contract = contracts[0]
    contract_relocations = contract.get("relocations")
    contract_retired_aliases = contract.get("retired_aliases")
    if not isinstance(contract_relocations, list) or not isinstance(
        contract_retired_aliases, list
    ):
        raise ReleaseFontError("legacy formation compatibility contract is invalid")
    if [
        (row.get("character"), row.get("from_code"), row.get("to_code"))
        for row in contract_relocations
        if isinstance(row, Mapping)
    ] != [
        (row.get("character"), row.get("from_code"), row.get("current_code"))
        for row in relocations
        if isinstance(row, Mapping)
    ] or [
        (row.get("character"), row.get("from_code"))
        for row in contract_retired_aliases
        if isinstance(row, Mapping)
    ] != [
        (row.get("character"), row.get("from_code"))
        for row in retired_aliases
        if isinstance(row, Mapping)
    ]:
        raise ReleaseFontError(
            "frozen formation affected-character migration scope drift"
        )

    primary = snapshot.get("primary_assignments")
    aliases = snapshot.get("surface_alias_assignments")
    compatibility = snapshot.get("source_compatibility_assignments")
    if not all(
        isinstance(mapping_rows, list)
        for mapping_rows in (primary, aliases, compatibility)
    ):
        raise ReleaseFontError("release font snapshot mappings are invalid")
    primary_by_character = {
        row.get("character"): row
        for row in primary
        if isinstance(row, Mapping)
    }
    alias_by_character = {
        row.get("character"): row
        for row in aliases
        if isinstance(row, Mapping)
    }
    active_by_code: dict[str, str] = {}
    for row in (*primary, *aliases, *compatibility):
        if not isinstance(row, Mapping):
            raise ReleaseFontError("release font snapshot mapping row is invalid")
        code = row.get("code")
        character = row.get("character")
        if (
            not isinstance(code, str)
            or not isinstance(character, str)
            or len(character) != 1
            or code in active_by_code
        ):
            raise ReleaseFontError("release font snapshot mapping row is invalid")
        active_by_code[code] = character

    for row in rows:
        if not isinstance(row, Mapping):
            raise ReleaseFontError(
                "frozen formation affected-character row is invalid"
            )
        character = row.get("character")
        from_code = row.get("from_code")
        current_code = row.get("current_code")
        glyph_index = row.get("current_glyph_index")
        assignment_kind = row.get("current_assignment_kind")
        from_code_character = row.get("from_code_active_character")
        try:
            codes_are_canonical = all(
                f"{int(code, 16):04X}" == code
                for code in (from_code, current_code)
            )
        except (TypeError, ValueError):
            codes_are_canonical = False
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(from_code_character, str)
            or len(from_code_character) != 1
            or not isinstance(glyph_index, int)
            or isinstance(glyph_index, bool)
            or assignment_kind not in {"primary", "surface_alias"}
            or not codes_are_canonical
        ):
            raise ReleaseFontError(
                "frozen formation affected-character row is invalid"
            )
        assignment = (
            primary_by_character.get(character)
            if assignment_kind == "primary"
            else alias_by_character.get(character)
        )
        if (
            not isinstance(assignment, Mapping)
            or assignment.get("code") != current_code
            or assignment.get("glyph_index") != glyph_index
            or active_by_code.get(current_code) != character
            or active_by_code.get(from_code) != from_code_character
        ):
            raise ReleaseFontError(
                "frozen formation affected-character mapping drift: "
                f"{character!r}"
            )

    return {
        "freeze_id": freeze.get("freeze_id"),
        "status": freeze.get("status"),
        "update_policy": freeze.get("update_policy"),
        "relocation_count": len(relocations),
        "retired_alias_count": len(retired_aliases),
        "affected_character_count": len(rows),
        "current_primary_assignment_count": primary_count,
        "current_surface_alias_assignment_count": alias_count,
        "frozen_mapping_sha256": frozen_mapping_sha256,
        "all_affected_character_assignments_frozen": True,
        "all_vacated_codes_frozen": True,
    }


def load_frozen_formation_compatibility(
    project_root: Path,
    config: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> dict:
    """Load the hash-locked freeze file and audit it against a snapshot."""

    reference = config.get("formation_compatibility_freeze")
    if not isinstance(reference, Mapping):
        raise ReleaseFontError(
            "release font profile has no formation compatibility freeze"
        )
    path = _project_path(project_root, reference.get("path"))
    data = path.read_bytes()
    if (
        len(data) != reference.get("size")
        or sha256_bytes(data) != reference.get("sha256")
    ):
        raise ReleaseFontError("formation compatibility freeze lock drift")
    try:
        freeze = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseFontError(
            "formation compatibility freeze is malformed"
        ) from error
    if (
        not isinstance(freeze, Mapping)
        or freeze.get("freeze_id") != reference.get("freeze_id")
    ):
        raise ReleaseFontError("formation compatibility freeze identity drift")
    report = audit_frozen_formation_compatibility_assignments(snapshot, freeze)
    return {
        **report,
        "contract": {
            "path": str(path.relative_to(project_root.resolve())),
            "size": len(data),
            "sha256": sha256_bytes(data),
        },
    }


def assignment_index(path: Path) -> dict[str, dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document.get("assignments")
    if not isinstance(rows, list):
        raise ReleaseFontError(f"assignment file has no assignments: {path}")
    assignments = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ReleaseFontError(f"malformed assignment in {path}")
        character = raw.get("character")
        code = raw.get("code")
        glyph_index = raw.get("glyph_index")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, str)
            or not isinstance(glyph_index, int)
        ):
            raise ReleaseFontError(f"malformed assignment in {path}")
        if character in assignments:
            raise ReleaseFontError(f"duplicate character assignment in {path}")
        assignment = dict(raw)
        assignment["code_value"] = int(code, 16)
        assignments[character] = assignment
    return assignments


def baseline_with_original_ascii(
    baseline: Mapping[str, object],
    *,
    preserve_raw_ascii_punctuation: bool = False,
) -> dict:
    """Teach coverage audits about stock two-byte ASCII glyph reuse."""

    table = baseline["table"]
    extended_entries = baseline["extended_entries"]
    assignments = dict(baseline["proposal_assignments"])
    for character, code in original_fullwidth_ascii_overrides(table).items():
        source_character = table.characters[code]
        synthetic = {
            "code_value": code,
            "mapping": "original_fullwidth_ascii",
            "glyph_index": glyph_index_for_code(code, extended_entries),
        }
        assignments[character] = synthetic
        assignments[source_character] = synthetic
    if preserve_raw_ascii_punctuation:
        for code in range(0x21, 0x7F):
            character = chr(code)
            if character.isalnum():
                continue
            assignments[character] = {
                "code_value": code,
                "mapping": "original_raw_ascii_punctuation",
                "glyph_index": ascii_glyph_index(code),
            }
    return {**baseline, "proposal_assignments": assignments}


def audit_legacy_formation_glyph_compatibility(
    snapshot: Mapping[str, object],
    table: object,
    *,
    project_root: Path | None = None,
) -> dict:
    """Prove every glyph used by stock names in legacy saves stays readable."""

    extensions = snapshot.get("extensions")
    if not isinstance(extensions, list):
        raise ReleaseFontError("release font snapshot extensions are invalid")
    contracts = [
        extension["legacy_save_formation_compatibility"]
        for extension in extensions
        if isinstance(extension, dict)
        and "legacy_save_formation_compatibility" in extension
    ]
    if len(contracts) != 1 or not isinstance(contracts[0], dict):
        raise ReleaseFontError(
            "release font snapshot must have exactly one legacy formation contract"
        )
    contract = contracts[0]
    inventory_reference = contract.get("source_inventory")
    source_inventory = None
    if inventory_reference is not None:
        if project_root is None or not isinstance(inventory_reference, dict):
            raise ReleaseFontError(
                "legacy formation compatibility inventory reference is invalid"
            )
        inventory_path = _project_path(
            project_root,
            inventory_reference.get("path"),
        )
        inventory_bytes = inventory_path.read_bytes()
        inventory_sha256 = sha256_bytes(inventory_bytes)
        if inventory_sha256 != inventory_reference.get("sha256"):
            raise ReleaseFontError(
                "legacy formation compatibility inventory SHA-256 drift"
            )
        try:
            inventory = json.loads(inventory_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReleaseFontError(
                "legacy formation compatibility inventory is malformed"
            ) from error
        inventory_names = inventory.get("sources")
        expected_name_count = inventory_reference.get("source_count")
        if (
            not isinstance(expected_name_count, int)
            or isinstance(expected_name_count, bool)
            or not isinstance(inventory_names, list)
            or len(inventory_names) != expected_name_count
            or inventory.get("expected", {}).get("unique_source_count")
            != expected_name_count
        ):
            raise ReleaseFontError(
                "legacy formation compatibility inventory count drift"
            )
        source_inventory = {
            "path": str(inventory_path.relative_to(project_root.resolve())),
            "size": len(inventory_bytes),
            "sha256": inventory_sha256,
            "source_count": expected_name_count,
        }
        extra_names = contract.get("observed_legacy_names", [])
        if not isinstance(extra_names, list):
            raise ReleaseFontError(
                "legacy formation compatibility observed-name list is invalid"
            )
        observed_names = list(dict.fromkeys([*inventory_names, *extra_names]))
    else:
        observed_names = contract.get("observed_legacy_names")
    preserved_text = contract.get("preserved_source_characters")
    reserved_text = contract.get("reserved_unoccupied_source_characters", "")
    if (
        not isinstance(observed_names, list)
        or not observed_names
        or any(not isinstance(name, str) or not name for name in observed_names)
        or not isinstance(preserved_text, str)
        or not preserved_text
        or not isinstance(reserved_text, str)
        or len(set(preserved_text)) != len(preserved_text)
        or len(set(reserved_text)) != len(reserved_text)
    ):
        raise ReleaseFontError("legacy formation compatibility contract is invalid")

    primary = snapshot.get("primary_assignments")
    aliases = snapshot.get("surface_alias_assignments")
    compatibility = snapshot.get("source_compatibility_assignments")
    candidates = snapshot.get("remaining_allocation_candidates")
    if not all(isinstance(rows, list) for rows in (
        primary,
        aliases,
        compatibility,
        candidates,
    )):
        raise ReleaseFontError("release font snapshot mappings are invalid")

    active_by_code: dict[int, str] = {}
    for row in (*primary, *aliases, *compatibility):
        if not isinstance(row, dict):
            raise ReleaseFontError("release font snapshot mapping row is invalid")
        try:
            code = int(row["code"], 16)
            character = row["character"]
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "release font snapshot mapping row is invalid"
            ) from error
        if code in active_by_code:
            raise ReleaseFontError(
                f"release font snapshot has duplicate active code {code:04X}"
            )
        active_by_code[code] = character
    try:
        candidate_codes = {int(row["code"], 16) for row in candidates}
    except (KeyError, TypeError, ValueError) as error:
        raise ReleaseFontError(
            "release font allocation candidate row is invalid"
        ) from error

    observed_characters = set("".join(observed_names))
    preserved_characters = set(preserved_text)
    reserved_characters = set(reserved_text)
    if (
        not preserved_characters <= observed_characters
        or not reserved_characters <= observed_characters
        or preserved_characters & reserved_characters
    ):
        raise ReleaseFontError(
            "legacy formation compatibility declarations do not match observed names"
        )
    expected_character_count = contract.get("protected_source_character_count")
    if expected_character_count is not None and (
        source_inventory is None
        or expected_character_count
        != len(set("".join(inventory_names)))
    ):
        raise ReleaseFontError(
            "legacy formation compatibility character-count drift"
        )
    legacy_compatibility_characters = {
        row.get("character")
        for row in compatibility
        if isinstance(row, dict)
        and row.get("mapping")
        == "legacy_save_formation_source_compatibility"
    }
    if legacy_compatibility_characters != preserved_characters:
        raise ReleaseFontError(
            "legacy formation compatibility assignments do not match the contract"
        )

    inverse_characters = getattr(table, "inverse_characters", None)
    if not isinstance(inverse_characters, Mapping):
        raise ReleaseFontError("legacy formation audit requires a text table")
    collisions = []
    reclaimable = []
    protected_original_codes = []
    for character in sorted(observed_characters):
        code = inverse_characters.get(character)
        if code is None:
            collisions.append({"character": character, "reason": "unmapped"})
            continue
        protected_original_codes.append(f"{code:04X}")
        effective_character = active_by_code.get(code, character)
        if effective_character != character:
            collisions.append({
                "character": character,
                "code": f"{code:04X}",
                "effective_character": effective_character,
                "reason": "glyph_reassigned",
            })
        if code in candidate_codes:
            reclaimable.append({"character": character, "code": f"{code:04X}"})
    if collisions or reclaimable:
        raise ReleaseFontError(
            "legacy formation glyph compatibility failed: "
            + json.dumps(
                {"collisions": collisions, "reclaimable": reclaimable},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    report = {
        "observed_name_count": len(observed_names),
        "observed_character_count": len(observed_characters),
        "explicit_compatibility_character_count": len(preserved_characters),
        "reserved_unoccupied_character_count": len(reserved_characters),
        "protected_original_code_count": len(protected_original_codes),
        "protected_original_codes": protected_original_codes,
        "collision_count": 0,
        "reclaimable_observed_character_count": 0,
        "all_observed_original_codes_preserved": True,
    }
    if source_inventory is not None:
        report["source_inventory"] = source_inventory
    return report


def audit_runtime_generated_glyph_compatibility(
    snapshot: Mapping[str, object],
    table: object,
    *,
    project_root: Path | None = None,
) -> dict:
    """Prove glyphs synthesized by the executable remain stock-compatible.

    These glyphs do not have to occur in any static text corpus.  The game can
    construct them after loading text, so a corpus-only allocator must treat
    their original codes as live runtime dependencies.
    """

    extensions = snapshot.get("extensions")
    if not isinstance(extensions, list):
        raise ReleaseFontError("release font snapshot extensions are invalid")
    contracts = [
        extension["runtime_generated_glyph_compatibility"]
        for extension in extensions
        if isinstance(extension, dict)
        and "runtime_generated_glyph_compatibility" in extension
    ]
    if len(contracts) != 1 or not isinstance(contracts[0], dict):
        raise ReleaseFontError(
            "release font snapshot must have exactly one runtime-generated "
            "glyph contract"
        )
    contract = contracts[0]
    outputs = contract.get("conversion_outputs")
    literal_outputs = contract.get("literal_outputs", [])
    if (
        not isinstance(outputs, list)
        or not outputs
        or any(not isinstance(row, dict) for row in outputs)
        or not isinstance(literal_outputs, list)
        or any(not isinstance(row, dict) for row in literal_outputs)
    ):
        raise ReleaseFontError(
            "runtime-generated glyph compatibility contract is invalid"
        )

    source_executable = contract.get("source_executable")
    source_report = None
    if source_executable is not None:
        if project_root is None or not isinstance(source_executable, dict):
            raise ReleaseFontError(
                "runtime-generated glyph executable reference is invalid"
            )
        executable_path = _project_path(
            project_root,
            source_executable.get("path"),
        )
        executable_bytes = executable_path.read_bytes()
        executable_sha256 = sha256_bytes(executable_bytes)
        if (
            len(executable_bytes) != source_executable.get("size")
            or executable_sha256 != source_executable.get("sha256")
        ):
            raise ReleaseFontError(
                "runtime-generated glyph executable evidence drift"
            )
        source_report = {
            "path": str(executable_path.relative_to(project_root.resolve())),
            "size": len(executable_bytes),
            "sha256": executable_sha256,
        }

    primary = snapshot.get("primary_assignments")
    aliases = snapshot.get("surface_alias_assignments")
    compatibility = snapshot.get("source_compatibility_assignments")
    candidates = snapshot.get("remaining_allocation_candidates")
    if not all(
        isinstance(rows, list)
        for rows in (primary, aliases, compatibility, candidates)
    ):
        raise ReleaseFontError("release font snapshot mappings are invalid")

    active_by_code: dict[int, str] = {}
    for row in (*primary, *aliases, *compatibility):
        if not isinstance(row, dict):
            raise ReleaseFontError("release font snapshot mapping row is invalid")
        try:
            code = int(row["code"], 16)
            character = row["character"]
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "release font snapshot mapping row is invalid"
            ) from error
        if code in active_by_code:
            raise ReleaseFontError(
                f"release font snapshot has duplicate active code {code:04X}"
            )
        active_by_code[code] = character
    try:
        candidate_codes = {int(row["code"], 16) for row in candidates}
    except (KeyError, TypeError, ValueError) as error:
        raise ReleaseFontError(
            "release font allocation candidate row is invalid"
        ) from error

    table_characters = getattr(table, "characters", None)
    if not isinstance(table_characters, Mapping):
        raise ReleaseFontError(
            "runtime-generated glyph audit requires a text table"
        )
    protected_codes = []
    protected_characters = []
    collisions = []
    reclaimable = []
    evidence_rows = []
    literal_evidence_rows = []
    seen_inputs = set()
    seen_codes = set()
    for row in outputs:
        input_character = row.get("input_character")
        source_character = row.get("source_character")
        try:
            code = int(row["code"], 16)
            evidence_file_offset = int(row["evidence_file_offset"], 16)
            evidence_bytes = bytes.fromhex(row["evidence_bytes_le"])
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "runtime-generated glyph conversion row is invalid"
            ) from error
        if (
            not isinstance(input_character, str)
            or len(input_character) != 1
            or not isinstance(source_character, str)
            or len(source_character) != 1
            or input_character in seen_inputs
            or code in seen_codes
            or table_characters.get(code) != source_character
            or len(evidence_bytes) != 4
        ):
            raise ReleaseFontError(
                "runtime-generated glyph conversion row is invalid"
            )
        seen_inputs.add(input_character)
        seen_codes.add(code)
        protected_codes.append(f"{code:04X}")
        protected_characters.append(source_character)
        if source_executable is not None:
            observed_bytes = executable_bytes[
                evidence_file_offset : evidence_file_offset + len(evidence_bytes)
            ]
            if observed_bytes != evidence_bytes:
                raise ReleaseFontError(
                    "runtime-generated glyph instruction evidence drift"
                )
        evidence_rows.append({
            "input_character": input_character,
            "code": f"{code:04X}",
            "evidence_vma": row.get("evidence_vma"),
            "evidence_file_offset": f"0x{evidence_file_offset:08X}",
            "evidence_bytes_le": evidence_bytes.hex().upper(),
        })
        effective_character = active_by_code.get(code, source_character)
        if effective_character != source_character:
            collisions.append({
                "input_character": input_character,
                "source_character": source_character,
                "code": f"{code:04X}",
                "effective_character": effective_character,
            })
        if code in candidate_codes:
            reclaimable.append({
                "source_character": source_character,
                "code": f"{code:04X}",
            })
    for row in literal_outputs:
        source_character = row.get("source_character")
        producer = row.get("producer")
        role = row.get("role")
        try:
            code = int(row["code"], 16)
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "runtime-generated glyph literal row is invalid"
            ) from error
        if (
            not isinstance(source_character, str)
            or len(source_character) != 1
            or not isinstance(producer, str)
            or not producer
            or not isinstance(role, str)
            or not role
            or code in seen_codes
            or table_characters.get(code) != source_character
        ):
            raise ReleaseFontError(
                "runtime-generated glyph literal row is invalid"
            )
        seen_codes.add(code)
        protected_codes.append(f"{code:04X}")
        protected_characters.append(source_character)
        literal_evidence_rows.append({
            "source_character": source_character,
            "code": f"{code:04X}",
            "producer": producer,
            "role": role,
        })
        effective_character = active_by_code.get(code, source_character)
        if effective_character != source_character:
            collisions.append({
                "source_character": source_character,
                "code": f"{code:04X}",
                "effective_character": effective_character,
                "producer": producer,
                "role": role,
            })
        if code in candidate_codes:
            reclaimable.append({
                "source_character": source_character,
                "code": f"{code:04X}",
            })
    if collisions or reclaimable:
        raise ReleaseFontError(
            "runtime-generated glyph compatibility failed: "
            + json.dumps(
                {"collisions": collisions, "reclaimable": reclaimable},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    relocations = contract.get("relocations")
    if not isinstance(relocations, list):
        raise ReleaseFontError(
            "runtime-generated glyph relocation contract is invalid"
        )
    active_by_character = {
        character: code for code, character in active_by_code.items()
    }
    relocation_rows = []
    for relocation in relocations:
        if not isinstance(relocation, dict):
            raise ReleaseFontError(
                "runtime-generated glyph relocation contract is invalid"
            )
        character = relocation.get("character")
        try:
            from_code = int(relocation["from_code"], 16)
            to_code = int(relocation["to_code"], 16)
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "runtime-generated glyph relocation contract is invalid"
            ) from error
        if (
            not isinstance(character, str)
            or len(character) != 1
            or from_code not in seen_codes
            or to_code in seen_codes
            or active_by_character.get(character) != to_code
        ):
            raise ReleaseFontError(
                "runtime-generated glyph relocation contract is invalid"
            )
        relocation_rows.append({
            "character": character,
            "from_code": f"{from_code:04X}",
            "to_code": f"{to_code:04X}",
        })
    report = {
        "conversion_output_count": len(outputs),
        "literal_output_count": len(literal_outputs),
        "protected_source_characters": "".join(protected_characters),
        "protected_original_codes": protected_codes,
        "instruction_evidence": evidence_rows,
        "literal_output_evidence": literal_evidence_rows,
        "relocations": relocation_rows,
        "collision_count": 0,
        "reclaimable_output_count": 0,
        "all_runtime_generated_original_codes_preserved": True,
    }
    if source_report is not None:
        report["source_executable"] = source_report
    return report


def audit_sound_select_title_glyph_compatibility(
    snapshot: Mapping[str, object],
    table: object,
    *,
    project_root: Path | None = None,
) -> dict:
    """Prove all stock two-byte glyphs used by the 101 song titles survive.

    Sound-select titles stay byte-exact Japanese.  Their codes therefore form
    a live VT1 dependency even though they are deliberately absent from the
    Chinese translation corpus.
    """

    extensions = snapshot.get("extensions")
    if not isinstance(extensions, list):
        raise ReleaseFontError("release font snapshot extensions are invalid")
    contracts = [
        extension["sound_select_title_glyph_compatibility"]
        for extension in extensions
        if isinstance(extension, Mapping)
        and "sound_select_title_glyph_compatibility" in extension
    ]
    if len(contracts) != 1 or not isinstance(contracts[0], Mapping):
        raise ReleaseFontError(
            "release font snapshot must have exactly one sound-select title "
            "glyph contract"
        )
    contract = contracts[0]
    source_member = contract.get("source_member")
    span_raw = contract.get("decoded_span")
    protected_code_rows = contract.get("protected_codes")
    relocations = contract.get("relocations")
    retired_aliases = contract.get("retired_aliases")
    if (
        project_root is None
        or not isinstance(source_member, Mapping)
        or not isinstance(span_raw, Mapping)
        or not isinstance(protected_code_rows, list)
        or not isinstance(relocations, list)
        or not isinstance(retired_aliases, list)
    ):
        raise ReleaseFontError(
            "sound-select title glyph compatibility contract is invalid"
        )

    source_path = _project_path(project_root, source_member.get("path"))
    source_bytes = source_path.read_bytes()
    if (
        len(source_bytes) != source_member.get("size")
        or sha256_bytes(source_bytes) != source_member.get("sha256")
    ):
        raise ReleaseFontError("sound-select COMPDATA source evidence drift")
    try:
        decoded = decode_production(source_bytes)
    except (RuntimeError, ValueError) as error:
        raise ReleaseFontError(
            "sound-select COMPDATA source decode failed"
        ) from error
    if (
        decoded.consumed != len(source_bytes)
        or len(decoded.output) != source_member.get("decoded_size")
        or sha256_bytes(decoded.output) != source_member.get("decoded_sha256")
    ):
        raise ReleaseFontError(
            "sound-select decoded COMPDATA source evidence drift"
        )

    table_characters = getattr(table, "characters", None)
    if not isinstance(table_characters, Mapping):
        raise ReleaseFontError(
            "sound-select title glyph audit requires a text table"
        )
    try:
        span = SoundTitleSpanLock.from_mapping(span_raw)
        titles = verify_sound_title_source(decoded.output, table, span)
    except ValueError as error:
        raise ReleaseFontError(
            "sound-select title source contract is invalid"
        ) from error

    observed_codes: set[int] = set()
    for title in titles:
        raw = decoded.output[title.start:title.end]
        cursor = 0
        while cursor < len(raw):
            lead = raw[cursor]
            cursor += 1
            if lead == 0:
                break
            if 0x31 <= lead <= 0x35:
                if cursor >= len(raw):
                    raise ReleaseFontError(
                        "sound-select title contains a truncated text tag"
                    )
                cursor += 1
                continue
            if 0x80 <= lead <= 0x9F or 0xE0 <= lead <= 0xEA:
                if cursor >= len(raw):
                    raise ReleaseFontError(
                        "sound-select title contains a truncated two-byte code"
                    )
                observed_codes.add((lead << 8) | raw[cursor])
                cursor += 1
    observed_code_rows = [f"{code:04X}" for code in sorted(observed_codes)]
    if (
        protected_code_rows != observed_code_rows
        or contract.get("expected_title_count") != len(titles)
        or contract.get("expected_unique_two_byte_code_count")
        != len(observed_codes)
    ):
        raise ReleaseFontError(
            "sound-select title protected-code inventory drift"
        )

    primary = snapshot.get("primary_assignments")
    aliases = snapshot.get("surface_alias_assignments")
    compatibility = snapshot.get("source_compatibility_assignments")
    candidates = snapshot.get("remaining_allocation_candidates")
    if not all(
        isinstance(rows, list)
        for rows in (primary, aliases, compatibility, candidates)
    ):
        raise ReleaseFontError("release font snapshot mappings are invalid")
    active_by_code: dict[int, str] = {}
    for row in (*primary, *aliases, *compatibility):
        if not isinstance(row, Mapping):
            raise ReleaseFontError("release font snapshot mapping row is invalid")
        try:
            code = int(row["code"], 16)
            character = row["character"]
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "release font snapshot mapping row is invalid"
            ) from error
        if code in active_by_code:
            raise ReleaseFontError(
                f"release font snapshot has duplicate active code {code:04X}"
            )
        active_by_code[code] = character
    try:
        candidate_codes = {int(row["code"], 16) for row in candidates}
    except (KeyError, TypeError, ValueError) as error:
        raise ReleaseFontError(
            "release font allocation candidate row is invalid"
        ) from error

    collisions = []
    reclaimable = []
    for code in sorted(observed_codes):
        source_character = table_characters.get(code)
        if not isinstance(source_character, str) or len(source_character) != 1:
            raise ReleaseFontError(
                "sound-select title code is absent from the stock text table"
            )
        effective_character = active_by_code.get(code, source_character)
        if effective_character != source_character:
            collisions.append({
                "code": f"{code:04X}",
                "source_character": source_character,
                "effective_character": effective_character,
            })
        if code in candidate_codes:
            reclaimable.append({
                "code": f"{code:04X}",
                "source_character": source_character,
            })
    if collisions or reclaimable:
        raise ReleaseFontError(
            "sound-select title glyph compatibility failed: "
            + json.dumps(
                {"collisions": collisions, "reclaimable": reclaimable},
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    active_by_character = {
        character: code for code, character in active_by_code.items()
    }
    relocation_rows = []
    for row in relocations:
        if not isinstance(row, Mapping):
            raise ReleaseFontError(
                "sound-select title glyph relocation contract is invalid"
            )
        character = row.get("character")
        try:
            from_code = int(row["from_code"], 16)
            to_code = int(row["to_code"], 16)
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "sound-select title glyph relocation contract is invalid"
            ) from error
        if (
            not isinstance(character, str)
            or len(character) != 1
            or from_code not in observed_codes
            or to_code in observed_codes
            or active_by_character.get(character) != to_code
        ):
            raise ReleaseFontError(
                "sound-select title glyph relocation contract is invalid"
            )
        relocation_rows.append({
            "character": character,
            "from_code": f"{from_code:04X}",
            "to_code": f"{to_code:04X}",
        })
    for row in retired_aliases:
        if not isinstance(row, Mapping) or not isinstance(
            row.get("character"), str
        ):
            raise ReleaseFontError(
                "sound-select title retired-alias contract is invalid"
            )
        try:
            from_code = int(row["from_code"], 16)
        except (KeyError, TypeError, ValueError) as error:
            raise ReleaseFontError(
                "sound-select title retired-alias contract is invalid"
            ) from error
        if active_by_code.get(from_code) == row["character"]:
            raise ReleaseFontError(
                "sound-select title retired-alias contract is invalid"
            )

    return {
        "source_member": {
            "path": str(source_path.relative_to(project_root.resolve())),
            "size": len(source_bytes),
            "sha256": sha256_bytes(source_bytes),
            "decoded_size": len(decoded.output),
            "decoded_sha256": sha256_bytes(decoded.output),
        },
        "track_title_count": len(titles),
        "unique_two_byte_code_count": len(observed_codes),
        "protected_original_codes": observed_code_rows,
        "relocations": relocation_rows,
        "retired_alias_count": len(retired_aliases),
        "collision_count": 0,
        "reclaimable_output_count": 0,
        "all_sound_select_title_codes_resolve_original_characters": True,
    }


def _selection_digest(entries: Mapping[str, Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry_id in sorted(entries):
        entry = entries[entry_id]
        row = {
            "id": entry_id,
            "source_text_sha256": entry.get("source_text_sha256"),
            "translation": entry.get("translation"),
            "editorial_status": entry.get("editorial_status"),
        }
        digest.update(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def selected_translation_tree_entries(
    project_root: Path,
    profile_document: Mapping[str, object],
) -> tuple[dict[str, dict], dict[str, set[str]], dict]:
    """Load every non-empty translation under the registered release tree."""

    reference = profile_document.get("translation_tree_selection")
    if not isinstance(reference, dict):
        raise ReleaseFontError("translation-tree selection is invalid")
    root_reference = reference.get("root")
    pattern = reference.get("glob", "**/*.json")
    field = reference.get("field", "translation")
    map_fields = reference.get("map_fields", [])
    exclude_globs = reference.get("exclude_globs", [])
    exclude_reason = reference.get("exclude_reason", "")
    selection_id = reference.get("selection_id")
    if (
        not all(
            isinstance(value, str) and value
            for value in (root_reference, pattern, field, selection_id)
        )
        or not isinstance(map_fields, list)
        or any(not isinstance(item, str) or not item for item in map_fields)
        or len(set(map_fields)) != len(map_fields)
        or not isinstance(exclude_globs, list)
        or any(not isinstance(item, str) or not item for item in exclude_globs)
        or len(set(exclude_globs)) != len(exclude_globs)
        or bool(exclude_globs) != bool(exclude_reason)
        or not isinstance(exclude_reason, str)
    ):
        raise ReleaseFontError("translation-tree selection contract is invalid")
    root = _project_path(project_root, root_reference)
    if not root.is_dir():
        raise ReleaseFontError("translation-tree selection root is not a directory")
    discovered_paths = sorted(path for path in root.glob(pattern) if path.is_file())
    excluded_paths = [
        path
        for path in discovered_paths
        if any(path.relative_to(root).match(glob) for glob in exclude_globs)
    ]
    paths = [path for path in discovered_paths if path not in excluded_paths]
    if not paths or (exclude_globs and not excluded_paths):
        raise ReleaseFontError("translation-tree selection is empty")

    entries: dict[str, dict] = {}
    entry_scenes: dict[str, set[str]] = {}
    sources = []
    token_forms: defaultdict[str, Counter[str]] = defaultdict(Counter)
    token_entry_count = 0
    literal_percent_occurrence_count = 0
    literal_percent_entry_count = 0

    def select_translation(
        translation: str,
        metadata: Mapping[str, object],
        source: str,
        pointer: str,
    ) -> int:
        nonlocal token_entry_count
        nonlocal literal_percent_occurrence_count
        nonlocal literal_percent_entry_count
        entry_id = f"{source}#{pointer or '/'}"
        unknown = unrecognized_control_notation_offsets(translation)
        if unknown:
            offsets = ", ".join(str(offset) for offset in unknown)
            raise ReleaseFontError(
                "unrecognized placeholder/control syntax in "
                f"{entry_id} at character offset(s) {offsets}"
            )
        if entry_id in entries:
            raise ReleaseFontError(
                f"duplicate translation-tree entry: {entry_id}"
            )
        entries[entry_id] = {
            "id": entry_id,
            "source_text_sha256": metadata.get("source_text_sha256"),
            "translation": translation,
            "editorial_status": metadata.get("editorial_status"),
        }
        entry_scenes[entry_id] = {f"translation-tree/{source}"}
        tokens = control_notation_tokens(translation)
        if tokens:
            token_entry_count += 1
            for token in tokens:
                token_forms[token.kind][token.text] += 1
        token_positions = {
            index
            for token in tokens
            for index in range(token.start, token.end)
        }
        literal_percents = sum(
            character == "%" and index not in token_positions
            for index, character in enumerate(translation)
        )
        if literal_percents:
            literal_percent_entry_count += 1
            literal_percent_occurrence_count += literal_percents
        return 1

    def visit(value: object, source: str, pointer: str) -> int:
        selected = 0
        if isinstance(value, dict):
            translation = value.get(field)
            if isinstance(translation, str) and translation:
                selected += select_translation(
                    translation, value, source, pointer
                )
            for map_field in map_fields:
                translation_map = value.get(map_field)
                if translation_map is None:
                    continue
                if not isinstance(translation_map, dict) or any(
                    not isinstance(key, str)
                    or not key
                    or not isinstance(mapped, str)
                    or not mapped
                    for key, mapped in translation_map.items()
                ):
                    raise ReleaseFontError(
                        f"translation-map field is invalid: {source}#{map_field}"
                    )
                for key, mapped in translation_map.items():
                    selected += select_translation(
                        mapped,
                        value,
                        source,
                        f"{pointer}/{map_field}/{key}"
                        if pointer
                        else f"/{map_field}/{key}",
                    )
            for key, child in value.items():
                selected += visit(
                    child,
                    source,
                    f"{pointer}/{key}" if pointer else f"/{key}",
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                selected += visit(
                    child,
                    source,
                    f"{pointer}/{index}" if pointer else f"/{index}",
                )
        return selected

    for path in paths:
        relative = str(path.relative_to(project_root.resolve()))
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseFontError(
                f"cannot load translation-tree source: {relative}"
            ) from error
        selected_count = visit(document, relative, "")
        if selected_count:
            sources.append(
                {
                    "path": relative,
                    "sha256": _hash_file(path),
                    "entry_count": selected_count,
                }
            )
    if not entries:
        raise ReleaseFontError("translation-tree selection has no non-empty text")
    occurrence_count = sum(
        sum(forms.values()) for forms in token_forms.values()
    )
    return entries, entry_scenes, {
        "kind": "global_translation_tree",
        "selection_id": selection_id,
        "root": root_reference,
        "glob": pattern,
        "field": field,
        "map_fields": list(map_fields),
        "exclude_globs": list(exclude_globs),
        "exclude_reason": exclude_reason,
        "excluded_sources": [
            {
                "path": str(path.relative_to(project_root.resolve())),
                "sha256": _hash_file(path),
            }
            for path in excluded_paths
        ],
        "source_count": len(sources),
        "sources": sources,
        "unique_entry_count": len(entries),
        "control_tokens": {
            "preservation": "lossless_encoder_control_path",
            "excluded_from_font_glyph_demand": True,
            "entry_count": token_entry_count,
            "occurrence_count": occurrence_count,
            "kinds": {
                kind: {
                    "occurrence_count": sum(forms.values()),
                    "forms": dict(sorted(forms.items())),
                }
                for kind, forms in sorted(token_forms.items())
            },
        },
        "literal_percent_signs": {
            "entry_count": literal_percent_entry_count,
            "occurrence_count": literal_percent_occurrence_count,
        },
        "selection_sha256": _selection_digest(entries),
    }


def rendered_characters(text: str) -> tuple[str, ...]:
    """Return literal glyphs, excluding placeholders and control notation."""

    if not isinstance(text, str):
        raise TypeError("rendered text must be a string")
    skipped = control_notation_positions(text)
    return tuple(
        character
        for index, character in enumerate(text)
        if index not in skipped and character != "\n"
    )


def audit_entry_font(
    entries: Iterable[Mapping[str, object]],
    baseline: Mapping[str, object],
) -> dict:
    """Measure literal translation glyph demand against the built font."""

    counts: Counter[str] = Counter()
    for entry in entries:
        translation = entry.get("translation", "")
        if not isinstance(translation, str):
            raise ReleaseFontError(f"{entry.get('id')} translation is not text")
        counts.update(rendered_characters(translation))

    table = baseline["table"]
    extended_entries = baseline["extended_entries"]
    font = baseline["font"]
    base_assignments = baseline["base_assignments"]
    proposal_assignments = baseline["proposal_assignments"]
    missing = []
    original_han = []
    selected_han = []
    original_visible = []
    selected_visible = []
    for character in sorted(counts):
        assignment = proposal_assignments.get(character)
        mapping = "release_proposal"
        if assignment is None:
            assignment = base_assignments.get(character)
            mapping = "base_codebook"
        if assignment is None:
            if len(character) == 1 and 0x20 <= ord(character) <= 0x7E:
                code = ord(character)
                glyph_index = ascii_glyph_index(code)
                mapping = "printable_ascii"
            else:
                code = table.inverse_characters.get(character)
                glyph_index = None
                mapping = "pinned_text_table"
        else:
            code = assignment["code_value"]
            glyph_index = (
                ascii_glyph_index(code)
                if assignment.get("mapping") == "printable_ascii"
                else None
            )
        if code is None:
            missing.append({
                "character": character,
                "reason": "unmapped",
                "occurrence_count": counts[character],
            })
            continue
        if glyph_index is None:
            try:
                glyph_index = glyph_index_for_code(code, extended_entries)
            except ValueError:
                missing.append({
                    "character": character,
                    "reason": "resolver_unreachable",
                    "occurrence_count": counts[character],
                })
                continue
        glyph = font[glyph_index * GLYPH_SIZE:(glyph_index + 1) * GLYPH_SIZE]
        if not any(glyph) and character not in {" ", "\u3000"}:
            missing.append({
                "character": character,
                "reason": "blank_glyph",
                "occurrence_count": counts[character],
            })
            continue
        row = {
            "character": character,
            "occurrence_count": counts[character],
            "glyph_index": glyph_index,
            "mapping": mapping,
        }
        if character in proposal_assignments or character in base_assignments:
            selected_visible.append(row)
        elif character not in {" ", "\u3000"}:
            original_visible.append(row)
        if is_cjk_unified_ideograph(character):
            (selected_han if character in proposal_assignments else original_han).append(row)
    return {
        "literal_character_count": sum(counts.values()),
        "unique_literal_character_count": len(counts),
        "missing_character_count": len(missing),
        "missing_character_occurrence_count": sum(
            item["occurrence_count"] for item in missing
        ),
        "missing_characters": "".join(item["character"] for item in missing),
        "missing": missing,
        "selected_font_han_count": len(selected_han),
        "original_font_han_count": len(original_han),
        "original_font_han_characters": "".join(
            item["character"] for item in original_han
        ),
        "selected_font_visible_character_count": len(selected_visible),
        "original_font_visible_character_count": len(original_visible),
        "original_font_visible_characters": "".join(
            item["character"] for item in original_visible
        ),
    }


__all__ = [
    "ReleaseFontError",
    "assignment_index",
    "audit_entry_font",
    "audit_legacy_formation_glyph_compatibility",
    "audit_runtime_generated_glyph_compatibility",
    "audit_sound_select_title_glyph_compatibility",
    "baseline_with_original_ascii",
    "rendered_characters",
    "selected_translation_tree_entries",
]
