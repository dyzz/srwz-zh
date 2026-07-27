"""Validated project-level inputs for deterministic SRWZ build profiles."""

from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .font import standard_glyph_index
from .text import SrwzTextEncodeError, TextTable, encode_text


EDITORIAL_STATUS_RANK = {
    "todo": 0,
    "draft": 1,
    "reviewed": 2,
    "final": 3,
}


class ProjectConfigError(ValueError):
    """A build profile or one of its referenced source files is invalid."""


@dataclass(frozen=True)
class TranslationDecision:
    entry_id: str
    source_text_sha256: str
    translation: str
    editorial_status: str
    notes: str
    source_path: str


@dataclass(frozen=True)
class CodebookAssignment:
    assignment_id: str
    character: str
    code: int
    glyph_index: int
    mapping: str
    status: str
    raw_gray_sha256: str
    pixels_4bpp_sha256: str
    packed_glyph_sha256: str

    def to_glyph_lock(self) -> dict:
        return {
            "assignment_id": self.assignment_id,
            "character": self.character,
            "code": f"{self.code:04X}",
            "glyph_index": self.glyph_index,
            "raw_gray_sha256": self.raw_gray_sha256,
            "pixels_4bpp_sha256": self.pixels_4bpp_sha256,
            "packed_glyph_sha256": self.packed_glyph_sha256,
        }


@dataclass(frozen=True)
class SurfaceSpec:
    surface_id: str
    entry_id: str
    source_member: str
    source_text_sha256: str
    layout_kind: str
    offsets: tuple[int, ...]
    encoded_size_with_terminator: int
    chunk_index: int | None
    allocated_length: int | None
    pointer_offsets: tuple[int, ...]
    writer_kind: str
    require_equal_encoded_size: bool
    arena_alignment: int | None
    offset_table_member: str | None
    offset_table_start: int | None
    offset_table_end: int | None
    codec_profile: str
    render_profile: str
    runtime_fixture: str
    source_path: str


@dataclass(frozen=True)
class BuildProfile:
    profile_id: str
    status: str
    minimum_editorial_status: str
    surface_refs: tuple[tuple[str, str], ...]
    translation_sources: tuple[str, ...]
    codebook_path: str
    assignment_ids: tuple[str, ...]
    required_gates: tuple[str, ...]
    source_path: str


@dataclass(frozen=True)
class ProfileSelection:
    profile: BuildProfile
    surfaces: tuple[SurfaceSpec, ...]
    translations: tuple[TranslationDecision, ...]
    assignments: tuple[CodebookAssignment, ...]

    def translation_for(self, entry_id: str) -> TranslationDecision:
        matches = tuple(
            decision
            for decision in self.translations
            if decision.entry_id == entry_id
        )
        if len(matches) != 1:
            raise ProjectConfigError(
                f"profile entry {entry_id!r} has {len(matches)} translations"
            )
        return matches[0]

    def single_surface(self) -> SurfaceSpec:
        if len(self.surfaces) != 1:
            raise ProjectConfigError(
                f"profile {self.profile.profile_id!r} needs exactly one "
                f"surface here, got {len(self.surfaces)}"
            )
        return self.surfaces[0]

    @property
    def character_overrides(self) -> dict[str, int]:
        return {
            assignment.character: assignment.code
            for assignment in self.assignments
        }

    def to_metadata(self) -> dict:
        return {
            "profile_id": self.profile.profile_id,
            "profile": self.profile.source_path,
            "surfaces": [
                {
                    "surface_id": surface.surface_id,
                    "entry_id": surface.entry_id,
                    "spec": surface.source_path,
                }
                for surface in self.surfaces
            ],
            "translation_sources": list(
                self.profile.translation_sources
            ),
            "codebook": self.profile.codebook_path,
            "codebook_assignments": [
                assignment.assignment_id
                for assignment in self.assignments
            ],
            "required_gates": list(self.profile.required_gates),
        }


def _require_string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(f"{context} must be a non-empty string")
    return value


def _require_sha256(value: object, *, context: str) -> str:
    digest = _require_string(value, context=context).lower()
    if len(digest) != 64 or any(
        character not in string.hexdigits for character in digest
    ):
        raise ProjectConfigError(f"{context} must be a SHA-256 digest")
    return digest


def _require_string_list(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProjectConfigError(f"{context} must be an array")
    result = tuple(
        _require_string(item, context=f"{context} item") for item in value
    )
    if len(result) != len(set(result)):
        raise ProjectConfigError(f"{context} contains duplicates")
    return result


def _optional_nonnegative_int(
    value: object,
    *,
    context: str,
) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectConfigError(f"{context} must be a non-negative integer")
    return value


def _resolve_project_source(
    project_root: Path,
    raw: str,
    *,
    context: str,
) -> Path:
    path = Path(_require_string(raw, context=context))
    if path.is_absolute():
        raise ProjectConfigError(f"{context} must be project-relative")
    resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise ProjectConfigError(
            f"{context} escapes the project root: {raw}"
        ) from error
    if not resolved.is_file():
        raise ProjectConfigError(f"{context} is missing: {raw}")
    return resolved


def _relative(project_root: Path, path: Path) -> str:
    return path.relative_to(project_root).as_posix()


def _load_document(
    project_root: Path,
    raw: str,
    *,
    context: str,
) -> tuple[dict, Path]:
    path = _resolve_project_source(project_root, raw, context=context)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ProjectConfigError(f"{context} root must be an object")
    if document.get("schema_version") != 1:
        raise ProjectConfigError(f"{context} has an unsupported schema")
    return document, path


def _load_surface(
    project_root: Path,
    raw: str,
    *,
    expected_id: str,
) -> SurfaceSpec:
    document, path = _load_document(
        project_root,
        raw,
        context=f"surface {expected_id}",
    )
    surface_id = _require_string(
        document.get("surface_id"),
        context=f"surface {expected_id} id",
    )
    if surface_id != expected_id:
        raise ProjectConfigError(
            f"surface reference {expected_id!r} resolves to {surface_id!r}"
        )
    record = document.get("record")
    if not isinstance(record, dict):
        raise ProjectConfigError(f"surface {surface_id} has no record")
    layout = document.get("layout")
    if not isinstance(layout, dict):
        raise ProjectConfigError(f"surface {surface_id} has no layout")
    raw_offsets = layout.get("offsets")
    if not isinstance(raw_offsets, list) or not raw_offsets:
        raise ProjectConfigError(
            f"surface {surface_id} offsets must be a non-empty array"
        )
    offsets = tuple(raw_offsets)
    if any(not isinstance(offset, int) or offset < 0 for offset in offsets):
        raise ProjectConfigError(f"surface {surface_id} has invalid offsets")
    if len(offsets) != len(set(offsets)):
        raise ProjectConfigError(
            f"surface {surface_id} offsets contain duplicates"
        )
    encoded_size = layout.get("encoded_size_with_terminator")
    if not isinstance(encoded_size, int) or encoded_size <= 0:
        raise ProjectConfigError(
            f"surface {surface_id} encoded size is invalid"
        )
    writer = document.get("writer")
    if not isinstance(writer, dict):
        raise ProjectConfigError(f"surface {surface_id} has no writer")
    writer_kind = _require_string(
        writer.get("kind"),
        context=f"surface {surface_id} writer kind",
    )
    chunk_index = _optional_nonnegative_int(
        layout.get("chunk_index"),
        context=f"surface {surface_id} chunk index",
    )
    allocated_length = _optional_nonnegative_int(
        layout.get("allocated_length"),
        context=f"surface {surface_id} allocated length",
    )
    raw_pointer_offsets = layout.get("pointer_offsets", [])
    if not isinstance(raw_pointer_offsets, list):
        raise ProjectConfigError(
            f"surface {surface_id} pointer offsets must be an array"
        )
    pointer_offsets = tuple(raw_pointer_offsets)
    if any(
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
        for offset in pointer_offsets
    ):
        raise ProjectConfigError(
            f"surface {surface_id} has invalid pointer offsets"
        )
    if len(pointer_offsets) != len(set(pointer_offsets)):
        raise ProjectConfigError(
            f"surface {surface_id} pointer offsets contain duplicates"
        )
    arena_alignment = _optional_nonnegative_int(
        writer.get("arena_alignment"),
        context=f"surface {surface_id} arena alignment",
    )
    raw_offset_table = writer.get("archive_offset_table")
    if raw_offset_table is None:
        offset_table_member = None
        offset_table_start = None
        offset_table_end = None
    elif isinstance(raw_offset_table, dict):
        offset_table_member = _require_string(
            raw_offset_table.get("member"),
            context=f"surface {surface_id} offset table member",
        )
        offset_table_start = _optional_nonnegative_int(
            raw_offset_table.get("start"),
            context=f"surface {surface_id} offset table start",
        )
        offset_table_end = _optional_nonnegative_int(
            raw_offset_table.get("end_inclusive"),
            context=f"surface {surface_id} offset table end",
        )
        if (
            offset_table_start is None
            or offset_table_end is None
            or offset_table_start >= offset_table_end
        ):
            raise ProjectConfigError(
                f"surface {surface_id} offset table range is invalid"
            )
    else:
        raise ProjectConfigError(
            f"surface {surface_id} archive offset table is invalid"
        )
    if writer_kind == "fixed_preimage":
        if (
            chunk_index is not None
            or allocated_length is not None
            or pointer_offsets
            or arena_alignment is not None
            or offset_table_member is not None
        ):
            raise ProjectConfigError(
                f"surface {surface_id} fixed writer has archive-only fields"
            )
    elif writer_kind == "summary_fixed_allocation":
        if (
            chunk_index is None
            or len(offsets) != 1
            or allocated_length != encoded_size
            or pointer_offsets
            or arena_alignment is not None
            or offset_table_member != "SLPS_258.87"
        ):
            raise ProjectConfigError(
                f"surface {surface_id} summary writer contract is invalid"
            )
    elif writer_kind == "stage_arena_pointer":
        if (
            chunk_index is None
            or len(offsets) != 1
            or allocated_length is not None
            or len(pointer_offsets) != 1
            or arena_alignment is None
            or arena_alignment <= 0
            or arena_alignment & (arena_alignment - 1)
            or offset_table_member != "HEDBDY/HB.BIN"
        ):
            raise ProjectConfigError(
                f"surface {surface_id} stage writer contract is invalid"
            )
    else:
        raise ProjectConfigError(
            f"surface {surface_id} has unsupported writer {writer_kind!r}"
        )
    render = document.get("render")
    if not isinstance(render, dict):
        raise ProjectConfigError(f"surface {surface_id} has no render profile")
    return SurfaceSpec(
        surface_id=surface_id,
        entry_id=_require_string(
            record.get("entry_id"),
            context=f"surface {surface_id} entry id",
        ),
        source_member=_require_string(
            document.get("source_member"),
            context=f"surface {surface_id} source member",
        ),
        source_text_sha256=_require_sha256(
            record.get("source_text_sha256"),
            context=f"surface {surface_id} source text hash",
        ),
        layout_kind=_require_string(
            layout.get("kind"),
            context=f"surface {surface_id} layout kind",
        ),
        offsets=offsets,
        encoded_size_with_terminator=encoded_size,
        chunk_index=chunk_index,
        allocated_length=allocated_length,
        pointer_offsets=pointer_offsets,
        writer_kind=writer_kind,
        require_equal_encoded_size=(
            writer.get("require_equal_encoded_size") is True
        ),
        arena_alignment=arena_alignment,
        offset_table_member=offset_table_member,
        offset_table_start=offset_table_start,
        offset_table_end=offset_table_end,
        codec_profile=_require_string(
            document.get("codec_profile"),
            context=f"surface {surface_id} codec profile",
        ),
        render_profile=_require_string(
            render.get("profile"),
            context=f"surface {surface_id} render profile",
        ),
        runtime_fixture=_require_string(
            document.get("runtime_fixture"),
            context=f"surface {surface_id} runtime fixture",
        ),
        source_path=_relative(project_root, path),
    )


def _load_translations(
    project_root: Path,
    sources: Iterable[str],
) -> tuple[TranslationDecision, ...]:
    decisions = []
    seen = set()
    for raw in sources:
        document, path = _load_document(
            project_root,
            raw,
            context=f"translation source {raw}",
        )
        entries = document.get("entries")
        if not isinstance(entries, list):
            raise ProjectConfigError(
                f"translation source {raw} entries must be an array"
            )
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ProjectConfigError(
                    f"translation source {raw} entry {index} is invalid"
                )
            if "source_text" in entry:
                raise ProjectConfigError(
                    f"translation source {raw} must not duplicate JP text"
                )
            entry_id = _require_string(
                entry.get("id"),
                context=f"translation source {raw} entry id",
            )
            if entry_id in seen:
                raise ProjectConfigError(
                    f"duplicate translation entry id: {entry_id}"
                )
            seen.add(entry_id)
            status = _require_string(
                entry.get("editorial_status"),
                context=f"translation {entry_id} editorial status",
            )
            if status not in EDITORIAL_STATUS_RANK:
                raise ProjectConfigError(
                    f"translation {entry_id} has invalid status {status!r}"
                )
            decisions.append(
                TranslationDecision(
                    entry_id=entry_id,
                    source_text_sha256=_require_sha256(
                        entry.get("source_text_sha256"),
                        context=f"translation {entry_id} source hash",
                    ),
                    translation=_require_string(
                        entry.get("translation"),
                        context=f"translation {entry_id} text",
                    ),
                    editorial_status=status,
                    notes=(
                        entry.get("notes")
                        if isinstance(entry.get("notes"), str)
                        else ""
                    ),
                    source_path=_relative(project_root, path),
                )
            )
    return tuple(decisions)


def _load_codebook(
    project_root: Path,
    raw: str,
) -> tuple[CodebookAssignment, ...]:
    document, _ = _load_document(
        project_root,
        raw,
        context="codebook",
    )
    records = document.get("assignments")
    if not isinstance(records, list):
        raise ProjectConfigError("codebook assignments must be an array")
    assignments = []
    seen_ids = set()
    seen_characters = set()
    seen_codes = set()
    seen_glyphs = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ProjectConfigError(
                f"codebook assignment {index} is invalid"
            )
        assignment_id = _require_string(
            record.get("id"),
            context=f"codebook assignment {index} id",
        )
        character = _require_string(
            record.get("character"),
            context=f"codebook assignment {assignment_id} character",
        )
        if len(character) != 1:
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} needs one character"
            )
        raw_code = _require_string(
            record.get("code"),
            context=f"codebook assignment {assignment_id} code",
        )
        try:
            code = int(raw_code, 16)
        except ValueError as error:
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} code is invalid"
            ) from error
        glyph_index = record.get("glyph_index")
        if not 0 <= code <= 0xFFFF:
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} code is out of range"
            )
        if code & 0xFF == 0:
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} has a NUL low byte"
            )
        if not isinstance(glyph_index, int) or glyph_index < 0:
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} glyph is invalid"
            )
        mapping = _require_string(
            record.get("mapping"),
            context=f"codebook assignment {assignment_id} mapping",
        )
        if mapping != "standard":
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} mapping is unsupported"
            )
        try:
            resolved_glyph_index = standard_glyph_index(code)
        except ValueError as error:
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} code is outside "
                "the standard glyph branch"
            ) from error
        if resolved_glyph_index != glyph_index:
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} code/glyph mismatch"
            )
        if (
            assignment_id in seen_ids
            or character in seen_characters
            or code in seen_codes
            or glyph_index in seen_glyphs
        ):
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} is not unique"
            )
        seen_ids.add(assignment_id)
        seen_characters.add(character)
        seen_codes.add(code)
        seen_glyphs.add(glyph_index)
        raster = record.get("raster")
        if not isinstance(raster, dict):
            raise ProjectConfigError(
                f"codebook assignment {assignment_id} has no raster lock"
            )
        assignments.append(
            CodebookAssignment(
                assignment_id=assignment_id,
                character=character,
                code=code,
                glyph_index=glyph_index,
                mapping=mapping,
                status=_require_string(
                    record.get("status"),
                    context=(
                        f"codebook assignment {assignment_id} status"
                    ),
                ),
                raw_gray_sha256=_require_sha256(
                    raster.get("raw_gray_sha256"),
                    context=(
                        f"codebook assignment {assignment_id} gray hash"
                    ),
                ),
                pixels_4bpp_sha256=_require_sha256(
                    raster.get("pixels_4bpp_sha256"),
                    context=(
                        f"codebook assignment {assignment_id} pixels hash"
                    ),
                ),
                packed_glyph_sha256=_require_sha256(
                    raster.get("packed_glyph_sha256"),
                    context=(
                        f"codebook assignment {assignment_id} packed hash"
                    ),
                ),
            )
        )
    return tuple(assignments)


def load_build_profile(
    project_root: Path,
    profile_path: Path,
) -> ProfileSelection:
    project_root = project_root.resolve()
    profile_path = profile_path.resolve()
    try:
        profile_relative = profile_path.relative_to(project_root).as_posix()
    except ValueError as error:
        raise ProjectConfigError(
            "build profile must be inside the project root"
        ) from error
    profile_document, _ = _load_document(
        project_root,
        profile_relative,
        context="build profile",
    )
    profile_id = _require_string(
        profile_document.get("profile_id"),
        context="build profile id",
    )
    surface_records = profile_document.get("surfaces")
    if not isinstance(surface_records, list) or not surface_records:
        raise ProjectConfigError("build profile needs at least one surface")
    surface_refs = []
    surfaces = []
    seen_surface_ids = set()
    for index, record in enumerate(surface_records):
        if not isinstance(record, dict):
            raise ProjectConfigError(
                f"build profile surface {index} is invalid"
            )
        surface_id = _require_string(
            record.get("id"),
            context=f"build profile surface {index} id",
        )
        spec = _require_string(
            record.get("spec"),
            context=f"build profile surface {surface_id} spec",
        )
        if surface_id in seen_surface_ids:
            raise ProjectConfigError(
                f"duplicate profile surface id: {surface_id}"
            )
        seen_surface_ids.add(surface_id)
        surface_refs.append((surface_id, spec))
        surfaces.append(
            _load_surface(
                project_root,
                spec,
                expected_id=surface_id,
            )
        )
    translation_sources = _require_string_list(
        profile_document.get("translation_sources"),
        context="build profile translation sources",
    )
    assignment_ids = _require_string_list(
        profile_document.get("codebook_assignments"),
        context="build profile codebook assignments",
    )
    required_gates = _require_string_list(
        profile_document.get("required_gates"),
        context="build profile required gates",
    )
    if not required_gates:
        raise ProjectConfigError(
            "build profile needs at least one required gate"
        )
    codebook_path = _require_string(
        profile_document.get("codebook"),
        context="build profile codebook",
    )
    minimum_status = _require_string(
        profile_document.get("minimum_editorial_status"),
        context="build profile minimum editorial status",
    )
    if minimum_status not in EDITORIAL_STATUS_RANK:
        raise ProjectConfigError(
            f"invalid minimum editorial status: {minimum_status!r}"
        )
    profile = BuildProfile(
        profile_id=profile_id,
        status=_require_string(
            profile_document.get("status"),
            context="build profile status",
        ),
        minimum_editorial_status=minimum_status,
        surface_refs=tuple(surface_refs),
        translation_sources=translation_sources,
        codebook_path=codebook_path,
        assignment_ids=assignment_ids,
        required_gates=required_gates,
        source_path=profile_relative,
    )
    translations = _load_translations(project_root, translation_sources)
    all_assignments = _load_codebook(project_root, codebook_path)
    assignments_by_id = {
        assignment.assignment_id: assignment
        for assignment in all_assignments
    }
    missing_assignments = sorted(
        set(assignment_ids) - set(assignments_by_id)
    )
    if missing_assignments:
        raise ProjectConfigError(
            f"profile has unknown codebook assignments: "
            f"{missing_assignments!r}"
        )
    selected_assignments = tuple(
        assignments_by_id[assignment_id]
        for assignment_id in assignment_ids
    )
    for assignment in selected_assignments:
        if assignment.status != "assigned":
            raise ProjectConfigError(
                f"codebook assignment {assignment.assignment_id} status "
                f"{assignment.status!r} is not selectable"
            )
    selection = ProfileSelection(
        profile=profile,
        surfaces=tuple(surfaces),
        translations=translations,
        assignments=selected_assignments,
    )
    minimum_rank = EDITORIAL_STATUS_RANK[minimum_status]
    for surface in selection.surfaces:
        decision = selection.translation_for(surface.entry_id)
        if decision.source_text_sha256 != surface.source_text_sha256:
            raise ProjectConfigError(
                f"surface {surface.surface_id} and translation "
                f"{decision.entry_id} source hashes differ"
            )
        if EDITORIAL_STATUS_RANK[decision.editorial_status] < minimum_rank:
            raise ProjectConfigError(
                f"translation {decision.entry_id} status "
                f"{decision.editorial_status!r} is below "
                f"{minimum_status!r}"
            )
    return selection


def validate_profile_encoding(
    selection: ProfileSelection,
    table: TextTable,
) -> dict:
    overrides = selection.character_overrides
    base_characters = frozenset(table.inverse_characters)
    for assignment in selection.assignments:
        if assignment.code in table.characters:
            raise ProjectConfigError(
                f"codebook code {assignment.code:04X} conflicts with "
                "the pinned text table"
            )
        if assignment.character in base_characters:
            raise ProjectConfigError(
                f"codebook character {assignment.character!r} is already "
                "encodable"
            )
    used_assignments = set()
    encoded_records = []
    for surface in selection.surfaces:
        decision = selection.translation_for(surface.entry_id)
        used_assignments.update(
            character
            for character in decision.translation
            if character in overrides
        )
        try:
            payload = encode_text(
                decision.translation,
                table,
                overrides=overrides,
                terminate=True,
            )
        except SrwzTextEncodeError as error:
            raise ProjectConfigError(
                f"translation {decision.entry_id} is not encodable: {error}"
            ) from error
        if (
            surface.require_equal_encoded_size
            and len(payload) != surface.encoded_size_with_terminator
        ):
            raise ProjectConfigError(
                f"translation {decision.entry_id} encodes to "
                f"{len(payload)} bytes, expected "
                f"{surface.encoded_size_with_terminator}"
            )
        encoded_records.append(
            {
                "entry_id": decision.entry_id,
                "surface_id": surface.surface_id,
                "encoded_size": len(payload),
                "encoded_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    selected_characters = set(overrides)
    if used_assignments != selected_characters:
        unused = sorted(selected_characters - used_assignments)
        raise ProjectConfigError(
            f"profile selects unused codebook characters: {unused!r}"
        )
    return {
        "profile_id": selection.profile.profile_id,
        "surface_count": len(selection.surfaces),
        "translation_count": len(
            {surface.entry_id for surface in selection.surfaces}
        ),
        "codebook_assignment_count": len(selection.assignments),
        "encoded_records": encoded_records,
    }


__all__ = [
    "BuildProfile",
    "CodebookAssignment",
    "EDITORIAL_STATUS_RANK",
    "ProfileSelection",
    "ProjectConfigError",
    "SurfaceSpec",
    "TranslationDecision",
    "load_build_profile",
    "validate_profile_encoding",
]
