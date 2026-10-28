from __future__ import annotations

import struct
import unittest

from tools.srwz.srvc import (
    INDEX_RECORD_SIZE,
    SRVC_MAGIC,
    parse_srvc_archive,
    parse_srvc_archive_with_layout,
    rebuild_srvc_archive,
    subtitle_line_break_policy_satisfied,
)
from tools.srwz.text import TextTable


class SrvcPoolRebuildTest(unittest.TestCase):
    def test_best_shortening_requires_explicit_line_removal_decision(self):
        source, translated = "first\\nsecond", "first"
        self.assertFalse(subtitle_line_break_policy_satisfied(source, translated, {}))
        decision = {"production_removed_line_break_override": "Best subtitle corrected for identical audio"}
        self.assertTrue(subtitle_line_break_policy_satisfied(source, translated, decision))
        self.assertFalse(subtitle_line_break_policy_satisfied(source, source, decision))
        self.assertFalse(subtitle_line_break_policy_satisfied("a\\nb\\nc", translated, decision))
        self.assertFalse(subtitle_line_break_policy_satisfied(source, translated,
            {**decision, "production_line_break_override": "add"}))

    def test_author_scope_is_encoded_with_battle_restore(self) -> None:
        from tools.srwz.compact_scopes import BATTLE, expand
        from tools.srwz.text import encode_text
        table = TextTable(characters={0x8141: "A", 0x8142: "M", 0x8143: "S", 0x8144: "0", 0x8145: "B"}, tags={0x32: "width", 0x33: "height", 0x34: "space"})
        overrides = {ch: code for code, ch in table.characters.items()}
        chunk = bytearray(24)
        struct.pack_into("<4H", chunk, 0, SRVC_MAGIC, 1, 2, 2)
        struct.pack_into("<II", chunk, 8, 10, 0)
        struct.pack_into("<II", chunk, 16, 20, 3)
        chunk.extend(b"\x81\x41\0" + b"\x81\x45" * 50 + b"\0")
        source = bytes(chunk)
        offsets = (0, len(source))
        authored = "<z>MS0</z>A"
        rebuilt, parsed, _ = rebuild_srvc_archive(source, offsets, table,
            {"A": authored, "B" * 50: "B"}, encoding_overrides=overrides)
        expected = encode_text(expand(authored, BATTLE), table,
            overrides=overrides, terminate=True)
        self.assertEqual(rebuilt[24:24+len(expected)], expected)
        self.assertIn(bytes.fromhex("32163416330b"), expected)
        self.assertEqual(len(rebuilt), len(source))

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
