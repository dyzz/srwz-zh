import struct
import unittest
from pathlib import Path

from tools.srwz.summary import parse_summary
from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_TABLE = (
    PROJECT_ROOT / "vendor" / "upstream-python" / "project" / "tbl_all.json"
)


class SummaryParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_text_table(TEXT_TABLE)

    def test_parses_fixed_length_text_record(self):
        data = bytearray(0x90)
        struct.pack_into("<I", data, 0x2C, 1)
        data[0x3C:0x40] = b"text"
        struct.pack_into("<I", data, 0x40, 0x40)
        struct.pack_into("<I", data, 0x66, 6)
        data[0x6A:0x70] = b"Hello\x00"

        result = parse_summary(
            bytes(data),
            self.table,
            chunk_index=0,
        )

        self.assertEqual(result.section_count, 1)
        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.entry_id, "summary/00/000")
        self.assertEqual(entry.text, "Hello")
        self.assertEqual(entry.text_offset, 0x6A)
        self.assertEqual(entry.allocated_length, 6)
        self.assertEqual(entry.terminator, "nul")


if __name__ == "__main__":
    unittest.main()
