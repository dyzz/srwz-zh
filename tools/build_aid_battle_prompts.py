#!/usr/bin/env python3
"""Build AIDDATA from its reviewed frozen indexed-texture snapshot.

Normal release builds never rasterize the ten battle labels. They inject the
exact reviewed compressed atlas slot into the hash-locked original member and
revalidate its indexed-palette, transparency, outline/fill, compression and
animation-stream contracts. ``--live-render`` is an explicit authoring-only
path retained for a future, separately reviewed revision.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Mapping

if __package__:
    from tools.srwz.codec import decode_production
    from tools.srwz.psmt4 import unswizzle_psmt4
    from tools.srwz.tim2 import parse_tim2
else:
    from srwz.codec import decode_production
    from srwz.psmt4 import unswizzle_psmt4
    from srwz.tim2 import parse_tim2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/assets/aid-battle-prompts-zh.json"
FROZEN_STATUS = "aid_battle_prompts_static_validated_runtime_pending"
SNAPSHOT_STATUS = "reviewed_locked"


class FrozenAidBattlePromptError(ValueError):
    """The reviewed AIDDATA snapshot or its source contract has drifted."""


def _path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise FrozenAidBattlePromptError("project path must be non-empty")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise FrozenAidBattlePromptError(f"path escapes project root: {raw}") from error
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lock(root: Path, path: Path, data: bytes | None = None) -> dict:
    payload = path.read_bytes() if data is None else data
    return {
        "path": str(path.resolve().relative_to(root.resolve())),
        "size": len(payload),
        "sha256": _sha256(payload),
    }


def _load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FrozenAidBattlePromptError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise FrozenAidBattlePromptError(f"JSON root must be an object: {path}")
    return value


def _validate_lock(path: Path, reference: Mapping, *, label: str) -> bytes:
    payload = path.read_bytes()
    if len(payload) != reference.get("size") or _sha256(payload) != reference.get("sha256"):
        raise FrozenAidBattlePromptError(f"{label} lock drift")
    return payload


def _snapshot_reference(root: Path, config: Mapping) -> tuple[Path, dict, bytes]:
    reference = config.get("frozen_snapshot")
    if not isinstance(reference, Mapping):
        raise FrozenAidBattlePromptError("AIDDATA frozen snapshot reference is missing")
    path = _path(root, reference.get("path"))
    payload = _validate_lock(path, reference, label="AIDDATA frozen snapshot")
    return path, _load_object(path), payload


def _thaw(raw: object, *, label: str, expected_size: int) -> bytes:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("zlib_base64"), str):
        raise FrozenAidBattlePromptError(f"{label} payload is missing")
    try:
        data = zlib.decompress(base64.b64decode(raw["zlib_base64"], validate=True))
    except (ValueError, zlib.error) as error:
        raise FrozenAidBattlePromptError(f"{label} payload cannot be decoded") from error
    if (
        len(data) != expected_size
        or raw.get("size") != len(data)
        or raw.get("sha256") != _sha256(data)
    ):
        raise FrozenAidBattlePromptError(f"{label} payload drift")
    return data


def _rect(raw: object) -> tuple[int, int, int, int]:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(not isinstance(value, int) or isinstance(value, bool) for value in raw)
    ):
        raise FrozenAidBattlePromptError("AIDDATA label rectangle is malformed")
    x, y, width, height = raw
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 256 or y + height > 256:
        raise FrozenAidBattlePromptError("AIDDATA label rectangle escapes the atlas")
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


def _atlas_view(slot: bytes, config: Mapping, *, encoded_size: int | None = None) -> dict:
    streams = config["streams"]
    tim2 = config["tim2"]
    encoded = slot if encoded_size is None else slot[:encoded_size]
    decoded = decode_production(encoded)
    if decoded.consumed != len(encoded) or len(decoded.output) != streams.get("atlas_decoded_size"):
        raise FrozenAidBattlePromptError("AIDDATA frozen atlas decode drift")
    record = parse_tim2(decoded.output, offset=tim2.get("offset"))
    if len(record.pictures) != 1:
        raise FrozenAidBattlePromptError("AIDDATA frozen TIM2 picture count drift")
    picture = record.pictures[0]
    if (
        picture.width != tim2.get("width")
        or picture.height != tim2.get("height")
        or picture.image_type != tim2.get("image_type")
        or picture.image_size != tim2.get("image_size")
        or picture.clut_color_count != tim2.get("clut_color_count")
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen TIM2 geometry drift")
    image_offset = picture.offset + picture.header_size
    image_end = image_offset + picture.image_size
    clut_end = image_end + picture.clut_size
    indexes = unswizzle_psmt4(
        decoded.output[image_offset:image_end], picture.width, picture.height
    )
    return {
        "decoded": decoded.output,
        "indexes": indexes,
        "clut": decoded.output[image_end:clut_end],
        "image_offset": image_offset,
        "image_end": image_end,
        "clut_end": clut_end,
    }


def _validate_frozen_atlas(
    source: bytes,
    output: bytes,
    config: Mapping,
    snapshot: Mapping,
) -> tuple[bytes, bytes]:
    if __package__:
        from tools.srwz.aid_battle_prompts import render_palette_montage
    else:
        from srwz.aid_battle_prompts import render_palette_montage

    streams = config["streams"]
    expected = config["expected"]
    slot_size = streams["atlas_slot_size"]
    encoded_size = expected["output_atlas_encoded_size"]
    source_view = _atlas_view(source[:slot_size], config)
    output_slot = output[:slot_size]
    if any(output_slot[encoded_size:]):
        raise FrozenAidBattlePromptError("AIDDATA frozen atlas padding drift")
    output_view = _atlas_view(output_slot, config, encoded_size=encoded_size)
    if (
        _sha256(source_view["decoded"]) != expected["source_atlas_decoded_sha256"]
        or _sha256(source_view["indexes"]) != expected["source_logical_indexes_sha256"]
        or _sha256(source_view["clut"]) != expected["source_clut_sha256"]
        or _sha256(output_view["decoded"]) != expected["output_atlas_decoded_sha256"]
        or _sha256(output_view["indexes"]) != expected["output_logical_indexes_sha256"]
        or _sha256(output_slot[:encoded_size]) != expected["output_atlas_encoded_sha256"]
        or source_view["clut"] != output_view["clut"]
        or source_view["decoded"][: source_view["image_offset"]]
        != output_view["decoded"][: output_view["image_offset"]]
        or source_view["decoded"][source_view["image_end"] :]
        != output_view["decoded"][output_view["image_end"] :]
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen indexed atlas contract drift")

    labels = config.get("labels")
    frozen_labels = snapshot.get("validation", {}).get("atlas", {}).get("labels")
    if not isinstance(labels, list) or not isinstance(frozen_labels, list) or len(labels) != len(frozen_labels):
        raise FrozenAidBattlePromptError("AIDDATA frozen label inventory drift")
    occupied: set[tuple[int, int]] = set()
    for spec, frozen in zip(labels, frozen_labels):
        if not isinstance(spec, Mapping) or not isinstance(frozen, Mapping):
            raise FrozenAidBattlePromptError("AIDDATA frozen label is malformed")
        rect = _rect(spec.get("rect"))
        if frozen.get("entry_id") != spec.get("entry_id") or frozen.get("rect") != list(rect):
            raise FrozenAidBattlePromptError("AIDDATA frozen label identity drift")
        source_rect = _rect_indexes(source_view["indexes"], rect)
        output_rect = _rect_indexes(output_view["indexes"], rect)
        if (
            _sha256(source_rect) != frozen.get("source_indexes_sha256")
            or _sha256(output_rect) != frozen.get("output_indexes_sha256")
            or not any(index in range(1, 8) for index in output_rect)
            or not any(index in range(8, 16) for index in output_rect)
        ):
            raise FrozenAidBattlePromptError("AIDDATA frozen label layer drift")
        x, y, width, height = rect
        occupied.update(
            (column, row)
            for row in range(y, y + height)
            for column in range(x, x + width)
        )
    changed = {
        (index % 256, index // 256)
        for index, pair in enumerate(zip(source_view["indexes"], output_view["indexes"]))
        if pair[0] != pair[1]
    }
    if not changed or not changed <= occupied:
        raise FrozenAidBattlePromptError("AIDDATA frozen pixel delta escaped target rectangles")

    clut = output_view["clut"]
    bank_count = config["tim2"]["palette_bank_count"]
    for bank in range(bank_count):
        if _palette_color(clut, bank, 0)[3] != 0:
            raise FrozenAidBattlePromptError("AIDDATA frozen background transparency drift")
        if any(_palette_color(clut, bank, index)[3] == 0 for index in range(1, 16)):
            raise FrozenAidBattlePromptError("AIDDATA frozen text-layer alpha drift")

    reference = render_palette_montage(source_view["indexes"], clut)
    localized = render_palette_montage(output_view["indexes"], clut)
    if (
        _sha256(reference) != expected["reference_preview_sha256"]
        or _sha256(localized) != expected["localized_preview_sha256"]
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen preview pixel drift")
    return reference, localized


def build_frozen_aid_battle_prompts(
    project_root: Path,
    config_path: Path,
) -> tuple[bytes, bytes, bytes, dict]:
    """Consume the reviewed snapshot without invoking any text renderer."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _load_object(config_path)
    if config.get("schema_version") != 1:
        raise FrozenAidBattlePromptError("unsupported AIDDATA config schema")
    if config.get("render_policy") != {
        "production_source": "frozen_snapshot",
        "normal_build_rasterization": False,
        "snapshot_update": "explicit_live_render_and_refreeze_only",
    }:
        raise FrozenAidBattlePromptError("AIDDATA frozen render policy drift")
    source_reference = config.get("source")
    streams = config.get("streams")
    expected = config.get("expected")
    corpus_reference = config.get("corpus")
    if not all(
        isinstance(value, Mapping)
        for value in (source_reference, streams, expected, corpus_reference)
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen source contract is incomplete")
    source_path = _path(root, source_reference.get("path"))
    source = _validate_lock(source_path, source_reference, label="original AIDDATA")
    snapshot_path, snapshot, snapshot_payload = _snapshot_reference(root, config)
    if (
        snapshot.get("schema_version") != 1
        or snapshot.get("status") != SNAPSHOT_STATUS
        or snapshot.get("profile_id") != config.get("profile_id")
        or snapshot.get("update_policy") != "explicit_refreeze_only"
        or snapshot.get("source_member_size") != len(source)
        or snapshot.get("source_member_sha256") != _sha256(source)
        or snapshot.get("expected") != expected
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen snapshot provenance drift")
    slot_size = streams.get("atlas_slot_size")
    animation_offset = streams.get("animation_offset")
    animation_size = streams.get("animation_size")
    if (
        not isinstance(slot_size, int)
        or animation_offset != slot_size
        or animation_offset + animation_size != len(source)
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen stream boundary drift")
    frozen_slot = _thaw(
        snapshot.get("frozen_atlas_slot"),
        label="AIDDATA frozen atlas slot",
        expected_size=slot_size,
    )
    output = frozen_slot + source[animation_offset:]
    if (
        len(output) != source_reference.get("size")
        or _sha256(output) != expected.get("output_member_sha256")
        or snapshot.get("output_member_size") != len(output)
        or snapshot.get("output_member_sha256") != _sha256(output)
        or _sha256(source[animation_offset:]) != expected.get("source_animation_sha256")
        or output[animation_offset:] != source[animation_offset:]
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen member or animation drift")
    reference, localized = _validate_frozen_atlas(source, output, config, snapshot)

    corpus_path = _path(root, corpus_reference.get("path"))
    corpus_payload = corpus_path.read_bytes()
    corpus = json.loads(corpus_payload.decode("utf-8"))
    entries = corpus.get("entries") if isinstance(corpus, dict) else None
    frozen_labels = snapshot.get("validation", {}).get("atlas", {}).get("labels")
    if not isinstance(entries, list) or not isinstance(frozen_labels, list):
        raise FrozenAidBattlePromptError("AIDDATA frozen translation inventory is malformed")
    translations = {
        item.get("id"): item.get("translation")
        for item in entries
        if isinstance(item, Mapping)
        and item.get("editorial_status") == corpus_reference.get("minimum_editorial_status")
    }
    if len(translations) != len(entries) or any(
        translations.get(item.get("entry_id")) != item.get("translation")
        for item in frozen_labels
    ):
        raise FrozenAidBattlePromptError("AIDDATA frozen translation inventory drift")

    validation = snapshot.get("validation")
    if not isinstance(validation, Mapping):
        raise FrozenAidBattlePromptError("AIDDATA frozen validation contract is missing")
    acceptance = deepcopy(validation.get("acceptance"))
    if not isinstance(acceptance, dict) or not all(acceptance.values()):
        raise FrozenAidBattlePromptError("AIDDATA frozen acceptance is incomplete")
    acceptance["frozen_render_snapshot_consumed"] = True
    component_path = _path(root, config["outputs"]["component_root"]) / str(source_reference.get("member"))
    atlas = deepcopy(validation["atlas"])
    atlas["frozen_render_snapshot_consumed"] = True
    report = {
        "schema_version": 1,
        "status": FROZEN_STATUS,
        "profile_id": config.get("profile_id"),
        "scope": config.get("scope"),
        "build_mode": "locked_indexed_snapshot",
        "inputs": {
            "config": _lock(root, config_path),
            "source": _lock(root, source_path, source),
            "corpus": _lock(root, corpus_path, corpus_payload),
            "frozen_snapshot": _lock(root, snapshot_path, snapshot_payload),
        },
        "render": {
            "source": "reviewed_locked_indexed_snapshot",
            "update_policy": "explicit_refreeze_only",
            "frozen_render_snapshot_consumed": True,
            "normal_build_rasterization": False,
            "authoring_provenance": deepcopy(snapshot.get("authoring_provenance")),
        },
        "atlas": atlas,
        "compression": deepcopy(validation["compression"]),
        "animation_stream": deepcopy(validation["animation_stream"]),
        "expected": deepcopy(expected),
        "output_diff": deepcopy(validation["output_diff"]),
        "outputs": {
            source_reference.get("member"): {
                "path": str(component_path.relative_to(root)),
                "size": len(output),
                "sha256": _sha256(output),
            }
        },
        "acceptance": acceptance,
        "runtime": deepcopy(validation["runtime"]),
    }
    return output, reference, localized, report


def _snapshot_from_reviewed_payload(config: Mapping, payload: bytes, report: Mapping) -> dict:
    slot_size = config["streams"]["atlas_slot_size"]
    slot = payload[:slot_size]
    return {
        "schema_version": 1,
        "status": SNAPSHOT_STATUS,
        "profile_id": config.get("profile_id"),
        "update_policy": "explicit_refreeze_only",
        "source_member_size": config["source"]["size"],
        "source_member_sha256": config["source"]["sha256"],
        "frozen_atlas_slot": {
            "offset": 0,
            "size": len(slot),
            "sha256": _sha256(slot),
            "zlib_base64": base64.b64encode(zlib.compress(slot, 9)).decode("ascii"),
        },
        "output_member_size": len(payload),
        "output_member_sha256": _sha256(payload),
        "expected": deepcopy(config["expected"]),
        "authoring_provenance": {
            "font": deepcopy(report.get("font")),
            "toolchain": deepcopy(report.get("toolchain")),
        },
        "validation": {
            key: deepcopy(report[key])
            for key in (
                "atlas",
                "compression",
                "animation_stream",
                "output_diff",
                "acceptance",
                "runtime",
            )
        },
    }


def _write_json(path: Path, value: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_outputs(
    config: Mapping,
    payload: bytes,
    reference: bytes,
    localized: bytes,
    report: Mapping,
    *,
    refresh_manifest: bool | None,
    write_previews: bool,
) -> None:
    outputs = config["outputs"]
    component_path = _path(PROJECT_ROOT, outputs["component_root"]) / str(config["source"]["member"])
    component_path.parent.mkdir(parents=True, exist_ok=True)
    component_path.write_bytes(payload)
    if write_previews:
        if __package__:
            from tools.srwz.imagemagick import (
                require_imagemagick,
                write_deterministic_rgba8_png,
            )
        else:
            from srwz.imagemagick import (
                require_imagemagick,
                write_deterministic_rgba8_png,
            )
        magick = require_imagemagick()
        for raw_path, pixels in (
            (outputs["reference_png"], reference),
            (outputs["localized_png"], localized),
        ):
            path = _path(PROJECT_ROOT, raw_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_deterministic_rgba8_png(
                magick,
                pixels,
                path,
                width=512,
                height=1024,
            )
    report_path = _path(PROJECT_ROOT, outputs["report"])
    _write_json(report_path, report)
    manifest_path = _path(PROJECT_ROOT, outputs["manifest"])
    if refresh_manifest is True:
        _write_json(manifest_path, report)
    elif refresh_manifest is False and (
        not manifest_path.is_file() or _load_object(manifest_path) != report
    ):
        raise FrozenAidBattlePromptError(
            "AIDDATA manifest drift; review the report and rerun with --refresh-manifest"
        )


def _run_live_render(args: argparse.Namespace, config_path: Path, config: dict) -> int:
    if __package__:
        from tools.srwz.aid_battle_prompts import (
            AidBattlePromptError,
            build_aid_battle_prompts,
        )
    else:
        from srwz.aid_battle_prompts import (
            AidBattlePromptError,
            build_aid_battle_prompts,
        )

    try:
        payload, reference, localized, report = build_aid_battle_prompts(
            PROJECT_ROOT,
            config_path,
            enforce_expected=not args.no_enforce_expected,
        )
    except (AidBattlePromptError, OSError, KeyError, ValueError) as error:
        raise SystemExit(f"AIDDATA live render failed: {error}") from error
    _write_outputs(
        config,
        payload,
        reference,
        localized,
        report,
        refresh_manifest=None,
        write_previews=True,
    )
    if args.refreeze_snapshot:
        snapshot_reference = config.get("frozen_snapshot")
        if not isinstance(snapshot_reference, Mapping):
            raise SystemExit("AIDDATA frozen snapshot reference is missing")
        snapshot_path = _path(PROJECT_ROOT, snapshot_reference.get("path"))
        _write_json(snapshot_path, _snapshot_from_reviewed_payload(config, payload, report))
        print(json.dumps(_lock(PROJECT_ROOT, snapshot_path), indent=2))
    print(
        "AID battle prompts live render:",
        f"labels={len(report['atlas']['labels'])}",
        f"member_sha256={_sha256(payload)}",
        "promotion=explicit-refreeze-only",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--live-render",
        action="store_true",
        help="authoring only: rerasterize text instead of consuming the snapshot",
    )
    parser.add_argument("--no-enforce-expected", action="store_true")
    parser.add_argument(
        "--refreeze-snapshot",
        action="store_true",
        help="with --live-render, replace the reviewed snapshot explicitly",
    )
    args = parser.parse_args()
    if args.no_enforce_expected and not args.live_render:
        raise SystemExit("--no-enforce-expected requires --live-render")
    if args.refreeze_snapshot and not args.live_render:
        raise SystemExit("--refreeze-snapshot requires --live-render")
    if args.refresh_manifest and args.live_render:
        raise SystemExit(
            "the release manifest records the frozen build; rerun without "
            "--live-render after reviewing/refreezing"
        )

    config_path = args.config.resolve()
    config = _load_object(config_path)
    outputs = config["outputs"]
    component_path = _path(PROJECT_ROOT, outputs["component_root"]) / str(config["source"]["member"])
    report_path = _path(PROJECT_ROOT, outputs["report"])
    if (component_path.exists() or report_path.exists()) and not args.force:
        raise SystemExit("AID battle-prompt output exists; use --force")
    if args.live_render:
        return _run_live_render(args, config_path, config)
    try:
        payload, reference, localized, report = build_frozen_aid_battle_prompts(
            PROJECT_ROOT,
            config_path,
        )
        _write_outputs(
            config,
            payload,
            reference,
            localized,
            report,
            refresh_manifest=args.refresh_manifest,
            write_previews=False,
        )
    except (FrozenAidBattlePromptError, OSError, KeyError, ValueError) as error:
        raise SystemExit(f"AIDDATA frozen build failed: {error}") from error
    print(
        "AID battle prompts frozen:",
        f"labels={len(report['atlas']['labels'])}",
        f"changed_pixels={report['atlas']['changed_logical_pixel_count']}",
        f"encoded={report['atlas']['output_encoded_size']}/{report['atlas']['stored_slot_size']}",
        "rasterization=disabled",
        "runtime=pending",
    )
    print(f"component: {next(iter(report['outputs'].values()))['path']}")
    print(f"report: {outputs['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
