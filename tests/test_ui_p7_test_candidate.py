import json
import unittest
from pathlib import Path

from tools.srwz.ui_test_candidate import build_ui_test_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-integration/"
    "p7-embedded-font-groups-first-five-atlas-test.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/"
    "ui-p7-embedded-font-groups-first-five-atlas-test-validation.json"
)


class UiP7TestCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_rebuild_manifest_and_seven_outputs_are_exact(self):
        payloads, report = build_ui_test_candidate(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        self.assertEqual(report, self.manifest)
        self.assertEqual(sorted(payloads), self.config["composition"]["members"])
        for member, payload in payloads.items():
            path = PROJECT_ROOT / report["outputs"][member]["path"]
            self.assertEqual(path.read_bytes(), payload)

    def test_p7_core_owns_the_four_ui_members(self):
        outputs = self.manifest["outputs"]
        self.assertEqual(len(outputs), 7)
        self.assertEqual(
            {item["owner"] for item in outputs.values()},
            {
                "ui-p7-embedded-font-groups-core",
                "ui-atlas-suite-zh",
                "first-five-story",
            },
        )
        self.assertEqual(
            outputs["SLPS_258.87"]["sha256"],
            "8822c29da791295e534ba72e300e9167ded4fa95028986013d253238e4e52220",
        )
        self.assertEqual(
            outputs["DATA/VT1.BIN"]["sha256"],
            "1424eb1626b624eb637130e08a11c320e5fb39ebf40077e91cbbfe6875839fbf",
        )
        self.assertEqual(
            self.manifest["composition"]["font_owner"],
            "ui-p7-embedded-font-groups-core",
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_runtime_boundary_covers_twenty_four_scene_families(self):
        self.assertEqual(
            self.manifest["status"],
            (
                "integrated_ui_p7_embedded_font_groups_first_five_atlas_"
                "test_component_validated_runtime_pending"
            ),
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        families = self.manifest["runtime"]["required_scene_families"]
        self.assertEqual(len(families), 24)
        self.assertIn("upgrade/full-upgrade-reward", families)


if __name__ == "__main__":
    unittest.main()
