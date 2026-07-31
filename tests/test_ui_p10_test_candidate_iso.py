import json
import unittest
from pathlib import Path

from tools.verify_ui_test_candidate_iso import build_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/iso/"
    "ui-p10-database-fixed-core-first-five-atlas-test-build.json"
)
COMPONENT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/"
    "ui-p10-database-fixed-core-first-five-atlas-test-validation.json"
)
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/"
    "ui-p10-database-fixed-core-first-five-atlas-test-runtime-validation.json"
)


class UiP10TestCandidateIsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.component = json.loads(
            COMPONENT_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.runtime = json.loads(
            RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_static_iso_report_and_manifest_are_exact(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not (PROJECT_ROOT / config["output"]["path"]).is_file():
            self.skipTest(
                "legacy generated ISO is not materialized; rebuild from config"
            )
        self.assertEqual(
            build_report(CONFIG_PATH, COMPONENT_MANIFEST_PATH),
            self.runtime,
        )
        self.assertEqual(
            self.runtime["iso_build"]["output"],
            {
                "size": 3758456832,
                "sha256": (
                    "2bba1c82a0f1fa88eef2d0870c62eddbf36cfe4ceaa8f566"
                    "767d3c5020c37431"
                ),
            },
        )

    def test_seven_members_and_single_shift_segment_are_bound(self):
        replacements = self.runtime["iso_build"]["replacements"]
        self.assertEqual(set(replacements), set(self.component["outputs"]))
        self.assertEqual(len(replacements), 7)
        self.assertTrue(
            all(
                item["independent_udf_reread_exact"]
                for item in replacements.values()
            )
        )
        self.assertEqual(
            self.runtime["iso_build"]["shift_segments"],
            [
                {
                    "first_member": "DATA/STAGE.BIN",
                    "shift_sectors": 1,
                },
            ],
        )

    def test_runtime_boundary_is_explicit(self):
        self.assertTrue(all(self.runtime["static_acceptance"].values()))
        self.assertEqual(
            self.runtime["runtime"]["status"],
            "boot_smoke_passed_visual_not_tested",
        )
        self.assertEqual(self.runtime["runtime"]["pine_state"], "Running")
        self.assertEqual(self.runtime["runtime"]["tlb_miss_count"], 0)
        self.assertEqual(
            self.runtime["runtime"]["required_iso_sha256"],
            self.runtime["iso_build"]["output"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
