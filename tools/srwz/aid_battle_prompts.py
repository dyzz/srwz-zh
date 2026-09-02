"""Deterministic indexed localization for AIDDATA battle prompts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Mapping

from .codec import decode_production, reencode_changed_suffix
from .patch_audit import sha256_bytes, summarize_diff
from .psmt4 import swizzle_psmt4, unswizzle_psmt4
from .tim2 import parse_tim2


class AidBattlePromptError(ValueError):
    """The AIDDATA input or localized output violates its locked contract."""


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AidBattlePromptError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise AidBattlePromptError(f"JSON root must be an object: {path}")
    return value


def _path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise AidBattlePromptError("project path must be non-empty")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise AidBattlePromptError(f"path escapes project root: {raw}") from error
    return path


def _lock(root: Path, path: Path, data: bytes | None = None) -> dict:
    payload = path.read_bytes() if data is None else data
    return {
        "path": str(path.resolve().relative_to(root.resolve())),
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _rect(raw: object) -> tuple[int, int, int, int]:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(not isinstance(value, int) or isinstance(value, bool) for value in raw)
    ):
        raise AidBattlePromptError("label rectangle must contain four integers")
    x, y, width, height = raw
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 256 or y + height > 256:
        raise AidBattlePromptError(f"label rectangle is outside the atlas: {raw}")
    return x, y, width, height


def _rect_indexes(indexes: bytes, rect: tuple[int, int, int, int]) -> bytes:
    x, y, width, height = rect
    return b"".join(
        indexes[row * 256 + x : row * 256 + x + width]
        for row in range(y, y + height)
    )


def _csm1_offset(index: int) -> int:
    return (index & 0xE7) | ((index & 0x08) << 1) | ((index & 0x10) >> 1)


def _palette_color(clut: bytes, bank: int, index: int) -> bytes:
    offset = _csm1_offset(bank * 16 + index) * 4
    return clut[offset : offset + 4]


def _render_bank(indexes: bytes, clut: bytes, bank: int) -> bytes:
    output = bytearray(256 * 256 * 4)
    for pixel, index in enumerate(indexes):
        color = _palette_color(clut, bank, index)
        alpha = min(255, color[3] * 2)
        x = pixel % 256
        y = pixel // 256
        background = 48 if ((x // 8 + y // 8) & 1) == 0 else 64
        target = pixel * 4
        output[target : target + 4] = bytes(
            (
                (color[0] * alpha + background * (255 - alpha) + 127) // 255,
                (color[1] * alpha + background * (255 - alpha) + 127) // 255,
                (color[2] * alpha + background * (255 - alpha) + 127) // 255,
                255,
            )
        )
    return bytes(output)


def render_palette_montage(indexes: bytes, clut: bytes) -> bytes:
    """Return a 2x4 preview of all eight runtime palette banks."""

    output = bytearray(512 * 1024 * 4)
    for bank in range(8):
        panel = _render_bank(indexes, clut, bank)
        x_offset = (bank % 2) * 256
        y_offset = (bank // 2) * 256
        for y in range(256):
            source = y * 256 * 4
            target = ((y_offset + y) * 512 + x_offset) * 4
            output[target : target + 256 * 4] = panel[source : source + 256 * 4]
    return bytes(output)


def _apply_label(
    indexes: bytearray,
    *,
    rect: tuple[int, int, int, int],
    outline_mask: bytes,
    fill_mask: bytes,
    outline_indexes: tuple[int, ...],
    fill_indexes: tuple[int, ...],
    background_index: int,
) -> dict:
    x, y, width, height = rect
    expected_size = width * height
    if len(outline_mask) != expected_size or len(fill_mask) != expected_size:
        raise AidBattlePromptError("render mask geometry drift")
    outline_only = [
        value for offset, value in enumerate(outline_mask)
        if value and not fill_mask[offset]
    ]
    visible_fill = [value for value in fill_mask if value]
    if not outline_only or not visible_fill:
        raise AidBattlePromptError("label requires non-empty outline and fill layers")

    for row in range(y, y + height):
        indexes[row * 256 + x : row * 256 + x + width] = bytes(
            [background_index]
        ) * width

    outline_max = max(outline_only)
    fill_max = max(visible_fill)
    counts = {"outline": Counter(), "fill": Counter()}
    for local_y in range(height):
        for local_x in range(width):
            local = local_y * width + local_x
            fill = fill_mask[local]
            outline = outline_mask[local]
            if fill:
                ramp = fill_indexes
                coverage = fill
                maximum = fill_max
                layer = "fill"
            elif outline:
                ramp = outline_indexes
                coverage = outline
                maximum = outline_max
                layer = "outline"
            else:
                continue
            ramp_offset = (coverage * (len(ramp) - 1) + maximum // 2) // maximum
            palette_index = ramp[min(ramp_offset, len(ramp) - 1)]
            indexes[(y + local_y) * 256 + x + local_x] = palette_index
            counts[layer][palette_index] += 1
    return {
        "outline_mask_sha256": sha256_bytes(outline_mask),
        "outline_mask_nonzero_pixel_count": sum(value > 0 for value in outline_mask),
        "outline_only_pixel_count": len(outline_only),
        "fill_mask_sha256": sha256_bytes(fill_mask),
        "fill_mask_nonzero_pixel_count": len(visible_fill),
        "indexed_layer_counts": {
            layer: {str(index): count for index, count in sorted(layer_counts.items())}
            for layer, layer_counts in counts.items()
        },
    }


def build_aid_battle_prompts(
    project_root: Path,
    config_path: Path,
    *,
    enforce_expected: bool = True,
) -> tuple[bytes, bytes, bytes, dict]:
    """Authoring-only live renderer for explicitly refreezing the atlas."""

    from .font_flavor import (
        font_flavor_metadata,
        load_font_flavor_reference,
        verify_font_flavor_files,
    )
    from .imagemagick import (
        imagemagick_version,
        render_grayscale_text_mask,
        require_imagemagick,
    )

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json(config_path)
    if config.get("schema_version") != 1:
        raise AidBattlePromptError("unsupported AID battle-prompt schema")

    source_ref = config.get("source")
    streams = config.get("streams")
    tim2_contract = config.get("tim2")
    render = config.get("render")
    compression = config.get("compression")
    if not all(isinstance(value, Mapping) for value in (source_ref, streams, tim2_contract, render, compression)):
        raise AidBattlePromptError("AID battle-prompt config is incomplete")
    source_path = _path(root, source_ref.get("path"))
    source = source_path.read_bytes()
    if len(source) != source_ref.get("size") or sha256_bytes(source) != source_ref.get("sha256"):
        raise AidBattlePromptError("original AIDDATA source drift")

    atlas_offset = streams.get("atlas_offset")
    slot_size = streams.get("atlas_slot_size")
    animation_offset = streams.get("animation_offset")
    animation_size = streams.get("animation_size")
    if atlas_offset != 0 or animation_offset != slot_size or animation_offset + animation_size != len(source):
        raise AidBattlePromptError("AIDDATA stream boundary drift")
    stored_atlas = source[:slot_size]
    animation = source[animation_offset:]
    decoded = decode_production(stored_atlas)
    if decoded.consumed != slot_size or len(decoded.output) != streams.get("atlas_decoded_size"):
        raise AidBattlePromptError("AIDDATA atlas stream decode drift")

    record = parse_tim2(decoded.output, offset=tim2_contract.get("offset"))
    if len(record.pictures) != 1:
        raise AidBattlePromptError("AIDDATA TIM2 picture count drift")
    picture = record.pictures[0]
    if (
        picture.width != tim2_contract.get("width")
        or picture.height != tim2_contract.get("height")
        or picture.image_type != tim2_contract.get("image_type")
        or picture.image_size != tim2_contract.get("image_size")
        or picture.clut_color_count != tim2_contract.get("clut_color_count")
    ):
        raise AidBattlePromptError("AIDDATA TIM2 layout drift")
    image_offset = picture.offset + picture.header_size
    image_end = image_offset + picture.image_size
    clut_end = image_end + picture.clut_size
    original_indexes = unswizzle_psmt4(
        decoded.output[image_offset:image_end], picture.width, picture.height
    )
    clut = decoded.output[image_end:clut_end]
    bank_count = picture.clut_color_count // 16
    if bank_count != tim2_contract.get("palette_bank_count"):
        raise AidBattlePromptError("AIDDATA palette bank count drift")
    background_index = tim2_contract.get("background_index")
    outline_indexes = tuple(tim2_contract.get("outline_indexes", []))
    fill_indexes = tuple(tim2_contract.get("fill_indexes", []))
    if background_index != 0 or outline_indexes != tuple(range(1, 8)) or fill_indexes != tuple(range(8, 16)):
        raise AidBattlePromptError("AIDDATA semantic palette-index contract drift")

    palette_audit = []
    for bank in range(bank_count):
        colors = [_palette_color(clut, bank, index) for index in range(16)]
        if colors[background_index][3] != 0:
            raise AidBattlePromptError(f"palette bank {bank} background is not transparent")
        if any(colors[index][3] == 0 for index in (*outline_indexes, *fill_indexes)):
            raise AidBattlePromptError(f"palette bank {bank} text layer is transparent")
        palette_audit.append(
            {
                "bank": bank,
                "background_rgba": colors[0].hex(),
                "outline_alpha_values": sorted({colors[index][3] for index in outline_indexes}),
                "fill_alpha_values": sorted({colors[index][3] for index in fill_indexes}),
            }
        )

    corpus_ref = config.get("corpus")
    if not isinstance(corpus_ref, Mapping):
        raise AidBattlePromptError("AIDDATA corpus reference is missing")
    corpus_path = _path(root, corpus_ref.get("path"))
    corpus_data = corpus_path.read_bytes()
    corpus = json.loads(corpus_data.decode("utf-8"))
    entries = corpus.get("entries") if isinstance(corpus, dict) else None
    if not isinstance(entries, list):
        raise AidBattlePromptError("AIDDATA corpus entries are invalid")
    entries_by_id = {
        item.get("id"): item for item in entries if isinstance(item, Mapping)
    }
    if len(entries_by_id) != len(entries):
        raise AidBattlePromptError("AIDDATA corpus entry IDs are not unique")

    flavor = load_font_flavor_reference(root, config.get("font_flavor"))
    _font_lock, font_files, _fallback_paths, fallback_reports = verify_font_flavor_files(
        root, root / "work", flavor
    )
    font_path = font_files["font"]
    magick = require_imagemagick()
    labels = config.get("labels")
    if not isinstance(labels, list) or len(labels) != len(entries):
        raise AidBattlePromptError("AIDDATA label inventory is incomplete")

    occupied: set[tuple[int, int]] = set()
    edited_indexes = bytearray(original_indexes)
    label_reports = []
    for spec in labels:
        if not isinstance(spec, Mapping):
            raise AidBattlePromptError("AIDDATA label spec is invalid")
        entry_id = spec.get("entry_id")
        entry = entries_by_id.get(entry_id)
        if (
            not isinstance(entry, Mapping)
            or entry.get("editorial_status") != corpus_ref.get("minimum_editorial_status")
        ):
            raise AidBattlePromptError(f"AIDDATA translation is not reviewed: {entry_id}")
        text = entry.get("translation")
        if not isinstance(text, str) or not text or "\n" in text or "\r" in text:
            raise AidBattlePromptError(f"AIDDATA translation is invalid: {entry_id}")
        rect = _rect(spec.get("rect"))
        x, y, width, height = rect
        pixels = {(xx, yy) for yy in range(y, y + height) for xx in range(x, x + width)}
        if occupied & pixels:
            raise AidBattlePromptError(f"AIDDATA label rectangles overlap: {entry_id}")
        occupied.update(pixels)
        point_size = spec.get("point_size", render.get("point_size"))
        common = {
            "width": width,
            "height": height,
            "point_size": point_size,
            "italic_shear_degrees": 0,
            "supersample_factor": render.get("supersample_factor"),
            "vertical_offset": render.get("vertical_offset", 0),
        }
        outline_mask = render_grayscale_text_mask(
            magick,
            font_path,
            text,
            stroke_gray="white",
            stroke_width=float(render.get("stroke_width")),
            fill_stroke_width=0,
            **common,
        )
        fill_mask = render_grayscale_text_mask(
            magick,
            font_path,
            text,
            stroke_gray="black",
            stroke_width=0,
            fill_stroke_width=0,
            **common,
        )
        source_rect = _rect_indexes(original_indexes, rect)
        layer_report = _apply_label(
            edited_indexes,
            rect=rect,
            outline_mask=outline_mask,
            fill_mask=fill_mask,
            outline_indexes=outline_indexes,
            fill_indexes=fill_indexes,
            background_index=background_index,
        )
        output_rect = _rect_indexes(bytes(edited_indexes), rect)
        label_reports.append(
            {
                "entry_id": entry_id,
                "source_text": entry.get("source_text"),
                "translation": text,
                "rect": list(rect),
                "point_size": point_size,
                "source_indexes_sha256": sha256_bytes(source_rect),
                "source_index_counts": {str(index): count for index, count in sorted(Counter(source_rect).items())},
                "output_indexes_sha256": sha256_bytes(output_rect),
                "output_index_counts": {str(index): count for index, count in sorted(Counter(output_rect).items())},
                **layer_report,
            }
        )

    edited = bytes(edited_indexes)
    changed_pixels = [index for index, pair in enumerate(zip(original_indexes, edited)) if pair[0] != pair[1]]
    if not changed_pixels or any((index % 256, index // 256) not in occupied for index in changed_pixels):
        raise AidBattlePromptError("AIDDATA logical index delta escaped target rectangles")
    outside_before = bytes(
        value for index, value in enumerate(original_indexes)
        if (index % 256, index // 256) not in occupied
    )
    outside_after = bytes(
        value for index, value in enumerate(edited)
        if (index % 256, index // 256) not in occupied
    )
    if outside_before != outside_after:
        raise AidBattlePromptError("AIDDATA non-target logical indexes changed")

    rebuilt_decoded = bytearray(decoded.output)
    rebuilt_decoded[image_offset:image_end] = swizzle_psmt4(edited, 256, 256)
    if (
        rebuilt_decoded[:image_offset] != decoded.output[:image_offset]
        or rebuilt_decoded[image_end:] != decoded.output[image_end:]
        or bytes(rebuilt_decoded[image_end:clut_end]) != clut
    ):
        raise AidBattlePromptError("AIDDATA TIM2 metadata or palette changed")
    rebuilt_encoded = reencode_changed_suffix(
        stored_atlas,
        bytes(rebuilt_decoded),
        strategy=compression.get("strategy"),
        min_match_length=compression.get("min_match_length"),
        max_match_chain=compression.get("max_match_chain"),
        lazy_matching=compression.get("lazy_matching"),
        max_output_size=slot_size,
        original_result=decoded,
    )
    reread = decode_production(rebuilt_encoded)
    if reread.consumed != len(rebuilt_encoded) or reread.output != bytes(rebuilt_decoded):
        raise AidBattlePromptError("AIDDATA compressed atlas round-trip failed")
    padding_byte = compression.get("padding_byte")
    if not isinstance(padding_byte, int) or not 0 <= padding_byte <= 255:
        raise AidBattlePromptError("AIDDATA padding byte is invalid")
    output = rebuilt_encoded + bytes([padding_byte]) * (slot_size - len(rebuilt_encoded)) + animation
    if len(output) != len(source) or output[animation_offset:] != animation:
        raise AidBattlePromptError("AIDDATA member size or animation stream changed")

    reference_preview = render_palette_montage(original_indexes, clut)
    localized_preview = render_palette_montage(edited, clut)
    expected = config.get("expected", {})
    actual_expected = {
        "source_atlas_decoded_sha256": sha256_bytes(decoded.output),
        "source_animation_sha256": sha256_bytes(animation),
        "source_logical_indexes_sha256": sha256_bytes(original_indexes),
        "source_clut_sha256": sha256_bytes(clut),
        "label_preimages": {item["entry_id"]: item["source_indexes_sha256"] for item in label_reports},
        "render_masks": {
            item["entry_id"]: {
                "outline": item["outline_mask_sha256"],
                "fill": item["fill_mask_sha256"],
            }
            for item in label_reports
        },
        "output_logical_indexes_sha256": sha256_bytes(edited),
        "output_atlas_decoded_sha256": sha256_bytes(bytes(rebuilt_decoded)),
        "output_atlas_encoded_size": len(rebuilt_encoded),
        "output_atlas_encoded_sha256": sha256_bytes(rebuilt_encoded),
        "output_member_sha256": sha256_bytes(output),
        "reference_preview_sha256": sha256_bytes(reference_preview),
        "localized_preview_sha256": sha256_bytes(localized_preview),
    }
    if enforce_expected and expected != actual_expected:
        raise AidBattlePromptError("AIDDATA frozen expected values drift")

    report = {
        "schema_version": 1,
        "status": "aid_battle_prompts_static_validated_runtime_pending",
        "profile_id": config.get("profile_id"),
        "scope": config.get("scope"),
        "inputs": {
            "config": _lock(root, config_path),
            "source": _lock(root, source_path, source),
            "corpus": _lock(root, corpus_path, corpus_data),
            "font_flavor": _lock(root, root / flavor["path"]),
            "font_file": _lock(root, font_path),
        },
        "font": font_flavor_metadata(flavor),
        "atlas": {
            "stored_slot_size": slot_size,
            "source_encoded_size": decoded.consumed,
            "output_encoded_size": len(rebuilt_encoded),
            "padding_size": slot_size - len(rebuilt_encoded),
            "decoded_size": len(decoded.output),
            "tim2_offset": record.offset,
            "tim2_size": record.size,
            "image_offset": image_offset,
            "image_size": picture.image_size,
            "clut_size": picture.clut_size,
            "palette_bank_count": bank_count,
            "palette_audit": palette_audit,
            "labels": label_reports,
            "changed_logical_pixel_count": len(changed_pixels),
            "changed_logical_pixel_indexes_sha256": sha256_bytes(b"".join(index.to_bytes(4, "little") for index in changed_pixels)),
            "non_target_logical_indexes_sha256": sha256_bytes(outside_before),
            "non_target_logical_indexes_preserved_byte_exact": True,
            "tim2_metadata_preserved_byte_exact": True,
            "clut_preserved_byte_exact": True,
            "background_transparent_in_all_palette_banks": True,
            "outline_and_fill_nontransparent_in_all_palette_banks": True,
        },
        "compression": {
            "strategy": compression.get("strategy"),
            "backend": "rust-only",
            "round_trip_exact": True,
            "fixed_slot_preserved": True,
        },
        "animation_stream": {
            "offset": animation_offset,
            "size": len(animation),
            "sha256": sha256_bytes(animation),
            "preserved_byte_exact": True,
        },
        "toolchain": {
            "imagemagick": imagemagick_version(magick),
            "font_fallbacks": list(fallback_reports),
        },
        "expected": actual_expected,
        "output_diff": summarize_diff(source, output).to_mapping(),
        "outputs": {
            source_ref.get("member"): {
                "path": str((_path(root, config["outputs"]["component_root"]) / source_ref.get("member")).relative_to(root)),
                "size": len(output),
                "sha256": sha256_bytes(output),
            }
        },
        "acceptance": {
            "reviewed_translation_inventory_complete": len(label_reports) == len(entries) == 10,
            "latin_digits_and_symbols_preserved_via_non_target_indexes": True,
            "indexed_outline_and_fill_layers_present": all(item["outline_only_pixel_count"] > 0 and item["fill_mask_nonzero_pixel_count"] > 0 for item in label_reports),
            "palette_and_alpha_preserved": True,
            "atlas_round_trip_exact": True,
            "animation_stream_preserved_byte_exact": True,
            "member_size_preserved": len(output) == len(source),
        },
        "runtime": {
            "status": "not_tested",
            "reason": "Static indexed-texture and compressed-member proof only; exact-ISO PCSX2 battle-flow evidence remains pending.",
        },
    }
    if not all(report["acceptance"].values()):
        raise AidBattlePromptError("AIDDATA component acceptance failed")
    return output, reference_preview, localized_preview, report


__all__ = [
    "AidBattlePromptError",
    "build_aid_battle_prompts",
    "render_palette_montage",
]
