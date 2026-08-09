"""Localize the fixed 512x32 location-title textures in MAPMODEL."""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from typing import Mapping

from .codec import decode, reencode_changed_suffix
from .font import sha256_bytes
from .font_flavor import (
    font_flavor_metadata,
    load_font_flavor_reference,
    verify_font_flavor_files,
)
from .imagemagick import (
    imagemagick_version,
    require_imagemagick,
    write_deterministic_rgba8_png,
)


class WorldMapTitleError(ValueError):
    """A WORLD MAP title input, layout, or writeback invariant failed."""


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise WorldMapTitleError("world-map path must be a non-empty string")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise WorldMapTitleError(
            f"world-map path escapes project root: {raw}"
        ) from error
    return path


def _display_path(project_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _locked_file(
    project_root: Path,
    reference: object,
    *,
    label: str,
) -> tuple[Path, bytes]:
    if not isinstance(reference, Mapping):
        raise WorldMapTitleError(f"{label} lock is invalid")
    path = _project_path(project_root, reference.get("path"))
    try:
        data = path.read_bytes()
    except OSError as error:
        raise WorldMapTitleError(f"cannot read {label}: {path}") from error
    if (
        not isinstance(reference.get("size"), int)
        or isinstance(reference.get("size"), bool)
        or len(data) != reference.get("size")
        or sha256_bytes(data) != reference.get("sha256")
    ):
        raise WorldMapTitleError(f"{label} lock drift")
    return path, data


def _integer(raw: object, *, label: str) -> int:
    if isinstance(raw, bool):
        raise WorldMapTitleError(f"{label} is not an integer")
    try:
        value = int(str(raw), 0) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError) as error:
        raise WorldMapTitleError(f"{label} is not an integer") from error
    if value < 0:
        raise WorldMapTitleError(f"{label} cannot be negative")
    return value


def unpack_vertical_linear_4bpp(
    raw: bytes,
    *,
    width: int,
    height: int,
) -> bytes:
    """Return top-down 4-bit indexes from low-nibble-first flipped rows."""

    expected = width * height // 2
    if width <= 0 or height <= 0 or width % 2 or len(raw) != expected:
        raise WorldMapTitleError("invalid vertical linear 4bpp texture")
    logical = bytearray(width * height)
    row_size = width // 2
    for stored_y in range(height):
        logical_y = height - 1 - stored_y
        row = raw[stored_y * row_size : (stored_y + 1) * row_size]
        target = logical_y * width
        for byte_index, value in enumerate(row):
            logical[target + byte_index * 2] = value & 0x0F
            logical[target + byte_index * 2 + 1] = value >> 4
    return bytes(logical)


def pack_vertical_linear_4bpp(
    logical: bytes,
    *,
    width: int,
    height: int,
) -> bytes:
    """Pack top-down 4-bit indexes into low-nibble-first flipped rows."""

    if width <= 0 or height <= 0 or width % 2:
        raise WorldMapTitleError("invalid vertical linear 4bpp geometry")
    if len(logical) != width * height or any(value > 0x0F for value in logical):
        raise WorldMapTitleError("invalid vertical linear 4bpp indexes")
    row_size = width // 2
    raw = bytearray(row_size * height)
    for logical_y in range(height):
        stored_y = height - 1 - logical_y
        source = logical_y * width
        target = stored_y * row_size
        for x in range(0, width, 2):
            raw[target + x // 2] = (
                logical[source + x]
                | (logical[source + x + 1] << 4)
            )
    return bytes(raw)


def index_bbox(
    logical: bytes,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    if len(logical) != width * height:
        raise WorldMapTitleError("logical texture geometry drift")
    points = [index for index, value in enumerate(logical) if value]
    if not points:
        return None
    xs = [index % width for index in points]
    ys = [index // width for index in points]
    return min(xs), min(ys), max(xs), max(ys)


def _render_quantized_text(
    executable: str,
    font: Path,
    text: str,
    *,
    point_size: int,
    kerning: float,
    hinting: bool,
    antialias: bool,
    canvas_width: int,
    canvas_height: int,
) -> bytes:
    command = [
        executable,
        "-size",
        f"{canvas_width}x{canvas_height}",
        "xc:black",
        "-font",
        str(font),
        "-pointsize",
        str(point_size),
        "-kerning",
        f"{kerning:g}",
        "-define",
        f"type:hinting={'true' if hinting else 'false'}",
    ]
    command.append("-antialias" if antialias else "+antialias")
    command.extend(
        [
            "-gravity",
            "center",
            "-fill",
            "white",
            "-stroke",
            "none",
            "-annotate",
            "+0+0",
            text,
            "-alpha",
            "off",
            "-colorspace",
            "Gray",
            "-depth",
            "8",
            "gray:-",
        ]
    )
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", errors="replace").strip()
        raise WorldMapTitleError(
            f"ImageMagick title render failed for {text!r}: {message}"
        )
    expected = canvas_width * canvas_height
    if len(process.stdout) != expected:
        raise WorldMapTitleError(
            f"ImageMagick returned {len(process.stdout)} bytes, expected {expected}"
        )
    return bytes(min(15, (value * 15 + 127) // 255) for value in process.stdout)


def render_title_inside_bbox(
    executable: str,
    font: Path,
    text: str,
    source_bbox: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
    max_point_size: int,
    min_point_size: int,
    kerning_candidates: tuple[float, ...],
    hinting: bool,
    antialias: bool,
    canvas_width: int,
    canvas_height: int,
) -> tuple[bytes, dict]:
    """Render one title and center it inside the original nonzero bounds."""

    if not text or "\n" in text or "\r" in text:
        raise WorldMapTitleError("world-map translation must be one non-empty line")
    source_x0, source_y0, source_x1, source_y1 = source_bbox
    source_width = source_x1 - source_x0 + 1
    source_height = source_y1 - source_y0 + 1
    selected = None
    for point_size in range(max_point_size, min_point_size - 1, -1):
        for kerning in kerning_candidates:
            rendered = _render_quantized_text(
                executable,
                font,
                text,
                point_size=point_size,
                kerning=kerning,
                hinting=hinting,
                antialias=antialias,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
            )
            bbox = index_bbox(
                rendered,
                width=canvas_width,
                height=canvas_height,
            )
            if bbox is None:
                continue
            x0, y0, x1, y1 = bbox
            rendered_width = x1 - x0 + 1
            rendered_height = y1 - y0 + 1
            if rendered_width <= source_width and rendered_height <= source_height:
                selected = (
                    point_size,
                    kerning,
                    rendered,
                    bbox,
                    rendered_width,
                    rendered_height,
                )
                break
        if selected is not None:
            break
    if selected is None:
        raise WorldMapTitleError(
            f"translation does not fit source bounds {source_bbox}: {text!r}"
        )
    point_size, kerning, rendered, bbox, rendered_width, rendered_height = selected
    render_x0, render_y0, _render_x1, _render_y1 = bbox
    target_x0 = source_x0 + (source_width - rendered_width) // 2
    target_y0 = source_y0 + (source_height - rendered_height) // 2
    target_x1 = target_x0 + rendered_width - 1
    target_y1 = target_y0 + rendered_height - 1
    if not (
        source_x0 <= target_x0 <= target_x1 <= source_x1
        and source_y0 <= target_y0 <= target_y1 <= source_y1
    ):
        raise WorldMapTitleError("rendered title escaped its source bounds")
    title = bytearray(width * height)
    for y in range(rendered_height):
        source_row = (render_y0 + y) * canvas_width + render_x0
        target_row = (target_y0 + y) * width + target_x0
        title[target_row : target_row + rendered_width] = rendered[
            source_row : source_row + rendered_width
        ]
    if index_bbox(bytes(title), width=width, height=height) != (
        target_x0,
        target_y0,
        target_x1,
        target_y1,
    ):
        raise WorldMapTitleError("rendered title bbox changed during placement")
    return bytes(title), {
        "point_size": point_size,
        "kerning": kerning,
        "source_bbox": list(source_bbox),
        "rendered_bbox": [target_x0, target_y0, target_x1, target_y1],
        "rendered_width": rendered_width,
        "rendered_height": rendered_height,
    }


def replace_title_inside_bbox(
    source: bytes,
    rendered_title: bytes,
    source_bbox: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
) -> bytes:
    """Clear only the original title rectangle, then overlay its replacement."""

    if len(source) != width * height or len(rendered_title) != width * height:
        raise WorldMapTitleError("title replacement geometry drift")
    x0, y0, x1, y1 = source_bbox
    output = bytearray(source)
    for y in range(y0, y1 + 1):
        row = y * width
        output[row + x0 : row + x1 + 1] = bytes(x1 - x0 + 1)
    for index, value in enumerate(rendered_title):
        if not value:
            continue
        x = index % width
        y = index // width
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            raise WorldMapTitleError("replacement pixel escaped source bounds")
        output[index] = value
    for y in range(height):
        for x in range(width):
            if x0 <= x <= x1 and y0 <= y <= y1:
                continue
            index = y * width + x
            if output[index] != source[index]:
                raise WorldMapTitleError("replacement changed pixels outside source bounds")
    return bytes(output)


def _write_preview(
    executable: str,
    preview_root: Path,
    rows: list[bytes],
    *,
    width: int,
    height: int,
) -> tuple[Path, bytes]:
    gap = 4
    sheet_height = len(rows) * (height + gap) - gap
    rgba = bytearray(width * sheet_height * 4)
    for row_index, indexes in enumerate(rows):
        y_offset = row_index * (height + gap)
        for index, value in enumerate(indexes):
            x = index % width
            y = index // width + y_offset
            gray = value * 17
            target = (y * width + x) * 4
            rgba[target : target + 4] = bytes((gray, gray, gray, 255))
    preview_root.mkdir(parents=True, exist_ok=True)
    path = preview_root / "world-map-titles-contact-sheet.png"
    write_deterministic_rgba8_png(
        executable,
        bytes(rgba),
        path,
        width=width,
        height=sheet_height,
    )
    return path, path.read_bytes()


def build_world_map_titles(
    project_root: Path,
    work_root: Path,
    reference: object,
    *,
    preview_root: Path | None = None,
) -> tuple[bytes, dict, dict[str, Path]]:
    """Build a same-size MAPMODEL archive with all reviewed titles localized."""

    if not isinstance(reference, Mapping):
        raise WorldMapTitleError("world-map title configuration is invalid")
    original_slps_path, original_slps = _locked_file(
        project_root,
        reference.get("original_slps"),
        label="world-map original SLPS",
    )
    original_archive_path, original_archive = _locked_file(
        project_root,
        reference.get("original_archive"),
        label="world-map original archive",
    )
    corpus_path, corpus_data = _locked_file(
        project_root,
        reference.get("corpus"),
        label="world-map title corpus",
    )
    try:
        corpus = json.loads(corpus_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorldMapTitleError("world-map title corpus is invalid JSON") from error
    if not isinstance(corpus, dict) or corpus.get("schema_version") != 1:
        raise WorldMapTitleError("unsupported world-map title corpus schema")

    archive_config = reference.get("archive")
    texture = reference.get("texture")
    render = reference.get("render")
    codec = reference.get("codec")
    expected = reference.get("expected")
    if not all(
        isinstance(item, Mapping)
        for item in (archive_config, texture, render, codec, expected)
    ):
        raise WorldMapTitleError("world-map configuration groups are incomplete")
    width = _integer(texture.get("width"), label="title width")
    height = _integer(texture.get("height"), label="title height")
    if texture.get("bpp") != 4 or width != 512 or height != 32:
        raise WorldMapTitleError("unsupported world-map title geometry")
    raw_size = width * height // 2
    japanese_start = _integer(
        texture.get("japanese_raw_start"), label="Japanese title start"
    )
    japanese_end = _integer(
        texture.get("japanese_raw_end"), label="Japanese title end"
    )
    english_start = _integer(
        texture.get("english_raw_start"), label="English subtitle start"
    )
    english_end = _integer(
        texture.get("english_raw_end"), label="English subtitle end"
    )
    if (
        japanese_end - japanese_start != raw_size
        or english_end - english_start != raw_size
        or japanese_end > english_start
    ):
        raise WorldMapTitleError("world-map raw texture spans are invalid")

    table_start = _integer(
        archive_config.get("offset_table_start"), label="offset table start"
    )
    offset_count = _integer(
        archive_config.get("offset_count"), label="offset count"
    )
    table_end = table_start + offset_count * 4
    if table_end > len(original_slps):
        raise WorldMapTitleError("MAPMODEL offset table leaves SLPS")
    table_data = original_slps[table_start:table_end]
    if sha256_bytes(table_data) != archive_config.get("offset_table_sha256"):
        raise WorldMapTitleError("MAPMODEL offset table SHA-256 drift")
    offsets = list(struct.unpack(f"<{offset_count}I", table_data))
    if (
        not offsets
        or offsets[0] != 0
        or offsets[-1] != len(original_archive)
        or any(left >= right for left, right in zip(offsets, offsets[1:]))
    ):
        raise WorldMapTitleError("MAPMODEL offset table structure drift")
    alignment = _integer(
        archive_config.get("alignment"), label="archive alignment"
    )
    if alignment <= 0 or any(offset % alignment for offset in offsets):
        raise WorldMapTitleError("MAPMODEL member alignment drift")
    first_member = _integer(
        archive_config.get("first_title_member"), label="first title member"
    )
    last_member = _integer(
        archive_config.get("last_title_member"), label="last title member"
    )
    if not (0 <= first_member <= last_member < len(offsets) - 1):
        raise WorldMapTitleError("world-map title member range is invalid")

    entries = corpus.get("entries")
    if not isinstance(entries, list):
        raise WorldMapTitleError("world-map corpus entries are missing")
    member_to_entry: dict[int, dict] = {}
    source_hashes = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise WorldMapTitleError("world-map corpus entry is malformed")
        entry_id = entry.get("id")
        members = entry.get("members")
        source = entry.get("source")
        translation = entry.get("translation")
        source_hash = entry.get("source_raw_sha256")
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(members, list)
            or not members
            or not isinstance(source, str)
            or not source
            or not isinstance(translation, str)
            or not translation
            or entry.get("editorial_status") != "reviewed"
            or not isinstance(source_hash, str)
            or len(source_hash) != 64
            or source_hash in source_hashes
        ):
            raise WorldMapTitleError(f"invalid world-map corpus entry: {entry_id}")
        source_hashes.add(source_hash)
        for member in members:
            if (
                not isinstance(member, int)
                or isinstance(member, bool)
                or member in member_to_entry
            ):
                raise WorldMapTitleError(
                    f"invalid or duplicate world-map member: {member}"
                )
            member_to_entry[member] = entry
    expected_members = list(range(first_member, last_member + 1))
    if (
        len(entries) != expected.get("unique_title_count")
        or len(member_to_entry) != expected.get("member_count")
        or sorted(member_to_entry) != expected_members
    ):
        raise WorldMapTitleError("world-map corpus coverage drift")
    translated_unique_count = sum(
        entry["source"] != entry["translation"] for entry in entries
    )
    translated_member_count = sum(
        len(entry["members"])
        for entry in entries
        if entry["source"] != entry["translation"]
    )
    if (
        translated_unique_count != expected.get("translated_unique_title_count")
        or translated_member_count != expected.get("translated_member_count")
    ):
        raise WorldMapTitleError("world-map translated corpus coverage drift")

    flavor = load_font_flavor_reference(
        project_root,
        reference.get("font_flavor"),
    )
    _font_lock, primary_files, _fallback_paths, fallback_reports = (
        verify_font_flavor_files(project_root, work_root, flavor)
    )
    font_path = primary_files.get("font")
    if font_path is None:
        raise WorldMapTitleError("world-map primary font is unavailable")
    executable = require_imagemagick()
    version = imagemagick_version(executable)
    if version != render.get("imagemagick_version"):
        raise WorldMapTitleError("world-map ImageMagick version drift")
    max_point_size = _integer(
        render.get("max_point_size"), label="maximum point size"
    )
    min_point_size = _integer(
        render.get("min_point_size"), label="minimum point size"
    )
    raw_kernings = render.get("kerning_candidates")
    if (
        min_point_size <= 0
        or min_point_size > max_point_size
        or not isinstance(raw_kernings, list)
        or not raw_kernings
    ):
        raise WorldMapTitleError("world-map render search is invalid")
    try:
        kerning_candidates = tuple(float(value) for value in raw_kernings)
    except (TypeError, ValueError) as error:
        raise WorldMapTitleError("world-map kerning candidates are invalid") from error
    if any(value < 0 for value in kerning_candidates):
        raise WorldMapTitleError("world-map kerning cannot be negative")
    hinting = render.get("hinting")
    antialias = render.get("antialias")
    if not isinstance(hinting, bool) or not isinstance(antialias, bool):
        raise WorldMapTitleError("world-map raster flags are invalid")
    canvas_width = _integer(
        render.get("canvas_width"), label="render canvas width"
    )
    canvas_height = _integer(
        render.get("canvas_height"), label="render canvas height"
    )
    if canvas_width < width or canvas_height < height:
        raise WorldMapTitleError("world-map render canvas is too small")
    if codec.get("strategy") != "rust-fit":
        raise WorldMapTitleError("world-map production codec must be rust-fit")
    min_match_length = _integer(
        codec.get("min_match_length"), label="minimum match length"
    )
    max_match_chain = _integer(
        codec.get("max_match_chain"), label="maximum match chain"
    )

    output_archive = bytearray(original_archive)
    title_reports = []
    member_reports = []
    preview_rows: list[bytes] = []
    translated_headrooms = []
    all_headrooms = []
    english_hash = texture.get("english_raw_sha256")
    entry_render_cache: dict[str, tuple[bytes, tuple[int, int, int, int], dict]] = {}

    for entry in entries:
        representative = entry["members"][0]
        stored = original_archive[offsets[representative] : offsets[representative + 1]]
        decoded = decode(stored)
        if decoded.consumed > len(stored) or any(stored[decoded.consumed :]):
            raise WorldMapTitleError(
                f"member {representative} compressed padding is not zero"
            )
        if english_end > len(decoded.output):
            raise WorldMapTitleError(
                f"member {representative} title texture leaves decoded payload"
            )
        source_raw = decoded.output[japanese_start:japanese_end]
        if sha256_bytes(source_raw) != entry["source_raw_sha256"]:
            raise WorldMapTitleError(
                f"member {representative} source title SHA-256 drift"
            )
        if sha256_bytes(decoded.output[english_start:english_end]) != english_hash:
            raise WorldMapTitleError(
                f"member {representative} English subtitle SHA-256 drift"
            )
        source_logical = unpack_vertical_linear_4bpp(
            source_raw,
            width=width,
            height=height,
        )
        bbox = index_bbox(source_logical, width=width, height=height)
        if bbox is None:
            raise WorldMapTitleError(f"member {representative} title is blank")
        if entry["source"] == entry["translation"]:
            replacement = source_logical
            geometry = {
                "point_size": None,
                "kerning": None,
                "source_bbox": list(bbox),
                "rendered_bbox": list(bbox),
                "rendered_width": bbox[2] - bbox[0] + 1,
                "rendered_height": bbox[3] - bbox[1] + 1,
            }
        else:
            rendered, geometry = render_title_inside_bbox(
                executable,
                font_path,
                entry["translation"],
                bbox,
                width=width,
                height=height,
                max_point_size=max_point_size,
                min_point_size=min_point_size,
                kerning_candidates=kerning_candidates,
                hinting=hinting,
                antialias=antialias,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
            )
            replacement = replace_title_inside_bbox(
                source_logical,
                rendered,
                bbox,
                width=width,
                height=height,
            )
        entry_render_cache[entry["id"]] = (replacement, bbox, geometry)
        preview_rows.append(replacement)
        title_reports.append(
            {
                "id": entry["id"],
                "source": entry["source"],
                "translation": entry["translation"],
                "members": entry["members"],
                "source_raw_sha256": entry["source_raw_sha256"],
                "output_raw_sha256": sha256_bytes(
                    pack_vertical_linear_4bpp(
                        replacement,
                        width=width,
                        height=height,
                    )
                ),
                "same_text_no_op": entry["source"] == entry["translation"],
                "geometry": geometry,
            }
        )

    for member in expected_members:
        entry = member_to_entry[member]
        start = offsets[member]
        end = offsets[member + 1]
        stored = original_archive[start:end]
        decoded = decode(stored)
        if decoded.consumed > len(stored) or any(stored[decoded.consumed :]):
            raise WorldMapTitleError(f"member {member} compressed padding is not zero")
        if english_end > len(decoded.output):
            raise WorldMapTitleError(
                f"member {member} title texture leaves decoded payload"
            )
        source_raw = decoded.output[japanese_start:japanese_end]
        if sha256_bytes(source_raw) != entry["source_raw_sha256"]:
            raise WorldMapTitleError(f"member {member} source title SHA-256 drift")
        source_english = decoded.output[english_start:english_end]
        if sha256_bytes(source_english) != english_hash:
            raise WorldMapTitleError(f"member {member} English subtitle SHA-256 drift")
        replacement, bbox, _geometry = entry_render_cache[entry["id"]]
        source_logical = unpack_vertical_linear_4bpp(
            source_raw,
            width=width,
            height=height,
        )
        if index_bbox(source_logical, width=width, height=height) != bbox:
            raise WorldMapTitleError(f"member {member} duplicate title geometry drift")
        same_text = entry["source"] == entry["translation"]
        if same_text:
            output_stored = stored
            output_decoded = decoded.output
            encoded_size = decoded.consumed
        else:
            output_raw = pack_vertical_linear_4bpp(
                replacement,
                width=width,
                height=height,
            )
            modified = bytearray(decoded.output)
            modified[japanese_start:japanese_end] = output_raw
            if (
                modified[:japanese_start] != decoded.output[:japanese_start]
                or modified[japanese_end:] != decoded.output[japanese_end:]
                or modified[english_start:english_end] != source_english
            ):
                raise WorldMapTitleError(
                    f"member {member} changed bytes outside Japanese title"
                )
            encoded = reencode_changed_suffix(
                stored,
                bytes(modified),
                strategy="rust-fit",
                min_match_length=min_match_length,
                max_match_chain=max_match_chain,
                max_output_size=len(stored),
            )
            encoded_size = len(encoded)
            output_stored = encoded + bytes(len(stored) - encoded_size)
            reread = decode(output_stored)
            if (
                reread.output != bytes(modified)
                or reread.consumed != encoded_size
                or any(output_stored[encoded_size:])
            ):
                raise WorldMapTitleError(
                    f"member {member} compressed round-trip failed"
                )
            output_decoded = reread.output
        if len(output_stored) != len(stored):
            raise WorldMapTitleError(f"member {member} allocation size changed")
        if output_decoded[english_start:english_end] != source_english:
            raise WorldMapTitleError(f"member {member} English subtitle changed")
        if (
            output_decoded[:japanese_start] != decoded.output[:japanese_start]
            or output_decoded[japanese_end:] != decoded.output[japanese_end:]
        ):
            raise WorldMapTitleError(f"member {member} non-title bytes changed")
        if same_text and output_stored != stored:
            raise WorldMapTitleError(f"member {member} no-op was re-encoded")
        output_archive[start:end] = output_stored
        headroom = len(stored) - encoded_size
        all_headrooms.append(headroom)
        if not same_text:
            translated_headrooms.append(headroom)
        member_reports.append(
            {
                "member": member,
                "entry_id": entry["id"],
                "same_text_no_op": same_text,
                "stored_size": len(stored),
                "source_encoded_size": decoded.consumed,
                "output_encoded_size": encoded_size,
                "compressed_headroom": headroom,
                "source_stored_sha256": sha256_bytes(stored),
                "output_stored_sha256": sha256_bytes(output_stored),
                "source_decoded_sha256": sha256_bytes(decoded.output),
                "output_decoded_sha256": sha256_bytes(output_decoded),
                "source_title_raw_sha256": sha256_bytes(source_raw),
                "output_title_raw_sha256": sha256_bytes(
                    output_decoded[japanese_start:japanese_end]
                ),
            }
        )

    output = bytes(output_archive)
    if (
        len(output) != len(original_archive)
        or output[: offsets[first_member]] != original_archive[: offsets[first_member]]
        or output[offsets[last_member + 1] :]
        != original_archive[offsets[last_member + 1] :]
    ):
        raise WorldMapTitleError("MAPMODEL non-target archive bytes changed")

    preview_report = None
    if preview_root is not None:
        preview_path, preview_data = _write_preview(
            executable,
            preview_root,
            preview_rows,
            width=width,
            height=height,
        )
        preview_report = {
            "path": _display_path(project_root, preview_path),
            "size": len(preview_data),
            "sha256": sha256_bytes(preview_data),
            "row_order": [entry["id"] for entry in entries],
        }

    no_op_titles = len(entries) - translated_unique_count
    no_op_members = sum(
        len(entry["members"])
        for entry in entries
        if entry["source"] == entry["translation"]
    )
    report = {
        "unique_title_count": len(entries),
        "translated_unique_title_count": translated_unique_count,
        "same_text_unique_title_count": no_op_titles,
        "member_count": len(expected_members),
        "translated_member_count": translated_member_count,
        "same_text_member_count": no_op_members,
        "member_range": [first_member, last_member],
        "texture": {
            "width": width,
            "height": height,
            "bits_per_pixel": 4,
            "storage": texture.get("storage"),
            "japanese_raw_range": [japanese_start, japanese_end],
            "english_raw_range": [english_start, english_end],
            "english_raw_sha256": english_hash,
        },
        "font": {
            "flavor": font_flavor_metadata(flavor),
            "primary_path": _display_path(project_root, font_path),
            "primary_sha256": sha256_bytes(font_path.read_bytes()),
            "fallbacks": list(fallback_reports),
        },
        "render": {
            "imagemagick_version": version,
            "max_point_size": max_point_size,
            "min_point_size": min_point_size,
            "kerning_candidates": list(kerning_candidates),
            "hinting": hinting,
            "antialias": antialias,
            "clear_policy": "source_nonzero_bbox_only",
            "placement_policy": "center_tight_target_bbox_inside_source_bbox",
        },
        "codec": {
            "strategy": "rust-fit",
            "min_match_length": min_match_length,
            "max_match_chain": max_match_chain,
            "minimum_translated_member_headroom": min(translated_headrooms),
            "minimum_all_member_headroom": min(all_headrooms),
        },
        "titles": title_reports,
        "members": member_reports,
        "preview": preview_report,
        "archive_size_preserved": len(output) == len(original_archive),
        "top_level_offsets_preserved": True,
        "non_title_members_preserved_byte_exact": (
            output[: offsets[first_member]] == original_archive[: offsets[first_member]]
        ),
        "non_title_decoded_bytes_preserved": True,
        "english_subtitle_preserved_byte_exact": True,
        "same_text_members_preserved_byte_exact": all(
            item["source_stored_sha256"] == item["output_stored_sha256"]
            for item in member_reports
            if item["same_text_no_op"]
        ),
        "compressed_chunks_fit_allocations": all(
            item["compressed_headroom"] >= 0 for item in member_reports
        ),
        "codec_round_trip_exact": True,
        "output_archive_sha256": sha256_bytes(output),
    }
    return output, report, {
        "original_slps": original_slps_path,
        "original_archive": original_archive_path,
        "corpus": corpus_path,
    }


__all__ = [
    "WorldMapTitleError",
    "build_world_map_titles",
    "index_bbox",
    "pack_vertical_linear_4bpp",
    "render_title_inside_bbox",
    "replace_title_inside_bbox",
    "unpack_vertical_linear_4bpp",
]
