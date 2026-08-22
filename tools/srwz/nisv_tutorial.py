"""Translate the ten runtime tutorial pages in NISVDATA chunk 5.

The page heading strings live in SLPS and are handled by the fixed-string
writer.  This module owns only the body-page container: ten fixed allocations
containing 114 positioned text records.  Record style and all coordinates stay
source-exact unless a corpus record declares a narrowly scoped position
override.  Page allocations, the outer archive offset table, and every
non-target chunk remain byte-exact.
"""

from __future__ import annotations

import struct
from typing import Mapping

from .codec import decode_production, reencode_changed_suffix
from .font import sha256_bytes
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .text import (
    PreparedTextEncoder,
    SrwzTextEncodeError,
    TextTable,
    decode_text,
    project_runtime_text_table,
)


class NisvTutorialError(ValueError):
    """The tutorial-page source or writeback contract drifted."""


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NisvTutorialError(f"{label} must be an integer")
    return value


def _parse_page(data: bytes, start: int, size: int) -> dict:
    end = start + size
    if start < 0 or size <= 4 or end > len(data):
        raise NisvTutorialError("tutorial page allocation is outside chunk")
    text_size = struct.unpack_from("<H", data, start)[0]
    cursor = start + 2
    text_end = cursor + text_size
    if text_end + 2 > end:
        raise NisvTutorialError("tutorial text section exceeds page allocation")
    records = []
    while cursor < text_end:
        if cursor + 8 > text_end:
            raise NisvTutorialError("tutorial text-record header is truncated")
        record_start = cursor
        style0, style1, x, y, z = struct.unpack_from("<BBHHH", data, cursor)
        cursor += 8
        try:
            terminator = data.index(0, cursor, text_end)
        except ValueError as error:
            raise NisvTutorialError(
                "tutorial text record has no in-section terminator"
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
        raise NisvTutorialError("tutorial text section boundary drift")
    sprite_size = struct.unpack_from("<H", data, text_end)[0]
    sprite_start = text_end + 2
    sprite_end = sprite_start + sprite_size
    if sprite_end > end:
        raise NisvTutorialError("tutorial sprite section exceeds page allocation")
    padding = data[sprite_end:end]
    if any(padding):
        raise NisvTutorialError("tutorial page has nonzero allocation padding")
    return {
        "start": start,
        "size": size,
        "text_size": text_size,
        "records": records,
        "sprite_size": sprite_size,
        "sprite_bytes": data[sprite_start:sprite_end],
        "padding_size": len(padding),
    }


def parse_nisv_tutorial_pages(data: bytes) -> tuple[dict, ...]:
    """Parse the fixed ten-page chunk without interpreting its text codebook."""

    if len(data) < 0x60:
        raise NisvTutorialError("tutorial chunk is truncated")
    page_count, data_base = struct.unpack_from("<II", data, 0)
    if page_count != 10 or data_base != 0x60:
        raise NisvTutorialError("tutorial chunk header drift")
    entries = []
    for index in range(page_count):
        offset, size = struct.unpack_from("<II", data, 8 + index * 8)
        entries.append((offset, size))
    terminal_offset, terminal_size = struct.unpack_from(
        "<II", data, 8 + page_count * 8
    )
    if terminal_size != 0 or terminal_offset != len(data) - data_base:
        raise NisvTutorialError("tutorial page sentinel drift")
    if entries[0][0] != 0:
        raise NisvTutorialError("tutorial first page does not start at zero")
    for index, (offset, size) in enumerate(entries):
        following = (
            entries[index + 1][0]
            if index + 1 < len(entries)
            else terminal_offset
        )
        if size <= 0 or offset + size != following:
            raise NisvTutorialError("tutorial page allocations are not contiguous")
    return tuple(
        _parse_page(data, data_base + offset, size) for offset, size in entries
    )


def _source_preimage(record: Mapping[str, object]) -> bytes:
    source = record.get("source")
    prefix_hex = record.get("source_prefix_hex", "")
    if not isinstance(source, str) or not source or not isinstance(prefix_hex, str):
        raise NisvTutorialError("tutorial corpus source record is invalid")
    try:
        return bytes.fromhex(prefix_hex) + source.encode("cp932")
    except (UnicodeEncodeError, ValueError) as error:
        raise NisvTutorialError("tutorial corpus source preimage is invalid") from error


def _record_position(
    source_record: Mapping[str, object],
    corpus_record: Mapping[str, object],
) -> tuple[int, int, int]:
    """Return a source position with optional, explicit per-axis overrides."""

    position = [
        _integer(source_record["x"], "tutorial source x"),
        _integer(source_record["y"], "tutorial source y"),
        _integer(source_record["z"], "tutorial source z"),
    ]
    raw_override = corpus_record.get("position")
    if raw_override is None:
        return tuple(position)
    if not isinstance(raw_override, Mapping) or not raw_override:
        raise NisvTutorialError("tutorial position override must be a nonempty object")
    unknown = set(raw_override) - {"x", "y", "z"}
    if unknown:
        raise NisvTutorialError(
            f"tutorial position override has unknown axes: {sorted(unknown)!r}"
        )
    for axis, index in (("x", 0), ("y", 1), ("z", 2)):
        if axis not in raw_override:
            continue
        value = _integer(raw_override[axis], f"tutorial override {axis}")
        if not 0 <= value <= 0xFFFF:
            raise NisvTutorialError(f"tutorial override {axis} exceeds uint16")
        position[index] = value
    return tuple(position)


def build_nisv_tutorial_pages(
    archive: bytes,
    slps: bytes,
    raw_config: Mapping[str, object],
    corpus: Mapping[str, object],
    table: TextTable,
    encoding_overrides: Mapping[str, int],
) -> tuple[bytes, dict]:
    """Translate chunk 5 and return the fixed-size NISVDATA archive."""

    archive_spec = raw_config.get("archive")
    target = raw_config.get("target")
    codec = raw_config.get("codec")
    if not all(isinstance(value, Mapping) for value in (archive_spec, target, codec)):
        raise NisvTutorialError("tutorial build configuration is incomplete")
    if (
        corpus.get("schema_version") != 1
        or corpus.get("selection_authority")
        != "complete_nisvdata_chunk5_page_and_record_inventory"
        or corpus.get("expected_page_count") != 10
        or corpus.get("expected_text_record_count") != 114
    ):
        raise NisvTutorialError("tutorial corpus identity drift")
    raw_pages = corpus.get("pages")
    if not isinstance(raw_pages, list) or len(raw_pages) != 10:
        raise NisvTutorialError("tutorial corpus page count drift")

    try:
        offset_spec = ExecutableOffsetSpec(
            name=str(archive_spec["name"]),
            member=str(archive_spec["member"]),
            table_start=int(str(archive_spec["table_start"]), 0),
            table_end=int(str(archive_spec["table_end"]), 0),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise NisvTutorialError("tutorial archive specification is invalid") from error
    if archive_spec.get("storage") != "srwz_stream" or archive_spec.get(
        "alignment"
    ) != 16:
        raise NisvTutorialError("tutorial archive policy drift")
    offsets = read_executable_archive_offsets(slps, offset_spec, len(archive))
    chunk_index = _integer(target.get("chunk_index"), "tutorial chunk index")
    if not 0 <= chunk_index < len(offsets) - 1:
        raise NisvTutorialError("tutorial chunk index is outside archive")
    chunk_start, chunk_end = offsets[chunk_index : chunk_index + 2]
    stored = archive[chunk_start:chunk_end]
    if (
        chunk_start != target.get("stored_start")
        or chunk_end != target.get("stored_end")
        or len(stored) != target.get("stored_size")
        or sha256_bytes(stored) != target.get("stored_sha256")
    ):
        raise NisvTutorialError("tutorial stored chunk lock drift")
    decoded = decode_production(stored)
    if (
        decoded.consumed != target.get("stored_consumed")
        or any(stored[decoded.consumed :])
        or len(decoded.output) != target.get("decoded_size")
        or sha256_bytes(decoded.output) != target.get("decoded_sha256")
    ):
        raise NisvTutorialError("tutorial decoded chunk lock drift")
    pages = parse_nisv_tutorial_pages(decoded.output)
    expected_sizes = target.get("page_sizes")
    expected_counts = target.get("record_counts")
    if (
        expected_sizes != [page["size"] for page in pages]
        or expected_counts != [len(page["records"]) for page in pages]
        or sum(expected_counts) != 114
    ):
        raise NisvTutorialError("tutorial page inventory drift")

    encoder = PreparedTextEncoder(table, encoding_overrides)
    runtime_table = project_runtime_text_table(table, encoding_overrides)
    modified = bytearray(decoded.output)
    page_reports = []
    record_total = 0
    for index, (source_page, corpus_page) in enumerate(zip(pages, raw_pages)):
        if not isinstance(corpus_page, Mapping) or corpus_page.get("page") != index + 1:
            raise NisvTutorialError("tutorial corpus page ordering drift")
        corpus_records = corpus_page.get("records")
        if not isinstance(corpus_records, list) or len(corpus_records) != len(
            source_page["records"]
        ):
            raise NisvTutorialError("tutorial corpus record count drift")
        rebuilt_records = bytearray()
        record_reports = []
        for ordinal, (source_record, corpus_record) in enumerate(
            zip(source_page["records"], corpus_records)
        ):
            if not isinstance(corpus_record, Mapping):
                raise NisvTutorialError("tutorial corpus record is invalid")
            if source_record["raw"] != _source_preimage(corpus_record):
                raise NisvTutorialError(
                    f"tutorial source preimage drift at page {index + 1}, "
                    f"record {ordinal}"
                )
            translation = corpus_record.get("translation")
            if not isinstance(translation, str) or not translation:
                raise NisvTutorialError("tutorial translation is empty")
            try:
                encoded = encoder.encode(translation, terminate=True)
            except (SrwzTextEncodeError, ValueError) as error:
                raise NisvTutorialError(
                    f"tutorial translation encoding failed at page {index + 1}, "
                    f"record {ordinal}: {error}"
                ) from error
            source_position = (
                source_record["x"],
                source_record["y"],
                source_record["z"],
            )
            position = _record_position(source_record, corpus_record)
            rebuilt_records.extend(
                struct.pack(
                    "<BBHHH",
                    source_record["style0"],
                    source_record["style1"],
                    *position,
                )
            )
            rebuilt_records.extend(encoded)
            record_reports.append(
                {
                    "ordinal": ordinal,
                    "translation": translation,
                    "source_size": len(source_record["raw"]),
                    "translation_size": len(encoded) - 1,
                    "style": [source_record["style0"], source_record["style1"]],
                    "source_position": list(source_position),
                    "position": list(position),
                    "coordinate_overridden": position != source_position,
                }
            )
        page_payload = (
            struct.pack("<H", len(rebuilt_records))
            + bytes(rebuilt_records)
            + struct.pack("<H", source_page["sprite_size"])
            + source_page["sprite_bytes"]
        )
        if len(page_payload) > source_page["size"]:
            raise NisvTutorialError(
                f"tutorial page {index + 1} exceeds its allocation"
            )
        used_size = len(page_payload)
        page_payload += bytes(source_page["size"] - used_size)
        start = source_page["start"]
        modified[start : start + source_page["size"]] = page_payload
        page_reports.append(
            {
                "page": index + 1,
                "record_count": len(record_reports),
                "allocation_size": source_page["size"],
                "source_text_size": source_page["text_size"],
                "output_text_size": len(rebuilt_records),
                "output_padding_size": source_page["size"] - used_size,
                "records": record_reports,
            }
        )
        record_total += len(record_reports)
    if record_total != 114:
        raise NisvTutorialError("tutorial translated record total drift")
    modified_bytes = bytes(modified)

    try:
        rebuilt = reencode_changed_suffix(
            stored[: decoded.consumed],
            modified_bytes,
            strategy=str(codec.get("strategy")),
            min_match_length=_integer(
                codec.get("min_match_length"), "tutorial codec min-match"
            ),
            max_match_chain=_integer(
                codec.get("max_match_chain"), "tutorial codec max-chain"
            ),
            lazy_matching=codec.get("lazy_matching"),
            max_output_size=len(stored),
        )
    except (RuntimeError, ValueError) as error:
        raise NisvTutorialError(f"tutorial compression failed: {error}") from error
    round_trip = decode_production(rebuilt)
    if (
        round_trip.consumed != len(rebuilt)
        or round_trip.output != modified_bytes
        or round_trip.flags != decoded.flags
    ):
        raise NisvTutorialError("tutorial codec round trip failed")
    padded = rebuilt + bytes(len(stored) - len(rebuilt))
    output = archive[:chunk_start] + padded + archive[chunk_end:]
    if (
        len(output) != len(archive)
        or output[:chunk_start] != archive[:chunk_start]
        or output[chunk_end:] != archive[chunk_end:]
        or read_executable_archive_offsets(slps, offset_spec, len(output)) != offsets
    ):
        raise NisvTutorialError("tutorial archive layout changed")
    reread = decode_production(output[chunk_start:chunk_end])
    reread_pages = parse_nisv_tutorial_pages(reread.output)
    for index, (page, corpus_page) in enumerate(zip(reread_pages, raw_pages)):
        for ordinal, (record, corpus_record) in enumerate(
            zip(page["records"], corpus_page["records"])
        ):
            decoded_text = decode_text(record["raw"] + b"\x00", 0, runtime_table)
            if decoded_text.text != corpus_record["translation"]:
                raise NisvTutorialError(
                    f"tutorial translated reread failed at page {index + 1}, "
                    f"record {ordinal}"
                )
            expected_position = _record_position(
                pages[index]["records"][ordinal], corpus_record
            )
            if (record["x"], record["y"], record["z"]) != expected_position:
                raise NisvTutorialError(
                    f"tutorial position reread failed at page {index + 1}, "
                    f"record {ordinal}"
                )
    if any(output[chunk_start + reread.consumed : chunk_end]):
        raise NisvTutorialError("tutorial stored padding is nonzero")
    return output, {
        "member": archive_spec["member"],
        "chunk_index": chunk_index,
        "page_count": len(page_reports),
        "text_record_count": record_total,
        "pages": page_reports,
        "source_stored_size": len(stored),
        "output_encoded_size": len(rebuilt),
        "output_padding_size": len(stored) - len(rebuilt),
        "archive_size_preserved": True,
        "archive_offsets_preserved": True,
        "non_target_chunks_preserved_byte_exact": True,
        "record_styles_preserved": True,
        "undeclared_coordinates_preserved": True,
        "coordinate_override_count": sum(
            record["coordinate_overridden"]
            for page in page_reports
            for record in page["records"]
        ),
        "page_allocations_preserved": True,
        "translated_reread_exact": True,
    }


__all__ = [
    "NisvTutorialError",
    "build_nisv_tutorial_pages",
    "parse_nisv_tutorial_pages",
]
