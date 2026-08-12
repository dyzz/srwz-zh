"""Clean-room parser for the indexed battle subtitles in ``BTL/SRVC``.

Each SEG chunk starts with four little-endian uint16 values.  The final value
is the number of indexed subtitle records.  The text index is the unique table
whose records are ``<metadata:uint32, text_offset:uint32>`` and whose offsets
describe consecutive NUL-terminated strings immediately after the table.

Some chunks retain additional quote-like bytes after the indexed string pool.
Those bytes are deliberately outside this parser's active records: they have no
entry in the runtime text index and must not be confused with playable lines.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Mapping

from .text import DecodedText, PreparedTextEncoder, TextTable, decode_text


SRVC_MAGIC = 0x4F00
HEADER_SIZE = 8
INDEX_RECORD_SIZE = 8


class SrvcParseError(ValueError):
    """An SRVC chunk does not contain one unambiguous indexed text pool."""


@dataclass(frozen=True)
class SrvcTextRecord:
    chunk_index: int
    record_index: int
    metadata: int
    text_pool_offset: int
    chunk_text_start: int
    chunk_text_end: int
    archive_text_start: int
    archive_text_end: int
    text: str
    unknown_code_count: int

    @property
    def encoded_size(self) -> int:
        return self.chunk_text_end - self.chunk_text_start


@dataclass(frozen=True)
class SrvcChunk:
    chunk_index: int
    archive_start: int
    archive_end: int
    header_field_1: int
    header_field_2: int
    text_record_count: int
    text_index_start: int | None
    text_pool_start: int | None
    indexed_text_end: int | None
    records: tuple[SrvcTextRecord, ...]

    @property
    def size(self) -> int:
        return self.archive_end - self.archive_start

    @property
    def unindexed_tail_size(self) -> int:
        if self.indexed_text_end is None:
            return self.size - HEADER_SIZE
        return self.size - self.indexed_text_end


def _decode_index_candidate(
    data: bytes,
    *,
    chunk_index: int,
    archive_start: int,
    record_count: int,
    index_start: int,
    table: TextTable,
) -> tuple[tuple[SrvcTextRecord, ...], int] | None:
    text_pool_start = index_start + record_count * INDEX_RECORD_SIZE
    if text_pool_start >= len(data):
        return None

    offsets = tuple(
        struct.unpack_from(
            "<I",
            data,
            index_start + record_index * INDEX_RECORD_SIZE + 4,
        )[0]
        for record_index in range(record_count)
    )
    if not offsets or offsets[0] != 0:
        return None
    if any(left >= right for left, right in zip(offsets, offsets[1:])):
        return None
    if text_pool_start + offsets[-1] >= len(data):
        return None

    records = []
    indexed_text_end = text_pool_start
    for record_index, text_offset in enumerate(offsets):
        start = text_pool_start + text_offset
        try:
            decoded: DecodedText = decode_text(
                data,
                start,
                table,
                end=len(data),
            )
        except ValueError:
            return None
        if (
            record_index + 1 < record_count
            and decoded.end != text_pool_start + offsets[record_index + 1]
        ):
            return None
        metadata = struct.unpack_from(
            "<I", data, index_start + record_index * INDEX_RECORD_SIZE
        )[0]
        records.append(
            SrvcTextRecord(
                chunk_index=chunk_index,
                record_index=record_index,
                metadata=metadata,
                text_pool_offset=text_offset,
                chunk_text_start=start,
                chunk_text_end=decoded.end,
                archive_text_start=archive_start + start,
                archive_text_end=archive_start + decoded.end,
                text=decoded.text,
                unknown_code_count=decoded.unknown_code_count,
            )
        )
        indexed_text_end = decoded.end
    return tuple(records), indexed_text_end


def parse_srvc_chunk(
    data: bytes,
    *,
    chunk_index: int,
    archive_start: int,
    table: TextTable,
) -> SrvcChunk:
    """Parse one SEG-delimited SRVC chunk without inspecting adjacent chunks."""

    if len(data) < HEADER_SIZE:
        raise SrvcParseError(f"chunk {chunk_index} is shorter than its header")
    magic, field_1, field_2, record_count = struct.unpack_from("<4H", data)
    if magic != SRVC_MAGIC:
        raise SrvcParseError(
            f"chunk {chunk_index} has magic 0x{magic:04X}, expected 0x{SRVC_MAGIC:04X}"
        )
    archive_end = archive_start + len(data)
    if record_count == 0:
        return SrvcChunk(
            chunk_index=chunk_index,
            archive_start=archive_start,
            archive_end=archive_end,
            header_field_1=field_1,
            header_field_2=field_2,
            text_record_count=0,
            text_index_start=None,
            text_pool_start=None,
            indexed_text_end=None,
            records=(),
        )

    maximum_start = len(data) - record_count * INDEX_RECORD_SIZE
    candidates = []
    for index_start in range(HEADER_SIZE, maximum_start + 1, 4):
        if struct.unpack_from("<I", data, index_start + 4)[0] != 0:
            continue
        decoded = _decode_index_candidate(
            data,
            chunk_index=chunk_index,
            archive_start=archive_start,
            record_count=record_count,
            index_start=index_start,
            table=table,
        )
        if decoded is not None:
            records, indexed_text_end = decoded
            candidates.append((index_start, records, indexed_text_end))

    if len(candidates) != 1:
        raise SrvcParseError(
            f"chunk {chunk_index} has {len(candidates)} valid text-index candidates; "
            "expected exactly one"
        )
    index_start, records, indexed_text_end = candidates[0]
    if any(record.unknown_code_count for record in records):
        raise SrvcParseError(f"chunk {chunk_index} has unknown indexed text codes")
    return SrvcChunk(
        chunk_index=chunk_index,
        archive_start=archive_start,
        archive_end=archive_end,
        header_field_1=field_1,
        header_field_2=field_2,
        text_record_count=record_count,
        text_index_start=index_start,
        text_pool_start=index_start + record_count * INDEX_RECORD_SIZE,
        indexed_text_end=indexed_text_end,
        records=records,
    )


def parse_srvc_chunk_at_index(
    data: bytes,
    *,
    chunk_index: int,
    archive_start: int,
    text_index_start: int | None,
    table: TextTable,
) -> SrvcChunk:
    """Parse a rebuilt chunk using its source-validated index location.

    Releasing zero-filled bytes at the end of a compacted pool can create
    additional heuristic candidates, especially in one-record chunks.  The
    index location itself is structural source metadata and is not changed by
    writeback, so readback should bind to that known location rather than scan
    the translated slack again.
    """

    if len(data) < HEADER_SIZE:
        raise SrvcParseError(f"chunk {chunk_index} is shorter than its header")
    magic, field_1, field_2, record_count = struct.unpack_from("<4H", data)
    if magic != SRVC_MAGIC:
        raise SrvcParseError(
            f"chunk {chunk_index} has magic 0x{magic:04X}, expected 0x{SRVC_MAGIC:04X}"
        )
    archive_end = archive_start + len(data)
    if record_count == 0:
        if text_index_start is not None:
            raise SrvcParseError("zero-record SRVC chunk has an index location")
        return SrvcChunk(
            chunk_index=chunk_index,
            archive_start=archive_start,
            archive_end=archive_end,
            header_field_1=field_1,
            header_field_2=field_2,
            text_record_count=0,
            text_index_start=None,
            text_pool_start=None,
            indexed_text_end=None,
            records=(),
        )
    if text_index_start is None:
        raise SrvcParseError("indexed SRVC chunk has no source index location")
    decoded = _decode_index_candidate(
        data,
        chunk_index=chunk_index,
        archive_start=archive_start,
        record_count=record_count,
        index_start=text_index_start,
        table=table,
    )
    if decoded is None:
        raise SrvcParseError(
            f"chunk {chunk_index} cannot decode its source-bound text index"
        )
    records, indexed_text_end = decoded
    if any(record.unknown_code_count for record in records):
        raise SrvcParseError(f"chunk {chunk_index} has unknown indexed text codes")
    return SrvcChunk(
        chunk_index=chunk_index,
        archive_start=archive_start,
        archive_end=archive_end,
        header_field_1=field_1,
        header_field_2=field_2,
        text_record_count=record_count,
        text_index_start=text_index_start,
        text_pool_start=text_index_start + record_count * INDEX_RECORD_SIZE,
        indexed_text_end=indexed_text_end,
        records=records,
    )


def parse_srvc_archive_with_layout(
    data: bytes,
    offsets: tuple[int, ...],
    source_chunks: tuple[SrvcChunk, ...],
    table: TextTable,
) -> tuple[SrvcChunk, ...]:
    """Parse a rebuilt archive against source-bound chunk/index locations."""

    if (
        len(offsets) != len(source_chunks) + 1
        or offsets[0] != 0
        or offsets[-1] != len(data)
    ):
        raise SrvcParseError("SRVC source layout does not cover rebuilt archive")
    return tuple(
        parse_srvc_chunk_at_index(
            data[start:end],
            chunk_index=chunk_index,
            archive_start=start,
            text_index_start=source_chunks[chunk_index].text_index_start,
            table=table,
        )
        for chunk_index, (start, end) in enumerate(zip(offsets, offsets[1:]))
    )


def parse_srvc_archive(
    data: bytes,
    offsets: tuple[int, ...],
    table: TextTable,
) -> tuple[SrvcChunk, ...]:
    """Parse every chunk covered exactly by a validated SEG offset tuple."""

    if len(offsets) < 2 or offsets[0] != 0 or offsets[-1] != len(data):
        raise SrvcParseError("SEG offsets do not cover the SRVC archive exactly")
    if any(left >= right for left, right in zip(offsets, offsets[1:])):
        raise SrvcParseError("SEG offsets are not strictly increasing")
    return tuple(
        parse_srvc_chunk(
            data[start:end],
            chunk_index=chunk_index,
            archive_start=start,
            table=table,
        )
        for chunk_index, (start, end) in enumerate(zip(offsets, offsets[1:]))
    )


def rebuild_srvc_archive(
    data: bytes,
    offsets: tuple[int, ...],
    source_table: TextTable,
    translations: Mapping[str, str],
    *,
    encoding_overrides: Mapping[str, int],
    parsed_chunks: tuple[SrvcChunk, ...] | None = None,
) -> tuple[bytes, tuple[SrvcChunk, ...], dict[str, int]]:
    """Rebuild each indexed pool without changing its SEG-delimited chunk.

    SRVC string offsets are relative to the start of a chunk's text pool.  A
    shorter translated record therefore cannot simply be NUL-padded in place:
    the parser and runtime expect the next indexed string to start immediately
    after the previous terminator.  This writer compacts translated payloads,
    rewrites only the offset word in each eight-byte index record, zero-fills
    the released pool bytes, and leaves metadata and the unindexed tail at its
    original archive offset.

    The corpus spells SRVC's two raw ASCII line-break marker bytes as ``\\n``.
    They are converted to raw-byte notation before the shared encoder so that
    global fullwidth ASCII routing cannot turn either marker byte into a glyph.
    """

    chunks = parsed_chunks or parse_srvc_archive(data, offsets, source_table)
    if any(
        chunk.archive_start != offsets[chunk.chunk_index]
        or chunk.archive_end != offsets[chunk.chunk_index + 1]
        for chunk in chunks
    ):
        raise SrvcParseError("preparsed SRVC chunk boundaries drift")
    encoder = PreparedTextEncoder(source_table, encoding_overrides)
    output = bytearray(data)
    translated_record_count = 0
    original_pool_bytes = 0
    output_pool_bytes = 0
    minimum_record_headroom: int | None = None
    minimum_chunk_headroom: int | None = None

    for chunk in chunks:
        if not chunk.records:
            continue
        if (
            chunk.text_index_start is None
            or chunk.text_pool_start is None
            or chunk.indexed_text_end is None
        ):
            raise SrvcParseError(
                f"chunk {chunk.chunk_index} has records without a text pool"
            )
        payloads = []
        text_offset = 0
        for record in chunk.records:
            try:
                translation = translations[record.text]
            except KeyError as error:
                raise SrvcParseError(
                    "missing translation for indexed SRVC text in chunk "
                    f"{chunk.chunk_index}, record {record.record_index}"
                ) from error
            if not isinstance(translation, str) or not translation:
                raise SrvcParseError("SRVC translation must be non-empty text")
            stored_text = translation.replace("\\n", "{5C}{6E}")
            payload = encoder.encode(
                stored_text,
                terminate=True,
            )
            if len(payload) > record.encoded_size:
                raise SrvcParseError(
                    "SRVC translation exceeds its original record budget in "
                    f"chunk {chunk.chunk_index}, record {record.record_index}: "
                    f"{len(payload)} > {record.encoded_size}"
                )
            index_word = (
                chunk.archive_start
                + chunk.text_index_start
                + record.record_index * INDEX_RECORD_SIZE
                + 4
            )
            struct.pack_into("<I", output, index_word, text_offset)
            payloads.append(payload)
            text_offset += len(payload)
            headroom = record.encoded_size - len(payload)
            minimum_record_headroom = (
                headroom
                if minimum_record_headroom is None
                else min(minimum_record_headroom, headroom)
            )
            translated_record_count += 1

        pool_capacity = chunk.indexed_text_end - chunk.text_pool_start
        if text_offset > pool_capacity:
            raise SrvcParseError(
                f"chunk {chunk.chunk_index} translated pool exceeds capacity"
            )
        pool_start = chunk.archive_start + chunk.text_pool_start
        pool_end = chunk.archive_start + chunk.indexed_text_end
        output[pool_start:pool_end] = b"".join(payloads) + bytes(
            pool_capacity - text_offset
        )
        original_pool_bytes += pool_capacity
        output_pool_bytes += text_offset
        chunk_headroom = pool_capacity - text_offset
        minimum_chunk_headroom = (
            chunk_headroom
            if minimum_chunk_headroom is None
            else min(minimum_chunk_headroom, chunk_headroom)
        )

    if len(output) != len(data):
        raise SrvcParseError("SRVC archive size changed during rebuild")
    return (
        bytes(output),
        chunks,
        {
            "translated_record_count": translated_record_count,
            "original_indexed_pool_bytes": original_pool_bytes,
            "output_indexed_pool_bytes": output_pool_bytes,
            "released_indexed_pool_bytes": original_pool_bytes - output_pool_bytes,
            "minimum_record_headroom": minimum_record_headroom or 0,
            "minimum_chunk_headroom": minimum_chunk_headroom or 0,
        },
    )
