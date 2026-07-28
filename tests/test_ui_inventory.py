import json
import unittest
from pathlib import Path

from tools.srwz.ui_inventory import (
    build_inventory_manifest,
    decision_is_complete,
    expand_scene_entries,
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
            rendered_characters("第%s话$n@<color:31>陆<width:00>"),
            ("第", "话", "陆"),
        )

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
            "dynamic_sources": [],
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


if __name__ == "__main__":
    unittest.main()
