from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.weapon_category_labels import (
    WeaponCategoryLabelError,
    apply_runtime_weapon_category_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WeaponCategoryLabelTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        self.contract = config["runtime_weapon_category_labels"]
        last_offset = max(
            int(site["file_offset"], 0)
            + len(bytes.fromhex(site["original_block_hex"]))
            for site in self.contract["sites"]
        )
        executable = bytearray(last_offset + 16)
        for site in self.contract["sites"]:
            offset = int(site["file_offset"], 0)
            block = bytes.fromhex(site["original_block_hex"])
            executable[offset : offset + len(block)] = block
        self.executable = bytes(executable)

    def test_shared_melee_and_ranged_labels_are_simplified(self) -> None:
        output, report = apply_runtime_weapon_category_labels(
            self.executable, self.contract
        )
        changed_offsets = [
            offset
            for offset, (before, after) in enumerate(
                zip(self.executable, output)
            )
            if before != after
        ]
        self.assertEqual(
            changed_offsets,
            [0x291AF9, 0x291B50, 0x291B51],
        )
        self.assertEqual(report["site_count"], 2)
        self.assertEqual(report["changed_byte_count"], 3)
        self.assertEqual(
            [site["translation"] for site in report["sites"]],
            ["格斗武器（　　）", "射击武器（　　）"],
        )
        self.assertTrue(
            report[
                "all_matching_weapon_instances_covered_by_shared_branches"
            ]
        )
        self.assertTrue(
            all(
                site["shared_branch_applies_to_all_matching_weapons"]
                for site in report["sites"]
            )
        )

        reread, reread_report = apply_runtime_weapon_category_labels(
            output, self.contract
        )
        self.assertEqual(reread, output)
        self.assertEqual(reread_report["changed_byte_count"], 0)
        self.assertTrue(
            all(site["already_patched"] for site in reread_report["sites"])
        )

    def test_runtime_materialization_sequence_drift_is_rejected(self) -> None:
        damaged = bytearray(self.executable)
        damaged[0x291B0C] ^= 1
        with self.assertRaises(WeaponCategoryLabelError):
            apply_runtime_weapon_category_labels(
                bytes(damaged), self.contract
            )


if __name__ == "__main__":
    unittest.main()
