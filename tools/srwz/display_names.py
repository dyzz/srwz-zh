"""Parse fixed-record pilot and pointer-backed unit display names."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .codec import decode_production as decode
from .codec_contract import DecodeResult
from .font import sha256_bytes
from .text import (
    TextTable,
    decode_text,
    load_text_table,
)


class DisplayNameError(ValueError):
    """Display-name structure, source, or translation data has drifted."""


def text_sha256(text: str) -> str:
    """Return the source-text identity used by display-name records."""

    return sha256_bytes(text.encode("utf-8"))


_EDITORIAL_STATUS_RANK = {
    "todo": 0,
    "draft": 1,
    "reviewed": 2,
    "final": 3,
}
_KANA_PATTERN = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]")
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
    if verify_text_preimages and sha256_bytes(record_bytes) != config.get(
        "record_bytes_sha256"
    ):
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
    if verify_text_preimages and pointer_bytes_sha256 != config.get(
        "pointer_bytes_sha256"
    ):
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
    *,
    decoder: Callable[[bytes], DecodeResult] = decode,
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
    decoded = decoder(stored)
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


def load_full_unit_name_corpus(
    project_root: Path,
    corpus_path: Path,
    source_entries: Sequence[DisplayNameEntry],
) -> tuple[dict[str, dict], dict]:
    """Load the complete index-bound Chinese unit-name corpus.

    The corpus intentionally stores translations by contiguous record ranges.
    Source hashes and fixed-span metadata come from the independently validated
    original display-name structure, so a translation cannot silently drift to
    another pointer-backed slot.
    """

    root = project_root.resolve()
    corpus_path = corpus_path.resolve()
    try:
        corpus_path.relative_to(root)
    except ValueError as error:
        raise DisplayNameError("unit-name corpus path escapes project") from error
    document = _load_json_object(corpus_path)
    scope = _require_object(document.get("scope"), context="unit-name scope")
    segments = document.get("segments")
    expected_count = scope.get("expected_unique_name_count")
    if (
        document.get("schema_version") != 1
        or scope.get("domain") != "display-names"
        or scope.get("table") != "unit"
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count <= 0
        or not isinstance(segments, list)
        or not segments
        or len(source_entries) != expected_count
    ):
        raise DisplayNameError("full unit-name corpus contract is invalid")

    source_by_index = {entry.record_index: entry for entry in source_entries}
    if (
        len(source_by_index) != expected_count
        or set(source_by_index) != set(range(expected_count))
        or any(entry.table != "unit" or entry.field != "name" for entry in source_entries)
    ):
        raise DisplayNameError("unit-name source structure is not contiguous")

    decisions: dict[str, dict] = {}
    status_counts: dict[str, int] = {}
    work_counts: dict[str, int] = {}
    next_index = 0
    for segment_index, raw_segment in enumerate(segments):
        segment = _require_object(
            raw_segment,
            context=f"unit-name segment {segment_index}",
        )
        raw_range = segment.get("range")
        translations = segment.get("translations")
        work = segment.get("work")
        status = segment.get("editorial_status")
        source_refs = segment.get("source_refs")
        if (
            not isinstance(raw_range, list)
            or len(raw_range) != 2
            or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in raw_range
            )
            or raw_range[0] != next_index
            or raw_range[1] < raw_range[0]
            or not isinstance(translations, list)
            or len(translations) != raw_range[1] - raw_range[0] + 1
            or not isinstance(work, str)
            or not work
            or status not in _EDITORIAL_STATUS_RANK
            or _EDITORIAL_STATUS_RANK[status] < _EDITORIAL_STATUS_RANK["draft"]
            or not isinstance(source_refs, list)
            or not source_refs
            or not all(isinstance(ref, str) and ref for ref in source_refs)
        ):
            raise DisplayNameError(
                f"unit-name segment contract is invalid at {segment_index}"
            )
        for offset, translation in enumerate(translations):
            record_index = raw_range[0] + offset
            source = source_by_index.get(record_index)
            if (
                source is None
                or not isinstance(translation, str)
                or not translation
                or _KANA_PATTERN.search(translation)
            ):
                raise DisplayNameError(
                    f"unit-name translation is invalid at record {record_index}"
                )
            entry_id = f"display-name/unit/{record_index:04d}/name"
            if source.entry_id != entry_id or entry_id in decisions:
                raise DisplayNameError(
                    f"unit-name source binding drift at record {record_index}"
                )
            decisions[entry_id] = {
                "id": entry_id,
                "source_text_sha256": source.source_text_sha256,
                "translation": translation,
                "editorial_status": status,
                "source_refs": list(source_refs),
                "work": work,
                "record_index": record_index,
                "target_offset": source.target_offset,
                "capacity": source.capacity,
                "pointer_offsets": list(source.pointer_offsets),
            }
        next_index = raw_range[1] + 1
        status_counts[status] = status_counts.get(status, 0) + len(translations)
        work_counts[work] = work_counts.get(work, 0) + len(translations)

    if next_index != expected_count or len(decisions) != expected_count:
        raise DisplayNameError("full unit-name corpus coverage is incomplete")
    return decisions, {
        "path": str(corpus_path.relative_to(root)),
        "sha256": sha256_bytes(corpus_path.read_bytes()),
        "batch_id": document.get("batch_id"),
        "entry_count": len(decisions),
        "entry_ids_sha256": sha256_bytes(
            json.dumps(
                sorted(decisions),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
        "decisions_sha256": sha256_bytes(
            json.dumps(
                decisions,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
        "editorial_status_counts": status_counts,
        "work_counts": work_counts,
    }


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



__all__ = [
    "DisplayNameEntry",
    "DisplayNameError",
    "DisplayNameParseResult",
    "build_display_name_report",
    "entry_signature_sha256",
    "load_display_name_source",
    "load_full_unit_name_corpus",
    "parse_display_names",
]
