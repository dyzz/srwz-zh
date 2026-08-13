"""Deterministic Chinese text replacement for one mapped UI-atlas locator."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import zlib
from pathlib import Path
from typing import Mapping, Sequence

from .font_flavor import (
    FontFlavorError,
    font_flavor_metadata,
    load_font_flavor_reference,
    verify_font_flavor_files,
)
from .font_source import font_source_metadata
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
    apply_masked_rgba,
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


def _json_sha256(value: object) -> str:
    return sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _frozen_bytes(data: bytes) -> dict:
    return {
        "size": len(data),
        "sha256": sha256_bytes(data),
        "zlib_base64": base64.b64encode(zlib.compress(data, 9)).decode("ascii"),
    }


def _thaw_bytes(raw: object, *, label: str, expected_size: int) -> bytes:
    if not isinstance(raw, Mapping):
        raise UiAtlasLocalizationError(f"{label} snapshot payload is missing")
    encoded = raw.get("zlib_base64")
    if not isinstance(encoded, str) or not encoded:
        raise UiAtlasLocalizationError(f"{label} snapshot payload is invalid")
    try:
        data = zlib.decompress(base64.b64decode(encoded, validate=True))
    except (ValueError, zlib.error) as error:
        raise UiAtlasLocalizationError(
            f"{label} snapshot payload cannot be decoded"
        ) from error
    if (
        len(data) != expected_size
        or raw.get("size") != len(data)
        or raw.get("sha256") != sha256_bytes(data)
    ):
        raise UiAtlasLocalizationError(f"{label} snapshot payload drift")
    return data


def _file_lock(root: Path, path: Path) -> dict:
    return {
        "path": str(path.resolve().relative_to(root.resolve())),
        "size": path.stat().st_size,
        "sha256": _sha256_path(path),
    }


def _crop_rgba(rgba: bytes, mask: AtlasMask) -> bytes:
    """Return one exact row-major RGBA atlas-element rectangle."""

    expected_size = CANARY_WIDTH * CANARY_HEIGHT * 4
    if len(rgba) != expected_size:
        raise UiAtlasLocalizationError("localized atlas RGBA size is invalid")
    return b"".join(
        rgba[
            (y * CANARY_WIDTH + mask.x) * 4 :
            (y * CANARY_WIDTH + mask.x + mask.width) * 4
        ]
        for y in range(mask.y, mask.y + mask.height)
    )


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


def _decode_indexed_layers(
    raw: object,
) -> dict[str, tuple[tuple[bytes, int], ...]] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"outline", "fill"}:
        raise UiAtlasLocalizationError(
            "indexed text layers must define outline and fill"
        )
    decoded = {}
    for layer_name in ("outline", "fill"):
        entries = raw[layer_name]
        if not isinstance(entries, list) or len(entries) < 2:
            raise UiAtlasLocalizationError(
                f"indexed {layer_name} layer must contain at least two entries"
            )
        layer = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise UiAtlasLocalizationError(
                    f"indexed {layer_name} layer entry is malformed"
                )
            rgba = entry.get("rgba")
            palette_index = entry.get("palette_index")
            if (
                not isinstance(rgba, str)
                or len(rgba) != 8
                or not isinstance(palette_index, int)
                or isinstance(palette_index, bool)
                or not 0 <= palette_index <= 0x0F
            ):
                raise UiAtlasLocalizationError(
                    f"indexed {layer_name} layer entry is invalid"
                )
            try:
                color = bytes.fromhex(rgba)
            except ValueError as error:
                raise UiAtlasLocalizationError(
                    f"indexed {layer_name} layer contains invalid RGBA"
                ) from error
            layer.append((color, palette_index))
        if len({index for _color, index in layer}) != len(layer):
            raise UiAtlasLocalizationError(
                f"indexed {layer_name} palette indexes must be unique"
            )
        decoded[layer_name] = tuple(layer)
    if 0 in {
        index for layer in decoded.values() for _color, index in layer
    }:
        raise UiAtlasLocalizationError(
            "indexed text layers cannot use the background index"
        )
    return decoded


def _indexed_layers_metadata(
    layers: Mapping[str, Sequence[tuple[bytes, int]]],
) -> dict:
    return {
        layer_name: [
            {"rgba": color.hex(), "palette_index": palette_index}
            for color, palette_index in entries
        ]
        for layer_name, entries in layers.items()
    }


def _resolve_indexed_layers(
    render: Mapping,
    profiles: Mapping[str, Mapping[str, Sequence[tuple[bytes, int]]]],
) -> Mapping[str, Sequence[tuple[bytes, int]]] | None:
    inline = render.get("indexed_layers")
    profile_name = render.get("indexed_layer_profile")
    if inline is not None and profile_name is not None:
        raise UiAtlasLocalizationError(
            "indexed text render cannot use both a profile and inline layers"
        )
    if profile_name is None:
        return _decode_indexed_layers(inline)
    if not isinstance(profile_name, str) or profile_name not in profiles:
        raise UiAtlasLocalizationError(
            "indexed text layer profile is missing or invalid"
        )
    return profiles[profile_name]


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


def apply_indexed_text_layers(
    erased_rgba: bytes,
    outline_mask: bytes,
    fill_mask: bytes,
    mask: AtlasMask,
    layers: Mapping[str, Sequence[tuple[bytes, int]]],
) -> tuple[bytes, dict, dict[int, int]]:
    """Render a dark indexed outline plus a separately indexed light fill."""

    expected_rgba_size = CANARY_WIDTH * CANARY_HEIGHT * 4
    expected_mask_size = mask.width * mask.height
    if len(erased_rgba) != expected_rgba_size:
        raise UiAtlasLocalizationError("localized atlas RGBA size is invalid")
    if len(outline_mask) != expected_mask_size or len(fill_mask) != expected_mask_size:
        raise UiAtlasLocalizationError(
            "indexed localized atlas text mask size is invalid"
        )
    outline = tuple(layers["outline"])
    fill = tuple(layers["fill"])
    allowed_backgrounds = {mask.replacement_rgba, *mask.preserve_rgba}
    outline_only = [
        outline_mask[index]
        for index in range(expected_mask_size)
        if outline_mask[index] and not fill_mask[index]
    ]
    visible_fill = [value for value in fill_mask if value]
    if not outline_only or not visible_fill:
        raise UiAtlasLocalizationError(
            "indexed text layers require visible outline and fill pixels"
        )
    layer_maximum = {
        "outline": max(outline_only),
        "fill": max(visible_fill),
    }
    edited = bytearray(erased_rgba)
    exact_indexes = {}
    counts = {
        "outline": {index: 0 for _color, index in outline},
        "fill": {index: 0 for _color, index in fill},
    }
    added_indexes = []
    for local_y in range(mask.height):
        for local_x in range(mask.width):
            local_index = local_y * mask.width + local_x
            fill_coverage = fill_mask[local_index]
            outline_coverage = outline_mask[local_index]
            if fill_coverage:
                layer_name = "fill"
                coverage = fill_coverage
                layer = fill
            elif outline_coverage:
                layer_name = "outline"
                coverage = outline_coverage
                layer = outline
            else:
                continue
            maximum = layer_maximum[layer_name]
            ramp_index = (
                coverage * (len(layer) - 1) + maximum // 2
            ) // maximum
            color, palette_index = layer[min(ramp_index, len(layer) - 1)]
            x = mask.x + local_x
            y = mask.y + local_y
            pixel_index = y * CANARY_WIDTH + x
            start = pixel_index * 4
            if erased_rgba[start : start + 4] not in allowed_backgrounds:
                raise UiAtlasLocalizationError(
                    "indexed localized atlas base is not erased at "
                    f"({x},{y})"
                )
            edited[start : start + 4] = color
            exact_indexes[pixel_index] = palette_index
            counts[layer_name][palette_index] += 1
            added_indexes.append(pixel_index)
    if not added_indexes:
        raise UiAtlasLocalizationError(
            "indexed localized atlas text has no visible pixels"
        )
    return bytes(edited), {
        "added_pixel_count": len(added_indexes),
        "added_pixel_indexes_sha256": sha256_bytes(
            b"".join(index.to_bytes(4, "little") for index in added_indexes)
        ),
        "indexed_layer_counts": {
            layer_name: {
                str(index): count
                for index, count in layer_counts.items()
                if count
            }
            for layer_name, layer_counts in counts.items()
        },
        "fill_mask_sha256": sha256_bytes(fill_mask),
        "fill_mask_nonzero_pixel_count": len(visible_fill),
        "outside_mask_rgba_exact": True,
        "erased_background_preimage_exact": True,
    }, exact_indexes


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


def _mask_pixels(
    masks: Sequence[AtlasMask],
) -> set[tuple[int, int]]:
    normalized = tuple(masks)
    if not normalized:
        raise UiAtlasLocalizationError("localized atlas mask set is empty")
    occupied: set[tuple[int, int]] = set()
    for mask in normalized:
        for y in range(mask.y, mask.y + mask.height):
            for x in range(mask.x, mask.x + mask.width):
                if (x, y) in occupied:
                    raise UiAtlasLocalizationError(
                        f"localized atlas masks overlap at ({x},{y})"
                    )
                occupied.add((x, y))
    return occupied


def rgba_delta_in_masks(
    before: bytes,
    after: bytes,
    masks: Sequence[AtlasMask],
) -> dict:
    """Describe an RGBA delta confined to a non-overlapping mask set."""

    normalized = tuple(masks)
    occupied = _mask_pixels(normalized)
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
        if (x, y) not in occupied:
            raise UiAtlasLocalizationError(
                f"localized atlas delta escaped its masks at ({x},{y})"
            )
        changed.append(pixel_index)
    if not changed:
        raise UiAtlasLocalizationError("localized atlas has no RGBA delta")
    return {
        "changed_pixel_count": len(changed),
        "changed_pixel_indexes_sha256": sha256_bytes(
            b"".join(index.to_bytes(4, "little") for index in changed)
        ),
        "mask_count": len(normalized),
        "outside_masks_rgba_exact": True,
    }


def build_ui_atlas_localization(
    project_root: Path,
    work_root: Path,
    config_path: Path,
    *,
    enforce_expected: bool = True,
    live_render: bool = False,
    render_snapshot_sink: dict | None = None,
) -> tuple[dict[str, bytes], dict]:
    """Build one localized atlas from frozen masks or an explicit refreeze."""

    root = project_root.resolve()
    work = work_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiAtlasLocalizationError(
            "unsupported localized UI-atlas schema"
        )
    replacement_mode = config.get("replacement_mode", "masked_text")
    if replacement_mode not in {"masked_text", "fixed_source_elements"}:
        raise UiAtlasLocalizationError(
            "unsupported localized UI-atlas replacement mode"
        )
    fixed_source_elements = replacement_mode == "fixed_source_elements"
    raw_indexed_layer_profiles = config.get(
        "indexed_text_layer_profiles", {}
    )
    if not isinstance(raw_indexed_layer_profiles, Mapping):
        raise UiAtlasLocalizationError(
            "indexed text layer profiles must be an object"
        )
    indexed_layer_profiles = {}
    for profile_name, raw_profile in raw_indexed_layer_profiles.items():
        if not isinstance(profile_name, str) or not profile_name:
            raise UiAtlasLocalizationError(
                "indexed text layer profile name is invalid"
            )
        decoded_profile = _decode_indexed_layers(raw_profile)
        if decoded_profile is None:
            raise UiAtlasLocalizationError(
                "indexed text layer profile cannot be empty"
            )
        indexed_layer_profiles[profile_name] = decoded_profile

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
    italic_shear_degrees = render.get("italic_shear_degrees", 0)
    horizontal_offset = render.get("horizontal_offset", 0)
    if (
        not isinstance(point_size, int)
        or isinstance(point_size, bool)
        or point_size <= 0
        or not isinstance(stroke_gray, str)
        or not isinstance(stroke_width, (int, float))
        or isinstance(stroke_width, bool)
        or not isinstance(fill_stroke_width, (int, float))
        or isinstance(fill_stroke_width, bool)
        or not isinstance(italic_shear_degrees, (int, float))
        or isinstance(italic_shear_degrees, bool)
        or not isinstance(horizontal_offset, int)
        or isinstance(horizontal_offset, bool)
    ):
        raise UiAtlasLocalizationError(
            "localized atlas render contract is invalid"
        )
    ramp = _decode_ramp(render.get("ramp_rgba"))

    label_specs = [
        {
            "semantic_locator": source_locator,
            "entry_id": entry_id,
            "decision": decision,
            "text": text,
            "mask": mask,
            "render": render,
            "point_size": point_size,
            "stroke_gray": stroke_gray,
            "stroke_width": stroke_width,
            "fill_stroke_width": fill_stroke_width,
            "italic_shear_degrees": italic_shear_degrees,
            "horizontal_offset": horizontal_offset,
            "ramp": ramp,
            "indexed_layers": _resolve_indexed_layers(
                render,
                indexed_layer_profiles,
            ),
            "source_element_id": label.get("source_element_id"),
            "source_element_rgba_sha256": label.get(
                "source_element_rgba_sha256"
            ),
        }
    ]
    additional_labels = config.get("additional_localized_labels", [])
    if not isinstance(additional_labels, list):
        raise UiAtlasLocalizationError(
            "additional localized atlas labels must be a list"
        )
    for raw in additional_labels:
        if not isinstance(raw, Mapping):
            raise UiAtlasLocalizationError(
                "additional localized atlas label is malformed"
            )
        additional_entry_id = raw.get("entry_id")
        additional_locator = raw.get("semantic_locator")
        matches = [
            entry
            for entry in raw_entries
            if isinstance(entry, Mapping)
            and entry.get("id") == additional_entry_id
        ]
        if len(matches) != 1:
            raise UiAtlasLocalizationError(
                "additional localized atlas translation entry is not unique"
            )
        additional_decision = matches[0]
        additional_text = additional_decision.get("translation")
        additional_source = additional_decision.get("source_text")
        additional_refs = additional_decision.get("source_refs")
        if (
            additional_decision.get("editorial_status")
            != raw.get("minimum_editorial_status")
            or additional_source != additional_locator
            or additional_decision.get("source_text_sha256")
            != sha256_bytes(str(additional_source).encode("utf-8"))
            or not isinstance(additional_refs, list)
            or not additional_refs
            or not isinstance(additional_text, str)
            or not additional_text
            or "\n" in additional_text
            or "\r" in additional_text
        ):
            raise UiAtlasLocalizationError(
                "additional localized atlas translation decision is invalid"
            )
        additional_render = raw.get("render")
        if not isinstance(additional_render, Mapping):
            raise UiAtlasLocalizationError(
                "additional localized atlas render contract is missing"
            )
        additional_point_size = additional_render.get("point_size")
        additional_stroke_gray = additional_render.get("stroke_gray")
        additional_stroke_width = additional_render.get("stroke_width")
        additional_fill_stroke_width = additional_render.get(
            "fill_stroke_width", 0
        )
        additional_italic_shear_degrees = additional_render.get(
            "italic_shear_degrees", 0
        )
        additional_horizontal_offset = additional_render.get(
            "horizontal_offset", 0
        )
        if (
            not isinstance(additional_point_size, int)
            or isinstance(additional_point_size, bool)
            or additional_point_size <= 0
            or not isinstance(additional_stroke_gray, str)
            or not isinstance(additional_stroke_width, (int, float))
            or isinstance(additional_stroke_width, bool)
            or not isinstance(
                additional_fill_stroke_width, (int, float)
            )
            or isinstance(additional_fill_stroke_width, bool)
            or not isinstance(
                additional_italic_shear_degrees, (int, float)
            )
            or isinstance(additional_italic_shear_degrees, bool)
            or not isinstance(additional_horizontal_offset, int)
            or isinstance(additional_horizontal_offset, bool)
        ):
            raise UiAtlasLocalizationError(
                "additional localized atlas render contract is invalid"
            )
        label_specs.append(
            {
                "semantic_locator": additional_locator,
                "entry_id": additional_entry_id,
                "decision": additional_decision,
                "text": additional_text,
                "mask": AtlasMask.from_mapping(raw.get("mask")),
                "render": additional_render,
                "point_size": additional_point_size,
                "stroke_gray": additional_stroke_gray,
                "stroke_width": additional_stroke_width,
                "fill_stroke_width": additional_fill_stroke_width,
                "italic_shear_degrees": (
                    additional_italic_shear_degrees
                ),
                "horizontal_offset": additional_horizontal_offset,
                "ramp": _decode_ramp(additional_render.get("ramp_rgba")),
                "indexed_layers": _resolve_indexed_layers(
                    additional_render,
                    indexed_layer_profiles,
                ),
                "source_element_id": raw.get("source_element_id"),
                "source_element_rgba_sha256": raw.get(
                    "source_element_rgba_sha256"
                ),
            }
        )

    _mask_pixels([spec["mask"] for spec in label_specs])
    if not fixed_source_elements and any(
        spec["indexed_layers"] is not None for spec in label_specs
    ):
        raise UiAtlasLocalizationError(
            "indexed text layers require fixed source elements"
        )

    try:
        font_flavor = load_font_flavor_reference(
            root,
            label.get("font_flavor"),
        )
        font_lock, font_files, fallback_paths, _fallback_reports = (
            verify_font_flavor_files(root, work, font_flavor)
        )
    except FontFlavorError as error:
        raise UiAtlasLocalizationError(str(error)) from error
    unsupported = sorted(
        set().union(*(set(spec["text"]) for spec in label_specs))
        & set(fallback_paths)
    )
    if unsupported:
        raise UiAtlasLocalizationError(
            "localized atlas text requires per-character fallback rendering: "
            + "".join(unsupported)
        )

    magick = require_imagemagick()
    version = imagemagick_version(magick)
    if version != config.get("toolchain", {}).get("imagemagick"):
        raise UiAtlasLocalizationError(
            "localized atlas ImageMagick version drift"
        )

    render_contract = [
        {
            "entry_id": spec["entry_id"],
            "text": spec["text"],
            "mask": spec["mask"].to_mapping(),
            "point_size": spec["point_size"],
            "stroke_gray": spec["stroke_gray"],
            "stroke_width": spec["stroke_width"],
            "fill_stroke_width": spec["fill_stroke_width"],
            "italic_shear_degrees": spec["italic_shear_degrees"],
            "horizontal_offset": spec["horizontal_offset"],
            "ramp_rgba": [color.hex() for color in spec["ramp"]],
            "indexed_layers": (
                _indexed_layers_metadata(spec["indexed_layers"])
                if spec["indexed_layers"] is not None
                else None
            ),
        }
        for spec in label_specs
    ]
    render_contract_sha256 = _json_sha256(render_contract)
    font_sha256 = _sha256_path(font_files["font"])
    translation_sha256 = _sha256_path(translation_path)
    base_reference_png_sha256 = sha256_bytes(base_payloads["reference_png"])
    base_erased_png_sha256 = sha256_bytes(base_payloads["edited_png"])
    render_snapshot_path = None
    render_snapshot = None
    render_snapshot_reference = config.get("render_snapshot")
    if not live_render and render_snapshot_reference is not None:
        if not isinstance(render_snapshot_reference, Mapping):
            raise UiAtlasLocalizationError(
                "localized atlas frozen render snapshot reference is invalid"
            )
        render_snapshot_path = _project_path(
            root,
            render_snapshot_reference.get("path"),
        )
        if (
            not render_snapshot_path.is_file()
            or render_snapshot_path.stat().st_size
            != render_snapshot_reference.get("size")
            or _sha256_path(render_snapshot_path)
            != render_snapshot_reference.get("sha256")
        ):
            raise UiAtlasLocalizationError(
                "localized atlas frozen render snapshot lock drift"
            )
        render_snapshot = _json_object(render_snapshot_path)
        if (
            render_snapshot.get("schema_version") != 1
            or render_snapshot.get("status") != "reviewed_locked"
            or render_snapshot.get("selection_authority")
            != "frozen_rendered_text_masks"
            or render_snapshot.get("profile_id") != config.get("profile_id")
            or render_snapshot.get("translation_source_sha256")
            != translation_sha256
            or render_snapshot.get("font_sha256") != font_sha256
            or render_snapshot.get("render_contract_sha256")
            != render_contract_sha256
            or render_snapshot.get("base_reference_png_sha256")
            != base_reference_png_sha256
            or render_snapshot.get("base_erased_png_sha256")
            != base_erased_png_sha256
            or render_snapshot.get("imagemagick_version") != version
        ):
            raise UiAtlasLocalizationError(
                "localized atlas frozen render snapshot provenance drift"
            )
        frozen_labels = render_snapshot.get("labels")
        if (
            not isinstance(frozen_labels, list)
            or len(frozen_labels) != len(label_specs)
        ):
            raise UiAtlasLocalizationError(
                "localized atlas frozen render label count drift"
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
        base_erased_rgba = read_rgba8(
            magick,
            erased_path,
            expected_width=CANARY_WIDTH,
            expected_height=CANARY_HEIGHT,
        )
        source_element_ids = []
        source_element_audits = []
        for spec in label_specs:
            source_element_id = spec["source_element_id"]
            source_element_hash = spec["source_element_rgba_sha256"]
            if (
                not fixed_source_elements
                and source_element_id is None
                and source_element_hash is None
            ):
                continue
            if (
                not isinstance(source_element_id, str)
                or not source_element_id
                or not isinstance(source_element_hash, str)
                or len(source_element_hash) != 64
            ):
                raise UiAtlasLocalizationError(
                    "localized atlas source element lock is invalid"
                )
            source_element_ids.append(source_element_id)
            crop = _crop_rgba(original_rgba, spec["mask"])
            actual_source_element_hash = sha256_bytes(crop)
            if actual_source_element_hash != source_element_hash:
                raise UiAtlasLocalizationError(
                    "localized atlas source element RGBA drift for "
                    f"{source_element_id}"
                )
            source_element_audits.append(
                {
                    "source_element_id": source_element_id,
                    "width": spec["mask"].width,
                    "height": spec["mask"].height,
                    "rgba_size": len(crop),
                    "rgba_sha256": actual_source_element_hash,
                }
            )
        if fixed_source_elements and len(source_element_ids) != len(
            label_specs
        ):
            raise UiAtlasLocalizationError(
                "fixed source element mode requires one lock per label"
            )
        if len(source_element_ids) != len(set(source_element_ids)):
            raise UiAtlasLocalizationError(
                "localized atlas source element ids are not unique"
            )
        source_palette = {
            original_rgba[index : index + 4]
            for index in range(0, len(original_rgba), 4)
        }
        missing_ramp = sorted(
            {
                color.hex()
                for spec in label_specs
                for color in (
                    *spec["ramp"],
                    *(
                        color
                        for layer in (spec["indexed_layers"] or {}).values()
                        for color, _palette_index in layer
                    ),
                )
                if color not in source_palette
            }
        )
        if missing_ramp:
            raise UiAtlasLocalizationError(
                "localized atlas ramp is absent from source palette: "
                + ", ".join(missing_ramp)
            )
        erased_rgba = base_erased_rgba
        for spec in label_specs[1:]:
            erased_rgba = apply_masked_rgba(erased_rgba, spec["mask"])
        localized_rgba = erased_rgba
        text_audits = []
        grayscale_masks = []
        fill_masks = []
        forced_palette_indexes_by_pixel = {}
        for label_index, spec in enumerate(label_specs):
            frozen_label = (
                None
                if render_snapshot is None
                else render_snapshot["labels"][label_index]
            )
            if render_snapshot is None:
                current_mask = render_grayscale_text_mask(
                    magick,
                    font_files["font"],
                    spec["text"],
                    width=spec["mask"].width,
                    height=spec["mask"].height,
                    point_size=spec["point_size"],
                    stroke_gray=spec["stroke_gray"],
                    stroke_width=float(spec["stroke_width"]),
                    fill_stroke_width=float(spec["fill_stroke_width"]),
                    italic_shear_degrees=float(
                        spec["italic_shear_degrees"]
                    ),
                    horizontal_offset=spec["horizontal_offset"],
                )
            else:
                if (
                    not isinstance(frozen_label, Mapping)
                    or frozen_label.get("entry_id") != spec["entry_id"]
                    or frozen_label.get("text_sha256")
                    != sha256_bytes(spec["text"].encode("utf-8"))
                ):
                    raise UiAtlasLocalizationError(
                        "localized atlas frozen render label identity drift"
                    )
                current_mask = _thaw_bytes(
                    frozen_label.get("outline_mask"),
                    label=f"{spec['entry_id']} outline mask",
                    expected_size=spec["mask"].width * spec["mask"].height,
                )
            indexed_layers = spec["indexed_layers"]
            if indexed_layers is None:
                localized_rgba, current_audit = apply_text_mask(
                    localized_rgba,
                    current_mask,
                    spec["mask"],
                    spec["ramp"],
                )
                fill_masks.append(None)
            else:
                if render_snapshot is None:
                    fill_mask = render_grayscale_text_mask(
                        magick,
                        font_files["font"],
                        spec["text"],
                        width=spec["mask"].width,
                        height=spec["mask"].height,
                        point_size=spec["point_size"],
                        stroke_gray="black",
                        stroke_width=0,
                        fill_stroke_width=float(spec["fill_stroke_width"]),
                        italic_shear_degrees=float(
                            spec["italic_shear_degrees"]
                        ),
                        horizontal_offset=spec["horizontal_offset"],
                    )
                else:
                    fill_mask = _thaw_bytes(
                        frozen_label.get("fill_mask"),
                        label=f"{spec['entry_id']} fill mask",
                        expected_size=(
                            spec["mask"].width * spec["mask"].height
                        ),
                    )
                (
                    localized_rgba,
                    current_audit,
                    current_exact_indexes,
                ) = apply_indexed_text_layers(
                    localized_rgba,
                    current_mask,
                    fill_mask,
                    spec["mask"],
                    indexed_layers,
                )
                forced_palette_indexes_by_pixel.update(
                    current_exact_indexes
                )
                fill_masks.append(fill_mask)
            grayscale_masks.append(current_mask)
            text_audits.append(current_audit)
        masks = [spec["mask"] for spec in label_specs]
        expected_background_palette_index = config.get(
            "expected_background_palette_index"
        )
        force_reindex_entire_masks = config.get(
            "force_reindex_entire_masks",
            fixed_source_elements,
        )
        if not isinstance(force_reindex_entire_masks, bool):
            raise UiAtlasLocalizationError(
                "force_reindex_entire_masks must be boolean"
            )
        if fixed_source_elements and not force_reindex_entire_masks:
            raise UiAtlasLocalizationError(
                "fixed source elements require full mask reindexing"
            )
        if force_reindex_entire_masks:
            if (
                not isinstance(expected_background_palette_index, int)
                or isinstance(expected_background_palette_index, bool)
                or not 0 <= expected_background_palette_index <= 0x0F
            ):
                raise UiAtlasLocalizationError(
                    "fixed source elements require a background palette "
                    "index that fits one nibble"
                )
            replacement_colors = {
                current_mask.replacement_rgba for current_mask in masks
            }
            if len(replacement_colors) != 1:
                raise UiAtlasLocalizationError(
                    "fixed source element backgrounds must use one RGBA"
                )
            forced_pixel_indexes = {
                y * CANARY_WIDTH + x
                for current_mask in masks
                for y in range(
                    current_mask.y,
                    current_mask.y + current_mask.height,
                )
                for x in range(
                    current_mask.x,
                    current_mask.x + current_mask.width,
                )
            }
            forced_color_indexes = {
                next(iter(replacement_colors)): (
                    expected_background_palette_index
                )
            }
        else:
            if expected_background_palette_index is not None:
                raise UiAtlasLocalizationError(
                    "background palette index requires fixed source elements"
                )
            forced_pixel_indexes = set()
            forced_color_indexes = {}
        if len(masks) == 1:
            original_delta = rgba_delta(
                original_rgba, localized_rgba, masks[0]
            )
            erased_delta = rgba_delta(
                erased_rgba, localized_rgba, masks[0]
            )
        else:
            original_delta = rgba_delta_in_masks(
                original_rgba, localized_rgba, masks
            )
            erased_delta = rgba_delta_in_masks(
                erased_rgba, localized_rgba, masks
            )
        added_pixel_count = sum(
            audit["added_pixel_count"] for audit in text_audits
        )
        indexed_rgba_unchanged_pixel_count = sum(
            localized_rgba[pixel_index * 4 : pixel_index * 4 + 4]
            == erased_rgba[pixel_index * 4 : pixel_index * 4 + 4]
            for pixel_index in forced_palette_indexes_by_pixel
        )
        if (
            erased_delta["changed_pixel_count"]
            + indexed_rgba_unchanged_pixel_count
            != added_pixel_count
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
            base_erased_rgba,
            localized_rgba,
            force_reindex_pixel_indexes=forced_pixel_indexes,
            forced_color_indexes=forced_color_indexes,
            forced_palette_indexes_by_pixel=(
                forced_palette_indexes_by_pixel
            ),
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
        if render_snapshot is None:
            write_deterministic_rgba8_png(
                magick,
                localized_rgba,
                localized_path,
                width=CANARY_WIDTH,
                height=CANARY_HEIGHT,
            )
            localized_png = localized_path.read_bytes()
        else:
            frozen_preview = render_snapshot.get("preview_png")
            if not isinstance(frozen_preview, Mapping) or not isinstance(
                frozen_preview.get("size"), int
            ):
                raise UiAtlasLocalizationError(
                    "localized atlas frozen preview is invalid"
                )
            localized_png = _thaw_bytes(
                frozen_preview,
                label="localized atlas preview PNG",
                expected_size=frozen_preview["size"],
            )
            localized_path.write_bytes(localized_png)
            frozen_preview_rgba = read_rgba8(
                magick,
                localized_path,
                expected_width=CANARY_WIDTH,
                expected_height=CANARY_HEIGHT,
            )
            if frozen_preview_rgba != localized_rgba:
                raise UiAtlasLocalizationError(
                    "localized atlas frozen preview pixels drift"
                )

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
    if live_render and render_snapshot_sink is not None:
        render_snapshot_sink.update(
            {
                "schema_version": 1,
                "status": "reviewed_locked",
                "selection_authority": "frozen_rendered_text_masks",
                "profile_id": config["profile_id"],
                "translation_source_sha256": translation_sha256,
                "font_sha256": font_sha256,
                "render_contract_sha256": render_contract_sha256,
                "base_reference_png_sha256": base_reference_png_sha256,
                "base_erased_png_sha256": base_erased_png_sha256,
                "imagemagick_version": version,
                "labels": [
                    {
                        "entry_id": spec["entry_id"],
                        "text_sha256": sha256_bytes(
                            spec["text"].encode("utf-8")
                        ),
                        "outline_mask": _frozen_bytes(current_mask),
                        "fill_mask": (
                            _frozen_bytes(fill_mask)
                            if fill_mask is not None
                            else None
                        ),
                    }
                    for spec, current_mask, fill_mask in zip(
                        label_specs,
                        grayscale_masks,
                        fill_masks,
                    )
                ],
                "preview_png": _frozen_bytes(localized_png),
            }
        )
    expected = {
        "text_mask": {
            "size": len(grayscale_masks[0]),
            "sha256": sha256_bytes(grayscale_masks[0]),
            "nonzero_pixel_count": sum(
                value != 0 for value in grayscale_masks[0]
            ),
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
        "added_pixel_count": added_pixel_count,
        "original_changed_pixel_count": original_delta[
            "changed_pixel_count"
        ],
        "original_changed_pixel_indexes_sha256": original_delta[
            "changed_pixel_indexes_sha256"
        ],
        "changed_archive_byte_count": archive_diff["diff_count"],
        "changed_archive_range_count": archive_diff["range_count"],
    }
    if len(label_specs) > 1:
        expected["additional_text_masks"] = [
            {
                "semantic_locator_sha256": sha256_bytes(
                    spec["semantic_locator"].encode("utf-8")
                ),
                "size": len(current_mask),
                "sha256": sha256_bytes(current_mask),
                "nonzero_pixel_count": sum(
                    value != 0 for value in current_mask
                ),
            }
            for spec, current_mask in zip(
                label_specs[1:], grayscale_masks[1:]
            )
        ]
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
                "flavor": font_flavor_metadata(font_flavor),
                "source": font_source_metadata(font_lock),
            },
            "translation_source": {
                "file": _file_lock(root, translation_path),
                "batch_id": translation_document.get("batch_id"),
                "entry_id": entry_id,
                "editorial_status": decision["editorial_status"],
                "source_ref_count": len(source_refs),
            },
            **(
                {
                    "render_snapshot": (
                        _file_lock(root, render_snapshot_path)
                        if render_snapshot_path is not None
                        else {
                            "source": "live_explicit_refreeze",
                            "render_contract_sha256": (
                                render_contract_sha256
                            ),
                        }
                    )
                }
                if live_render or render_snapshot_path is not None
                else {}
            ),
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
            **(
                {
                    "masks": [
                        spec["mask"].to_mapping() for spec in label_specs
                    ]
                }
                if len(label_specs) > 1
                else {}
            ),
            "mask_audit": original_delta,
            **(
                {
                    "force_reindex_entire_masks": True,
                    "expected_background_palette_index": (
                        expected_background_palette_index
                    ),
                    "forced_indexed_text_pixel_count": len(
                        forced_palette_indexes_by_pixel
                    ),
                    "indexed_rgba_unchanged_pixel_count": (
                        indexed_rgba_unchanged_pixel_count
                    ),
                }
                if force_reindex_entire_masks
                else {}
            ),
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
                **(
                    {"italic_shear_degrees": italic_shear_degrees}
                    if italic_shear_degrees
                    else {}
                ),
                **(
                    {"horizontal_offset": horizontal_offset}
                    if horizontal_offset
                    else {}
                ),
                "ramp_rgba": [color.hex() for color in ramp],
                **(
                    {
                        "indexed_layers": _indexed_layers_metadata(
                            label_specs[0]["indexed_layers"]
                        )
                    }
                    if label_specs[0]["indexed_layers"] is not None
                    else {}
                ),
                "text_mask": expected["text_mask"],
            },
        },
        **(
            {
                "additional_localized_labels": [
                    {
                        "source_locator_sha256": sha256_bytes(
                            spec["semantic_locator"].encode("utf-8")
                        ),
                        "text_sha256": sha256_bytes(
                            spec["text"].encode("utf-8")
                        ),
                        "character_count": len(spec["text"]),
                        "mask": spec["mask"].to_mapping(),
                        "render": {
                            "point_size": spec["point_size"],
                            "stroke_gray": spec["stroke_gray"],
                            "stroke_width": spec["stroke_width"],
                            "fill_stroke_width": spec[
                                "fill_stroke_width"
                            ],
                            **(
                                {
                                    "italic_shear_degrees": spec[
                                        "italic_shear_degrees"
                                    ]
                                }
                                if spec["italic_shear_degrees"]
                                else {}
                            ),
                            **(
                                {
                                    "horizontal_offset": spec[
                                        "horizontal_offset"
                                    ]
                                }
                                if spec["horizontal_offset"]
                                else {}
                            ),
                            "ramp_rgba": [
                                color.hex() for color in spec["ramp"]
                            ],
                            **(
                                {
                                    "indexed_layers": (
                                        _indexed_layers_metadata(
                                            spec["indexed_layers"]
                                        )
                                    )
                                }
                                if spec["indexed_layers"] is not None
                                else {}
                            ),
                            "text_mask": expected[
                                "additional_text_masks"
                            ][index],
                        },
                    }
                    for index, spec in enumerate(label_specs[1:])
                ]
            }
            if len(label_specs) > 1
            else {}
        ),
        "toolchain": {
            "imagemagick": version,
            **(
                {
                    "text_render_source": (
                        "live_explicit_refreeze"
                        if live_render
                        else "locked_snapshot"
                    )
                }
                if live_render or render_snapshot is not None
                else {}
            ),
        },
        "text_audit": (
            {
                **text_audits[0],
                "delta_from_erased": erased_delta,
                "delta_from_original": original_delta,
            }
            if len(label_specs) == 1
            else {
                "added_pixel_count": added_pixel_count,
                "label_count": len(label_specs),
                "labels": text_audits,
                **(
                    {"source_elements": source_element_audits}
                    if source_element_audits
                    else {}
                ),
                "outside_masks_rgba_exact": True,
                "erased_background_preimage_exact": True,
                "delta_from_erased": erased_delta,
                "delta_from_original": original_delta,
            }
        ),
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
            **(
                {"frozen_render_snapshot_consumed": True}
                if render_snapshot is not None
                else {}
            ),
            "ramp_uses_only_source_palette_rgba": True,
            "localized_pixels_within_mapping_mask": True,
            **(
                {"source_element_rectangles_and_rgba_locked": True}
                if fixed_source_elements
                else {}
            ),
            **(
                {"fixed_element_palette_indexes_rebuilt": True}
                if fixed_source_elements
                else {}
            ),
            **(
                {"mask_background_palette_index_rebuilt": True}
                if force_reindex_entire_masks and not fixed_source_elements
                else {}
            ),
            **(
                {"indexed_outline_and_fill_layers_rebuilt": True}
                if forced_palette_indexes_by_pixel
                else {}
            ),
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
    "rgba_delta_in_masks",
]
