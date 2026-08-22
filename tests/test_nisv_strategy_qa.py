import json
import unittest
from collections import Counter
from pathlib import Path

from tools.build_full_story_components import (
    _full_story_overrides,
    _stored_text_overrides,
)
from tools.srwz.codec import decode_production
from tools.srwz.iso_layout import (
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from tools.srwz.nisv_strategy_qa import (
    QA_METADATA_STRING_COUNT,
    QA_PAGE_COUNT,
    QA_TEXT_RECORD_COUNT,
    build_nisv_strategy_qa,
    parse_nisv_strategy_qa,
)
from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/full-story-components.json"
SOURCE_SLPS = PROJECT_ROOT / "work/disc/SLPS_258.87"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
FONT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-font-validation.json"


class NisvStrategyQaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.contract = config["nisv_strategy_qa"]
        cls.source_archive = (
            PROJECT_ROOT / cls.contract["original_archive"]["path"]
        ).read_bytes()
        cls.slps = SOURCE_SLPS.read_bytes()
        cls.corpus = json.loads(
            (PROJECT_ROOT / cls.contract["corpus"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        cls.table = load_text_table(TEXT_TABLE)
        font_manifest = json.loads(FONT_MANIFEST.read_text(encoding="utf-8"))
        _, primary, aliases, _ = _full_story_overrides(font_manifest)
        cls.encoding_overrides = _stored_text_overrides(
            cls.table, primary, aliases
        )

    def _source_qa(self):
        archive = self.contract["archive"]
        spec = ExecutableOffsetSpec(
            name=archive["name"],
            member=archive["member"],
            table_start=int(archive["table_start"], 0),
            table_end=int(archive["table_end"], 0),
        )
        offsets = read_executable_archive_offsets(
            self.slps, spec, len(self.source_archive)
        )
        chunk = self.contract["target"]["chunk_index"]
        decoded = decode_production(
            self.source_archive[offsets[chunk] : offsets[chunk + 1]]
        )
        return parse_nisv_strategy_qa(decoded.output)

    def test_source_inventory_and_style_surface_are_locked(self):
        qa = self._source_qa()
        self.assertEqual(
            sum(len(records) for records in qa["metadata"].values()),
            QA_METADATA_STRING_COUNT,
        )
        self.assertEqual(len(qa["pages"]), QA_PAGE_COUNT)
        self.assertEqual(qa["text_record_count"], QA_TEXT_RECORD_COUNT)
        styles = Counter(
            (record["style0"], record["style1"])
            for page in qa["pages"]
            for record in page["records"]
        )
        self.assertEqual(len(styles), 7)
        self.assertIn((2, 14), styles)
        self.assertIn((4, 6), styles)

    def test_complete_writeback_preserves_colours_and_reflows_mixed_styles(self):
        output, report = build_nisv_strategy_qa(
            self.source_archive,
            self.source_archive,
            self.slps,
            self.contract,
            self.corpus,
            self.table,
            self.encoding_overrides,
        )
        self.assertEqual(len(output), len(self.source_archive))
        self.assertEqual(report["metadata_string_count"], 264)
        self.assertEqual(report["page_count"], 102)
        self.assertEqual(report["text_record_count"], 2609)
        self.assertGreater(report["output_padding_size"], 0)
        self.assertTrue(report["allocation_table_preserved"])
        self.assertTrue(report["page_allocations_preserved"])
        self.assertTrue(report["record_styles_preserved"])
        self.assertTrue(report["record_z_coordinates_preserved"])
        self.assertTrue(report["mixed_style_line_flow"])
        self.assertTrue(report["empty_continuation_rows_collapsed"])
        self.assertTrue(report["fixed_column_anchors_aligned"])
        self.assertFalse(report["empty_records_extend_scroll_height"])
        self.assertEqual(report["empty_translation_record_count"], 415)
        self.assertGreater(report["vertically_reflowed_record_count"], 0)
        self.assertGreater(report["fixed_column_line_count"], 0)
        self.assertTrue(report["sprite_sections_preserved"])
        self.assertTrue(report["translated_reread_exact"])

        page1 = report["pages"][0]["records"]
        page2 = report["pages"][1]["records"]
        self.assertEqual(page1[2]["translation"], "队形")
        self.assertEqual(page1[2]["style"], [2, 14])
        self.assertEqual(page1[3]["source_position"], [190, 25, 1])
        self.assertEqual(page1[3]["position"], [76, 25, 1])
        self.assertEqual(page1[8]["translation"], "TRI队形")
        self.assertEqual(page1[8]["style"], [2, 14])
        self.assertEqual(page2[5]["translation"], "TRI攻击")
        self.assertEqual(page2[5]["style"], [2, 14])
        self.assertEqual(page2[5]["position"], [304, 36, 1])
        self.assertEqual(page2[6]["position"], [399, 36, 1])
        self.assertEqual(page2[7]["position"], [19, 47, 1])

        page5 = report["pages"][4]["records"]
        self.assertEqual(page5[8]["position"], [190, 69, 1])
        self.assertEqual(page5[9]["position"], [209, 69, 1])
        self.assertEqual(page5[11]["position"], [152, 80, 1])
        self.assertEqual(page5[14]["position"], [152, 91, 1])

        page6 = report["pages"][5]["records"]
        self.assertEqual(page6[5]["position"], [456, 36, 1])
        self.assertEqual(page6[6]["position"], [19, 47, 1])
        self.assertEqual(page6[7]["position"], [171, 47, 1])
        self.assertEqual(page6[9]["position"], [19, 58, 1])
        self.assertEqual(page6[10]["position"], [247, 58, 1])
        self.assertEqual(page6[11]["position"], [285, 58, 1])

        page9 = report["pages"][8]["records"]
        self.assertEqual(page9[22]["position"], [38, 179, 1])
        self.assertEqual(page9[23]["position"], [247, 179, 1])
        self.assertEqual(page9[24]["position"], [38, 201, 1])
        self.assertEqual(page9[25]["position"], [247, 201, 1])

        for page in report["pages"]:
            self.assertEqual(page["output_max_y"], page["visible_max_y"])
            for record in page["records"]:
                if record["translation"]:
                    last_x = record["position"][0] + (
                        len(record["translation"]) - 1
                    ) * report["glyph_advance_px"]
                    self.assertLessEqual(last_x, report["max_last_glyph_x"])


if __name__ == "__main__":
    unittest.main()
