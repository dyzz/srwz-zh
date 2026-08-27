from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

from tools.srwz.intermission_library_alignment import (
    apply_intermission_library_alignment,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class IntermissionLibraryAlignmentTest(unittest.TestCase):
    def test_robot_encyclopedia_uses_character_encyclopedia_x(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        contract = config["remaining_ui"]["intermission_library_alignment"]
        robot = contract["entries"][0]
        character = contract["entries"][1]
        self.assertEqual(robot["surface"], "robot_encyclopedia")
        self.assertEqual(robot["replacement_x"], -100)
        self.assertEqual(robot["replacement_x"], character["original_x"])

        slps = bytearray(0x347400)
        table_offset = int(contract["position_table_file_offset"], 0)
        for index, entry in enumerate(contract["entries"]):
            struct.pack_into(
                "<IhH",
                slps,
                table_offset + index * contract["entry_stride"],
                int(entry["pointer_virtual_address"], 0),
                entry["original_x"],
                0,
            )
        output, report = apply_intermission_library_alignment(
            bytes(slps), contract
        )
        self.assertEqual(struct.unpack_from("<h", output, 0x332414)[0], -100)
        self.assertEqual(report["changed_byte_count"], 1)
        self.assertTrue(report["sibling_rows_preserved"])
        self.assertTrue(report["pointer_table_preserved"])


if __name__ == "__main__":
    unittest.main()
