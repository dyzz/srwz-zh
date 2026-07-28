import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-writeback/ui-p0-compdata-fixed.json"
COMPONENT_PATH = (
    PROJECT_ROOT / "work/build/ui-p0-fixed-compdata/components/DATA/COMPDATA.BN"
)
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p0-fixed-compdata-validation.json"


class UiP0FixedCompdataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_fixed_coverage_matches_ratchet(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["p0_entry_count"], 44)
        self.assertEqual(selection["no_op_entry_count"], 3)
        self.assertEqual(selection["selected_write_entry_count"], 41)
        self.assertEqual(selection["selected_write_target_count"], 41)
        self.assertEqual(selection["fixed_covered_entry_count"], 44)
        self.assertEqual(selection["excluded_reason_counts"], {})
        self.assertTrue(self.manifest["ratchet"]["passed"])
        self.assertEqual(
            self.manifest["ratchet"]["expected"],
            self.config["ratchet"],
        )

    def test_writer_preserves_pointer_and_non_target_bytes(self):
        write = self.manifest["write"]
        self.assertEqual(write["pointer_write_count"], 0)
        self.assertGreater(write["pointer_site_byte_count"], 0)
        self.assertTrue(write["pointer_bytes_unchanged"])
        self.assertTrue(write["non_target_bytes_unchanged"])
        self.assertTrue(write["target_reparse_exact"])

    def test_compressed_component_matches_manifest_and_round_trips(self):
        component = COMPONENT_PATH.read_bytes()
        compressed = self.manifest["compressed_component"]
        self.assertEqual(len(component), compressed["output_size"])
        self.assertEqual(
            hashlib.sha256(component).hexdigest(),
            compressed["output_sha256"],
        )
        decoded = decode(component)
        self.assertEqual(decoded.consumed, len(component))
        self.assertEqual(
            hashlib.sha256(decoded.output).hexdigest(),
            self.manifest["decoded_component"]["output_sha256"],
        )
        self.assertTrue(compressed["decoded_round_trip_exact"])
        self.assertTrue(compressed["flags_preserved"])

    def test_no_p0_compdata_text_requires_a_pool(self):
        remaining = self.manifest["remaining_work"]
        excluded = self.manifest["excluded"]
        self.assertEqual(remaining["growing_compdata_entry_count"], 0)
        self.assertEqual(excluded, [])
        self.assertEqual(
            set(remaining["requires_registered_pool_or_other_allocation"]),
            {item["entry_id"] for item in excluded},
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")


if __name__ == "__main__":
    unittest.main()
