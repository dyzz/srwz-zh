"""Build the profile-owned menu, summary, and story canary components."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .archive import load_offset_layout
from .canary import (
    CanaryError,
    build_static_canary,
    rebuild_archive_with_replacement,
    verify_file,
)
from .codec import decode, encode, reencode_changed_suffix
from .corpus import text_sha256
from .iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .patch_audit import summarize_diff
from .project import (
    ProjectConfigError,
    SurfaceSpec,
    load_build_profile,
    validate_profile_encoding,
)
from .stage import parse_stage, read_stage_function_addresses
from .summary import parse_summary
from .text import TextTable, encode_text, load_text_table
from .writeback import WritebackError, sha256_bytes
from .writers import (
    apply_summary_replacements,
    build_executable_offset_patch_plan,
    relocate_stage_text_to_arena,
)


class CompleteCanaryError(ValueError):
    """The full three-surface canary violates a pinned production contract."""


def _load_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise CompleteCanaryError(f"unsupported config schema: {path}")
    return document


def _resolve(project_root: Path, raw: str) -> Path:
    path = (project_root / raw).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as error:
        raise CompleteCanaryError(
            f"config path escapes project root: {raw}"
        ) from error
    return path


def _read_iso_member(source, member) -> bytes:
    source.seek(member.extent_lba * SECTOR_SIZE)
    data = source.read(member.size)
    if len(data) != member.size:
        raise CompleteCanaryError(f"short ISO member read: {member.path}")
    return data


def _augmented_table(
    table: TextTable,
    overrides: Mapping[str, int],
) -> TextTable:
    return TextTable(
        characters={
            **table.characters,
            **{code: character for character, code in overrides.items()},
        },
        tags=table.tags,
    )


def _surface_by_writer(
    surfaces: tuple[SurfaceSpec, ...],
    writer_kind: str,
) -> SurfaceSpec:
    matches = tuple(
        surface
        for surface in surfaces
        if surface.writer_kind == writer_kind
    )
    if len(matches) != 1:
        raise CompleteCanaryError(
            f"full profile needs one {writer_kind!r} surface, "
            f"got {len(matches)}"
        )
    return matches[0]


def _offset_spec(surface: SurfaceSpec) -> ExecutableOffsetSpec:
    if (
        surface.offset_table_member is None
        or surface.offset_table_start is None
        or surface.offset_table_end is None
    ):
        raise CompleteCanaryError(
            f"{surface.surface_id} has no offset-table contract"
        )
    return ExecutableOffsetSpec(
        name=f"{surface.source_member} offsets",
        member=surface.offset_table_member,
        table_start=surface.offset_table_start,
        table_end=surface.offset_table_end,
    )


def _verify_unchanged_chunks(
    before: bytes,
    before_offsets: tuple[int, ...],
    after: bytes,
    after_offsets: tuple[int, ...],
    *,
    replaced_index: int,
    context: str,
) -> int:
    if len(before_offsets) != len(after_offsets):
        raise CompleteCanaryError(f"{context} offset count changed")
    unchanged = 0
    for index in range(len(before_offsets) - 1):
        if index == replaced_index:
            continue
        old = before[before_offsets[index]:before_offsets[index + 1]]
        new = after[after_offsets[index]:after_offsets[index + 1]]
        if old != new:
            raise CompleteCanaryError(
                f"{context} non-target chunk {index} changed"
            )
        unchanged += 1
    return unchanged


def _output_lock(data: bytes) -> dict:
    return {"size": len(data), "sha256": sha256_bytes(data)}


def _verify_output_locks(
    outputs: Mapping[str, bytes],
    expected: Mapping,
) -> None:
    for name, data in outputs.items():
        lock = expected.get(name)
        if not isinstance(lock, dict):
            raise CompleteCanaryError(
                f"expected output lock is missing for {name}"
            )
        actual = _output_lock(data)
        if actual != {
            "size": lock.get("size"),
            "sha256": lock.get("sha256"),
        }:
            raise CompleteCanaryError(
                f"{name} output does not match its pinned lock"
            )


def build_complete_canary(
    project_root: Path,
    config_path: Path,
    *,
    enforce_expected_outputs: bool = True,
) -> tuple[dict[str, bytes], dict]:
    """Build five replacement members for the complete E2 canary profile."""

    project_root = project_root.resolve()
    config = _load_json(config_path)
    if config.get("profile_id") != "canary-complete":
        raise CompleteCanaryError("full component profile must be canary-complete")
    codec = config.get("codec")
    if not isinstance(codec, dict):
        raise CompleteCanaryError("full component codec contract is missing")
    summary_strategy = codec.get("summary_strategy")
    story_strategy = codec.get("story_strategy")
    if summary_strategy not in {"literal", "greedy", "splice"}:
        raise CompleteCanaryError("summary codec strategy is invalid")
    if story_strategy not in {"literal", "greedy", "splice"}:
        raise CompleteCanaryError("story codec strategy is invalid")
    if codec.get("archive_alignment") != 16:
        raise CompleteCanaryError(
            "full component archive alignment must be 16"
        )

    table = load_text_table(
        _resolve(project_root, config["inputs"]["text_table"])
    )
    try:
        selection = load_build_profile(
            project_root,
            _resolve(project_root, config["profile"]),
        )
        profile_validation = validate_profile_encoding(selection, table)
    except ProjectConfigError as error:
        raise CompleteCanaryError(f"invalid full profile: {error}") from error
    if selection.profile.profile_id != "canary-complete":
        raise CompleteCanaryError("selected profile id is not canary-complete")
    isolated_profile_inputs = {}
    isolated_profile_validations = {}
    raw_isolated_profiles = config.get("isolated_profiles")
    if not isinstance(raw_isolated_profiles, dict):
        raise CompleteCanaryError("isolated profile contracts are missing")
    complete_entry_ids = {
        surface.entry_id
        for surface in selection.surfaces
    }
    for profile_id, raw_path in raw_isolated_profiles.items():
        try:
            isolated = load_build_profile(
                project_root,
                _resolve(project_root, raw_path),
            )
            isolated_validation = validate_profile_encoding(
                isolated,
                table,
            )
        except ProjectConfigError as error:
            raise CompleteCanaryError(
                f"invalid isolated profile {profile_id}: {error}"
            ) from error
        if isolated.profile.profile_id != profile_id:
            raise CompleteCanaryError(
                f"isolated profile id mismatch for {profile_id}"
            )
        isolated_entry_ids = {
            surface.entry_id
            for surface in isolated.surfaces
        }
        if not isolated_entry_ids or not isolated_entry_ids.issubset(
            complete_entry_ids
        ):
            raise CompleteCanaryError(
                f"isolated profile {profile_id} is not a full-profile subset"
            )
        for entry_id in isolated_entry_ids:
            if (
                isolated.translation_for(entry_id).translation
                != selection.translation_for(entry_id).translation
            ):
                raise CompleteCanaryError(
                    f"isolated translation differs for {entry_id}"
                )
        if isolated.character_overrides != selection.character_overrides:
            raise CompleteCanaryError(
                f"isolated codebook differs for {profile_id}"
            )
        isolated_profile_inputs[profile_id] = isolated.to_metadata()
        isolated_profile_validations[profile_id] = isolated_validation

    menu_surface = _surface_by_writer(
        selection.surfaces,
        "fixed_preimage",
    )
    summary_surface = _surface_by_writer(
        selection.surfaces,
        "summary_fixed_allocation",
    )
    story_surface = _surface_by_writer(
        selection.surfaces,
        "stage_arena_pointer",
    )
    overrides = selection.character_overrides
    augmented_table = _augmented_table(table, overrides)

    menu_config_path = _resolve(
        project_root,
        config["inputs"]["menu_component_config"],
    )
    try:
        menu_slps, menu_vt1, preview, menu_report = build_static_canary(
            project_root,
            menu_config_path,
        )
    except CanaryError as error:
        raise CompleteCanaryError(
            f"menu/font subcomponent failed: {error}"
        ) from error
    menu_decision = selection.translation_for(menu_surface.entry_id)
    menu_patch = menu_report["text_patch"]
    if (
        menu_patch["entry_id"] != menu_surface.entry_id
        or menu_patch["replacement_text"] != menu_decision.translation
    ):
        raise CompleteCanaryError(
            "menu subcomponent differs from complete profile ownership"
        )

    inputs = config["inputs"]
    slps_path = _resolve(project_root, inputs["slps"]["path"])
    mtv_path = _resolve(project_root, inputs["mtv_pros"]["path"])
    stage_path = _resolve(project_root, inputs["stage"]["path"])
    verify_file(slps_path, inputs["slps"], context="SLPS input")
    verify_file(mtv_path, inputs["mtv_pros"], context="MTV_PROS input")
    verify_file(stage_path, inputs["stage"], context="STAGE input")
    source_slps = slps_path.read_bytes()
    source_mtv = mtv_path.read_bytes()
    source_stage = stage_path.read_bytes()

    source_iso_path = _resolve(
        project_root,
        inputs["source_iso"]["path"],
    )
    verify_file(
        source_iso_path,
        inputs["source_iso"],
        context="source ISO",
    )
    image = scan_iso9660(source_iso_path)
    members = member_map(image)
    hb_member_path = inputs["hb"]["member"]
    hb_member = members.get(hb_member_path)
    if hb_member is None:
        raise CompleteCanaryError(f"source ISO has no {hb_member_path}")
    with source_iso_path.open("rb") as source:
        source_hb = _read_iso_member(source, hb_member)
    if _output_lock(source_hb) != {
        "size": inputs["hb"]["size"],
        "sha256": inputs["hb"]["sha256"],
    }:
        raise CompleteCanaryError("HB input baseline mismatch")

    # MTV_PROS: fixed allocation -> chunk re-encode -> SLPS table update.
    summary_spec = _offset_spec(summary_surface)
    summary_offsets = read_executable_archive_offsets(
        source_slps,
        summary_spec,
        len(source_mtv),
    )
    if read_executable_archive_offsets(
        menu_slps,
        summary_spec,
        len(source_mtv),
    ) != summary_offsets:
        raise CompleteCanaryError(
            "menu subcomponent unexpectedly changed MTV_PROS offsets"
        )
    assert summary_surface.chunk_index is not None
    summary_index = summary_surface.chunk_index
    summary_stream = source_mtv[
        summary_offsets[summary_index]:summary_offsets[summary_index + 1]
    ]
    summary_decoded_result = decode(summary_stream)
    summary_parsed = parse_summary(
        summary_decoded_result.output,
        table,
        chunk_index=summary_index,
    )
    summary_matches = tuple(
        entry
        for entry in summary_parsed.entries
        if entry.entry_id == summary_surface.entry_id
    )
    if len(summary_matches) != 1:
        raise CompleteCanaryError("summary source entry is not unique")
    summary_entry = summary_matches[0]
    if (
        summary_entry.text_offset != summary_surface.offsets[0]
        or summary_entry.allocated_length
        != summary_surface.allocated_length
        or text_sha256(summary_entry.text)
        != summary_surface.source_text_sha256
        or len(encode_text(summary_entry.text, table))
        != summary_surface.encoded_size_with_terminator
    ):
        raise CompleteCanaryError("summary source layout/hash mismatch")
    summary_decision = selection.translation_for(summary_surface.entry_id)
    rebuilt_summary_decoded = apply_summary_replacements(
        summary_decoded_result.output,
        table,
        chunk_index=summary_index,
        replacements={
            summary_surface.entry_id: summary_decision.translation,
        },
        overrides=overrides,
    )
    encoded_summary = (
        reencode_changed_suffix(
            summary_stream,
            rebuilt_summary_decoded,
        )
        if summary_strategy == "splice"
        else encode(
            rebuilt_summary_decoded,
            strategy=summary_strategy,
        )
    )
    summary_round_trip = decode(encoded_summary)
    if (
        summary_round_trip.output != rebuilt_summary_decoded
        or summary_round_trip.consumed != len(encoded_summary)
    ):
        raise CompleteCanaryError("summary encoded chunk fails round-trip")
    rebuilt_mtv, rebuilt_summary_offsets, summary_padding = (
        rebuild_archive_with_replacement(
            source_mtv,
            summary_offsets,
            chunk_index=summary_index,
            encoded_replacement=encoded_summary,
            minimum_allocation=len(summary_stream),
        )
    )
    summary_unchanged = _verify_unchanged_chunks(
        source_mtv,
        summary_offsets,
        rebuilt_mtv,
        rebuilt_summary_offsets,
        replaced_index=summary_index,
        context="MTV_PROS",
    )
    summary_offset_plan = build_executable_offset_patch_plan(
        menu_slps,
        summary_spec,
        rebuilt_summary_offsets,
    )
    rebuilt_slps = summary_offset_plan.apply(menu_slps)
    if read_executable_archive_offsets(
        rebuilt_slps,
        summary_spec,
        len(rebuilt_mtv),
    ) != rebuilt_summary_offsets:
        raise CompleteCanaryError("rebuilt MTV_PROS offsets fail SLPS reread")
    if (
        "canary-story" in isolated_profile_inputs
        and rebuilt_slps != menu_slps
    ):
        raise CompleteCanaryError(
            "story fixture cannot reuse SLPS after summary offsets change"
        )
    reread_summary = parse_summary(
        decode(
            rebuilt_mtv[
                rebuilt_summary_offsets[summary_index]:
                rebuilt_summary_offsets[summary_index + 1]
            ]
        ).output,
        augmented_table,
        chunk_index=summary_index,
    )
    if next(
        entry.text
        for entry in reread_summary.entries
        if entry.entry_id == summary_surface.entry_id
    ) != summary_decision.translation:
        raise CompleteCanaryError("summary output text reread mismatch")

    # STAGE: aligned arena relocation -> chunk re-encode -> HB table update.
    stage_layout = load_offset_layout(
        _resolve(project_root, inputs["stage_layout"])
    )
    if (
        stage_layout.offsets[-1] != len(source_stage)
        or stage_layout.expected_sha256 != sha256_bytes(source_stage)
    ):
        raise CompleteCanaryError("STAGE layout baseline mismatch")
    story_spec = _offset_spec(story_surface)
    hb_offsets = read_executable_archive_offsets(
        source_hb,
        story_spec,
        len(source_stage),
    )
    if hb_offsets != stage_layout.offsets:
        raise CompleteCanaryError(
            "HB STAGE offsets differ from the pinned layout"
        )
    assert story_surface.chunk_index is not None
    story_index = story_surface.chunk_index
    story_stream = source_stage[
        hb_offsets[story_index]:hb_offsets[story_index + 1]
    ]
    story_decoded_result = decode(story_stream)
    functions = read_stage_function_addresses(source_slps)
    function_address = functions[story_index]
    story_parsed = parse_stage(
        story_decoded_result.output,
        table,
        stage_index=story_index,
        function_address=function_address,
    )
    story_matches = tuple(
        entry
        for entry in story_parsed.entries
        if entry.entry_id == story_surface.entry_id
    )
    if len(story_matches) != 1:
        raise CompleteCanaryError("story source entry is not unique")
    story_entry = story_matches[0]
    if (
        story_entry.text_offset != story_surface.offsets[0]
        or story_entry.pointer_offset != story_surface.pointer_offsets[0]
        or text_sha256(story_entry.text)
        != story_surface.source_text_sha256
        or len(encode_text(story_entry.text, table, terminate=True))
        != story_surface.encoded_size_with_terminator
    ):
        raise CompleteCanaryError("story source layout/hash mismatch")
    story_decision = selection.translation_for(story_surface.entry_id)
    replacement_message_size = len(
        encode_text(
            story_decision.translation,
            table,
            overrides=overrides,
            terminate=True,
        )
    )
    if replacement_message_size <= story_surface.encoded_size_with_terminator:
        raise CompleteCanaryError(
            "story canary must exercise a growing text payload"
        )
    assert story_surface.arena_alignment is not None
    arena_write = relocate_stage_text_to_arena(
        story_decoded_result.output,
        table,
        stage_index=story_index,
        function_address=function_address,
        entry_id=story_surface.entry_id,
        replacement=story_decision.translation,
        overrides=overrides,
        alignment=story_surface.arena_alignment,
    )
    encoded_story = (
        reencode_changed_suffix(
            story_stream,
            arena_write.data,
        )
        if story_strategy == "splice"
        else encode(
            arena_write.data,
            strategy=story_strategy,
        )
    )
    story_round_trip = decode(encoded_story)
    if (
        story_round_trip.output != arena_write.data
        or story_round_trip.consumed != len(encoded_story)
    ):
        raise CompleteCanaryError("story encoded chunk fails round-trip")
    rebuilt_stage, rebuilt_stage_offsets, story_padding = (
        rebuild_archive_with_replacement(
            source_stage,
            hb_offsets,
            chunk_index=story_index,
            encoded_replacement=encoded_story,
            minimum_allocation=len(story_stream),
        )
    )
    story_unchanged = _verify_unchanged_chunks(
        source_stage,
        hb_offsets,
        rebuilt_stage,
        rebuilt_stage_offsets,
        replaced_index=story_index,
        context="STAGE",
    )
    hb_offset_plan = build_executable_offset_patch_plan(
        source_hb,
        story_spec,
        rebuilt_stage_offsets,
        source_name=hb_member_path,
    )
    rebuilt_hb = hb_offset_plan.apply(source_hb)
    if read_executable_archive_offsets(
        rebuilt_hb,
        story_spec,
        len(rebuilt_stage),
    ) != rebuilt_stage_offsets:
        raise CompleteCanaryError("rebuilt STAGE offsets fail HB reread")
    reread_story = parse_stage(
        decode(
            rebuilt_stage[
                rebuilt_stage_offsets[story_index]:
                rebuilt_stage_offsets[story_index + 1]
            ]
        ).output,
        augmented_table,
        stage_index=story_index,
        function_address=function_address,
    )
    reread_story_entry = next(
        entry
        for entry in reread_story.entries
        if entry.entry_id == story_surface.entry_id
    )
    if (
        reread_story_entry.text != story_decision.translation
        or reread_story_entry.text_offset != arena_write.arena_offset
    ):
        raise CompleteCanaryError("story output text/pointer reread mismatch")

    outputs = {
        "slps": rebuilt_slps,
        "vt1": menu_vt1,
        "mtv_pros": rebuilt_mtv,
        "stage": rebuilt_stage,
        "hb": rebuilt_hb,
        "preview": preview,
    }
    if enforce_expected_outputs:
        expected_outputs = config.get("expected_outputs")
        if not isinstance(expected_outputs, dict):
            raise CompleteCanaryError("expected output locks are missing")
        _verify_output_locks(outputs, expected_outputs)

    report = {
        "schema_version": 1,
        "status": "static_components_validated_runtime_evidence_separate",
        "content_policy": (
            "Hashes, offsets, counts and build parameters only; no source "
            "or rebuilt game bytes embedded."
        ),
        "production_inputs": selection.to_metadata(),
        "profile_validation": profile_validation,
        "isolated_production_inputs": isolated_profile_inputs,
        "isolated_profile_validations": isolated_profile_validations,
        "subcomponents": {
            "menu_font": {
                "profile_id": menu_report["production_inputs"]["profile_id"],
                "slps_sha256": sha256_bytes(menu_slps),
                "vt1_sha256": sha256_bytes(menu_vt1),
                "preview_sha256": sha256_bytes(preview),
                "static_validation_reused": True,
                "isolated_story_slps_byte_identical": (
                    rebuilt_slps == menu_slps
                ),
            }
        },
        "summary": {
            "surface_id": summary_surface.surface_id,
            "source_member": summary_surface.source_member,
            "chunk_index": summary_index,
            "text_offset": summary_entry.text_offset,
            "allocated_length": summary_entry.allocated_length,
            "replacement_encoded_size": len(
                encode_text(
                    summary_decision.translation,
                    table,
                    overrides=overrides,
                    terminate=True,
                )
            ),
            "encoded_chunk_size": len(encoded_summary),
            "encoded_chunk_sha256": sha256_bytes(encoded_summary),
            "codec_strategy": summary_strategy,
            "archive_padding_size": summary_padding,
            "archive_offset_count": len(rebuilt_summary_offsets),
            "offsets_aligned_16": all(
                offset % 16 == 0 for offset in rebuilt_summary_offsets
            ),
            "slps_offset_reread_exact": True,
            "decoded_round_trip_exact": True,
            "text_reread_exact": True,
            "unchanged_chunk_count": summary_unchanged,
        },
        "story": {
            "surface_id": story_surface.surface_id,
            "source_member": story_surface.source_member,
            "chunk_index": story_index,
            "source_message_size": (
                story_surface.encoded_size_with_terminator
            ),
            "replacement_message_size": replacement_message_size,
            "payload_growth_exercised": True,
            "arena": arena_write.to_metadata(),
            "encoded_chunk_size": len(encoded_story),
            "encoded_chunk_sha256": sha256_bytes(encoded_story),
            "codec_strategy": story_strategy,
            "archive_padding_size": story_padding,
            "archive_offset_count": len(rebuilt_stage_offsets),
            "offsets_aligned_16": all(
                offset % 16 == 0 for offset in rebuilt_stage_offsets
            ),
            "hb_offset_reread_exact": True,
            "decoded_round_trip_exact": True,
            "text_reread_exact": True,
            "unchanged_chunk_count": story_unchanged,
        },
        "outputs": {
            name: _output_lock(data)
            for name, data in outputs.items()
        },
        "fixed_size_diffs": {
            "slps": summarize_diff(
                source_slps,
                rebuilt_slps,
            ).to_mapping(),
            "hb": summarize_diff(
                source_hb,
                rebuilt_hb,
            ).to_mapping(),
        },
        "patch_plans": {
            "summary_offset_table": summary_offset_plan.to_metadata(),
            "story_offset_table": hb_offset_plan.to_metadata(),
        },
        "runtime_acceptance": "not tested by component builder",
        "iso_rebuild": "not performed by component builder",
    }
    return outputs, report


__all__ = [
    "CompleteCanaryError",
    "build_complete_canary",
]
