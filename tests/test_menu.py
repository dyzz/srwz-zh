import struct
import unittest
from pathlib import Path

from tools.srwz.menu import parse_menu_file
from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_TABLE = (
    PROJECT_ROOT / "vendor" / "upstream-python" / "project" / "tbl_all.json"
)


class MenuParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_text_table(TEXT_TABLE)

    def test_merges_regular_and_embedded_pointers_for_same_text(self):
        data = bytearray(0x80)
        struct.pack_into("<I", data, 0x10, 0x30)
        struct.pack_into("<H", data, 0x04, 0)
        struct.pack_into("<h", data, 0x08, 0x30)
        data[0x30:0x36] = b"Hello\x00"
        descriptor = {
            "friendly_name": "Fixture",
            "base_offset": 0,
            "embedded": {
                "Main": [{"HI": [0x04], "LO": [0x08]}],
            },
            "sections": [
                {
                    "name": "Main",
                    "pointers": [
                        {
                            "pointers_start": "0x10",
                            "pointers_end": "0x14",
                            "style": "P",
                        }
                    ],
                }
            ],
        }

        result = parse_menu_file(bytes(data), descriptor, self.table)

        self.assertEqual(result.section_names, ("Main",))
        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.entry_id, "menu/Fixture/00/0000")
        self.assertEqual(entry.text, "Hello")
        self.assertEqual(entry.pointer_offsets, (0x10,))
        self.assertEqual(entry.target_offsets, (0x30,))
        self.assertEqual(entry.embedded_hi, (0x04,))
        self.assertEqual(entry.embedded_lo, (0x08,))

    def test_pointer_style_skips_interleaved_fields(self):
        data = bytearray(0x80)
        struct.pack_into("<I", data, 0x10, 0x40)
        struct.pack_into("<I", data, 0x18, 0x50)
        data[0x40:0x42] = b"A\x00"
        data[0x50:0x52] = b"B\x00"
        descriptor = {
            "friendly_name": "Fixture",
            "base_offset": 0,
            "sections": [
                {
                    "name": "Main",
                    "pointers": [
                        {
                            "pointers_start": "0x10",
                            "pointers_end": "0x1C",
                            "style": "P4P",
                        }
                    ],
                }
            ],
        }

        result = parse_menu_file(bytes(data), descriptor, self.table)

        self.assertEqual(
            [(entry.text, entry.pointer_offsets) for entry in result.entries],
            [("A", (0x10,)), ("B", (0x18,))],
        )


if __name__ == "__main__":
    unittest.main()
