import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.ui_runtime_matrix import (
    UiRuntimeMatrixError,
    _matrix_plan_sha256,
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
        title_case = next(
            case
            for case in document["cases"]
            if case["case_id"] == "core/title-main-menu"
        )
        title_case["runtime_status"] = "not_tested"
        title_case.pop("runtime_evidence", None)
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
            46,
        )
        self.assertEqual(self.manifest["summary"]["artifact_count"], 8)
        self.assertEqual(
            self.manifest["summary"]["capture_counts"],
            {
                "screenshot": 112,
                "screenshot_sequence": 6,
                "texture_delta": 5,
            },
        )
        integrated = self.manifest["artifacts"][0]
        self.assertEqual(
            integrated["artifact_id"],
            "first-five-noncompdata-ui",
        )
        self.assertEqual(
            integrated["iso_sha256"],
            (
                "85ba645d980d84861f233a11c93b1f0cb3742a8a0583cec4"
                "1d9e70263851ec39"
            ),
        )
        non_mapping_cases = [
            case
            for case in self.manifest["cases"]
            if case["purpose"] != "asset_mapping"
        ]
        blocked_case_ids = {
            "first-five/stage-title-route-branch",
            "compdata/information-display-names",
            "compdata/search-filter-terms",
            "database/unit-special-abilities-core",
            "database/leadership-effects-core",
        }
        self.assertEqual(
            {
                case["case_id"]
                for case in non_mapping_cases
                if case["artifact_id"]
                == "first-five-full-ui-with-compdata"
            },
            blocked_case_ids,
        )
        self.assertTrue(
            all(
                case["artifact_id"] == "first-five-noncompdata-ui"
                for case in non_mapping_cases
                if case["case_id"] not in blocked_case_ids
                and case["case_id"]
                not in {
                    "fresh-boot/default-protagonist-labels",
                    "compdata/intermission-buttons",
                }
            )
        )
        self.assertEqual(
            {
                self.cases[case_id]["artifact_id"]
                for case_id in {
                    "fresh-boot/default-protagonist-labels",
                    "compdata/intermission-buttons",
                }
            },
            {"ui-p1-opening-names-maximum"},
        )

    def test_every_inventory_scene_has_one_explicit_disposition(self):
        inventory = json.loads(
            (PROJECT_ROOT / "config/ui-scenes.json").read_text(encoding="utf-8")
        )
        inventory_ids = {scene["scene_id"] for scene in inventory["scenes"]}
        extension_ids = {
            scene["scene_id"]
            for extension in self.manifest["scene_extensions"]
            for scene in extension["scenes"]
        }
        dispositions = self.manifest["scene_dispositions"]
        self.assertEqual(
            {item["scene_id"] for item in dispositions},
            inventory_ids | extension_ids,
        )
        self.assertEqual(
            len(dispositions),
            len(inventory_ids) + len(extension_ids),
        )
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
                "tutorial/unit-stat-and-terrain-legend",
                "opening/default-protagonist-labels",
                "formation/squad-and-reboard-confirmations",
                "information/tactical-status-metrics",
                "battle/end-phase-map-command-tail",
                "battle/action-restriction-messages",
                "system/quick-command-save-and-cancel-confirmations",
                "battle/repair-resupply-spirit-targeting",
                "deployment/squad-selection-and-size-format",
                "options/bgm-controller-and-map-settings",
                "results/settlement-and-support-setup",
                "formation/list-search-and-priority",
                "upgrade/full-upgrade-reward",
                "archive/scenario-progress-and-route-headings",
                "formation/terrain-variant-selector",
                "battle/weapon-selection-and-use-conditions",
                "information/reboard-and-option-subpages",
                "parts/equipment-and-predeployment-actions",
                "preparation/reboard-status-visible-subset",
                "information/pilot-ability-visible-subset",
                "database/pilot-skills-core",
                "database/unit-special-abilities-core",
                "database/spirit-commands-core",
                "database/leadership-effects-core",
            },
        )
        self.assertTrue(
            all(
                item["disposition"] == "selected"
                for item in dispositions
                if item["priority"] == "P0"
            )
        )

    def test_promoted_scene_extensions_are_hash_locked_and_selected(self):
        self.assertEqual(self.manifest["summary"]["base_scene_count"], 14)
        self.assertEqual(self.manifest["summary"]["extended_scene_count"], 24)
        self.assertEqual(self.manifest["summary"]["scene_count"], 38)
        self.assertEqual(len(self.manifest["scene_extensions"]), 3)
        (
            extension,
            subset_extension,
            database_extension,
        ) = self.manifest["scene_extensions"]
        self.assertEqual(extension["scene_count"], 18)
        self.assertEqual(extension["promoted_entry_count"], 253)
        self.assertEqual(extension["remaining_entry_count"], 22)
        self.assertEqual(
            extension["promotion_manifest"]["profile_id"],
            "srwz-ui-p7-embedded-font-groups-integrated-v1",
        )
        self.assertEqual(extension["promotion_manifest"]["scene_count"], 5)
        self.assertEqual(extension["promotion_manifest"]["entry_count"], 93)
        self.assertEqual(
            {
                scene["scene_id"]: scene["entry_count"]
                for scene in extension["scenes"]
            },
            {
                "tutorial/unit-stat-and-terrain-legend": 20,
                "opening/default-protagonist-labels": 3,
                "formation/squad-and-reboard-confirmations": 10,
                "information/tactical-status-metrics": 14,
                "battle/end-phase-map-command-tail": 6,
                "battle/action-restriction-messages": 10,
                "system/quick-command-save-and-cancel-confirmations": 5,
                "battle/repair-resupply-spirit-targeting": 17,
                "deployment/squad-selection-and-size-format": 16,
                "options/bgm-controller-and-map-settings": 29,
                "results/settlement-and-support-setup": 5,
                "formation/list-search-and-priority": 33,
                "upgrade/full-upgrade-reward": 17,
                "archive/scenario-progress-and-route-headings": 9,
                "formation/terrain-variant-selector": 10,
                "battle/weapon-selection-and-use-conditions": 22,
                "information/reboard-and-option-subpages": 12,
                "parts/equipment-and-predeployment-actions": 15,
            },
        )
        self.assertEqual(
            database_extension["selection_id"],
            "srwz-ui-database-fixed-core-v1",
        )
        self.assertEqual(database_extension["scene_count"], 4)
        self.assertEqual(database_extension["promoted_entry_count"], 402)
        self.assertEqual(database_extension["remaining_entry_count"], 848)
        self.assertEqual(
            {
                scene["scene_id"]: scene["entry_count"]
                for scene in database_extension["scenes"]
            },
            {
                "database/pilot-skills-core": 88,
                "database/unit-special-abilities-core": 155,
                "database/spirit-commands-core": 144,
                "database/leadership-effects-core": 15,
            },
        )
        self.assertEqual(subset_extension["scene_count"], 2)
        self.assertEqual(subset_extension["promoted_entry_count"], 9)
        self.assertEqual(
            subset_extension["promotion_manifest"]["profile_id"],
            "srwz-ui-p9-mixed-user-facing-subset-integrated-v1",
        )
        self.assertEqual(
            {
                scene["scene_id"]: {
                    "source_scene_id": scene["source_scene_id"],
                    "entry_count": scene["entry_count"],
                    "writeback_readiness": scene[
                        "writeback_readiness"
                    ],
                }
                for scene in subset_extension["scenes"]
            },
            {
                "preparation/reboard-status-visible-subset": {
                    "source_scene_id": (
                        "preparation/"
                        "reboard-status-and-internal-warnings"
                    ),
                    "entry_count": 5,
                    "writeback_readiness": (
                        "entry_subset_fixed_span_ready"
                    ),
                },
                "information/pilot-ability-visible-subset": {
                    "source_scene_id": (
                        "information/"
                        "pilot-ability-format-and-control-fragments"
                    ),
                    "entry_count": 4,
                    "writeback_readiness": (
                        "entry_subset_fixed_span_ready"
                    ),
                },
            },
        )
        for case_id, artifact_id in {
            "fresh-boot/tutorial-unit-stat-terrain": (
                "first-five-noncompdata-ui"
            ),
            "fresh-boot/default-protagonist-labels": (
                "ui-p1-opening-names-maximum"
            ),
        }.items():
            case = self.cases[case_id]
            self.assertEqual(case["fixture_id"], "fresh-boot")
            self.assertEqual(
                case["artifact_id"],
                artifact_id,
            )
        for case_id in (
            "intermission/squad-reboard-confirmations",
            "information/tactical-status-metrics",
        ):
            case = self.cases[case_id]
            self.assertEqual(case["fixture_id"], "first-intermission-card")
            self.assertEqual(
                case["artifact_id"],
                "first-five-noncompdata-ui",
            )
        for case_id in (
            "battle/end-phase-map-command-tail",
            "battle/action-restriction-messages",
            "system/quick-command-save-and-cancel-confirmations",
            "battle/repair-resupply-spirit-targeting",
        ):
            case = self.cases[case_id]
            self.assertEqual(case["fixture_id"], "first-battle-card")
            self.assertEqual(
                case["artifact_id"],
                "first-five-noncompdata-ui",
            )
        deployment = self.cases["deployment/squad-selection-and-size-format"]
        self.assertEqual(deployment["fixture_id"], "pre-results-card")
        self.assertEqual(
            deployment["artifact_id"],
            "first-five-noncompdata-ui",
        )
        for case_id in (
            "formation/terrain-variant-selector",
            "information/reboard-and-option-subpages",
            "parts/equipment-and-predeployment-actions",
        ):
            case = self.cases[case_id]
            self.assertEqual(case["fixture_id"], "first-intermission-card")
            self.assertEqual(
                case["artifact_id"],
                "first-five-noncompdata-ui",
            )
        weapon = self.cases[
            "battle/weapon-selection-and-use-conditions"
        ]
        self.assertEqual(weapon["fixture_id"], "first-battle-card")
        self.assertEqual(
            weapon["artifact_id"],
            "first-five-noncompdata-ui",
        )
        for case_id, screenshot_count in {
            "database/pilot-skills-core": 3,
            "database/unit-special-abilities-core": 2,
            "database/spirit-commands-core": 3,
            "database/leadership-effects-core": 2,
        }.items():
            case = self.cases[case_id]
            self.assertEqual(case["priority"], "P1")
            self.assertEqual(
                case["fixture_id"],
                "first-intermission-card",
            )
            expected_artifact = (
                "first-five-full-ui-with-compdata"
                if case_id
                in {
                    "database/unit-special-abilities-core",
                    "database/leadership-effects-core",
                }
                else "first-five-noncompdata-ui"
            )
            self.assertEqual(case["artifact_id"], expected_artifact)
            self.assertEqual(
                len(case["capture_points"]),
                screenshot_count,
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
                2: 421,
                4: 2292,
                5: 3634,
                6: 2083,
                7: 1262,
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
        self.assertEqual(len(memory_cards), 7)
        for fixture in memory_cards:
            self.assertEqual(fixture["status"], "not_acquired")
            self.assertIsNone(fixture["sha256"])
            self.assertTrue(fixture["workspace_path"].endswith(".ps2"))
            self.assertNotIn(".p2s", fixture["workspace_path"])
        self.assertEqual(
            self.manifest["summary"]["route_ready_case_count"],
            6,
        )
        self.assertEqual(
            self.manifest["summary"]["missing_fixture_case_count"],
            35,
        )
        self.assertEqual(
            self.manifest["summary"][
                "artifact_runtime_blocked_case_count"
            ],
            5,
        )

    def test_tsv_is_one_bounded_row_per_case(self):
        stream = io.StringIO()
        write_runtime_matrix_tsv(self.report, stream)
        rows = stream.getvalue().splitlines()
        self.assertEqual(len(rows), 47)
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

    def test_scene_extension_hash_drift_fails_closed(self):
        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "scene extension embedded-ui-promoted-p8 manifest SHA-256 drift",
        ):
            self._audit_mutation(
                lambda document: document["scene_extensions"][0].update(
                    {"manifest_sha256": "0" * 64}
                )
            )

    def test_scene_extension_promotion_hash_drift_fails_closed(self):
        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "promotion manifest SHA-256 drift",
        ):
            self._audit_mutation(
                lambda document: document["scene_extensions"][0][
                    "promotion_manifest"
                ].update({"sha256": "0" * 64})
            )

    def test_scene_extension_fixture_drift_fails_closed(self):
        def mutate(document):
            case = next(
                case
                for case in document["cases"]
                if case["case_id"] == "fresh-boot/tutorial-unit-stat-terrain"
            )
            case["fixture_id"] = "first-intermission-card"

        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "fixture does not match scene",
        ):
            self._audit_mutation(mutate)

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

    def test_passed_case_without_committed_receipt_fails_closed(self):
        def mutate(document):
            case = next(
                case
                for case in document["cases"]
                if case["case_id"] == "core/title-main-menu"
            )
            case["runtime_status"] = "passed"

        with self.assertRaisesRegex(
            UiRuntimeMatrixError,
            "needs runtime_evidence",
        ):
            self._audit_mutation(mutate)

    def test_plan_hash_excludes_only_runtime_result_state(self):
        document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        changed_status = copy.deepcopy(document)
        changed_status["cases"][0]["runtime_status"] = "passed"
        changed_status["cases"][0]["runtime_evidence"] = {
            "manifest": "manifests/runtime/ui-cases/fixture.json",
            "sha256": "0" * 64,
        }
        self.assertEqual(
            _matrix_plan_sha256(document),
            _matrix_plan_sha256(changed_status),
        )

        changed_route = copy.deepcopy(document)
        changed_route["cases"][0]["route"][0] += " changed"
        self.assertNotEqual(
            _matrix_plan_sha256(document),
            _matrix_plan_sha256(changed_route),
        )


if __name__ == "__main__":
    unittest.main()
