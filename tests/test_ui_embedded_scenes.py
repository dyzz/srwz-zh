import json
import unittest
from pathlib import Path

from tools.srwz.ui_embedded_scenes import (
    audit_ui_embedded_scenes,
    build_embedded_scene_manifest,
    load_embedded_scene_config,
)
from tools.srwz.ui_inventory import (
    expand_scene_entries,
    expand_selector,
    load_scene_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-embedded-scenes.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-embedded-scene-map.json"


class UiEmbeddedSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_embedded_scene_config(CONFIG_PATH)
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_groups_exactly_partition_deferred_aggregate(self):
        inventory = load_scene_config(
            PROJECT_ROOT / self.config["aggregate_scene"]["inventory"]
        )
        aggregate = next(
            scene
            for scene in inventory["scenes"]
            if scene["scene_id"] == self.config["aggregate_scene"]["scene_id"]
        )
        aggregate_ids = {
            entry["id"] for entry in expand_scene_entries(PROJECT_ROOT, aggregate)
        }
        grouped_ids = set()
        for group in self.config["groups"]:
            ids = {
                entry["id"]
                for entry in expand_selector(PROJECT_ROOT, group["selector"])
            }
            self.assertFalse(grouped_ids & ids, group["scene_id"])
            grouped_ids.update(ids)
        self.assertEqual(grouped_ids, aggregate_ids)
        self.assertEqual(len(grouped_ids), 275)

    def test_scene_and_classification_ratchets_are_exact(self):
        summary = self.manifest["summary"]
        self.assertEqual(summary["group_count"], 22)
        self.assertEqual(summary["classified_entry_count"], 275)
        self.assertEqual(summary["unclassified_entry_count"], 0)
        self.assertEqual(summary["overlap_entry_count"], 0)
        self.assertEqual(
            summary["classification_group_counts"],
            {
                "diagnostic_or_format_fragment": 2,
                "mixed_user_and_diagnostic": 2,
                "user_facing_candidate": 18,
            },
        )
        self.assertEqual(
            summary["classification_entry_counts"],
            {
                "diagnostic_or_format_fragment": 5,
                "mixed_user_and_diagnostic": 17,
                "user_facing_candidate": 253,
            },
        )

    def test_every_group_has_a_route_and_capture_contract(self):
        for group in self.config["groups"]:
            with self.subTest(scene_id=group["scene_id"]):
                self.assertTrue(group["fixture_id"])
                self.assertGreaterEqual(len(group["route"]), 2)
                self.assertGreaterEqual(len(group["capture_points"]), 1)
                self.assertGreaterEqual(len(group["runtime_assertions"]), 1)

    def test_p2_fixed_span_readiness_is_quantified(self):
        summary = self.manifest["summary"]
        self.assertEqual(
            summary["writeback_readiness_group_counts"],
            {
                "allocation_or_shared_owner_required": 4,
                "fixed_span_ready": 13,
                "font_extension_required": 5,
            },
        )
        self.assertEqual(
            summary["writeback_readiness_entry_counts"],
            {
                "allocation_or_shared_owner_required": 59,
                "fixed_span_ready": 123,
                "font_extension_required": 93,
            },
        )
        self.assertEqual(summary["fixed_span_ready_entry_count"], 123)
        self.assertEqual(
            summary["fixed_span_ready_user_facing_entry_count"],
            101,
        )
        self.assertEqual(summary["font_missing_character_count"], 6)
        self.assertEqual(summary["overflow_entry_count"], 7)
        self.assertNotIn("font_missing_characters", summary)

    def test_fresh_boot_groups_are_fixed_span_ready(self):
        groups = {group["scene_id"]: group for group in self.manifest["groups"]}
        for scene_id in (
            "tutorial/unit-stat-and-terrain-legend",
            "opening/default-protagonist-labels",
        ):
            with self.subTest(scene_id=scene_id):
                readiness = groups[scene_id]["writeback_readiness"]
                self.assertEqual(readiness["status"], "fixed_span_ready")
                self.assertEqual(readiness["excluded_entry_count"], 0)
                self.assertEqual(
                    readiness["fixed_selected_entry_count"],
                    groups[scene_id]["entry_count"],
                )

    def test_provenance_ownership_is_hash_locked(self):
        for group in self.manifest["groups"]:
            with self.subTest(scene_id=group["scene_id"]):
                provenance = group["provenance"]
                self.assertGreater(provenance["unique_target_count"], 0)
                self.assertEqual(len(provenance["ownership_sha256"]), 64)
                self.assertEqual(
                    sum(provenance["entry_backing_counts"].values()),
                    group["entry_count"],
                )
                self.assertNotIn("unreferenced", provenance["entry_backing_counts"])

    def test_manifest_contains_no_source_or_translation_text(self):
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
        self.assertEqual(
            self.manifest["content_policy"],
            (
                "Hashes, counts, stable IDs and runtime gates only; no game bytes, "
                "Japanese source text or localized UI strings are embedded."
            ),
        )

    def test_committed_manifest_matches_current_sources(self):
        report = audit_ui_embedded_scenes(PROJECT_ROOT, CONFIG_PATH)
        self.assertEqual(build_embedded_scene_manifest(report), self.manifest)


if __name__ == "__main__":
    unittest.main()
