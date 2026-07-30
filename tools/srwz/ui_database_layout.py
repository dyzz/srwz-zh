"""Offline layout and exact-glyph review for the P10 UI database slice."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from .chinese_layout import PLAYER_NAME_RENDER_WIDTH, rendered_line_width
from .codec import decode
from .corpus import text_sha256
from .font import (
    GLYPH_HEIGHT,
    GLYPH_SIZE,
    GLYPH_WIDTH,
    ascii_glyph_index,
    decode_glyph,
    decode_vt1_font_segment,
    glyph_index_for_code,
    grayscale_png,
    is_cjk_unified_ideograph,
    read_extended_glyph_table,
    sha256_bytes,
)
from .menu import parse_menu_file
from .text import (
    CONTROL_NOTATION,
    PRINTABLE_ASCII,
    augment_text_table,
    control_notation_positions,
    load_text_table,
)
from .ui_database_selection import (
    UiDatabaseSelectionError,
    select_database_entries,
)
from .ui_menu import UiMenuError, load_ui_font_overrides


class UiDatabaseLayoutError(ValueError):
    """The P10 layout oracle, source envelope or preview has drifted."""


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiDatabaseLayoutError(
            f"cannot load JSON object {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise UiDatabaseLayoutError(f"JSON root must be an object: {path}")
    return value


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise UiDatabaseLayoutError("project path must be non-empty text")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiDatabaseLayoutError(
            f"path escapes project root: {raw}"
        ) from error
    return path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_lock(project_root: Path, path: Path) -> dict:
    resolved = path.resolve()
    return {
        "path": str(resolved.relative_to(project_root.resolve())),
        "size": resolved.stat().st_size,
        "sha256": _sha256_path(resolved),
    }


def _stable_hash(value: object) -> str:
    return sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _verify_reference(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(project_root, reference.get("path"))
    if _sha256_path(path) != reference.get("sha256"):
        raise UiDatabaseLayoutError(f"{label} SHA-256 drift")
    document = _json_object(path)
    for key in ("status", "profile_id", "selection_id", "font_profile_id"):
        expected = reference.get(f"required_{key}")
        if expected is not None and document.get(key) != expected:
            raise UiDatabaseLayoutError(f"{label} {key} drift")
    return path, document


def load_ui_database_layout_config(path: Path) -> dict:
    """Load the strict outer contract for the database layout oracle."""

    document = _json_object(path)
    if document.get("schema_version") != 1:
        raise UiDatabaseLayoutError(
            "unsupported UI database layout schema"
        )
    if not isinstance(document.get("layout_id"), str):
        raise UiDatabaseLayoutError("layout oracle needs a layout_id")
    for key in ("candidate", "source_envelope", "render", "ratchet", "outputs"):
        if not isinstance(document.get(key), dict):
            raise UiDatabaseLayoutError(
                f"layout oracle needs an object: {key}"
            )
    families = document["source_envelope"].get("families")
    if not isinstance(families, list) or not families:
        raise UiDatabaseLayoutError(
            "layout oracle needs source-envelope families"
        )
    family_ids = []
    for family in families:
        if not isinstance(family, dict):
            raise UiDatabaseLayoutError(
                "source-envelope family must be an object"
            )
        family_id = family.get("runtime_scene_id")
        numeric = (
            family.get("expected_entry_count"),
            family.get("expected_source_max_line_cells"),
            family.get("expected_source_max_line_count"),
        )
        if (
            not isinstance(family_id, str)
            or not family_id
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                for value in numeric
            )
        ):
            raise UiDatabaseLayoutError(
                "source-envelope family contract is invalid"
            )
        family_ids.append(family_id)
    if len(family_ids) != len(set(family_ids)):
        raise UiDatabaseLayoutError(
            "source-envelope family IDs must be unique"
        )
    render = document["render"]
    expected_geometry = {
        "glyph_width": GLYPH_WIDTH,
        "glyph_height": GLYPH_HEIGHT,
    }
    if any(render.get(key) != value for key, value in expected_geometry.items()):
        raise UiDatabaseLayoutError(
            "layout preview must use the verified 24x24 glyph geometry"
        )
    for key in ("scale", "entries_per_page", "index_cells", "row_gap"):
        value = render.get(key)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
        ):
            raise UiDatabaseLayoutError(
                f"layout render value must be positive: {key}"
            )
    return document


def _payload(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, bytes]:
    path = _project_path(project_root, reference.get("path"))
    payload = path.read_bytes()
    if {
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    } != {
        "size": reference.get("size"),
        "sha256": reference.get("sha256"),
    }:
        raise UiDatabaseLayoutError(
            f"{label} size or SHA-256 drift"
        )
    return path, payload


def _menu_descriptors(path: Path) -> dict[str, dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UiDatabaseLayoutError(
            "menu descriptor JSON is invalid"
        ) from error
    if not isinstance(value, list):
        raise UiDatabaseLayoutError(
            "menu descriptor root must be a list"
        )
    descriptors = {}
    for friendly_name, member_id in (("SLPS", "slps"), ("Compdata", "compdata")):
        matches = [
            item
            for item in value
            if isinstance(item, dict)
            and item.get("friendly_name") == friendly_name
        ]
        if len(matches) != 1:
            raise UiDatabaseLayoutError(
                f"menu descriptor is not unique: {friendly_name}"
            )
        descriptors[member_id] = matches[0]
    return descriptors


def _assignment_index(proposal: Mapping[str, object]) -> dict[str, dict]:
    raw_assignments = proposal.get("assignments")
    if not isinstance(raw_assignments, list):
        raise UiDatabaseLayoutError(
            "font proposal has no assignments"
        )
    assignments = {}
    identity = {}
    for raw in raw_assignments:
        if not isinstance(raw, dict):
            raise UiDatabaseLayoutError("font assignment is malformed")
        character = raw.get("character")
        code = raw.get("code")
        glyph_index = raw.get("glyph_index")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, str)
            or not isinstance(glyph_index, int)
            or isinstance(glyph_index, bool)
        ):
            raise UiDatabaseLayoutError("font assignment is malformed")
        current_identity = (int(code, 16), glyph_index)
        previous_identity = identity.setdefault(character, current_identity)
        if previous_identity != current_identity:
            raise UiDatabaseLayoutError(
                f"font assignment identity differs: {character}"
            )
        # Reraster assignments are appended after their inherited allocation.
        # The last assignment therefore owns the exact final raster hash.
        assignments[character] = raw
    return assignments


def _glyph_for_character(
    character: str,
    *,
    table,
    overrides: Mapping[str, int],
    extended_entries,
) -> tuple[int, int, str]:
    override = overrides.get(character)
    if override is not None:
        return (
            override,
            glyph_index_for_code(override, extended_entries),
            "codebook_override",
        )
    if character in PRINTABLE_ASCII:
        code = ord(character)
        return code, ascii_glyph_index(code), "printable_ascii"
    code = table.inverse_characters.get(character)
    if code is None:
        raise UiDatabaseLayoutError(
            f"preview character has no text code: {character!r}"
        )
    return code, glyph_index_for_code(code, extended_entries), "text_table"


def _line_units(
    line: str,
    *,
    table,
    overrides: Mapping[str, int],
    extended_entries,
) -> tuple[tuple[str, int | None], ...]:
    units = []
    offset = 0
    while offset < len(line):
        notation = CONTROL_NOTATION.match(line, offset)
        if notation is not None:
            token = notation.group(0)
            if token.startswith(("$", "%")):
                units.extend(
                    ("runtime_placeholder", None)
                    for _ in range(PLAYER_NAME_RENDER_WIDTH)
                )
            offset = notation.end()
            continue
        character = line[offset]
        _code, glyph_index, _source = _glyph_for_character(
            character,
            table=table,
            overrides=overrides,
            extended_entries=extended_entries,
        )
        units.append((character, glyph_index))
        offset += 1
    leading_cells = len(line) - len(line.lstrip("　 "))
    if len(units) != leading_cells + rendered_line_width(line):
        raise UiDatabaseLayoutError(
            f"preview width differs from layout width: {line!r}"
        )
    return tuple(units)


def _blit_glyph(
    canvas: bytearray,
    *,
    canvas_width: int,
    origin_x: int,
    origin_y: int,
    glyph: bytes,
) -> None:
    for y in range(GLYPH_HEIGHT):
        row_start = (origin_y + y) * canvas_width + origin_x
        source_start = y * GLYPH_WIDTH
        for x in range(GLYPH_WIDTH):
            canvas[row_start + x] = glyph[source_start + x] * 17


def _draw_placeholder(
    canvas: bytearray,
    *,
    canvas_width: int,
    origin_x: int,
    origin_y: int,
    value: int,
) -> None:
    inset = 4
    left = origin_x + inset
    right = origin_x + GLYPH_WIDTH - inset - 1
    top = origin_y + inset
    bottom = origin_y + GLYPH_HEIGHT - inset - 1
    for x in range(left, right + 1):
        canvas[top * canvas_width + x] = value
        canvas[bottom * canvas_width + x] = value
    for y in range(top, bottom + 1):
        canvas[y * canvas_width + left] = value
        canvas[y * canvas_width + right] = value


def _nearest_scale(
    pixels: bytes | bytearray,
    width: int,
    height: int,
    scale: int,
) -> tuple[int, int, bytes]:
    if scale == 1:
        return width, height, bytes(pixels)
    scaled_width = width * scale
    scaled = bytearray(scaled_width * height * scale)
    for y in range(height):
        source = pixels[y * width : (y + 1) * width]
        expanded = b"".join(bytes([value]) * scale for value in source)
        for offset in range(scale):
            start = (y * scale + offset) * scaled_width
            scaled[start : start + scaled_width] = expanded
    return scaled_width, height * scale, bytes(scaled)


def render_database_preview_page(
    font: bytes,
    entries: Sequence[Mapping[str, object]],
    *,
    family_budget: int,
    render: Mapping[str, object],
    table,
    overrides: Mapping[str, int],
    extended_entries,
) -> tuple[bytes, dict]:
    """Render one deterministic exact-glyph page for human review."""

    if not entries:
        raise UiDatabaseLayoutError("preview page cannot be empty")
    index_cells = int(render["index_cells"])
    row_gap = int(render["row_gap"])
    scale = int(render["scale"])
    width = (index_cells + family_budget) * GLYPH_WIDTH
    row_heights = [
        max(1, len(str(entry["target_text"]).splitlines()))
        * GLYPH_HEIGHT
        + row_gap
        for entry in entries
    ]
    height = sum(row_heights)
    canvas = bytearray(width * height)
    rule_value = int(render.get("rule_value", 32))
    placeholder_value = int(render.get("placeholder_value", 96))
    if not 0 <= rule_value <= 255 or not 0 <= placeholder_value <= 255:
        raise UiDatabaseLayoutError(
            "preview grayscale values must fit one byte"
        )

    glyph_cache = {}

    def glyph(index: int) -> bytes:
        cached = glyph_cache.get(index)
        if cached is None:
            cached = decode_glyph(font, index)
            glyph_cache[index] = cached
        return cached

    origin_y = 0
    for entry, row_height in zip(entries, row_heights):
        target_text = str(entry["target_text"])
        lines = target_text.splitlines() or [""]
        index_text = f"{int(entry['family_ordinal']):03d} "
        for line_index, line in enumerate(lines):
            prefix = index_text if line_index == 0 else (" " * index_cells)
            units = [
                *_line_units(
                    prefix,
                    table=table,
                    overrides=overrides,
                    extended_entries=extended_entries,
                ),
                *_line_units(
                    line,
                    table=table,
                    overrides=overrides,
                    extended_entries=extended_entries,
                ),
            ]
            if len(units) > index_cells + family_budget:
                raise UiDatabaseLayoutError(
                    f"preview line exceeds family canvas: {entry['entry_id']}"
                )
            line_y = origin_y + line_index * GLYPH_HEIGHT
            for cell, (_label, glyph_index) in enumerate(units):
                cell_x = cell * GLYPH_WIDTH
                if glyph_index is None:
                    _draw_placeholder(
                        canvas,
                        canvas_width=width,
                        origin_x=cell_x,
                        origin_y=line_y,
                        value=placeholder_value,
                    )
                else:
                    _blit_glyph(
                        canvas,
                        canvas_width=width,
                        origin_x=cell_x,
                        origin_y=line_y,
                        glyph=glyph(glyph_index),
                    )
        rule_y = origin_y + row_height - 1
        canvas[rule_y * width : (rule_y + 1) * width] = bytes(
            [rule_value]
        ) * width
        origin_y += row_height

    output_width, output_height, pixels = _nearest_scale(
        canvas,
        width,
        height,
        scale,
    )
    png = grayscale_png(output_width, output_height, pixels)
    return png, {
        "width": output_width,
        "height": output_height,
        "entry_count": len(entries),
    }


def _glyph_metrics(font: bytes, glyph_index: int) -> dict:
    pixels = decode_glyph(font, glyph_index)
    points = [
        (offset % GLYPH_WIDTH, offset // GLYPH_WIDTH)
        for offset, value in enumerate(pixels)
        if value
    ]
    if not points:
        return {
            "ink_pixel_count": 0,
            "bbox": None,
        }
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    left = min(xs)
    top = min(ys)
    right = max(xs)
    bottom = max(ys)
    return {
        "ink_pixel_count": len(points),
        "bbox": {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": right - left + 1,
            "height": bottom - top + 1,
        },
    }


def audit_ui_database_layout(
    project_root: Path,
    config_path: Path,
) -> tuple[dict, dict[str, bytes]]:
    """Audit exact P10 text/glyphs and build deterministic review pages."""

    root = project_root.resolve()
    document = load_ui_database_layout_config(config_path.resolve())
    candidate_reference = document["candidate"]
    config_reference = candidate_reference.get("config")
    manifest_reference = candidate_reference.get("manifest")
    if not isinstance(config_reference, dict) or not isinstance(
        manifest_reference,
        dict,
    ):
        raise UiDatabaseLayoutError(
            "layout candidate references are invalid"
        )
    candidate_config_path, candidate_config = _verify_reference(
        root,
        config_reference,
        label="P10 candidate config",
    )
    candidate_manifest_path, candidate_manifest = _verify_reference(
        root,
        manifest_reference,
        label="P10 candidate manifest",
    )
    if (
        candidate_config.get("profile_id")
        != candidate_manifest.get("profile_id")
        or candidate_manifest.get("runtime", {}).get("status")
        != manifest_reference.get("required_runtime_status")
    ):
        raise UiDatabaseLayoutError(
            "P10 candidate profile or runtime status drift"
        )

    selection_reference = candidate_config["database_selection"]
    selection_config_path = _project_path(
        root,
        selection_reference["config"]["path"],
    )
    selection_manifest_path, selection_manifest = _verify_reference(
        root,
        selection_reference["manifest"],
        label="P10 database selection",
    )
    if (
        _sha256_path(selection_config_path)
        != selection_reference["config"]["sha256"]
    ):
        raise UiDatabaseLayoutError(
            "P10 database selection config SHA-256 drift"
        )
    try:
        decisions, entry_families, selection_metadata = (
            select_database_entries(root, selection_config_path)
        )
    except UiDatabaseSelectionError as error:
        raise UiDatabaseLayoutError(str(error)) from error
    if (
        selection_metadata["selected_entry_ids_sha256"]
        != selection_manifest["selection"]["selected_entry_ids_sha256"]
        or selection_metadata["selected_decisions_sha256"]
        != selection_manifest["selection"]["selected_decisions_sha256"]
    ):
        raise UiDatabaseLayoutError(
            "P10 database selection manifest drift"
        )

    font_manifest_path, font_manifest = _verify_reference(
        root,
        candidate_config["font_extension"]["manifest"],
        label="P10 font manifest",
    )
    writer_config_path = _project_path(
        root,
        candidate_config["writer_baseline_config"]["path"],
    )
    if (
        _sha256_path(writer_config_path)
        != candidate_config["writer_baseline_config"]["sha256"]
    ):
        raise UiDatabaseLayoutError(
            "P10 writer baseline config SHA-256 drift"
        )
    writer_config = _json_object(writer_config_path)
    try:
        overrides, codebook = load_ui_font_overrides(
            root,
            writer_config,
            font_manifest,
        )
    except UiMenuError as error:
        raise UiDatabaseLayoutError(str(error)) from error
    proposal_path = _project_path(
        root,
        font_manifest["proposal"]["path"],
    )
    if _sha256_path(proposal_path) != font_manifest["proposal"]["sha256"]:
        raise UiDatabaseLayoutError(
            "P10 font proposal SHA-256 drift"
        )
    proposal = _json_object(proposal_path)
    proposal_assignments = _assignment_index(proposal)

    candidate_outputs = candidate_manifest.get("outputs")
    if not isinstance(candidate_outputs, dict):
        raise UiDatabaseLayoutError(
            "P10 candidate manifest has no outputs"
        )
    candidate_paths = {}
    candidate_payloads = {}
    for output_id in ("slps", "vt1", "compdata"):
        path, payload = _payload(
            root,
            candidate_outputs[output_id],
            label=f"P10 candidate {output_id}",
        )
        candidate_paths[output_id] = path
        candidate_payloads[output_id] = payload

    base_outputs = candidate_config["base_ui_core"]["outputs"]
    base_paths = {}
    base_payloads = {}
    for output_id in ("slps", "compdata"):
        path, payload = _payload(
            root,
            base_outputs[output_id],
            label=f"P9 source {output_id}",
        )
        base_paths[output_id] = path
        base_payloads[output_id] = payload

    text_table_path = _project_path(
        root,
        candidate_config["text_table"]["path"],
    )
    descriptor_path = _project_path(
        root,
        candidate_config["menu_descriptor"]["path"],
    )
    for label, path, reference in (
        ("text table", text_table_path, candidate_config["text_table"]),
        (
            "menu descriptor",
            descriptor_path,
            candidate_config["menu_descriptor"],
        ),
    ):
        if _sha256_path(path) != reference["sha256"]:
            raise UiDatabaseLayoutError(f"{label} SHA-256 drift")
    table = augment_text_table(load_text_table(text_table_path), overrides)
    descriptors = _menu_descriptors(descriptor_path)
    source_data = {
        "slps": base_payloads["slps"],
        "compdata": decode(base_payloads["compdata"]).output,
    }
    target_data = {
        "slps": candidate_payloads["slps"],
        "compdata": decode(candidate_payloads["compdata"]).output,
    }
    parsed = {}
    for member_id in ("slps", "compdata"):
        parsed[member_id] = {
            "source": {
                entry.entry_id: entry
                for entry in parse_menu_file(
                    source_data[member_id],
                    descriptors[member_id],
                    table,
                ).entries
            },
            "target": {
                entry.entry_id: entry
                for entry in parse_menu_file(
                    target_data[member_id],
                    descriptors[member_id],
                    table,
                ).entries
            },
        }

    envelopes = {
        family["runtime_scene_id"]: family
        for family in document["source_envelope"]["families"]
    }
    if set(envelopes) != {
        family["runtime_scene_id"]
        for family in selection_metadata["families"]
    }:
        raise UiDatabaseLayoutError(
            "source-envelope families differ from database selection"
        )

    entry_rows = []
    family_rows: defaultdict[str, list[dict]] = defaultdict(list)
    for entry_id in sorted(decisions):
        member_id = (
            "slps" if entry_id.startswith("menu/SLPS/") else "compdata"
        )
        source_entry = parsed[member_id]["source"].get(entry_id)
        target_entry = parsed[member_id]["target"].get(entry_id)
        if source_entry is None or target_entry is None:
            raise UiDatabaseLayoutError(
                f"database entry is absent from parsed members: {entry_id}"
            )
        decision = decisions[entry_id]
        if (
            text_sha256(source_entry.text)
            != decision["source_text_sha256"]
            or target_entry.text != decision["translation"]
        ):
            raise UiDatabaseLayoutError(
                f"database source/target readback drift: {entry_id}"
            )
        families = entry_families[entry_id]
        if len(families) != 1:
            raise UiDatabaseLayoutError(
                f"database entry must own one runtime family: {entry_id}"
            )
        family_id = next(iter(families))
        envelope = envelopes[family_id]
        source_widths = tuple(
            rendered_line_width(line)
            for line in source_entry.text.splitlines()
        )
        target_widths = tuple(
            rendered_line_width(line)
            for line in target_entry.text.splitlines()
        )
        row = {
            "entry_id": entry_id,
            "member_id": member_id,
            "runtime_scene_id": family_id,
            "source_text": source_entry.text,
            "target_text": target_entry.text,
            "source_line_widths": list(source_widths),
            "target_line_widths": list(target_widths),
            "source_line_count": len(source_widths),
            "target_line_count": len(target_widths),
            "family_source_max_line_cells": envelope[
                "expected_source_max_line_cells"
            ],
            "family_source_max_line_count": envelope[
                "expected_source_max_line_count"
            ],
            "line_width_overflow": (
                max(target_widths, default=0)
                > envelope["expected_source_max_line_cells"]
            ),
            "line_count_overflow": (
                len(target_widths)
                > envelope["expected_source_max_line_count"]
            ),
        }
        family_rows[family_id].append(row)
        entry_rows.append(row)

    font = decode_vt1_font_segment(
        candidate_payloads["slps"],
        candidate_payloads["vt1"],
    ).decoded
    font_hash = sha256_bytes(font)
    if (
        font_hash
        != font_manifest["font_component"]["decoded_sha256"]
    ):
        raise UiDatabaseLayoutError(
            "P10 candidate decoded font SHA-256 drift"
        )
    extended_entries = read_extended_glyph_table(
        candidate_payloads["slps"]
    )
    literal_characters = set()
    for decision in decisions.values():
        text = decision["translation"]
        notation_positions = control_notation_positions(text)
        literal_characters.update(
            character
            for index, character in enumerate(text)
            if index not in notation_positions and character != "\n"
        )

    glyph_rows = []
    missing_glyph_characters = []
    empty_glyph_characters = []
    han_raster_mismatches = []
    original_font_han_characters = []
    for character in sorted(literal_characters):
        try:
            code, glyph_index, mapping_source = _glyph_for_character(
                character,
                table=table,
                overrides=overrides,
                extended_entries=extended_entries,
            )
        except (UiDatabaseLayoutError, ValueError):
            missing_glyph_characters.append(character)
            continue
        metrics = _glyph_metrics(font, glyph_index)
        if metrics["ink_pixel_count"] == 0 and not character.isspace():
            empty_glyph_characters.append(character)
        selected_font = False
        raster_exact = None
        if is_cjk_unified_ideograph(character):
            assignment = proposal_assignments.get(character)
            if assignment is None:
                original_font_han_characters.append(character)
            else:
                selected_font = True
                expected = assignment.get("raster", {}).get(
                    "packed_glyph_sha256"
                )
                start = glyph_index * GLYPH_SIZE
                actual = sha256_bytes(font[start : start + GLYPH_SIZE])
                raster_exact = actual == expected
                if not raster_exact:
                    han_raster_mismatches.append(character)
        glyph_rows.append(
            {
                "character": character,
                "code": f"{code:04X}",
                "glyph_index": glyph_index,
                "mapping_source": mapping_source,
                "selected_font": selected_font,
                "raster_exact": raster_exact,
                **metrics,
            }
        )

    family_reports = []
    preview_payloads = {}
    preview_locks = []
    render = document["render"]
    output_root = document["outputs"]["preview_root"]
    entries_per_page = render["entries_per_page"]
    for family_id in sorted(family_rows):
        rows = family_rows[family_id]
        for ordinal, row in enumerate(rows, start=1):
            row["family_ordinal"] = ordinal
        envelope = envelopes[family_id]
        actual_source_max_line_cells = max(
            max(row["source_line_widths"], default=0)
            for row in rows
        )
        actual_source_max_line_count = max(
            row["source_line_count"] for row in rows
        )
        if (
            len(rows) != envelope["expected_entry_count"]
            or actual_source_max_line_cells
            != envelope["expected_source_max_line_cells"]
            or actual_source_max_line_count
            != envelope["expected_source_max_line_count"]
        ):
            raise UiDatabaseLayoutError(
                f"source envelope drift: {family_id}"
            )
        pages = []
        for page_index, start in enumerate(
            range(0, len(rows), entries_per_page),
            start=1,
        ):
            page_rows = rows[start : start + entries_per_page]
            png, geometry = render_database_preview_page(
                font,
                page_rows,
                family_budget=envelope[
                    "expected_source_max_line_cells"
                ],
                render=render,
                table=table,
                overrides=overrides,
                extended_entries=extended_entries,
            )
            slug = family_id.rsplit("/", 1)[-1]
            relative_path = (
                f"{output_root}/{slug}-{page_index:02d}.png"
            )
            preview_payloads[relative_path] = png
            page = {
                "path": relative_path,
                "runtime_scene_id": family_id,
                "page_index": page_index,
                "entry_count": len(page_rows),
                "first_entry_id": page_rows[0]["entry_id"],
                "last_entry_id": page_rows[-1]["entry_id"],
                "size": len(png),
                "sha256": sha256_bytes(png),
                **geometry,
            }
            pages.append(page)
            preview_locks.append(page)
        family_reports.append(
            {
                "runtime_scene_id": family_id,
                "entry_count": len(rows),
                "source_max_line_cells": actual_source_max_line_cells,
                "source_max_line_count": actual_source_max_line_count,
                "target_max_line_cells": max(
                    max(row["target_line_widths"], default=0)
                    for row in rows
                ),
                "target_max_line_count": max(
                    row["target_line_count"] for row in rows
                ),
                "line_width_overflow_count": sum(
                    row["line_width_overflow"] for row in rows
                ),
                "line_count_overflow_count": sum(
                    row["line_count_overflow"] for row in rows
                ),
                "preview_page_count": len(pages),
                "previews": pages,
            }
        )

    summary = {
        "family_count": len(family_reports),
        "entry_count": len(entry_rows),
        "source_readback_count": len(entry_rows),
        "target_readback_count": len(entry_rows),
        "line_width_overflow_count": sum(
            row["line_width_overflow"] for row in entry_rows
        ),
        "line_count_overflow_count": sum(
            row["line_count_overflow"] for row in entry_rows
        ),
        "literal_character_count": len(literal_characters),
        "missing_glyph_character_count": len(missing_glyph_characters),
        "empty_glyph_character_count": len(empty_glyph_characters),
        "target_han_character_count": sum(
            is_cjk_unified_ideograph(character)
            for character in literal_characters
        ),
        "original_font_han_character_count": len(
            original_font_han_characters
        ),
        "han_raster_mismatch_count": len(han_raster_mismatches),
        "preview_page_count": len(preview_locks),
        "preview_entry_count": sum(
            preview["entry_count"] for preview in preview_locks
        ),
    }
    expected_ratchet = document["ratchet"]
    ratchet_checks = {
        key: summary.get(key) == value
        for key, value in expected_ratchet.items()
    }
    if not all(ratchet_checks.values()):
        raise UiDatabaseLayoutError(
            f"database layout ratchet failed: {summary}"
        )
    acceptance = {
        "source_envelopes_exact": True,
        "all_selected_sources_reread": (
            summary["source_readback_count"] == summary["entry_count"]
        ),
        "all_selected_targets_reread": (
            summary["target_readback_count"] == summary["entry_count"]
        ),
        "zero_line_width_overflow": (
            summary["line_width_overflow_count"] == 0
        ),
        "zero_line_count_overflow": (
            summary["line_count_overflow_count"] == 0
        ),
        "zero_missing_glyphs": (
            summary["missing_glyph_character_count"] == 0
        ),
        "zero_empty_non_space_glyphs": (
            summary["empty_glyph_character_count"] == 0
        ),
        "all_han_use_selected_font": (
            summary["original_font_han_character_count"] == 0
        ),
        "all_han_rasters_exact": (
            summary["han_raster_mismatch_count"] == 0
        ),
        "all_entries_rendered_once": (
            summary["preview_entry_count"] == summary["entry_count"]
        ),
        "ratchet_passed": all(ratchet_checks.values()),
    }
    if not all(acceptance.values()):
        raise UiDatabaseLayoutError(
            f"database layout acceptance failed: {acceptance}"
        )
    entry_projection = [
        {
            "entry_id": row["entry_id"],
            "runtime_scene_id": row["runtime_scene_id"],
            "source_line_widths": row["source_line_widths"],
            "target_line_widths": row["target_line_widths"],
            "source_line_count": row["source_line_count"],
            "target_line_count": row["target_line_count"],
            "line_width_overflow": row["line_width_overflow"],
            "line_count_overflow": row["line_count_overflow"],
        }
        for row in entry_rows
    ]
    report = {
        "schema_version": 1,
        "status": (
            "offline_p10_database_layout_and_exact_glyph_previews_"
            "validated_runtime_pending"
        ),
        "layout_id": document["layout_id"],
        "scope": document["scope"],
        "inputs": {
            "config": _file_lock(root, config_path),
            "candidate_config": _file_lock(root, candidate_config_path),
            "candidate_manifest": _file_lock(root, candidate_manifest_path),
            "selection_config": _file_lock(root, selection_config_path),
            "selection_manifest": _file_lock(root, selection_manifest_path),
            "font_manifest": _file_lock(root, font_manifest_path),
            "font_proposal": _file_lock(root, proposal_path),
            "writer_config": _file_lock(root, writer_config_path),
            "text_table": _file_lock(root, text_table_path),
            "menu_descriptor": _file_lock(root, descriptor_path),
            "source_members": {
                output_id: _file_lock(root, path)
                for output_id, path in base_paths.items()
            },
            "candidate_members": {
                output_id: _file_lock(root, path)
                for output_id, path in candidate_paths.items()
            },
            "decoded_font": {
                "size": len(font),
                "sha256": font_hash,
            },
            "codebook": codebook,
        },
        "source_envelope_policy": document["source_envelope"]["policy"],
        "families": family_reports,
        "entries": entry_rows,
        "glyphs": {
            "rows": glyph_rows,
            "missing_characters": "".join(missing_glyph_characters),
            "empty_characters": "".join(empty_glyph_characters),
            "original_font_han_characters": "".join(
                original_font_han_characters
            ),
            "han_raster_mismatch_characters": "".join(
                han_raster_mismatches
            ),
        },
        "previews": preview_locks,
        "summary": summary,
        "entry_plan_sha256": _stable_hash(entry_projection),
        "ratchet": {
            "expected": expected_ratchet,
            "actual": {
                key: summary.get(key) for key in expected_ratchet
            },
            "checks": ratchet_checks,
            "passed": True,
        },
        "acceptance": acceptance,
        "runtime": {
            "status": "not_tested",
            "boundary": (
                "The family widths are conservative envelopes observed in "
                "the original strings, not measured runtime panel geometry. "
                "Exact-glyph previews cannot prove clipping, animation, "
                "dynamic substitution or final PCSX2 rendering."
            ),
        },
    }
    return report, preview_payloads


def build_ui_database_layout_manifest(
    report: Mapping[str, object],
) -> dict:
    """Project text-free deterministic layout facts for source control."""

    if report.get("status") != (
        "offline_p10_database_layout_and_exact_glyph_previews_"
        "validated_runtime_pending"
    ):
        raise UiDatabaseLayoutError(
            "database layout report status is invalid"
        )
    return {
        "schema_version": 1,
        "status": report["status"],
        "layout_id": report["layout_id"],
        "scope": report["scope"],
        "content_policy": (
            "Hashes, counts, dimensions, entry IDs and runtime gates only; "
            "source text, localized text, game bytes and preview PNG bytes "
            "remain outside this committed manifest."
        ),
        "inputs": report["inputs"],
        "source_envelope_policy": report["source_envelope_policy"],
        "families": [
            {
                key: family[key]
                for key in (
                    "runtime_scene_id",
                    "entry_count",
                    "source_max_line_cells",
                    "source_max_line_count",
                    "target_max_line_cells",
                    "target_max_line_count",
                    "line_width_overflow_count",
                    "line_count_overflow_count",
                    "preview_page_count",
                    "previews",
                )
            }
            for family in report["families"]
        ],
        "summary": report["summary"],
        "entry_plan_sha256": report["entry_plan_sha256"],
        "ratchet": report["ratchet"],
        "acceptance": report["acceptance"],
        "runtime": report["runtime"],
    }


__all__ = [
    "UiDatabaseLayoutError",
    "audit_ui_database_layout",
    "build_ui_database_layout_manifest",
    "load_ui_database_layout_config",
    "render_database_preview_page",
]
