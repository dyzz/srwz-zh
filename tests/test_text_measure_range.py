from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.srwz.text_measure_range import (
    TextMeasureRangeError,
    apply_text_measurement_range_patch,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TextMeasureRangeTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(encoding="utf-8")
        )
        self.contract = config["text_measurement_range"]
        last_offset = max(int(site["file_offset"], 0) + 8 for site in self.contract["patches"])
        executable = bytearray(last_offset + 16)
        for site in self.contract["patches"]:
            offset = int(site["file_offset"], 0)
            executable[offset : offset + 4] = bytes.fromhex(site["original_instruction_hex"])
            executable[offset + 4 : offset + 8] = bytes.fromhex(site["following_instruction_hex"])
        self.executable = bytes(executable)

    def test_contract_matches_the_stock_executable_sites(self) -> None:
        # Both immediates are `ori at, zero, 0x889F` followed by the compare
        # against `at`; the replacement only lowers the immediate to 0x829F.
        self.assertEqual(self.contract["original_upper_bound"], "0x889F")
        self.assertEqual(self.contract["replacement_upper_bound"], "0x829F")
        self.assertEqual(self.contract["renderer_upper_bound"], "0x829E")
        self.assertEqual(
            {site["virtual_address"] for site in self.contract["patches"]},
            {"0x139CC0", "0x2617EC"},
        )
        for site in self.contract["patches"]:
            self.assertEqual(site["original_instruction_hex"], "9F880134")
            self.assertEqual(site["replacement_instruction_hex"], "9F820134")
        original_elf = PROJECT_ROOT / "work/disc/SLPS_258.87"
        if original_elf.is_file():
            data = original_elf.read_bytes()
            for site in self.contract["patches"]:
                offset = int(site["file_offset"], 0)
                self.assertEqual(data[offset : offset + 4].hex().upper(), "9F880134", site["id"])
                self.assertEqual(
                    data[offset + 4 : offset + 8].hex().upper(),
                    site["following_instruction_hex"],
                    site["id"],
                )

    def test_patch_rewrites_only_the_two_immediates_and_is_idempotent(self) -> None:
        output, report = apply_text_measurement_range_patch(self.executable, self.contract)
        self.assertEqual(len(output), len(self.executable))
        changed = [
            offset
            for offset in range(0, len(output), 4)
            if output[offset : offset + 4] != self.executable[offset : offset + 4]
        ]
        self.assertEqual(
            sorted(changed),
            sorted(int(site["file_offset"], 0) for site in self.contract["patches"]),
        )
        for site in self.contract["patches"]:
            offset = int(site["file_offset"], 0)
            self.assertEqual(output[offset : offset + 4].hex().upper(), "9F820134")
        self.assertEqual(report["changed_site_count"], 2)
        again, report_again = apply_text_measurement_range_patch(output, self.contract)
        self.assertEqual(again, output)
        self.assertEqual(report_again["changed_site_count"], 0)
        self.assertTrue(all(site["already_patched"] for site in report_again["patches"]))

    def test_preimage_and_contract_drift_fail_closed(self) -> None:
        corrupt = bytearray(self.executable)
        first = int(self.contract["patches"][0]["file_offset"], 0)
        corrupt[first + 5] ^= 1
        with self.assertRaisesRegex(TextMeasureRangeError, "preimage"):
            apply_text_measurement_range_patch(bytes(corrupt), self.contract)
        wrong_bound = copy.deepcopy(self.contract)
        wrong_bound["replacement_upper_bound"] = "0x829E"
        with self.assertRaisesRegex(TextMeasureRangeError, "renderer"):
            apply_text_measurement_range_patch(self.executable, wrong_bound)
        wrong_word = copy.deepcopy(self.contract)
        wrong_word["patches"][0]["replacement_instruction_hex"] = "9F830134"
        with self.assertRaisesRegex(TextMeasureRangeError, "immediate drift"):
            apply_text_measurement_range_patch(self.executable, wrong_word)
        not_ori = copy.deepcopy(self.contract)
        not_ori["patches"][0]["replacement_instruction_hex"] = "9F820135"
        with self.assertRaisesRegex(TextMeasureRangeError, "ori at, zero"):
            apply_text_measurement_range_patch(self.executable, not_ori)

    def test_best_edition_contract_declares_both_sites(self) -> None:
        layout = json.loads(
            (PROJECT_ROOT / "config/editions/best/source-layout.json").read_text(encoding="utf-8")
        )
        spans = {tuple(span) for span in layout["elf_spans"]}
        guards = {
            (row["original_offset"], row["best_offset"], row["original"], row["best"])
            for row in layout["elf_instructions"]
        }
        expected = {
            (0x3B740, 0x3B744, 0x3B740),
            (0x16326C, 0x163270, 0x16362C),
        }
        self.assertTrue(expected <= spans, expected - spans)
        for original_offset, _end, best_offset in expected:
            self.assertIn((original_offset, best_offset, "9f880134", "9f880134"), guards)
        best_elf = PROJECT_ROOT / "work/analysis/v040-best-chart-20260909/best/SLPS_732.70"
        if best_elf.is_file():
            data = best_elf.read_bytes()
            for _o, _e, best_offset in expected:
                self.assertEqual(data[best_offset : best_offset + 4].hex(), "9f880134")


if __name__ == "__main__":
    unittest.main()
