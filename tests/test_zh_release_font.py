import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.srwz.release_font import (
    ReleaseFontError,
    audit_frozen_formation_compatibility_assignments,
    audit_legacy_formation_glyph_compatibility,
    audit_runtime_generated_glyph_compatibility,
    audit_sound_select_title_glyph_compatibility,
    load_frozen_formation_compatibility,
    selected_translation_tree_entries,
)
from tools.srwz.text import load_text_table


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
        cls.formation_freeze = json.loads(
            (
                PROJECT_ROOT
                / "config/encoding/zh-release-formation-compatibility-freeze.json"
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
            snapshot = json.loads(json.dumps(self.snapshot))
            candidate = snapshot["remaining_allocation_candidates"][0]
            snapshot["remaining_allocation_candidates"] = [
                candidate
            ]
            snapshot["remaining_allocation_candidate_count"] = 1
            snapshot["remaining_allocation_candidates_sha256"] = hashlib.sha256(
                json.dumps(
                    snapshot["remaining_allocation_candidates"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            profile = json.loads(json.dumps(self.profile))
            profile["translation_tree_selection"]["root"] = str(
                corpus.relative_to(PROJECT_ROOT)
            )
            profile["translation_tree_selection"].pop("exclude_globs", None)
            profile["translation_tree_selection"].pop("exclude_reason", None)
            profile["allocation_snapshot"]["path"] = str(
                snapshot_path.relative_to(PROJECT_ROOT)
            )
            profile["allocation_snapshot"]["sha256"] = hashlib.sha256(
                snapshot_path.read_bytes()
            ).hexdigest()
            profile["expected"]["remaining_candidate_slot_count"] = 1
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

    def test_legacy_name_audit_rejects_reassigned_original_code(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["source_compatibility_assignments"] = [
            row
            for row in snapshot["source_compatibility_assignments"]
            if row["character"] != "の"
        ]
        snapshot["primary_assignments"].append(
            {
                "character": "鶫",
                "code": "82CC",
                "glyph_index": 332,
                "mapping": "reclaimed_unused_original_double_byte",
                "source_character": "の",
            }
        )
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        with self.assertRaisesRegex(
            ReleaseFontError,
            "legacy formation compatibility",
        ):
            audit_legacy_formation_glyph_compatibility(
                snapshot,
                table,
                project_root=PROJECT_ROOT,
            )

    def test_runtime_generated_glyph_audit_rejects_reclaimed_output(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["primary_assignments"] = [
            row
            for row in snapshot["primary_assignments"]
            if row["character"] != "冴"
        ]
        snapshot["primary_assignments"].append(
            {
                "character": "冴",
                "code": "8151",
                "glyph_index": 17,
                "mapping": "reclaimed_unused_original_double_byte",
                "source_character": "＿",
            }
        )
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        with self.assertRaisesRegex(
            ReleaseFontError,
            "runtime-generated glyph compatibility",
        ):
            audit_runtime_generated_glyph_compatibility(
                snapshot,
                table,
                project_root=PROJECT_ROOT,
            )

    def test_runtime_generated_glyph_audit_rejects_literal_wrapper_collision(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["primary_assignments"].append(
            {
                "character": "寺",
                "code": "8175",
                "glyph_index": 53,
                "mapping": "reclaimed_unused_original_double_byte",
                "source_character": "「",
            }
        )
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        with self.assertRaisesRegex(
            ReleaseFontError,
            "runtime-generated glyph compatibility",
        ):
            audit_runtime_generated_glyph_compatibility(
                snapshot,
                table,
                project_root=PROJECT_ROOT,
            )

    def test_every_formation_compatibility_encoding_change_is_current(self):
        contract = next(
            item["legacy_save_formation_compatibility"]
            for item in self.snapshot["extensions"]
            if "legacy_save_formation_compatibility" in item
        )
        primary_by_character = {
            item["character"]: item
            for item in self.snapshot["primary_assignments"]
        }
        aliases_by_character = {
            item["character"]: item
            for item in self.snapshot["surface_alias_assignments"]
        }
        stored_code_by_character = {
            **{
                character: item["code"]
                for character, item in primary_by_character.items()
            },
            **{
                character: item["code"]
                for character, item in aliases_by_character.items()
            },
        }
        active_by_code = {
            item["code"]: item["character"]
            for item in (
                *self.snapshot["primary_assignments"],
                *self.snapshot["surface_alias_assignments"],
                *self.snapshot["source_compatibility_assignments"],
            )
        }
        compatibility_by_character = {
            item["character"]: item
            for item in self.snapshot["source_compatibility_assignments"]
        }

        self.assertEqual(len(contract["relocations"]), 30)
        self.assertEqual(len(contract["retired_aliases"]), 27)
        self.assertEqual(
            len(
                {
                    item["character"]
                    for item in (
                        *contract["relocations"],
                        *contract["retired_aliases"],
                    )
                }
            ),
            57,
        )
        for relocation in contract["relocations"]:
            character = relocation["character"]
            self.assertEqual(
                stored_code_by_character[character],
                relocation["to_code"],
            )
            self.assertNotEqual(
                active_by_code.get(relocation["from_code"]),
                character,
            )
        for retired in contract["retired_aliases"]:
            character = retired["character"]
            self.assertNotIn(character, aliases_by_character)
            self.assertNotEqual(
                active_by_code.get(retired["from_code"]),
                character,
            )

        self.assertEqual(primary_by_character["边"]["code"], "8843")
        self.assertEqual(
            compatibility_by_character["傭"]["code"],
            "9762",
        )
        self.assertEqual(active_by_code["9762"], "傭")

    def test_all_formation_affected_characters_are_explicitly_frozen(self):
        report = load_frozen_formation_compatibility(
            PROJECT_ROOT,
            self.profile,
            self.snapshot,
        )
        self.assertEqual(report["status"], "reviewed_locked")
        self.assertEqual(report["update_policy"], "explicit_refreeze_only")
        self.assertEqual(report["relocation_count"], 30)
        self.assertEqual(report["retired_alias_count"], 27)
        self.assertEqual(report["affected_character_count"], 57)
        self.assertEqual(report["current_primary_assignment_count"], 54)
        self.assertEqual(
            report["current_surface_alias_assignment_count"],
            3,
        )
        self.assertEqual(
            report["frozen_mapping_sha256"],
            "9530a4bbef6fc040092d0102a7b93019c46e83dcc4fea7be50daec2e1d6f3833",
        )
        self.assertTrue(report["all_affected_character_assignments_frozen"])
        self.assertTrue(report["all_vacated_codes_frozen"])
        current_audit = self.formation_freeze["current_translation_audit"]
        self.assertEqual(current_audit["positive_demand_character_count"], 54)
        self.assertEqual(current_audit["zero_demand_characters"], "ビラン")
        self.assertEqual(current_audit["total_occurrence_count"], 108724)

    def test_formation_freeze_rejects_current_glyph_drift(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        edge = next(
            row
            for row in snapshot["primary_assignments"]
            if row["character"] == "边"
        )
        edge["glyph_index"] += 1
        with self.assertRaisesRegex(
            ReleaseFontError,
            "frozen formation affected-character mapping drift",
        ):
            audit_frozen_formation_compatibility_assignments(
                snapshot,
                self.formation_freeze,
            )

    def test_flat_snapshot_preserves_history_and_adds_global_corpora(self):
        self.assertEqual(self.snapshot["primary_assignment_count"], 3424)
        self.assertEqual(
            self.snapshot["surface_alias_assignment_count"], 604
        )
        self.assertEqual(
            self.snapshot["remaining_allocation_candidate_count"], 178
        )
        compatibility = self.snapshot["source_compatibility_assignments"]
        compatibility_by_character = {
            item["character"]: item for item in compatibility
        }
        self.assertEqual(
            set(compatibility_by_character),
            set("いの乗備傭働別動姫撃敵無獣異砂級組総艦衛親話請議負賢軍連鉄銀陽隊頭飛鳥黒陆"),
        )
        legacy_codes = {
            "い": "82A2",
            "の": "82CC",
            "黒": "8D95",
            "乗": "8FE6",
            "組": "9167",
            "隊": "91E0",
            "働": "93AD",
            "飛": "94F2",
            "別": "95CA",
        }
        for character, code in legacy_codes.items():
            row = compatibility_by_character[character]
            self.assertEqual(row["code"], code)
            self.assertEqual(row["source_character"], character)
            self.assertEqual(
                row["mapping"],
                "legacy_save_formation_source_compatibility",
            )
        self.assertEqual(
            compatibility_by_character["陆"]["source_character"], "陸"
        )
        by_character = {
            item["character"]: item
            for item in self.snapshot["primary_assignments"]
        }
        self.assertEqual(by_character["锵"]["code"], "986E")
        self.assertEqual(by_character["锵"]["glyph_index"], 4462)
        self.assertEqual(by_character["倩"]["code"], "82DA")
        self.assertEqual(by_character["倩"]["glyph_index"], 346)
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
        self.assertTrue(set("储剂椅潘罐贱蹄Σ妲浏珀碌裘蔷蹴邓") <= assigned)
        self.assertEqual(by_character["邓"]["code"], "90EF")
        self.assertEqual(by_character["邓"]["glyph_index"], 3055)
        self.assertNotIn(
            "オ",
            {
                item["character"]
                for item in self.snapshot["surface_alias_assignments"]
            },
        )
        reclamation = next(
            item["reclamation"]
            for item in self.snapshot["extensions"]
            if "reclamation" in item
        )
        self.assertEqual(reclamation["retired_alias_character"], "オ")
        self.assertEqual(reclamation["retired_alias_demand_count"], 0)
        active_rows = {
            item["character"]: item
            for item in (
                *self.snapshot["primary_assignments"],
                *self.snapshot["surface_alias_assignments"],
            )
        }
        self.assertEqual(
            {
                character: active_rows[character]["code"]
                for character in "耕鶫蟑呣噪箔“哄涂冴呓寺屐"
            },
            {
                "耕": "82D3",
                "鶫": "82D4",
                "蟑": "90F0",
                "呣": "90F1",
                "噪": "90FC",
                "箔": "9140",
                "“": "9141",
                "哄": "9142",
                "涂": "9143",
                "冴": "96FD",
                "呓": "97FD",
                "寺": "9579",
                "屐": "92C5",
            },
        )
        self.assertTrue(
            set("コスセツトドハ").isdisjoint(
                {
                    item["character"]
                    for item in self.snapshot[
                        "surface_alias_assignments"
                    ]
                }
            )
        )
        legacy = next(
            item["legacy_save_formation_compatibility"]
            for item in self.snapshot["extensions"]
            if "legacy_save_formation_compatibility" in item
        )
        table = load_text_table(
            PROJECT_ROOT
            / "vendor/upstream-python/project/tbl_all.json"
        )
        legacy_audit = audit_legacy_formation_glyph_compatibility(
            self.snapshot,
            table,
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(legacy_audit["observed_name_count"], 251)
        self.assertEqual(legacy_audit["observed_character_count"], 199)
        self.assertEqual(legacy_audit["protected_original_code_count"], 199)
        self.assertEqual(
            len(set(legacy_audit["protected_original_codes"])),
            199,
        )
        self.assertEqual(
            legacy_audit["source_inventory"]["source_count"],
            248,
        )
        self.assertTrue(
            legacy_audit["all_observed_original_codes_preserved"]
        )
        runtime_audit = audit_runtime_generated_glyph_compatibility(
            self.snapshot,
            table,
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(
            runtime_audit["protected_original_codes"],
            ["8144", "8151", "815D", "8175", "8176", "817D"],
        )
        self.assertEqual(
            runtime_audit["protected_source_characters"],
            "．＿‐「」±",
        )
        self.assertEqual(runtime_audit["literal_output_count"], 3)
        self.assertEqual(
            next(
                row
                for row in self.snapshot["primary_assignments"]
                if row["character"] == "屯"
            )["code"],
            "91E9",
        )
        runtime_contract = next(
            extension["runtime_generated_glyph_compatibility"]
            for extension in self.snapshot["extensions"]
            if "runtime_generated_glyph_compatibility" in extension
        )
        frozen_characters = {
            row["character"]
            for row in (
                *self.formation_freeze["relocations"],
                *self.formation_freeze["retired_aliases"],
            )
        }
        self.assertTrue(
            {
                row["reused_alias_character"]
                for row in runtime_contract["relocations"]
                if "reused_alias_character" in row
            }.isdisjoint(frozen_characters)
        )
        self.assertTrue(
            runtime_audit[
                "all_runtime_generated_original_codes_preserved"
            ]
        )
        sound_audit = audit_sound_select_title_glyph_compatibility(
            self.snapshot,
            table,
            project_root=PROJECT_ROOT,
        )
        self.assertEqual(sound_audit["track_title_count"], 101)
        self.assertEqual(sound_audit["unique_two_byte_code_count"], 252)
        self.assertEqual(len(sound_audit["relocations"]), 59)
        self.assertEqual(sound_audit["retired_alias_count"], 59)
        self.assertEqual(sound_audit["collision_count"], 0)
        self.assertEqual(sound_audit["reclaimable_output_count"], 0)
        self.assertTrue(
            sound_audit[
                "all_sound_select_title_codes_resolve_original_characters"
            ]
        )
        active_codes = {
            item["code"]
            for item in (
                *self.snapshot["primary_assignments"],
                *self.snapshot["surface_alias_assignments"],
                *self.snapshot["source_compatibility_assignments"],
            )
        }
        literal_codes = {
            item["code"] for item in runtime_audit["literal_output_evidence"]
        }
        self.assertTrue(literal_codes.isdisjoint(active_codes))

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
            any(
                0x8140 <= int(item["code"], 16) < 0x889F
                for item in self.snapshot[
                    "remaining_allocation_candidates"
                ]
            )
        )
        self.assertEqual(
            self.snapshot["candidate_pool"],
            {
                "mode": "all_unoccupied_renderer_standard_double_byte_slots",
                "includes_retired_japanese_positions": True,
                "includes_conditional_width_positions": True,
                "candidate_count": 418,
            },
        )

    def test_sound_select_title_glyph_audit_rejects_reclaimed_code(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        protected = next(
            extension["sound_select_title_glyph_compatibility"]
            for extension in snapshot["extensions"]
            if "sound_select_title_glyph_compatibility" in extension
        )["protected_codes"]
        code = protected[0]
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        snapshot["remaining_allocation_candidates"].append({
            "code": code,
            "glyph_index": 0,
            "source_character": table.characters[int(code, 16)],
        })
        with self.assertRaisesRegex(
            ReleaseFontError,
            "sound-select title glyph compatibility",
        ):
            audit_sound_select_title_glyph_compatibility(
                snapshot,
                table,
                project_root=PROJECT_ROOT,
            )

    def test_every_translation_tree_entry_is_covered(self):
        selection = self.manifest["inputs"]["translation_selection"]
        self.assertEqual(selection["unique_entry_count"], 125989)
        source_paths = {item["path"] for item in selection["sources"]}
        self.assertIn("corpus/zh/battle/srvc-lines.json", source_paths)
        self.assertIn("corpus/zh/menu/battle-lines.json", source_paths)
        self.assertIn("corpus/zh/menu/system-ui-parts.json", source_paths)
        self.assertIn("corpus/zh/menu/stage-overviews.json", source_paths)
        self.assertIn("corpus/zh/library/v0.2-reviewed.json", source_paths)
        excluded = {item["path"] for item in selection["excluded_sources"]}
        self.assertEqual(
            excluded,
            {
                "corpus/zh/ui-atlas/bazaar-v2.json",
                "corpus/zh/ui-atlas/core-menus-v1.json",
                "corpus/zh/ui-atlas/info-v1.json",
                "corpus/zh/ui-atlas/stage-clear-v1.json",
                "corpus/zh/ui-atlas/world-map-titles-v1.json",
            },
        )
        self.assertTrue(excluded.isdisjoint(source_paths))
        self.assertEqual(selection["exclude_globs"], ["ui-atlas/*.json"])
        self.assertIn("pre-rendered", selection["exclude_reason"])
        coverage = self.manifest["coverage"]
        self.assertEqual(coverage["missing_character_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            coverage["original_font_visible_character_count"], 0
        )
        self.assertEqual(
            coverage["preserved_raw_ascii_punctuation_characters"],
            '"%&\'+,-./:<=>@[\\]~',
        )
        control_tokens = selection["control_tokens"]
        self.assertEqual(control_tokens["entry_count"], 2149)
        self.assertEqual(control_tokens["occurrence_count"], 2263)
        self.assertEqual(
            control_tokens["kinds"]["runtime_format"]["forms"],
            {"%s": 59},
        )
        self.assertEqual(
            control_tokens["kinds"]["runtime_substitution"][
                "occurrence_count"
            ],
            2086,
        )
        self.assertEqual(
            {
                key: value
                for key, value in control_tokens["kinds"][
                    "runtime_substitution"
                ]["forms"].items()
                if key.startswith("<")
            },
            {"<0>": 3, "<6>": 1, "<8>": 1, "<9>": 1},
        )
        self.assertEqual(
            control_tokens["kinds"]["text_tag"]["occurrence_count"], 118
        )
        self.assertTrue(control_tokens["excluded_from_font_glyph_demand"])
        self.assertEqual(
            selection["literal_percent_signs"]["occurrence_count"], 185
        )
        self.assertEqual(
            coverage["control_token_occurrence_count"], 2263
        )
        self.assertEqual(
            coverage["runtime_placeholder_occurrence_count"], 2145
        )
        self.assertTrue(coverage["runtime_placeholder_bytes_preserved_exactly"])
        self.assertEqual(coverage["literal_percent_occurrence_count"], 185)

    def test_snapshot_updater_appends_without_reordering_existing_rows(self):
        updated = self._run_snapshot_updater("龘")
        self.assertEqual(
            updated["primary_assignments"][:-1],
            self.snapshot["primary_assignments"],
        )
        self.assertEqual(
            updated["primary_assignments"][-1]["character"], "龘"
        )
        self.assertEqual(
            updated["primary_assignments"][-1]["code"],
            self.snapshot["remaining_allocation_candidates"][0]["code"],
        )
        self.assertEqual(
            updated["remaining_allocation_candidate_count"], 0
        )

    def test_snapshot_updater_allocates_when_original_slot_is_already_reclaimed(self):
        updated = self._run_snapshot_updater("☆")
        assignment = updated["primary_assignments"][-1]
        self.assertEqual(assignment["character"], "☆")
        self.assertEqual(
            assignment["code"],
            self.snapshot["remaining_allocation_candidates"][0]["code"],
        )
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
            profile["translation_tree_selection"].pop("exclude_globs", None)
            profile["translation_tree_selection"].pop("exclude_reason", None)

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
