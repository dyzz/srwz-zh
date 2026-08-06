import hashlib
import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "zh"
    / "story-dialogue"
    / "stage-001.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "glossary"
    / "story-dialogue-stage-001-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StoryDialogueTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_stage_001_is_a_complete_context_batch_without_source_text(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-story-dialogue")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "dialogue",
                "stage_indices": [1],
                "entry_count": 312,
                "unique_source_text_count": 288,
                "translated_entry_count": 312,
                "punctuation_only_entry_count": 11,
            },
        )
        self.assertEqual(len(entries), 312)
        self.assertEqual(len({entry["id"] for entry in entries}), 312)
        self.assertEqual(
            entries[0]["id"],
            "story/001/dialogue/01.01/0000",
        )
        self.assertEqual(
            entries[-1]["id"],
            "story/001/dialogue/02.01/0176",
        )

        for entry in entries:
            self.assertRegex(
                entry["id"],
                r"^story/001/dialogue/\d{2}\.\d{2}/\d{4}$",
            )
            self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("source_text", entry)
            self.assertEqual(entry["editorial_status"], "reviewed")
            self.assertEqual(entry["translation_action"], "translate")
            self.assertNotIn("...", entry["translation"])
            self.assertNotIn("「", entry["translation"])
            self.assertNotIn("」", entry["translation"])
            self.assertIsNone(
                re.search(
                    r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff]",
                    entry["translation"],
                )
            )
        self.assertEqual(
            Counter(entry["editorial_status"] for entry in entries),
            {"reviewed": 312},
        )
        self.assertEqual(
            len(
                {
                    entry["source_text_sha256"]
                    for entry in entries
                    if entry["editorial_status"] == "reviewed"
                }
            ),
            288,
        )

    def test_repeated_source_lines_keep_one_translation_decision(self):
        by_source_hash = defaultdict(list)
        for entry in self.translations["entries"]:
            by_source_hash[entry["source_text_sha256"]].append(entry)
        self.assertEqual(len(by_source_hash), 288)
        self.assertEqual(
            Counter(len(group) for group in by_source_hash.values()),
            {1: 274, 2: 11, 3: 2, 10: 1},
        )
        for group in by_source_hash.values():
            decisions = {
                (
                    entry["translation"],
                    entry["translation_action"],
                    tuple(entry["glossary_refs"]),
                    tuple(entry.get("glossary_exceptions", [])),
                    entry["notes"],
                )
                for entry in group
            }
            self.assertEqual(len(decisions), 1)

    def test_layout_shape_and_runtime_tokens_are_locked(self):
        entries = self.translations["entries"]
        newline_counts = [
            entry["translation"].count("\n") for entry in entries
        ]
        self.assertEqual(Counter(newline_counts), {0: 207, 1: 105})
        pattern = "".join(str(count) for count in newline_counts)
        self.assertEqual(
            hashlib.sha256(pattern.encode("ascii")).hexdigest(),
            "ed4c9adf82b9267499c6bae57c8b297b61b33e646a8bbfe32e40bdc0d7296561",
        )
        tokens = Counter(
            token
            for entry in entries
            for token in re.findall(
                r"\$[A-Za-z]|●+",
                entry["translation"],
            )
        )
        self.assertEqual(
            tokens,
            {"$n": 6, "$F": 3, "●●": 3, "●": 1},
        )

    def test_punctuation_only_lines_are_explicit_normalized_decisions(self):
        punctuation_only = [
            entry
            for entry in self.translations["entries"]
            if entry["notes"].startswith("纯标点演出")
        ]
        self.assertEqual(len(punctuation_only), 11)
        self.assertEqual(
            Counter(entry["translation"] for entry in punctuation_only),
            {"“……”": 10, "“！”": 1},
        )
        self.assertTrue(
            all(
                entry["translation_action"] == "translate"
                for entry in punctuation_only
            )
        )
        self.assertTrue(
            all(not entry["glossary_refs"] for entry in punctuation_only)
        )

    def test_representative_tone_terms_and_censorship_are_reviewable(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        expected = {
            "story/001/dialogue/01.01/0000": (
                "“从紧急出动命令下达到出击，\n"
                "　用时一分十五秒。算是及格吧”"
            ),
            "story/001/dialogue/01.01/0008": (
                "“明白。负责适配测试的$n\n"
                "　确实还不能参加实战”"
            ),
            "story/001/dialogue/01.08/0006": (
                "“啧……红色机体和高达的王牌，\n"
                "　简直就像同时对付夏亚·阿兹纳布尔和阿姆罗·雷！”"
            ),
            "story/001/dialogue/02.01/0087": (
                "“全领域泛用武装系统，\n"
                "　‘加纳利·卡弗’啊……还真是什么都想包办”"
            ),
            "story/001/dialogue/02.01/0008": (
                "“隶属月面驻军战技研究班：\n"
                "　荣耀之星。我在十天前到任”"
            ),
            "story/001/dialogue/02.01/0146": (
                "“而且，尽管只有短短十天，\n"
                "　我对巴尔戈拉也已经产生了感情”"
            ),
            "story/001/dialogue/02.01/0168": (
                "“明天就进入运行测试C级。\n"
                "　把加纳利·卡弗的手册再读一遍”"
            ),
        }
        self.assertEqual(
            {
                entry_id: entries[entry_id]["translation"]
                for entry_id in expected
            },
            expected,
        )

        obscured = entries["story/001/dialogue/02.01/0067"]
        self.assertIn("●●", obscured["translation"])
        self.assertIn("不擅自还原", obscured["notes"])
        level = entries["story/001/dialogue/02.01/0168"]
        self.assertIn("system/level", level["glossary_exceptions"])
        self.assertIn("C级", level["notes"])

    def test_stage_glossary_is_separate_and_fully_referenced(self):
        glossary = self.glossary
        terms = glossary["terms"]
        self.assertEqual(
            glossary["glossary_id"],
            "srwz-zh-story-dialogue-stage-001-v1",
        )
        self.assertEqual(glossary["default_source_match"], "substring")
        self.assertEqual(len(terms), 23)
        self.assertEqual(len({term["id"] for term in terms}), 23)
        self.assertEqual(
            Counter(term["status"] for term in terms),
            {"researched": 21, "proposed": 2},
        )
        self.assertEqual(
            Counter(term["category"] for term in terms),
            {
                "people": 9,
                "organization": 3,
                "system": 3,
                "unit": 3,
                "place": 2,
                "weapon": 2,
                "technology": 1,
            },
        )
        self.assertTrue(all(term["enforce"] for term in terms))
        self.assertTrue(all(term["notes"] for term in terms))

        referenced = {
            term_id
            for entry in self.translations["entries"]
            for term_id in entry["glossary_refs"]
        }
        self.assertTrue({term["id"] for term in terms}.issubset(referenced))

        by_id = {term["id"]: term for term in terms}
        self.assertEqual(
            by_id["place/lutetium-base"]["translation"],
            "卢特提姆基地",
        )
        self.assertEqual(
            by_id["organization/glory-star"]["translation"],
            "荣耀之星",
        )
        self.assertEqual(
            by_id["weapon/gunnery-carver"]["translation"],
            "加纳利·卡弗",
        )
        self.assertEqual(
            by_id["technology/gs-combat-action"]["translation"],
            "GS战斗术",
        )

    def test_v1_release_registers_complete_dialogue_draft_batch(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-dialogue/stage-001.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-dialogue-stage-001-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            batch
            for batch in release["coverage_plan"]
            if batch["batch_id"] == "v1-story-dialogue"
        )
        self.assertEqual(batch["target_entry_count"], 82719)
        self.assertEqual(batch["status"], "draft_complete")


if __name__ == "__main__":
    unittest.main()
