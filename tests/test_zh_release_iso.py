import hashlib
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_CONFIG = PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
CHAIN_CONFIG = PROJECT_ROOT / "config/iso/zh-release-chain.json"
COMPONENT_MANIFEST = (
    PROJECT_ROOT
    / "manifests/releases/v0.1.0/full-story-components-validation.json"
)
ISO_REPORT = (
    PROJECT_ROOT / "build/iso/v0.1.0/iso-validation-v0.1.0.json"
)
CONTENT_MANIFEST = (
    PROJECT_ROOT
    / "manifests/releases/v0.1.0/zh-release-full-story-iso-content-validation.json"
)
FONT_PROPOSAL = (
    PROJECT_ROOT / "work/writeback/zh-release-codebook-proposal.json"
)
REMAINING_UI_CORPUS = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
STAGE_REPORT = (
    PROJECT_ROOT
    / "work/build/full-story-stage/components/component-validation.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class ZhReleaseIsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(BUILD_CONFIG.read_text(encoding="utf-8"))
        cls.chain = json.loads(CHAIN_CONFIG.read_text(encoding="utf-8"))
        cls.component = json.loads(
            COMPONENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.iso_report = json.loads(ISO_REPORT.read_text(encoding="utf-8"))
        cls.content = json.loads(
            CONTENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.proposal = json.loads(FONT_PROPOSAL.read_text(encoding="utf-8"))
        cls.remaining_ui_corpus = json.loads(
            REMAINING_UI_CORPUS.read_text(encoding="utf-8")
        )
        cls.stage = json.loads(STAGE_REPORT.read_text(encoding="utf-8"))

    def test_iso_replacements_are_bound_to_current_component_outputs(self):
        replacements = {
            item["member"]: {
                "path": item["source"],
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in self.config["replacements"]
        }
        self.assertTrue(self.config["require_component_output_binding"])
        self.assertEqual(replacements, self.component["outputs"])
        self.assertEqual(
            self.config["component_required_status"],
            self.component["status"],
        )
        self.assertTrue(
            self.config["layout"][
                "preserve_original_member_sector_allocations"
            ]
        )
        self.assertTrue(
            all(
                segment["shift_sectors"] == 0
                for segment in self.config["layout"]["shift_segments"]
            )
        )

    def test_new_character_uses_a_default_width_global_assignment(self):
        assignments = {
            item["character"]: item for item in self.proposal["assignments"]
        }
        dai = assignments["岱"]
        self.assertEqual(dai["code"], "90BB")
        self.assertFalse(0x8140 <= int(dai["code"], 16) < 0x889F)
        self.assertEqual(
            self.stage["unaliased_conditional_localized_assignment_count"],
            self.proposal["surface_safe_aliases"][
                "unaliased_conditional_assignment_count"
            ],
        )
        self.assertEqual(
            self.component["story"]["minimum_compressed_chunk_headroom"],
            22,
        )

    def test_production_compression_chain_is_rust_only(self):
        compression = self.component["compression"]
        self.assertEqual(compression["backend_policy"], "rust-only")
        self.assertIs(compression["python_encoder_used"], False)
        self.assertTrue(compression["font_strategy"].startswith("rust-"))
        self.assertTrue(
            all(
                "rust-" in strategy
                for strategy in compression["stage_strategies"]
            )
        )
        self.assertEqual(compression["component_strategy"], "rust-fit")
        self.assertEqual(compression["world_map_title_strategy"], "rust-fit")
        self.assertEqual(
            compression["scenario_select_strategy"],
            "rust-fit",
        )
        self.assertTrue(
            self.component["acceptance"][
                "production_compression_backend_rust_only"
            ]
        )

    def test_stage_title_textures_are_bound_to_vt1(self):
        graphics = self.component["stage_titles"]["graphics"]
        self.assertEqual(graphics["member"], "DATA/VT1.BIN")
        self.assertEqual(graphics["stage_name_entry_count"], 122)
        self.assertEqual(graphics["scenario_record_count"], 204)
        self.assertEqual(graphics["texture_entry_count"], 107)
        self.assertEqual(graphics["text_only_entry_count"], 15)
        self.assertTrue(graphics["all_stage_name_entries_accounted_for"])

        self.assertEqual(
            [item["ordinal"] for item in graphics["text_only_entries"]],
            list(range(107, 122)),
        )
        self.assertTrue(
            all(
                item["owns_stage_entry_texture"] is False
                for item in graphics["text_only_entries"]
            )
        )
        self.assertTrue(graphics["archive_size_preserved"])
        self.assertTrue(graphics["top_level_offsets_preserved"])
        self.assertTrue(graphics["internal_offsets_preserved"])
        self.assertTrue(graphics["tim2_metadata_and_clut_preserved"])
        self.assertTrue(graphics["translated_reread_exact"])
        self.assertEqual(
            graphics["stage_38"],
            next(
                item
                for item in graphics["titles"]
                if item["ordinal"] == 72
            ),
        )
        self.assertEqual(graphics["stage_38"]["text"], "被安排的决战")
        self.assertEqual(graphics["stage_38"]["selector"], 73)
        self.assertEqual(graphics["stage_38"]["loader_table_index"], 81)
        replacement = next(
            item
            for item in self.config["replacements"]
            if item["member"] == "DATA/VT1.BIN"
        )
        self.assertEqual(
            replacement["sha256"],
            self.component["outputs"]["DATA/VT1.BIN"]["sha256"],
        )

    def test_world_map_location_titles_are_bound_to_mapmodel(self):
        report = self.component["world_map_titles"]
        self.assertEqual(report["unique_title_count"], 78)
        self.assertEqual(report["translated_unique_title_count"], 70)
        self.assertEqual(report["member_count"], 115)
        self.assertEqual(report["translated_member_count"], 101)
        self.assertEqual(report["member_range"], [81, 195])
        self.assertGreaterEqual(
            report["codec"]["minimum_translated_member_headroom"],
            0,
        )
        self.assertTrue(report["archive_size_preserved"])
        self.assertTrue(report["top_level_offsets_preserved"])
        self.assertTrue(report["non_title_decoded_bytes_preserved"])
        self.assertTrue(report["english_subtitle_preserved_byte_exact"])
        self.assertTrue(report["same_text_members_preserved_byte_exact"])
        self.assertTrue(
            self.component["acceptance"]["world_map_titles_reread_exact"]
        )
        self.assertEqual(
            self.component["outputs"]["MAP/MAPMODEL.BIN"]["sha256"],
            "234710f2d39ae70b854d6f46a5f24e94c4085713b46bf4653b30371b52349518",
        )

    def test_final_iso_hash_layout_and_current_candidate_are_locked(self):
        output = self.config["output"]
        iso_path = PROJECT_ROOT / output["path"]
        generated = sorted(
            (PROJECT_ROOT / "build/iso/v0.1.0").glob("*.iso")
        )
        self.assertEqual(generated, [iso_path])
        self.assertEqual(iso_path.name, "srwz-zh-v0.1.0.iso")
        self.assertEqual(len(self.config["replacements"]), 13)
        self.assertIn(
            "DATA/NISVDATA.BIN",
            {item["member"] for item in self.config["replacements"]},
        )
        self.assertIn(
            "MAP/MAPMODEL.BIN",
            {item["member"] for item in self.config["replacements"]},
        )
        self.assertEqual(iso_path.stat().st_size, output["expected_size"])
        self.assertEqual(sha256_file(iso_path), output["expected_sha256"])
        self.assertEqual(
            self.iso_report["output_iso"]["sha256"],
            output["expected_sha256"],
        )
        self.assertEqual(
            self.iso_report["layout"]["member_manifest_sha256"],
            output["expected_member_manifest_sha256"],
        )
        self.assertEqual(self.iso_report["layout"]["shifted_member_count"], 0)
        self.assertEqual(self.iso_report["layout"]["unchanged_member_count"], 53)
        self.assertTrue(
            self.iso_report["component_binding"][
                "all_replacements_match_component_outputs"
            ]
        )

    def test_current_v0_1_0_content_readback_is_complete(self):
        self.assertEqual(
            Path(self.content["iso"]["path"]).name,
            "srwz-zh-v0.1.0.iso",
        )
        self.assertEqual(
            self.content["iso"]["sha256"],
            self.config["output"]["expected_sha256"],
        )
        self.assertEqual(self.content["stage_count"], 154)
        self.assertEqual(self.content["translation_entry_count"], 91746)
        self.assertEqual(self.content["dialogue_count"], 82719)
        self.assertEqual(self.content["condition_count"], 558)
        self.assertEqual(self.content["speaker_count"], 8469)
        self.assertEqual(
            self.content["stage_overviews"]["translated_entry_ids"],
            [f"overview:{ordinal:03d}" for ordinal in range(110)],
        )
        self.assertEqual(
            self.content["hsfc_overviews"]["inventory_record_count"], 180
        )
        self.assertEqual(
            self.content["hsfc_overviews"]["unique_source_text_count"], 105
        )
        self.assertEqual(
            self.content["hsfc_overviews"]["translated_occurrence_count"],
            180,
        )
        self.assertIs(
            self.content["hsfc_overviews"]["external_model_used"],
            False,
        )
        self.assertEqual(
            self.content["hsfc_overviews"]["translation_method"],
            "direct_manual",
        )
        self.assertEqual(
            self.content["hsfc_overviews"]["examples"]["record_066"],
            "　迪兰达尔演说引发新地球联邦政变。\n"
            "众人随即落入敌人的陷阱，\n"
            "迎来了前所未有的巨大危机。",
        )
        self.assertTrue(all(self.content["checks"].values()))

        mode = self.content["mode_select_effect"]
        self.assertEqual(mode["effect_id"], 296)
        self.assertEqual(
            mode["composed_labels"],
            ["普通模式", "EX困难模式", "特殊模式"],
        )
        self.assertTrue(mode["archive_offsets_preserved"])

        nisv = self.content["nisv_effect_names"]
        self.assertEqual(nisv["member"], "DATA/NISVDATA.BIN")
        self.assertEqual(nisv["occurrence_count"], 6)
        self.assertEqual(
            {item["translation"] for item in nisv["terms"]},
            {"屏障贯通", "无视体型修正"},
        )
        self.assertTrue(nisv["translated_reread_exact"])

    def test_current_v0_1_0_remaining_ui_readback_is_complete(self):
        report = self.content["compdata"]
        self.assertEqual(report["selected_entry_count"], 2452)
        self.assertEqual(
            report["field_entry_counts"],
            {"display": 933, "given": 918, "family": 601},
        )
        remaining = report["remaining_ui"]
        self.assertEqual(remaining["compdata_direct"]["entry_count"], 307)
        self.assertEqual(
            remaining["compdata_context_help"]["entry_count"], 357
        )
        self.assertEqual(remaining["compdata_inline"]["entry_count"], 6)
        self.assertEqual(remaining["leadership_effects"]["entry_count"], 59)
        self.assertEqual(remaining["slps_context_ui"]["entry_count"], 379)
        self.assertEqual(
            remaining["stage_fixed_formation"]["entry_count"], 9
        )
        self.assertEqual(remaining["slps"]["entry_count"], 169)
        self.assertEqual(remaining["parts"]["written_entry_count"], 132)
        atlas = self.component["remaining_ui"]["atlas"]
        self.assertEqual(
            atlas["protected_single_character_sources"],
            ["攻", "反"],
        )
        self.assertEqual(atlas["pending_dedicated_mask_count"], 4)
        self.assertTrue(
            report["new_game_regressions"][
                "male_default_name_readback_exact"
            ]
        )
        self.assertTrue(
            report["new_game_regressions"]["male_profile_within_24x3"]
        )
        self.assertTrue(remaining["readback_exact"])
        self.assertTrue(self.content["checks"]["remaining_ui_binary_text_exact"])

    def test_new_game_title_name_and_profile_regressions_are_locked(self):
        title = self.content["scenario_select_effect"]
        self.assertEqual(title["effect_id"], 295)
        self.assertEqual(title["labels"], ["正篇", "教学", "剧情"])
        self.assertEqual(
            title["composed_labels"], ["正篇剧情", "教学剧情"]
        )
        self.assertTrue(title["source_title_texture_replaced"])
        self.assertTrue(title["all_label_segments_nonblank"])
        self.assertTrue(
            title["all_label_segments_native_4bpp_antialiased"]
        )
        self.assertEqual(
            title["glyph_sampling"],
            "native_24px_center_crop_preserve_4bpp",
        )
        self.assertEqual(
            {segment["text"]: segment["x"] for segment in title["segments"]},
            {"正篇": 2, "教学": 108, "剧情": 161},
        )
        self.assertTrue(title["archive_offsets_preserved"])

        component_title = self.component["scenario_select_effect"]
        geometry = component_title["geometry"]
        self.assertEqual(geometry["frame_count"], 60)
        self.assertEqual(geometry["patched_quad_count"], 240)
        self.assertTrue(geometry["centers_aligned"])
        self.assertEqual(
            {
                group["label"]: (
                    group["x_shift"],
                    group["visible_x_bounds"],
                    group["visible_center_twice"],
                )
                for group in geometry["groups"]
            },
            {
                "正篇剧情": (20, [-48, 38], -10),
                "教学剧情": (-8, [-50, 40], -10),
            },
        )
        description_layout = component_title["description_layout"]
        self.assertTrue(description_layout["centers_aligned"])
        self.assertEqual(
            {
                entry["label"]: (
                    entry["source_x"],
                    entry["target_x"],
                    entry["visual_center_twice"],
                )
                for entry in description_layout["entries"]
            },
            {
                "正篇剧情说明": (-110, -56, 14),
                "教学剧情说明": (-155, -110, 14),
            },
        )
        self.assertTrue(
            self.component["acceptance"]["scenario_select_labels_aligned"]
        )

        regressions = self.content["compdata"]["new_game_regressions"]
        self.assertEqual(
            regressions["male_default_name_offsets"],
            {
                "0x33B440": "兰德",
                "0x33B448": "特拉维斯",
                "0x33E300": "兰德·特拉维斯",
                "0x3479C8": "兰德",
                "0x3479D0": "特拉维斯",
            },
        )
        self.assertTrue(regressions["male_default_name_readback_exact"])
        fixed_slps = self.remaining_ui_corpus["slps_by_offset"]
        self.assertEqual(fixed_slps["0x347A00"], "巴尔戈拉")
        self.assertEqual(
            {
                offset: fixed_slps[offset]
                for offset in ("0x345DC8", "0x345DD0", "0x345DE0")
            },
            {
                "0x345DC8": "三角",
                "0x345DD0": "中央",
                "0x345DE0": "广域",
            },
        )
        fixed_compdata = self.remaining_ui_corpus[
            "compdata_direct_by_offset"
        ]
        self.assertEqual(
            {
                offset: fixed_compdata[offset]
                for offset in (
                    "0x7F580",
                    "0x7F5A0",
                    "0x7F5C0",
                    "0x7F5E0",
                    "0x7F5E8",
                    "0x7F5F8",
                )
            },
            {
                "0x7F580": "三角队形",
                "0x7F5A0": "中央队形",
                "0x7F5C0": "广域队形",
                "0x7F5E0": "三角",
                "0x7F5E8": "中央",
                "0x7F5F8": "广域",
            },
        )
        self.assertEqual(
            {
                offset: fixed_slps[offset]
                for offset in ("0x342580", "0x3425B0", "0x3425C4")
            },
            {
                "0x342580": "攻击",
                "0x3425B0": "反击",
                "0x3425C4": "参与攻击",
            },
        )
        self.assertEqual(
            {
                offset: fixed_slps[offset]
                for offset in (
                    "0x343FB0",
                    "0x343FE0",
                    "0x344010",
                    "0x344040",
                    "0x344070",
                    "0x3440A0",
                )
            },
            {
                "0x343FB0": "热魂闪不铁集必加迅觉手狙直努乱分",
                "0x343FE0": "热魂闪不铁集必加迅觉手狙直幸努乱",
                "0x344010": "热魂闪不铁集必加迅觉手狙直努／乱分",
                "0x344040": "热魂闪不铁集必加迅觉手狙直幸努／乱",
                "0x344070": "热魂闪不铁集必加\n迅觉手狙直努乱分",
                "0x3440A0": "热魂闪不铁集必加\n迅觉手狙直幸努乱",
            },
        )
        self.assertEqual(
            regressions["scenario_button_offsets"],
            {"0x33BD4A": "：确定", "0x33BD58": "：取消"},
        )
        self.assertTrue(regressions["scenario_button_readback_exact"])
        self.assertTrue(regressions["male_profile_readback_exact"])
        self.assertTrue(regressions["male_profile_within_24x3"])
        self.assertTrue(regressions["male_profile_default_width_codes_only"])
        self.assertEqual(
            regressions["male_profile_conditional_width_code_count"], 0
        )

    def test_battle_text_domain_is_included_and_runtime_pending(self):
        step = self.chain["steps"][0]
        self.assertEqual(step["excluded_incomplete_domains"], [])
        self.assertEqual(
            {"BTL/SRVC.BIN", "BTL/SRVC.SEG"},
            set(step["changed_members"])
            & {"BTL/SRVC.BIN", "BTL/SRVC.SEG"},
        )
        self.assertEqual(
            self.component["srvc_battle_text"]["record_count"], 58740
        )
        self.assertTrue(
            self.component["acceptance"]["srvc_battle_text_reread_exact"]
        )
        srvc = self.component["srvc_battle_text"]
        self.assertEqual(srvc["unique_text_count"], 25708)
        self.assertEqual(srvc["record_count"], 58740)
        self.assertEqual(srvc["chunk_count"], 353)
        self.assertEqual(srvc["translated_reread_count"], 58740)
        for key in (
            "translated_reread_exact",
            "control_tokens_preserved",
            "record_budgets_preserved",
            "chunk_boundaries_preserved",
            "index_structure_preserved",
            "metadata_preserved_byte_exact",
            "unindexed_tails_preserved_byte_exact",
            "zero_record_chunks_preserved_byte_exact",
            "seg_preserved_byte_exact",
        ):
            self.assertTrue(srvc[key], key)
        self.assertTrue(
            self.content["visible_space_storage"]["srvc_pollution_absent"]
        )
        self.assertEqual(step["runtime_status"], "not_tested")
        self.assertFalse(step["promotion_eligible"])
        self.assertEqual(
            self.iso_report["runtime_acceptance"],
            "not tested by ISO builder",
        )


if __name__ == "__main__":
    unittest.main()
