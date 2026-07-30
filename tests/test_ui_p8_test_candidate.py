import json
import unittest
from pathlib import Path

from tools.srwz.ui_test_candidate import build_ui_test_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-integration/"
    "p8-remaining-user-facing-first-five-atlas-test.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/"
    "ui-p8-remaining-user-facing-first-five-atlas-test-validation.json"
)


class UiP8TestCandidateTests(unittest.TestCase):
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

    def test_p8_core_owns_the_four_ui_members(self):
        outputs = self.manifest["outputs"]
        self.assertEqual(len(outputs), 7)
        self.assertEqual(
            {item["owner"] for item in outputs.values()},
            {
                "ui-p8-remaining-user-facing-core",
                "ui-atlas-suite-zh",
                "first-five-story",
            },
        )
        self.assertEqual(
            outputs["SLPS_258.87"]["sha256"],
            "2b6e9909f50f49186079fe5908c3191b47ddafb50fe86d631fc1091945b2353d",
        )
        self.assertEqual(
            outputs["DATA/VT1.BIN"]["sha256"],
            "1424eb1626b624eb637130e08a11c320e5fb39ebf40077e91cbbfe6875839fbf",
        )
        self.assertEqual(
            self.manifest["composition"]["font_owner"],
            "ui-p8-remaining-user-facing-core",
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_runtime_boundary_covers_twenty_eight_scene_families(self):
        self.assertEqual(
            self.manifest["status"],
            (
                "integrated_ui_p8_remaining_user_facing_first_five_atlas_"
                "test_component_validated_runtime_pending"
            ),
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        families = self.manifest["runtime"]["required_scene_families"]
        self.assertEqual(len(families), 28)
        self.assertIn("formation/terrain-variant-selector", families)
        self.assertIn(
            "battle/weapon-selection-and-use-conditions",
            families,
        )
        self.assertIn(
            "information/reboard-and-option-subpages",
            families,
        )
        self.assertIn(
            "parts/equipment-and-predeployment-actions",
            families,
        )


if __name__ == "__main__":
    unittest.main()
