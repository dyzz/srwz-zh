import json
import unittest
from pathlib import Path

from tools.build_full_story_components import (
    _apply_fixed_span_translations,
    _full_story_overrides,
    _stored_text_overrides,
)
from tools.srwz.nisv_tutorial import build_nisv_tutorial_pages
from tools.srwz.text import (
    decode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)
from tools.srwz.veff_tutorial_titles import (
    audit_tutorial_effect_binding,
    build_veff_tutorial_titles,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/full-story-components.json"
SOURCE_SLPS = PROJECT_ROOT / "work/disc/SLPS_258.87"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
FONT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-font-validation.json"


class Issue036TutorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.source_slps = SOURCE_SLPS.read_bytes()
        cls.table = load_text_table(TEXT_TABLE)
        font_manifest = json.loads(FONT_MANIFEST.read_text(encoding="utf-8"))
        _, primary, aliases, _ = _full_story_overrides(font_manifest)
        cls.encoding_overrides = _stored_text_overrides(
            cls.table, primary, aliases
        )
        cls.output_table = project_runtime_text_table(cls.table, primary)
        cls.output_table = project_runtime_text_table(cls.output_table, aliases)
        cls.output_table = project_runtime_text_table(
            cls.output_table,
            original_fullwidth_ascii_overrides(cls.table),
        )

    def test_slps_tutorial_page_titles_are_source_locked_and_fit(self):
        sources = {
            "0x347B40": "１．「ＳＲポイント」について",
            "0x347B60": "２．「精神コマンド」について",
            "0x347B80": "３．「途中セーブ」について",
            "0x347BA0": "４．「トライ・フォーメーション」について",
            "0x347BD0": "５．「センター・フォーメーション」について",
            "0x347C00": "６．「ワイド・フォーメーション」について",
            "0x347C30": "７．「３種のフォーメーションについて」",
            "0x347C60": "８．「セレクトヘルプ」について",
            "0x347C80": "９．「リトライ」について",
            "0x347CA0": "１０．「攻略Ｑ＆Ａ」について",
        }
        remaining = json.loads(
            (PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
                encoding="utf-8"
            )
        )["slps_by_offset"]
        translations = {offset: remaining[offset] for offset in sources}
        for offset, source in sources.items():
            self.assertEqual(
                decode_text(self.source_slps, int(offset, 16), self.table).text,
                source,
            )
        output, report = _apply_fixed_span_translations(
            self.source_slps,
            self.source_slps,
            translations,
            table=self.table,
            output_table=self.output_table,
            encoding_overrides=self.encoding_overrides,
            label="ISSUE-036 tutorial page titles",
        )
        self.assertTrue(report["reread_exact"])
        self.assertEqual(report["entry_count"], 10)
        for offset, translation in translations.items():
            self.assertEqual(
                decode_text(output, int(offset, 16), self.output_table).text,
                translation,
            )

    def test_nisv_tutorial_body_translates_all_114_records(self):
        contract = self.config["nisv_tutorial_pages"]
        corpus = json.loads(
            (PROJECT_ROOT / contract["corpus"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        output, report = build_nisv_tutorial_pages(
            (PROJECT_ROOT / contract["original_archive"]["path"]).read_bytes(),
            self.source_slps,
            contract,
            corpus,
            self.table,
            self.encoding_overrides,
        )
        self.assertEqual(len(output), contract["original_archive"]["size"])
        self.assertEqual(report["page_count"], 10)
        self.assertEqual(report["text_record_count"], 114)
        self.assertTrue(report["translated_reread_exact"])
        self.assertTrue(report["non_target_chunks_preserved_byte_exact"])
        page4 = report["pages"][3]["records"]
        page7 = report["pages"][6]["records"]
        page9 = report["pages"][8]["records"]
        self.assertEqual(page4[12]["translation"], "可使用TRI攻击")
        self.assertEqual(page7[4]["translation"], "可使用TRI攻击")
        self.assertEqual(page9[2]["source_position"], [272, 11, 1])
        self.assertEqual(page9[2]["position"], [143, 11, 1])
        self.assertEqual(page9[3]["source_position"], [493, 11, 1])
        self.assertEqual(page9[3]["position"], [364, 11, 1])
        self.assertTrue(page9[2]["coordinate_overridden"])
        self.assertTrue(page9[3]["coordinate_overridden"])

    def test_stage_186_code_path_references_all_four_title_effects(self):
        contract = self.config["tutorial_title_effects"]
        report = audit_tutorial_effect_binding(
            (PROJECT_ROOT / self.config["full_story_stage"]["stage"]["path"]).read_bytes(),
            (PROJECT_ROOT / self.config["full_story_stage"]["hb"]["path"]).read_bytes(),
            contract["event_binding"],
        )
        self.assertEqual(report["opcode"], "0x13C8")
        self.assertEqual(report["command_count"], 9)
        self.assertEqual(report["effect_ids"], [284, 285, 286, 287])
        self.assertTrue(report["all_four_effects_referenced"])

    def test_tutorial_veff_localizes_only_used_titles_and_preserves_mission_clear(self):
        contract = self.config["tutorial_title_effects"]
        source = (
            PROJECT_ROOT / contract["original_archive"]["path"]
        ).read_bytes()
        output, report = build_veff_tutorial_titles(
            source,
            self.source_slps,
            PROJECT_ROOT / contract["font"]["path"],
            contract,
        )
        self.assertEqual(len(output), len(source))
        self.assertEqual(report["effect_ids"], [284, 285, 286, 287])
        self.assertEqual(report["chunk_indices"], [285, 286, 287, 288])
        self.assertEqual(report["localized_effect_count"], 3)
        self.assertEqual(report["preserved_effect_count"], 1)
        self.assertEqual(report["localized_picture_count"], 4)
        self.assertEqual(report["preserved_picture_count"], 12)
        self.assertEqual(report["localized_background_picture_count"], 12)
        self.assertEqual(report["preserved_background_picture_count"], 4)
        self.assertEqual(report["coverage_ramp_indices"], [9, 3, 4, 5, 6, 7, 8])
        self.assertTrue(report["coverage_ramp_safe_across_all_four_clut_banks"])
        self.assertTrue(report["localized_title_underlays_removed"])
        self.assertTrue(report["mission_clear_preserved_byte_exact"])
        self.assertEqual(
            [item["localized_picture_indices"] for item in report["targets"]],
            [[0], [1], [1, 2], []],
        )
        self.assertEqual(
            [item["clear_background_picture_indices"] for item in report["targets"]],
            [[0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3], []],
        )
        mission = report["targets"][-1]
        self.assertEqual(mission["effect_id"], 287)
        self.assertTrue(mission["preserved_original"])
        self.assertTrue(mission["source_allocation_preserved_byte_exact"])
        self.assertTrue(all(item["preserved_original"] for item in mission["pictures"]))
        self.assertTrue(
            all(item["preserved_original"] for item in mission["background_pictures"])
        )
        self.assertTrue(report["tim2_metadata_preserved"])
        self.assertTrue(report["palette_preserved_byte_exact"])
        self.assertTrue(report["non_target_chunks_preserved_byte_exact"])
        self.assertTrue(report["translated_reread_exact"])


if __name__ == "__main__":
    unittest.main()
