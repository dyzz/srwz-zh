import csv
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "corpus" / "reference" / "gundam-roster-names.tsv"
LOCK = ROOT / "corpus" / "reference" / "gundam-roster-names.lock.json"
EXPECTED_FIELDS = [
    "category",
    "jp",
    "zh",
    "status",
    "source",
    "roster_ids",
    "stage_count_sum",
    "notes",
    "display_zh",
]


class GundamRosterReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        with REFERENCE.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            cls.fields = reader.fieldnames
            cls.rows = list(reader)
        cls.by_key = {
            (row["category"], row["jp"]): row
            for row in cls.rows
        }

    def test_snapshot_matches_locked_source(self):
        digest = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
        self.assertEqual(digest, self.lock["source"]["sha256"])
        self.assertEqual(digest, self.lock["snapshot"]["sha256"])
        self.assertTrue(self.lock["snapshot"]["byte_exact"])

    def test_schema_counts_and_unique_keys(self):
        self.assertEqual(self.fields, EXPECTED_FIELDS)
        self.assertEqual(len(self.rows), 517)
        self.assertEqual(
            sum(row["category"] == "person" for row in self.rows),
            285,
        )
        self.assertEqual(
            sum(row["category"] == "unit" for row in self.rows),
            232,
        )
        self.assertEqual(set(row["category"] for row in self.rows), {"person", "unit"})
        self.assertEqual(len(self.by_key), len(self.rows))
        self.assertTrue(all(row["jp"] and row["zh"] for row in self.rows))

    def test_scope_explicitly_excludes_non_gundam_works(self):
        self.assertFalse(self.lock["scope"]["authoritative_for_non_gundam"])
        self.assertTrue(self.lock["policy"]["do_not_use_for_non_gundam"])
        self.assertTrue(self.lock["policy"]["do_not_auto_match_ambiguous_short_names"])

    def test_selected_gundam_names_are_locked(self):
        expected = {
            ("person", "アポリー"): "阿波利",
            ("person", "ロベルト"): "罗伯托",
            ("person", "スティング"): "斯汀",
            ("person", "ステラ・ルーシェ"): "史黛拉·鲁西耶",
            ("person", "アレックス・ディノ"): "亚历士",
            ("person", "エマ・シーン"): "爱玛·辛",
            ("person", "ジェリド・メサ"): "捷利特·梅萨",
            ("person", "ザフト兵"): "扎夫特兵",
            ("unit", "アビスガンダム"): "深渊高达",
            ("unit", "カオスガンダム"): "混沌高达",
            ("unit", "ガイアガンダム"): "盖亚高达",
            ("unit", "フォースインパルスガンダム"): "强攻型脉冲高达",
            ("unit", "ソードインパルスガンダム"): "巨剑型脉冲高达",
            ("unit", "ブラストインパルスガンダム"): "轰击型脉冲高达",
        }
        for key, translation in expected.items():
            with self.subTest(key=key):
                self.assertEqual(self.by_key[key]["zh"], translation)


if __name__ == "__main__":
    unittest.main()
