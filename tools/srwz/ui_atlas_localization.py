"""Deterministic Chinese text replacement for one mapped UI-atlas locator."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from .font_source import (
    FontSourceError,
    load_font_lock,
    verify_font_lock_files,
)
from .imagemagick import (
    imagemagick_version,
    read_rgba8,
    render_grayscale_text_mask,
    render_tim2_png8,
    require_imagemagick,
    write_deterministic_rgba8_png,
)
from .patch_audit import sha256_bytes, summarize_diff
from .tim2_writeback import CANARY_HEIGHT, CANARY_WIDTH, inject_indexed4_rgba
from .ui_atlas_canary import (
    AtlasMask,
    UiAtlasCanaryError,
    build_ui_atlas_map_canary,
)


class UiAtlasLocalizationError(ValueError):
    """A localized atlas does not match its locked mapping or render contract."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiAtlasLocalizationError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise UiAtlasLocalizationError(f"JSON root must be an object: {path}")
    return value


def _project_path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiAtlasLocalizationError(
            "project path must be a non-empty string"
        )
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise UiAtlasLocalizationError(
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
        "path": str(path.resolve().relative_to(root.resolve())),
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }


def _decode_ramp(raw: object) -> tuple[bytes, ...]:
    if (
        not isinstance(raw, list)
        or len(raw) < 2
        or any(not isinstance(value, str) or len(value) != 8 for value in raw)
    ):
        raise UiAtlasLocalizationError(
            "localized atlas ramp must contain at least two RGBA colors"
        )
    try:
        ramp = tuple(bytes.fromhex(value) for value in raw)
    except ValueError as error:
        raise UiAtlasLocalizationError(
            "localized atlas ramp contains invalid hexadecimal"
        ) from error
    if len(ramp) != len(set(ramp)) or any(color[3] != 0xFF for color in ramp):
        raise UiAtlasLocalizationError(
            "localized atlas ramp must be unique and fully opaque"
        )
    return ramp


def apply_text_mask(
    erased_rgba: bytes,
    grayscale_mask: bytes,
    mask: AtlasMask,
    ramp: Sequence[bytes],
) -> tuple[bytes, dict]:
    """Place one quantized grayscale label inside an already-erased rectangle."""

    expected_rgba_size = CANARY_WIDTH * CANARY_HEIGHT * 4
    expected_mask_size = mask.width * mask.height
    if len(erased_rgba) != expected_rgba_size:
        raise UiAtlasLocalizationError("localized atlas RGBA size is invalid")
    if len(grayscale_mask) != expected_mask_size:
        raise UiAtlasLocalizationError(
            "localized atlas grayscale mask size is invalid"
        )
    normalized_ramp = tuple(bytes(color) for color in ramp)
    allowed_backgrounds = {
        mask.replacement_rgba,
        *mask.preserve_rgba,
    }
    if (
        len(normalized_ramp) < 2
        or len(normalized_ramp) != len(set(normalized_ramp))
        or any(len(color) != 4 or color[3] != 0xFF for color in normalized_ramp)
    ):
        raise UiAtlasLocalizationError("localized atlas ramp is invalid")

    edited = bytearray(erased_rgba)
    added_indexes = []
    ramp_counts = {color: 0 for color in normalized_ramp}
    for local_y in range(mask.height):
        for local_x in range(mask.width):
            local_index = local_y * mask.width + local_x
            coverage = grayscale_mask[local_index]
            x = mask.x + local_x
            y = mask.y + local_y
            pixel_index = y * CANARY_WIDTH + x
            start = pixel_index * 4
            before = erased_rgba[start : start + 4]
            if before not in allowed_backgrounds:
                raise UiAtlasLocalizationError(
                    "localized atlas base is not erased or preserved "
                    f"background at ({x},{y})"
                )
            if coverage == 0:
                continue
            ramp_index = (
                coverage * (len(normalized_ramp) - 1) + 127
            ) // 255
            color = normalized_ramp[ramp_index]
            edited[start : start + 4] = color
            added_indexes.append(pixel_index)
            ramp_counts[color] += 1

    if not added_indexes:
        raise UiAtlasLocalizationError(
            "localized atlas text mask has no visible pixels"
        )
    output = bytes(edited)
    for pixel_index in range(CANARY_WIDTH * CANARY_HEIGHT):
        x = pixel_index % CANARY_WIDTH
        y = pixel_index // CANARY_WIDTH
        inside = (
            mask.x <= x < mask.x + mask.width
            and mask.y <= y < mask.y + mask.height
        )
        start = pixel_index * 4
        before = erased_rgba[start : start + 4]
        after = output[start : start + 4]
        if not inside and before != after:
            raise UiAtlasLocalizationError(
                f"localized atlas text escaped its mask at ({x},{y})"
            )
    return output, {
        "added_pixel_count": len(added_indexes),
        "added_pixel_indexes_sha256": sha256_bytes(
            b"".join(
                index.to_bytes(4, "little") for index in added_indexes
            )
        ),
        "ramp_rgba_counts": {
            color.hex(): count
            for color, count in ramp_counts.items()
            if count
        },
        "outside_mask_rgba_exact": True,
        "erased_background_preimage_exact": True,
    }


def rgba_delta(before: bytes, after: bytes, mask: AtlasMask) -> dict:
    """Describe an exact RGBA delta and require it to stay inside the mask."""

    expected_size = CANARY_WIDTH * CANARY_HEIGHT * 4
    if len(before) != expected_size or len(after) != expected_size:
        raise UiAtlasLocalizationError("localized atlas delta size is invalid")
    changed = []
    for pixel_index in range(CANARY_WIDTH * CANARY_HEIGHT):
        start = pixel_index * 4
        if before[start : start + 4] == after[start : start + 4]:
            continue
        x = pixel_index % CANARY_WIDTH
        y = pixel_index // CANARY_WIDTH
        if not (
            mask.x <= x < mask.x + mask.width
            and mask.y <= y < mask.y + mask.height
        ):
            raise UiAtlasLocalizationError(
                f"localized atlas delta escaped its mask at ({x},{y})"
            )
        changed.append(pixel_index)
    if not changed:
        raise UiAtlasLocalizationError("localized atlas has no RGBA delta")
    return {
        "changed_pixel_count": len(changed),
        "changed_pixel_indexes_sha256": sha256_bytes(
            b"".join(index.to_bytes(4, "little") for index in changed)
        ),
        "outside_mask_rgba_exact": True,
    }


def build_ui_atlas_localization(
    project_root: Path,
    work_root: Path,
    config_path: Path,
    *,
    enforce_expected: bool = True,
) -> tuple[dict[str, bytes], dict]:
    """Build one localized atlas component from a locked erasure canary."""

    root = project_root.resolve()
    work = work_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiAtlasLocalizationError(
            "unsupported localized UI-atlas schema"
        )

    base_reference = config.get("base_mapping")
    target = config.get("target")
    label = config.get("localized_label")
    runtime = config.get("runtime")
    if not all(
        isinstance(value, Mapping)
        for value in (base_reference, target, label, runtime)
    ):
        raise UiAtlasLocalizationError(
            "localized UI-atlas config is incomplete"
        )

    base_config_path = _project_path(root, base_reference.get("config"))
    base_manifest_path = _project_path(root, base_reference.get("manifest"))
    if _sha256_path(base_config_path) != base_reference.get("config_sha256"):
        raise UiAtlasLocalizationError("base atlas config SHA-256 drift")
    if _sha256_path(base_manifest_path) != base_reference.get(
        "manifest_sha256"
    ):
        raise UiAtlasLocalizationError("base atlas manifest SHA-256 drift")
    try:
        base_payloads, base_report = build_ui_atlas_map_canary(
            root,
            base_config_path,
        )
    except UiAtlasCanaryError as error:
        raise UiAtlasLocalizationError(str(error)) from error
    committed_base = _json_object(base_manifest_path)
    if committed_base != base_report:
        raise UiAtlasLocalizationError(
            "base atlas mapping manifest is not reproducible"
        )
    if base_report.get("status") != base_reference.get("required_status"):
        raise UiAtlasLocalizationError("base atlas mapping status drift")

    base_target = base_report["target"]
    expected_target = {
        "member": target.get("member"),
        "chunk_index": target.get("chunk_index"),
        "record_index": target.get("record_index"),
        "picture_index": target.get("picture_index"),
        "semantic_locator": target.get("semantic_locator"),
    }
    actual_target = {
        key: base_target.get(key) for key in expected_target
    }
    if actual_target != expected_target:
        raise UiAtlasLocalizationError(
            "localized atlas target differs from the base mapping"
        )
    if target.get("operation") != "replace_erased_locator_with_text":
        raise UiAtlasLocalizationError(
            "unsupported localized UI-atlas operation"
        )
    mask = AtlasMask.from_mapping(base_target["mask"])

    translation_reference = label.get("translation_source")
    if not isinstance(translation_reference, Mapping):
        raise UiAtlasLocalizationError(
            "localized atlas translation source is missing"
        )
    translation_path = _project_path(
        root,
        translation_reference.get("path"),
    )
    if _sha256_path(translation_path) != translation_reference.get("sha256"):
        raise UiAtlasLocalizationError(
            "localized atlas translation source drift"
        )
    translation_document = _json_object(translation_path)
    raw_entries = translation_document.get("entries")
    entry_id = translation_reference.get("entry_id")
    if not isinstance(raw_entries, list) or not isinstance(entry_id, str):
        raise UiAtlasLocalizationError(
            "localized atlas translation source is invalid"
        )
    matches = [
        entry
        for entry in raw_entries
        if isinstance(entry, Mapping) and entry.get("id") == entry_id
    ]
    if len(matches) != 1:
        raise UiAtlasLocalizationError(
            "localized atlas translation entry is not unique"
        )
    decision = matches[0]
    source_locator = decision.get("source_text")
    text = decision.get("translation")
    source_refs = decision.get("source_refs")
    if (
        decision.get("editorial_status")
        != translation_reference.get("minimum_editorial_status")
        or not isinstance(source_refs, list)
        or not source_refs
        or any(not isinstance(ref, str) or not ref for ref in source_refs)
        or not isinstance(source_locator, str)
        or decision.get("source_text_sha256")
        != sha256_bytes(source_locator.encode("utf-8"))
    ):
        raise UiAtlasLocalizationError(
            "localized atlas translation decision is invalid"
        )
    render = label.get("render")
    if (
        source_locator != target.get("semantic_locator")
        or not isinstance(text, str)
        or not text
        or "\n" in text
        or "\r" in text
        or not isinstance(render, Mapping)
    ):
        raise UiAtlasLocalizationError(
            "localized atlas label is invalid"
        )
    point_size = render.get("point_size")
    stroke_gray = render.get("stroke_gray")
    stroke_width = render.get("stroke_width")
    fill_stroke_width = render.get("fill_stroke_width", 0)
    if (
        not isinstance(point_size, int)
        or isinstance(point_size, bool)
        or point_size <= 0
        or not isinstance(stroke_gray, str)
        or not isinstance(stroke_width, (int, float))
        or isinstance(stroke_width, bool)
        or not isinstance(fill_stroke_width, (int, float))
        or isinstance(fill_stroke_width, bool)
    ):
        raise UiAtlasLocalizationError(
            "localized atlas render contract is invalid"
        )
    ramp = _decode_ramp(render.get("ramp_rgba"))

    font_lock_path = _project_path(root, label.get("font_lock"))
    if _sha256_path(font_lock_path) != label.get("font_lock_sha256"):
        raise UiAtlasLocalizationError("localized atlas font lock drift")
    try:
        font_lock = load_font_lock(font_lock_path)
        font_files = verify_font_lock_files(root, work, font_lock)
    except FontSourceError as error:
        raise UiAtlasLocalizationError(str(error)) from error

    magick = require_imagemagick()
    version = imagemagick_version(magick)
    if version != config.get("toolchain", {}).get("imagemagick"):
        raise UiAtlasLocalizationError(
            "localized atlas ImageMagick version drift"
        )

    with tempfile.TemporaryDirectory(
        prefix="srwz-ui-atlas-localization-"
    ) as directory:
        temporary = Path(directory)
        reference_path = temporary / "reference.png"
        erased_path = temporary / "erased.png"
        localized_path = temporary / "localized.png"
        output_tm2_path = temporary / "localized.tm2"
        reread_path = temporary / "localized-reread.png"
        reference_path.write_bytes(base_payloads["reference_png"])
        erased_path.write_bytes(base_payloads["edited_png"])
        original_rgba = read_rgba8(
            magick,
            reference_path,
            expected_width=CANARY_WIDTH,
            expected_height=CANARY_HEIGHT,
        )
        erased_rgba = read_rgba8(
            magick,
            erased_path,
            expected_width=CANARY_WIDTH,
            expected_height=CANARY_HEIGHT,
        )
        source_palette = {
            original_rgba[index : index + 4]
            for index in range(0, len(original_rgba), 4)
        }
        missing_ramp = [
            color.hex() for color in ramp if color not in source_palette
        ]
        if missing_ramp:
            raise UiAtlasLocalizationError(
                "localized atlas ramp is absent from source palette: "
                + ", ".join(missing_ramp)
            )
        grayscale_mask = render_grayscale_text_mask(
            magick,
            font_files["font"],
            text,
            width=mask.width,
            height=mask.height,
            point_size=point_size,
            stroke_gray=stroke_gray,
            stroke_width=float(stroke_width),
            fill_stroke_width=float(fill_stroke_width),
        )
        localized_rgba, text_audit = apply_text_mask(
            erased_rgba,
            grayscale_mask,
            mask,
            ramp,
        )
        original_delta = rgba_delta(original_rgba, localized_rgba, mask)
        erased_delta = rgba_delta(erased_rgba, localized_rgba, mask)
        if (
            erased_delta["changed_pixel_count"]
            != text_audit["added_pixel_count"]
        ):
            raise UiAtlasLocalizationError(
                "localized atlas text delta count drift"
            )

        chunk_start = base_target["chunk_start"]
        chunk_end = base_target["chunk_end"]
        base_archive = base_payloads["archive"]
        erased_chunk = base_archive[chunk_start:chunk_end]
        injection = inject_indexed4_rgba(
            erased_chunk,
            erased_rgba,
            localized_rgba,
        )
        output_tm2_path.write_bytes(injection.data)
        render_tim2_png8(magick, output_tm2_path, reread_path)
        reread_rgba = read_rgba8(
            magick,
            reread_path,
            expected_width=CANARY_WIDTH,
            expected_height=CANARY_HEIGHT,
        )
        if reread_rgba != localized_rgba:
            raise UiAtlasLocalizationError(
                "localized atlas TIM2 RGBA reread mismatch"
            )
        write_deterministic_rgba8_png(
            magick,
            localized_rgba,
            localized_path,
            width=CANARY_WIDTH,
            height=CANARY_HEIGHT,
        )
        localized_png = localized_path.read_bytes()

    localized_archive = (
        base_archive[:chunk_start]
        + injection.data
        + base_archive[chunk_end:]
    )
    if len(localized_archive) != len(base_archive):
        raise UiAtlasLocalizationError(
            "localized atlas changed archive size"
        )
    archive_diff = summarize_diff(
        base_archive,
        localized_archive,
    ).to_mapping()
    expected = {
        "text_mask": {
            "size": len(grayscale_mask),
            "sha256": sha256_bytes(grayscale_mask),
            "nonzero_pixel_count": sum(value != 0 for value in grayscale_mask),
        },
        "reference_png": {
            "size": len(base_payloads["reference_png"]),
            "sha256": sha256_bytes(base_payloads["reference_png"]),
        },
        "localized_png": {
            "size": len(localized_png),
            "sha256": sha256_bytes(localized_png),
        },
        "archive": {
            "size": len(localized_archive),
            "sha256": sha256_bytes(localized_archive),
        },
        "chunk": {
            "size": len(injection.data),
            "sha256": sha256_bytes(injection.data),
        },
        "added_pixel_count": text_audit["added_pixel_count"],
        "original_changed_pixel_count": original_delta[
            "changed_pixel_count"
        ],
        "original_changed_pixel_indexes_sha256": original_delta[
            "changed_pixel_indexes_sha256"
        ],
        "changed_archive_byte_count": archive_diff["diff_count"],
        "changed_archive_range_count": archive_diff["range_count"],
    }
    configured_expected = config.get("expected")
    if enforce_expected and configured_expected != expected:
        raise UiAtlasLocalizationError(
            f"localized atlas output ratchet drift: {expected}"
        )

    required_routes = runtime.get("required_routes")
    runtime_statements = (
        runtime.get("purpose"),
        runtime.get("expected_visual_effect"),
        runtime.get("promotion_rule"),
    )
    if (
        not isinstance(required_routes, list)
        or not required_routes
        or any(not isinstance(route, str) or not route for route in required_routes)
        or any(
            not isinstance(statement, str) or not statement.strip()
            for statement in runtime_statements
        )
    ):
        raise UiAtlasLocalizationError(
            "localized atlas runtime contract is invalid"
        )

    report = {
        "schema_version": 1,
        "status": (
            "static_localized_component_validated_runtime_mapping_pending"
        ),
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "content_policy": (
            "Hashes, coordinates, counts and render parameters only; game "
            "bytes, localized text and preview PNGs remain outside this "
            "committed manifest."
        ),
        "inputs": {
            "config": _file_lock(root, config_path),
            "base_mapping": {
                "config": _file_lock(root, base_config_path),
                "manifest": _file_lock(root, base_manifest_path),
                "profile_id": base_report["profile_id"],
                "status": base_report["status"],
                "archive": base_report["outputs"]["archive"],
            },
            "font": {
                "lock": _file_lock(root, font_lock_path),
                "family": font_lock["family"],
                "version": font_lock["version"],
                "commit": font_lock["commit"],
                "font_sha256": font_lock["font"]["sha256"],
                "license_spdx": font_lock["license"]["spdx"],
                "license_sha256": font_lock["license"]["sha256"],
            },
            "translation_source": {
                "file": _file_lock(root, translation_path),
                "batch_id": translation_document.get("batch_id"),
                "entry_id": entry_id,
                "editorial_status": decision["editorial_status"],
                "source_ref_count": len(source_refs),
            },
        },
        "target": {
            "member": target["member"],
            "chunk_index": target["chunk_index"],
            "chunk_start": chunk_start,
            "chunk_end": chunk_end,
            "record_index": target["record_index"],
            "picture_index": target["picture_index"],
            "semantic_locator": target["semantic_locator"],
            "operation": target["operation"],
            "candidate_scene_ids": base_target["candidate_scene_ids"],
            "mask": mask.to_mapping(),
            "mask_audit": original_delta,
        },
        "localized_label": {
            "source_locator_sha256": sha256_bytes(
                source_locator.encode("utf-8")
            ),
            "text_sha256": sha256_bytes(text.encode("utf-8")),
            "character_count": len(text),
            "render": {
                "point_size": point_size,
                "stroke_gray": stroke_gray,
                "stroke_width": stroke_width,
                "fill_stroke_width": fill_stroke_width,
                "ramp_rgba": [color.hex() for color in ramp],
                "text_mask": expected["text_mask"],
            },
        },
        "toolchain": {
            "imagemagick": version,
        },
        "text_audit": {
            **text_audit,
            "delta_from_erased": erased_delta,
            "delta_from_original": original_delta,
        },
        "injection": {
            **injection.to_metadata(),
            "archive_diff_from_erased_base": archive_diff,
            "chunk_size_unchanged": len(injection.data) == len(erased_chunk),
            "archive_size_unchanged": (
                len(localized_archive) == len(base_archive)
            ),
            "non_target_chunks_exact": True,
            "output_rgba_exact": True,
        },
        "outputs": {
            "archive": expected["archive"],
            "chunk": expected["chunk"],
            "reference_png": expected["reference_png"],
            "localized_png": expected["localized_png"],
        },
        "expected_lock": expected,
        "acceptance": {
            "base_mapping_reproduced_exact": True,
            "font_and_license_locked": True,
            "text_mask_hash_locked": True,
            "ramp_uses_only_source_palette_rgba": True,
            "localized_pixels_within_mapping_mask": True,
            "erased_locator_preimage_exact": True,
            "tim2_header_clut_and_padding_exact": True,
            "archive_geometry_and_other_chunks_exact": True,
            "imagemagick_output_rgba_exact": True,
            "all_output_locks_exact": enforce_expected,
        },
        "runtime": {
            "status": "not_tested",
            "purpose": runtime["purpose"],
            "required_routes": required_routes,
            "expected_visual_effect": runtime["expected_visual_effect"],
            "promotion_rule": runtime["promotion_rule"],
        },
    }
    return {
        "archive": localized_archive,
        "reference_png": base_payloads["reference_png"],
        "localized_png": localized_png,
    }, report


__all__ = [
    "UiAtlasLocalizationError",
    "apply_text_mask",
    "build_ui_atlas_localization",
    "rgba_delta",
]
