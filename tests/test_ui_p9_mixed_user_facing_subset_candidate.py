import json
import unittest
from pathlib import Path

from tools.srwz.ui_embedded_candidate import build_ui_embedded_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-writeback/ui-p9-mixed-user-facing-subset-slps.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p9-mixed-user-facing-subset-validation.json"
)


class UiP9MixedUserFacingSubsetCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

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

    def test_nine_player_facing_entries_are_selected_exactly(self):
        subsets = self.config["scene_map"]["selected_entry_subsets"]
        selected = {
            entry_id
            for subset in subsets.values()
            for entry_id in subset["entry_ids"]
        }
        self.assertEqual(
            selected,
            {
                "menu/SLPS/00/0084",
                "menu/SLPS/00/0085",
                "menu/SLPS/00/0086",
                "menu/SLPS/00/0091",
                "menu/SLPS/00/0092",
                "menu/SLPS/00/0247",
                "menu/SLPS/00/0251",
                "menu/SLPS/00/0252",
                "menu/SLPS/00/0253",
            },
        )
        self.assertEqual(self.manifest["selection"]["entry_count"], 9)
        self.assertEqual(
            self.manifest["selection"]["entry_subset_scene_count"],
            2,
        )
        self.assertEqual(
            set(self.manifest["selection"]["runtime_scene_ids"]),
            {
                "preparation/reboard-status-visible-subset",
                "information/pilot-ability-visible-subset",
            },
        )

    def test_thirteen_internal_or_unproven_entries_remain_excluded(self):
        selected = {
            entry_id
            for subset in self.config["scene_map"][
                "selected_entry_subsets"
            ].values()
            for entry_id in subset["entry_ids"]
        }
        source_group_entries = {
            *(
                f"menu/SLPS/00/{index:04d}"
                for index in range(83, 93)
            ),
            *(
                f"menu/SLPS/00/{index:04d}"
                for index in range(247, 254)
            ),
            "menu/SLPS/00/0112",
            *(
                f"menu/SLPS/00/{index:04d}"
                for index in range(342, 346)
            ),
        }
        self.assertEqual(
            source_group_entries - selected,
            {
                "menu/SLPS/00/0083",
                "menu/SLPS/00/0087",
                "menu/SLPS/00/0088",
                "menu/SLPS/00/0089",
                "menu/SLPS/00/0090",
                "menu/SLPS/00/0112",
                "menu/SLPS/00/0248",
                "menu/SLPS/00/0249",
                "menu/SLPS/00/0250",
                "menu/SLPS/00/0342",
                "menu/SLPS/00/0343",
                "menu/SLPS/00/0344",
                "menu/SLPS/00/0345",
            },
        )
        self.assertEqual(len(source_group_entries - selected), 13)

    def test_write_is_bounded_and_font_members_are_unchanged(self):
        self.assertEqual(
            self.manifest["selection"]["selected_write_entry_count"],
            9,
        )
        self.assertEqual(
            self.manifest["selection"]["selected_write_target_count"],
            34,
        )
        self.assertEqual(
            self.manifest["slice"]["component"]["changed_byte_count"],
            174,
        )
        self.assertEqual(
            self.manifest["slice"]["component"][
                "difference_range_count"
            ],
            36,
        )
        self.assertEqual(
            self.manifest["composition"]["overlap_byte_count"],
            0,
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))
        self.assertEqual(
            self.manifest["outputs"]["vt1"]["sha256"],
            "1424eb1626b624eb637130e08a11c320e5fb39ebf40077e91cbbfe6875839fbf",
        )


if __name__ == "__main__":
    unittest.main()
