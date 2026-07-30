import json
import unittest
from pathlib import Path

from tools.verify_ui_test_candidate_iso import build_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/iso/"
    "ui-p8-remaining-user-facing-first-five-atlas-test-build.json"
)
COMPONENT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/"
    "ui-p8-remaining-user-facing-first-five-atlas-test-validation.json"
)
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/"
    "ui-p8-remaining-user-facing-first-five-atlas-test-runtime-validation.json"
)


class UiP8TestCandidateIsoTests(unittest.TestCase):
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
                    "99235186f0a70b6cad40aa7f2b34d564d751bd1c5c93810b2"
                    "fce75cdea5bbc3f"
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
        self.assertEqual(
            self.runtime["iso_build"]["unchanged_member_count"],
            59,
        )
        self.assertEqual(
            self.runtime["iso_build"]["shift_segments"],
            self.config["layout"]["shift_segments"],
        )

    def test_runtime_boundary_is_explicit(self):
        self.assertEqual(
            self.runtime["status"],
            (
                "static_integrated_ui_p8_remaining_user_facing_first_five_"
                "atlas_test_iso_validated_runtime_pending"
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
