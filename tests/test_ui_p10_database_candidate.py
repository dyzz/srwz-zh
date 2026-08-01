import json
import unittest
from pathlib import Path

from tools.srwz.ui_database_candidate import build_ui_database_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-writeback/ui-p10-database-fixed-core.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p10-database-fixed-core-validation.json"
)


class UiP10DatabaseCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_rebuild_manifest_and_four_outputs_are_exact(self):
        payloads, report = build_ui_database_candidate(
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

    def test_all_database_and_unit_names_are_fixed_span_and_reread(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["entry_count"], 1113)
        self.assertEqual(selection["slps_entry_count"], 233)
        self.assertEqual(selection["compdata_entry_count"], 880)
        self.assertEqual(
            self.manifest["ratchet"]["actual"][
                "fixed_covered_entry_count"
            ],
            1113,
        )
        self.assertEqual(
            self.manifest["ratchet"]["actual"][
                "font_semantic_replacement_count"
            ],
            4,
        )
        self.assertEqual(
            self.manifest["ratchet"]["actual"][
                "first_five_stage_title_count"
            ],
            5,
        )
        self.assertEqual(
            self.manifest["ratchet"]["actual"][
                "opening_profile_entry_count"
            ],
            4,
        )
        unit_names = self.manifest["fixed_span"]["unit_names"]
        self.assertEqual(unit_names["entry_count"], 348)
        self.assertEqual(unit_names["write_entry_count"], 305)
        self.assertEqual(unit_names["no_op_entry_count"], 43)
        self.assertEqual(unit_names["pointer_count"], 808)
        self.assertEqual(unit_names["minimum_output_headroom"], 1)
        self.assertTrue(unit_names["pointer_bytes_unchanged"])
        self.assertTrue(unit_names["readback_exact"])
        self.assertEqual(
            self.manifest["ratchet"]["actual"]["excluded_entry_count"],
            0,
        )
        self.assertTrue(
            self.manifest["acceptance"][
                "selected_targets_reread_exact"
            ]
        )

    def test_font_and_codec_composition_is_bounded(self):
        composition = self.manifest["composition"]
        self.assertEqual(composition["font_chunk_index"], 2)
        self.assertEqual(composition["vt1_chunk_count"], 14)
        self.assertEqual(
            composition["preserved_non_font_vt1_chunk_count"], 13
        )
        self.assertEqual(
            composition["font_borrowed_preceding_zero_slack"], 10032
        )
        self.assertTrue(composition["vt1_archive_size_preserved"])
        self.assertEqual(composition["zero_slack_donor_chunk_index"], 1)
        self.assertEqual(
            composition["font_and_slps_text_overlap_byte_count"],
            0,
        )
        self.assertEqual(
            composition["compdata_compressed_common_prefix"],
            108324,
        )
        codec = composition["compdata_codec"]
        self.assertEqual(codec["strategy"], "rust-maximum")
        self.assertEqual(codec["min_match_length"], 3)
        self.assertEqual(codec["maximum_output_size"], 145408)
        self.assertEqual(codec["budget_headroom"], 115)
        self.assertTrue(codec["within_sector_budget"])
        self.assertGreaterEqual(codec["budget_headroom"], 0)
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_first_five_titles_and_opening_profile_use_locked_spans(self):
        titles = self.manifest["fixed_span"]["first_five_stage_titles"]
        self.assertEqual(titles["entry_count"], 5)
        self.assertEqual(
            [entry["span"] for entry in titles["entries"]],
            [24, 16, 16, 16, 16],
        )
        self.assertTrue(titles["readback_exact"])
        self.assertTrue(titles["pointer_bytes_unchanged"])
        self.assertTrue(titles["non_target_bytes_unchanged"])
        stage_two = titles["entries"][1]
        self.assertEqual(stage_two["source_encoded_size"], 9)
        self.assertEqual(stage_two["output_encoded_size"], 11)
        self.assertEqual(stage_two["headroom"], 5)

        profile = self.manifest["fixed_span"]["opening_profile"]
        self.assertEqual(profile["entry_count"], 4)
        self.assertEqual(
            [entry["entry_id"] for entry in profile["entries"]],
            [
                "menu/Compdata/direct/opening-male-route-title",
                "menu/Compdata/direct/opening-female-route-title",
                "menu/Compdata/direct/opening-male-profile",
                "menu/Compdata/direct/opening-female-profile",
            ],
        )
        self.assertEqual(
            [entry["span"] for entry in profile["entries"]],
            [32, 32, 128, 136],
        )
        self.assertTrue(profile["readback_exact"])
        self.assertTrue(profile["non_target_bytes_unchanged"])

    def test_output_locks_and_runtime_boundary_are_explicit(self):
        self.assertEqual(
            self.manifest["outputs"]["slps"]["sha256"],
            "7806a15b088c7c7cbf4a5859c43ecee5165d91d212cfcaacaa33224c7cf4d979",
        )
        self.assertEqual(
            self.manifest["outputs"]["vt1"],
            {
                "path": "work/build/ui-p10-database-fixed-core/components/DATA/VT1.BIN",
                "size": 127501728,
                "sha256": "f7640d2b0093ef37002265445f309a62d959e6797bc9bb51b01c288070bc5ee9",
            },
        )
        self.assertEqual(
            self.manifest["outputs"]["compdata"]["sha256"],
            "bcc573758e0b452114c04370f97c5d898aa2879a39a20cc5caed7314fbbd2ee9",
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            len(self.manifest["runtime"]["required_routes"]),
            9,
        )


if __name__ == "__main__":
    unittest.main()
