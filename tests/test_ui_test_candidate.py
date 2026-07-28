import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.ui_test_candidate import (
    UiTestCandidateError,
    build_ui_test_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-integration/p2-first-five-atlas-test.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p2-first-five-atlas-test-validation.json"
)


class UiTestCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def _mutated_config(self, mutation):
        document = copy.deepcopy(self.config)
        mutation(document)
        temporary = tempfile.TemporaryDirectory(dir=WORK_ROOT)
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "candidate.json"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

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

    def test_member_ownership_is_disjoint_and_source_exact(self):
        outputs = self.manifest["outputs"]
        self.assertEqual(len(outputs), 7)
        self.assertEqual(
            {
                item["owner"] for item in outputs.values()
            },
            {
                "ui-p2-core",
                "ui-atlas-suite-zh",
                "first-five-story",
            },
        )
        for item in outputs.values():
            output = PROJECT_ROOT / item["path"]
            source = PROJECT_ROOT / item["source"]["path"]
            self.assertEqual(output.read_bytes(), source.read_bytes())
            self.assertTrue(item["manifest_output_lock_exact"])

    def test_runtime_boundary_and_content_policy_are_explicit(self):
        self.assertEqual(
            self.manifest["status"],
            (
                "integrated_ui_p2_first_five_atlas_test_component_"
                "validated_runtime_pending"
            ),
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertTrue(
            self.manifest["runtime"][
                "isolated_atlas_mapping_profiles_remain_required"
            ]
        )
        self.assertEqual(
            len(self.manifest["runtime"]["required_scene_families"]),
            10,
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_manifest_contains_no_translation_payload(self):
        def visit(value):
            if isinstance(value, dict):
                self.assertNotIn("source_text", value)
                self.assertNotIn("translation", value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.manifest)

    def test_component_status_drift_is_rejected(self):
        path = self._mutated_config(
            lambda document: document["components"]["ui_p2_core"][
                "manifest"
            ].update({"required_status": "wrong"})
        )
        with self.assertRaisesRegex(
            UiTestCandidateError,
            "status drift",
        ):
            build_ui_test_candidate(PROJECT_ROOT, path)

    def test_component_runtime_status_drift_is_rejected(self):
        path = self._mutated_config(
            lambda document: document["components"][
                "first_five_story"
            ]["manifest"].update({"required_runtime_status": "passed"})
        )
        with self.assertRaisesRegex(
            UiTestCandidateError,
            "runtime status drift",
        ):
            build_ui_test_candidate(PROJECT_ROOT, path)

    def test_missing_manifest_output_field_is_rejected(self):
        path = self._mutated_config(
            lambda document: document["components"]["atlas_suite"][
                "outputs"
            ][0].update({"manifest_lock_field": "outputs.missing"})
        )
        with self.assertRaisesRegex(
            UiTestCandidateError,
            "manifest field is missing",
        ):
            build_ui_test_candidate(PROJECT_ROOT, path)

    def test_duplicate_member_owner_is_rejected(self):
        def duplicate(document):
            output = copy.deepcopy(
                document["components"]["first_five_story"]["outputs"][0]
            )
            output["member"] = "SLPS_258.87"
            document["components"]["first_five_story"]["outputs"].append(
                output
            )

        path = self._mutated_config(duplicate)
        with self.assertRaisesRegex(
            UiTestCandidateError,
            "member ownership overlaps",
        ):
            build_ui_test_candidate(PROJECT_ROOT, path)


if __name__ == "__main__":
    unittest.main()
