import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.srwz.release_font import selected_translation_tree_entries


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ZhReleaseFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain = json.loads(
            (PROJECT_ROOT / "config/fonts/zh-font-build-chain.json").read_text(
                encoding="utf-8"
            )
        )
        cls.profile = json.loads(
            (PROJECT_ROOT / "config/fonts/zh-release-font.json").read_text(
                encoding="utf-8"
            )
        )
        cls.snapshot = json.loads(
            (
                PROJECT_ROOT
                / "config/encoding/zh-release-font-assignments.json"
            ).read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            (
                PROJECT_ROOT / "manifests/zh-release-font-validation.json"
            ).read_text(encoding="utf-8")
        )

    def _run_snapshot_updater(self, character):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            root = Path(temporary)
            corpus = root / "corpus"
            corpus.mkdir()
            (corpus / "battle.json").write_text(
                json.dumps(
                    {"entries": [{"translation": character}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(
                json.dumps(self.snapshot, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            profile = json.loads(json.dumps(self.profile))
            profile["translation_tree_selection"]["root"] = str(
                corpus.relative_to(PROJECT_ROOT)
            )
            profile["allocation_snapshot"]["path"] = str(
                snapshot_path.relative_to(PROJECT_ROOT)
            )
            profile["allocation_snapshot"]["sha256"] = hashlib.sha256(
                snapshot_path.read_bytes()
            ).hexdigest()
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    "tools/update_zh_release_font_snapshot.py",
                    "--config",
                    str(profile_path),
                    "--apply",
                ],
                cwd=PROJECT_ROOT,
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )
            return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def test_active_chain_has_only_base_and_release_profiles(self):
        self.assertEqual(
            self.chain["base_profile"],
            "config/fonts/zh-font-base.json",
        )
        self.assertEqual(
            self.chain["release_profile"],
            "config/fonts/zh-release-font.json",
        )
        self.assertNotIn("profile_chain", self.chain)
        self.assertNotIn("historical_profiles", self.chain)

    def test_flat_snapshot_preserves_history_and_adds_global_corpora(self):
        self.assertEqual(self.snapshot["primary_assignment_count"], 3261)
        self.assertEqual(
            self.snapshot["surface_alias_assignment_count"], 701
        )
        self.assertEqual(
            self.snapshot["remaining_allocation_candidate_count"], 1
        )
        compatibility = self.snapshot["source_compatibility_assignments"]
        self.assertEqual(
            compatibility,
            [
                {
                    "character": "陆",
                    "code": "97A4",
                    "glyph_index": 4324,
                    "mapping": "raw_source_character_simplification",
                    "source_character": "陸",
                    "reason": (
                        "Preserve original structural runtime fields that "
                        "still encode the stock Japanese character 陸 while "
                        "rendering the localized simplified form 陆."
                    ),
                }
            ],
        )
        by_character = {
            item["character"]: item
            for item in self.snapshot["primary_assignments"]
        }
        self.assertEqual(by_character["锵"]["code"], "986E")
        self.assertEqual(by_character["锵"]["glyph_index"], 4462)
        migration = self.snapshot["migration"]
        self.assertFalse(migration["active_build_dependency"])
        self.assertEqual(
            migration["preserved_historical_primary_assignment_count"],
            3158,
        )
        self.assertEqual(migration["added_global_assignment_count"], 19)
        assigned = {
            item["character"]
            for item in self.snapshot["primary_assignments"]
        }
        self.assertTrue(set("储剂椅潘罐贱蹄Σ妲浏珀") <= assigned)
        assigned_codes = {
            item["code"]
            for item in (
                *self.snapshot["primary_assignments"],
                *self.snapshot["surface_alias_assignments"],
            )
        }
        assigned_glyphs = {
            item["glyph_index"]
            for item in (
                *self.snapshot["primary_assignments"],
                *self.snapshot["surface_alias_assignments"],
            )
        }
        self.assertTrue(
            all(
                item["code"] not in assigned_codes
                and item["glyph_index"] not in assigned_glyphs
                for item in self.snapshot[
                    "remaining_allocation_candidates"
                ]
            )
        )
        self.assertTrue(
            all(
                not 0x8140 <= int(item["code"], 16) < 0x889F
                for item in self.snapshot[
                    "remaining_allocation_candidates"
                ]
            )
        )

    def test_every_translation_tree_entry_is_covered(self):
        selection = self.manifest["inputs"]["translation_selection"]
        self.assertEqual(selection["unique_entry_count"], 120660)
        source_paths = {item["path"] for item in selection["sources"]}
        self.assertIn("corpus/zh/battle/srvc-lines.json", source_paths)
        self.assertIn("corpus/zh/menu/battle-lines.json", source_paths)
        self.assertIn("corpus/zh/menu/system-ui-parts.json", source_paths)
        self.assertIn("corpus/zh/menu/stage-overviews.json", source_paths)
        coverage = self.manifest["coverage"]
        self.assertEqual(coverage["missing_character_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            coverage["original_font_visible_character_count"], 0
        )
        self.assertEqual(
            coverage["preserved_raw_ascii_punctuation_characters"],
            '"%&\',-./:<=\\]{}~',
        )
        control_tokens = selection["control_tokens"]
        self.assertEqual(control_tokens["entry_count"], 2085)
        self.assertEqual(control_tokens["occurrence_count"], 2130)
        self.assertEqual(
            control_tokens["kinds"]["runtime_format"]["forms"],
            {"%s": 51},
        )
        self.assertEqual(
            control_tokens["kinds"]["runtime_substitution"][
                "occurrence_count"
            ],
            2054,
        )
        self.assertEqual(
            control_tokens["kinds"]["text_tag"]["occurrence_count"], 25
        )
        self.assertTrue(control_tokens["excluded_from_font_glyph_demand"])
        self.assertEqual(
            selection["literal_percent_signs"]["occurrence_count"], 150
        )
        self.assertEqual(
            coverage["control_token_occurrence_count"], 2130
        )
        self.assertEqual(
            coverage["runtime_placeholder_occurrence_count"], 2105
        )
        self.assertTrue(coverage["runtime_placeholder_bytes_preserved_exactly"])
        self.assertEqual(coverage["literal_percent_occurrence_count"], 150)

    def test_snapshot_updater_appends_without_reordering_existing_rows(self):
        updated = self._run_snapshot_updater("龘")
        self.assertEqual(
            updated["primary_assignments"][:-1],
            self.snapshot["primary_assignments"],
        )
        self.assertEqual(
            updated["primary_assignments"][-1]["character"], "龘"
        )
        self.assertFalse(
            0x8140
            <= int(updated["primary_assignments"][-1]["code"], 16)
            < 0x889F
        )
        self.assertEqual(
            updated["remaining_allocation_candidate_count"], 0
        )

    def test_snapshot_updater_reroutes_original_single_mode_character(self):
        updated = self._run_snapshot_updater("☆")
        assignment = updated["primary_assignments"][-1]
        self.assertEqual(assignment["character"], "☆")
        self.assertNotEqual(assignment["code"], "8199")
        self.assertFalse(0x8140 <= int(assignment["code"], 16) < 0x889F)
        self.assertEqual(
            updated["remaining_allocation_candidate_count"], 0
        )

    def test_translation_tree_includes_registered_translation_maps(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            root = Path(temporary)
            (root / "mapped.json").write_text(
                json.dumps(
                    {
                        "editorial_status": "reviewed",
                        "compdata_direct_by_offset": {
                            "0x10": "映射译文",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            profile = json.loads(json.dumps(self.profile))
            profile["translation_tree_selection"]["root"] = str(
                root.relative_to(PROJECT_ROOT)
            )

            entries, _scenes, selection = (
                selected_translation_tree_entries(PROJECT_ROOT, profile)
            )

            self.assertEqual(len(entries), 1)
            self.assertEqual(
                next(iter(entries.values()))["translation"], "映射译文"
            )
            self.assertEqual(
                selection["map_fields"],
                profile["translation_tree_selection"]["map_fields"],
            )


if __name__ == "__main__":
    unittest.main()
