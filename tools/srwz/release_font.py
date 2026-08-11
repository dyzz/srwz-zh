"""Corpus selection and coverage audit for the flattened release font."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from .font import (
    GLYPH_SIZE,
    ascii_glyph_index,
    glyph_index_for_code,
    is_cjk_unified_ideograph,
    sha256_bytes,
)
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
    "baseline_with_original_ascii",
    "rendered_characters",
    "selected_translation_tree_entries",
]
