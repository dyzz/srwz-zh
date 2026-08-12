import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tools.audit_source_bound_glossary import (
    audit_source_terms,
    load_source_translations,
)


def glossary_term(path: str, term_id: str) -> dict:
    document = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return next(term for term in document["terms"] if term["id"] == term_id)


class SourceBoundNameRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_source_translations(ROOT)

    def test_confirmed_person_names_are_source_bound(self) -> None:
        expected_occurrences = {
            "people/speaker-e00210e47303": 197,  # エイジ -> 英司
            "people/speaker-0fb8d52aeaf0": 83,  # ガットラー -> 加特勒
            "people/speaker-c12dfb53f28b": 134,  # アフロディア -> 阿芙罗蒂亚
            "people/speaker-cbd92fab5f0b": 41,  # クインシュタイン -> 奎因斯坦
            "people/speaker-39bb8bf5e8f1": 35,  # ギャバン -> 嘉班
            "people/speaker-71fbb7dba7d3": 256,  # シロッコ -> 西罗克
            "people/speaker-d142d771217a": 13,  # ディアッカ -> 迪安卡
            "people/speaker-24b19e20c0e0": 4,  # シンゴ -> 新吾
            "people/speaker-5cf2a20e0254": 8,  # シド -> 希德
            "people/speaker-6b04fe4b92a7": 1,  # ダンケル -> 邓克尔
            "people/speaker-ed4360aca4c4": 10,  # マユ -> 玛尤
            "people/speaker-9af21164f24e": 32,  # さやか -> 沙也加
            "people/speaker-9cbe65863d05": 3,  # チュイル -> 裘露
            "people/speaker-0a8ee4e9b797": 18,  # テテス -> 特泰丝
        }
        for term_id, expected in expected_occurrences.items():
            with self.subTest(term_id=term_id):
                term = glossary_term(
                    "corpus/glossary/story-speakers-v1.json",
                    term_id,
                )
                report = audit_source_terms(self.rows, [term])
                self.assertEqual(
                    report["source_occurrences"],
                    {term_id: expected},
                )
                self.assertEqual(report["mismatches"], [])

    def test_setsuko_only_appears_in_setsuko_source_context(self) -> None:
        term = glossary_term(
            "corpus/glossary/terms-v1.json",
            "people/setsuko",
        )
        report = audit_source_terms(self.rows, [term])
        self.assertEqual(report["source_occurrences"], {term["id"]: 25})
        self.assertEqual(report["mismatches"], [])

        unbound = [
            row.entry_id
            for row in self.rows
            if "节子" in re.sub(r"[\s　]+", "", row.translation)
            and "セツコ" not in row.source_text
        ]
        self.assertEqual(unbound, [])


if __name__ == "__main__":
    unittest.main()
