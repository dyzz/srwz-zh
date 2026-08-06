"""Fail-closed construction of the first static SRWZ Chinese canary."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Union

from .codec import decode, reencode_changed_suffix
from .corpus import text_sha256
from .font import (
    GLYPH_COUNT,
    GLYPH_HEIGHT,
    GLYPH_SIZE,
    GLYPH_WIDTH,
    decode_vt1_font_segment,
    encode_glyph,
    is_cjk_unified_ideograph,
    render_glyph_grid,
    replace_glyph,
    sha256_bytes,
    standard_glyph_index,
)
from .iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from .patch_audit import summarize_diff
from .project import (
    ProjectConfigError,
    load_build_profile,
    validate_profile_encoding,
)
from .text import TextTable, decode_text, encode_text, load_text_table
from .writeback import PatchOperation, PatchPlan
from .writers import build_executable_offset_patch_plan


class CanaryError(ValueError):
    """The static canary violates a pinned source or renderer contract."""


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_project_path(project_root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else project_root / path


def verify_file(path: Path, expected: Mapping, *, context: str) -> None:
    if not path.is_file():
        raise CanaryError(f"{context} is missing: {path}")
    size = expected.get("size")
    if not isinstance(size, int) or path.stat().st_size != size:
        raise CanaryError(f"{context} size mismatch")
    if sha256_path(path) != expected.get("sha256"):
        raise CanaryError(f"{context} SHA-256 mismatch")


def quantize_gray_4bpp(gray: bytes) -> bytes:
    """Quantize 8-bit gray to 0..15 with integer round-to-nearest."""

    return bytes((value * 15 + 127) // 255 for value in gray)


def double_byte_width_class(code: int) -> str:
    """Classify only the width split relevant to the selected canary.

    The original measurement path at 0x139CB8..0x139CF4 optionally uses
    an alternate width for 0x8140..0x889E.  Both the source and canary
    codes are above that range and therefore use the same default width.
    """

    if not 0 <= code <= 0xFFFF:
        raise ValueError("text code is outside two bytes")
    if 0x8140 <= code < 0x889F:
        return "conditional_double_byte"
    return "default_double_byte"


def rasterizer_version(executable: str) -> str:
    try:
        result = subprocess.run(
            (executable, "-version"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CanaryError(f"cannot run rasterizer {executable}") from error
    return result.stdout.splitlines()[0]


def rasterizer_point_size(
    character: str,
    rasterizer: Mapping,
) -> Union[int, float]:
    """Resolve the one uniform point size used by the rasterizer."""

    if not isinstance(character, str) or len(character) != 1:
        raise CanaryError("glyph point-size lookup needs one character")
    point_size = rasterizer.get("point_size")
    if (
        not isinstance(point_size, (int, float))
        or isinstance(point_size, bool)
        or not float("-inf") < point_size < float("inf")
        or point_size <= 0
    ):
        raise CanaryError(
            "rasterizer point size must be a finite positive number"
        )
    corrections = rasterizer.get("optical_corrections", {})
    if not isinstance(corrections, Mapping):
        raise CanaryError("rasterizer optical corrections must be a mapping")
    if corrections:
        raise CanaryError(
            "per-character optical corrections are forbidden; use the "
            "uniform CJK bounding-box normalization"
        )
    return point_size


def _cjk_bbox_normalization(rasterizer: Mapping) -> dict | None:
    """Validate and return the uniform CJK bounding-box normalization rule."""

    raw = rasterizer.get("cjk_bbox_normalization")
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {
        "source_canvas_size",
        "source_point_size",
        "trim_threshold",
        "target_bbox_size",
        "resize_filter",
        "reason",
    }:
        raise CanaryError("CJK bounding-box normalization is malformed")
    source_canvas_size = raw["source_canvas_size"]
    source_point_size = raw["source_point_size"]
    trim_threshold = raw["trim_threshold"]
    target_bbox_size = raw["target_bbox_size"]
    resize_filter = raw["resize_filter"]
    reason = raw["reason"]
    if (
        not isinstance(source_canvas_size, int)
        or isinstance(source_canvas_size, bool)
        or source_canvas_size < GLYPH_WIDTH
        or not isinstance(source_point_size, (int, float))
        or isinstance(source_point_size, bool)
        or not float("-inf") < source_point_size < float("inf")
        or source_point_size <= 0
        or not isinstance(trim_threshold, int)
        or isinstance(trim_threshold, bool)
        or not 0 <= trim_threshold < 255
        or not isinstance(target_bbox_size, int)
        or isinstance(target_bbox_size, bool)
        or not 1 <= target_bbox_size <= min(GLYPH_WIDTH, GLYPH_HEIGHT) - 2
        or not isinstance(resize_filter, str)
        or not resize_filter.strip()
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise CanaryError("CJK bounding-box normalization is invalid")
    corrections = rasterizer.get("optical_corrections", {})
    if corrections:
        raise CanaryError(
            "CJK bounding-box normalization forbids optical corrections"
        )
    return dict(raw)


def _cjk_fixed_canvas(rasterizer: Mapping) -> dict | None:
    """Validate the shared CJK em canvas used by the production font."""

    raw = rasterizer.get("cjk_fixed_canvas")
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != {
        "x_offset",
        "y_offset",
        "reason",
    }:
        raise CanaryError("CJK fixed-canvas policy is malformed")
    x_offset = raw["x_offset"]
    y_offset = raw["y_offset"]
    reason = raw["reason"]
    if (
        not isinstance(x_offset, int)
        or isinstance(x_offset, bool)
        or not -GLYPH_WIDTH < x_offset < GLYPH_WIDTH
        or not isinstance(y_offset, int)
        or isinstance(y_offset, bool)
        or not -GLYPH_HEIGHT < y_offset < GLYPH_HEIGHT
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise CanaryError("CJK fixed-canvas policy is invalid")
    if rasterizer.get("cjk_bbox_normalization") is not None:
        raise CanaryError(
            "CJK fixed canvas and bounding-box normalization are mutually "
            "exclusive"
        )
    corrections = rasterizer.get("optical_corrections", {})
    if corrections:
        raise CanaryError("CJK fixed canvas forbids optical corrections")
    return dict(raw)


def _rasterize_fixed_canvas_cjk(
    executable: str,
    font_path: Path,
    character: str,
    rasterizer: Mapping,
    fixed_canvas: Mapping,
) -> bytes:
    """Render one CJK glyph without character-specific trim or scaling."""

    geometry = (
        f"{fixed_canvas['x_offset']:+d}{fixed_canvas['y_offset']:+d}"
    )
    command = [
        executable,
        "-size",
        f"{GLYPH_WIDTH}x{GLYPH_HEIGHT}",
        "xc:black",
        "-fill",
        "white",
        "-density",
        str(rasterizer["density"]),
        "-units",
        "PixelsPerInch",
        "-font",
        str(font_path),
        "-pointsize",
        str(rasterizer["point_size"]),
        "-define",
        f"type:hinting={'true' if rasterizer['hinting'] else 'false'}",
        "-antialias" if rasterizer["antialias"] else "+antialias",
        "-gravity",
        rasterizer["gravity"],
        "-annotate",
        geometry,
        character,
        "-colorspace",
        "Gray",
        "-depth",
        "8",
        "gray:-",
    ]
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode(
            "utf-8",
            errors="replace",
        )
        raise CanaryError(
            f"CJK fixed-canvas rasterizer failed for {character!r}: "
            f"{detail}"
        ) from error


def _occupied_bbox(
    gray: bytes,
    *,
    width: int,
    height: int,
    threshold: int,
) -> tuple[int, int, int, int]:
    occupied = [
        (index % width, index // width)
        for index, value in enumerate(gray)
        if value > threshold
    ]
    if not occupied:
        raise CanaryError("CJK raster is empty after trim threshold")
    xs = [x for x, _ in occupied]
    ys = [y for _, y in occupied]
    return min(xs), min(ys), max(xs), max(ys)


def _crop_gray(
    gray: bytes,
    *,
    canvas_size: int,
    bbox: tuple[int, int, int, int],
) -> tuple[bytes, int, int]:
    left, top, right, bottom = bbox
    width = right - left + 1
    height = bottom - top + 1
    cropped = bytearray(width * height)
    for row in range(height):
        source_start = (top + row) * canvas_size + left
        target_start = row * width
        cropped[target_start : target_start + width] = gray[
            source_start : source_start + width
        ]
    return bytes(cropped), width, height


def normalized_cjk_bbox_size(
    source_width: int,
    source_height: int,
    normalization: Mapping,
) -> tuple[int, int]:
    target = normalization["target_bbox_size"]
    scale = min(target / source_width, target / source_height)

    def round_half_up(value: float) -> int:
        return max(1, int(value + 0.5))

    width = round_half_up(source_width * scale)
    height = round_half_up(source_height * scale)
    return width, height


def _rasterize_normalized_cjk(
    executable: str,
    font_path: Path,
    character: str,
    rasterizer: Mapping,
    normalization: Mapping,
) -> bytes:
    canvas_size = normalization["source_canvas_size"]
    source_command = [
        executable,
        "-background",
        "black",
        "-fill",
        "white",
        "-density",
        str(rasterizer["density"]),
        "-units",
        "PixelsPerInch",
        "-font",
        str(font_path),
        "-pointsize",
        str(normalization["source_point_size"]),
        "-define",
        f"type:hinting={'true' if rasterizer['hinting'] else 'false'}",
        "-antialias" if rasterizer["antialias"] else "+antialias",
        "-gravity",
        rasterizer["gravity"],
        "-size",
        f"{canvas_size}x{canvas_size}",
        f"label:{character}",
        "-colorspace",
        "Gray",
        "-depth",
        "8",
        "gray:-",
    ]
    try:
        source = subprocess.run(
            source_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode(
            "utf-8",
            errors="replace",
        )
        raise CanaryError(
            f"CJK source rasterizer failed for {character!r}: {detail}"
        ) from error
    if len(source) != canvas_size * canvas_size:
        raise CanaryError(
            f"CJK source rasterizer returned {len(source)} bytes for "
            f"{character!r}"
        )
    cropped, source_width, source_height = _crop_gray(
        source,
        canvas_size=canvas_size,
        bbox=_occupied_bbox(
            source,
            width=canvas_size,
            height=canvas_size,
            threshold=normalization["trim_threshold"],
        ),
    )
    target_width, target_height = normalized_cjk_bbox_size(
        source_width,
        source_height,
        normalization,
    )
    resize_command = [
        executable,
        "-size",
        f"{source_width}x{source_height}",
        "-depth",
        "8",
        "gray:-",
        "-filter",
        normalization["resize_filter"],
        "-resize",
        f"{target_width}x{target_height}!",
        "-gravity",
        "center",
        "-background",
        "black",
        "-extent",
        f"{GLYPH_WIDTH}x{GLYPH_HEIGHT}",
        "-colorspace",
        "Gray",
        "-depth",
        "8",
        "gray:-",
    ]
    try:
        return subprocess.run(
            resize_command,
            input=cropped,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode(
            "utf-8",
            errors="replace",
        )
        raise CanaryError(
            f"CJK resize failed for {character!r}: {detail}"
        ) from error


def rasterize_character(
    executable: str,
    font_path: Path,
    character: str,
    rasterizer: Mapping,
) -> tuple[bytes, bytes, bytes]:
    if len(character) != 1:
        raise CanaryError("canary glyph must contain one character")
    hinting = rasterizer.get("hinting")
    antialias = rasterizer.get("antialias")
    if not isinstance(hinting, bool) or not isinstance(antialias, bool):
        raise CanaryError("rasterizer hinting/antialias lock is invalid")
    point_size = rasterizer_point_size(character, rasterizer)
    if character == " ":
        gray = bytes(GLYPH_WIDTH * GLYPH_HEIGHT)
        pixels = quantize_gray_4bpp(gray)
        return gray, pixels, encode_glyph(pixels)
    fixed_canvas = _cjk_fixed_canvas(rasterizer)
    normalization = _cjk_bbox_normalization(rasterizer)
    if fixed_canvas is not None:
        gray = _rasterize_fixed_canvas_cjk(
            executable,
            font_path,
            character,
            rasterizer,
            fixed_canvas,
        )
        if len(gray) != GLYPH_WIDTH * GLYPH_HEIGHT:
            raise CanaryError(
                f"fixed-canvas rasterizer returned {len(gray)} bytes "
                f"for {character!r}"
            )
        pixels = quantize_gray_4bpp(gray)
        return gray, pixels, encode_glyph(pixels)
    if normalization is not None and is_cjk_unified_ideograph(character):
        gray = _rasterize_normalized_cjk(
            executable,
            font_path,
            character,
            rasterizer,
            normalization,
        )
        if len(gray) != GLYPH_WIDTH * GLYPH_HEIGHT:
            raise CanaryError(
                f"CJK normalizer returned {len(gray)} bytes for {character!r}"
            )
        pixels = quantize_gray_4bpp(gray)
        return gray, pixels, encode_glyph(pixels)
    command = [
        executable,
        "-background",
        "black",
        "-fill",
        "white",
        "-density",
        str(rasterizer["density"]),
        "-units",
        "PixelsPerInch",
        "-font",
        str(font_path),
        "-pointsize",
        str(point_size),
        "-define",
        f"type:hinting={'true' if hinting else 'false'}",
        "-antialias" if antialias else "+antialias",
        "-gravity",
        rasterizer["gravity"],
        "-size",
        f"{GLYPH_WIDTH}x{GLYPH_HEIGHT}",
        f"label:{character}",
        "-colorspace",
        "Gray",
        "-depth",
        "8",
        "gray:-",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode(
            "utf-8",
            errors="replace",
        )
        raise CanaryError(
            f"rasterizer failed for {character!r}: {detail}"
        ) from error
    gray = result.stdout
    if len(gray) != GLYPH_WIDTH * GLYPH_HEIGHT:
        raise CanaryError(
            f"rasterizer returned {len(gray)} bytes for {character!r}"
        )
    pixels = quantize_gray_4bpp(gray)
    packed = encode_glyph(pixels)
    return gray, pixels, packed


def rebuild_archive_with_replacement(
    archive: bytes,
    offsets: Iterable[int],
    *,
    chunk_index: int,
    encoded_replacement: bytes,
    alignment: int = 16,
    minimum_allocation: int = 0,
) -> tuple[bytes, tuple[int, ...], int]:
    offsets = tuple(offsets)
    if len(offsets) < 2:
        raise CanaryError("archive offsets have no chunks")
    if not 0 <= chunk_index < len(offsets) - 1:
        raise CanaryError("replacement chunk index is outside archive")
    if offsets[0] != 0 or offsets[-1] != len(archive):
        raise CanaryError("archive offsets do not cover the source")
    if alignment <= 0 or alignment & (alignment - 1):
        raise CanaryError("archive alignment must be a power of two")
    if minimum_allocation < 0 or minimum_allocation % alignment:
        raise CanaryError(
            "minimum archive allocation must be aligned and non-negative"
        )
    if any(offset % alignment for offset in offsets):
        raise CanaryError("source archive offsets are not aligned")

    replacement_size = max(
        (len(encoded_replacement) + alignment - 1) & -alignment,
        minimum_allocation,
    )
    replacement_padding = replacement_size - len(encoded_replacement)
    replacement = encoded_replacement + bytes(replacement_padding)
    output = bytearray()
    new_offsets = []
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        new_offsets.append(len(output))
        if index == chunk_index:
            output.extend(replacement)
        else:
            output.extend(archive[start:end])
    new_offsets.append(len(output))
    if any(offset % alignment for offset in new_offsets):
        raise CanaryError("rebuilt archive offsets are not aligned")
    return bytes(output), tuple(new_offsets), replacement_padding


def verify_reserved_codes_absent(
    corpus_path: Path,
    table: TextTable,
    codes: Iterable[int],
    *,
    expected_entry_count: int,
) -> int:
    reserved = frozenset(codes)
    count = 0
    with corpus_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            text = row.get("source_text")
            if not isinstance(text, str):
                raise CanaryError(
                    f"corpus row {line_number} has no source_text"
                )
            encoded = encode_text(text, table)
            current = 0
            while current < len(encoded):
                first = encoded[current]
                if 0x31 <= first <= 0x35:
                    current += 2
                    continue
                if (
                    0x80 <= first <= 0x9F
                    or 0xE0 <= first <= 0xEA
                ):
                    if current + 1 >= len(encoded):
                        raise CanaryError(
                            f"corpus row {line_number} ends in a lead byte"
                        )
                    code = (first << 8) | encoded[current + 1]
                    if code in reserved:
                        raise CanaryError(
                            f"reserved code {code:04X} occurs in "
                            f"corpus row {line_number}"
                        )
                    current += 2
                    continue
                current += 1
            count += 1
    if count != expected_entry_count:
        raise CanaryError(
            f"corpus entry count mismatch: "
            f"expected {expected_entry_count}, got {count}"
        )
    return count


def _load_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise CanaryError(f"unsupported schema: {path}")
    return document


def _verify_raster_hashes(
    gray: bytes,
    pixels: bytes,
    packed: bytes,
    expected: Mapping,
    *,
    character: str,
) -> None:
    actual = {
        "raw_gray_sha256": sha256_bytes(gray),
        "pixels_4bpp_sha256": sha256_bytes(pixels),
        "packed_glyph_sha256": sha256_bytes(packed),
    }
    for field, digest in actual.items():
        if digest != expected.get(field):
            raise CanaryError(
                f"{character!r} {field} mismatch: "
                f"expected {expected.get(field)}, got {digest}"
            )


def build_static_canary(
    project_root: Path,
    config_path: Path,
    *,
    enforce_expected_outputs: bool = True,
) -> tuple[bytes, bytes, bytes, dict]:
    project_root = project_root.resolve()
    config = _load_json(config_path)
    if config.get("status") != "static_candidate_not_runtime_verified":
        raise CanaryError("canary status must remain static-only")
    renderer_contract = config.get("renderer_contract", {})
    if renderer_contract.get("runtime_hooks") != []:
        raise CanaryError("minimal canary must not declare runtime hooks")
    if renderer_contract.get("code_injection") is not False:
        raise CanaryError("minimal canary must not inject executable code")

    inputs = config["inputs"]
    slps_path = resolve_project_path(
        project_root,
        inputs["slps"]["path"],
    )
    vt1_path = resolve_project_path(
        project_root,
        inputs["vt1"]["path"],
    )
    verify_file(slps_path, inputs["slps"], context="SLPS input")
    verify_file(vt1_path, inputs["vt1"], context="VT1 input")

    font_lock_path = resolve_project_path(
        project_root,
        inputs["font_lock"],
    )
    font_lock = _load_json(font_lock_path)
    if font_lock.get("repository") != (
        "https://github.com/notofonts/noto-cjk.git"
    ):
        raise CanaryError("canary font is not from official Noto CJK")
    if font_lock.get("license", {}).get("spdx") != "OFL-1.1":
        raise CanaryError("canary font license is not OFL-1.1")
    font_path = resolve_project_path(
        project_root,
        font_lock["font"]["path"],
    )
    license_path = resolve_project_path(
        project_root,
        font_lock["license"]["path"],
    )
    verify_file(font_path, font_lock["font"], context="font source")
    verify_file(license_path, font_lock["license"], context="font license")

    rasterizer = config["rasterizer"]
    executable = rasterizer["executable"]
    actual_version = rasterizer_version(executable)
    if actual_version != rasterizer["version_line"]:
        raise CanaryError(
            "rasterizer version mismatch: "
            f"expected {rasterizer['version_line']!r}, "
            f"got {actual_version!r}"
        )

    table_path = resolve_project_path(
        project_root,
        inputs["text_table"]["path"],
    )
    table = load_text_table(table_path)
    try:
        profile_path = resolve_project_path(
            project_root,
            config["profile"],
        )
        selection = load_build_profile(project_root, profile_path)
        surface = selection.single_surface()
        decision = selection.translation_for(surface.entry_id)
        profile_validation = validate_profile_encoding(selection, table)
    except (KeyError, ProjectConfigError) as error:
        raise CanaryError(f"invalid canary build profile: {error}") from error
    if surface.source_member != "SLPS_258.87":
        raise CanaryError("canary surface must target SLPS_258.87")
    if surface.writer_kind != "fixed_preimage":
        raise CanaryError("canary surface must use fixed_preimage writer")
    if not surface.require_equal_encoded_size:
        raise CanaryError("canary surface must require equal encoded size")
    glyph_locks = [
        assignment.to_glyph_lock()
        for assignment in selection.assignments
    ]
    assigned_codes = tuple(
        int(glyph["code"], 16) for glyph in glyph_locks
    )
    candidate_range = config["font_segment"][
        "static_blank_candidate_range"
    ]
    candidate_codes = tuple(
        range(
            int(candidate_range["code_start"], 0),
            int(candidate_range["code_end_inclusive"], 0) + 1,
        )
    )
    candidate_glyphs = tuple(
        range(
            candidate_range["glyph_start"],
            candidate_range["glyph_end_inclusive"] + 1,
        )
    )
    if (
        len(candidate_codes) != candidate_range["count"]
        or len(candidate_glyphs) != candidate_range["count"]
        or tuple(
            standard_glyph_index(code) for code in candidate_codes
        )
        != candidate_glyphs
    ):
        raise CanaryError("static blank candidate range is invalid")
    if not set(assigned_codes).issubset(candidate_codes):
        raise CanaryError("assigned codes are outside candidate range")
    if len(assigned_codes) != len(set(assigned_codes)):
        raise CanaryError("assigned canary codes are not unique")
    assigned_characters = tuple(
        glyph["character"] for glyph in glyph_locks
    )
    if len(assigned_characters) != len(set(assigned_characters)):
        raise CanaryError("assigned canary characters are not unique")
    codes = candidate_codes
    if len(codes) != len(set(codes)):
        raise CanaryError("canary codes are not unique")
    if any(code in table.characters for code in codes):
        raise CanaryError(
            "static candidate code conflicts with the pinned text table"
        )

    parse_path = resolve_project_path(
        project_root,
        inputs["parse_report"]["path"],
    )
    parse_report = _load_json(parse_path)
    unknown_count = parse_report["totals"]["unknown_text_codes"]
    if unknown_count != inputs["parse_report"]["unknown_text_codes"]:
        raise CanaryError("parsed unknown-text-code count changed")
    corpus_path = resolve_project_path(
        project_root,
        inputs["corpus"]["path"],
    )
    corpus_count = verify_reserved_codes_absent(
        corpus_path,
        table,
        codes,
        expected_entry_count=inputs["corpus"]["entry_count"],
    )

    slps = slps_path.read_bytes()
    vt1 = vt1_path.read_bytes()
    source_texts = []
    for offset in surface.offsets:
        decoded_source = decode_text(slps, offset, table)
        if (
            decoded_source.consumed
            != surface.encoded_size_with_terminator
        ):
            raise CanaryError(
                f"surface source size mismatch at 0x{offset:X}"
            )
        if text_sha256(decoded_source.text) != surface.source_text_sha256:
            raise CanaryError(
                f"surface source hash mismatch at 0x{offset:X}"
            )
        source_texts.append(decoded_source.text)
    if len(set(source_texts)) != 1:
        raise CanaryError("surface offsets decode to different source text")
    text_patch = {
        "entry_id": surface.entry_id,
        "source_text": source_texts[0],
        "replacement_text": decision.translation,
        "offsets": list(surface.offsets),
        "encoded_size_with_terminator": (
            surface.encoded_size_with_terminator
        ),
    }
    instruction_reports = []
    for window in renderer_contract["instruction_windows"]:
        virtual_start = int(window["virtual_start"], 0)
        virtual_end = int(window["virtual_end"], 0)
        file_offset = int(window["file_offset"], 0)
        size = window["size"]
        if virtual_end - virtual_start != size:
            raise CanaryError(
                f"{window['id']} virtual instruction size mismatch"
            )
        if virtual_start - 0x000FE580 != file_offset:
            raise CanaryError(
                f"{window['id']} ELF file-offset mapping mismatch"
            )
        source_window = slps[file_offset:file_offset + size]
        if (
            len(source_window) != size
            or sha256_bytes(source_window) != window["sha256"]
        ):
            raise CanaryError(
                f"{window['id']} instruction preimage mismatch"
            )
        instruction_reports.append(
            {
                **window,
                "source_preimage_exact": True,
            }
        )
    segment_lock = config["font_segment"]
    original_font = decode_vt1_font_segment(
        slps,
        vt1,
        segment_index=segment_lock["index"],
    )
    if len(original_font.decoded) != segment_lock["decoded_size"]:
        raise CanaryError("decoded font size mismatch")
    if sha256_bytes(original_font.decoded) != segment_lock["decoded_sha256"]:
        raise CanaryError("decoded font SHA-256 mismatch")

    modified_font = original_font.decoded
    glyph_reports = []
    glyph_indices = []
    character_overrides = {}
    blank_digest = segment_lock["blank_glyph_sha256"]
    for code, index in zip(candidate_codes, candidate_glyphs):
        start = index * GLYPH_SIZE
        candidate = original_font.decoded[start:start + GLYPH_SIZE]
        if sha256_bytes(candidate) != blank_digest or any(candidate):
            raise CanaryError(
                f"candidate code {code:04X} glyph {index} is not blank"
            )
    for glyph_lock in glyph_locks:
        character = glyph_lock["character"]
        code = int(glyph_lock["code"], 16)
        index = glyph_lock["glyph_index"]
        if standard_glyph_index(code) != index:
            raise CanaryError(
                f"{character!r} code does not resolve to glyph {index}"
            )
        if not 0 <= index < GLYPH_COUNT:
            raise CanaryError(f"{character!r} glyph index is invalid")
        start = index * GLYPH_SIZE
        before = modified_font[start:start + GLYPH_SIZE]
        if sha256_bytes(before) != blank_digest or any(before):
            raise CanaryError(
                f"{character!r} glyph preimage is not the pinned blank"
            )
        gray, pixels, packed = rasterize_character(
            executable,
            font_path,
            character,
            rasterizer,
        )
        _verify_raster_hashes(
            gray,
            pixels,
            packed,
            glyph_lock,
            character=character,
        )
        modified_font = replace_glyph(modified_font, index, pixels)
        glyph_indices.append(index)
        character_overrides[character] = code
        glyph_reports.append(
            {
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": index,
                "blank_preimage_sha256": blank_digest,
                "raw_gray_sha256": sha256_bytes(gray),
                "pixels_4bpp_sha256": sha256_bytes(pixels),
                "packed_glyph_sha256": sha256_bytes(packed),
            }
        )

    changed_glyphs = tuple(
        index
        for index in range(GLYPH_COUNT)
        if (
            original_font.decoded[
                index * GLYPH_SIZE:(index + 1) * GLYPH_SIZE
            ]
            != modified_font[
                index * GLYPH_SIZE:(index + 1) * GLYPH_SIZE
            ]
        )
    )
    if changed_glyphs != tuple(glyph_indices):
        raise CanaryError("decoded font changed outside assigned glyphs")

    vt1_spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
    old_offsets = read_executable_archive_offsets(
        slps,
        vt1_spec,
        len(vt1),
    )
    font_stream = vt1[
        old_offsets[segment_lock["index"]]:
        old_offsets[segment_lock["index"] + 1]
    ]
    encoded_font = reencode_changed_suffix(
        font_stream,
        modified_font,
    )
    decoded_check = decode(encoded_font)
    if decoded_check.output != modified_font:
        raise CanaryError("encoded canary font does not round-trip")
    if decoded_check.consumed != len(encoded_font):
        raise CanaryError("encoded canary font consumed length mismatch")

    rebuilt_vt1, new_offsets, font_padding = (
        rebuild_archive_with_replacement(
            vt1,
            old_offsets,
            chunk_index=segment_lock["index"],
            encoded_replacement=encoded_font,
        )
    )

    source_payload = encode_text(
        text_patch["source_text"],
        table,
        terminate=True,
    )
    replacement_payload = encode_text(
        text_patch["replacement_text"],
        table,
        overrides=character_overrides,
        terminate=True,
    )
    expected_size = text_patch["encoded_size_with_terminator"]
    if (
        len(source_payload) != expected_size
        or len(replacement_payload) != expected_size
    ):
        raise CanaryError("canary text is not an exact-size replacement")
    source_codes = tuple(
        int.from_bytes(source_payload[index:index + 2], "big")
        for index in range(0, len(source_payload) - 1, 2)
    )
    replacement_codes = tuple(
        int.from_bytes(replacement_payload[index:index + 2], "big")
        for index in range(0, len(replacement_payload) - 1, 2)
    )
    if (
        tuple(double_byte_width_class(code) for code in source_codes)
        != tuple(
            double_byte_width_class(code) for code in replacement_codes
        )
    ):
        raise CanaryError("canary changes the measured width class")

    text_operations = []
    for offset in text_patch["offsets"]:
        if slps[offset:offset + expected_size] != source_payload:
            raise CanaryError(
                f"canary text preimage mismatch at 0x{offset:X}"
            )
        text_operations.append(
            PatchOperation(
                owner=text_patch["entry_id"],
                offset=offset,
                before=source_payload,
                after=replacement_payload,
            )
        )
    offset_plan = build_executable_offset_patch_plan(
        slps,
        vt1_spec,
        new_offsets,
    )
    slps_plan = PatchPlan(
        source_name="SLPS_258.87",
        source_size=len(slps),
        source_sha256=sha256_bytes(slps),
        operations=tuple(text_operations) + offset_plan.operations,
    )
    rebuilt_slps = slps_plan.apply(slps)
    for window in instruction_reports:
        file_offset = int(window["file_offset"], 0)
        size = window["size"]
        if rebuilt_slps[file_offset:file_offset + size] != (
            slps[file_offset:file_offset + size]
        ):
            raise CanaryError(
                f"{window['id']} instruction bytes changed"
            )
        window["output_unchanged"] = True

    reread_offsets = read_executable_archive_offsets(
        rebuilt_slps,
        vt1_spec,
        len(rebuilt_vt1),
    )
    if reread_offsets != new_offsets:
        raise CanaryError("rebuilt VT1 offsets fail SLPS reread")
    rebuilt_font = decode_vt1_font_segment(
        rebuilt_slps,
        rebuilt_vt1,
        segment_index=segment_lock["index"],
    )
    if rebuilt_font.decoded != modified_font:
        raise CanaryError("rebuilt VT1 font segment content mismatch")

    augmented_table = TextTable(
        characters={
            **table.characters,
            **{
                int(glyph["code"], 16): glyph["character"]
                for glyph in glyph_locks
            },
        },
        tags=table.tags,
    )
    for offset in text_patch["offsets"]:
        decoded_text = decode_text(
            rebuilt_slps,
            offset,
            augmented_table,
        )
        if decoded_text.text != text_patch["replacement_text"]:
            raise CanaryError(
                f"canary text reread failed at 0x{offset:X}"
            )

    unchanged_chunks = 0
    for index, (old_start, old_end, new_start, new_end) in enumerate(
        zip(
            old_offsets,
            old_offsets[1:],
            new_offsets,
            new_offsets[1:],
        )
    ):
        if index == segment_lock["index"]:
            continue
        if vt1[old_start:old_end] != rebuilt_vt1[new_start:new_end]:
            raise CanaryError(f"VT1 chunk {index} changed unexpectedly")
        unchanged_chunks += 1

    preview = render_glyph_grid(
        modified_font,
        glyph_indices,
        columns=len(glyph_indices),
        scale=12,
    )
    slps_diff = summarize_diff(slps, rebuilt_slps)
    actual_decoded = sha256_bytes(modified_font)
    if enforce_expected_outputs:
        expected_outputs = config.get("expected_outputs", {})
        expected_decoded = expected_outputs.get("decoded_font_sha256")
        if actual_decoded != expected_decoded:
            raise CanaryError(
                "decoded canary font output SHA-256 mismatch"
            )
        expected_encoded = expected_outputs.get("encoded_font", {})
        if (
            len(encoded_font) != expected_encoded.get("size")
            or sha256_bytes(encoded_font)
            != expected_encoded.get("sha256")
        ):
            raise CanaryError(
                "encoded canary font output does not match the lock"
            )
        expected_slps = expected_outputs.get("slps", {})
        if (
            len(rebuilt_slps) != expected_slps.get("size")
            or sha256_bytes(rebuilt_slps)
            != expected_slps.get("sha256")
            or slps_diff.diff_count != expected_slps.get("diff_count")
            or slps_diff.offsets_sha256
            != expected_slps.get("offsets_sha256")
        ):
            raise CanaryError("canary SLPS output does not match the lock")
        expected_vt1 = expected_outputs.get("vt1", {})
        if (
            len(rebuilt_vt1) != expected_vt1.get("size")
            or sha256_bytes(rebuilt_vt1)
            != expected_vt1.get("sha256")
        ):
            raise CanaryError("canary VT1 output does not match the lock")
        if sha256_bytes(preview) != expected_outputs.get(
            "preview",
            {},
        ).get("sha256"):
            raise CanaryError("canary preview does not match the lock")

    report = {
        "schema_version": 1,
        "status": "static_candidate_not_runtime_verified",
        "content_policy": (
            "Hashes, offsets, counts, assigned characters and build "
            "parameters only; no original or rebuilt game bytes embedded."
        ),
        "runtime_acceptance": "not tested",
        "iso_rebuild": "not performed",
        "production_inputs": selection.to_metadata(),
        "profile_validation": profile_validation,
        "runtime_patch": {
            "hook_count": 0,
            "code_injection": False,
            "reason": (
                "Both reserved codes remain on the original two-byte "
                "standard glyph path and the same default width class as "
                "the replaced text."
            ),
            "instruction_windows": instruction_reports,
        },
        "inputs": {
            "slps": {
                "size": len(slps),
                "sha256": sha256_bytes(slps),
            },
            "vt1": {
                "size": len(vt1),
                "sha256": sha256_bytes(vt1),
            },
            "corpus_entry_count": corpus_count,
            "parsed_unknown_text_code_count": unknown_count,
            "static_candidate_code_scan_count": len(candidate_codes),
        },
        "font_source": {
            "family": font_lock["family"],
            "version": font_lock["version"],
            "commit": font_lock["commit"],
            "font_sha256": font_lock["font"]["sha256"],
            "license_spdx": font_lock["license"]["spdx"],
            "license_sha256": font_lock["license"]["sha256"],
        },
        "rasterizer": {
            **rasterizer,
            "actual_version_line": actual_version,
        },
        "glyphs": glyph_reports,
        "static_blank_candidates": {
            **candidate_range,
            "codes": [f"{code:04X}" for code in candidate_codes],
            "glyph_indices": list(candidate_glyphs),
            "all_blank_preimages_exact": True,
            "codebook_conflict_count": 0,
            "corpus_token_conflict_count": 0,
        },
        "decoded_font": {
            "source_sha256": sha256_bytes(original_font.decoded),
            "output_sha256": sha256_bytes(modified_font),
            "changed_glyph_indices": list(changed_glyphs),
            "changed_glyph_count": len(changed_glyphs),
            "changed_glyphs_outside_assignment": 0,
        },
        "text_patch": {
            "entry_id": text_patch["entry_id"],
            "source_text": text_patch["source_text"],
            "replacement_text": text_patch["replacement_text"],
            "offsets": text_patch["offsets"],
            "encoded_size_with_terminator": expected_size,
            "source_codes": [f"{code:04X}" for code in source_codes],
            "replacement_codes": [
                f"{code:04X}" for code in replacement_codes
            ],
            "width_class_preserved": True,
        },
        "slps_output": {
            "size": len(rebuilt_slps),
            "sha256": sha256_bytes(rebuilt_slps),
            "diff": slps_diff.to_mapping(),
            "patch_plan": slps_plan.to_metadata(),
            "text_reread_exact": True,
        },
        "vt1_output": {
            "size": len(rebuilt_vt1),
            "sha256": sha256_bytes(rebuilt_vt1),
            "old_offset_count": len(old_offsets),
            "new_offset_count": len(new_offsets),
            "offsets_aligned_16": all(
                offset % 16 == 0 for offset in new_offsets
            ),
            "slps_offset_reread_exact": True,
            "replaced_chunk_index": segment_lock["index"],
            "replaced_encoded_size": len(encoded_font),
            "replaced_encoded_sha256": sha256_bytes(encoded_font),
            "replaced_padding_size": font_padding,
            "replaced_decoded_sha256": sha256_bytes(modified_font),
            "replaced_decoded_round_trip_exact": True,
            "unchanged_chunk_count": unchanged_chunks,
        },
        "preview_sha256": sha256_bytes(preview),
    }
    return rebuilt_slps, rebuilt_vt1, preview, report


__all__ = [
    "CanaryError",
    "build_static_canary",
    "double_byte_width_class",
    "normalized_cjk_bbox_size",
    "quantize_gray_4bpp",
    "rasterize_character",
    "rasterizer_point_size",
    "rasterizer_version",
    "rebuild_archive_with_replacement",
    "resolve_project_path",
    "sha256_path",
    "verify_file",
    "verify_reserved_codes_absent",
]
