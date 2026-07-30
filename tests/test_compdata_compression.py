import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/compdata-compression-comparison.json"
)
COMPONENT_PATH = (
    PROJECT_ROOT
    / "work/build/compdata-step-02-p0-menu-inplace/components/DATA/COMPDATA.BN"
)
COMPONENT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/compdata-step-02-p0-menu-inplace-validation.json"
)


class CompdataCompressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparison = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.component = json.loads(
            COMPONENT_MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_original_loss_is_attributed_to_distance_seed_packing(self):
        suffix = self.comparison["changed_suffix"]
        self.assertEqual(suffix["original_stored_suffix_size"], 16209)
        self.assertEqual(
            suffix["legacy_reencoded_original_suffix_size"],
            18139,
        )
        self.assertEqual(suffix["legacy_gap_to_original"], 1930)
        self.assertEqual(
            suffix["bytes_recovered_by_compact_distance_seed"],
            1808,
        )
        self.assertLessEqual(suffix["compact_gap_to_original"], 128)

    def test_complete_p0_meets_the_71_sector_hard_gate(self):
        budget = self.comparison["p0_budget"]
        compressed = self.component["compressed_component"]
        self.assertEqual(budget["maximum_output_size"], 145408)
        self.assertEqual(budget["size_constrained_size"], 145237)
        self.assertEqual(compressed["strategy"], "maximum")
        self.assertEqual(compressed["output_size"], 145057)
        self.assertLess(
            compressed["output_size"],
            budget["size_constrained_size"],
        )
        self.assertLessEqual(compressed["output_size"], 145408)
        self.assertEqual(compressed["output_sectors"], 71)
        self.assertTrue(compressed["within_sector_budget"])
        self.assertGreater(compressed["budget_headroom"], 0)

    def test_complete_p0_stream_is_fully_consumed(self):
        raw = COMPONENT_PATH.read_bytes()
        result = decode(raw)
        self.assertEqual(result.declared_size, 524032)
        self.assertEqual(result.consumed, len(raw))
        self.assertEqual(
            self.component["selection"]["fixed_covered_entry_count"],
            44,
        )
        self.assertTrue(
            self.component["write"]["pointer_bytes_unchanged"]
        )
        self.assertTrue(
            self.component["write"]["non_target_bytes_unchanged"]
        )

    def test_every_cost_breakdown_sums_to_stream_size(self):
        for name, stream in self.comparison["streams"].items():
            with self.subTest(name=name):
                self.assertEqual(
                    sum(stream["encoded_cost_bytes"].values()),
                    stream["size"],
                )
                self.assertEqual(
                    stream["distance_seed"]["missed_compact_count"],
                    1796 if name == "p0_full_legacy" else (
                        214 if name == "p0_buttons_legacy" else 0
                    ),
                )


if __name__ == "__main__":
    unittest.main()
