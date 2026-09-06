from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.command_status_label_alignment import (
    CommandStatusLabelAlignmentError,
    apply_command_status_label_alignment,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CommandStatusLabelAlignmentTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        self.contract = config["remaining_ui"][
            "command_status_label_alignment"
        ]

    def _slps_with_instruction(self, key: str) -> bytes:
        patch = self.contract["patch"]
        offset = int(patch["instruction_file_offset"], 0)
        slps = bytearray(offset + 4)
        slps[offset : offset + 4] = bytes.fromhex(patch[key])
        return bytes(slps)

    def test_sr_points_label_moves_eight_pixels_right(self) -> None:
        output, report = apply_command_status_label_alignment(
            self._slps_with_instruction("original_instruction_hex"),
            self.contract,
        )
        patch = self.contract["patch"]
        offset = int(patch["instruction_file_offset"], 0)

        self.assertEqual(report["shift_pixels"], 8)
        self.assertEqual(report["original_x"], -20)
        self.assertEqual(report["replacement_x"], -12)
        self.assertEqual(report["changed_byte_count"], 1)
        self.assertTrue(report["text_bytes_untouched"])
        self.assertTrue(report["turn_count_coordinate_untouched"])
        self.assertEqual(
            output[offset : offset + 4],
            bytes.fromhex(patch["replacement_instruction_hex"]),
        )

    def test_patched_preimage_is_idempotent(self) -> None:
        output, report = apply_command_status_label_alignment(
            self._slps_with_instruction("replacement_instruction_hex"),
            self.contract,
        )
        patch = self.contract["patch"]
        offset = int(patch["instruction_file_offset"], 0)

        self.assertEqual(report["changed_byte_count"], 0)
        self.assertTrue(report["patch"]["already_patched"])
        self.assertEqual(
            output[offset : offset + 4],
            bytes.fromhex(patch["replacement_instruction_hex"]),
        )

    def test_rejects_coordinate_preimage_drift(self) -> None:
        slps = bytearray(
            self._slps_with_instruction("original_instruction_hex")
        )
        offset = int(self.contract["patch"]["instruction_file_offset"], 0)
        slps[offset] ^= 0x01

        with self.assertRaisesRegex(
            CommandStatusLabelAlignmentError, "coordinate preimage drift"
        ):
            apply_command_status_label_alignment(bytes(slps), self.contract)


if __name__ == "__main__":
    unittest.main()
