"""Build and verify the complete MTV_PROS Chinese world-history component."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Mapping

from .chinese_layout import rendered_line_width
from .codec import decode, reencode_changed_suffix
from .corpus import text_sha256
from .iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from .summary import parse_summary
from .text import augment_text_table, encode_text, load_text_table
from .ui_menu import load_ui_font_overrides
from .writeback import rebuild_aligned_archive, sha256_bytes
from .writers import (
    build_executable_offset_patch_plan,
    build_summary_patch_plan,
)


class WorldHistoryError(ValueError):
    """The world-history source, component, or proof contract has drifted."""


_EDITORIAL_STATUS_RANK = {
    "todo": 0,
    "draft": 1,
    "reviewed": 2,
    "final": 3,
}


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorldHistoryError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise WorldHistoryError(f"JSON root must be an object: {path}")
    return value


def _object(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise WorldHistoryError(f"{context} must be an object")
    return value


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise WorldHistoryError("world-history path must be a non-empty string")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise WorldHistoryError(
            f"world-history path escapes project root: {raw}"
        ) from error
    return path


def _verified_file(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    context: str,
) -> Path:
    path = _project_path(project_root, reference.get("path"))
    payload = path.read_bytes()
    expected_size = reference.get("size")
    if expected_size is not None and len(payload) != expected_size:
        raise WorldHistoryError(f"{context} size drift")
    if sha256_bytes(payload) != reference.get("sha256"):
        raise WorldHistoryError(f"{context} SHA-256 drift")
    return path


def _file_lock(path: Path, project_root: Path) -> dict:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(project_root.resolve())),
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _payload_lock(payload: bytes) -> dict:
    return {"size": len(payload), "sha256": sha256_bytes(payload)}


def _offsets_sha256(offsets: tuple[int, ...]) -> str:
    return sha256_bytes(
        b"".join(offset.to_bytes(4, "little") for offset in offsets)
    )


def _load_translations(
    project_root: Path,
    reference: Mapping[str, object],
) -> tuple[dict[str, str], dict]:
    path = _verified_file(
        project_root,
        reference,
        context="world-history translation source",
    )
    document = _json_object(path)
    if (
        document.get("batch_id") != reference.get("batch_id")
        or document.get("language") != reference.get("language")
    ):
        raise WorldHistoryError("world-history translation metadata drift")
    raw_entries = document.get("entries")
    if (
        not isinstance(raw_entries, list)
        or len(raw_entries) != reference.get("expected_entry_count")
    ):
        raise WorldHistoryError("world-history translation count drift")
    minimum = reference.get("minimum_editorial_status")
    if minimum not in _EDITORIAL_STATUS_RANK:
        raise WorldHistoryError("world-history minimum editorial status is invalid")
    translations = {}
    source_hashes = {}
    status_counts = Counter()
    entry_signature = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise WorldHistoryError("world-history translation entry is malformed")
        entry_id = raw.get("id")
        translation = raw.get("translation")
        source_hash = raw.get("source_text_sha256")
        status = raw.get("editorial_status")
        if (
            not isinstance(entry_id, str)
            or not isinstance(translation, str)
            or not translation
            or not isinstance(source_hash, str)
            or status not in _EDITORIAL_STATUS_RANK
        ):
            raise WorldHistoryError("world-history translation entry is malformed")
        if _EDITORIAL_STATUS_RANK[status] < _EDITORIAL_STATUS_RANK[minimum]:
            raise WorldHistoryError(
                f"{entry_id} is below the required editorial status"
            )
        if entry_id in translations:
            raise WorldHistoryError(f"duplicate world-history ID: {entry_id}")
        translations[entry_id] = translation
        source_hashes[entry_id] = source_hash
        status_counts[status] += 1
        entry_signature.append(
            {
                "id": entry_id,
                "source_text_sha256": source_hash,
                "translation_sha256": text_sha256(translation),
                "editorial_status": status,
            }
        )
    return translations, {
        **_file_lock(path, project_root),
        "batch_id": document["batch_id"],
        "language": document["language"],
        "minimum_editorial_status": minimum,
        "status_counts": dict(sorted(status_counts.items())),
        "entry_signature_sha256": sha256_bytes(
            json.dumps(
                entry_signature,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
        "source_hashes": source_hashes,
    }


def _load_layout_manifest(
    project_root: Path,
    reference: Mapping[str, object],
) -> tuple[Path, dict]:
    path = _verified_file(
        project_root,
        reference,
        context="world-history layout manifest",
    )
    manifest = _json_object(path)
    if manifest.get("status") != reference.get("required_status"):
        raise WorldHistoryError("world-history layout manifest status drift")
    if (
        manifest.get("selection", {}).get("entry_count") != 28
        or manifest.get("layout", {}).get("noncanonical_entry_count") != 0
        or manifest.get("layout", {}).get("logical_text_preserved") is not True
        or manifest.get("allocation", {}).get("overflow_count") != 0
    ):
        raise WorldHistoryError("world-history layout manifest is not component-ready")
    return path, manifest


def _load_font_component(
    project_root: Path,
    config: Mapping[str, object],
) -> tuple[bytes, bytes, dict, dict[str, int]]:
    reference = _object(
        config.get("font_candidate"),
        context="world-history font candidate",
    )
    manifest_path = _project_path(project_root, reference.get("manifest"))
    if sha256_bytes(manifest_path.read_bytes()) != reference.get("sha256"):
        raise WorldHistoryError("world-history font manifest SHA-256 drift")
    manifest = _json_object(manifest_path)
    if manifest.get("status") != reference.get("required_status"):
        raise WorldHistoryError("world-history font manifest status drift")
    coverage_key = reference.get(
        "coverage_key",
        "selected_renderer_coverage",
    )
    if (
        not isinstance(coverage_key, str)
        or not coverage_key
        or manifest.get(coverage_key, {}).get(
            "missing_renderer_character_count"
        )
        != 0
    ):
        raise WorldHistoryError("world-history font still has missing characters")
    try:
        overrides, codebook = load_ui_font_overrides(
            project_root,
            config,
            manifest,
        )
    except ValueError as error:
        raise WorldHistoryError(str(error)) from error
    component = _object(
        manifest.get("font_component"),
        context="world-history font component",
    )
    report_path = _project_path(project_root, component.get("report"))
    if sha256_bytes(report_path.read_bytes()) != component.get("report_sha256"):
        raise WorldHistoryError("world-history font report SHA-256 drift")
    component_root = report_path.parent
    slps_path = component_root / "SLPS_258.87"
    vt1_path = component_root / "DATA/VT1.BIN"
    outputs = _object(component.get("outputs"), context="world-history font outputs")
    payloads = {}
    for label, path in (("slps", slps_path), ("vt1", vt1_path)):
        expected = _object(
            outputs.get(label),
            context=f"world-history font {label} output",
        )
        payload = path.read_bytes()
        if _payload_lock(payload) != {
            "size": expected.get("size"),
            "sha256": expected.get("sha256"),
        }:
            raise WorldHistoryError(f"world-history font {label} component drift")
        payloads[label] = payload
    return (
        payloads["slps"],
        payloads["vt1"],
        {
            "manifest": {
                **_file_lock(manifest_path, project_root),
                "status": manifest["status"],
            },
            "report": _file_lock(report_path, project_root),
            "slps": _file_lock(slps_path, project_root),
            "vt1": _file_lock(vt1_path, project_root),
            "selected_renderer_missing_character_count": 0,
            "codebook": codebook,
        },
        overrides,
    )


def _assert_output_locks(
    outputs: Mapping[str, bytes],
    expected: Mapping[str, object],
) -> None:
    for name, payload in outputs.items():
        raw = expected.get(name)
        if not isinstance(raw, dict):
            raise WorldHistoryError(f"expected output lock is missing for {name}")
        if _payload_lock(payload) != {
            "size": raw.get("size"),
            "sha256": raw.get("sha256"),
        }:
            raise WorldHistoryError(f"{name} output lock drift")


def build_world_history_component(
    project_root: Path,
    config_path: Path,
    *,
    enforce_expected_outputs: bool = True,
) -> tuple[dict[str, bytes], dict]:
    """Build P1 SLPS/VT1/MTV_PROS bytes and a bounded validation report."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if (
        config.get("schema_version") != 1
        or not isinstance(config.get("profile_id"), str)
        or not config["profile_id"]
    ):
        raise WorldHistoryError("unsupported world-history component profile")
    codec = _object(config.get("codec"), context="world-history codec")
    if (
        codec.get("mode")
        != "preserve-unchanged-chunks-and-reencode-changed-suffixes"
        or codec.get("strategy") not in {"greedy", "literal"}
        or codec.get("archive_alignment") != 16
    ):
        raise WorldHistoryError("unsupported world-history codec contract")

    source = _object(config.get("source"), context="world-history source")
    source_slps_path = _verified_file(
        root,
        _object(source.get("slps"), context="world-history source SLPS"),
        context="world-history source SLPS",
    )
    source_member_path = _verified_file(
        root,
        _object(source.get("member"), context="world-history source member"),
        context="world-history source member",
    )
    table_path = _verified_file(
        root,
        _object(source.get("text_table"), context="world-history text table"),
        context="world-history text table",
    )
    source_slps = source_slps_path.read_bytes()
    source_member = source_member_path.read_bytes()
    table = load_text_table(table_path)
    translations, translation_report = _load_translations(
        root,
        _object(
            config.get("translation_source"),
            context="world-history translation source",
        ),
    )
    layout_path, layout_manifest = _load_layout_manifest(
        root,
        _object(
            config.get("layout_manifest"),
            context="world-history layout manifest",
        ),
    )
    font_slps, font_vt1, font_report, overrides = _load_font_component(
        root,
        config,
    )
    output_table = augment_text_table(table, overrides)
    archive_spec = CORE_ARCHIVE_SPECS["MTV_PROS.BIN"]
    source_offsets = read_executable_archive_offsets(
        source_slps,
        archive_spec,
        len(source_member),
    )
    font_offsets = read_executable_archive_offsets(
        font_slps,
        archive_spec,
        len(source_member),
    )
    if font_offsets != source_offsets:
        raise WorldHistoryError(
            "P1 font SLPS unexpectedly changed MTV_PROS source offsets"
        )

    source_hashes = translation_report.pop("source_hashes")
    seen_ids = set()
    encoded_chunks = []
    chunk_reports = []
    allocation_entries = []
    write_operation_count = 0
    unknown_output_code_count = 0
    changed_chunk_count = 0
    unchanged_chunk_count = 0
    for chunk_index, (start, end) in enumerate(
        zip(source_offsets, source_offsets[1:])
    ):
        source_stream = source_member[start:end]
        source_decoded = decode(source_stream)
        if any(source_stream[source_decoded.consumed :]):
            raise WorldHistoryError(
                f"source MTV_PROS chunk {chunk_index:02d} has nonzero padding"
            )
        parsed = parse_summary(
            source_decoded.output,
            table,
            chunk_index=chunk_index,
        )
        replacements = {}
        for entry in parsed.entries:
            if entry.entry_id not in translations:
                raise WorldHistoryError(
                    f"missing world-history translation: {entry.entry_id}"
                )
            if source_hashes[entry.entry_id] != text_sha256(entry.text):
                raise WorldHistoryError(
                    f"world-history source hash drift: {entry.entry_id}"
                )
            replacement = translations[entry.entry_id]
            output_size = len(
                encode_text(replacement, table, overrides=overrides)
            ) + (1 if entry.terminator == "nul" else 0)
            margin = entry.allocated_length - output_size
            if margin < 0:
                raise WorldHistoryError(
                    f"world-history allocation overflow: {entry.entry_id}"
                )
            replacements[entry.entry_id] = replacement
            seen_ids.add(entry.entry_id)
            allocation_entries.append(
                {
                    "id": entry.entry_id,
                    "chunk_index": chunk_index,
                    "ordinal": entry.ordinal,
                    "allocated_length": entry.allocated_length,
                    "terminator": entry.terminator,
                    "output_encoded_size": output_size,
                    "margin": margin,
                    "line_count": len(replacement.splitlines()),
                    "maximum_line_width": max(
                        (
                            rendered_line_width(line)
                            for line in replacement.splitlines()
                        ),
                        default=0,
                    ),
                    "translation_sha256": text_sha256(replacement),
                }
            )
        plan = build_summary_patch_plan(
            source_decoded.output,
            table,
            chunk_index=chunk_index,
            replacements=replacements,
            overrides=overrides,
        )
        rebuilt_decoded = plan.apply(source_decoded.output)
        write_operation_count += len(plan.operations)
        if replacements:
            encoded = reencode_changed_suffix(
                source_stream,
                rebuilt_decoded,
                strategy=codec["strategy"],
                min_match_length=int(codec.get("min_match_length", 4)),
                max_match_chain=int(codec.get("max_match_chain", 256)),
                lazy_matching=codec.get("lazy_matching") is True,
            )
            changed_chunk_count += 1
        else:
            encoded = source_stream
            unchanged_chunk_count += 1
        round_trip = decode(encoded)
        if round_trip.output != rebuilt_decoded:
            raise WorldHistoryError(
                f"world-history chunk {chunk_index:02d} codec round trip failed"
            )
        if replacements and round_trip.consumed != len(encoded):
            raise WorldHistoryError(
                f"world-history chunk {chunk_index:02d} retained encoder padding"
            )
        reparsed = parse_summary(
            round_trip.output,
            output_table,
            chunk_index=chunk_index,
        )
        unknown_output_code_count += reparsed.unknown_code_count
        actual = {entry.entry_id: entry.text for entry in reparsed.entries}
        if any(actual.get(entry_id) != text for entry_id, text in replacements.items()):
            raise WorldHistoryError(
                f"world-history chunk {chunk_index:02d} output reparse mismatch"
            )
        encoded_chunks.append(encoded)
        chunk_reports.append(
            {
                "chunk_index": chunk_index,
                "entry_count": len(parsed.entries),
                "changed": bool(replacements),
                "source_allocation_size": len(source_stream),
                "source_consumed_size": source_decoded.consumed,
                "source_decoded_sha256": sha256_bytes(source_decoded.output),
                "output_encoded_size": round_trip.consumed,
                "output_decoded_size": len(round_trip.output),
                "output_decoded_sha256": sha256_bytes(round_trip.output),
                "write_operation_count": len(plan.operations),
            }
        )
    if seen_ids != set(translations):
        raise WorldHistoryError("world-history source/translation ID sets differ")

    allocation_signature = sha256_bytes(
        json.dumps(
            allocation_entries,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if allocation_signature != layout_manifest["allocation"][
        "entry_signature_sha256"
    ]:
        raise WorldHistoryError(
            "world-history allocation signature differs from layout manifest"
        )
    rebuilt_member, rebuilt_offsets = rebuild_aligned_archive(
        encoded_chunks,
        alignment=codec["archive_alignment"],
    )
    offset_plan = build_executable_offset_patch_plan(
        font_slps,
        archive_spec,
        rebuilt_offsets,
    )
    rebuilt_slps = offset_plan.apply(font_slps)
    if read_executable_archive_offsets(
        rebuilt_slps,
        archive_spec,
        len(rebuilt_member),
    ) != rebuilt_offsets:
        raise WorldHistoryError("world-history SLPS offsets fail reread")
    table_start = archive_spec.table_start
    table_end_exclusive = archive_spec.table_end + 1
    if (
        rebuilt_slps[:table_start] != font_slps[:table_start]
        or rebuilt_slps[table_end_exclusive:]
        != font_slps[table_end_exclusive:]
    ):
        raise WorldHistoryError("world-history SLPS changed outside offset table")

    outputs = {
        "slps": rebuilt_slps,
        "vt1": font_vt1,
        "mtv_pros": rebuilt_member,
    }
    if enforce_expected_outputs:
        _assert_output_locks(
            outputs,
            _object(
                config.get("expected_outputs"),
                context="world-history expected outputs",
            ),
        )

    actual_ratchet = {
        "archive_chunk_count": len(chunk_reports),
        "text_chunk_count": changed_chunk_count,
        "translation_entry_count": len(translations),
        "write_operation_count": write_operation_count,
        "unchanged_chunk_count": unchanged_chunk_count,
        "fixed_allocation_overflow_count": 0,
        "unknown_output_code_count": unknown_output_code_count,
        "maximum_line_width": layout_manifest["layout"]["maximum_line_width"],
    }
    expected_ratchet = _object(
        config.get("ratchet"),
        context="world-history ratchet",
    )
    ratchet_checks = {
        key: actual_ratchet.get(key) == expected
        for key, expected in expected_ratchet.items()
    }
    if not all(ratchet_checks.values()):
        raise WorldHistoryError(
            f"world-history component ratchet failed: {ratchet_checks}"
        )

    manifest_contract = config.get("manifest_contract", {})
    if not isinstance(manifest_contract, dict):
        raise WorldHistoryError("world-history manifest contract is invalid")
    font_acceptance_key = manifest_contract.get(
        "font_acceptance_key",
        "p1_font_component_exact",
    )
    runtime_reason = manifest_contract.get(
        "runtime_reason",
        (
            "The isolated P1 world-history ISO is statically validated, "
            "but no fresh PCSX2 evidence exists. The first, middle and "
            "final scroll segments and the new raw trail classes remain "
            "runtime acceptance gates."
        ),
    )
    if (
        not isinstance(font_acceptance_key, str)
        or not font_acceptance_key
        or not isinstance(runtime_reason, str)
        or not runtime_reason
    ):
        raise WorldHistoryError("world-history manifest contract is incomplete")

    report = {
        "schema_version": 1,
        "status": "offline_component_validated_runtime_not_tested",
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "inputs": {
            "config": _file_lock(config_path, root),
            "source_slps": _file_lock(source_slps_path, root),
            "source_member": _file_lock(source_member_path, root),
            "text_table": _file_lock(table_path, root),
            "translation_source": translation_report,
            "layout_manifest": {
                **_file_lock(layout_path, root),
                "status": layout_manifest["status"],
                "allocation_entry_signature_sha256": allocation_signature,
            },
            "font_component": font_report,
        },
        "selection": {
            "translation_entry_count": len(translations),
            "text_chunk_count": changed_chunk_count,
            "editorial_status_counts": translation_report["status_counts"],
            "translation_entry_signature_sha256": translation_report[
                "entry_signature_sha256"
            ],
        },
        "fixed_allocations": {
            "write_operation_count": write_operation_count,
            "overflow_count": 0,
            "minimum_margin": min(item["margin"] for item in allocation_entries),
            "maximum_margin": max(item["margin"] for item in allocation_entries),
            "entry_signature_sha256": allocation_signature,
        },
        "archive": {
            "source": _payload_lock(source_member),
            "output": _payload_lock(rebuilt_member),
            "chunk_count": len(chunk_reports),
            "changed_chunk_count": changed_chunk_count,
            "unchanged_chunk_count": unchanged_chunk_count,
            "source_offsets_sha256": _offsets_sha256(source_offsets),
            "output_offsets_sha256": _offsets_sha256(rebuilt_offsets),
            "offsets": list(rebuilt_offsets),
            "alignment": codec["archive_alignment"],
            "decoded_round_trip_exact_count": len(chunk_reports),
            "unknown_output_code_count": unknown_output_code_count,
            "chunks": chunk_reports,
        },
        "slps_component": {
            "font_base": _payload_lock(font_slps),
            "output": _payload_lock(rebuilt_slps),
            "offset_table_start": archive_spec.table_start,
            "offset_table_end_inclusive": archive_spec.table_end,
            "offset_table_end_exclusive": table_end_exclusive,
            "offset_table_reread_exact": True,
            "outside_offset_table_unchanged": True,
            "patch_plan": offset_plan.to_metadata(),
        },
        "vt1_component": {
            "output": _payload_lock(font_vt1),
            font_acceptance_key: True,
        },
        "outputs": {
            name: _payload_lock(payload) for name, payload in outputs.items()
        },
        "ratchet": {
            "expected": dict(expected_ratchet),
            "actual": actual_ratchet,
            "checks": ratchet_checks,
            "passed": True,
        },
        "acceptance": {
            "translation_source_hash_locked": True,
            "layout_manifest_exact": True,
            font_acceptance_key: True,
            "all_28_records_written_and_reparsed": True,
            "fixed_allocations_within_bounds": True,
            "all_14_chunks_codec_round_trip_exact": True,
            "two_non_text_chunks_byte_exact": unchanged_chunk_count == 2,
            "slps_changes_limited_to_mtv_pros_offset_table": True,
            "slps_offset_reread_exact": True,
            "unknown_output_code_count_zero": unknown_output_code_count == 0,
        },
        "runtime": {
            "status": "not_tested",
            "reason": runtime_reason,
        },
    }
    return outputs, report


def audit_world_history_outputs(
    project_root: Path,
    config_path: Path,
    outputs: Mapping[str, bytes],
) -> dict:
    """Independently reparse built members and compare them to the corpus."""

    root = project_root.resolve()
    config = _json_object(config_path.resolve())
    source = _object(config.get("source"), context="world-history source")
    table_path = _verified_file(
        root,
        _object(source.get("text_table"), context="world-history text table"),
        context="world-history text table",
    )
    table = load_text_table(table_path)
    translations, _ = _load_translations(
        root,
        _object(
            config.get("translation_source"),
            context="world-history translation source",
        ),
    )
    _, expected_vt1, font_report, overrides = _load_font_component(root, config)
    if outputs.get("vt1") != expected_vt1:
        raise WorldHistoryError("world-history VT1 is not the exact P1 component")
    slps = outputs.get("slps")
    member = outputs.get("mtv_pros")
    if not isinstance(slps, bytes) or not isinstance(member, bytes):
        raise WorldHistoryError("world-history output set is incomplete")
    offsets = read_executable_archive_offsets(
        slps,
        CORE_ARCHIVE_SPECS["MTV_PROS.BIN"],
        len(member),
    )
    augmented = augment_text_table(table, overrides)
    actual = {}
    chunk_reports = []
    for chunk_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        stream = member[start:end]
        result = decode(stream)
        if any(stream[result.consumed :]):
            raise WorldHistoryError(
                f"output MTV_PROS chunk {chunk_index:02d} has nonzero padding"
            )
        parsed = parse_summary(
            result.output,
            augmented,
            chunk_index=chunk_index,
        )
        if parsed.unknown_code_count:
            raise WorldHistoryError(
                f"output MTV_PROS chunk {chunk_index:02d} has unknown codes"
            )
        actual.update({entry.entry_id: entry.text for entry in parsed.entries})
        chunk_reports.append(
            {
                "chunk_index": chunk_index,
                "stored_size": len(stream),
                "consumed_size": result.consumed,
                "padding_size": len(stream) - result.consumed,
                "decoded_sha256": sha256_bytes(result.output),
                "entry_count": len(parsed.entries),
            }
        )
    if actual != translations:
        raise WorldHistoryError("world-history output texts differ from corpus")
    return {
        "entry_count": len(actual),
        "chunk_count": len(chunk_reports),
        "all_texts_exact": True,
        "unknown_code_count": 0,
        "p1_vt1_exact": True,
        "font_manifest_sha256": font_report["manifest"]["sha256"],
        "chunks": chunk_reports,
    }


__all__ = [
    "WorldHistoryError",
    "audit_world_history_outputs",
    "build_world_history_component",
]
