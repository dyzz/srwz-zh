import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.display_names import (
    DisplayNameError,
    load_display_name_source,
    load_full_unit_name_corpus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_PATH = PROJECT_ROOT / "config/display-names/compdata.json"
CORPUS_PATH = PROJECT_ROOT / "corpus/zh/display-names/units-full.json"


class FullUnitNameCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _config, _decoded, parsed, _context = load_display_name_source(
            PROJECT_ROOT,
            STRUCTURE_PATH,
        )
        cls.source_entries = parsed.unit_entries
        cls.decisions, cls.report = load_full_unit_name_corpus(
            PROJECT_ROOT,
            CORPUS_PATH,
            cls.source_entries,
        )

    def test_all_348_pointer_backed_name_slots_are_bound_once(self):
        self.assertEqual(len(self.decisions), 348)
        self.assertEqual(self.report["entry_count"], 348)
        self.assertEqual(
            list(self.decisions),
            [f"display-name/unit/{index:04d}/name" for index in range(348)],
        )
        self.assertEqual(
            sum(self.report["editorial_status_counts"].values()),
            348,
        )
        for index, source in enumerate(self.source_entries):
            decision = self.decisions[f"display-name/unit/{index:04d}/name"]
            self.assertEqual(decision["record_index"], index)
            self.assertEqual(decision["target_offset"], source.target_offset)
            self.assertEqual(decision["capacity"], source.capacity)
            self.assertEqual(
                decision["pointer_offsets"],
                list(source.pointer_offsets),
            )
            self.assertEqual(
                decision["source_text_sha256"],
                source.source_text_sha256,
            )

    def test_every_segment_has_attributable_sources_and_no_kana(self):
        self.assertTrue(
            all(decision["source_refs"] for decision in self.decisions.values())
        )
        kana = set("あいうえおアイウエオ")
        self.assertFalse(
            kana & set("".join(
                decision["translation"] for decision in self.decisions.values()
            ))
        )

    def test_gap_or_range_drift_fails_closed(self):
        document = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        document["segments"][1]["range"][0] += 1
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            path = Path(directory) / "units.json"
            path.write_text(
                json.dumps(document, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(DisplayNameError):
                load_full_unit_name_corpus(
                    PROJECT_ROOT,
                    path,
                    self.source_entries,
                )

    def test_king_gainer_and_gravion_names_follow_reviewed_families(self):
        expected = {
            226: "拉什罗德",
            249: "超重皇",
            250: "神机超重神",
            251: "烈阳超重神",
            252: "神机Σ超重神",
            253: "超重骑警",
            265: "G重钻机",
            266: "G战影",
            271: "超重Σ",
            272: "超重要塞",
        }
        self.assertEqual(
            {
                index: self.decisions[
                    f"display-name/unit/{index:04d}/name"
                ]["translation"]
                for index in expected
            },
            expected,
        )


if __name__ == "__main__":
    unittest.main()
