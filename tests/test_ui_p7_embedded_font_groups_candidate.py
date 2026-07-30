import json
import unittest
from pathlib import Path

from tools.srwz.ui_embedded_candidate import build_ui_embedded_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-writeback/ui-p7-embedded-font-groups-slps.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p7-embedded-font-groups-validation.json"
)


class UiP7EmbeddedFontGroupsCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_rebuild_manifest_and_four_outputs_are_exact(self):
        payloads, report = build_ui_embedded_candidate(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        self.assertEqual(report, self.manifest)
        output_names = {
            "SLPS_258.87": "slps",
            "DATA/VT1.BIN": "vt1",
            "DATA/COMPDATA.BN": "compdata",
            "DATA/MTV_PROS.BIN": "mtv_pros",
        }
        self.assertEqual(set(payloads), set(output_names))
        for member, payload in payloads.items():
            path = (
                PROJECT_ROOT
                / report["outputs"][output_names[member]]["path"]
            )
            self.assertEqual(path.read_bytes(), payload)

    def test_five_groups_cover_all_ninety_three_entries(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["scene_count"], 5)
        self.assertEqual(selection["entry_count"], 93)
        self.assertEqual(selection["no_op_entry_count"], 20)
        self.assertEqual(selection["selected_write_entry_count"], 73)
        self.assertEqual(selection["selected_write_target_count"], 86)
        self.assertEqual(selection["excluded_entry_count"], 0)
        self.assertEqual(
            {
                scene["scene_id"]: scene["entry_count"]
                for scene in selection["scenes"]
            },
            {
                "options/bgm-controller-and-map-settings": 29,
                "results/settlement-and-support-setup": 5,
                "formation/list-search-and-priority": 33,
                "upgrade/full-upgrade-reward": 17,
                "archive/scenario-progress-and-route-headings": 9,
            },
        )

    def test_font_chunk_is_rebased_without_changing_other_vt1_chunks(self):
        font = self.manifest["composition"]["font_extension"]
        self.assertEqual(font["font_chunk_index"], 2)
        self.assertEqual(font["vt1_chunk_count"], 14)
        self.assertEqual(font["unchanged_vt1_chunk_count"], 13)
        self.assertEqual(font["font_and_slice_overlap_byte_count"], 0)
        self.assertEqual(
            self.manifest["composition"]["overlap_byte_count"],
            0,
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_runtime_boundary_lists_all_five_native_routes(self):
        self.assertEqual(
            self.manifest["status"],
            (
                "integrated_ui_p7_embedded_font_groups_component_"
                "validated_iso_runtime_pending"
            ),
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            len(self.manifest["runtime"]["required_routes"]),
            5,
        )


if __name__ == "__main__":
    unittest.main()
