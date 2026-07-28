import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.ui_runtime_matrix import (
    UiRuntimeMatrixError,
    audit_ui_runtime_matrix,
    build_runtime_matrix_manifest,
    write_runtime_matrix_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-runtime-test-matrix.json"


class UiRuntimeMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.report = audit_ui_runtime_matrix(PROJECT_ROOT, CONFIG_PATH)
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.cases = {
            case["case_id"]: case
            for case in cls.config["cases"]
        }

    def _audit_mutation(self, mutation):
        document = copy.deepcopy(self.config)
        mutation(document)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ui-test-matrix.json"
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return audit_ui_runtime_matrix(PROJECT_ROOT, path)

    def test_committed_manifest_matches_current_locked_inputs(self):
        self.assertEqual(
            build_runtime_matrix_manifest(self.report),
            self.manifest,
        )
        self.assertEqual(
            self.manifest["status"],
            "runtime_matrix_validated_execution_pending",
        )
        self.assertEqual(self.manifest["summary"]["runtime_passed_case_count"], 0)
        self.assertEqual(
            self.manifest["summary"]["runtime_not_tested_case_count"],
            19,
        )

    def test_every_inventory_scene_has_one_explicit_disposition(self):
        inventory = json.loads(
            (PROJECT_ROOT / "config/ui-scenes.json").read_text(encoding="utf-8")
        )
        inventory_ids = {scene["scene_id"] for scene in inventory["scenes"]}
        dispositions = self.manifest["scene_dispositions"]
        self.assertEqual(
            {item["scene_id"] for item in dispositions},
            inventory_ids,
        )
        self.assertEqual(len(dispositions), len(inventory_ids))
        self.assertEqual(
            {
                item["scene_id"]
                for item in dispositions
                if item["disposition"] == "selected"
            },
            {
                "title/main-menu",
                "opening/player-setup",
                "intermission/main-and-options",
                "information/unit-pilot-mech-core",
                "battle/map-and-tactical",
                "results/level-up-and-deployment",
                "search/filter-and-results",
                "route/stage-title-and-branch",
                "opening/world-history-scroll",
                "story/first-five-opening-sequences",
            },
        )
        self.assertTrue(
            all(
                item["disposition"] == "selected"
                for item in dispositions
                if item["priority"] == "P0"
            )
        )

    def test_first_five_opening_variants_are_independent_cases(self):
        variants = {
            case["variant"]
            for case in self.manifest["cases"]
            if "story/first-five-opening-sequences" in case["scene_ids"]
        }
        self.assertEqual(variants, {"001", "002", "003", "004", "005"})
        self.assertEqual(
            self.cases["first-five/stage-001-opening"]["fixture_id"],
            "fresh-boot",
        )
        for stage in ("002", "003", "004", "005"):
            self.assertEqual(
                self.cases[f"first-five/stage-{stage}-opening"]["fixture_id"],
                "first-five-progress-card",
            )

    def test_world_history_requires_start_middle_end_and_sequence(self):
        case = self.cases["core/world-history-scroll"]
        phases = {
            capture.get("phase")
            for capture in case["capture_points"]
            if capture.get("phase") is not None
        }
        self.assertEqual(phases, {"start", "middle", "end"})
        self.assertIn(
            "screenshot_sequence",
            {capture["kind"] for capture in case["capture_points"]},
        )

    def test_five_atlas_cases_keep_screenshot_texture_dual_gate(self):
        mapping_cases = [
            case
            for case in self.manifest["cases"]
            if case["purpose"] == "asset_mapping"
        ]
        self.assertEqual(len(mapping_cases), 5)
        self.assertEqual(
            {
                case["texture_delta"]["chunk_index"]:
                case["texture_delta"]["changed_pixel_count"]
                for case in mapping_cases
            },
            {
                2: 299,
                4: 2297,
                5: 2197,
                6: 803,
                7: 1325,
            },
        )
        for case in mapping_cases:
            self.assertEqual(case["capture_counts"]["screenshot"], 1)
            self.assertEqual(case["capture_counts"]["texture_delta"], 1)
            self.assertEqual(case["runtime_status"], "not_tested")

    def test_missing_memory_cards_are_not_replaced_by_savestates(self):
        fixtures = {
            fixture["fixture_id"]: fixture
            for fixture in self.manifest["fixtures"]
        }
        self.assertEqual(fixtures["fresh-boot"]["status"], "ready")
        memory_cards = [
            fixture
            for fixture in fixtures.values()
            if fixture["kind"] == "memory_card"
        ]
        self.assertEqual(len(memory_cards), 6)
        for fixture in memory_cards:
            self.assertEqual(fixture["status"], "not_acquired")
            self.assertIsNone(fixture["sha256"])
            self.assertTrue(fixture["workspace_path"].endswith(".ps2"))
            self.assertNotIn(".p2s", fixture["workspace_path"])
        self.assertEqual(
            self.manifest["summary"]["route_ready_case_count"],
            4,
        )
        self.assertEqual(
            self.manifest["summary"]["missing_fixture_case_count"],
            15,
        )

    def test_tsv_is_one_bounded_row_per_case(self):
        stream = io.StringIO()
        write_runtime_matrix_tsv(self.report, stream)
        rows = stream.getvalue().splitlines()
        self.assertEqual(len(rows), 20)
        self.assertIn("iso_sha256", rows[0])
        self.assertIn("texture_delta_pixels", rows[0])
        self.assertTrue(any("mapping/info-atlas" in row for row in rows[1:]))

    def test_scene_inventory_hash_drift_fails_closed(self):
        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "scene inventory SHA-256 drift",
        ):
            self._audit_mutation(
                lambda document: document["scene_inventory"].update(
                    {"sha256": "0" * 64}
                )
            )

    def test_duplicate_capture_id_fails_closed(self):
        def mutate(document):
            document["cases"][1]["capture_points"][0]["capture_id"] = (
                document["cases"][0]["capture_points"][0]["capture_id"]
            )

        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "capture ID is invalid or duplicated",
        ):
            self._audit_mutation(mutate)

    def test_ready_memory_card_without_hash_fails_closed(self):
        def mutate(document):
            document["fixtures"][1]["status"] = "ready"

        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "memory-card hash",
        ):
            self._audit_mutation(mutate)

    def test_world_history_missing_phase_fails_closed(self):
        def mutate(document):
            case = next(
                case
                for case in document["cases"]
                if case["case_id"] == "core/world-history-scroll"
            )
            case["capture_points"][2].pop("phase")

        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "must capture start, middle and end",
        ):
            self._audit_mutation(mutate)

    def test_mapping_case_without_texture_delta_fails_closed(self):
        def mutate(document):
            case = next(
                case
                for case in document["cases"]
                if case["case_id"] == "mapping/info-atlas"
            )
            case["capture_points"] = [
                capture
                for capture in case["capture_points"]
                if capture["kind"] != "texture_delta"
            ]

        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "needs one locked texture delta",
        ):
            self._audit_mutation(mutate)


if __name__ == "__main__":
    unittest.main()
