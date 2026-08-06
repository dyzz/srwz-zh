import json
import unittest
from pathlib import Path

from tools.srwz.ui_inventory import (
    audit_entry_font,
    audit_ui_inventory,
    build_inventory_manifest,
    decision_is_complete,
    expand_scene_entries,
    load_font_baseline,
    load_scene_config,
    rendered_characters,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-scenes.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-surface-inventory.json"


class UiInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_scene_config(CONFIG_PATH)
        cls.scenes = {scene["scene_id"]: scene for scene in cls.config["scenes"]}

    def test_inventory_covers_requested_scene_families(self):
        self.assertEqual(
            {
                "title/main-menu",
                "opening/player-setup",
                "intermission/main-and-options",
                "information/unit-pilot-mech-core",
                "battle/map-and-tactical",
                "results/level-up-and-deployment",
                "search/filter-and-results",
            },
            {
                scene_id
                for scene_id, scene in self.scenes.items()
                if scene["priority"] == "P0"
            },
        )
        self.assertIn("opening/world-history-scroll", self.scenes)
        self.assertIn("story/first-five-opening-sequences", self.scenes)

    def test_p0_entry_ratchet_is_exact(self):
        selected = {}
        for scene in self.config["scenes"]:
            if scene["priority"] != "P0":
                continue
            for entry in expand_scene_entries(PROJECT_ROOT, scene):
                selected.setdefault(entry["id"], entry)
        self.assertEqual(
            len(selected),
            self.config["ratchet"]["p0_unique_entry_count"],
        )
        self.assertEqual(len(selected), 462)
        self.assertTrue(all(decision_is_complete(entry) for entry in selected.values()))

    def test_first_five_story_selector_count_is_exact(self):
        entries = expand_scene_entries(
            PROJECT_ROOT,
            self.scenes["story/first-five-opening-sequences"],
        )
        self.assertEqual(len(entries), 1833)
        self.assertTrue(
            all(
                entry["id"].startswith(
                    (
                        "story/001/",
                        "story/002/",
                        "story/003/",
                        "story/004/",
                        "story/005/",
                    )
                )
                for entry in entries
            )
        )

    def test_unclassified_p0_and_remainder_form_exact_partition(self):
        p0_ids = set()
        for scene in self.config["scenes"]:
            if scene["priority"] != "P0":
                continue
            p0_ids.update(
                entry["id"]
                for entry in expand_scene_entries(PROJECT_ROOT, scene)
                if entry["id"].startswith("menu/SLPS/00/")
            )
        remainder = {
            entry["id"]
            for entry in expand_scene_entries(
                PROJECT_ROOT,
                self.scenes["menus/extended-embedded-dialogs"],
            )
        }
        all_unknown = {
            entry["id"]
            for entry in json.loads(
                (PROJECT_ROOT / "corpus/zh/menu/unclassified.json").read_text(
                    encoding="utf-8"
                )
            )["entries"]
        }
        self.assertFalse(p0_ids & remainder)
        self.assertEqual(p0_ids | remainder, all_unknown)
        self.assertEqual(len(p0_ids), 107)
        self.assertEqual(len(remainder), 275)

    def test_rendered_characters_exclude_runtime_notation(self):
        self.assertEqual(
            rendered_characters(
                "第%s%2$s话$c$f$l$n$F{7F}@<color:31>陆<width:00>"
            ),
            ("第", "话", "陆"),
        )

    def test_font_audit_resolves_printable_ascii_through_ascii_glyphs(self):
        baseline = load_font_baseline(PROJECT_ROOT, self.config)
        report = audit_entry_font(
            [{"id": "fixture/ascii", "translation": "Y"}],
            baseline,
        )
        self.assertEqual(report["missing_character_count"], 0)

    def test_dynamic_probes_store_hashes_not_source_text(self):
        for source in self.config["dynamic_sources"]:
            for probe in source["probes"]:
                self.assertNotIn("source_text", probe)
                self.assertEqual(len(probe["source_text_sha256"]), 64)
                self.assertGreater(probe["encoded_size_with_terminator"], 1)

    def test_manifest_projection_is_bounded(self):
        report = {
            "status": "inventory_passed_work_remaining",
            "inventory_id": "fixture",
            "scope": "fixture",
            "source_corpus": {},
            "font_baseline": {},
            "summary": {},
            "ratchet": {},
            "dynamic_sources": [
                {
                    "source_id": "fixture",
                    "structure_manifest": {
                        "sha256": "structure-hash",
                    },
                    "writer_manifest": {
                        "path": "manifests/downstream.json",
                        "sha256": "downstream-hash",
                        "status": "validated",
                        "selected_translation_entry_count": 1,
                    },
                    "probes": [],
                }
            ],
            "scenes": [
                {
                    "scene_id": "fixture",
                    "priority": "P0",
                    "label": "fixture",
                    "category": "runtime-text-ui",
                    "selected_entry_count": 1,
                    "decision_complete_count": 1,
                    "asset_translation_count": 0,
                    "font": {
                        "missing_character_count": 1,
                        "missing_characters": "源",
                        "missing": [{"character": "源"}],
                    },
                    "assets": [],
                    "implementation": {
                        "text": "pending",
                        "asset": "pending",
                        "integration": "pending",
                    },
                    "runtime_route_step_count": 1,
                    "runtime_assertion_count": 1,
                }
            ],
        }
        manifest = build_inventory_manifest(report)
        scene = manifest["scenes"][0]
        self.assertEqual(scene["missing_renderer_character_count"], 1)
        self.assertNotIn("font", scene)
        self.assertNotIn("missing_characters", scene)
        dynamic = manifest["dynamic_sources"][0]
        self.assertEqual(
            dynamic["structure_manifest"]["sha256"],
            "structure-hash",
        )
        self.assertNotIn("sha256", dynamic["writer_manifest"])
        self.assertEqual(
            dynamic["writer_manifest"]["status"],
            "validated",
        )

    def test_committed_manifest_has_hash_only_dynamic_probes(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            {scene["scene_id"] for scene in manifest["scenes"]},
            set(self.scenes),
        )
        self.assertEqual(
            manifest["summary"]["p0_unique_entry_count"],
            self.config["ratchet"]["p0_unique_entry_count"],
        )
        for source in manifest["dynamic_sources"]:
            for probe in source["probes"]:
                self.assertNotIn("source_text", probe)
                self.assertEqual(len(probe["source_text_sha256"]), 64)
        summary_scene = next(
            scene
            for scene in manifest["scenes"]
            if scene["scene_id"] == "opening/world-history-scroll"
        )
        self.assertEqual(
            summary_scene["layout"]["status"],
            "layout_validated_editorial_font_runtime_pending",
        )
        self.assertEqual(summary_scene["layout"]["entry_count"], 28)
        self.assertEqual(summary_scene["layout"]["maximum_line_width"], 22)
        self.assertEqual(
            summary_scene["layout"]["fixed_allocation_overflow_count"],
            0,
        )
        self.assertEqual(summary_scene["layout"]["font_missing_character_count"], 41)
        self.assertEqual(summary_scene["layout"]["font_candidate_shortfall"], 38)
        self.assertEqual(summary_scene["layout"]["runtime_status"], "not_tested")

    def test_committed_manifest_matches_current_sources(self):
        report = audit_ui_inventory(PROJECT_ROOT, CONFIG_PATH)
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(build_inventory_manifest(report), manifest)

    def test_p0_asset_candidates_are_hash_locked_by_scene(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        scenes = {scene["scene_id"]: scene for scene in manifest["scenes"]}
        expected = {
            "intermission/main-and-options": {
                "manifests/ui-bazaar-atlas-zh-validation.json",
                "manifests/ui-intermission-atlas-zh-validation.json",
                "manifests/ui-formation-atlas-zh-validation.json",
            },
            "information/unit-pilot-mech-core": {
                "manifests/ui-info-atlas-zh-validation.json",
            },
            "battle/map-and-tactical": {
                "manifests/ui-battle-command-atlas-zh-validation.json",
                "manifests/ui-info-atlas-zh-validation.json",
            },
            "results/level-up-and-deployment": {
                "manifests/ui-formation-atlas-zh-validation.json",
            },
            "search/filter-and-results": {
                "manifests/ui-info-atlas-zh-validation.json",
            },
        }
        for scene_id, expected_manifests in expected.items():
            with self.subTest(scene_id=scene_id):
                assets = scenes[scene_id]["assets"]
                self.assertEqual(
                    {asset["manifest"] for asset in assets},
                    expected_manifests,
                )
                self.assertTrue(all(len(asset["sha256"]) == 64 for asset in assets))
                self.assertTrue(
                    all(asset["runtime_status"] == "not_tested" for asset in assets)
                )
                self.assertEqual(
                    scenes[scene_id]["asset_translation_count"],
                    len(expected_manifests),
                )

    def test_dynamic_inventory_tracks_p2_researched_names(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        source = manifest["dynamic_sources"][0]
        self.assertEqual(
            source["writer_manifest"]["selected_translation_entry_count"],
            1307,
        )
        self.assertEqual(
            source["writer_manifest"]["unselected_non_empty_entry_count"],
            1493,
        )


if __name__ == "__main__":
    unittest.main()
