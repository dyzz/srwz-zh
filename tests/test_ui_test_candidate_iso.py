import json
import unittest
from pathlib import Path

from tools.verify_ui_test_candidate_iso import build_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/iso/ui-p2-first-five-atlas-test-build.json"
)
COMPONENT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p2-first-five-atlas-test-validation.json"
)
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p2-first-five-atlas-test-runtime-validation.json"
)


class UiTestCandidateIsoTests(unittest.TestCase):
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
                    "af5c1c5a510db1d86bee2054935400e51c86df34902972"
                    "ef2ebafa71bb3eb52a"
                ),
            },
        )

    def test_all_seven_component_members_are_bound_to_iso(self):
        replacements = self.runtime["iso_build"]["replacements"]
        self.assertEqual(
            set(replacements),
            set(self.component["outputs"]),
        )
        self.assertEqual(len(replacements), 7)
        self.assertTrue(
            all(
                item["independent_udf_reread_exact"]
                for item in replacements.values()
            )
        )
        self.assertEqual(
            {item["owner"] for item in replacements.values()},
            {
                "ui-p2-core",
                "ui-atlas-suite-zh",
                "first-five-story",
            },
        )

    def test_iso_layout_and_runtime_boundary_are_explicit(self):
        self.assertEqual(
            self.runtime["status"],
            (
                "static_integrated_ui_p2_first_five_atlas_test_iso_"
                "validated_runtime_pending"
            ),
        )
        self.assertEqual(
            self.runtime["iso_build"]["shift_segments"],
            self.config["layout"]["shift_segments"],
        )
        self.assertTrue(
            all(self.runtime["static_acceptance"].values())
        )
        self.assertEqual(self.runtime["runtime"]["status"], "not_tested")
        self.assertTrue(
            self.runtime["runtime"][
                "isolated_atlas_mapping_profiles_remain_required"
            ]
        )

    def test_manifests_contain_no_translation_payload(self):
        def visit(value):
            if isinstance(value, dict):
                self.assertNotIn("source_text", value)
                self.assertNotIn("translation", value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.runtime)


if __name__ == "__main__":
    unittest.main()
