"""Compose independently validated localized UI atlas components."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from .iso9660 import (
    SECTOR_SIZE,
    member_map,
    scan_iso9660,
    sha256_member,
)
from .patch_audit import changed_offsets, sha256_bytes, summarize_diff


class UiAtlasSuiteError(ValueError):
    """Localized atlas components cannot be composed without a conflict."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiAtlasSuiteError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiAtlasSuiteError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiAtlasSuiteError("project path must be a non-empty string")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiAtlasSuiteError(f"path escapes project root: {raw}") from error
    return path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_lock(project_root: Path, path: Path) -> dict:
    return {
        "path": str(path.relative_to(project_root.resolve())),
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }


def _payload_lock(payload: bytes) -> dict:
    return {
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _verify_path_reference(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> Path:
    path = _project_path(project_root, reference.get("path"))
    if not path.is_file():
        raise UiAtlasSuiteError(f"{label} is missing: {path}")
    actual = _file_lock(project_root, path)
    expected_sha256 = reference.get("sha256")
    expected_size = reference.get("size")
    if actual["sha256"] != expected_sha256 or (
        expected_size is not None and actual["size"] != expected_size
    ):
        raise UiAtlasSuiteError(f"{label} size or SHA-256 drift")
    return path


def _read_iso_member(
    project_root: Path,
    source_reference: Mapping[str, object],
    member_reference: Mapping[str, object],
) -> tuple[Path, bytes, dict]:
    iso_path = _verify_path_reference(
        project_root,
        source_reference,
        label="source ISO",
    )
    image = scan_iso9660(iso_path)
    raw_member = member_reference.get("member")
    if not isinstance(raw_member, str) or not raw_member:
        raise UiAtlasSuiteError("source archive member is invalid")
    member = member_map(image).get(raw_member)
    if member is None:
        raise UiAtlasSuiteError(f"source archive member is missing: {raw_member}")
    expected = {
        "size": member_reference.get("size"),
        "sha256": member_reference.get("sha256"),
    }
    actual = {
        "size": member.size,
        "sha256": sha256_member(iso_path, member),
    }
    if actual != expected:
        raise UiAtlasSuiteError("source archive member size or SHA-256 drift")
    with iso_path.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        payload = source.read(member.size)
    if _payload_lock(payload) != expected:
        raise UiAtlasSuiteError("source archive member readback drift")
    return iso_path, payload, {
        "member": raw_member,
        **actual,
        "independent_iso9660_read_exact": True,
    }


def _verified_component(
    project_root: Path,
    base_archive: bytes,
    raw: Mapping[str, object],
) -> tuple[bytes, tuple[int, ...], dict]:
    profile_id = raw.get("profile_id")
    chunk_index = raw.get("chunk_index")
    if (
        not isinstance(profile_id, str)
        or not profile_id
        or not isinstance(chunk_index, int)
        or isinstance(chunk_index, bool)
        or chunk_index < 0
    ):
        raise UiAtlasSuiteError("atlas component identity is invalid")

    config_reference = raw.get("config")
    manifest_reference = raw.get("manifest")
    archive_reference = raw.get("archive")
    if not all(
        isinstance(reference, dict)
        for reference in (config_reference, manifest_reference, archive_reference)
    ):
        raise UiAtlasSuiteError(f"{profile_id} references are incomplete")
    config_path = _verify_path_reference(
        project_root,
        config_reference,
        label=f"{profile_id} config",
    )
    manifest_path = _verify_path_reference(
        project_root,
        manifest_reference,
        label=f"{profile_id} manifest",
    )
    archive_path = _verify_path_reference(
        project_root,
        archive_reference,
        label=f"{profile_id} archive",
    )
    component_config = _json_object(config_path)
    manifest = _json_object(manifest_path)
    archive = archive_path.read_bytes()

    required_status = manifest_reference.get("required_status")
    required_runtime_status = manifest_reference.get("required_runtime_status")
    if (
        component_config.get("profile_id") != profile_id
        or manifest.get("profile_id") != profile_id
        or manifest.get("status") != required_status
        or manifest.get("runtime", {}).get("status") != required_runtime_status
    ):
        raise UiAtlasSuiteError(f"{profile_id} component status or identity drift")
    target = manifest.get("target")
    outputs = manifest.get("outputs")
    if not isinstance(target, dict) or not isinstance(outputs, dict):
        raise UiAtlasSuiteError(f"{profile_id} manifest shape drift")
    if (
        target.get("member") != raw.get("member")
        or target.get("chunk_index") != chunk_index
        or outputs.get("archive") != _payload_lock(archive)
        or len(archive) != len(base_archive)
    ):
        raise UiAtlasSuiteError(f"{profile_id} target or archive drift")

    chunk_start = target.get("chunk_start")
    chunk_end = target.get("chunk_end")
    if (
        not isinstance(chunk_start, int)
        or isinstance(chunk_start, bool)
        or not isinstance(chunk_end, int)
        or isinstance(chunk_end, bool)
        or not 0 <= chunk_start < chunk_end <= len(base_archive)
    ):
        raise UiAtlasSuiteError(f"{profile_id} chunk geometry is invalid")
    offsets = changed_offsets(base_archive, archive)
    if not offsets or offsets[0] < chunk_start or offsets[-1] >= chunk_end:
        raise UiAtlasSuiteError(f"{profile_id} changed bytes escape target chunk")
    diff = summarize_diff(base_archive, archive)
    expected_diff = {
        "diff_count": raw.get("expected_changed_byte_count"),
        "range_count": raw.get("expected_changed_range_count"),
    }
    actual_diff = {
        "diff_count": diff.diff_count,
        "range_count": diff.range_count,
    }
    if actual_diff != expected_diff:
        raise UiAtlasSuiteError(f"{profile_id} byte-diff ratchet drift")

    return archive, offsets, {
        "profile_id": profile_id,
        "chunk_index": chunk_index,
        "config": _file_lock(project_root, config_path),
        "manifest": _file_lock(project_root, manifest_path),
        "archive": _file_lock(project_root, archive_path),
        "target": {
            "member": target["member"],
            "chunk_start": chunk_start,
            "chunk_end": chunk_end,
        },
        "diff": diff.to_mapping(),
        "runtime_status": manifest["runtime"]["status"],
        "exact": True,
    }


def build_ui_atlas_suite(
    project_root: Path,
    config_path: Path,
    *,
    enforce_expected_output: bool = True,
) -> tuple[bytes, dict]:
    """Return one archive containing all disjoint localized atlas changes."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiAtlasSuiteError("unsupported UI atlas suite schema")
    profile_id = config.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise UiAtlasSuiteError("UI atlas suite needs a profile_id")

    source = config.get("source")
    if not isinstance(source, dict):
        raise UiAtlasSuiteError("UI atlas suite source is missing")
    source_iso = source.get("iso")
    source_member = source.get("member")
    if not isinstance(source_iso, dict) or not isinstance(source_member, dict):
        raise UiAtlasSuiteError("UI atlas suite source references are incomplete")
    iso_path, base_archive, source_member_report = _read_iso_member(
        root,
        source_iso,
        source_member,
    )

    raw_components = config.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise UiAtlasSuiteError("UI atlas suite needs components")
    components = []
    component_payloads = {}
    ownership: dict[int, str] = {}
    output = bytearray(base_archive)
    seen_profiles = set()
    seen_chunks = set()
    for raw in raw_components:
        if not isinstance(raw, dict):
            raise UiAtlasSuiteError("UI atlas suite component is not an object")
        component, offsets, report = _verified_component(root, base_archive, raw)
        profile = report["profile_id"]
        chunk_index = report["chunk_index"]
        if profile in seen_profiles or chunk_index in seen_chunks:
            raise UiAtlasSuiteError("UI atlas suite profile or chunk is duplicated")
        seen_profiles.add(profile)
        seen_chunks.add(chunk_index)
        component_payloads[profile] = component
        for offset in offsets:
            previous = ownership.get(offset)
            if previous is not None:
                raise UiAtlasSuiteError(
                    f"atlas byte ownership overlaps: {previous} and {profile}"
                )
            ownership[offset] = profile
            output[offset] = component[offset]
        components.append(report)

    combined = bytes(output)
    combined_diff = summarize_diff(base_archive, combined)
    composition = config.get("composition")
    if not isinstance(composition, dict):
        raise UiAtlasSuiteError("UI atlas suite composition is missing")
    actual_composition = {
        "mode": "disjoint-byte-patch",
        "component_count": len(components),
        "chunk_indices": sorted(seen_chunks),
        "ownership_overlap_count": 0,
        "changed_byte_count": combined_diff.diff_count,
        "changed_range_count": combined_diff.range_count,
    }
    if actual_composition != composition:
        raise UiAtlasSuiteError(
            f"UI atlas suite composition ratchet drift: {actual_composition}"
        )

    expected_output = config.get("expected_output")
    if not isinstance(expected_output, dict):
        raise UiAtlasSuiteError("UI atlas suite expected output is missing")
    output_lock = _payload_lock(combined)
    if enforce_expected_output and output_lock != expected_output:
        raise UiAtlasSuiteError("UI atlas suite output lock drift")

    acceptance = {
        "source_iso_and_member_locked": True,
        "component_configs_and_manifests_locked": True,
        "component_archives_match_manifests": True,
        "component_diffs_within_owned_chunks": True,
        "component_byte_ownership_disjoint": True,
        "combined_bytes_match_component_owners": all(
            combined[offset] == component_payloads[owner][offset]
            for offset, owner in ownership.items()
        ),
        "bytes_outside_component_ownership_exact": all(
            combined[offset] == base_archive[offset]
            for offset in range(len(combined))
            if offset not in ownership
        ),
        "archive_size_preserved": len(combined) == len(base_archive),
        "output_lock_exact": (
            not enforce_expected_output or output_lock == expected_output
        ),
    }
    if not all(acceptance.values()):
        raise UiAtlasSuiteError(f"UI atlas suite acceptance failed: {acceptance}")

    report = {
        "schema_version": 1,
        "status": "static_combined_atlas_component_validated_runtime_mapping_pending",
        "content_policy": (
            "Hashes, counts, paths and runtime gates only; no game bytes or "
            "localized text are embedded."
        ),
        "profile_id": profile_id,
        "scope": config.get("scope"),
        "inputs": {
            "config": _file_lock(root, config_path),
            "source_iso": _file_lock(root, iso_path),
            "source_member": source_member_report,
            "components": components,
        },
        "composition": {
            **actual_composition,
            "combined_diff": combined_diff.to_mapping(),
        },
        "outputs": {
            "archive": output_lock,
        },
        "acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "purpose": (
                "Exercise all five localized atlas candidates in one test image "
                "after isolated mapping evidence remains available."
            ),
            "isolated_mapping_profiles_remain_required": True,
            "required_chunk_indices": sorted(seen_chunks),
            "promotion_rule": (
                "The suite may be integrated into the P2 UI candidate only as "
                "a test layer; each atlas still needs its own screenshot and "
                "exact texture-delta receipt before runtime promotion."
            ),
        },
    }
    return combined, report


__all__ = [
    "UiAtlasSuiteError",
    "build_ui_atlas_suite",
]
