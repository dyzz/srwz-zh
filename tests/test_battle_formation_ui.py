import json
import unittest
from pathlib import Path

from tools import build_full_story_components
from tools.srwz import font as srwz_font
from tools.srwz.text import (
    decode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BattleFormationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        cls.component = json.loads(
            (
                PROJECT_ROOT
                / "manifests/full-story-components-validation.json"
            ).read_text(encoding="utf-8")
        )
        font_manifest = json.loads(
            (
                PROJECT_ROOT
                / cls.config["full_story_font"]["manifest"]["path"]
            ).read_text(encoding="utf-8")
        )
        _proposal, primary, aliases, _report = (
            build_full_story_components._full_story_overrides(font_manifest)
        )
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        output_table = project_runtime_text_table(table, primary)
        output_table = project_runtime_text_table(output_table, aliases)
        cls.output_table = project_runtime_text_table(
            output_table,
            original_fullwidth_ascii_overrides(table),
        )
        cls.table = table
        cls.original_slps = (
            PROJECT_ROOT / "work/disc/SLPS_258.87"
        ).read_bytes()
        cls.output_slps = (
            PROJECT_ROOT / cls.component["outputs"]["SLPS_258.87"]["path"]
        ).read_bytes()

    def test_battle_formation_labels_are_localized_and_reread_exact(self):
        expected = {
            0x343DE8: ("強化パーツ", "强化零件"),
            0x345EE8: ("隊長効果", "队长效果"),
            0x346398: ("無効", "无效"),
            0x346990: ("隊長効果", "队长效果"),
        }
        for offset, (source, translation) in expected.items():
            self.assertEqual(
                decode_text(self.original_slps, offset, self.table).text,
                source,
            )
            self.assertEqual(
                decode_text(self.output_slps, offset, self.output_table).text,
                translation,
            )
        self.assertTrue(
            self.component["remaining_ui"]["slps"]["reread_exact"]
        )

    def test_signed_zero_prefix_keeps_the_original_plus_minus_glyph(self):
        snapshot = json.loads(
            (
                PROJECT_ROOT
                / "config/encoding/zh-release-font-assignments.json"
            ).read_text(encoding="utf-8")
        )
        active_codes = {
            row["code"]
            for row in (
                *snapshot["primary_assignments"],
                *snapshot["surface_alias_assignments"],
                *snapshot["source_compatibility_assignments"],
            )
        }
        self.assertNotIn("817D", active_codes)
        self.assertEqual(
            next(
                row
                for row in snapshot["primary_assignments"]
                if row["character"] == "屯"
            )["code"],
            "91E9",
        )

        source_vt1 = (PROJECT_ROOT / "work/disc/DATA/VT1.BIN").read_bytes()
        output_vt1 = (
            PROJECT_ROOT
            / self.component["outputs"]["DATA/VT1.BIN"]["path"]
        ).read_bytes()
        source_font = srwz_font.decode_vt1_font_segment(
            self.original_slps, source_vt1
        ).decoded
        output_font = srwz_font.decode_vt1_font_segment(
            self.output_slps, output_vt1
        ).decoded
        glyph_index = srwz_font.standard_glyph_index(0x817D)
        start = glyph_index * srwz_font.GLYPH_SIZE
        end = start + srwz_font.GLYPH_SIZE
        self.assertEqual(source_font[start:end], output_font[start:end])


if __name__ == "__main__":
    unittest.main()
