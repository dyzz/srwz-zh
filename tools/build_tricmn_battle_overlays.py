#!/usr/bin/env python3
"""Build TRICMN from its reviewed frozen indexed-texture snapshot.

Normal release builds do not rasterize text. They inject the three locked
PSMT4 image ranges into the hash-locked original member and verify the exact
reviewed output. ``--live-render`` is an explicit authoring-only path retained
for future revisions.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import zlib
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/assets/tricmn-battle-overlays-zh.json"
FROZEN_STATUS = "tricmn_battle_overlay_frozen_runtime_validated"
SNAPSHOT_STATUS = "reviewed_locked"


class FrozenTricmnError(ValueError):
    """The reviewed TRICMN snapshot or its source contract has drifted."""


def _path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise FrozenTricmnError("project path must be a non-empty string")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise FrozenTricmnError(f"path escapes project root: {raw}") from error
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
        raise FrozenTricmnError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise FrozenTricmnError(f"JSON root must be an object: {path}")
    return value


def _validate_lock(path: Path, reference: Mapping, *, label: str) -> bytes:
    payload = path.read_bytes()
    if (
        len(payload) != reference.get("size")
        or _sha256(payload) != reference.get("sha256")
    ):
        raise FrozenTricmnError(f"{label} lock drift")
    return payload


def _snapshot_reference(root: Path, config: Mapping) -> tuple[Path, dict, bytes]:
    reference = config.get("frozen_snapshot")
    if not isinstance(reference, Mapping):
        raise FrozenTricmnError("TRICMN frozen snapshot reference is missing")
    path = _path(root, reference.get("path"))
    payload = path.read_bytes()
    if "size" in reference or "sha256" in reference:
        if (
            len(payload) != reference.get("size")
            or _sha256(payload) != reference.get("sha256")
        ):
            raise FrozenTricmnError("TRICMN frozen snapshot lock drift")
    snapshot = _load_object(path)
    return path, snapshot, payload


def _frozen_component(
    root: Path,
    config_path: Path,
) -> tuple[bytes, dict]:
    config = _load_object(config_path)
    source_reference = config.get("source")
    seg_reference = config.get("seg")
    tim2 = config.get("tim2")
    expected = config.get("expected")
    if not all(
        isinstance(value, Mapping)
        for value in (source_reference, seg_reference, tim2, expected)
    ):
        raise FrozenTricmnError("TRICMN source contract is incomplete")

    source_path = _path(root, source_reference.get("path"))
    source = _validate_lock(source_path, source_reference, label="TRICMN source")
    seg_path = _path(root, seg_reference.get("path"))
    seg = _validate_lock(seg_path, seg_reference, label="TRICMN SEG")
    snapshot_path, snapshot, snapshot_payload = _snapshot_reference(root, config)
    if (
        snapshot.get("schema_version") != 1
        or snapshot.get("status") != SNAPSHOT_STATUS
        or snapshot.get("profile_id") != config.get("profile_id")
        or snapshot.get("update_policy") != "explicit_refreeze_only"
        or snapshot.get("source_member_sha256") != _sha256(source)
        or snapshot.get("source_member_size") != len(source)
    ):
        raise FrozenTricmnError("TRICMN frozen snapshot provenance drift")

    pictures = tim2.get("pictures")
    ranges = snapshot.get("frozen_image_ranges")
    if (
        not isinstance(pictures, list)
        or len(pictures) != 4
        or not isinstance(ranges, list)
        or len(ranges) != 3
    ):
        raise FrozenTricmnError("TRICMN frozen image range inventory is malformed")

    output = bytearray(source)
    seen_picture_indexes: set[int] = set()
    for item in ranges:
        if not isinstance(item, Mapping):
            raise FrozenTricmnError("TRICMN frozen image range is malformed")
        picture_index = item.get("picture_index")
        if (
            not isinstance(picture_index, int)
            or isinstance(picture_index, bool)
            or picture_index not in (0, 1, 2)
            or picture_index in seen_picture_indexes
        ):
            raise FrozenTricmnError("TRICMN frozen picture ownership is invalid")
        seen_picture_indexes.add(picture_index)
        picture = pictures[picture_index]
        if not isinstance(picture, Mapping):
            raise FrozenTricmnError("TRICMN picture contract is malformed")
        offset = item.get("offset")
        size = item.get("size")
        if (
            offset != picture.get("image_offset")
            or size != picture.get("image_size")
            or not isinstance(offset, int)
            or not isinstance(size, int)
            or offset < 0
            or size <= 0
            or offset + size > len(output)
        ):
            raise FrozenTricmnError("TRICMN frozen image geometry drift")
        encoded = item.get("zlib_base64")
        if not isinstance(encoded, str):
            raise FrozenTricmnError("TRICMN frozen image payload is missing")
        try:
            raw = zlib.decompress(base64.b64decode(encoded, validate=True))
        except (ValueError, zlib.error) as error:
            raise FrozenTricmnError(
                "TRICMN frozen image payload cannot be decoded"
            ) from error
        if len(raw) != size or _sha256(raw) != item.get("sha256"):
            raise FrozenTricmnError("TRICMN frozen image payload drift")
        output[offset : offset + size] = raw

    if seen_picture_indexes != {0, 1, 2}:
        raise FrozenTricmnError("TRICMN frozen snapshot misses a localized picture")
    payload = bytes(output)
    expected_member_sha256 = expected.get("output_member_sha256")
    if (
        len(payload) != source_reference.get("size")
        or _sha256(payload) != expected_member_sha256
        or snapshot.get("output_member_sha256") != expected_member_sha256
        or snapshot.get("output_member_size") != len(payload)
    ):
        raise FrozenTricmnError("TRICMN frozen output member drift")

    output_picture_hashes = snapshot.get("output_picture_indexes_sha256")
    if output_picture_hashes != expected.get("output_picture_indexes_sha256"):
        raise FrozenTricmnError("TRICMN frozen logical picture hash drift")
    corpus_reference = config.get("corpus")
    if not isinstance(corpus_reference, Mapping):
        raise FrozenTricmnError("TRICMN corpus reference is missing")
    corpus_path = _path(root, corpus_reference.get("path"))
    corpus = corpus_path.read_bytes()
    labels = config.get("labels")
    inventory = config.get("atlas_inventory")
    if not isinstance(labels, list) or not isinstance(inventory, list):
        raise FrozenTricmnError("TRICMN atlas inventory is malformed")

    component_root = _path(root, config["outputs"]["component_root"])
    component_path = component_root / str(source_reference.get("member"))
    report = {
        "schema_version": 1,
        "status": FROZEN_STATUS,
        "profile_id": config.get("profile_id"),
        "scope": config.get("scope"),
        "build_mode": "locked_indexed_snapshot",
        "inputs": {
            "config": _lock(root, config_path),
            "source_bin": _lock(root, source_path, source),
            "source_seg": _lock(root, seg_path, seg),
            "corpus": _lock(root, corpus_path, corpus),
            "frozen_snapshot": _lock(root, snapshot_path, snapshot_payload),
        },
        "seg": {
            "size": len(seg),
            "sha256": _sha256(seg),
            "offsets": list(seg_reference.get("offsets", [])),
            "preserved_byte_exact": True,
        },
        "atlas": {
            "picture_count": 4,
            "complete_six_picture_inventory": inventory,
            "label_count": len(labels),
            "localized_picture_indexes": [0, 1, 2],
            "preserved_picture_indexes": [3],
            "output_picture_indexes_sha256": output_picture_hashes,
            "output_member_sha256": _sha256(payload),
            "frozen_range_count": len(ranges),
            "frozen_snapshot_consumed": True,
        },
        "frozen_snapshot": {
            "status": snapshot.get("status"),
            "selection_authority": snapshot.get("selection_authority"),
            "selected_at": snapshot.get("selected_at"),
            "update_policy": snapshot.get("update_policy"),
        },
        "outputs": {
            str(source_reference.get("member")): {
                "path": str(component_path.resolve().relative_to(root)),
                "size": len(payload),
                "sha256": _sha256(payload),
            }
        },
        "acceptance": {
            "reviewed_translation_inventory_complete": len(labels) == 51,
            "all_six_atlas_pictures_classified": len(inventory) == 6,
            "frozen_snapshot_consumed": True,
            "localized_picture_ranges_reread_exact": True,
            "non_localized_member_bytes_inherit_locked_source": True,
            "seg_preserved": True,
            "member_size_preserved": len(payload) == len(source),
            "reviewed_member_sha256_exact": _sha256(payload)
            == expected_member_sha256,
            "runtime_acceptance_complete": snapshot.get("runtime", {}).get("status")
            == "accepted",
        },
        "runtime": snapshot.get("runtime"),
    }
    if not all(report["acceptance"].values()):
        raise FrozenTricmnError("TRICMN frozen component acceptance failed")
    return payload, report


def _snapshot_from_reviewed_payload(config: Mapping, payload: bytes) -> dict:
    source = config.get("source")
    tim2 = config.get("tim2")
    expected = config.get("expected")
    if not all(isinstance(value, Mapping) for value in (source, tim2, expected)):
        raise FrozenTricmnError("TRICMN refreeze contract is incomplete")
    if (
        len(payload) != source.get("size")
        or _sha256(payload) != expected.get("output_member_sha256")
    ):
        raise FrozenTricmnError("only the reviewed expected TRICMN may be frozen")
    pictures = tim2.get("pictures")
    if not isinstance(pictures, list) or len(pictures) != 4:
        raise FrozenTricmnError("TRICMN refreeze picture inventory is malformed")
    frozen_ranges = []
    for picture_index in (0, 1, 2):
        picture = pictures[picture_index]
        if not isinstance(picture, Mapping):
            raise FrozenTricmnError("TRICMN refreeze picture contract is malformed")
        offset = picture.get("image_offset")
        size = picture.get("image_size")
        if not isinstance(offset, int) or not isinstance(size, int):
            raise FrozenTricmnError("TRICMN refreeze image geometry is malformed")
        raw = payload[offset : offset + size]
        if len(raw) != size:
            raise FrozenTricmnError("TRICMN refreeze image is truncated")
        frozen_ranges.append(
            {
                "picture_index": picture_index,
                "offset": offset,
                "size": size,
                "sha256": _sha256(raw),
                "zlib_base64": base64.b64encode(zlib.compress(raw, 9)).decode(
                    "ascii"
                ),
            }
        )
    return {
        "schema_version": 1,
        "status": SNAPSHOT_STATUS,
        "profile_id": config.get("profile_id"),
        "selection_authority": "user_accepted_exact_iso_runtime_review",
        "selected_at": "2026-09-02",
        "update_policy": "explicit_refreeze_only",
        "source_member_size": source.get("size"),
        "source_member_sha256": source.get("sha256"),
        "output_member_size": len(payload),
        "output_member_sha256": _sha256(payload),
        "output_picture_indexes_sha256": expected.get(
            "output_picture_indexes_sha256"
        ),
        "frozen_image_ranges": frozen_ranges,
        "runtime": {
            "status": "accepted",
            "acceptance_date": "2026-09-02",
            "manual_acceptance": (
                "User accepted the full TRICMN atlas after exact-ISO ARMSX2/"
                "LRPS2 battle-animation review."
            ),
            "lrps2_ability_sweep": {
                "passed": 19,
                "total": 19,
                "frame": 6429,
                "contact_sheet_sha256": (
                    "870b9f34a8420c6ea30e2bfd33e2726e4ec1bdebf9e6eb522fe65c527577c4a5"
                ),
                "sequence_sha256": (
                    "4048794fa1634f7f9356fa111d178ad8fbbeb9b6dea679958b92efaf00e93bcc"
                ),
            },
            "current_iso_member_readback": {
                "member": "BTL/TRICMN.BIN",
                "lba": 1312883,
                "sha256": _sha256(payload),
                "byte_exact": True,
            },
        },
    }


def _write_json(path: Path, value: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_live_render(args: argparse.Namespace, config_path: Path, config: dict) -> int:
    from srwz.imagemagick import require_imagemagick, write_deterministic_rgba8_png
    from srwz.tricmn_battle_overlay import (
        TricmnBattleOverlayError,
        build_tricmn_battle_overlay,
    )

    try:
        payload, reference, localized, report = build_tricmn_battle_overlay(
            PROJECT_ROOT,
            config_path,
            enforce_expected=not args.no_enforce_expected,
        )
    except (TricmnBattleOverlayError, OSError, KeyError, ValueError) as error:
        raise SystemExit(f"TRICMN live render failed: {error}") from error
    outputs = config["outputs"]
    component_path = (
        _path(PROJECT_ROOT, outputs["component_root"])
        / config["source"]["member"]
    )
    component_path.parent.mkdir(parents=True, exist_ok=True)
    component_path.write_bytes(payload)
    executable = require_imagemagick()
    for raw_path, pixels in (
        (outputs["reference_png"], reference),
        (outputs["localized_png"], localized),
    ):
        path = _path(PROJECT_ROOT, raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_deterministic_rgba8_png(
            executable,
            pixels,
            path,
            width=2048,
            height=5376,
        )
    report_path = _path(PROJECT_ROOT, outputs["report"])
    _write_json(report_path, report)
    if args.refreeze_snapshot:
        snapshot_reference = config.get("frozen_snapshot")
        if not isinstance(snapshot_reference, Mapping):
            raise SystemExit("TRICMN frozen snapshot reference is missing")
        snapshot_path = _path(PROJECT_ROOT, snapshot_reference.get("path"))
        snapshot = _snapshot_from_reviewed_payload(config, payload)
        _write_json(snapshot_path, snapshot)
        print(json.dumps(_lock(PROJECT_ROOT, snapshot_path), indent=2))
    print(
        "TRICMN live render:",
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
        help="authoring only: rerasterize the atlas instead of consuming the snapshot",
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
    component_path = (
        _path(PROJECT_ROOT, outputs["component_root"])
        / config["source"]["member"]
    )
    report_path = _path(PROJECT_ROOT, outputs["report"])
    if (component_path.exists() or report_path.exists()) and not args.force:
        raise SystemExit("TRICMN battle-overlay output exists; use --force")
    if args.live_render:
        return _run_live_render(args, config_path, config)

    try:
        payload, report = _frozen_component(PROJECT_ROOT, config_path)
    except (FrozenTricmnError, OSError, KeyError, ValueError) as error:
        raise SystemExit(f"TRICMN frozen build failed: {error}") from error
    component_path.parent.mkdir(parents=True, exist_ok=True)
    component_path.write_bytes(payload)
    _write_json(report_path, report)
    manifest_path = _path(PROJECT_ROOT, outputs["manifest"])
    if args.refresh_manifest:
        _write_json(manifest_path, report)
    elif not manifest_path.is_file() or _load_object(manifest_path) != report:
        raise SystemExit(
            "TRICMN frozen manifest drift; review and rerun with --refresh-manifest"
        )
    print(
        "TRICMN battle overlays:",
        f"labels={report['atlas']['label_count']}",
        f"member_size={len(payload)}",
        "mode=locked-indexed-snapshot",
        "runtime=accepted",
    )
    print(f"component: {component_path.relative_to(PROJECT_ROOT)}")
    print(f"report: {report_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
