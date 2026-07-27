import hashlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "zh"
    / "story-dialogue"
    / "stage-003.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "glossary"
    / "story-dialogue-stage-003-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StoryDialogueStage003TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_stage_003_is_complete_and_contains_no_japanese_source_text(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-story-dialogue")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "dialogue",
                "stage_indices": [3],
                "entry_count": 36,
                "unique_source_text_count": 36,
                "translated_entry_count": 36,
                "punctuation_only_entry_count": 1,
            },
        )
        self.assertEqual(len(entries), 36)
        self.assertEqual(len({entry["id"] for entry in entries}), 36)
        self.assertEqual(
            entries[0]["id"],
            "story/003/dialogue/01.01/0000",
        )
        self.assertEqual(
            entries[-1]["id"],
            "story/003/dialogue/01.05/0017",
        )

        for entry in entries:
            self.assertRegex(
                entry["id"],
                r"^story/003/dialogue/\d{2}\.\d{2}/\d{4}$",
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

    def test_every_source_has_one_unique_stage_decision(self):
        entries = self.translations["entries"]
        self.assertEqual(
            len({entry["source_text_sha256"] for entry in entries}),
            36,
        )

    def test_layout_shape_is_locked(self):
        entries = self.translations["entries"]
        newline_counts = [
            entry["translation"].count("\n") for entry in entries
        ]
        self.assertEqual(Counter(newline_counts), {0: 29, 1: 7})
        pattern = "".join(str(count) for count in newline_counts)
        self.assertEqual(
            hashlib.sha256(pattern.encode("ascii")).hexdigest(),
            "d6bf90402ff479625584d72690e09532fa02a374b66b23259ccc469dbdc160c8",
        )
        self.assertFalse(
            any(
                re.search(r"\$[A-Za-z]|●+", entry["translation"])
                for entry in entries
            )
        )

    def test_punctuation_only_decision_is_explicit(self):
        punctuation_only = [
            entry
            for entry in self.translations["entries"]
            if entry["notes"].startswith("纯标点演出")
        ]
        self.assertEqual(len(punctuation_only), 1)
        self.assertEqual(punctuation_only[0]["translation"], "“……”")

    def test_representative_story_tone_and_setting_terms(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        expected = {
            "story/003/dialogue/01.02/0003": (
                "“他们本就是为这种任务而投入的Extended”"
            ),
            "story/003/dialogue/01.02/0005": (
                "“尼奥·罗阿诺克上校，\n"
                "　军械库一号方向发现机影！数量为3！”"
            ),
            "story/003/dialogue/01.05/0012": (
                "“通知全员。本舰即刻追击敌舰。\n"
                "　从现在起，目标代号为Bogey One！”"
            ),
            "story/003/dialogue/01.05/0013": (
                "“发布红色警戒！全员就位！”"
            ),
            "story/003/dialogue/01.05/0016": (
                "“审讯已交给阿瑟·川恩副长负责”"
            ),
        }
        self.assertEqual(
            {
                entry_id: entries[entry_id]["translation"]
                for entry_id in expected
            },
            expected,
        )
        self.assertIn(
            "不是三架被夺取的新型机",
            entries["story/003/dialogue/01.05/0015"]["notes"],
        )

    def test_stage_glossary_is_separate_and_fully_referenced(self):
        terms = self.glossary["terms"]
        self.assertEqual(
            self.glossary["glossary_id"],
            "srwz-zh-story-dialogue-stage-003-v1",
        )
        self.assertEqual(len(terms), 5)
        self.assertEqual(len({term["id"] for term in terms}), 5)
        self.assertEqual(
            Counter(term["status"] for term in terms),
            {"researched": 5},
        )
        self.assertEqual(
            Counter(term["category"] for term in terms),
            {"people": 2, "system": 2, "organization": 1},
        )
        self.assertTrue(all(term["notes"] for term in terms))

        referenced = {
            term_id
            for entry in self.translations["entries"]
            for term_id in entry["glossary_refs"]
        }
        self.assertTrue({term["id"] for term in terms}.issubset(referenced))
        self.assertIn("skill/extended", referenced)
        self.assertIn("unit/minerva", referenced)
        self.assertIn("organization/zaft", referenced)

        by_id = {term["id"]: term for term in terms}
        self.assertEqual(
            by_id["people/neo-roanoke-full"]["translation"],
            "尼奥·罗阿诺克",
        )
        self.assertEqual(
            by_id["system/condition-red"]["status"],
            "researched",
        )

    def test_v1_release_registers_stage_003(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-dialogue/stage-003.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-dialogue-stage-003-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            item
            for item in release["coverage_plan"]
            if item["batch_id"] == "v1-story-dialogue"
        )
        self.assertEqual(batch["target_entry_count"], 82719)
        self.assertEqual(batch["status"], "in_progress")
        self.assertIn("stages 001-005", release["notes"])


if __name__ == "__main__":
    unittest.main()
