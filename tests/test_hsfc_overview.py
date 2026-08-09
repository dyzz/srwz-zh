import json
import struct
import unittest
from pathlib import Path

from tools.srwz.codec import decode
from tools.srwz.hsfc_overview import (
    group_hsfc_overviews,
    parse_hsfc_overviews,
    replace_hsfc_overviews_in_place,
)
from tools.srwz.text import (
    load_text_table,
    original_fullwidth_ascii_overrides,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HsfcOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hsfc = (PROJECT_ROOT / "work/disc/DATA/HSFC.BIN").read_bytes()
        slps = (PROJECT_ROOT / "work/disc/SLPS_258.87").read_bytes()
        offsets = struct.unpack_from("<5I", slps, 0x3476A0)
        cls.decoded = decode(hsfc[offsets[0] : offsets[1]]).output
        cls.table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
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

    def test_original_inventory_has_180_records_and_105_unique_texts(self):
        records = parse_hsfc_overviews(self.decoded, self.table)
        groups = group_hsfc_overviews(records)
        self.assertEqual(len(records), 180)
        self.assertEqual(len(groups), 105)
        self.assertEqual(records[66].record_offset, 0x2762)
        self.assertEqual(groups[0].entry_id, "hsfc-overview:000")

    def test_reviewed_corpus_rewrites_every_fixed_cell(self):
        corpus_path = PROJECT_ROOT / "corpus/zh/menu/hsfc-overviews.json"
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        rewritten, report = replace_hsfc_overviews_in_place(
            self.decoded,
            self.table,
            corpus["entries"],
            encoding_overrides=self.overrides,
        )
        self.assertEqual(report["inventory_record_count"], 180)
        self.assertEqual(report["unique_source_text_count"], 105)
        self.assertEqual(report["translated_occurrence_count"], 180)
        self.assertGreaterEqual(report["minimum_cell_headroom"], 0)
        self.assertTrue(report["fixed_cells_preserved"])
        self.assertTrue(report["translated_readback_exact"])
        self.assertEqual(len(rewritten), len(self.decoded))


if __name__ == "__main__":
    unittest.main()
