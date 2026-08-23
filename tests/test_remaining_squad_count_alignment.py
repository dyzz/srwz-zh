import json
import unittest
from pathlib import Path

from tools.srwz.remaining_squad_count_alignment import (
    RemainingSquadCountAlignmentError,
    apply_remaining_squad_count_alignment,
)
from tools.srwz.text import decode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/full-story-components.json"
REMAINING_UI = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
SOURCE_SLPS = PROJECT_ROOT / "work/disc/SLPS_258.87"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"


class RemainingSquadCountAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.contract = config["remaining_ui"][
            "remaining_squad_count_alignment"
        ]
        cls.remaining = json.loads(REMAINING_UI.read_text(encoding="utf-8"))[
            "slps_context_ui_by_offset"
        ]
        cls.source = SOURCE_SLPS.read_bytes()
        cls.table = load_text_table(TEXT_TABLE)

    def test_contract_binds_all_three_independent_draw_fields(self):
        self.assertEqual(self.contract["prefix"]["text"], "（剩余")
        self.assertEqual(self.contract["number"]["text"], "%<width:64>")
        self.assertEqual(self.contract["suffix"]["text"], "个小队）")
        self.assertEqual(
            (
                self.contract["prefix"]["original_x"],
                self.contract["number"]["original_x"],
                self.contract["suffix"]["original_x"],
            ),
            (460, 506, 552),
        )
        self.assertEqual(self.contract["replacement_number_x"], 514)
        self.assertEqual(self.remaining["0x33FC68"], "（剩余")
        self.assertEqual(self.remaining["0x33FC70"], "个小队）")
        self.assertEqual(self.remaining["0x33FC80"], "%<width:64>")
        self.assertEqual(
            decode_text(self.source, 0x33FC80, self.table).text,
            "%<width:64>隊",
        )

    def test_apply_moves_only_number_coordinate_and_is_idempotent(self):
        output, report = apply_remaining_squad_count_alignment(
            self.source, self.contract
        )
        number_offset = int(
            self.contract["number"]["instruction_file_offset"], 0
        )
        prefix_offset = int(
            self.contract["prefix"]["instruction_file_offset"], 0
        )
        suffix_offset = int(
            self.contract["suffix"]["instruction_file_offset"], 0
        )
        self.assertEqual(
            output[number_offset : number_offset + 4],
            bytes.fromhex("02020624"),
        )
        self.assertEqual(
            output[prefix_offset : prefix_offset + 4],
            self.source[prefix_offset : prefix_offset + 4],
        )
        self.assertEqual(
            output[suffix_offset : suffix_offset + 4],
            self.source[suffix_offset : suffix_offset + 4],
        )
        self.assertEqual(report["shift_pixels"], 8)
        self.assertEqual(report["changed_byte_count"], 2)
        self.assertTrue(report["adjacent_coordinates_preserved"])
        self.assertTrue(report["format_token_untouched"])
        self.assertTrue(report["instruction_replacement_exact"])
        self.assertTrue(report["executable_size_preserved"])

        repeated, repeated_report = apply_remaining_squad_count_alignment(
            output, self.contract
        )
        self.assertEqual(repeated, output)
        self.assertTrue(repeated_report["already_patched"])
        self.assertEqual(repeated_report["changed_byte_count"], 0)

    def test_unknown_number_coordinate_preimage_is_rejected(self):
        changed = bytearray(self.source)
        number_offset = int(
            self.contract["number"]["instruction_file_offset"], 0
        )
        changed[number_offset] ^= 0xFF
        with self.assertRaisesRegex(
            RemainingSquadCountAlignmentError, "preimage drift"
        ):
            apply_remaining_squad_count_alignment(
                bytes(changed), self.contract
            )


if __name__ == "__main__":
    unittest.main()
