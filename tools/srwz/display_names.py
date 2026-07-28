"""Parse fixed-record pilot and pointer-backed unit display names."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .codec import decode, reencode_changed_suffix
from .corpus import text_sha256
from .font import sha256_bytes
from .text import (
    TextTable,
    augment_text_table,
    decode_text,
    encode_text,
    load_text_table,
)
from .ui_menu import (
    build_fixed_compdata_component,
    load_ui_font_overrides,
)
from .writeback import PatchOperation, PatchPlan


class DisplayNameError(ValueError):
    """Display-name structure, source, or translation data has drifted."""


_EDITORIAL_STATUS_RANK = {
    "todo": 0,
    "draft": 1,
    "reviewed": 2,
    "final": 3,
}
_KANA_PATTERN = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]")
_P0_WRITE_POLICY = {
    "require_every_translation_id": True,
    "require_source_text_hash": True,
    "require_minimum_editorial_status": True,
    "require_source_refs": True,
    "require_payload_with_terminator_within_allocation": True,
    "pointer_write_policy": "forbidden",
}
_RESEARCHED_WRITE_POLICY = {
    "require_reviewed_prior_batch": True,
    "require_researched_exact_selection": True,
    "require_source_text_hash": True,
    "require_source_refs": True,
    "require_payload_with_terminator_within_allocation": True,
    "pointer_write_policy": "forbidden",
}


@dataclass(frozen=True)
class DisplayNameEntry:
    entry_id: str
    table: str
    record_index: int
    field: str
    text: str
    target_offset: int
    capacity: int
    encoded_size: int
    pointer_offsets: tuple[int, ...] = ()
    pointer_record_indices: tuple[int, ...] = ()

    @property
    def source_text_sha256(self) -> str:
        return text_sha256(self.text)

    def to_mapping(self, *, include_text: bool = True) -> dict:
        result = {
            "id": self.entry_id,
            "table": self.table,
            "record_index": self.record_index,
            "field": self.field,
            "target_offset": self.target_offset,
            "capacity": self.capacity,
            "encoded_size": self.encoded_size,
            "pointer_offsets": list(self.pointer_offsets),
            "pointer_record_indices": list(self.pointer_record_indices),
            "source_text_sha256": self.source_text_sha256,
        }
        if include_text:
            result["text"] = self.text
        return result


@dataclass(frozen=True)
class DisplayNameParseResult:
    source_size: int
    pilot_entries: tuple[DisplayNameEntry, ...]
    unit_entries: tuple[DisplayNameEntry, ...]
    pilot_table_sha256: str
    pilot_id_bytes_sha256: str
    unit_record_bytes_sha256: str
    unit_pointer_bytes_sha256: str
    unit_target_slot_bytes_sha256: str

    @property
    def entries(self) -> tuple[DisplayNameEntry, ...]:
        return (*self.pilot_entries, *self.unit_entries)


def _number(value: object, *, context: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise DisplayNameError(f"{context} is not an integer") from error
    raise DisplayNameError(f"{context} must be an integer")


def _require_object(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise DisplayNameError(f"{context} must be an object")
    return value


def _require_span(data: bytes, offset: int, size: int, *, context: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise DisplayNameError(f"{context} is outside decoded COMPDATA")


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise DisplayNameError("display-name alignment must be a positive power of two")
    return (value + alignment - 1) & -alignment


def _sha256_parts(parts: Sequence[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


def _parse_pilot_entries(
    data: bytes,
    table: TextTable,
    config: Mapping[str, object],
    *,
    verify_text_preimages: bool,
) -> tuple[tuple[DisplayNameEntry, ...], dict]:
    start = _number(config.get("start"), context="pilot table start")
    stride = _number(config.get("record_stride"), context="pilot record stride")
    count = _number(config.get("record_count"), context="pilot record count")
    id_offset = _number(config.get("id_offset"), context="pilot ID offset")
    end = _number(config.get("end"), context="pilot table end")
    if stride <= 0 or count <= 0 or end != start + stride * count:
        raise DisplayNameError("pilot table extent is inconsistent")
    _require_span(data, start, end - start, context="pilot table")
    if verify_text_preimages and sha256_bytes(data[start:end]) != config.get(
        "table_sha256"
    ):
        raise DisplayNameError("pilot table SHA-256 drift")

    raw_fields = config.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise DisplayNameError("pilot fields must be a non-empty array")
    fields = []
    occupied = set(range(id_offset, id_offset + 2))
    for raw in raw_fields:
        field = _require_object(raw, context="pilot field")
        name = field.get("name")
        offset = _number(field.get("offset"), context="pilot field offset")
        capacity = _number(field.get("capacity"), context="pilot field capacity")
        if not isinstance(name, str) or not name or capacity <= 0:
            raise DisplayNameError("pilot field descriptor is malformed")
        span = set(range(offset, offset + capacity))
        if offset < 0 or offset + capacity > stride or occupied & span:
            raise DisplayNameError(f"pilot field {name!r} overlaps or leaves record")
        occupied.update(span)
        fields.append((name, offset, capacity, field))

    entries = []
    id_parts = []
    empty_counts = {name: 0 for name, *_ in fields}
    max_encoded_sizes = {name: 0 for name, *_ in fields}
    for record_index in range(count):
        record_offset = start + record_index * stride
        raw_id = data[record_offset + id_offset : record_offset + id_offset + 2]
        id_parts.append(raw_id)
        if struct.unpack("<H", raw_id)[0] != record_index:
            raise DisplayNameError(f"pilot record ID drift at index {record_index}")
        for name, field_offset, capacity, _ in fields:
            target_offset = record_offset + field_offset
            decoded = decode_text(data, target_offset, table)
            if decoded.unknown_code_count:
                raise DisplayNameError(
                    f"pilot {record_index:04d} {name} contains unknown text codes"
                )
            if decoded.consumed > capacity:
                raise DisplayNameError(
                    f"pilot {record_index:04d} {name} exceeds its fixed field"
                )
            padding = data[target_offset + decoded.consumed : target_offset + capacity]
            if any(padding):
                raise DisplayNameError(
                    f"pilot {record_index:04d} {name} has nonzero field padding"
                )
            empty_counts[name] += not decoded.text
            max_encoded_sizes[name] = max(
                max_encoded_sizes[name],
                decoded.consumed,
            )
            entries.append(
                DisplayNameEntry(
                    entry_id=(f"display-name/pilot/{record_index:04d}/{name}"),
                    table="pilot",
                    record_index=record_index,
                    field=name,
                    text=decoded.text,
                    target_offset=target_offset,
                    capacity=capacity,
                    encoded_size=decoded.consumed,
                )
            )

    id_bytes_sha256 = _sha256_parts(id_parts)
    if id_bytes_sha256 != config.get("id_bytes_sha256"):
        raise DisplayNameError("pilot ID-byte aggregate drift")
    if verify_text_preimages:
        for name, _, _, field in fields:
            if empty_counts[name] != field.get("expected_empty_count"):
                raise DisplayNameError(f"pilot field {name!r} empty-count drift")
            if max_encoded_sizes[name] != field.get("expected_max_encoded_size"):
                raise DisplayNameError(f"pilot field {name!r} maximum-size drift")
    if len(entries) != config.get("expected_entry_count"):
        raise DisplayNameError("pilot entry-count drift")
    non_empty_count = sum(bool(entry.text) for entry in entries)
    if non_empty_count != config.get("expected_non_empty_entry_count"):
        raise DisplayNameError("pilot non-empty entry-count drift")

    terminal = _require_object(
        config.get("terminal_preimage"),
        context="pilot terminal preimage",
    )
    terminal_offset = _number(
        terminal.get("offset"),
        context="pilot terminal offset",
    )
    try:
        terminal_bytes = bytes.fromhex(str(terminal.get("hex")))
    except ValueError as error:
        raise DisplayNameError("pilot terminal preimage hex is invalid") from error
    _require_span(
        data,
        terminal_offset,
        len(terminal_bytes),
        context="pilot terminal preimage",
    )
    if data[terminal_offset : terminal_offset + len(terminal_bytes)] != terminal_bytes:
        raise DisplayNameError("pilot terminal preimage drift")

    return tuple(entries), {
        "start": start,
        "end": end,
        "record_stride": stride,
        "record_count": count,
        "entry_count": len(entries),
        "non_empty_entry_count": non_empty_count,
        "empty_counts": empty_counts,
        "max_encoded_sizes": max_encoded_sizes,
        "table_sha256": sha256_bytes(data[start:end]),
        "id_bytes_sha256": id_bytes_sha256,
    }


def _inside_region(
    start: int,
    end: int,
    regions: Sequence[tuple[int, int]],
) -> bool:
    return any(
        region_start <= start < end <= region_end
        for region_start, region_end in regions
    )


def _parse_unit_entries(
    data: bytes,
    table: TextTable,
    config: Mapping[str, object],
    *,
    verify_text_preimages: bool,
) -> tuple[tuple[DisplayNameEntry, ...], dict]:
    record_start = _number(
        config.get("record_start"),
        context="unit record start",
    )
    stride = _number(config.get("record_stride"), context="unit record stride")
    count = _number(config.get("record_count"), context="unit record count")
    pointer_offset = _number(
        config.get("pointer_offset"),
        context="unit pointer offset",
    )
    record_end = _number(config.get("record_end"), context="unit record end")
    base_address = _number(
        config.get("pointer_base_address"),
        context="unit pointer base address",
    )
    alignment = _number(
        config.get("target_alignment"),
        context="unit target alignment",
    )
    if (
        stride <= 0
        or count <= 0
        or pointer_offset < 0
        or pointer_offset + 4 > stride
        or record_end != record_start + stride * count
    ):
        raise DisplayNameError("unit record table extent is inconsistent")
    if config.get("allocation_policy") != "minimum_zero_padded_alignment":
        raise DisplayNameError("unsupported unit display-name allocation policy")
    _require_span(
        data,
        record_start,
        record_end - record_start,
        context="unit record table",
    )
    record_bytes = data[record_start:record_end]
    if sha256_bytes(record_bytes) != config.get("record_bytes_sha256"):
        raise DisplayNameError("unit record table SHA-256 drift")

    raw_regions = config.get("allowed_target_regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise DisplayNameError("unit target regions must be a non-empty array")
    regions = []
    previous_end = -1
    for raw in raw_regions:
        region = _require_object(raw, context="unit target region")
        start = _number(region.get("start"), context="unit target region start")
        end = _number(region.get("end"), context="unit target region end")
        if start < previous_end or end <= start or end > len(data):
            raise DisplayNameError("unit target regions overlap or leave input")
        regions.append((start, end))
        previous_end = end

    pointer_parts = []
    by_target: dict[int, dict] = {}
    for record_index in range(count):
        pointer_site = record_start + record_index * stride + pointer_offset
        raw_pointer = data[pointer_site : pointer_site + 4]
        pointer_parts.append(raw_pointer)
        pointer_value = struct.unpack("<I", raw_pointer)[0]
        if pointer_value <= base_address:
            raise DisplayNameError(
                f"unit record {record_index:04d} has an invalid name pointer"
            )
        target_offset = pointer_value - base_address
        if target_offset % alignment:
            raise DisplayNameError(
                f"unit record {record_index:04d} target is misaligned"
            )
        decoded = decode_text(data, target_offset, table)
        if decoded.unknown_code_count:
            raise DisplayNameError(
                f"unit record {record_index:04d} has unknown name codes"
            )
        capacity = _align_up(decoded.consumed, alignment)
        if not _inside_region(
            target_offset,
            target_offset + capacity,
            regions,
        ):
            raise DisplayNameError(
                f"unit record {record_index:04d} target leaves allowed regions"
            )
        padding = data[target_offset + decoded.consumed : target_offset + capacity]
        if any(padding):
            raise DisplayNameError(
                f"unit record {record_index:04d} has nonzero name-slot padding"
            )
        group = by_target.setdefault(
            target_offset,
            {
                "text": decoded.text,
                "encoded_size": decoded.consumed,
                "capacity": capacity,
                "pointer_offsets": [],
                "record_indices": [],
            },
        )
        if (
            group["text"] != decoded.text
            or group["encoded_size"] != decoded.consumed
            or group["capacity"] != capacity
        ):
            raise DisplayNameError("unit shared target decodes inconsistently")
        group["pointer_offsets"].append(pointer_site)
        group["record_indices"].append(record_index)

    pointer_bytes_sha256 = _sha256_parts(pointer_parts)
    if pointer_bytes_sha256 != config.get("pointer_bytes_sha256"):
        raise DisplayNameError("unit pointer-byte aggregate drift")
    if len(pointer_parts) != config.get("expected_pointer_count"):
        raise DisplayNameError("unit pointer-count drift")
    if len(by_target) != config.get("expected_unique_target_count"):
        raise DisplayNameError("unit unique-target count drift")
    if verify_text_preimages and len(
        {group["text"] for group in by_target.values()}
    ) != config.get("expected_unique_text_count"):
        raise DisplayNameError("unit unique-text count drift")

    entries = []
    for ordinal, (target_offset, group) in enumerate(by_target.items()):
        entries.append(
            DisplayNameEntry(
                entry_id=f"display-name/unit/{ordinal:04d}/name",
                table="unit",
                record_index=ordinal,
                field="name",
                text=group["text"],
                target_offset=target_offset,
                capacity=group["capacity"],
                encoded_size=group["encoded_size"],
                pointer_offsets=tuple(group["pointer_offsets"]),
                pointer_record_indices=tuple(group["record_indices"]),
            )
        )
    target_slot_bytes_sha256 = _sha256_parts(
        [
            data[entry.target_offset : entry.target_offset + entry.capacity]
            for entry in sorted(entries, key=lambda item: item.target_offset)
        ]
    )
    if verify_text_preimages and target_slot_bytes_sha256 != config.get(
        "target_slot_bytes_sha256"
    ):
        raise DisplayNameError("unit target-slot aggregate drift")

    return tuple(entries), {
        "record_start": record_start,
        "record_end": record_end,
        "record_stride": stride,
        "record_count": count,
        "pointer_count": len(pointer_parts),
        "unique_target_count": len(entries),
        "unique_text_count": len({entry.text for entry in entries}),
        "target_regions": [{"start": start, "end": end} for start, end in regions],
        "record_bytes_sha256": sha256_bytes(record_bytes),
        "pointer_bytes_sha256": pointer_bytes_sha256,
        "target_slot_bytes_sha256": target_slot_bytes_sha256,
        "minimum_capacity": min(entry.capacity for entry in entries),
        "maximum_capacity": max(entry.capacity for entry in entries),
    }


def parse_display_names(
    data: bytes,
    table: TextTable,
    config: Mapping[str, object],
    *,
    verify_text_preimages: bool = True,
) -> DisplayNameParseResult:
    """Parse and fully validate all configured pilot and unit name records."""

    if config.get("schema_version") != 1:
        raise DisplayNameError("unsupported display-name structure schema")
    pilot_config = _require_object(
        config.get("pilot_table"),
        context="pilot table",
    )
    unit_config = _require_object(
        config.get("unit_table"),
        context="unit table",
    )
    pilot_entries, pilot_report = _parse_pilot_entries(
        data,
        table,
        pilot_config,
        verify_text_preimages=verify_text_preimages,
    )
    unit_entries, unit_report = _parse_unit_entries(
        data,
        table,
        unit_config,
        verify_text_preimages=verify_text_preimages,
    )
    entry_ids = [entry.entry_id for entry in (*pilot_entries, *unit_entries)]
    if len(entry_ids) != len(set(entry_ids)):
        raise DisplayNameError("display-name stable IDs are not unique")
    return DisplayNameParseResult(
        source_size=len(data),
        pilot_entries=pilot_entries,
        unit_entries=unit_entries,
        pilot_table_sha256=pilot_report["table_sha256"],
        pilot_id_bytes_sha256=pilot_report["id_bytes_sha256"],
        unit_record_bytes_sha256=unit_report["record_bytes_sha256"],
        unit_pointer_bytes_sha256=unit_report["pointer_bytes_sha256"],
        unit_target_slot_bytes_sha256=unit_report["target_slot_bytes_sha256"],
    )


def _project_path(project_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise DisplayNameError("display-name project path must be non-empty")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise DisplayNameError(
            f"display-name path escapes project: {relative}"
        ) from error
    return path


def _load_json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DisplayNameError(
            f"cannot load display-name JSON {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise DisplayNameError(f"display-name JSON root must be an object: {path}")
    return value


def load_display_name_source(
    project_root: Path,
    config_path: Path,
) -> tuple[dict, bytes, DisplayNameParseResult, dict]:
    """Load hash-locked COMPDATA and return its validated display-name parse."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _load_json_object(config_path)
    source = _require_object(
        config.get("source_member"),
        context="display-name source member",
    )
    source_path = _project_path(root, source.get("path"))
    stored = source_path.read_bytes()
    if len(stored) != source.get("size") or sha256_bytes(stored) != source.get(
        "sha256"
    ):
        raise DisplayNameError("display-name COMPDATA source drift")
    decoded = decode(stored)
    if decoded.consumed != len(stored):
        raise DisplayNameError("display-name COMPDATA source has trailing bytes")
    if (
        len(decoded.output) != source.get("decoded_size")
        or sha256_bytes(decoded.output) != source.get("decoded_sha256")
        or decoded.flags != source.get("flags")
    ):
        raise DisplayNameError("display-name decoded COMPDATA source drift")
    table_reference = _require_object(
        config.get("text_table"),
        context="display-name text table",
    )
    table_path = _project_path(root, table_reference.get("path"))
    if sha256_bytes(table_path.read_bytes()) != table_reference.get("sha256"):
        raise DisplayNameError("display-name text table drift")
    table = load_text_table(table_path)
    parsed = parse_display_names(decoded.output, table, config)
    context = {
        "config": {
            "path": str(config_path.relative_to(root)),
            "sha256": sha256_bytes(config_path.read_bytes()),
        },
        "source_member": {
            "path": str(source_path.relative_to(root)),
            "size": len(stored),
            "sha256": sha256_bytes(stored),
            "decoded_size": len(decoded.output),
            "decoded_sha256": sha256_bytes(decoded.output),
            "flags": decoded.flags,
            "fully_consumed": True,
        },
        "text_table": {
            "path": str(table_path.relative_to(root)),
            "sha256": sha256_bytes(table_path.read_bytes()),
        },
    }
    return config, decoded.output, parsed, context


def entry_signature_sha256(entries: Sequence[DisplayNameEntry]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.entry_id):
        digest.update(
            json.dumps(
                entry.to_mapping(include_text=False),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def build_display_name_report(
    project_root: Path,
    config_path: Path,
) -> tuple[dict, dict]:
    """Build full local report and bounded publishable structure manifest."""

    config, _, parsed, context = load_display_name_source(
        project_root,
        config_path,
    )
    entries = parsed.entries
    by_id = {entry.entry_id: entry for entry in entries}
    probes = []
    for raw in config.get("probes", []):
        probe = _require_object(raw, context="display-name probe")
        entry_id = probe.get("entry_id")
        if not isinstance(entry_id, str) or entry_id not in by_id:
            raise DisplayNameError("display-name probe references an unknown entry")
        entry = by_id[entry_id]
        exact = (
            entry.target_offset
            == _number(probe.get("decoded_offset"), context="probe decoded offset")
            and entry.encoded_size == probe.get("encoded_size_with_terminator")
            and entry.source_text_sha256 == probe.get("source_text_sha256")
        )
        if not exact:
            raise DisplayNameError(
                f"display-name probe drift: {probe.get('semantic_id')}"
            )
        probes.append(
            {
                "semantic_id": probe.get("semantic_id"),
                "entry_id": entry.entry_id,
                "decoded_offset": f"0x{entry.target_offset:X}",
                "capacity": entry.capacity,
                "encoded_size_with_terminator": entry.encoded_size,
                "source_text_sha256": entry.source_text_sha256,
                "exact": True,
            }
        )

    pilot_config = config["pilot_table"]
    unit_config = config["unit_table"]
    full_report = {
        "schema_version": 1,
        "content_policy": (
            "This ignored local report contains original Japanese display names. "
            "Only the bounded manifest may be committed."
        ),
        "structure_id": config["structure_id"],
        "inputs": context,
        "pilot_table": {
            "record_count": pilot_config["record_count"],
            "entry_count": len(parsed.pilot_entries),
            "non_empty_entry_count": sum(
                bool(entry.text) for entry in parsed.pilot_entries
            ),
            "table_sha256": parsed.pilot_table_sha256,
            "id_bytes_sha256": parsed.pilot_id_bytes_sha256,
            "entries": [entry.to_mapping() for entry in parsed.pilot_entries],
        },
        "unit_table": {
            "record_count": unit_config["record_count"],
            "pointer_count": sum(
                len(entry.pointer_offsets) for entry in parsed.unit_entries
            ),
            "unique_name_count": len(parsed.unit_entries),
            "record_bytes_sha256": parsed.unit_record_bytes_sha256,
            "pointer_bytes_sha256": parsed.unit_pointer_bytes_sha256,
            "target_slot_bytes_sha256": parsed.unit_target_slot_bytes_sha256,
            "entries": [entry.to_mapping() for entry in parsed.unit_entries],
        },
        "totals": {
            "entry_count": len(entries),
            "non_empty_entry_count": sum(bool(entry.text) for entry in entries),
            "entry_signature_sha256": entry_signature_sha256(entries),
        },
        "probes": probes,
    }
    manifest = {
        "schema_version": 1,
        "status": "structure_validated",
        "scope": (
            "Full clean-room structure parse. Japanese names and game bytes "
            "remain only in ignored work output; ISO/runtime are not tested."
        ),
        "structure_id": config["structure_id"],
        "inputs": context,
        "pilot_table": {
            "record_count": pilot_config["record_count"],
            "entry_count": len(parsed.pilot_entries),
            "non_empty_entry_count": sum(
                bool(entry.text) for entry in parsed.pilot_entries
            ),
            "table_sha256": parsed.pilot_table_sha256,
            "id_bytes_sha256": parsed.pilot_id_bytes_sha256,
        },
        "unit_table": {
            "record_count": unit_config["record_count"],
            "pointer_count": sum(
                len(entry.pointer_offsets) for entry in parsed.unit_entries
            ),
            "unique_name_count": len(parsed.unit_entries),
            "record_bytes_sha256": parsed.unit_record_bytes_sha256,
            "pointer_bytes_sha256": parsed.unit_pointer_bytes_sha256,
            "target_slot_bytes_sha256": parsed.unit_target_slot_bytes_sha256,
        },
        "totals": full_report["totals"],
        "probes": probes,
        "runtime": {
            "status": "not_tested",
            "reason": (
                "This manifest proves source structure only; it does not "
                "contain translated display-name bytes or an ISO."
            ),
        },
    }
    return full_report, manifest


def _load_hashed_project_object(
    project_root: Path,
    relative: object,
    expected_sha256: object,
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(project_root, relative)
    if sha256_bytes(path.read_bytes()) != expected_sha256:
        raise DisplayNameError(f"{label} SHA-256 drift")
    return path, _load_json_object(path)


def _load_terminology_ids(
    project_root: Path,
    references: object,
) -> tuple[set[str], list[dict]]:
    if not isinstance(references, list) or not references:
        raise DisplayNameError("display-name terminology sources are missing")
    term_ids = set()
    reports = []
    for raw in references:
        reference = _require_object(raw, context="terminology source")
        path, document = _load_hashed_project_object(
            project_root,
            reference.get("path"),
            reference.get("sha256"),
            label="terminology source",
        )
        terms = document.get("terms")
        if not isinstance(terms, list):
            raise DisplayNameError(f"terminology source has no terms: {path}")
        source_ids = set()
        for term in terms:
            if not isinstance(term, dict) or not isinstance(term.get("id"), str):
                raise DisplayNameError(f"malformed terminology source: {path}")
            source_ids.add(term["id"])
        term_ids.update(source_ids)
        reports.append(
            {
                "path": str(path.relative_to(project_root.resolve())),
                "sha256": sha256_bytes(path.read_bytes()),
                "term_count": len(source_ids),
            }
        )
    return term_ids, reports


def _load_translation_decisions(
    project_root: Path,
    reference: Mapping[str, object],
    structure_manifest: Mapping[str, object],
    parsed: DisplayNameParseResult,
    *,
    terminology_ids: set[str],
) -> tuple[dict[str, dict], dict]:
    path, document = _load_hashed_project_object(
        project_root,
        reference.get("path"),
        reference.get("sha256"),
        label="display-name translation source",
    )
    if document.get("schema_version") != 1:
        raise DisplayNameError("unsupported display-name translation schema")
    if document.get("batch_id") != reference.get("batch_id"):
        raise DisplayNameError("display-name translation batch drift")
    if document.get("language") != "zh-Hans":
        raise DisplayNameError("display-name translation language is unsupported")
    scope = _require_object(
        document.get("scope"),
        context="display-name translation scope",
    )
    structure_path = _project_path(
        project_root,
        scope.get("structure_manifest"),
    )
    if (
        sha256_bytes(structure_path.read_bytes())
        != scope.get("structure_manifest_sha256")
        or _load_json_object(structure_path) != structure_manifest
    ):
        raise DisplayNameError("translation source structure manifest drift")
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list) or len(raw_entries) != scope.get(
        "entry_count"
    ):
        raise DisplayNameError("display-name translation entry-count drift")
    minimum_status = reference.get("minimum_editorial_status")
    if minimum_status not in _EDITORIAL_STATUS_RANK:
        raise DisplayNameError("invalid minimum display-name editorial status")
    source_by_id = {entry.entry_id: entry for entry in parsed.entries}
    decisions = {}
    for raw in raw_entries:
        decision = _require_object(raw, context="display-name translation")
        entry_id = decision.get("id")
        if not isinstance(entry_id, str) or entry_id not in source_by_id:
            raise DisplayNameError("display-name translation has an unknown ID")
        if entry_id in decisions:
            raise DisplayNameError(f"duplicate display-name translation: {entry_id}")
        source = source_by_id[entry_id]
        if decision.get("source_text_sha256") != source.source_text_sha256:
            raise DisplayNameError(f"display-name source hash drift: {entry_id}")
        translation = decision.get("translation")
        if (
            not isinstance(translation, str)
            or not translation
            or "\n" in translation
            or "\r" in translation
        ):
            raise DisplayNameError(
                f"display-name translation must be one non-empty line: {entry_id}"
            )
        if _KANA_PATTERN.search(translation):
            raise DisplayNameError(
                f"display-name translation contains Japanese kana: {entry_id}"
            )
        status = decision.get("editorial_status")
        if (
            status not in _EDITORIAL_STATUS_RANK
            or _EDITORIAL_STATUS_RANK[status] < _EDITORIAL_STATUS_RANK[minimum_status]
        ):
            raise DisplayNameError(
                f"display-name translation is below review threshold: {entry_id}"
            )
        source_refs = decision.get("source_refs")
        if (
            not isinstance(source_refs, list)
            or not source_refs
            or not all(isinstance(item, str) and item for item in source_refs)
        ):
            raise DisplayNameError(
                f"display-name translation has no source refs: {entry_id}"
            )
        unknown_refs = sorted(set(source_refs) - terminology_ids)
        if unknown_refs:
            raise DisplayNameError(
                f"display-name translation has unknown source refs: "
                f"{entry_id}: {unknown_refs}"
            )
        decisions[entry_id] = dict(decision)
    return decisions, {
        "path": str(path.relative_to(project_root.resolve())),
        "sha256": sha256_bytes(path.read_bytes()),
        "batch_id": document["batch_id"],
        "minimum_editorial_status": minimum_status,
        "entry_count": len(decisions),
        "selection_sha256": sha256_bytes(
            json.dumps(
                [
                    {
                        "id": entry_id,
                        "source_text_sha256": decisions[entry_id]["source_text_sha256"],
                        "translation": decisions[entry_id]["translation"],
                    }
                    for entry_id in sorted(decisions)
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
    }


def _load_researched_coverage_decisions(
    project_root: Path,
    reference: Mapping[str, object],
    parsed: DisplayNameParseResult,
) -> tuple[dict[str, dict], dict]:
    config_path, _ = _load_hashed_project_object(
        project_root,
        reference.get("config"),
        reference.get("config_sha256"),
        label="researched display-name selection config",
    )
    manifest_path, committed = _load_hashed_project_object(
        project_root,
        reference.get("manifest"),
        reference.get("manifest_sha256"),
        label="researched display-name selection manifest",
    )
    if committed.get("selection_id") != reference.get("selection_id"):
        raise DisplayNameError("researched display-name selection ID drift")
    if committed.get("status") != reference.get("required_status"):
        raise DisplayNameError("researched display-name selection status drift")

    from .display_name_coverage import (  # Avoid module import cycle.
        DisplayNameCoverageError,
        audit_display_name_coverage,
    )

    try:
        report, expected_manifest = audit_display_name_coverage(
            project_root,
            config_path,
        )
    except DisplayNameCoverageError as error:
        raise DisplayNameError(str(error)) from error
    if committed != expected_manifest:
        raise DisplayNameError(
            "researched display-name selection is not reproducible"
        )
    raw_entries = report.get("selection", {}).get("entries")
    expected_count = reference.get("expected_entry_count")
    if (
        not isinstance(raw_entries, list)
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or len(raw_entries) != expected_count
    ):
        raise DisplayNameError("researched display-name selection count drift")
    source_by_id = {entry.entry_id: entry for entry in parsed.entries}
    decisions = {}
    source_refs = set()
    for raw in raw_entries:
        decision = _require_object(
            raw,
            context="researched display-name selection entry",
        )
        entry_id = decision.get("id")
        if (
            not isinstance(entry_id, str)
            or entry_id not in source_by_id
            or entry_id in decisions
        ):
            raise DisplayNameError(
                "researched display-name selection has an invalid ID"
            )
        source = source_by_id[entry_id]
        if decision.get("source_text_sha256") != source.source_text_sha256:
            raise DisplayNameError(
                f"researched display-name source hash drift: {entry_id}"
            )
        translation = decision.get("translation")
        refs = decision.get("source_refs")
        if (
            not isinstance(translation, str)
            or not translation
            or "\n" in translation
            or "\r" in translation
            or _KANA_PATTERN.search(translation)
            or not isinstance(refs, list)
            or not refs
            or not all(isinstance(item, str) and item for item in refs)
        ):
            raise DisplayNameError(
                f"researched display-name decision is invalid: {entry_id}"
            )
        decisions[entry_id] = {
            "id": entry_id,
            "source_text_sha256": source.source_text_sha256,
            "translation": translation,
            "source_refs": list(refs),
            "editorial_status": "researched_exact",
        }
        source_refs.update(refs)

    root = project_root.resolve()
    return decisions, {
        "config": {
            "path": str(config_path.relative_to(root)),
            "sha256": sha256_bytes(config_path.read_bytes()),
        },
        "manifest": {
            "path": str(manifest_path.relative_to(root)),
            "sha256": sha256_bytes(manifest_path.read_bytes()),
            "status": committed["status"],
        },
        "selection_id": committed["selection_id"],
        "entry_count": len(decisions),
        "unique_source_ref_count": len(source_refs),
        "selection_sha256": committed["selection"]["selection_sha256"],
    }


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    if len(before) != len(after):
        raise DisplayNameError("display-name patch changed decoded size")
    return [
        offset
        for offset, (left, right) in enumerate(zip(before, after))
        if left != right
    ]


def _difference_range_count(offsets: Sequence[int]) -> int:
    ranges = 0
    previous = None
    for offset in offsets:
        if previous is None or offset != previous + 1:
            ranges += 1
        previous = offset
    return ranges


def build_display_name_component(
    project_root: Path,
    config_path: Path,
) -> tuple[bytes, dict]:
    """Compose one locked display-name selection onto fixed P0 COMPDATA."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _load_json_object(config_path)
    if config.get("schema_version") != 1:
        raise DisplayNameError("unsupported display-name writeback schema")
    selection_policy = config.get("selection_policy")
    if selection_policy not in (
        _P0_WRITE_POLICY,
        _RESEARCHED_WRITE_POLICY,
    ):
        raise DisplayNameError("display-name writeback policy is incomplete")

    structure_reference = _require_object(
        config.get("structure"),
        context="display-name structure",
    )
    structure_config_path, structure_config = _load_hashed_project_object(
        root,
        structure_reference.get("config"),
        structure_reference.get("config_sha256"),
        label="display-name structure config",
    )
    structure_manifest_path, structure_manifest = _load_hashed_project_object(
        root,
        structure_reference.get("manifest"),
        structure_reference.get("manifest_sha256"),
        label="display-name structure manifest",
    )
    if structure_manifest.get("status") != structure_reference.get("required_status"):
        raise DisplayNameError("display-name structure status drift")
    _, expected_structure_manifest = build_display_name_report(
        root,
        structure_config_path,
    )
    if expected_structure_manifest != structure_manifest:
        raise DisplayNameError("display-name structure manifest is not reproducible")
    _, source_decoded, parsed, structure_context = load_display_name_source(
        root,
        structure_config_path,
    )

    terminology_ids, terminology_report = _load_terminology_ids(
        root,
        config.get("terminology_sources"),
    )
    if selection_policy == _P0_WRITE_POLICY:
        translation_reference = _require_object(
            config.get("translation_source"),
            context="display-name translation source",
        )
        decisions, translation_report = _load_translation_decisions(
            root,
            translation_reference,
            structure_manifest,
            parsed,
            terminology_ids=terminology_ids,
        )
    else:
        translation_sources = _require_object(
            config.get("translation_sources"),
            context="display-name translation sources",
        )
        prior_reference = _require_object(
            translation_sources.get("reviewed_prior"),
            context="reviewed prior display-name source",
        )
        prior_decisions, prior_report = _load_translation_decisions(
            root,
            prior_reference,
            structure_manifest,
            parsed,
            terminology_ids=terminology_ids,
        )
        coverage_reference = _require_object(
            translation_sources.get("researched_coverage"),
            context="researched display-name selection",
        )
        researched_decisions, researched_report = (
            _load_researched_coverage_decisions(
                root,
                coverage_reference,
                parsed,
            )
        )
        overlap = sorted(set(prior_decisions) & set(researched_decisions))
        if overlap:
            raise DisplayNameError(
                "reviewed and researched display-name selections overlap"
            )
        decisions = {**prior_decisions, **researched_decisions}
        translation_report = {
            "mode": "reviewed-prior-plus-researched-exact",
            "reviewed_prior": prior_report,
            "researched_coverage": researched_report,
            "combined_entry_count": len(decisions),
            "overlap_count": 0,
        }

    font_reference = _require_object(
        config.get("font_candidate"),
        context="display-name font candidate",
    )
    font_manifest_path, font_manifest = _load_hashed_project_object(
        root,
        font_reference.get("manifest"),
        font_reference.get("sha256"),
        label="display-name font manifest",
    )
    required_font_status = font_reference.get(
        "required_status",
        "offline_font_and_p0_renderer_coverage_passed_runtime_pending",
    )
    if font_manifest.get("status") != required_font_status:
        raise DisplayNameError("display-name font candidate status is invalid")
    try:
        overrides, codebook_report = load_ui_font_overrides(
            root,
            config,
            font_manifest,
        )
    except ValueError as error:
        raise DisplayNameError(str(error)) from error

    table_path = _project_path(
        root,
        structure_config["text_table"]["path"],
    )
    table = load_text_table(table_path)
    augmented_table = augment_text_table(table, overrides)

    base_reference = _require_object(
        config.get("base_component"),
        context="display-name base component",
    )
    base_config_path, _ = _load_hashed_project_object(
        root,
        base_reference.get("config"),
        base_reference.get("config_sha256"),
        label="base COMPDATA config",
    )
    base_manifest_path, base_manifest = _load_hashed_project_object(
        root,
        base_reference.get("manifest"),
        base_reference.get("manifest_sha256"),
        label="base COMPDATA manifest",
    )
    try:
        base_component, base_report = build_fixed_compdata_component(
            root,
            base_config_path,
        )
    except ValueError as error:
        raise DisplayNameError(str(error)) from error
    if base_report != base_manifest or sha256_bytes(
        base_component
    ) != base_reference.get("output_sha256"):
        raise DisplayNameError("base COMPDATA component is not reproducible")
    base_decoded_result = decode(base_component)
    if base_decoded_result.consumed != len(base_component) or len(
        base_decoded_result.output
    ) != len(source_decoded):
        raise DisplayNameError("base COMPDATA component fails full decode")
    base_decoded = base_decoded_result.output

    entries_by_id = {entry.entry_id: entry for entry in parsed.entries}
    operations = []
    no_op_ids = []
    encoded_sizes = {}
    for entry_id in sorted(decisions):
        entry = entries_by_id[entry_id]
        source_slot = source_decoded[
            entry.target_offset : entry.target_offset + entry.capacity
        ]
        base_slot = base_decoded[
            entry.target_offset : entry.target_offset + entry.capacity
        ]
        if base_slot != source_slot:
            raise DisplayNameError(
                f"base COMPDATA overlaps display-name allocation: {entry_id}"
            )
        try:
            payload = encode_text(
                decisions[entry_id]["translation"],
                table,
                overrides=overrides,
                terminate=True,
            )
        except ValueError as error:
            raise DisplayNameError(
                f"display-name encoding failed for {entry_id}: {error}"
            ) from error
        if len(payload) > entry.capacity:
            raise DisplayNameError(
                f"display-name translation overflows {entry_id}: "
                f"{len(payload)} > {entry.capacity}"
            )
        after = payload + bytes(entry.capacity - len(payload))
        encoded_sizes[entry_id] = len(payload)
        if after == base_slot:
            no_op_ids.append(entry_id)
            continue
        operations.append(
            PatchOperation(
                owner=entry_id,
                offset=entry.target_offset,
                before=base_slot,
                after=after,
            )
        )

    plan = PatchPlan(
        source_name="P0 fixed decoded DATA/COMPDATA.BN",
        source_size=len(base_decoded),
        source_sha256=sha256_bytes(base_decoded),
        operations=tuple(operations),
    )
    output_decoded = plan.apply(base_decoded)
    changed_offsets = _changed_offsets(base_decoded, output_decoded)
    allowed_offsets = {
        offset
        for operation in operations
        for offset in range(operation.offset, operation.end)
    }
    if any(offset not in allowed_offsets for offset in changed_offsets):
        raise DisplayNameError("display-name writer changed non-target bytes")

    unit_pointer_sites = {
        offset
        for entry in parsed.unit_entries
        for pointer in entry.pointer_offsets
        for offset in range(pointer, pointer + 4)
    }
    if any(
        base_decoded[offset] != output_decoded[offset] for offset in unit_pointer_sites
    ):
        raise DisplayNameError("display-name writer modified unit pointer bytes")
    pilot_config = structure_config["pilot_table"]
    pilot_start = _number(
        pilot_config["start"],
        context="pilot table start",
    )
    pilot_stride = pilot_config["record_stride"]
    pilot_id_offset = pilot_config["id_offset"]
    pilot_id_sites = {
        pilot_start + index * pilot_stride + pilot_id_offset + byte_index
        for index in range(pilot_config["record_count"])
        for byte_index in range(2)
    }
    if any(base_decoded[offset] != output_decoded[offset] for offset in pilot_id_sites):
        raise DisplayNameError("display-name writer modified pilot ID bytes")

    reparsed = parse_display_names(
        output_decoded,
        augmented_table,
        structure_config,
        verify_text_preimages=False,
    )
    reparsed_by_id = {entry.entry_id: entry for entry in reparsed.entries}
    for entry_id, decision in decisions.items():
        if reparsed_by_id[entry_id].text != decision["translation"]:
            raise DisplayNameError(f"display-name reread mismatch: {entry_id}")

    codec = _require_object(
        config.get("codec"),
        context="display-name codec",
    )
    if codec.get("mode") != "preserve-base-prefix-reencode-suffix":
        raise DisplayNameError("unsupported display-name codec mode")
    output_component = reencode_changed_suffix(
        base_component,
        output_decoded,
        strategy=codec["strategy"],
        min_match_length=codec["min_match_length"],
        max_match_chain=codec["max_match_chain"],
        lazy_matching=codec["lazy_matching"],
    )
    output_result = decode(output_component)
    if (
        output_result.consumed != len(output_component)
        or output_result.output != output_decoded
        or output_result.flags != base_decoded_result.flags
    ):
        raise DisplayNameError("display-name COMPDATA fails codec round-trip")
    preserved_prefix = next(
        (
            offset
            for offset, (before, after) in enumerate(
                zip(base_component, output_component)
            )
            if before != after
        ),
        min(len(base_component), len(output_component)),
    )

    ratchet = _require_object(
        config.get("ratchet"),
        context="display-name ratchet",
    )
    selection = {
        "translation_entry_count": len(decisions),
        "pilot_translation_entry_count": sum(
            entries_by_id[entry_id].table == "pilot" for entry_id in decisions
        ),
        "unit_translation_entry_count": sum(
            entries_by_id[entry_id].table == "unit" for entry_id in decisions
        ),
        "no_op_entry_count": len(no_op_ids),
        "write_entry_count": len(operations),
        "pointer_write_count": 0,
        "preserved_base_compressed_prefix_size": preserved_prefix,
    }
    checks = {
        "translation_entry_count": (
            selection["translation_entry_count"] == ratchet["translation_entry_count"]
        ),
        "pilot_translation_entry_count": (
            selection["pilot_translation_entry_count"]
            == ratchet["pilot_translation_entry_count"]
        ),
        "unit_translation_entry_count": (
            selection["unit_translation_entry_count"]
            == ratchet["unit_translation_entry_count"]
        ),
        "no_op_entry_count": (
            selection["no_op_entry_count"] == ratchet["no_op_entry_count"]
        ),
        "write_entry_count": (
            selection["write_entry_count"] == ratchet["write_entry_count"]
        ),
        "pointer_write_count": (
            selection["pointer_write_count"] == ratchet["pointer_write_count"]
        ),
        "minimum_preserved_base_compressed_prefix": (
            preserved_prefix >= ratchet["minimum_preserved_base_compressed_prefix"]
        ),
    }
    if not all(checks.values()):
        raise DisplayNameError(f"display-name writeback ratchet failed: {checks}")

    selected_metadata = []
    for entry_id in sorted(decisions):
        entry = entries_by_id[entry_id]
        selected_metadata.append(
            {
                "id": entry_id,
                "table": entry.table,
                "record_index": entry.record_index,
                "field": entry.field,
                "target_offset": entry.target_offset,
                "capacity": entry.capacity,
                "source_encoded_size": entry.encoded_size,
                "output_encoded_size": encoded_sizes[entry_id],
                "source_text_sha256": entry.source_text_sha256,
                "translation_sha256": text_sha256(decisions[entry_id]["translation"]),
                "pointer_record_indices": list(entry.pointer_record_indices),
            }
        )
    non_empty_total = sum(bool(entry.text) for entry in parsed.entries)
    manifest_contract = config.get("manifest_contract", {})
    if not isinstance(manifest_contract, dict):
        raise DisplayNameError("display-name manifest contract is invalid")
    status = manifest_contract.get(
        "status",
        "p0_compdata_and_opening_display_names_validated_iso_runtime_pending",
    )
    remaining_scope = manifest_contract.get(
        "remaining_scope",
        (
            "The remaining names require terminology review and are not "
            "implicitly approved by this opening-route slice."
        ),
    )
    runtime_reason = manifest_contract.get(
        "runtime_reason",
        (
            "This is an isolated combined COMPDATA member. It has not "
            "been placed in an ISO or viewed in PCSX2."
        ),
    )
    if not all(
        isinstance(value, str) and value
        for value in (status, remaining_scope, runtime_reason)
    ):
        raise DisplayNameError("display-name manifest contract is incomplete")

    report = {
        "schema_version": 1,
        "status": status,
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "inputs": {
            "config": {
                "path": str(config_path.relative_to(root)),
                "sha256": sha256_bytes(config_path.read_bytes()),
            },
            "structure": {
                "config": structure_context["config"],
                "manifest": {
                    "path": str(structure_manifest_path.relative_to(root)),
                    "sha256": sha256_bytes(structure_manifest_path.read_bytes()),
                    "status": structure_manifest["status"],
                    "entry_signature_sha256": structure_manifest["totals"][
                        "entry_signature_sha256"
                    ],
                },
                "source_member": structure_context["source_member"],
                "text_table": structure_context["text_table"],
            },
            "translation_source": translation_report,
            "terminology_sources": terminology_report,
            "font_manifest": {
                "path": str(font_manifest_path.relative_to(root)),
                "sha256": sha256_bytes(font_manifest_path.read_bytes()),
            },
            "codebook": codebook_report,
            "base_component": {
                "config": {
                    "path": str(base_config_path.relative_to(root)),
                    "sha256": sha256_bytes(base_config_path.read_bytes()),
                },
                "manifest": {
                    "path": str(base_manifest_path.relative_to(root)),
                    "sha256": sha256_bytes(base_manifest_path.read_bytes()),
                },
                "compressed_sha256": sha256_bytes(base_component),
                "decoded_sha256": sha256_bytes(base_decoded),
                "static_p0_entry_count": base_report["selection"][
                    "fixed_covered_entry_count"
                ],
            },
        },
        "selection": {
            **selection,
            "no_op_entry_ids": no_op_ids,
            "selected_metadata_sha256": sha256_bytes(
                json.dumps(
                    selected_metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "entries": selected_metadata,
        },
        "write": {
            "operation_count": len(operations),
            "owned_capacity": sum(len(operation.after) for operation in operations),
            "changed_byte_count": len(changed_offsets),
            "difference_range_count": _difference_range_count(changed_offsets),
            "patch_plan_metadata_sha256": sha256_bytes(
                json.dumps(
                    plan.to_metadata(),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "unit_pointer_site_byte_count": len(unit_pointer_sites),
            "pilot_id_byte_count": len(pilot_id_sites),
            "pointer_bytes_unchanged": True,
            "pilot_ids_unchanged": True,
            "non_target_bytes_unchanged": True,
            "target_reparse_exact": True,
        },
        "decoded_component": {
            "size": len(output_decoded),
            "base_sha256": sha256_bytes(base_decoded),
            "output_sha256": sha256_bytes(output_decoded),
        },
        "compressed_component": {
            "base_size": len(base_component),
            "output_size": len(output_component),
            "size_delta_from_base": len(output_component) - len(base_component),
            "base_sha256": sha256_bytes(base_component),
            "output_sha256": sha256_bytes(output_component),
            "preserved_base_prefix_size": preserved_prefix,
            "strategy": codec["strategy"],
            "min_match_length": codec["min_match_length"],
            "max_match_chain": codec["max_match_chain"],
            "lazy_matching": codec["lazy_matching"],
            "flags_preserved": True,
            "decoded_round_trip_exact": True,
            "fully_consumed": True,
        },
        "ratchet": {
            "expected": ratchet,
            "checks": checks,
            "passed": True,
        },
        "remaining_work": {
            "source_entry_count": len(parsed.entries),
            "non_empty_source_entry_count": non_empty_total,
            "selected_translation_entry_count": len(decisions),
            "unselected_non_empty_entry_count": non_empty_total - len(decisions),
            "scope": (
                remaining_scope
            ),
        },
        "runtime": {
            "status": "not_tested",
            "reason": (
                runtime_reason
            ),
        },
    }
    return output_component, report


def build_p0_display_name_component(
    project_root: Path,
    config_path: Path,
) -> tuple[bytes, dict]:
    """Backward-compatible opening-route display-name component entry."""

    return build_display_name_component(project_root, config_path)


__all__ = [
    "DisplayNameEntry",
    "DisplayNameError",
    "DisplayNameParseResult",
    "build_display_name_report",
    "build_display_name_component",
    "build_p0_display_name_component",
    "entry_signature_sha256",
    "load_display_name_source",
    "parse_display_names",
]
