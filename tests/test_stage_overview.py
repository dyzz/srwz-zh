import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode_production as decode
from tools.srwz.iso_layout import (
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from tools.srwz.stage_overview import (
    STAGE_OVERVIEW_MAXIMUM_LINE_WIDTH,
    parse_stage_overviews,
    replace_stage_overviews_in_place,
)
from tools.srwz.chinese_layout import dialogue_line_widths
from tools.srwz.text import (
    load_text_table,
    original_fullwidth_ascii_overrides,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StageOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stage = (PROJECT_ROOT / "work/disc/DATA/STAGE.BIN").read_bytes()
        hb = (
            PROJECT_ROOT
            / "work/build/full-story-stage/components/HEDBDY/HB.BIN"
        ).read_bytes()
        offsets = read_executable_archive_offsets(
            hb,
            ExecutableOffsetSpec(
                name="HEDBDY/HB.BIN STAGE offsets",
                member="HEDBDY/HB.BIN",
                table_start=30320,
                table_end=31144,
            ),
            len(stage),
        )
        cls.decoded = decode(stage[offsets[0] : offsets[1]]).output
        cls.table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        cls.corpus = json.loads(
            (
                PROJECT_ROOT / "corpus/zh/menu/stage-overviews.json"
            ).read_text(encoding="utf-8")
        )
        snapshot = json.loads(
            (
                PROJECT_ROOT
                / "config/encoding/zh-release-font-assignments.json"
            ).read_text(encoding="utf-8")
        )
        cls.overrides = {
            row["character"]: int(row["code"], 16)
            for row in snapshot["primary_assignments"]
        }
        cls.overrides.update(
            {
                row["character"]: int(row["code"], 16)
                for row in snapshot["surface_alias_assignments"]
            }
        )
        cls.overrides.update(original_fullwidth_ascii_overrides(cls.table))

    def test_original_inventory_has_110_fixed_pointer_entries(self):
        entries = parse_stage_overviews(self.decoded, self.table)
        self.assertEqual(len(entries), 110)
        self.assertEqual(entries[53].entry_id, "overview:053")
        self.assertEqual(entries[53].pointer_offset, 0x10EA8)
        self.assertEqual(entries[71].entry_id, "overview:071")
        self.assertEqual(entries[71].pointer_offset, 0x10EF0)

    def test_all_stage_overviews_rewrite_in_place(self):
        rewritten, report = replace_stage_overviews_in_place(
            self.decoded,
            self.table,
            self.corpus["entries"],
            encoding_overrides=self.overrides,
        )
        self.assertEqual(report["inventory_entry_count"], 110)
        self.assertEqual(report["translated_entry_count"], 110)
        self.assertEqual(
            report["translated_entry_ids"],
            [f"overview:{ordinal:03d}" for ordinal in range(110)],
        )
        self.assertEqual(report["unique_source_text_count"], 107)
        self.assertGreaterEqual(report["minimum_output_headroom"], 0)
        self.assertTrue(report["fixed_allocations_preserved"])
        self.assertTrue(report["untranslated_allocations_preserved"])
        self.assertEqual(report["line_width_limit"], 29)
        self.assertLessEqual(report["maximum_output_line_width"], 29)
        self.assertTrue(report["line_counts_within_source_height"])
        self.assertTrue(report["paragraph_indents_present"])
        self.assertGreater(report["paragraph_indent_count"], 0)
        self.assertTrue(report["translated_readback_exact"])
        self.assertEqual(len(rewritten), len(self.decoded))

    def test_scenario_chart_overviews_use_the_original_surface_width(self):
        self.assertEqual(STAGE_OVERVIEW_MAXIMUM_LINE_WIDTH, 29)
        row = next(
            entry
            for entry in self.corpus["entries"]
            if entry["id"] == "overview:107"
        )
        self.assertEqual(
            row["translation"],
            "　奇美拉希望从内部改革新地球联邦军。\n"
            "众人以各自方式回应使者雷本大尉的合作邀请。\n"
            "　众人分为两队，分别向太平洋与加利亚大陆开辟新的前进路线。\n",
        )
        self.assertEqual(
            dialogue_line_widths(row["translation"].rstrip("\n")),
            (17, 21, 28),
        )


if __name__ == "__main__":
    unittest.main()
