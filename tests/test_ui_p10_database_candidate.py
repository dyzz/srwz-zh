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

    def test_all_402_entries_are_fixed_span_and_reread(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["entry_count"], 402)
        self.assertEqual(selection["slps_entry_count"], 232)
        self.assertEqual(selection["compdata_entry_count"], 170)
        self.assertEqual(
            self.manifest["ratchet"]["actual"][
                "fixed_covered_entry_count"
            ],
            402,
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
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_output_locks_and_runtime_boundary_are_explicit(self):
        self.assertEqual(
            self.manifest["outputs"]["slps"]["sha256"],
            "5eae555d6ec6287ac1ede7c0d27b9a3482eacff89a2bab092c2c7c50e434542f",
        )
        self.assertEqual(
            self.manifest["outputs"]["compdata"]["sha256"],
            "102b5f2e97bd7143e1d820c1b2a62c73dc41f274a44394103c3b5c547bfa6d62",
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            len(self.manifest["runtime"]["required_routes"]),
            4,
        )


if __name__ == "__main__":
    unittest.main()
