import struct
import unittest
from pathlib import Path

from tools.srwz.srvc import (
    SrvcParseError,
    parse_srvc_archive,
    parse_srvc_archive_with_layout,
    parse_srvc_chunk,
    rebuild_srvc_archive,
)
from tools.srwz.text import project_runtime_text_table
from tools.srwz.text import encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_TABLE = PROJECT_ROOT / "vendor" / "upstream-python" / "project" / "tbl_all.json"


def synthetic_chunk(lines, *, tail=b"", field_1=3, field_2=2):
    table = load_text_table(TEXT_TABLE)
    prefix = bytes.fromhex("000000ff 010001ff 020001ff")
    payloads = [encode_text(line, table, terminate=True) for line in lines]
    offsets = []
    position = 0
    for payload in payloads:
        offsets.append(position)
        position += len(payload)
    index = b"".join(
        struct.pack("<2I", 0x1000 + ordinal, offset)
        for ordinal, offset in enumerate(offsets)
    )
    header = struct.pack("<4H", 0x4F00, field_1, field_2, len(lines))
    return header + prefix + index + b"".join(payloads) + tail


class SrvcParserTests(unittest.TestCase):
    def test_parses_unique_index_and_excludes_unindexed_tail(self):
        table = load_text_table(TEXT_TABLE)
        indexed = ["「そこだ！」", "「一気に間合いをっ！」"]
        residue = encode_text("「未引用の旧稿」", table, terminate=True)
        chunk = synthetic_chunk(indexed, tail=residue + bytes(3))

        parsed = parse_srvc_chunk(
            chunk,
            chunk_index=7,
            archive_start=0x1200,
            table=table,
        )

        self.assertEqual([record.text for record in parsed.records], indexed)
        self.assertEqual(parsed.text_record_count, 2)
        self.assertEqual(parsed.records[0].metadata, 0x1000)
        self.assertEqual(parsed.records[1].archive_text_start, 0x1200 + parsed.text_pool_start + 13)
        self.assertEqual(parsed.unindexed_tail_size, len(residue) + 3)

    def test_parses_archive_with_zero_record_chunk(self):
        table = load_text_table(TEXT_TABLE)
        empty = struct.pack("<4H", 0x4F00, 0, 0, 0) + bytes(24)
        active = synthetic_chunk(["「了解！」"])
        archive = empty + active
        chunks = parse_srvc_archive(
            archive,
            (0, len(empty), len(archive)),
            table,
        )
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].records, ())
        self.assertEqual(chunks[1].records[0].text, "「了解！」")

    def test_rejects_wrong_magic(self):
        table = load_text_table(TEXT_TABLE)
        with self.assertRaises(SrvcParseError):
            parse_srvc_chunk(
                bytes(32),
                chunk_index=0,
                archive_start=0,
                table=table,
            )

    def test_rebuild_compacts_pool_and_preserves_tail_and_metadata(self):
        table = load_text_table(TEXT_TABLE)
        lines = ["「そこだ！」", "「一気に間合いをっ！」"]
        tail = encode_text("「未引用の旧稿」", table, terminate=True) + bytes(3)
        chunk = synthetic_chunk(lines, tail=tail)
        translations = {
            lines[0]: "上！",
            lines[1]: "冲！",
        }
        overrides = {"上": 0x889F, "冲": 0x88A0}
        rebuilt, original_chunks, report = rebuild_srvc_archive(
            chunk,
            (0, len(chunk)),
            table,
            translations,
            encoding_overrides=overrides,
        )
        output_table = project_runtime_text_table(table, overrides)
        output_chunks = parse_srvc_archive_with_layout(
            rebuilt,
            (0, len(rebuilt)),
            original_chunks,
            output_table,
        )

        self.assertEqual(len(rebuilt), len(chunk))
        self.assertEqual([record.text for record in output_chunks[0].records], ["上！", "冲！"])
        self.assertEqual(
            [record.metadata for record in output_chunks[0].records],
            [record.metadata for record in original_chunks[0].records],
        )
        self.assertEqual(rebuilt[-len(tail) :], tail)
        self.assertGreater(report["released_indexed_pool_bytes"], 0)
        self.assertEqual(report["translated_record_count"], 2)

    def test_rebuild_emits_literal_srvc_linebreak_marker(self):
        table = load_text_table(TEXT_TABLE)
        source = "「前半\\n　後半」"
        chunk = synthetic_chunk([source])
        rebuilt, chunks, _report = rebuild_srvc_archive(
            chunk,
            (0, len(chunk)),
            table,
            {source: "前\\n　后"},
            encoding_overrides={"前": 0x889F, "后": 0x88A0},
        )
        output_table = project_runtime_text_table(
            table, {"前": 0x889F, "后": 0x88A0}
        )
        parsed = parse_srvc_archive_with_layout(
            rebuilt,
            (0, len(rebuilt)),
            chunks,
            output_table,
        )
        self.assertEqual(parsed[0].records[0].text, "前\\n　后")
        self.assertIn(b"\\n", rebuilt)


if __name__ == "__main__":
    unittest.main()
