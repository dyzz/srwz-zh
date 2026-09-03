from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.game_mode_unlock import (
    GameModeUnlockError,
    apply_postgame_mode_unlock,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GameModeUnlockTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        self.contract = config["postgame_mode_unlock"]
        last_offset = max(
            max(
                int(site["file_offset"], 0) + 4
                for site in self.contract["patches"]
            ),
            max(
                int(site["file_offset"], 0) + 4
                for site in self.contract["runtime_color_patches"]
            ),
            max(
                int(site["record_file_offset"], 0) + 8
                for site in self.contract["text_layout_patches"]
            ),
        )
        executable = bytearray(last_offset + 16)
        for site in self.contract["patches"]:
            offset = int(site["file_offset"], 0)
            executable[offset : offset + 4] = bytes.fromhex(
                site["original_instruction_hex"]
            )
        for site in self.contract["runtime_color_patches"]:
            offset = int(site["file_offset"], 0)
            executable[offset : offset + 4] = bytes.fromhex(
                site["original_instruction_hex"]
            )
        for site in self.contract["text_layout_patches"]:
            offset = int(site["record_file_offset"], 0)
            executable[offset : offset + 4] = int(
                site["text_virtual_address"], 0
            ).to_bytes(4, "little")
            executable[offset + 4 : offset + 6] = int(site["original_x"]).to_bytes(
                2, "little", signed=True
            )
            executable[offset + 6 : offset + 8] = int(site["y"]).to_bytes(
                2, "little", signed=True
            )
        self.executable = bytes(executable)

    def test_all_sp_surfaces_are_unlocked_without_save_writeback(self) -> None:
        output, report = apply_postgame_mode_unlock(
            self.executable,
            self.contract,
        )
        changed_offsets = [
            offset
            for offset, (before, after) in enumerate(zip(self.executable, output))
            if before != after
        ]
        self.assertEqual(
            changed_offsets,
            [
                0xA507C,
                0xA5084,
                0xA5088,
                0xA5090,
                0xA5094,
                0xA5098,
                0xA50A0,
                0xA50A4,
                0xA50AC,
                0xA50BC,
                0xA50C4,
                0xA50C8,
                0xA50CC,
                0xA50D0,
                0xA50D4,
                0xA50E0,
                0xA50E4,
                0xA50EC,
                0xA5102,
                0xA512C,
                0xA5138,
                0xA5162,
                0xA5184,
                0xA5194,
                0xA52D2,
                0xA5356,
                0xA53DA,
                0xA55F6,
                0x31964C,
                0x31964D,
                0x319654,
                0x319694,
                0x31969C,
            ],
        )
        self.assertEqual(report["menu_modes"], ["NORMAL", "EX-HARD", "SP"])
        self.assertTrue(report["ex_row_retail_selectable"])
        self.assertTrue(report["sp_dual_route_gate_removed"])
        self.assertEqual(report["site_count"], 6)
        self.assertEqual(report["runtime_color_patch_count"], 23)
        self.assertEqual(report["text_layout_patch_count"], 4)
        self.assertEqual(report["changed_instruction_count"], 6)
        self.assertEqual(report["changed_runtime_color_instruction_count"], 22)
        self.assertEqual(report["changed_text_layout_count"], 4)
        self.assertEqual(report["changed_byte_count"], 33)
        self.assertTrue(report["all_instruction_replacements_exact"])
        self.assertTrue(report["all_runtime_color_retargets_exact"])
        self.assertTrue(report["localized_color_parameter_writes_retargeted"])
        self.assertEqual(report["selected_ex_special_color"], "0x01")
        self.assertEqual(report["selected_sp_special_color"], "0x04")
        self.assertTrue(report["all_text_layout_replacements_exact"])
        self.assertTrue(report["text_descriptor_y_preserved"])
        self.assertTrue(report["save_flag_reads_bypassed"])
        self.assertTrue(report["save_writeback_functions_unchanged"])
        self.assertTrue(report["executable_size_preserved"])

        reread, reread_report = apply_postgame_mode_unlock(output, self.contract)
        self.assertEqual(reread, output)
        self.assertEqual(reread_report["changed_instruction_count"], 0)
        self.assertEqual(
            reread_report["changed_runtime_color_instruction_count"], 0
        )
        self.assertEqual(reread_report["changed_text_layout_count"], 0)
        self.assertEqual(reread_report["changed_byte_count"], 0)

    def test_instruction_preimage_drift_is_rejected(self) -> None:
        damaged = bytearray(self.executable)
        damaged[0xA5354] ^= 1
        with self.assertRaises(GameModeUnlockError):
            apply_postgame_mode_unlock(bytes(damaged), self.contract)

    def test_branch_target_drift_is_rejected(self) -> None:
        contract = json.loads(json.dumps(self.contract))
        contract["patches"][0]["replacement_instruction_hex"] = "06000010"
        with self.assertRaises(GameModeUnlockError):
            apply_postgame_mode_unlock(self.executable, contract)

    def test_runtime_color_preimage_drift_is_rejected(self) -> None:
        damaged = bytearray(self.executable)
        damaged[0xA5120] ^= 1
        with self.assertRaises(GameModeUnlockError):
            apply_postgame_mode_unlock(bytes(damaged), self.contract)

    def test_runtime_color_opcode_drift_is_rejected(self) -> None:
        contract = json.loads(json.dumps(self.contract))
        contract["runtime_color_patches"][0]["replacement_instruction_hex"] = (
            "430080A4"
        )
        with self.assertRaises(GameModeUnlockError):
            apply_postgame_mode_unlock(self.executable, contract)

    def test_text_record_drift_is_rejected(self) -> None:
        damaged = bytearray(self.executable)
        damaged[0x319648] ^= 1
        with self.assertRaises(GameModeUnlockError):
            apply_postgame_mode_unlock(bytes(damaged), self.contract)


if __name__ == "__main__":
    unittest.main()
