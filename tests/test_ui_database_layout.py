import json
import struct
import unittest
from pathlib import Path

from tools.srwz.ui_database_layout import (
    audit_ui_database_layout,
    build_ui_database_layout_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-database-layout.json"
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p10-database-layout-validation.json"
)


class UiDatabaseLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.previews = audit_ui_database_layout(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_manifest_is_exact_text_free_projection(self):
        self.assertEqual(
            build_ui_database_layout_manifest(self.report),
            self.manifest,
        )
        serialized = json.dumps(self.manifest, ensure_ascii=False)
        self.assertNotIn("source_text", serialized)
        self.assertNotIn("target_text", serialized)

    def test_all_403_entries_fit_observed_source_envelopes(self):
        self.assertEqual(
            self.report["summary"],
            {
                "family_count": 4,
                "entry_count": 403,
                "source_readback_count": 403,
                "target_readback_count": 403,
                "line_width_overflow_count": 0,
                "line_count_overflow_count": 0,
                "literal_character_count": 513,
                "missing_glyph_character_count": 0,
                "empty_glyph_character_count": 0,
                "target_han_character_count": 445,
                "original_font_han_character_count": 0,
                "han_raster_mismatch_count": 0,
                "preview_page_count": 10,
                "preview_entry_count": 403,
            },
        )
        self.assertTrue(all(self.report["acceptance"].values()))

    def test_family_envelopes_and_target_maxima_are_locked(self):
        actual = {
            family["runtime_scene_id"]: (
                family["entry_count"],
                family["source_max_line_cells"],
                family["source_max_line_count"],
                family["target_max_line_cells"],
                family["target_max_line_count"],
                family["preview_page_count"],
            )
            for family in self.report["families"]
        }
        self.assertEqual(
            actual,
            {
                "database/leadership-effects-core": (15, 9, 1, 9, 1, 1),
                "database/pilot-skills-core": (88, 23, 3, 21, 3, 2),
                "database/spirit-commands-core": (145, 28, 2, 25, 2, 3),
                "database/unit-special-abilities-core": (
                    155,
                    30,
                    3,
                    27,
                    3,
                    4,
                ),
            },
        )

    def test_two_reflowed_entries_stay_within_their_envelopes(self):
        rows = {
            row["entry_id"]: row for row in self.report["entries"]
        }
        self.assertEqual(
            rows["menu/SLPS/09/0007"]["target_line_widths"],
            [15, 11, 20],
        )
        self.assertEqual(
            rows["menu/SLPS/08/0058"]["target_line_widths"],
            [16, 14],
        )
        for entry_id in ("menu/SLPS/09/0007", "menu/SLPS/08/0058"):
            self.assertFalse(rows[entry_id]["line_width_overflow"])
            self.assertFalse(rows[entry_id]["line_count_overflow"])

    def test_bond_keeps_one_cell_and_rereads_as_simplified_chinese(self):
        row = next(
            row
            for row in self.report["entries"]
            if row["entry_id"] == "menu/SLPS/08/0079"
        )
        self.assertEqual(row["source_text"], "絆")
        self.assertEqual(row["target_text"], "绊")
        self.assertEqual(row["source_line_widths"], [1])
        self.assertEqual(row["target_line_widths"], [1])
        self.assertFalse(row["line_width_overflow"])

    def test_exact_glyph_preview_pages_match_png_locks(self):
        self.assertEqual(len(self.previews), 10)
        for preview in self.report["previews"]:
            payload = self.previews[preview["path"]]
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", payload[16:24])
            self.assertEqual(width, preview["width"])
            self.assertEqual(height, preview["height"])
            self.assertEqual(
                (PROJECT_ROOT / preview["path"]).read_bytes(),
                payload,
            )

    def test_runtime_boundary_remains_explicit(self):
        self.assertEqual(self.report["runtime"]["status"], "not_tested")
        self.assertIn(
            "not measured runtime panel geometry",
            self.report["runtime"]["boundary"],
        )


if __name__ == "__main__":
    unittest.main()
