import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/full-story-components-validation.json"
)
CONTENT_MANIFEST = (
    PROJECT_ROOT / "manifests/zh-release-full-story-iso-content-validation.json"
)
REMAINING_UI_CORPUS = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"


class CurrentResidualUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.component = json.loads(
            COMPONENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.content = json.loads(
            CONTENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.remaining_ui = json.loads(
            REMAINING_UI_CORPUS.read_text(encoding="utf-8")
        )

    def test_fixed_slps_and_suspend_return_dialogue_are_locked(self):
        remaining = self.component["remaining_ui"]
        self.assertEqual(remaining["slps_context_ui"]["entry_count"], 407)
        self.assertEqual(remaining["slps"]["entry_count"], 177)

        formation = remaining["stage_default_formation"]
        self.assertEqual(formation["group_count"], 85)
        self.assertEqual(formation["stage_count"], 83)
        self.assertEqual(formation["entry_count"], 2382)
        self.assertEqual(formation["unique_source_count"], 103)
        self.assertEqual(
            formation["layout_group_counts"],
            {"record23+6": 79, "slot32": 6},
        )
        self.assertEqual(formation["record_metadata_count"], 2364)
        self.assertEqual(
            formation["inventory_sha256"],
            "1ede725d2a21c3124da144551f9914a9ddc8375ba235e1b19ea3f37a0a93d4b6",
        )
        translations = {
            item["source"]: item["translation"]
            for item in formation["translations"]
        }
        self.assertEqual(translations["エゥーゴ"], "奥古")
        self.assertEqual(translations["グローリー・スター１"], "荣耀之星1")
        self.assertEqual(translations["ザフト"], "ZAFT")
        self.assertEqual(translations["ザンベース"], "桑贝斯")
        self.assertTrue(formation["fixed_allocations_preserved"])
        self.assertTrue(formation["record_metadata_preserved_byte_exact"])
        self.assertTrue(formation["slot_padding_zero"])
        self.assertTrue(formation["reread_exact"])

        dialogue = remaining["stage_system_dialogue"]
        self.assertEqual(dialogue["selected_entry_count"], 379)
        self.assertEqual(dialogue["inventory_entry_count"], 379)
        self.assertEqual(
            dialogue["selected_pointer_offsets_sha256"],
            "296c64123f0587124a1583935d522f189ba0e9e992feb774ec3e4173b793a058",
        )
        self.assertTrue(dialogue["source_preimages_sha256_exact"])
        self.assertTrue(dialogue["pointer_bytes_unchanged"])
        self.assertTrue(dialogue["reread_exact"])
        self.assertTrue(dialogue["codec_round_trip_exact"])
        self.assertTrue(dialogue["archive_size_preserved"])
        self.assertTrue(dialogue["hb_offsets_preserved"])

    def test_female_default_name_and_back_log_labels_are_locked(self):
        regressions = self.content["compdata"]["new_game_regressions"]
        self.assertEqual(
            regressions["female_default_name_offsets"],
            {
                "0x337728": "节子",
                "0x337730": "小原",
                "0x33B458": "节子",
                "0x33B460": "小原",
                "0x33E318": "节子·小原",
            },
        )
        self.assertTrue(regressions["female_default_name_readback_exact"])

        fixed_slps = self.content["compdata"]["remaining_ui"][
            "slps_context_ui"
        ]
        self.assertTrue(fixed_slps["readback_exact"])
        self.assertEqual(fixed_slps["entry_count"], 407)
        context = self.remaining_ui["slps_context_ui_by_offset"]
        self.assertEqual(
            {offset: context[offset] for offset in (
                "0x33DB92",
                "0x33DBA2",
                "0x33DBB2",
                "0x33DBC2",
                "0x33DBD2",
                "0x33DBE2",
            )},
            {
                "0x33DB92": "上一条",
                "0x33DBA2": "下一条",
                "0x33DBB2": "上一行",
                "0x33DBC2": "下一行",
                "0x33DBD2": "返回",
                "0x33DBE2": "高速）",
            },
        )

    def test_all_discovered_terrain_names_are_reencoded(self):
        terrain = self.component["world_map_titles"]["terrain_names"]
        self.assertEqual(terrain["unique_source_count"], 15)
        self.assertEqual(terrain["occurrence_count"], 66)
        self.assertEqual(terrain["changed_member_count"], 10)
        self.assertTrue(terrain["fixed_decoded_spans_preserved"])
        self.assertTrue(terrain["archive_size_preserved"])
        self.assertTrue(terrain["offset_table_preserved"])
        self.assertTrue(terrain["codec_round_trip_exact"])
        self.assertTrue(terrain["reread_exact"])

    def test_final_iso_contains_no_stale_stage_text_rendered_by_new_font(self):
        story = self.content["stale_stage_runtime_rendering_audit"]
        self.assertEqual(story["checked_entry_count"], 91746)
        self.assertEqual(story["distinct_stale_fingerprint_count"], 90165)
        self.assertEqual(story["stale_fingerprint_match_count"], 0)
        self.assertTrue(
            story["all_distinct_stale_source_renderings_absent"]
        )

        system = self.content["stage_system_dialogue"]
        self.assertEqual(system["record_count"], 379)
        self.assertEqual(system["checked_text_field_count"], 758)
        self.assertEqual(system["distinct_stale_fingerprint_field_count"], 690)
        self.assertEqual(system["stale_fingerprint_match_count"], 0)
        self.assertTrue(system["translated_readback_exact"])

    def test_dynamic_condition_updates_have_no_original_payload_fallback(self):
        audit = self.content["dynamic_condition_update_audit"]
        self.assertEqual(audit["translated_condition_count"], 534)
        self.assertEqual(audit["dynamic_variant_count"], 210)
        self.assertEqual(audit["dynamic_variant_stage_count"], 100)
        self.assertEqual(audit["exact_source_payload_match_count"], 0)
        self.assertEqual(
            audit["original_offset_source_payload_match_count"],
            0,
        )
        reported = audit["reported_impulse_entry_update"]
        self.assertEqual(
            reported["entry_id"],
            "story/002/condition/00/01",
        )
        self.assertEqual(reported["stage_index"], 2)
        self.assertEqual(reported["condition_table_pointer_offset"], 31460)
        self.assertEqual(reported["original_text_offset"], 74720)
        self.assertEqual(reported["final_text_offset"], 45936)
        self.assertEqual(reported["translation"], "击坠真或亚历克斯。")
        self.assertTrue(reported["final_table_readback_exact"])
        self.assertTrue(
            reported["exact_source_payload_absent_from_final_stage"]
        )
        self.assertTrue(reported["original_offset_source_payload_absent"])
        self.assertTrue(
            audit["all_translated_condition_source_payloads_absent"]
        )
        self.assertTrue(
            self.content["checks"]["dynamic_condition_updates_exact"]
        )

    def test_story_and_battle_text_have_no_raw_visible_ascii_glyphs(self):
        storage = self.content["raw_visible_ascii_storage"]
        self.assertEqual(storage["story_glyph_count"], 0)
        self.assertEqual(storage["story_target_count"], 0)
        self.assertEqual(storage["srvc_glyph_count"], 0)
        self.assertEqual(storage["srvc_record_count"], 0)
        self.assertTrue(storage["runtime_substitution_tokens_excluded"])
        self.assertTrue(
            storage["all_stored_visible_ascii_uses_two_byte_glyphs"]
        )
        self.assertTrue(
            self.content["checks"]["raw_visible_ascii_glyph_count_zero"]
        )


if __name__ == "__main__":
    unittest.main()
