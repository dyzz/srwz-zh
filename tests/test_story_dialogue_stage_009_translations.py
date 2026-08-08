import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT / "corpus" / "zh" / "story-dialogue" / "stage-009.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "story-dialogue-stage-009-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StoryDialogueStage009TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
        cls.entries = {
            entry["id"]: entry for entry in cls.translations["entries"]
        }

    def test_stage_009_is_complete_and_reviewed(self):
        document = self.translations
        self.assertEqual(document["batch_id"], "v1-story-dialogue")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "dialogue",
                "stage_indices": [9],
                "entry_count": 361,
                "unique_source_text_count": 335,
                "translated_entry_count": 361,
                "punctuation_only_entry_count": 8,
            },
        )
        self.assertEqual(len(document["entries"]), 361)
        self.assertEqual(
            Counter(entry["editorial_status"] for entry in document["entries"]),
            {"reviewed": 361},
        )
        self.assertEqual(
            Counter(entry["translation_action"] for entry in document["entries"]),
            {"translate": 361},
        )

    def test_stage_009_has_no_kana_or_unbounded_layout(self):
        for entry in self.translations["entries"]:
            translation = entry["translation"]
            self.assertIsNone(
                re.search(r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff]", translation),
                entry["id"],
            )
            self.assertNotIn("...", translation)
            self.assertNotIn("「", translation)
            self.assertNotIn("」", translation)
            self.assertLessEqual(
                max((len(line.lstrip("　 ")) for line in translation.splitlines()), default=0),
                24,
                entry["id"],
            )
            self.assertLessEqual(translation.count("\n"), 2, entry["id"])

    def test_repeated_source_lines_keep_one_decision_and_player_token(self):
        by_source_hash = defaultdict(list)
        for entry in self.translations["entries"]:
            by_source_hash[entry["source_text_sha256"]].append(entry)
        self.assertEqual(len(by_source_hash), 335)
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
        self.assertEqual(
            Counter(
                token
                for entry in self.translations["entries"]
                for token in re.findall(r"\$[A-Za-z]|●+", entry["translation"])
            ),
            {"$n": 1},
        )

    def test_stage_009_terms_and_release_are_registered(self):
        glossary_ids = {entry["id"] for entry in self.glossary["terms"]}
        self.assertEqual(len(glossary_ids), 16)
        referenced_ids = {
            glossary_id
            for entry in self.translations["entries"]
            for glossary_id in entry.get("glossary_refs", [])
        }
        self.assertGreaterEqual(len(referenced_ids & glossary_ids), 15)
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-dialogue/stage-009.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-dialogue-stage-009-v1.json",
            release["glossary_sources"],
        )

    def test_representative_stage_009_decisions(self):
        self.assertEqual(
            self.entries["story/009/dialogue/01.29/0005"]["translation"],
            "“这是天下无敌的桑波特3！\n　驾驶员是我，还有这些‘附赠品’！”",
        )
        self.assertEqual(
            self.entries["story/009/dialogue/01.36/0005"]["translation"],
            "“超重龙卷拳和超重新月镖吗？”",
        )
        self.assertEqual(
            self.entries["story/009/dialogue/02.01/0010"]["translation"],
            "“我叫坛斗志也。确实，我也许是外人，\n　但怎么能眼睁睁看着这种事发生！”",
        )


if __name__ == "__main__":
    unittest.main()
