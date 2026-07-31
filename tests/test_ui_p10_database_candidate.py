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

    def test_all_403_entries_are_fixed_span_and_reread(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["entry_count"], 403)
        self.assertEqual(selection["slps_entry_count"], 233)
        self.assertEqual(selection["compdata_entry_count"], 170)
        self.assertEqual(
            self.manifest["ratchet"]["actual"][
                "fixed_covered_entry_count"
            ],
            403,
        )
        self.assertEqual(
            self.manifest["ratchet"]["actual"][
                "font_semantic_replacement_count"
            ],
            1,
        )
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
        self.assertEqual(composition["unchanged_vt1_chunk_count"], 13)
        self.assertEqual(
            composition["font_and_slps_text_overlap_byte_count"],
            0,
        )
        self.assertEqual(
            composition["compdata_compressed_common_prefix"],
            113266,
        )
        codec = composition["compdata_codec"]
        self.assertEqual(codec["strategy"], "rust-maximum")
        self.assertEqual(codec["maximum_output_size"], 145408)
        self.assertTrue(codec["within_sector_budget"])
        self.assertGreaterEqual(codec["budget_headroom"], 0)
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_output_locks_and_runtime_boundary_are_explicit(self):
        self.assertEqual(
            self.manifest["outputs"]["slps"]["sha256"],
            "c5ab62a6e530118805a2025d2598872838012ae6d0c7fab023c4722eb6433cc0",
        )
        self.assertEqual(
            self.manifest["outputs"]["compdata"]["sha256"],
            "d91e38bd0ede4520362ae1e08047887623e5c0586e3224d4ba8d19a39615d8f2",
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            len(self.manifest["runtime"]["required_routes"]),
            4,
        )


if __name__ == "__main__":
    unittest.main()
