import unittest
from pathlib import Path

from tools.srwz.codec import encode
from tools.srwz.terrain_names import inventory_terrain_names
from tools.srwz.text import encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_TABLE = (
    PROJECT_ROOT / "vendor" / "upstream-python" / "project" / "tbl_all.json"
)


class TerrainNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_text_table(TEXT_TABLE)

    def test_inventories_records_from_frame_anchor(self):
        decoded = bytearray(0x120)
        record_start = 0x40
        for index, name in enumerate(("海", "森")):
            offset = record_start + index * 0x1C
            payload = encode_text(name, self.table, terminate=True)
            decoded[offset : offset + len(payload)] = payload
        frame = record_start + 2 * 0x1C + 0x1C
        decoded[frame : frame + 6] = b"Frame\0"
        stored = encode(bytes(decoded))

        rows = inventory_terrain_names(
            stored,
            (0, len(stored)),
            self.table,
            first_member=0,
            last_member=0,
        )

        self.assertEqual(
            rows,
            (
                {
                    "member": 0,
                    "decoded_offset": 0x40,
                    "source": "海",
                    "source_consumed": 3,
                },
                {
                    "member": 0,
                    "decoded_offset": 0x5C,
                    "source": "森",
                    "source_consumed": 3,
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
