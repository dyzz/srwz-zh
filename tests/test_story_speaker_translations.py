import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = PROJECT_ROOT / "corpus" / "zh" / "story-speakers.json"
GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "story-speakers-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StorySpeakerTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_batch_covers_every_speaker_record_without_source_text(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-story-speakers")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "speaker",
                "entry_count": 8665,
                "unique_source_text_count": 425,
                "translated_entry_count": 8108,
                "preserved_placeholder_entry_count": 557,
            },
        )
        self.assertEqual(len(entries), 8665)
        self.assertEqual(len({entry["id"] for entry in entries}), 8665)
        self.assertEqual(entries[0]["id"], "story/001/speaker/001")
        self.assertEqual(entries[-1]["id"], "story/186/speaker/006")

        for entry in entries:
            self.assertRegex(entry["id"], r"^story/\d{3}/speaker/\d{3}$")
            self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("source_text", entry)
            self.assertEqual(entry["editorial_status"], "draft")
            self.assertIn(
                entry["translation_action"],
                {"translate", "preserve"},
            )
            self.assertNotIn("...", entry["translation"])
            if entry["translation_action"] == "translate":
                self.assertIsNone(
                    re.search(
                        r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff]",
                        entry["translation"],
                    )
                )

    def test_repeated_display_names_keep_one_review_decision(self):
        by_source_hash = defaultdict(list)
        for entry in self.translations["entries"]:
            by_source_hash[entry["source_text_sha256"]].append(entry)
        self.assertEqual(len(by_source_hash), 425)
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

    def test_structural_and_unknown_speaker_slots_are_explicit(self):
        preserved = [
            entry
            for entry in self.translations["entries"]
            if entry["translation_action"] == "preserve"
        ]
        self.assertEqual(len(preserved), 557)
        self.assertEqual(
            Counter(entry["translation"] for entry in preserved),
            {
                "": 160,
                "$n": 132,
                "　": 98,
                "　　": 94,
                "？？？": 73,
            },
        )
        self.assertTrue(all(entry["notes"] for entry in preserved))
        self.assertTrue(all(not entry["glossary_refs"] for entry in preserved))

    def test_representative_names_and_high_risk_labels_are_locked(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        expected = {
            "story/001/speaker/001": "丹泽尔",
            "story/002/speaker/012": "ZAFT士兵",
            "story/005/speaker/001": "甲儿",
            "story/007/speaker/017": "英司",
            "story/007/speaker/020": "雷文",
            "story/013/speaker/005": "梅尔",
            "story/019/speaker/016": "DC士兵",
            "story/019/speaker/017": "苏茜亚",
            "story/020/speaker/017": "美雪",
            "story/037/speaker/030": "纯",
        }
        self.assertEqual(
            {
                entry_id: entries[entry_id]["translation"]
                for entry_id in expected
            },
            expected,
        )
        jun = entries["story/037/speaker/030"]
        self.assertIn("跨作品同名", jun["notes"])
        self.assertIn("重点人工复核", jun["notes"])
        self.assertIn(
            "organization/zaft",
            entries["story/002/speaker/012"]["glossary_refs"],
        )

    def test_speaker_glossary_is_separate_and_fully_referenced(self):
        glossary = self.glossary
        terms = glossary["terms"]
        self.assertEqual(
            glossary["glossary_id"],
            "srwz-zh-story-speakers-v1",
        )
        self.assertEqual(glossary["default_source_match"], "token")
        self.assertEqual(len(terms), 342)
        self.assertEqual(len({term["id"] for term in terms}), 342)
        self.assertEqual(
            Counter(term["status"] for term in terms),
            {"researched": 222, "proposed": 114, "approved": 6},
        )
        self.assertTrue(all(term["category"] == "people" for term in terms))
        self.assertTrue(all(term["enforce"] for term in terms))
        self.assertTrue(all(term["notes"] for term in terms))
        self.assertEqual(
            len(
                {
                    source_term
                    for term in terms
                    for source_term in term["source_terms"]
                }
            ),
            343,
        )

        referenced = {
            term_id
            for entry in self.translations["entries"]
            for term_id in entry["glossary_refs"]
        }
        unreferenced = {
            term["id"]: term
            for term in terms
            if term["id"] not in referenced
        }
        self.assertTrue(
            all(term["status"] == "approved" for term in unreferenced.values())
        )
        self.assertEqual(
            set(unreferenced),
            {"people/moondoggie-short", "people/user-ji-edel-full"},
        )

        by_source = {
            term["source_terms"][0]: term
            for term in terms
        }
        self.assertEqual(by_source["甲児"]["translation"], "甲儿")
        self.assertEqual(by_source["エイジ"]["translation"], "英司")
        self.assertEqual(by_source["ソシエ"]["translation"], "苏茜亚")
        self.assertEqual(by_source["メシェー"]["translation"], "美雪")
        self.assertEqual(by_source["ジュン"]["translation"], "纯")
        self.assertEqual(by_source["ザフト兵"]["translation"], "ZAFT士兵")

    def test_v1_release_registers_complete_story_speaker_batch(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-speakers.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-speakers-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            batch
            for batch in release["coverage_plan"]
            if batch["batch_id"] == "v1-story-speakers"
        )
        self.assertEqual(batch["target_entry_count"], 8665)
        self.assertEqual(batch["status"], "draft_complete")


if __name__ == "__main__":
    unittest.main()
