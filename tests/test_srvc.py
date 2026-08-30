from __future__ import annotations

import struct
import unittest

from tools.srwz.srvc import (
    INDEX_RECORD_SIZE,
    SRVC_MAGIC,
    parse_srvc_archive,
    parse_srvc_archive_with_layout,
    rebuild_srvc_archive,
)
from tools.srwz.text import TextTable


class SrvcPoolRebuildTest(unittest.TestCase):
    def test_record_can_borrow_released_bytes_within_its_chunk(self) -> None:
        table = TextTable(
            characters={0x8141: "A", 0x8142: "B"},
            tags={},
        )
        encoding_overrides = {"A": 0x8141, "B": 0x8142}
        first = struct.pack(">H", 0x8141) + b"\x00"
        second = struct.pack(">H", 0x8142) * 4 + b"\x00"
        index_start = 8
        text_pool_start = index_start + 2 * INDEX_RECORD_SIZE
        chunk = bytearray(text_pool_start)
        struct.pack_into("<4H", chunk, 0, SRVC_MAGIC, 1, 2, 2)
        struct.pack_into("<II", chunk, index_start, 10, 0)
        struct.pack_into("<II", chunk, index_start + INDEX_RECORD_SIZE, 20, len(first))
        chunk.extend(first + second)
        source = bytes(chunk)
        offsets = (0, len(source))
        parsed = parse_srvc_archive(source, offsets, table)

        rebuilt, source_chunks, report = rebuild_srvc_archive(
            source,
            offsets,
            table,
            {"A": "AAA", "BBBB": "B"},
            encoding_overrides=encoding_overrides,
            parsed_chunks=parsed,
        )
        reread = parse_srvc_archive_with_layout(
            rebuilt,
            offsets,
            source_chunks,
            table,
        )

        self.assertEqual([record.text for record in reread[0].records], ["AAA", "B"])
        self.assertEqual([record.metadata for record in reread[0].records], [10, 20])
        self.assertEqual(len(rebuilt), len(source))
        self.assertEqual(report["minimum_record_headroom"], -4)
        self.assertEqual(report["minimum_chunk_headroom"], 2)
        self.assertEqual(report["expanded_record_count"], 1)

    def test_records_cannot_exceed_their_complete_chunk_pool(self) -> None:
        table = TextTable(
            characters={0x8141: "A", 0x8142: "B"},
            tags={},
        )
        encoding_overrides = {"A": 0x8141, "B": 0x8142}
        first = struct.pack(">H", 0x8141) + b"\x00"
        second = struct.pack(">H", 0x8142) * 4 + b"\x00"
        index_start = 8
        text_pool_start = index_start + 2 * INDEX_RECORD_SIZE
        chunk = bytearray(text_pool_start)
        struct.pack_into("<4H", chunk, 0, SRVC_MAGIC, 1, 2, 2)
        struct.pack_into("<II", chunk, index_start, 10, 0)
        struct.pack_into("<II", chunk, index_start + INDEX_RECORD_SIZE, 20, len(first))
        chunk.extend(first + second)
        source = bytes(chunk)
        offsets = (0, len(source))
        parsed = parse_srvc_archive(source, offsets, table)

        with self.assertRaisesRegex(
            ValueError,
            "chunk 0 translated pool exceeds capacity",
        ):
            rebuild_srvc_archive(
                source,
                offsets,
                table,
                {"A": "AAAAAA", "BBBB": "BBBB"},
                encoding_overrides=encoding_overrides,
                parsed_chunks=parsed,
            )


if __name__ == "__main__":
    unittest.main()
