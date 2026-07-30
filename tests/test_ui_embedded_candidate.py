import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.ui_embedded_candidate import (
    UiEmbeddedCandidateError,
    build_ui_embedded_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
CONFIG_PATH = (
    PROJECT_ROOT / "config/ui-writeback/ui-p3-fresh-boot-slps.json"
)
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p3-fresh-boot-validation.json"


class UiEmbeddedCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

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

    def test_rebuild_manifest_and_four_outputs_are_exact(self):
        payloads, report = build_ui_embedded_candidate(
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
            path = PROJECT_ROOT / report["outputs"][output_names[member]]["path"]
            self.assertEqual(path.read_bytes(), payload)

    def test_selection_and_fixed_span_composition_are_exact(self):
        selection = self.manifest["selection"]
        composition = self.manifest["composition"]
        self.assertEqual(selection["scene_count"], 2)
        self.assertEqual(selection["entry_count"], 23)
        self.assertEqual(selection["no_op_entry_count"], 11)
        self.assertEqual(selection["selected_write_entry_count"], 12)
        self.assertEqual(selection["selected_write_target_count"], 32)
        self.assertEqual(composition["slice_changed_byte_count"], 124)
        self.assertEqual(self.manifest["slice"]["component"]["difference_range_count"], 35)
        self.assertEqual(composition["overlap_byte_count"], 0)
        self.assertTrue(composition["base_preimage_exact_at_slice_offsets"])
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_only_slps_differs_from_the_p2_core(self):
        outputs = self.manifest["outputs"]
        base = self.manifest["inputs"]["base_ui_core"]["outputs"]
        self.assertNotEqual(outputs["slps"]["sha256"], base["slps"]["sha256"])
        self.assertEqual(
            outputs["slps"]["sha256"],
            "fa703c5d7cdf4e5113e50743374547adb2031bd5393d15c05d01037c188c3a44",
        )
        for name in ("vt1", "compdata", "mtv_pros"):
            self.assertEqual(outputs[name]["sha256"], base[name]["sha256"])
            self.assertEqual(outputs[name]["size"], base[name]["size"])
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")

    def test_non_ready_scene_is_rejected(self):
        path = self._mutated_config(
            lambda document: document["scene_map"].update(
                {"selected_scene_ids": ["options/bgm-controller-and-map-settings"]}
            )
        )
        with self.assertRaisesRegex(
            UiEmbeddedCandidateError,
            "does not match required scene-map readiness",
        ):
            build_ui_embedded_candidate(PROJECT_ROOT, path)

    def test_p2_base_hash_drift_is_rejected(self):
        path = self._mutated_config(
            lambda document: document["base_ui_core"]["outputs"]["slps"].update(
                {"sha256": "0" * 64}
            )
        )
        with self.assertRaisesRegex(
            UiEmbeddedCandidateError,
            "size or SHA-256 drift",
        ):
            build_ui_embedded_candidate(PROJECT_ROOT, path)

    def test_ratchet_failure_reports_actual_counts_and_checks(self):
        path = self._mutated_config(
            lambda document: document["ratchet"].update(
                {
                    "selected_entry_count": (
                        document["ratchet"]["selected_entry_count"] + 1
                    )
                }
            )
        )
        with self.assertRaisesRegex(
            UiEmbeddedCandidateError,
            r"ratchet failed: actual=.*checks=",
        ):
            build_ui_embedded_candidate(PROJECT_ROOT, path)


if __name__ == "__main__":
    unittest.main()
