import json
import unittest
from pathlib import Path

from tools.srwz.ui_test_candidate import build_ui_test_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-integration/p3-fresh-boot-first-five-atlas-test.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p3-fresh-boot-first-five-atlas-test-validation.json"
)


class UiP3TestCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_rebuild_manifest_and_seven_outputs_are_exact(self):
        payloads, report = build_ui_test_candidate(PROJECT_ROOT, CONFIG_PATH)
        self.assertEqual(report, self.manifest)
        self.assertEqual(sorted(payloads), self.config["composition"]["members"])
        for member, payload in payloads.items():
            path = PROJECT_ROOT / report["outputs"][member]["path"]
            self.assertEqual(path.read_bytes(), payload)

    def test_p3_core_owns_the_four_ui_members(self):
        outputs = self.manifest["outputs"]
        self.assertEqual(len(outputs), 7)
        self.assertEqual(
            {
                item["owner"] for item in outputs.values()
            },
            {
                "ui-p3-fresh-boot-core",
                "ui-atlas-suite-zh",
                "first-five-story",
            },
        )
        self.assertEqual(
            outputs["SLPS_258.87"]["sha256"],
            "84c19cba14cc9583bfd49b8105149684b445231691a4ec736ffb4d788b0568f0",
        )
        self.assertEqual(
            self.manifest["composition"]["font_owner"],
            "ui-p3-fresh-boot-core",
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_runtime_boundary_covers_twelve_scene_families(self):
        self.assertEqual(
            self.manifest["status"],
            (
                "integrated_ui_p3_fresh_boot_first_five_atlas_test_"
                "component_validated_runtime_pending"
            ),
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            len(self.manifest["runtime"]["required_scene_families"]),
            12,
        )
        self.assertIn(
            "tutorial/unit-stat-and-terrain-legend",
            self.manifest["runtime"]["required_scene_families"],
        )
        self.assertIn(
            "opening/default-protagonist-labels",
            self.manifest["runtime"]["required_scene_families"],
        )


if __name__ == "__main__":
    unittest.main()
