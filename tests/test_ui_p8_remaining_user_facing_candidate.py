import json
import unittest
from pathlib import Path

from tools.srwz.ui_embedded_candidate import build_ui_embedded_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-writeback/ui-p8-remaining-user-facing-slps.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p8-remaining-user-facing-validation.json"
)


class UiP8RemainingUserFacingCandidateTests(unittest.TestCase):
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

    def test_four_groups_cover_all_fifty_nine_entries(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["scene_count"], 4)
        self.assertEqual(selection["entry_count"], 59)
        self.assertEqual(selection["no_op_entry_count"], 19)
        self.assertEqual(selection["selected_write_entry_count"], 40)
        self.assertEqual(selection["selected_write_target_count"], 47)
        self.assertEqual(selection["fixed_covered_entry_count"], 59)
        self.assertEqual(selection["excluded_entry_count"], 0)
        self.assertEqual(
            {
                scene["scene_id"]: scene["entry_count"]
                for scene in selection["scenes"]
            },
            {
                "formation/terrain-variant-selector": 10,
                "battle/weapon-selection-and-use-conditions": 22,
                "information/reboard-and-option-subpages": 12,
                "parts/equipment-and-predeployment-actions": 15,
            },
        )

    def test_write_is_bounded_and_font_members_are_unchanged(self):
        slice_report = self.manifest["slice"]
        self.assertEqual(
            slice_report["component"]["changed_byte_count"],
            418,
        )
        self.assertEqual(
            slice_report["component"]["difference_range_count"],
            61,
        )
        self.assertEqual(
            self.manifest["composition"]["overlap_byte_count"],
            0,
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))
        self.assertEqual(
            self.manifest["outputs"]["vt1"]["sha256"],
            "3e3d3ad784feacd8e8729c44578ccbdba14dc95311c2fee276c5c6eaf6bb4873",
        )
        self.assertEqual(
            self.manifest["outputs"]["compdata"]["sha256"],
            "bc63373dec31015a3628a8a963bc3e82258a48608042d02b1838bb5d39eec405",
        )

    def test_runtime_boundary_lists_all_four_native_routes(self):
        self.assertEqual(
            self.manifest["status"],
            (
                "integrated_ui_p8_remaining_user_facing_component_"
                "validated_iso_runtime_pending"
            ),
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            len(self.manifest["runtime"]["required_routes"]),
            4,
        )


if __name__ == "__main__":
    unittest.main()
