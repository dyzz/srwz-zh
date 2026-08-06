#!/usr/bin/env python3
"""Build fixed VT1 title-menu canary or localized components."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from srwz.assets import AssetInventoryConfig, AssetInventoryError
    from srwz.canary import CanaryError, rebuild_archive_with_replacement
    from srwz.codec import decode, encode
    from srwz.codec_contract import SrwzCodecError
    from srwz.diagnostics import require_work_output
    from srwz.font_flavor import (
        FontFlavorError,
        font_flavor_metadata,
        load_font_flavor_reference,
        verify_font_flavor_files,
    )
    from srwz.imagemagick import (
        ImageMagickError,
        imagemagick_version,
        render_grayscale_text_mask,
        require_imagemagick,
        write_rgba8_png,
    )
    from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from srwz.patch_audit import summarize_diff
    from srwz.tim2 import Tim2Error, scan_tim2
    from srwz.tim2_writeback import (
        Tim2WritebackError,
        extract_vt1_title_indexes,
        inject_vt1_title_indexes,
        render_vt1_title_rgba,
        replace_vt1_title_index,
    )
    from srwz.title_menu import (
        TITLE_LABEL_COUNT,
        TITLE_LABEL_HEIGHT,
        TITLE_LABEL_WIDTH,
        TITLE_TEXTURE_HEIGHT,
        TITLE_TEXTURE_WIDTH,
        TitleMenuError,
        apply_title_menu_masks,
    )
    from srwz.writers import build_executable_offset_patch_plan
    from srwz.writeback import WritebackError
except ModuleNotFoundError:
    from tools.srwz.assets import AssetInventoryConfig, AssetInventoryError
    from tools.srwz.canary import (
        CanaryError,
        rebuild_archive_with_replacement,
    )
    from tools.srwz.codec import decode, encode
    from tools.srwz.codec_contract import SrwzCodecError
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.font_flavor import (
        FontFlavorError,
        font_flavor_metadata,
        load_font_flavor_reference,
        verify_font_flavor_files,
    )
    from tools.srwz.imagemagick import (
        ImageMagickError,
        imagemagick_version,
        render_grayscale_text_mask,
        require_imagemagick,
        write_rgba8_png,
    )
    from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
    from tools.srwz.iso_layout import (
        ExecutableOffsetSpec,
        IsoLayoutError,
        read_executable_archive_offsets,
    )
    from tools.srwz.patch_audit import summarize_diff
    from tools.srwz.tim2 import Tim2Error, scan_tim2
    from tools.srwz.tim2_writeback import (
        Tim2WritebackError,
        extract_vt1_title_indexes,
        inject_vt1_title_indexes,
        render_vt1_title_rgba,
        replace_vt1_title_index,
    )
    from tools.srwz.title_menu import (
        TITLE_LABEL_COUNT,
        TITLE_LABEL_HEIGHT,
        TITLE_LABEL_WIDTH,
        TITLE_TEXTURE_HEIGHT,
        TITLE_TEXTURE_WIDTH,
        TitleMenuError,
        apply_title_menu_masks,
    )
    from tools.srwz.writers import build_executable_offset_patch_plan
    from tools.srwz.writeback import WritebackError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config" / "canary" / "tim2-vt1-title-index.json"
)


class Tim2CanaryBuildError(ValueError):
    """The fixed canary source or output violates its pinned contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def verify_path(path: Path, expected: dict, label: str) -> None:
    if not path.is_file():
        raise Tim2CanaryBuildError(f"{label} is missing: {path}")
    if path.stat().st_size != expected["size"]:
        raise Tim2CanaryBuildError(f"{label} size mismatch")
    if sha256_path(path) != expected["sha256"]:
        raise Tim2CanaryBuildError(f"{label} SHA-256 mismatch")


def verify_bytes(data: bytes, expected: dict, label: str) -> None:
    if len(data) != expected["size"]:
        raise Tim2CanaryBuildError(f"{label} size mismatch")
    if sha256_bytes(data) != expected["sha256"]:
        raise Tim2CanaryBuildError(f"{label} SHA-256 mismatch")


def read_member(source, member) -> bytes:
    source.seek(member.extent_lba * SECTOR_SIZE)
    data = source.read(member.size)
    if len(data) != member.size:
        raise Tim2CanaryBuildError(f"short read for {member.path}")
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Edit the verified VT1 title texture, re-encode its archive "
            "chunk, and patch the SLPS offset table. No ISO is built."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--print-output-locks", action="store_true")
    return parser.parse_args()


def _expected_output(config: dict, name: str) -> dict | None:
    expected = config.get("expected_outputs")
    if expected is None:
        return None
    value = expected.get(name)
    if not isinstance(value, dict):
        raise Tim2CanaryBuildError(
            f"expected_outputs.{name} must be an object"
        )
    return value


def _localized_title_edit(
    stored_record: bytes,
    config: dict,
    *,
    enforce_expected: bool = True,
) -> tuple[object, dict, bytes]:
    localized = config["localized_labels"]
    try:
        font_flavor = load_font_flavor_reference(
            PROJECT_ROOT,
            localized["font_flavor"],
        )
        font_lock, font_files, fallback_paths, _fallback_reports = (
            verify_font_flavor_files(PROJECT_ROOT, WORK_ROOT, font_flavor)
        )
    except FontFlavorError as error:
        raise Tim2CanaryBuildError(str(error)) from error
    font_path = font_files["font"]

    labels = localized["labels"]
    if not isinstance(labels, list) or len(labels) != TITLE_LABEL_COUNT:
        raise Tim2CanaryBuildError(
            f"localized title requires {TITLE_LABEL_COUNT} labels"
        )
    for index, label in enumerate(labels):
        if label.get("label_index") != index:
            raise Tim2CanaryBuildError(
                "localized title label indexes must be ordered 0..3"
            )
        if not isinstance(label.get("source"), str):
            raise Tim2CanaryBuildError("localized source label must be text")
        if not isinstance(label.get("text"), str):
            raise Tim2CanaryBuildError("localized target label must be text")
    unsupported = sorted(
        set("".join(label["text"] for label in labels)) & set(fallback_paths)
    )
    if unsupported:
        raise Tim2CanaryBuildError(
            "localized title requires per-character fallback rendering: "
            + "".join(unsupported)
        )

    render = localized["render"]
    magick = require_imagemagick()
    version = imagemagick_version(magick)
    version_prefix = render["imagemagick_version_prefix"]
    if not version.startswith(version_prefix):
        raise Tim2CanaryBuildError(
            f"ImageMagick version {version!r} does not start with "
            f"{version_prefix!r}"
        )
    masks = tuple(
        render_grayscale_text_mask(
            magick,
            font_path,
            label["text"],
            width=TITLE_LABEL_WIDTH,
            height=TITLE_LABEL_HEIGHT,
            point_size=render["point_size"],
            stroke_gray=render["stroke_gray"],
            stroke_width=render["stroke_width"],
            fill_stroke_width=render["fill_stroke_width"],
        )
        for label in labels
    )
    expected_mask_hashes = render.get("mask_sha256")
    actual_mask_hashes = [sha256_bytes(mask) for mask in masks]
    if (
        enforce_expected
        and
        expected_mask_hashes is not None
        and actual_mask_hashes != expected_mask_hashes
    ):
        raise Tim2CanaryBuildError(
            "localized title mask SHA-256 list mismatch"
        )

    original_indexes = extract_vt1_title_indexes(stored_record)
    menu_edit = apply_title_menu_masks(original_indexes, masks)
    replacement = inject_vt1_title_indexes(
        stored_record,
        menu_edit.indexes,
    )
    if replacement.changed_pixel_count != menu_edit.changed_pixel_count:
        raise Tim2CanaryBuildError(
            "logical title edit and TIM2 injection change counts disagree"
        )
    preview_rgba = render_vt1_title_rgba(replacement.data)
    metadata = {
        "mode": "localized_labels",
        "font": {
            "flavor": font_flavor_metadata(font_flavor),
            "family": font_lock["family"],
            "version": font_lock["version"],
            "size": font_path.stat().st_size,
            "sha256": sha256_path(font_path),
        },
        "imagemagick_version": version,
        "render": {
            "width": TITLE_LABEL_WIDTH,
            "height": TITLE_LABEL_HEIGHT,
            "point_size": render["point_size"],
            "stroke_gray": render["stroke_gray"],
            "stroke_width": render["stroke_width"],
            "fill_stroke_width": render["fill_stroke_width"],
            "mask_sha256": actual_mask_hashes,
        },
        "labels": labels,
        "composition": menu_edit.to_metadata(),
        "preview_rgba": {
            "width": TITLE_TEXTURE_WIDTH,
            "height": TITLE_TEXTURE_HEIGHT,
            "size": len(preview_rgba),
            "sha256": sha256_bytes(preview_rgba),
        },
    }
    return replacement, metadata, preview_rgba


def build(
    config_path: Path,
    *,
    enforce_expected_outputs: bool = True,
) -> tuple[bytes, bytes, dict, bytes | None]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise Tim2CanaryBuildError("unsupported canary config schema")

    iso_path = resolve_path(config["source_iso"]["path"])
    verify_path(iso_path, config["source_iso"], "source ISO")
    asset_config_path = resolve_path(config["asset_config"])
    asset_config = AssetInventoryConfig.from_mapping(
        json.loads(asset_config_path.read_text(encoding="utf-8"))
    )

    executable_lock = config["source_members"]["executable"]
    archive_lock = config["source_members"]["archive"]
    image = scan_iso9660(iso_path)
    members = member_map(image)
    required = {
        executable_lock["member"],
        archive_lock["member"],
    }
    missing = sorted(required - members.keys())
    if missing:
        raise Tim2CanaryBuildError(f"ISO members are missing: {missing}")
    with iso_path.open("rb") as source:
        executable = read_member(
            source,
            members[executable_lock["member"]],
        )
        archive = read_member(source, members[archive_lock["member"]])
    verify_bytes(executable, executable_lock, "source executable")
    verify_bytes(archive, archive_lock, "source archive")

    spec = asset_config.archive_for_member(archive_lock["member"])
    if spec is None or spec.storage != "srwz_stream":
        raise Tim2CanaryBuildError(
            "target archive must use declared srwz_stream storage"
        )
    if asset_config.executable_member != executable_lock["member"]:
        raise Tim2CanaryBuildError(
            "asset config executable does not match canary lock"
        )
    layout_spec = ExecutableOffsetSpec(
        name=spec.name,
        member=spec.member,
        table_start=spec.table_start,
        table_end=spec.table_end,
    )
    old_offsets = read_executable_archive_offsets(
        executable,
        layout_spec,
        len(archive),
    )

    target = config["target"]
    chunk_index = target["chunk_index"]
    if not 0 <= chunk_index < len(old_offsets) - 1:
        raise Tim2CanaryBuildError("target chunk index is outside archive")
    chunk_start = old_offsets[chunk_index]
    chunk_end = old_offsets[chunk_index + 1]
    if (chunk_start, chunk_end) != (
        target["stored_start"],
        target["stored_end"],
    ):
        raise Tim2CanaryBuildError("target stored range mismatch")
    stored_chunk = archive[chunk_start:chunk_end]
    if sha256_bytes(stored_chunk) != target["stored_sha256"]:
        raise Tim2CanaryBuildError("target stored chunk SHA-256 mismatch")

    decoded_result = decode(stored_chunk)
    if any(stored_chunk[decoded_result.consumed:]):
        raise Tim2CanaryBuildError(
            "target stored chunk has nonzero bytes after compressed stream"
        )
    decoded = decoded_result.output
    if (
        len(decoded) != target["decoded_size"]
        or sha256_bytes(decoded) != target["decoded_sha256"]
    ):
        raise Tim2CanaryBuildError("target decoded chunk lock mismatch")

    records = scan_tim2(decoded)
    record_index = target["record_index"]
    if not 0 <= record_index < len(records):
        raise Tim2CanaryBuildError("target TIM2 record index is outside chunk")
    record = records[record_index]
    stored_record = decoded[record.offset:record.end]
    if (
        record.offset != target["record_offset"]
        or record.size != target["record_size"]
        or sha256_bytes(stored_record) != target["record_sha256"]
    ):
        raise Tim2CanaryBuildError("target TIM2 record lock mismatch")
    if target["picture_index"] != 0:
        raise Tim2CanaryBuildError(
            "fixed VT1 title canary supports picture 0 only"
        )

    source_runtime_rgba = render_vt1_title_rgba(stored_record)
    if (
        len(source_runtime_rgba)
        != target["runtime_texture_width"]
        * target["runtime_texture_height"]
        * 4
        or sha256_bytes(source_runtime_rgba)
        != target["runtime_texture_rgba_sha256"]
    ):
        raise Tim2CanaryBuildError(
            "source title render does not match pinned runtime texture"
        )

    preview_rgba = None
    if "localized_labels" in config:
        replacement, edit_metadata, preview_rgba = _localized_title_edit(
            stored_record,
            config,
            enforce_expected=enforce_expected_outputs,
        )
    else:
        replacement = replace_vt1_title_index(
            stored_record,
            source_index=target["source_index"],
            replacement_index=target["replacement_index"],
            expected_occurrence_count=(
                target["source_index_occurrence_count"]
            ),
        )
        edit_metadata = {
            "mode": "global_index_replacement",
            "source_index": target["source_index"],
            "source_index_runtime_rgba": (
                target["source_index_runtime_rgba"]
            ),
            "replacement_index": target["replacement_index"],
            "replacement_index_runtime_rgba": (
                target["replacement_index_runtime_rgba"]
            ),
        }
    modified_decoded = (
        decoded[:record.offset]
        + replacement.data
        + decoded[record.end:]
    )
    if (
        modified_decoded[:record.offset] != decoded[:record.offset]
        or modified_decoded[record.end:] != decoded[record.end:]
    ):
        raise Tim2CanaryBuildError(
            "decoded bytes outside target TIM2 record changed"
        )

    strategy = config["codec"]["strategy"]
    alignment = config["codec"]["alignment"]
    maximum_size = config["codec"].get("maximum_size")
    if maximum_size is not None and (
        not isinstance(maximum_size, int)
        or isinstance(maximum_size, bool)
        or maximum_size <= 0
    ):
        raise Tim2CanaryBuildError(
            "codec.maximum_size must be a positive integer"
        )
    minimum_allocation = config["codec"].get("minimum_allocation", 0)
    if (
        not isinstance(minimum_allocation, int)
        or isinstance(minimum_allocation, bool)
        or minimum_allocation < 0
    ):
        raise Tim2CanaryBuildError(
            "codec.minimum_allocation must be a non-negative integer"
        )
    encoded = encode(
        modified_decoded,
        strategy=strategy,
        max_output_size=maximum_size,
    )
    encoded_round_trip = decode(encoded)
    if (
        encoded_round_trip.consumed != len(encoded)
        or encoded_round_trip.output != modified_decoded
    ):
        raise Tim2CanaryBuildError(
            "encoded replacement does not decode to modified chunk"
        )
    rebuilt_archive, new_offsets, padding_size = (
        rebuild_archive_with_replacement(
            archive,
            old_offsets,
            chunk_index=chunk_index,
            encoded_replacement=encoded,
            alignment=alignment,
            minimum_allocation=minimum_allocation,
        )
    )

    unchanged_chunk_count = 0
    for index, (old_start, old_end, new_start, new_end) in enumerate(
        zip(
            old_offsets,
            old_offsets[1:],
            new_offsets,
            new_offsets[1:],
        )
    ):
        if index == chunk_index:
            continue
        if archive[old_start:old_end] != rebuilt_archive[new_start:new_end]:
            raise Tim2CanaryBuildError(
                f"non-target archive chunk {index} changed"
            )
        unchanged_chunk_count += 1

    offset_plan = build_executable_offset_patch_plan(
        executable,
        layout_spec,
        new_offsets,
    )
    rebuilt_executable = offset_plan.apply(executable)
    if (
        read_executable_archive_offsets(
            rebuilt_executable,
            layout_spec,
            len(rebuilt_archive),
        )
        != new_offsets
    ):
        raise Tim2CanaryBuildError(
            "rebuilt executable cannot reread new VT1 offsets"
        )

    rebuilt_slice = rebuilt_archive[
        new_offsets[chunk_index]:new_offsets[chunk_index + 1]
    ]
    rebuilt_decoded = decode(rebuilt_slice)
    if (
        rebuilt_decoded.consumed != len(encoded)
        or rebuilt_decoded.output != modified_decoded
        or any(rebuilt_slice[rebuilt_decoded.consumed:])
    ):
        raise Tim2CanaryBuildError(
            "rebuilt archive target chunk verification failed"
        )

    expected_executable = _expected_output(config, "executable")
    expected_archive = _expected_output(config, "archive")
    if enforce_expected_outputs and expected_executable is not None:
        verify_bytes(
            rebuilt_executable,
            expected_executable,
            "rebuilt executable",
        )
    if enforce_expected_outputs and expected_archive is not None:
        verify_bytes(rebuilt_archive, expected_archive, "rebuilt archive")

    report = {
        "schema_version": 1,
        "status": "passed",
        "content_policy": (
            "Hashes, sizes, counts and half-open changed ranges only; "
            "game bytes remain in ignored work/."
        ),
        "profile_id": config["profile_id"],
        "runtime_acceptance": "not tested by component builder",
        "source": {
            "iso_file_name": iso_path.name,
            "iso_size": iso_path.stat().st_size,
            "iso_sha256": config["source_iso"]["sha256"],
            "executable": {
                "member": executable_lock["member"],
                "size": len(executable),
                "sha256": sha256_bytes(executable),
            },
            "archive": {
                "member": archive_lock["member"],
                "size": len(archive),
                "sha256": sha256_bytes(archive),
                "chunk_count": len(old_offsets) - 1,
            },
        },
        "target": {
            "chunk_index": chunk_index,
            "stored_start": chunk_start,
            "stored_end": chunk_end,
            "stored_size": len(stored_chunk),
            "stored_sha256": sha256_bytes(stored_chunk),
            "compressed_stream_size": decoded_result.consumed,
            "decoded_size": len(decoded),
            "decoded_sha256": sha256_bytes(decoded),
            "record_index": record_index,
            "record_offset": record.offset,
            "record_size": record.size,
            "record_sha256": sha256_bytes(stored_record),
            "picture_index": target["picture_index"],
            "runtime_texture": {
                "width": target["runtime_texture_width"],
                "height": target["runtime_texture_height"],
                "png_sha256": target["runtime_texture_sha256"],
                "rgba_sha256": target["runtime_texture_rgba_sha256"],
                "static_render_exact": True,
            },
        },
        "edit": edit_metadata,
        "injection": replacement.to_metadata(),
        "codec": {
            "strategy": strategy,
            "encoded_size": len(encoded),
            "encoded_sha256": sha256_bytes(encoded),
            "padding_size": padding_size,
            "maximum_size": maximum_size,
            "minimum_allocation": minimum_allocation,
            "within_size_budget": (
                maximum_size is None or len(encoded) <= maximum_size
            ),
            "decoded_round_trip_exact": True,
        },
        "outputs": {
            "executable": {
                "size": len(rebuilt_executable),
                "sha256": sha256_bytes(rebuilt_executable),
                "diff": summarize_diff(
                    executable,
                    rebuilt_executable,
                ).to_mapping(),
                "offset_patch_plan": offset_plan.to_metadata(),
                "offset_reread_exact": True,
            },
            "archive": {
                "size": len(rebuilt_archive),
                "sha256": sha256_bytes(rebuilt_archive),
                "old_offset_count": len(old_offsets),
                "new_offset_count": len(new_offsets),
                "offsets_aligned": all(
                    offset % alignment == 0 for offset in new_offsets
                ),
                "unchanged_chunk_count": unchanged_chunk_count,
                "target_decoded_round_trip_exact": True,
            },
        },
    }
    return rebuilt_executable, rebuilt_archive, report, preview_rgba


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        outputs = {
            name: require_work_output(resolve_path(path), WORK_ROOT)
            for name, path in config["outputs"].items()
        }
        if len(set(outputs.values())) != len(outputs):
            raise Tim2CanaryBuildError("output paths must be distinct")
        existing = [path for path in outputs.values() if path.exists()]
        if existing and not args.force:
            raise FileExistsError(
                f"refusing to replace existing file: {existing[0]}"
            )
        executable, archive, report, preview_rgba = build(
            config_path,
            enforce_expected_outputs=not args.print_output_locks,
        )
        if args.print_output_locks:
            print(
                json.dumps(
                    {
                        "mask_sha256": report["edit"]["render"][
                            "mask_sha256"
                        ],
                        "expected_outputs": {
                            name: report["outputs"][name]
                            for name in ("executable", "archive")
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        payloads = {
            "executable": executable,
            "archive": archive,
            "report": (
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8"),
        }
        required_outputs = {"executable", "archive", "report"}
        if not required_outputs.issubset(outputs):
            raise Tim2CanaryBuildError(
                "outputs must include executable, archive and report"
            )
        unexpected = set(outputs) - required_outputs - {"preview"}
        if unexpected:
            raise Tim2CanaryBuildError(
                f"unsupported outputs: {sorted(unexpected)}"
            )
        for name, payload in payloads.items():
            path = outputs[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            print(f"{name}: {path}")
        if preview_rgba is not None:
            preview_path = outputs.get("preview")
            if preview_path is None:
                raise Tim2CanaryBuildError(
                    "localized title output requires a preview path"
                )
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            write_rgba8_png(
                require_imagemagick(),
                preview_rgba,
                preview_path,
                width=TITLE_TEXTURE_WIDTH,
                height=TITLE_TEXTURE_HEIGHT,
            )
            print(f"preview: {preview_path}")
        elif "preview" in outputs:
            raise Tim2CanaryBuildError(
                "index replacement cannot declare a preview output"
            )
    except (
        AssetInventoryError,
        CanaryError,
        FileExistsError,
        IsoLayoutError,
        ImageMagickError,
        KeyError,
        SrwzCodecError,
        Tim2CanaryBuildError,
        Tim2Error,
        Tim2WritebackError,
        TitleMenuError,
        ValueError,
        WritebackError,
        json.JSONDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
