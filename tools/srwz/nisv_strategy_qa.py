"""Translate the complete runtime Strategy Q&A stored in NISVDATA chunk 6.

The chunk contains one metadata allocation followed by 102 fixed answer-page
allocations.  Metadata strings are sequential and answer text is split into
positioned records whose two style bytes select the runtime colour.  This
module deliberately rebuilds only the text payloads: the allocation table,
metadata indexes, page sizes, record styles, coordinates, sprite sections,
and every non-target archive chunk remain source-exact.
"""

from __future__ import annotations

import struct
from collections import Counter, defaultdict
from typing import Mapping, Sequence

from .codec import decode_production, reencode_changed_suffix
from .compressed_workspace import CompressedStreamWorkspace
from .font import sha256_bytes
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .text import (
    PreparedTextEncoder,
    SrwzTextEncodeError,
    TextTable,
    decode_text,
    normalize_two_byte_visible_spaces,
    project_runtime_text_table,
    two_byte_visible_spaces,
)


QA_PAGE_COUNT = 102
QA_ALLOCATION_COUNT = QA_PAGE_COUNT + 1
QA_DATA_BASE = 0x350
QA_METADATA_TEXT_OFFSET = 0x476
QA_METADATA_GROUPS = (
    ("categories", 4),
    ("topics", 26),
    ("questions", 102),
    ("category_summaries", 4),
    ("topic_summaries", 26),
    ("keyword_summaries", 102),
)
QA_METADATA_STRING_COUNT = sum(count for _name, count in QA_METADATA_GROUPS)
QA_TEXT_RECORD_COUNT = 2609


class NisvStrategyQaError(ValueError):
    """The Strategy Q&A source, corpus, or writeback contract drifted."""


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NisvStrategyQaError(f"{label} must be an integer")
    return value


def _parse_page(data: bytes, start: int, size: int) -> dict:
    end = start + size
    if start < 0 or size <= 4 or end > len(data):
        raise NisvStrategyQaError("Strategy Q&A page allocation is outside chunk")
    text_size = struct.unpack_from("<H", data, start)[0]
    cursor = start + 2
    text_end = cursor + text_size
    if text_end + 2 > end:
        raise NisvStrategyQaError(
            "Strategy Q&A text section exceeds page allocation"
        )
    records = []
    while cursor < text_end:
        if cursor + 8 > text_end:
            raise NisvStrategyQaError(
                "Strategy Q&A text-record header is truncated"
            )
        record_start = cursor
        style0, style1, x, y, z = struct.unpack_from("<BBHHH", data, cursor)
        cursor += 8
        try:
            terminator = data.index(0, cursor, text_end)
        except ValueError as error:
            raise NisvStrategyQaError(
                "Strategy Q&A text record has no in-section terminator"
            ) from error
        records.append(
            {
                "offset": record_start,
                "header": data[record_start : record_start + 8],
                "style0": style0,
                "style1": style1,
                "x": x,
                "y": y,
                "z": z,
                "raw": data[cursor:terminator],
            }
        )
        cursor = terminator + 1
    if cursor != text_end:
        raise NisvStrategyQaError("Strategy Q&A text section boundary drift")
    sprite_size = struct.unpack_from("<H", data, text_end)[0]
    sprite_start = text_end + 2
    sprite_end = sprite_start + sprite_size
    if sprite_end > end:
        raise NisvStrategyQaError(
            "Strategy Q&A sprite section exceeds page allocation"
        )
    padding = data[sprite_end:end]
    if any(padding):
        raise NisvStrategyQaError(
            "Strategy Q&A page has nonzero allocation padding"
        )
    return {
        "start": start,
        "size": size,
        "text_size": text_size,
        "records": records,
        "sprite_size": sprite_size,
        "sprite_bytes": data[sprite_start:sprite_end],
        "padding_size": len(padding),
    }


def parse_nisv_strategy_qa(data: bytes) -> dict:
    """Parse chunk 6 without assigning semantics to style-byte values."""

    if len(data) < QA_DATA_BASE:
        raise NisvStrategyQaError("Strategy Q&A chunk is truncated")
    allocation_count, data_base = struct.unpack_from("<II", data, 0)
    if allocation_count != QA_ALLOCATION_COUNT or data_base != QA_DATA_BASE:
        raise NisvStrategyQaError("Strategy Q&A chunk header drift")

    entries = [
        struct.unpack_from("<II", data, 8 + index * 8)
        for index in range(allocation_count)
    ]
    terminal_offset, terminal_size = struct.unpack_from(
        "<II", data, 8 + allocation_count * 8
    )
    if terminal_size != 0 or terminal_offset != len(data) - data_base:
        raise NisvStrategyQaError("Strategy Q&A allocation sentinel drift")
    if entries[0][0] != 0:
        raise NisvStrategyQaError(
            "Strategy Q&A first allocation does not start at zero"
        )
    for index, (offset, size) in enumerate(entries):
        following = (
            entries[index + 1][0]
            if index + 1 < len(entries)
            else terminal_offset
        )
        if size <= 0 or offset + size != following:
            raise NisvStrategyQaError(
                "Strategy Q&A allocations are not contiguous"
            )

    metadata_start = data_base + entries[0][0]
    metadata_end = metadata_start + entries[0][1]
    if not metadata_start <= QA_METADATA_TEXT_OFFSET < metadata_end:
        raise NisvStrategyQaError("Strategy Q&A metadata text offset drift")
    cursor = QA_METADATA_TEXT_OFFSET
    metadata_strings = []
    for ordinal in range(QA_METADATA_STRING_COUNT):
        try:
            terminator = data.index(0, cursor, metadata_end)
        except ValueError as error:
            raise NisvStrategyQaError(
                f"Strategy Q&A metadata string {ordinal} is unterminated"
            ) from error
        metadata_strings.append(data[cursor:terminator])
        cursor = terminator + 1
    metadata_padding = data[cursor:metadata_end]
    if any(metadata_padding):
        raise NisvStrategyQaError(
            "Strategy Q&A metadata allocation has nonzero trailing bytes"
        )

    metadata = {}
    position = 0
    for name, count in QA_METADATA_GROUPS:
        metadata[name] = tuple(metadata_strings[position : position + count])
        position += count

    pages = tuple(
        _parse_page(data, data_base + offset, size)
        for offset, size in entries[1:]
    )
    record_count = sum(len(page["records"]) for page in pages)
    if len(pages) != QA_PAGE_COUNT or record_count != QA_TEXT_RECORD_COUNT:
        raise NisvStrategyQaError("Strategy Q&A answer-page inventory drift")
    return {
        "allocation_count": allocation_count,
        "data_base": data_base,
        "entries": tuple(entries),
        "terminal_offset": terminal_offset,
        "metadata_start": metadata_start,
        "metadata_size": entries[0][1],
        "metadata_prefix": data[metadata_start:QA_METADATA_TEXT_OFFSET],
        "metadata": metadata,
        "metadata_text_end": cursor,
        "metadata_padding_size": len(metadata_padding),
        "pages": pages,
        "text_record_count": record_count,
    }


def _source_preimage(record: Mapping[str, object], label: str) -> bytes:
    source = record.get("source")
    if not isinstance(source, str) or not source:
        raise NisvStrategyQaError(f"{label} source text is invalid")
    try:
        return source.encode("cp932")
    except UnicodeEncodeError as error:
        raise NisvStrategyQaError(f"{label} source text is not CP932") from error


def _translation(
    record: Mapping[str, object],
    label: str,
    *,
    allow_newlines: bool = False,
    allow_empty: bool = False,
) -> str:
    translation = record.get("translation")
    if not isinstance(translation, str) or (not allow_empty and not translation):
        raise NisvStrategyQaError(f"{label} translation is empty")
    if "\r" in translation or (not allow_newlines and "\n" in translation):
        raise NisvStrategyQaError(f"{label} translation contains a newline")
    return translation


def layout_nisv_strategy_qa_page(
    source_page: Mapping[str, object],
    corpus_records: Sequence[Mapping[str, object]],
    *,
    glyph_advance_px: int,
    line_step_y: int,
    max_last_glyph_x: int,
) -> dict:
    """Lay out translated positioned records as mixed-style Chinese text.

    The stock data breaks a sentence into independently positioned records
    whenever its colour changes.  It also reserves continuation records for
    Japanese lines that are frequently empty after translation.  Treating
    those records as immutable text boxes leaves highlighted terms stranded on
    the following row and makes empty Japanese continuation rows contribute to
    the scroll height.

    This layout pass keeps every record and both style bytes, but flows visible
    records together across colour changes.  Empty continuation records do not
    consume a row.  Repeated multi-column source rows are treated as tables:
    their column anchors stay aligned, and an anchor only moves right when a
    translated label would otherwise overlap the following column.
    """

    if glyph_advance_px <= 0:
        raise NisvStrategyQaError("Strategy Q&A glyph advance must be positive")
    if line_step_y <= 0:
        raise NisvStrategyQaError("Strategy Q&A line step must be positive")
    if max_last_glyph_x <= 0:
        raise NisvStrategyQaError(
            "Strategy Q&A maximum glyph position must be positive"
        )
    source_records = source_page.get("records")
    if not isinstance(source_records, Sequence) or len(source_records) != len(
        corpus_records
    ):
        raise NisvStrategyQaError("Strategy Q&A layout record count drift")

    lines: list[tuple[int, list[int]]] = []
    for ordinal, source_record in enumerate(source_records):
        source_y = _integer(source_record["y"], "Strategy Q&A source y")
        if lines and source_y < lines[-1][0]:
            raise NisvStrategyQaError("Strategy Q&A source y ordering drift")
        if not lines or source_y != lines[-1][0]:
            lines.append((source_y, []))
        lines[-1][1].append(ordinal)

    def source_gap(left_ordinal: int, right_ordinal: int) -> int:
        left_source = source_records[left_ordinal]
        right_source = source_records[right_ordinal]
        left_text = str(corpus_records[left_ordinal].get("source", ""))
        gap = (
            _integer(right_source["x"], "Strategy Q&A source x")
            - _integer(left_source["x"], "Strategy Q&A source x")
            - glyph_advance_px * len(left_text)
        )
        if gap < 0:
            raise NisvStrategyQaError(
                "Strategy Q&A source records overlap on one line"
            )
        return gap

    signatures = Counter(
        tuple(
            _integer(source_records[ordinal]["x"], "Strategy Q&A source x")
            for ordinal in ordinals
        )
        for _source_y, ordinals in lines
        if len(ordinals) >= 2
    )
    repeated_column_anchors: dict[tuple[int, ...], tuple[int, ...]] = {}
    grouped_lines: dict[tuple[int, ...], list[list[int]]] = defaultdict(list)
    for _source_y, ordinals in lines:
        if len(ordinals) < 2:
            continue
        signature = tuple(
            _integer(source_records[ordinal]["x"], "Strategy Q&A source x")
            for ordinal in ordinals
        )
        if signatures[signature] >= 2:
            grouped_lines[signature].append(ordinals)
    for signature, grouped_ordinals in grouped_lines.items():
        anchors = [signature[0]]
        for column in range(1, len(signature)):
            required = signature[column]
            for ordinals in grouped_ordinals:
                previous_ordinal = ordinals[column - 1]
                previous_translation = str(
                    corpus_records[previous_ordinal].get("translation", "")
                )
                if not previous_translation:
                    continue
                gap = source_gap(previous_ordinal, ordinals[column])
                preserved_gap = gap if gap < glyph_advance_px else 0
                required = max(
                    required,
                    anchors[column - 1]
                    + glyph_advance_px * len(previous_translation)
                    + preserved_gap,
                )
            anchors.append(required)
        repeated_column_anchors[signature] = tuple(anchors)

    fixed_lines: set[int] = set()
    fixed_anchors_by_y: dict[int, tuple[int, ...]] = {}
    for source_y, ordinals in lines:
        if len(ordinals) < 2:
            continue
        signature = tuple(
            _integer(source_records[ordinal]["x"], "Strategy Q&A source x")
            for ordinal in ordinals
        )
        has_large_gap = any(
            source_gap(left, right) >= glyph_advance_px
            for left, right in zip(ordinals, ordinals[1:])
        )
        if signature not in repeated_column_anchors and not has_large_gap:
            continue
        fixed_lines.add(source_y)
        anchors = list(repeated_column_anchors.get(signature, signature))
        if signature not in repeated_column_anchors:
            for column in range(1, len(anchors)):
                previous_ordinal = ordinals[column - 1]
                previous_translation = str(
                    corpus_records[previous_ordinal].get("translation", "")
                )
                if not previous_translation:
                    continue
                gap = source_gap(previous_ordinal, ordinals[column])
                preserved_gap = gap if gap < glyph_advance_px else 0
                anchors[column] = max(
                    anchors[column],
                    anchors[column - 1]
                    + glyph_advance_px * len(previous_translation)
                    + preserved_gap,
                )
        fixed_anchors_by_y[source_y] = tuple(anchors)

    blocks: list[list[tuple[int, list[int]]]] = []
    for source_y, ordinals in lines:
        if not blocks or source_y - blocks[-1][-1][0] > line_step_y:
            blocks.append([])
        blocks[-1].append((source_y, ordinals))

    positions: list[tuple[int, int, int] | None] = [None] * len(source_records)
    previous_source_end: int | None = None
    previous_output_end: int | None = None
    body_started = False
    for block in blocks:
        source_start = block[0][0]
        source_end = block[-1][0]
        if not body_started and source_start >= 20:
            output_start = source_start
            body_started = True
        elif not body_started:
            output_start = source_start
        else:
            if previous_source_end is None or previous_output_end is None:
                raise NisvStrategyQaError("Strategy Q&A block state drift")
            source_distance = source_start - previous_source_end
            blank_rows = max(0, source_distance // line_step_y - 1)
            output_start = previous_output_end + (blank_rows + 1) * line_step_y

        later_x = [
            _integer(source_records[ordinal]["x"], "Strategy Q&A source x")
            for _source_y, ordinals in block[1:]
            for ordinal in ordinals
        ]
        all_x = [
            _integer(source_records[ordinal]["x"], "Strategy Q&A source x")
            for _source_y, ordinals in block
            for ordinal in ordinals
        ]
        continuation_x = min(later_x) if later_x else min(all_x)
        output_y = output_start
        cursor_x: int | None = None
        visible_in_block = False

        for source_y, ordinals in block:
            visible_ordinals = [
                ordinal
                for ordinal in ordinals
                if str(corpus_records[ordinal].get("translation", ""))
            ]
            if source_y in fixed_lines and visible_ordinals:
                if cursor_x is not None:
                    output_y += line_step_y
                anchors = fixed_anchors_by_y[source_y]
                for anchor, ordinal in zip(anchors, ordinals):
                    source_record = source_records[ordinal]
                    translation = str(
                        corpus_records[ordinal].get("translation", "")
                    )
                    if translation:
                        last_x = anchor + (len(translation) - 1) * glyph_advance_px
                        if last_x > max_last_glyph_x:
                            raise NisvStrategyQaError(
                                "Strategy Q&A fixed-column text exceeds page width"
                            )
                    positions[ordinal] = (
                        anchor,
                        output_y,
                        _integer(source_record["z"], "Strategy Q&A source z"),
                    )
                cursor_x = max(
                    anchors[ordinals.index(ordinal)]
                    + len(str(corpus_records[ordinal]["translation"]))
                    * glyph_advance_px
                    for ordinal in visible_ordinals
                )
                visible_in_block = True
                continue

            previous_source_ordinal: int | None = None
            for ordinal in ordinals:
                source_record = source_records[ordinal]
                translation = str(
                    corpus_records[ordinal].get("translation", "")
                )
                source_z = _integer(
                    source_record["z"], "Strategy Q&A source z"
                )
                if not translation:
                    positions[ordinal] = (continuation_x, output_y, source_z)
                    previous_source_ordinal = ordinal
                    continue
                if cursor_x is None:
                    output_x = (
                        _integer(source_record["x"], "Strategy Q&A source x")
                        if not visible_in_block
                        else continuation_x
                    )
                else:
                    preserved_gap = 0
                    if previous_source_ordinal is not None:
                        gap = source_gap(previous_source_ordinal, ordinal)
                        if gap < glyph_advance_px:
                            preserved_gap = gap
                    output_x = cursor_x + preserved_gap
                last_x = output_x + (len(translation) - 1) * glyph_advance_px
                if last_x > max_last_glyph_x:
                    output_y += line_step_y
                    output_x = continuation_x
                    last_x = output_x + (len(translation) - 1) * glyph_advance_px
                    if last_x > max_last_glyph_x:
                        raise NisvStrategyQaError(
                            "Strategy Q&A translated record exceeds page width"
                        )
                positions[ordinal] = (output_x, output_y, source_z)
                cursor_x = output_x + len(translation) * glyph_advance_px
                visible_in_block = True
                previous_source_ordinal = ordinal

        visible_y = [
            positions[ordinal][1]
            for _source_y, ordinals in block
            for ordinal in ordinals
            if str(corpus_records[ordinal].get("translation", ""))
        ]
        previous_source_end = source_end
        previous_output_end = max(visible_y) if visible_y else output_start

    if any(position is None for position in positions):
        raise NisvStrategyQaError("Strategy Q&A layout left a record unpositioned")
    typed_positions = tuple(position for position in positions if position is not None)
    visible_positions = [
        position
        for position, corpus_record in zip(typed_positions, corpus_records)
        if str(corpus_record.get("translation", ""))
    ]
    output_max_y = max(position[1] for position in typed_positions)
    visible_max_y = max(position[1] for position in visible_positions)
    if output_max_y != visible_max_y:
        raise NisvStrategyQaError(
            "Strategy Q&A empty record extends the translated scroll height"
        )
    return {
        "positions": typed_positions,
        "fixed_column_line_count": len(fixed_lines),
        "source_max_y": max(
            _integer(record["y"], "Strategy Q&A source y")
            for record in source_records
        ),
        "output_max_y": output_max_y,
        "visible_max_y": visible_max_y,
        "empty_translation_record_count": sum(
            not str(record.get("translation", ""))
            for record in corpus_records
        ),
    }


def _corpus_metadata(corpus: Mapping[str, object]) -> list[tuple[str, Mapping]]:
    raw_metadata = corpus.get("metadata")
    if not isinstance(raw_metadata, Mapping):
        raise NisvStrategyQaError("Strategy Q&A corpus metadata is missing")
    flattened = []
    for group_name, expected_count in QA_METADATA_GROUPS:
        records = raw_metadata.get(group_name)
        if not isinstance(records, list) or len(records) != expected_count:
            raise NisvStrategyQaError(
                f"Strategy Q&A corpus metadata group {group_name!r} drift"
            )
        for ordinal, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise NisvStrategyQaError(
                    f"Strategy Q&A metadata {group_name}[{ordinal}] is invalid"
                )
            expected_id = f"metadata/{group_name}/{ordinal:03d}"
            if record.get("id") != expected_id:
                raise NisvStrategyQaError(
                    f"Strategy Q&A metadata ID drift at {expected_id}"
                )
            flattened.append((expected_id, record))
    return flattened


def _archive_contract(
    slps: bytes,
    source_archive: bytes,
    raw_config: Mapping[str, object],
) -> tuple[ExecutableOffsetSpec, list[int], int, int, bytes, bytes, Mapping]:
    archive_spec = raw_config.get("archive")
    target = raw_config.get("target")
    codec = raw_config.get("codec")
    if not all(isinstance(value, Mapping) for value in (archive_spec, target, codec)):
        raise NisvStrategyQaError("Strategy Q&A build configuration is incomplete")
    try:
        offset_spec = ExecutableOffsetSpec(
            name=str(archive_spec["name"]),
            member=str(archive_spec["member"]),
            table_start=int(str(archive_spec["table_start"]), 0),
            table_end=int(str(archive_spec["table_end"]), 0),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise NisvStrategyQaError(
            "Strategy Q&A archive specification is invalid"
        ) from error
    if archive_spec.get("storage") != "srwz_stream" or archive_spec.get(
        "alignment"
    ) != 16:
        raise NisvStrategyQaError("Strategy Q&A archive policy drift")
    offsets = read_executable_archive_offsets(slps, offset_spec, len(source_archive))
    chunk_index = _integer(target.get("chunk_index"), "Strategy Q&A chunk index")
    if not 0 <= chunk_index < len(offsets) - 1:
        raise NisvStrategyQaError("Strategy Q&A chunk index is outside archive")
    chunk_start, chunk_end = offsets[chunk_index : chunk_index + 2]
    stored = source_archive[chunk_start:chunk_end]
    if (
        chunk_start != target.get("stored_start")
        or chunk_end != target.get("stored_end")
        or len(stored) != target.get("stored_size")
        or sha256_bytes(stored) != target.get("stored_sha256")
    ):
        raise NisvStrategyQaError("Strategy Q&A stored source lock drift")
    decoded = decode_production(stored)
    if (
        decoded.consumed != target.get("stored_consumed")
        or any(stored[decoded.consumed :])
        or len(decoded.output) != target.get("decoded_size")
        or sha256_bytes(decoded.output) != target.get("decoded_sha256")
    ):
        raise NisvStrategyQaError("Strategy Q&A decoded source lock drift")
    return (
        offset_spec,
        offsets,
        chunk_start,
        chunk_end,
        stored,
        decoded.output,
        codec,
    )


def build_nisv_strategy_qa(
    archive: bytes,
    source_archive: bytes,
    slps: bytes,
    raw_config: Mapping[str, object],
    corpus: Mapping[str, object],
    table: TextTable,
    encoding_overrides: Mapping[str, int],
    *,
    workspace: CompressedStreamWorkspace | None = None,
) -> tuple[bytes, dict]:
    """Translate all Strategy Q&A text and preserve its visual record format."""

    if (
        corpus.get("schema_version") != 1
        or corpus.get("selection_authority")
        != "complete_nisvdata_chunk6_strategy_qa_inventory"
        or corpus.get("expected_metadata_string_count")
        != QA_METADATA_STRING_COUNT
        or corpus.get("expected_page_count") != QA_PAGE_COUNT
        or corpus.get("expected_text_record_count") != QA_TEXT_RECORD_COUNT
    ):
        raise NisvStrategyQaError("Strategy Q&A corpus identity drift")
    (
        offset_spec,
        offsets,
        chunk_start,
        chunk_end,
        stored,
        source_decoded,
        codec,
    ) = _archive_contract(slps, source_archive, raw_config)
    if len(archive) != len(source_archive):
        raise NisvStrategyQaError("Strategy Q&A input archive size drift")
    if read_executable_archive_offsets(slps, offset_spec, len(archive)) != offsets:
        raise NisvStrategyQaError("Strategy Q&A input archive offsets drift")
    if workspace is not None and (
        workspace.stored != stored[: raw_config["target"]["stored_consumed"]]
        or len(workspace.current) != len(source_decoded)
    ):
        raise NisvStrategyQaError("Strategy Q&A workspace source drift")

    source = parse_nisv_strategy_qa(source_decoded)
    format_config = raw_config.get("format")
    if not isinstance(format_config, Mapping) or format_config.get(
        "layout_policy"
    ) != "mixed_style_compact_v1":
        raise NisvStrategyQaError("Strategy Q&A layout policy drift")
    glyph_advance_px = _integer(
        format_config.get("glyph_advance_px"), "Strategy Q&A glyph advance"
    )
    line_step_y = _integer(
        format_config.get("line_step_y"), "Strategy Q&A line step"
    )
    max_last_glyph_x = _integer(
        format_config.get("max_last_glyph_x"),
        "Strategy Q&A maximum glyph position",
    )
    expected_page_sizes = raw_config.get("target", {}).get("page_sizes")
    expected_record_counts = raw_config.get("target", {}).get("record_counts")
    if (
        expected_page_sizes
        != [page["size"] for page in source["pages"]]
        or expected_record_counts
        != [len(page["records"]) for page in source["pages"]]
    ):
        raise NisvStrategyQaError("Strategy Q&A page inventory lock drift")

    encoder = PreparedTextEncoder(table, encoding_overrides)
    runtime_table = project_runtime_text_table(table, encoding_overrides)
    modified = bytearray(
        workspace.current if workspace is not None else source_decoded
    )
    metadata_payload = bytearray(source["metadata_prefix"])
    metadata_reports = []
    source_metadata = [
        raw
        for group_name, _count in QA_METADATA_GROUPS
        for raw in source["metadata"][group_name]
    ]
    for (record_id, corpus_record), source_raw in zip(
        _corpus_metadata(corpus), source_metadata
    ):
        if source_raw != _source_preimage(corpus_record, record_id):
            raise NisvStrategyQaError(
                f"Strategy Q&A source preimage drift at {record_id}"
            )
        translation = _translation(corpus_record, record_id, allow_newlines=True)
        try:
            encoded = encoder.encode(
                two_byte_visible_spaces(translation), terminate=True
            )
        except (SrwzTextEncodeError, ValueError) as error:
            raise NisvStrategyQaError(
                f"Strategy Q&A encoding failed at {record_id}: {error}"
            ) from error
        metadata_payload.extend(encoded)
        metadata_reports.append(
            {
                "id": record_id,
                "translation": translation,
                "source_size": len(source_raw),
                "translation_size": len(encoded) - 1,
            }
        )
    if len(metadata_payload) > source["metadata_size"]:
        raise NisvStrategyQaError(
            "Strategy Q&A translated metadata exceeds its allocation"
        )
    metadata_output_size = len(metadata_payload)
    metadata_payload.extend(bytes(source["metadata_size"] - len(metadata_payload)))
    start = source["metadata_start"]
    modified[start : start + source["metadata_size"]] = metadata_payload

    raw_pages = corpus.get("pages")
    if not isinstance(raw_pages, list) or len(raw_pages) != QA_PAGE_COUNT:
        raise NisvStrategyQaError("Strategy Q&A corpus page count drift")
    page_reports = []
    for page_index, (source_page, corpus_page) in enumerate(
        zip(source["pages"], raw_pages), start=1
    ):
        if not isinstance(corpus_page, Mapping) or corpus_page.get("page") != page_index:
            raise NisvStrategyQaError(
                f"Strategy Q&A corpus page ordering drift at page {page_index}"
            )
        corpus_records = corpus_page.get("records")
        if not isinstance(corpus_records, list) or len(corpus_records) != len(
            source_page["records"]
        ):
            raise NisvStrategyQaError(
                f"Strategy Q&A corpus record count drift at page {page_index}"
            )
        for ordinal, corpus_record in enumerate(corpus_records):
            record_id = f"page/{page_index:03d}/record/{ordinal:03d}"
            if not isinstance(corpus_record, Mapping) or corpus_record.get(
                "id"
            ) != record_id:
                raise NisvStrategyQaError(
                    f"Strategy Q&A record ID drift at {record_id}"
                )
            _translation(corpus_record, record_id, allow_empty=True)
        page_layout = layout_nisv_strategy_qa_page(
            source_page,
            corpus_records,
            glyph_advance_px=glyph_advance_px,
            line_step_y=line_step_y,
            max_last_glyph_x=max_last_glyph_x,
        )
        reflowed_positions = page_layout["positions"]
        rebuilt_records = bytearray()
        record_reports = []
        for ordinal, (source_record, corpus_record, output_position) in enumerate(
            zip(source_page["records"], corpus_records, reflowed_positions)
        ):
            record_id = f"page/{page_index:03d}/record/{ordinal:03d}"
            if not isinstance(corpus_record, Mapping) or corpus_record.get(
                "id"
            ) != record_id:
                raise NisvStrategyQaError(
                    f"Strategy Q&A record ID drift at {record_id}"
                )
            if source_record["raw"] != _source_preimage(corpus_record, record_id):
                raise NisvStrategyQaError(
                    f"Strategy Q&A source preimage drift at {record_id}"
                )
            translation = _translation(corpus_record, record_id, allow_empty=True)
            try:
                encoded = encoder.encode(
                    two_byte_visible_spaces(translation), terminate=True
                )
            except (SrwzTextEncodeError, ValueError) as error:
                raise NisvStrategyQaError(
                    f"Strategy Q&A encoding failed at {record_id}: {error}"
                ) from error
            rebuilt_records.extend(
                struct.pack(
                    "<BBHHH",
                    source_record["style0"],
                    source_record["style1"],
                    *output_position,
                )
            )
            rebuilt_records.extend(encoded)
            record_reports.append(
                {
                    "id": record_id,
                    "translation": translation,
                    "source_size": len(source_record["raw"]),
                    "translation_size": len(encoded) - 1,
                    "style": [source_record["style0"], source_record["style1"]],
                    "position": [
                        output_position[0],
                        output_position[1],
                        output_position[2],
                    ],
                    "source_position": [
                        source_record["x"],
                        source_record["y"],
                        source_record["z"],
                    ],
                }
            )
        page_payload = bytearray(struct.pack("<H", len(rebuilt_records)))
        page_payload.extend(rebuilt_records)
        page_payload.extend(struct.pack("<H", source_page["sprite_size"]))
        page_payload.extend(source_page["sprite_bytes"])
        if len(page_payload) > source_page["size"]:
            raise NisvStrategyQaError(
                f"Strategy Q&A page {page_index} exceeds its allocation by "
                f"{len(page_payload) - source_page['size']} bytes"
            )
        used_size = len(page_payload)
        page_payload.extend(bytes(source_page["size"] - used_size))
        page_start = source_page["start"]
        modified[page_start : page_start + source_page["size"]] = page_payload
        page_reports.append(
            {
                "page": page_index,
                "record_count": len(record_reports),
                "allocation_size": source_page["size"],
                "source_text_size": source_page["text_size"],
                "output_text_size": len(rebuilt_records),
                "output_padding_size": source_page["size"] - used_size,
                "fixed_column_line_count": page_layout[
                    "fixed_column_line_count"
                ],
                "source_max_y": page_layout["source_max_y"],
                "output_max_y": page_layout["output_max_y"],
                "visible_max_y": page_layout["visible_max_y"],
                "empty_translation_record_count": page_layout[
                    "empty_translation_record_count"
                ],
                "records": record_reports,
            }
        )
    modified_bytes = bytes(modified)

    if workspace is not None:
        try:
            workspace.replace(modified_bytes, stage="NISVDATA Strategy Q&A")
        except ValueError as error:
            raise NisvStrategyQaError(str(error)) from error
        rebuilt = None
        output = archive
        reread_qa = parse_nisv_strategy_qa(modified_bytes)
    else:
        try:
            rebuilt = reencode_changed_suffix(
                stored,
                modified_bytes,
                strategy=str(codec.get("strategy")),
                min_match_length=_integer(
                    codec.get("min_match_length"),
                    "Strategy Q&A codec min-match",
                ),
                max_match_chain=_integer(
                    codec.get("max_match_chain"),
                    "Strategy Q&A codec max-chain",
                ),
                lazy_matching=codec.get("lazy_matching"),
                max_output_size=len(stored),
            )
        except (RuntimeError, ValueError) as error:
            raise NisvStrategyQaError(
                f"Strategy Q&A compression failed: {error}"
            ) from error
        round_trip = decode_production(rebuilt)
        if (
            round_trip.consumed != len(rebuilt)
            or round_trip.output != modified_bytes
        ):
            raise NisvStrategyQaError("Strategy Q&A codec round trip failed")
        padded = rebuilt + bytes(len(stored) - len(rebuilt))
        output = archive[:chunk_start] + padded + archive[chunk_end:]
        if (
            len(output) != len(archive)
            or output[:chunk_start] != archive[:chunk_start]
            or output[chunk_end:] != archive[chunk_end:]
            or read_executable_archive_offsets(slps, offset_spec, len(output))
            != offsets
        ):
            raise NisvStrategyQaError("Strategy Q&A archive layout changed")
        reread = decode_production(output[chunk_start:chunk_end])
        reread_qa = parse_nisv_strategy_qa(reread.output)
    corpus_metadata = _corpus_metadata(corpus)
    reread_metadata = [
        raw
        for group_name, _count in QA_METADATA_GROUPS
        for raw in reread_qa["metadata"][group_name]
    ]
    for (record_id, corpus_record), raw in zip(corpus_metadata, reread_metadata):
        decoded_text = decode_text(raw + b"\x00", 0, runtime_table).text
        if normalize_two_byte_visible_spaces(decoded_text) != corpus_record["translation"]:
            raise NisvStrategyQaError(
                f"Strategy Q&A metadata reread failed at {record_id}"
            )
    for page_index, (source_page, reread_page, corpus_page) in enumerate(
        zip(source["pages"], reread_qa["pages"], raw_pages), start=1
    ):
        for ordinal, (source_record, record, corpus_record) in enumerate(
            zip(
                source_page["records"],
                reread_page["records"],
                corpus_page["records"],
            )
        ):
            record_id = f"page/{page_index:03d}/record/{ordinal:03d}"
            decoded_text = decode_text(record["raw"] + b"\x00", 0, runtime_table).text
            if normalize_two_byte_visible_spaces(decoded_text) != corpus_record[
                "translation"
            ]:
                raise NisvStrategyQaError(
                    f"Strategy Q&A translated reread failed at {record_id}"
                )
            for field in ("style0", "style1"):
                if record[field] != source_record[field]:
                    raise NisvStrategyQaError(
                        f"Strategy Q&A visual record drift at {record_id}: {field}"
                    )
            expected_position = layout_nisv_strategy_qa_page(
                source_page,
                corpus_page["records"],
                glyph_advance_px=glyph_advance_px,
                line_step_y=line_step_y,
                max_last_glyph_x=max_last_glyph_x,
            )["positions"][ordinal]
            if (record["x"], record["y"], record["z"]) != expected_position:
                raise NisvStrategyQaError(
                    f"Strategy Q&A reflow reread failed at {record_id}"
                )
    if workspace is None and any(
        output[chunk_start + reread.consumed : chunk_end]
    ):
        raise NisvStrategyQaError("Strategy Q&A stored padding is nonzero")

    source_style_counts = Counter(
        (record["style0"], record["style1"])
        for page in source["pages"]
        for record in page["records"]
    )
    return output, {
        "member": raw_config["archive"]["member"],
        "chunk_index": raw_config["target"]["chunk_index"],
        "metadata_string_count": len(metadata_reports),
        "metadata_allocation_size": source["metadata_size"],
        "metadata_output_size": metadata_output_size,
        "metadata_output_padding_size": source["metadata_size"]
        - metadata_output_size,
        "page_count": len(page_reports),
        "text_record_count": sum(page["record_count"] for page in page_reports),
        "pages": page_reports,
        "style_counts": {
            f"{style0:02X}:{style1:02X}": count
            for (style0, style1), count in sorted(source_style_counts.items())
        },
        "source_stored_size": len(stored),
        "output_encoded_size": None if rebuilt is None else len(rebuilt),
        "output_padding_size": (
            None if rebuilt is None else len(stored) - len(rebuilt)
        ),
        "compression_deferred_to_workspace": workspace is not None,
        "archive_size_preserved": True,
        "archive_offsets_preserved": True,
        "non_target_chunks_preserved_byte_exact": True,
        "allocation_table_preserved": True,
        "metadata_indexes_preserved": True,
        "page_allocations_preserved": True,
        "record_styles_preserved": True,
        "record_z_coordinates_preserved": True,
        "mixed_style_line_flow": True,
        "empty_continuation_rows_collapsed": True,
        "fixed_column_anchors_aligned": True,
        "glyph_advance_px": glyph_advance_px,
        "line_step_y": line_step_y,
        "max_last_glyph_x": max_last_glyph_x,
        "reflowed_record_count": sum(
            record["position"] != record["source_position"]
            for page in page_reports
            for record in page["records"]
        ),
        "horizontally_reflowed_record_count": sum(
            record["position"][0] != record["source_position"][0]
            for page in page_reports
            for record in page["records"]
        ),
        "vertically_reflowed_record_count": sum(
            record["position"][1] != record["source_position"][1]
            for page in page_reports
            for record in page["records"]
        ),
        "fixed_column_line_count": sum(
            page["fixed_column_line_count"] for page in page_reports
        ),
        "empty_translation_record_count": sum(
            page["empty_translation_record_count"] for page in page_reports
        ),
        "empty_records_extend_scroll_height": any(
            page["output_max_y"] != page["visible_max_y"]
            for page in page_reports
        ),
        "sprite_sections_preserved": True,
        "translated_reread_exact": True,
        "metadata": metadata_reports,
    }


__all__ = [
    "NisvStrategyQaError",
    "QA_ALLOCATION_COUNT",
    "QA_DATA_BASE",
    "QA_METADATA_GROUPS",
    "QA_METADATA_STRING_COUNT",
    "QA_METADATA_TEXT_OFFSET",
    "QA_PAGE_COUNT",
    "QA_TEXT_RECORD_COUNT",
    "build_nisv_strategy_qa",
    "layout_nisv_strategy_qa_page",
    "parse_nisv_strategy_qa",
]
