import json
import unittest
from pathlib import Path

from tools.srwz.ui_embedded_candidate import build_ui_embedded_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT / "config/ui-writeback/ui-p5-battle-menus-slps.json"
)
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p5-battle-menus-validation.json"


class UiP5BattleMenusCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_rebuild_manifest_and_four_outputs_are_exact(self):
        payloads, report = build_ui_embedded_candidate(PROJECT_ROOT, CONFIG_PATH)
        self.assertEqual(report, self.manifest)
        output_names = {
            "SLPS_258.87": "slps",
            "DATA/VT1.BIN": "vt1",
            "DATA/COMPDATA.BN": "compdata",
            "DATA/MTV_PROS.BIN": "mtv_pros",
        }
        self.assertEqual(set(payloads), set(output_names))
        for member, payload in payloads.items():
            path = PROJECT_ROOT / report["outputs"][output_names[member]]["path"]
            self.assertEqual(path.read_bytes(), payload)

    def test_selection_and_layered_composition_are_exact(self):
        selection = self.manifest["selection"]
        composition = self.manifest["composition"]
        self.assertEqual(
            {
                scene["scene_id"]: scene["entry_count"]
                for scene in selection["scenes"]
            },
            {
                "battle/end-phase-map-command-tail": 6,
                "battle/action-restriction-messages": 10,
                "system/quick-command-save-and-cancel-confirmations": 5,
                "battle/repair-resupply-spirit-targeting": 17,
            },
        )
        self.assertEqual(selection["entry_count"], 38)
        self.assertEqual(selection["no_op_entry_count"], 5)
        self.assertEqual(selection["selected_write_entry_count"], 33)
        self.assertEqual(selection["selected_write_target_count"], 37)
        self.assertEqual(composition["slice_changed_byte_count"], 1024)
        self.assertEqual(
            self.manifest["slice"]["component"]["difference_range_count"],
            60,
        )
        self.assertEqual(composition["overlap_byte_count"], 0)
        self.assertTrue(composition["base_preimage_exact_at_slice_offsets"])
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_only_slps_differs_from_the_p4_core(self):
        outputs = self.manifest["outputs"]
        base = self.manifest["inputs"]["base_ui_core"]["outputs"]
        self.assertEqual(
            outputs["slps"]["sha256"],
            "473b5f5fee31d78aacbe5e6f78db1c9207a52f33ff50ef65a846e880b080d16d",
        )
        self.assertNotEqual(outputs["slps"]["sha256"], base["slps"]["sha256"])
        for name in ("vt1", "compdata", "mtv_pros"):
            self.assertEqual(outputs[name]["sha256"], base[name]["sha256"])
            self.assertEqual(outputs[name]["size"], base[name]["size"])

    def test_runtime_boundary_requires_native_first_battle_card(self):
        self.assertEqual(
            self.manifest["status"],
            "integrated_ui_p5_battle_menus_component_validated_iso_runtime_pending",
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertIn(
            "native_first_battle_memory_card",
            self.manifest["runtime"]["pending_gates"],
        )


if __name__ == "__main__":
    unittest.main()
