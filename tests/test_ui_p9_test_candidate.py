import json
import unittest
from pathlib import Path

from tools.srwz.ui_test_candidate import build_ui_test_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-integration/"
    "p9-mixed-user-facing-subset-first-five-atlas-test.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/"
    "ui-p9-mixed-user-facing-subset-first-five-atlas-test-validation.json"
)


class UiP9TestCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_rebuild_manifest_and_seven_outputs_are_exact(self):
        payloads, report = build_ui_test_candidate(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        self.assertEqual(report, self.manifest)
        self.assertEqual(
            sorted(payloads),
            self.config["composition"]["members"],
        )
        for member, payload in payloads.items():
            path = PROJECT_ROOT / report["outputs"][member]["path"]
            self.assertEqual(path.read_bytes(), payload)

    def test_p9_core_owns_the_four_ui_members(self):
        outputs = self.manifest["outputs"]
        self.assertEqual(len(outputs), 7)
        self.assertEqual(
            {item["owner"] for item in outputs.values()},
            {
                "ui-p9-mixed-user-facing-subset-core",
                "ui-atlas-suite-zh",
                "first-five-story",
            },
        )
        self.assertEqual(
            outputs["SLPS_258.87"]["sha256"],
            "51adcd5c79f422924743d758eaab77cc46d939e7c1272f88dcd614eb2c704657",
        )
        self.assertEqual(
            self.manifest["composition"]["font_owner"],
            "ui-p9-mixed-user-facing-subset-core",
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_runtime_boundary_covers_thirty_scene_families(self):
        self.assertEqual(
            self.manifest["runtime"]["status"],
            "not_tested",
        )
        families = self.manifest["runtime"]["required_scene_families"]
        self.assertEqual(len(families), 30)
        self.assertIn(
            "preparation/reboard-status-visible-subset",
            families,
        )
        self.assertIn(
            "information/pilot-ability-visible-subset",
            families,
        )


if __name__ == "__main__":
    unittest.main()
