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
        self.assertEqual(remaining["slps_context_ui"]["entry_count"], 613)
        fixed_slps = self.remaining_ui["slps_by_offset"]
        self.assertEqual(len(fixed_slps), 245)
        self.assertEqual(remaining["slps"]["entry_count"], 245)
        self.assertEqual(
            {
                offset: fixed_slps[offset]
                for offset in (
                    "0x343DE8",
                    "0x345EB8",
                    "0x345EE8",
                    "0x346990",
                )
            },
            {
                "0x343DE8": "强化零件",
                "0x345EB8": "无变化",
                "0x345EE8": "队长效果",
                "0x346990": "队长效果",
            },
        )
        self.assertEqual(
            {
                offset: fixed_slps[offset]
                for offset in (
                    "0x347B40",
                    "0x347B60",
                    "0x347B80",
                    "0x347BA0",
                    "0x347BD0",
                    "0x347C00",
                    "0x347C30",
                    "0x347C60",
                    "0x347C80",
                    "0x347CA0",
                )
            },
            {
                "0x347B40": "1．关于“SR点数”",
                "0x347B60": "2．关于“精神指令”",
                "0x347B80": "3．关于“中断保存”",
                "0x347BA0": "4．关于“TRI队形”",
                "0x347BD0": "5．关于“中央队形”",
                "0x347C00": "6．关于“广域队形”",
                "0x347C30": "7．关于三种队形",
                "0x347C60": "8．关于“选择帮助”",
                "0x347C80": "9．关于“重试”",
                "0x347CA0": "10．关于“攻略Q&A”",
            },
        )

        context = self.remaining_ui["slps_context_ui_by_offset"]
        bazaar = {
            offset: translation
            for offset, translation in context.items()
            if 0x33C280 <= int(offset, 16) <= 0x33D6E0
        }
        self.assertEqual(len(bazaar), 44)
        self.assertEqual(bazaar["0x33C3E0"], "经验值、PP提升")
        self.assertIn("纳豆菌", bazaar["0x33CE60"])
        self.assertIn("银制工艺", bazaar["0x33D2B0"])
        self.assertIn("超合金新Z", bazaar["0x33D6E0"])
        self.assertEqual(
            {
                offset: fixed_slps[offset]
                for offset in (
                    "0x3434B8",
                    "0x3434D8",
                    "0x3434E0",
                    "0x3435D8",
                    "0x3435E0",
                    "0x3435F0",
                    "0x343CF0",
                    "0x345E30",
                    "0x345E38",
                )
            },
            {
                "0x3434B8": "：菜单",
                "0x3434D8": "：选择",
                "0x3434E0": "：全队逆序配置",
                "0x3435D8": "：选择",
                "0x3435E0": "：全队逆序配置",
                "0x3435F0": "：返回",
                "0x343CF0": "不，等一下。",
                "0x345E30": "空中用",
                "0x345E38": "陆地用",
            },
        )
        self.assertEqual(
            {
                offset: fixed_slps[offset]
                for offset in (
                    "0x3462A0",
                    "0x3462C0",
                    "0x3462E0",
                    "0x346300",
                    "0x346320",
                    "0x346340",
                    "0x346360",
                    "0x346380",
                )
            },
            {
                "0x3462A0": "SP降低（P系）",
                "0x3462C0": "运动性降低（R系）",
                "0x3462E0": "气力降低（P系）",
                "0x346300": "行动不能（P系）",
                "0x346320": "装甲值降低（R系）",
                "0x346340": "能力减半（P系）",
                "0x346360": "瞄准值降低（R系）",
                "0x346380": "EN降低（R系）",
            },
        )

        formation = remaining["stage_default_formation"]
        self.assertEqual(formation["group_count"], 794)
        self.assertEqual(formation["stage_count"], 179)
        self.assertEqual(formation["entry_count"], 11170)
        self.assertEqual(formation["unique_source_count"], 248)
        self.assertEqual(
            formation["layout_group_counts"],
            {
                "formation18+33+1": 344,
                "packed8-16": 119,
                "packed8-24": 87,
                "packed8-32": 27,
                "packed8-8": 48,
                "record6+23": 163,
                "slot32": 6,
            },
        )
        self.assertEqual(formation["record_metadata_count"], 8267)
        self.assertEqual(formation["compact_ascii_entry_count"], 14)
        self.assertEqual(
            formation["inventory_sha256"],
            "95772e2274f3cca29df73046cba174232f2e7ba102535b12449d79308071370d",
        )
        translations = {
            item["source"]: item["translation"]
            for item in formation["translations"]
        }
        self.assertEqual(translations["エゥーゴ"], "奥古")
        self.assertEqual(translations["グローリー・スター１"], "荣耀之星1")
        self.assertEqual(translations["ザフト"], "ZAFT")
        self.assertEqual(translations["ザンベース"], "桑贝斯")
        self.assertEqual(translations["シベ鉄警備隊"], "西伯铁警备队")
        self.assertEqual(translations["アデット隊"], "亚蒂特队")
        self.assertEqual(translations["ギンガナム艦隊"], "金卡拉姆舰队")
        self.assertEqual(translations["ガウリ隊"], "高利队")
        self.assertEqual(translations["マジンガーチーム"], "魔神小队")
        self.assertEqual(translations["黒いサザンクロス"], "黑色南十字星")
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

        prompts = remaining["stage_scenario_chart_prompts"]
        self.assertEqual(
            self.remaining_ui["stage_scenario_chart_prompts_by_offset"],
            {
                "0x1F790": "：确定",
                "0x1F798": "：返回",
                "0x1F7A0": "：加速",
            },
        )
        self.assertEqual(
            prompts["source_texts"],
            {
                "0x1F790": "：決定",
                "0x1F798": "：戻る",
                "0x1F7A0": "：スピードＵＰ",
            },
        )
        self.assertEqual(
            prompts["translations"],
            {
                "0x1F790": "：确定",
                "0x1F798": "：返回",
                "0x1F7A0": "：加速",
            },
        )
        self.assertTrue(prompts["fixed_spans_preserved"])
        self.assertTrue(prompts["reread_exact"])
        self.assertTrue(prompts["codec_round_trip_exact"])
        self.assertTrue(prompts["archive_size_preserved"])
        self.assertTrue(prompts["hb_offsets_preserved"])

    def test_current_story_content_scope_is_locked(self):
        self.assertEqual(self.content["stage_count"], 170)
        self.assertEqual(self.content["translation_entry_count"], 93071)
        self.assertEqual(self.content["dialogue_count"], 83668)
        self.assertEqual(self.content["condition_count"], 670)
        self.assertEqual(self.content["speaker_count"], 8733)
        self.assertTrue(all(self.content["checks"].values()))

    def test_weapon_special_effect_2_final_iso_readback_is_complete(self):
        effect_2 = self.content["nisv_effect_names"]
        self.assertEqual(effect_2["term_count"], 2)
        self.assertEqual(effect_2["occurrence_count"], 6)
        self.assertEqual(
            {
                item["translation"]: item["record_ids"]
                for item in effect_2["terms"]
            },
            {
                "屏障贯通": [
                    "metadata/keyword_summaries/026",
                    "page/013/record/034",
                    "page/027/record/033",
                ],
                "无视体型修正": [
                    "metadata/keyword_summaries/026",
                    "page/013/record/036",
                    "page/027/record/044",
                ],
            },
        )
        self.assertTrue(
            all(
                item["residual_source_occurrence_count"] == 0
                for item in effect_2["terms"]
            )
        )
        self.assertTrue(effect_2["all_source_occurrences_absent"])
        self.assertTrue(effect_2["translated_reread_exact"])

    def test_female_default_name_and_back_log_labels_are_locked(self):
        regressions = self.content["compdata"]["new_game_regressions"]
        self.assertEqual(
            regressions["male_default_unit_name_offsets"],
            {"0x3479E0": "钢狮子"},
        )
        self.assertTrue(
            regressions["male_default_unit_name_readback_exact"]
        )
        self.assertEqual(
            self.remaining_ui["slps_by_offset"]["0x3479E0"],
            "钢狮子",
        )
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
        self.assertEqual(fixed_slps["entry_count"], 613)
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

    def test_library_runtime_text_and_confirm_prompts_are_locked(self):
        regressions = self.content["compdata"]["library_regressions"]
        self.assertEqual(
            regressions["runtime_text_offsets"],
            {
                "0x340BD8": "攻略Q&A",
                "0x340C08": "：确定",
                "0x340C10": "：返回",
                "0x340C18": "：切换页面",
                "0x3472B0": "　　＜机体图鉴＞　",
                "0x3472D0": "　　＜角色事典＞　　",
                "0x3472E8": "＜术语事典＞",
                "0x347300": "　　＜音乐选择＞　　",
                "0x347320": "　　＜剧情流程＞　　",
                "0x347338": "＜攻略Q&A＞",
            },
        )
        self.assertEqual(
            regressions["confirm_prompt_offsets"],
            {
                "0x3407B0": "：确定",
                "0x340C08": "：确定",
                "0x340CA8": "：确定",
                "0x340E38": "：确定",
                "0x3434B0": "：确定",
                "0x3435C0": "：确定",
                "0x347870": "：确定",
            },
        )
        self.assertTrue(regressions["runtime_text_readback_exact"])
        self.assertTrue(regressions["confirm_prompts_readback_exact"])
        self.assertEqual(regressions["residual_raw_decision_glyph_count"], 0)
        self.assertTrue(regressions["raw_decision_glyph_absent"])
        self.assertTrue(
            self.content["checks"]["library_runtime_text_exact"]
        )
        self.assertTrue(
            self.content["checks"][
                "all_confirm_prompts_use_localized_glyphs"
            ]
        )

    def test_all_keyword_visible_spaces_are_stored_as_two_byte_glyphs(self):
        keywords = self.content["runtime_keywords"]
        storage = keywords["visible_space_storage"]
        self.assertEqual(keywords["authority_keyword_count"], 52)
        self.assertEqual(storage["field_count"], 52 * 4)
        self.assertEqual(storage["raw_visible_space_count"], 0)
        self.assertEqual(storage["two_byte_visible_space_count"], 85)
        self.assertTrue(storage["all_visible_spaces_two_byte"])
        self.assertTrue(keywords["library_popup_fields_exact"])
        self.assertTrue(
            keywords["compdata"]["all_list_labels_match_library_word"]
        )
        self.assertEqual(keywords["stage"]["record_count"], 77)
        self.assertTrue(keywords["stage"]["all_four_fields_match_library"])
        self.assertTrue(keywords["all_three_runtime_surfaces_exact"])

    def test_all_discovered_terrain_names_are_reencoded(self):
        terrain = self.component["world_map_titles"]["terrain_names"]
        self.assertEqual(terrain["unique_source_count"], 84)
        self.assertEqual(terrain["occurrence_count"], 475)
        self.assertEqual(terrain["changed_member_count"], 80)
        self.assertTrue(terrain["fixed_decoded_spans_preserved"])
        self.assertTrue(terrain["archive_size_preserved"])
        self.assertTrue(terrain["offset_table_preserved"])
        self.assertTrue(terrain["codec_round_trip_exact"])
        self.assertTrue(terrain["reread_exact"])

    def test_final_iso_contains_no_stale_stage_text_rendered_by_new_font(self):
        story = self.content["stale_stage_runtime_rendering_audit"]
        self.assertEqual(story["checked_entry_count"], 93071)
        self.assertEqual(story["distinct_stale_fingerprint_count"], 91471)
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
        self.assertEqual(audit["translated_condition_count"], 645)
        self.assertEqual(audit["dynamic_variant_count"], 321)
        self.assertEqual(audit["dynamic_variant_stage_count"], 100)
        self.assertEqual(audit["exact_source_payload_match_count"], 0)
        self.assertEqual(
            audit["original_offset_source_payload_match_count"],
            0,
        )
        reported = audit["reported_impulse_entry_update"]
        self.assertEqual(
            reported["entry_id"],
            "story/002/condition/00/03",
        )
        self.assertEqual(reported["stage_index"], 2)
        self.assertEqual(reported["condition_table_pointer_offset"], 31468)
        self.assertEqual(reported["original_text_offset"], 74800)
        self.assertEqual(reported["final_text_offset"], 46000)
        self.assertEqual(
            reported["translation"],
            "击坠混沌、深渊、盖亚中的任意一机。",
        )
        self.assertTrue(reported["final_table_readback_exact"])
        self.assertTrue(
            reported["exact_source_payload_absent_from_final_stage"]
        )
        self.assertTrue(reported["original_offset_source_payload_absent"])
        self.assertTrue(
            audit["all_translated_condition_source_payloads_absent"]
        )
        self.assertEqual(audit["runtime_name_placeholder_entry_count"], 12)
        self.assertEqual(
            audit["runtime_name_placeholder_occurrence_count"], 12
        )
        reported_placeholder = audit["reported_episode_21_placeholder"]
        self.assertEqual(
            reported_placeholder["entry_id"],
            "story/041/condition/01/02",
        )
        self.assertEqual(reported_placeholder["stage_index"], 41)
        self.assertEqual(
            reported_placeholder["translation"],
            ":或托比被击坠。",
        )
        self.assertEqual(reported_placeholder["raw_0x3a_count"], 1)
        self.assertTrue(reported_placeholder["stored_hex"].startswith("3a"))
        self.assertTrue(reported_placeholder["raw_placeholder_exact"])
        self.assertTrue(audit["all_runtime_name_placeholders_raw_0x3a"])
        self.assertTrue(
            self.content["checks"]["dynamic_condition_updates_exact"]
        )

    def test_story_and_battle_text_have_no_raw_visible_ascii_glyphs(self):
        storage = self.content["raw_visible_ascii_storage"]
        self.assertEqual(storage["story_glyph_count"], 0)
        self.assertEqual(storage["story_target_count"], 0)
        self.assertEqual(storage["srvc_glyph_count"], 0)
        self.assertEqual(storage["srvc_record_count"], 0)
        self.assertEqual(storage["special_ability_glyph_count"], 0)
        self.assertEqual(storage["special_ability_target_count"], 0)
        self.assertEqual(storage["pilot_skill_glyph_count"], 0)
        self.assertEqual(storage["pilot_skill_target_count"], 0)
        self.assertEqual(
            storage["unit_mech_pilot_weapon_ui_glyph_count"], 0
        )
        self.assertEqual(
            storage["unit_mech_pilot_weapon_ui_target_count"], 0
        )
        self.assertEqual(storage["weapon_effect_1_glyph_count"], 0)
        self.assertEqual(storage["weapon_effect_1_target_count"], 0)
        self.assertEqual(storage["weapon_effect_help_glyph_count"], 0)
        self.assertEqual(storage["weapon_effect_help_target_count"], 0)
        self.assertEqual(storage["weapon_effect_2_glyph_count"], 0)
        self.assertEqual(storage["weapon_effect_2_target_count"], 0)
        self.assertTrue(storage["runtime_substitution_tokens_excluded"])
        self.assertTrue(
            storage["all_stored_visible_ascii_uses_two_byte_glyphs"]
        )
        self.assertTrue(
            self.content["checks"]["raw_visible_ascii_glyph_count_zero"]
        )
        self.assertTrue(
            self.content["checks"]["ability_visible_ascii_storage_exact"]
        )


if __name__ == "__main__":
    unittest.main()
