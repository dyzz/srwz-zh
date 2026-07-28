import hashlib
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-writeback/ui-p0-slps-fixed.json"
COMPONENT_PATH = PROJECT_ROOT / "work/build/ui-p0-fixed-slps/components/SLPS_258.87"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p0-fixed-slps-validation.json"


class UiP0FixedSlpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_fixed_span_selection_matches_ratchet(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["p0_entry_count"], 418)
        self.assertEqual(selection["no_op_entry_count"], 101)
        self.assertEqual(selection["selected_write_entry_count"], 317)
        self.assertEqual(selection["selected_write_target_count"], 378)
        self.assertEqual(selection["fixed_covered_entry_count"], 418)
        self.assertEqual(selection["excluded_entry_count"], 0)
        self.assertEqual(selection["excluded_reason_counts"], {})
        self.assertTrue(self.manifest["ratchet"]["passed"])
        self.assertEqual(
            self.manifest["ratchet"]["expected"],
            self.config["ratchet"],
        )

    def test_writer_preserves_pointers_non_targets_and_font(self):
        write = self.manifest["write"]
        component = self.manifest["component"]
        self.assertEqual(write["pointer_write_count"], 0)
        self.assertTrue(write["pointer_bytes_unchanged"])
        self.assertTrue(write["non_target_bytes_unchanged"])
        self.assertTrue(write["target_reparse_exact"])
        self.assertTrue(component["font_decoded_unchanged"])
        self.assertEqual(
            component["source_font_decoded_sha256"],
            component["output_font_decoded_sha256"],
        )

    def test_component_matches_committed_manifest(self):
        component = COMPONENT_PATH.read_bytes()
        self.assertEqual(len(component), self.manifest["component"]["size"])
        self.assertEqual(
            hashlib.sha256(component).hexdigest(),
            self.manifest["component"]["sha256"],
        )

    def test_remaining_work_is_explicit_and_runtime_is_pending(self):
        remaining = self.manifest["remaining_work"]
        excluded_ids = {item["entry_id"] for item in self.manifest["excluded"]}
        self.assertEqual(remaining["growing_slps_entry_count"], 0)
        self.assertEqual(
            remaining["out_of_scope_compdata_p0_entry_count"],
            44,
        )
        self.assertEqual(
            set(remaining["requires_registered_pool_or_other_allocation"]),
            excluded_ids,
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")


if __name__ == "__main__":
    unittest.main()
