import json
import unittest
from pathlib import Path

from tools.verify_ui_test_candidate_iso import build_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/iso/ui-p3-fresh-boot-first-five-atlas-test-build.json"
)
COMPONENT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p3-fresh-boot-first-five-atlas-test-validation.json"
)
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p3-fresh-boot-first-five-atlas-test-runtime-validation.json"
)


class UiP3TestCandidateIsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.component = json.loads(
            COMPONENT_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.runtime = json.loads(
            RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_static_iso_report_and_manifest_are_exact(self):
        self.assertEqual(
            build_report(CONFIG_PATH, COMPONENT_MANIFEST_PATH),
            self.runtime,
        )
        self.assertEqual(
            self.runtime["iso_build"]["output"],
            {
                "size": 3758456832,
                "sha256": (
                    "cc4575bdc94a71d79c3a40810308d4eb41f8d3f69f1fd4"
                    "0139e63c83fde038c0"
                ),
            },
        )

    def test_all_seven_members_are_bound_and_reread(self):
        replacements = self.runtime["iso_build"]["replacements"]
        self.assertEqual(set(replacements), set(self.component["outputs"]))
        self.assertEqual(len(replacements), 7)
        self.assertTrue(
            all(
                item["independent_udf_reread_exact"]
                for item in replacements.values()
            )
        )
        self.assertEqual(self.runtime["iso_build"]["unchanged_member_count"], 59)
        self.assertEqual(
            self.runtime["iso_build"]["shift_segments"],
            self.config["layout"]["shift_segments"],
        )

    def test_runtime_boundary_is_explicit(self):
        self.assertEqual(
            self.runtime["status"],
            (
                "static_integrated_ui_p3_fresh_boot_first_five_atlas_test_"
                "iso_validated_runtime_pending"
            ),
        )
        self.assertTrue(all(self.runtime["static_acceptance"].values()))
        self.assertEqual(self.runtime["runtime"]["status"], "not_tested")
        self.assertEqual(
            self.runtime["runtime"]["required_iso_sha256"],
            self.runtime["iso_build"]["output"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
