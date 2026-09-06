from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.bazaar_top_help_alignment import (
    BazaarTopHelpAlignmentError,
    apply_bazaar_top_help_alignment,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BazaarTopHelpAlignmentTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        self.contract = config["remaining_ui"]["bazaar_top_help_alignment"]

    def test_purchase_help_columns_move_twelve_pixels_left(self) -> None:
        slps = bytearray(0xD0600)
        for patch in self.contract["patches"]:
            offset = int(patch["instruction_file_offset"], 0)
            slps[offset : offset + 4] = bytes.fromhex(
                patch["original_instruction_hex"]
            )

        output, report = apply_bazaar_top_help_alignment(
            bytes(slps), self.contract
        )

        self.assertEqual(report["shift_pixels"], -12)
        self.assertEqual(report["confirm_replacement_x"], -251)
        self.assertEqual(report["secondary_replacement_x"], -166)
        self.assertEqual(report["site_count"], 4)
        self.assertEqual(report["changed_byte_count"], 4)
        self.assertTrue(report["text_bytes_untouched"])
        self.assertTrue(
            all(
                patch["text"].startswith("　")
                and not patch["text"].startswith("　　")
                and "：" not in patch["text"]
                for patch in report["patches"]
            )
        )
        for patch in self.contract["patches"]:
            offset = int(patch["instruction_file_offset"], 0)
            self.assertEqual(
                output[offset : offset + 4],
                bytes.fromhex(patch["replacement_instruction_hex"]),
            )

    def test_translated_help_hides_colons_with_fullwidth_spaces(self) -> None:
        translations = json.loads(
            (
                PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
            ).read_text(encoding="utf-8")
        )["slps_context_ui_by_offset"]

        for patch in self.contract["patches"]:
            text = translations[patch["source_string_file_offset"]]
            self.assertEqual(text, patch["text"])
            self.assertTrue(text.startswith("　"))
            self.assertNotIn("：", text)

    def test_rejects_coordinate_preimage_drift(self) -> None:
        slps = bytearray(0xD0600)
        for patch in self.contract["patches"]:
            offset = int(patch["instruction_file_offset"], 0)
            slps[offset : offset + 4] = bytes.fromhex(
                patch["original_instruction_hex"]
            )
        first_offset = int(
            self.contract["patches"][0]["instruction_file_offset"], 0
        )
        slps[first_offset] ^= 0x01

        with self.assertRaisesRegex(
            BazaarTopHelpAlignmentError, "coordinate preimage drift"
        ):
            apply_bazaar_top_help_alignment(bytes(slps), self.contract)


if __name__ == "__main__":
    unittest.main()
