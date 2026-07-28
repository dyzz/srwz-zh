"""Build a reversible UI-atlas mapping canary from locked game inputs."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .assets import AssetInventoryConfig
from .imagemagick import (
    imagemagick_version,
    read_rgba8,
    render_tim2_png8,
    require_imagemagick,
    write_deterministic_rgba8_png,
)
from .iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from .iso_layout import (
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from .patch_audit import sha256_bytes, summarize_diff
from .tim2 import scan_tim2
from .tim2_writeback import (
    CANARY_HEIGHT,
    CANARY_WIDTH,
    inject_indexed4_rgba,
)


class UiAtlasCanaryError(ValueError):
    """The requested atlas canary does not match its locked source."""


@dataclass(frozen=True)
class AtlasMask:
    x: int
    y: int
    width: int
    height: int
    replacement_rgba: bytes
    preserve_rgba: tuple[bytes, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "AtlasMask":
        values = tuple(raw.get(key) for key in ("x", "y", "width", "height"))
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in values
        ):
            raise UiAtlasCanaryError("atlas mask geometry must use integers")
        x, y, width, height = values
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise UiAtlasCanaryError("atlas mask geometry is invalid")
        if x + width > CANARY_WIDTH or y + height > CANARY_HEIGHT:
            raise UiAtlasCanaryError("atlas mask exceeds the picture")
        replacement = raw.get("replacement_rgba")
        if (
            not isinstance(replacement, str)
            or len(replacement) != 8
        ):
            raise UiAtlasCanaryError(
                "atlas replacement_rgba must contain eight hex digits"
            )
        try:
            replacement_rgba = bytes.fromhex(replacement)
        except ValueError as error:
            raise UiAtlasCanaryError(
                "atlas replacement_rgba is not hexadecimal"
            ) from error
        raw_preserve = raw.get("preserve_rgba")
        if (
            not isinstance(raw_preserve, list)
            or not raw_preserve
            or any(
                not isinstance(value, str) or len(value) != 8
                for value in raw_preserve
            )
        ):
            raise UiAtlasCanaryError(
                "atlas preserve_rgba must be a non-empty hex array"
            )
        try:
            preserve_rgba = tuple(
                bytes.fromhex(value) for value in raw_preserve
            )
        except ValueError as error:
            raise UiAtlasCanaryError(
                "atlas preserve_rgba contains non-hexadecimal data"
            ) from error
        if len(set(preserve_rgba)) != len(preserve_rgba):
            raise UiAtlasCanaryError(
                "atlas preserve_rgba contains duplicates"
            )
        if replacement_rgba not in preserve_rgba:
            raise UiAtlasCanaryError(
                "atlas replacement_rgba must also be preserved"
            )
        return cls(
            x=x,
            y=y,
            width=width,
            height=height,
            replacement_rgba=replacement_rgba,
            preserve_rgba=preserve_rgba,
        )

    def to_mapping(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "replacement_rgba": self.replacement_rgba.hex(),
            "preserve_rgba": [
                value.hex() for value in self.preserve_rgba
            ],
        }


def apply_masked_rgba(original: bytes, mask: AtlasMask) -> bytes:
    """Erase non-background pixels inside a bounded logical rectangle."""

    expected_size = CANARY_WIDTH * CANARY_HEIGHT * 4
    if len(original) != expected_size:
        raise UiAtlasCanaryError("atlas RGBA size is invalid")
    edited = bytearray(original)
    for y in range(mask.y, mask.y + mask.height):
        for x in range(mask.x, mask.x + mask.width):
            start = (y * CANARY_WIDTH + x) * 4
            before = original[start : start + 4]
            if before in mask.preserve_rgba:
                continue
            edited[start : start + 4] = mask.replacement_rgba
    return bytes(edited)


def verify_masked_rgba(
    original: bytes,
    edited: bytes,
    mask: AtlasMask,
) -> dict:
    """Require every visual delta to stay inside one exact rectangle."""

    expected_size = CANARY_WIDTH * CANARY_HEIGHT * 4
    if len(original) != expected_size or len(edited) != expected_size:
        raise UiAtlasCanaryError("atlas RGBA size is invalid")
    changed = []
    preserved_counts = {
        rgba: 0 for rgba in mask.preserve_rgba
    }
    for pixel_index in range(CANARY_WIDTH * CANARY_HEIGHT):
        start = pixel_index * 4
        before = original[start : start + 4]
        after = edited[start : start + 4]
        x = pixel_index % CANARY_WIDTH
        y = pixel_index // CANARY_WIDTH
        inside = (
            mask.x <= x < mask.x + mask.width
            and mask.y <= y < mask.y + mask.height
        )
        if not inside:
            if before == after:
                continue
            raise UiAtlasCanaryError(
                f"atlas edit escaped its mask at ({x},{y})"
            )
        if before in mask.preserve_rgba:
            if after != before:
                raise UiAtlasCanaryError(
                    f"atlas edit changed preserved RGBA at ({x},{y})"
                )
            preserved_counts[before] += 1
            continue
        if after != mask.replacement_rgba:
            raise UiAtlasCanaryError(
                f"atlas edit used an unexpected color at ({x},{y})"
            )
        if before != after:
            changed.append(pixel_index)
    if not changed:
        raise UiAtlasCanaryError("atlas mask did not change a visible pixel")
    missing_preserved = [
        rgba.hex()
        for rgba, count in preserved_counts.items()
        if count == 0
    ]
    if missing_preserved:
        raise UiAtlasCanaryError(
            "atlas mask does not contain preserved RGBA: "
            + ", ".join(missing_preserved)
        )
    return {
        "changed_pixel_count": len(changed),
        "preserved_pixel_count": sum(preserved_counts.values()),
        "preserved_rgba_counts": {
            rgba.hex(): count
            for rgba, count in preserved_counts.items()
        },
        "changed_pixel_indexes_sha256": sha256_bytes(
            b"".join(index.to_bytes(4, "little") for index in changed)
        ),
        "outside_mask_rgba_exact": True,
        "replacement_rgba_exact": True,
        "preserved_rgba_exact": True,
    }


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiAtlasCanaryError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiAtlasCanaryError(f"JSON root must be an object: {path}")
    return value


def _project_path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiAtlasCanaryError("project path must be a non-empty string")
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiAtlasCanaryError(
            f"path escapes the project root: {raw}"
        ) from error
    return path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_lock(root: Path, path: Path) -> dict:
    return {
        "path": str(path.relative_to(root)),
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }


def _verify_file_lock(
    root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> Path:
    path = _project_path(root, reference.get("path"))
    if not path.is_file():
        raise UiAtlasCanaryError(f"{label} is missing: {path}")
    actual = {
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }
    expected = {
        "size": reference.get("size"),
        "sha256": reference.get("sha256"),
    }
    if actual != expected:
        raise UiAtlasCanaryError(f"{label} size or SHA-256 drift")
    return path


def _read_iso_member(source, member) -> bytes:
    source.seek(member.extent_lba * SECTOR_SIZE)
    payload = source.read(member.size)
    if len(payload) != member.size:
        raise UiAtlasCanaryError(f"short ISO read for {member.path}")
    return payload


def _matching_candidate(
    registry: Mapping[str, object],
    target: Mapping[str, object],
) -> Mapping[str, object]:
    chunk_index = target.get("chunk_index")
    candidates = registry.get("candidates")
    if not isinstance(candidates, list):
        raise UiAtlasCanaryError("atlas candidate registry is incomplete")
    matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and candidate.get("chunk_index") == chunk_index
    ]
    if len(matches) != 1:
        raise UiAtlasCanaryError("atlas candidate is not unique")
    candidate = matches[0]
    picture = candidate.get("picture")
    if not isinstance(picture, Mapping):
        raise UiAtlasCanaryError("atlas candidate picture is invalid")
    semantic_locator = target.get("semantic_locator")
    observed_tokens = candidate.get("observed_tokens")
    candidate_scene_ids = candidate.get("candidate_scene_ids")
    if (
        not isinstance(semantic_locator, str)
        or not isinstance(observed_tokens, list)
        or semantic_locator not in observed_tokens
    ):
        raise UiAtlasCanaryError(
            "atlas semantic locator is not in the candidate evidence"
        )
    if (
        not isinstance(candidate_scene_ids, list)
        or not candidate_scene_ids
        or any(
            not isinstance(scene_id, str) or not scene_id
            for scene_id in candidate_scene_ids
        )
    ):
        raise UiAtlasCanaryError(
            "atlas candidate scene identifiers are invalid"
        )
    if target.get("operation") != "erase_non_background_pixels":
        raise UiAtlasCanaryError("unsupported atlas-canary operation")
    expected = {
        "payload_size": target.get("source_chunk_size"),
        "payload_sha256": target.get("source_chunk_sha256"),
        "record_index": target.get("record_index"),
        "picture_index": target.get("picture_index"),
    }
    actual = {
        "payload_size": candidate.get("payload_size"),
        "payload_sha256": candidate.get("payload_sha256"),
        "record_index": picture.get("record_index"),
        "picture_index": picture.get("picture_index"),
    }
    if actual != expected:
        raise UiAtlasCanaryError("atlas candidate coordinates drift")
    evidence_status = candidate.get("evidence_status")
    if evidence_status not in {
        "offline_visual_candidate_not_runtime_mapped",
        (
            "upstream_changed_offline_visual_candidate_"
            "not_runtime_mapped"
        ),
    }:
        raise UiAtlasCanaryError("atlas candidate evidence status drift")
    return candidate


def build_ui_atlas_map_canary(
    project_root: Path,
    config_path: Path,
) -> tuple[dict[str, bytes], dict]:
    """Return the deterministic component and byte-free validation report."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiAtlasCanaryError("unsupported atlas-canary schema")

    source_config = config.get("source")
    target = config.get("target")
    expected = config.get("expected")
    runtime_config = config.get("runtime")
    if not all(
        isinstance(item, Mapping)
        for item in (source_config, target, expected, runtime_config)
    ):
        raise UiAtlasCanaryError("atlas-canary config is incomplete")
    required_routes = runtime_config.get("required_routes")
    if (
        not isinstance(required_routes, list)
        or not required_routes
        or any(
            not isinstance(route, str) or not route
            for route in required_routes
        )
    ):
        raise UiAtlasCanaryError(
            "atlas-canary runtime routes are invalid"
        )
    runtime_statements = (
        runtime_config.get("purpose"),
        runtime_config.get("expected_visual_effect"),
        runtime_config.get("promotion_rule"),
    )
    if any(
        not isinstance(statement, str) or not statement.strip()
        for statement in runtime_statements
    ):
        raise UiAtlasCanaryError(
            "atlas-canary runtime evidence contract is invalid"
        )

    iso_path = _verify_file_lock(
        root,
        source_config["iso"],
        label="source ISO",
    )
    asset_config_path = _project_path(
        root,
        source_config["asset_config"]["path"],
    )
    candidate_path = _project_path(
        root,
        source_config["candidate_registry"]["path"],
    )
    for path, reference, label in (
        (
            asset_config_path,
            source_config["asset_config"],
            "asset config",
        ),
        (
            candidate_path,
            source_config["candidate_registry"],
            "candidate registry",
        ),
    ):
        if _sha256_path(path) != reference.get("sha256"):
            raise UiAtlasCanaryError(f"{label} SHA-256 drift")

    asset_config = AssetInventoryConfig.from_mapping(
        _json_object(asset_config_path)
    )
    candidate_registry = _json_object(candidate_path)
    candidate = _matching_candidate(candidate_registry, target)
    member_path = target.get("member")
    if not isinstance(member_path, str):
        raise UiAtlasCanaryError("atlas target member is invalid")
    archive_spec = asset_config.archive_for_member(member_path)
    if archive_spec is None or archive_spec.storage != "raw":
        raise UiAtlasCanaryError("atlas target is not a raw archive")

    image = scan_iso9660(iso_path)
    members = member_map(image)
    required = {asset_config.executable_member, member_path}
    if not required <= set(members):
        raise UiAtlasCanaryError("source ISO is missing atlas members")
    with iso_path.open("rb") as source:
        executable = _read_iso_member(
            source,
            members[asset_config.executable_member],
        )
        archive = _read_iso_member(source, members[member_path])
    source_members = source_config.get("members")
    if not isinstance(source_members, Mapping):
        raise UiAtlasCanaryError("source member locks are missing")
    for name, payload in (
        ("executable", executable),
        ("archive", archive),
    ):
        lock = {
            "size": len(payload),
            "sha256": sha256_bytes(payload),
        }
        reference = source_members.get(name)
        if not isinstance(reference, Mapping) or lock != {
            "size": reference.get("size"),
            "sha256": reference.get("sha256"),
        }:
            raise UiAtlasCanaryError(f"source {name} lock drift")

    layout_spec = ExecutableOffsetSpec(
        name=archive_spec.name,
        member=archive_spec.member,
        table_start=archive_spec.table_start,
        table_end=archive_spec.table_end,
    )
    offsets = read_executable_archive_offsets(
        executable,
        layout_spec,
        len(archive),
    )
    chunk_index = target.get("chunk_index")
    if (
        not isinstance(chunk_index, int)
        or isinstance(chunk_index, bool)
        or not 0 <= chunk_index < len(offsets) - 1
    ):
        raise UiAtlasCanaryError("atlas chunk index is invalid")
    chunk_start = offsets[chunk_index]
    chunk_end = offsets[chunk_index + 1]
    chunk = archive[chunk_start:chunk_end]
    if {
        "size": len(chunk),
        "sha256": sha256_bytes(chunk),
    } != {
        "size": target.get("source_chunk_size"),
        "sha256": target.get("source_chunk_sha256"),
    }:
        raise UiAtlasCanaryError("atlas source chunk drift")
    records = scan_tim2(chunk)
    record_index = target.get("record_index")
    picture_index = target.get("picture_index")
    if (
        record_index != 0
        or picture_index != 0
        or len(records) != 1
        or records[0].offset != 0
        or records[0].end != len(chunk)
        or len(records[0].pictures) != 1
    ):
        raise UiAtlasCanaryError("atlas TIM2 record geometry drift")

    mask = AtlasMask.from_mapping(target["mask"])
    magick = require_imagemagick()
    version = imagemagick_version(magick)
    if version != config.get("toolchain", {}).get("imagemagick"):
        raise UiAtlasCanaryError("ImageMagick version drift")
    with tempfile.TemporaryDirectory(prefix="srwz-ui-atlas-") as directory:
        temporary = Path(directory)
        source_tm2 = temporary / "source.tm2"
        source_png = temporary / "reference.png"
        reference_preview = temporary / "reference-preview.png"
        edited_preview = temporary / "edited-preview.png"
        output_tm2 = temporary / "output.tm2"
        output_png = temporary / "output.png"
        source_tm2.write_bytes(chunk)
        render_tim2_png8(magick, source_tm2, source_png)
        original_rgba = read_rgba8(
            magick,
            source_png,
            expected_width=CANARY_WIDTH,
            expected_height=CANARY_HEIGHT,
        )
        edited_rgba = apply_masked_rgba(original_rgba, mask)
        mask_report = verify_masked_rgba(
            original_rgba,
            edited_rgba,
            mask,
        )
        injection = inject_indexed4_rgba(
            chunk,
            original_rgba,
            edited_rgba,
        )
        output_tm2.write_bytes(injection.data)
        render_tim2_png8(magick, output_tm2, output_png)
        if read_rgba8(
            magick,
            output_png,
            expected_width=CANARY_WIDTH,
            expected_height=CANARY_HEIGHT,
        ) != edited_rgba:
            raise UiAtlasCanaryError("atlas output RGBA reread mismatch")
        write_deterministic_rgba8_png(
            magick,
            original_rgba,
            reference_preview,
            width=CANARY_WIDTH,
            height=CANARY_HEIGHT,
        )
        write_deterministic_rgba8_png(
            magick,
            edited_rgba,
            edited_preview,
            width=CANARY_WIDTH,
            height=CANARY_HEIGHT,
        )
        reference_png = reference_preview.read_bytes()
        edited_png_bytes = edited_preview.read_bytes()

    rebuilt = (
        archive[:chunk_start]
        + injection.data
        + archive[chunk_end:]
    )
    if len(rebuilt) != len(archive):
        raise UiAtlasCanaryError("atlas component changed archive size")
    if (
        rebuilt[:chunk_start] != archive[:chunk_start]
        or rebuilt[chunk_end:] != archive[chunk_end:]
    ):
        raise UiAtlasCanaryError("atlas component changed another chunk")
    archive_diff = summarize_diff(archive, rebuilt).to_mapping()
    actual_expected = {
        "reference_png": {
            "size": len(reference_png),
            "sha256": sha256_bytes(reference_png),
        },
        "edited_png": {
            "size": len(edited_png_bytes),
            "sha256": sha256_bytes(edited_png_bytes),
        },
        "archive": {
            "size": len(rebuilt),
            "sha256": sha256_bytes(rebuilt),
        },
        "chunk": {
            "size": len(injection.data),
            "sha256": sha256_bytes(injection.data),
        },
        "changed_pixel_count": injection.changed_pixel_count,
        "changed_archive_byte_count": archive_diff["diff_count"],
        "changed_archive_range_count": archive_diff["range_count"],
    }
    if actual_expected != expected:
        raise UiAtlasCanaryError(
            f"atlas-canary output ratchet drift: {actual_expected}"
        )

    outputs = {
        "archive": rebuilt,
        "reference_png": reference_png,
        "edited_png": edited_png_bytes,
    }
    report = {
        "schema_version": 1,
        "status": "static_component_validated_runtime_mapping_pending",
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "content_policy": (
            "Hashes, coordinates, counts and diff summaries only; game "
            "bytes and preview PNGs remain under ignored work/."
        ),
        "inputs": {
            "config": _file_lock(root, config_path),
            "iso": _file_lock(root, iso_path),
            "asset_config": _file_lock(root, asset_config_path),
            "candidate_registry": _file_lock(root, candidate_path),
            "members": {
                "executable": {
                    "member": asset_config.executable_member,
                    "size": len(executable),
                    "sha256": sha256_bytes(executable),
                },
                "archive": {
                    "member": member_path,
                    "size": len(archive),
                    "sha256": sha256_bytes(archive),
                },
            },
        },
        "target": {
            "member": member_path,
            "chunk_index": chunk_index,
            "chunk_start": chunk_start,
            "chunk_end": chunk_end,
            "record_index": record_index,
            "picture_index": picture_index,
            "source_chunk": {
                "size": len(chunk),
                "sha256": sha256_bytes(chunk),
            },
            "semantic_locator": target["semantic_locator"],
            "operation": target["operation"],
            "candidate_evidence_status": candidate["evidence_status"],
            "candidate_scene_ids": candidate["candidate_scene_ids"],
            "mask": mask.to_mapping(),
            "mask_audit": mask_report,
        },
        "toolchain": {
            "imagemagick": version,
        },
        "injection": {
            **injection.to_metadata(),
            "archive_diff": archive_diff,
            "chunk_size_unchanged": len(injection.data) == len(chunk),
            "archive_size_unchanged": len(rebuilt) == len(archive),
            "non_target_chunks_exact": True,
            "output_rgba_exact": True,
        },
        "outputs": {
            "archive": actual_expected["archive"],
            "chunk": actual_expected["chunk"],
            "reference_png": actual_expected["reference_png"],
            "edited_png": actual_expected["edited_png"],
        },
        "acceptance": {
            "candidate_registry_exact": True,
            "single_picture_4bpp_geometry_exact": True,
            "mask_contains_every_rgba_change": True,
            "replacement_uses_existing_source_color": True,
            "preserved_background_rgba_exact": True,
            "tim2_header_clut_and_padding_exact": True,
            "archive_geometry_and_other_chunks_exact": True,
            "imagemagick_output_rgba_exact": True,
            "all_output_locks_exact": True,
        },
        "runtime": {
            "status": "not_tested",
            "purpose": runtime_config["purpose"],
            "required_routes": required_routes,
            "expected_visual_effect": runtime_config[
                "expected_visual_effect"
            ],
            "promotion_rule": runtime_config["promotion_rule"],
        },
    }
    return outputs, report


__all__ = [
    "AtlasMask",
    "UiAtlasCanaryError",
    "apply_masked_rgba",
    "build_ui_atlas_map_canary",
    "verify_masked_rgba",
]
