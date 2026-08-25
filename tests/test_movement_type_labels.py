from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.movement_type_labels import (
    MovementTypeLabelError,
    apply_runtime_movement_type_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MovementTypeLabelTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        self.contract = config["runtime_movement_type_labels"]
        parallel = self.contract["preserved_parallel_type"]
        last_offset = max(
            [int(site["file_offset"], 0) + 32 for site in self.contract["sites"]]
            + [int(parallel["file_offset"], 0) + 7]
        )
        executable = bytearray(last_offset + 16)
        for site in self.contract["sites"]:
            offset = int(site["file_offset"], 0)
            executable[offset : offset + 32] = bytes.fromhex(
                site["original_block_hex"]
            )
        parallel_offset = int(parallel["file_offset"], 0)
        executable[parallel_offset : parallel_offset + 7] = bytes.fromhex(
            parallel["encoded_hex"]
        )
        self.executable = bytes(executable)

    def test_runtime_materialized_air_and_land_labels_are_simplified(self) -> None:
        output, report = apply_runtime_movement_type_labels(
            self.executable, self.contract
        )
        changed_offsets = [
            offset
            for offset, (before, after) in enumerate(zip(self.executable, output))
            if before != after
        ]
        self.assertEqual(changed_offsets, [0x28AE81, 0x28AEA1])
        self.assertEqual(report["site_count"], 2)
        self.assertEqual(report["changed_byte_count"], 2)
        self.assertEqual(
            [site["translation"] for site in report["sites"]],
            ["空专用", "陆专用"],
        )
        self.assertTrue(
            report["preserved_parallel_type"]["preserved_byte_exact"]
        )

        reread, reread_report = apply_runtime_movement_type_labels(
            output, self.contract
        )
        self.assertEqual(reread, output)
        self.assertEqual(reread_report["changed_byte_count"], 0)

    def test_runtime_materialization_sequence_drift_is_rejected(self) -> None:
        damaged = bytearray(self.executable)
        damaged[0x28AE88] ^= 1
        with self.assertRaises(MovementTypeLabelError):
            apply_runtime_movement_type_labels(bytes(damaged), self.contract)


if __name__ == "__main__":
    unittest.main()
