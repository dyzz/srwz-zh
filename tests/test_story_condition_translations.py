import hashlib
import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT / "corpus" / "zh" / "story-conditions.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "story-conditions-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StoryConditionTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_batch_covers_all_condition_records_without_source_text(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-story-conditions")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "sections": [
                    "Victory Conditions",
                    "Defeat Conditions",
                    "SR Conditions",
                ],
                "entry_count": 558,
                "unique_source_text_count": 241,
            },
        )
        self.assertEqual(len(entries), 558)
        self.assertEqual(len({entry["id"] for entry in entries}), 558)
        self.assertEqual(entries[0]["id"], "story/001/condition/00/00")
        self.assertEqual(entries[-1]["id"], "story/186/condition/02/01")

        for entry in entries:
            self.assertRegex(
                entry["id"],
                r"^story/\d{3}/condition/\d{2}/\d{2}$",
            )
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

    def test_repeated_templates_remain_identical(self):
        by_source_hash = defaultdict(list)
        for entry in self.translations["entries"]:
            by_source_hash[entry["source_text_sha256"]].append(entry)
        self.assertEqual(len(by_source_hash), 241)
        self.assertEqual(
            sorted(len(group) for group in by_source_hash.values())[-3:],
            [44, 63, 85],
        )
        for group in by_source_hash.values():
            decisions = {
                (
                    entry["translation"],
                    entry["translation_action"],
                    tuple(entry["glossary_refs"]),
                    entry["notes"],
                )
                for entry in group
            }
            self.assertEqual(len(decisions), 1)

    def test_line_break_shape_and_unknown_placeholders_are_locked(self):
        entries = self.translations["entries"]
        newline_counts = [
            entry["translation"].count("\n") for entry in entries
        ]
        self.assertEqual(Counter(newline_counts), {0: 516, 1: 41, 2: 1})
        pattern = "".join(str(count) for count in newline_counts)
        self.assertEqual(
            hashlib.sha256(pattern.encode("ascii")).hexdigest(),
            "b15fa0f39211129681b33675f9b23d68c20645b58feb1cf3bae982e56d1db58a",
        )

        preserved = [
            entry
            for entry in entries
            if entry["translation_action"] == "preserve"
        ]
        self.assertEqual(len(preserved), 24)
        self.assertTrue(
            all(entry["translation"] == "？？？" for entry in preserved)
        )
        self.assertTrue(all(entry["notes"] for entry in preserved))

    def test_high_risk_conditions_and_dynamic_placeholders_are_explicit(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        expected = {
            "story/001/condition/00/00": "击坠阿波利和罗伯托。",
            "story/001/condition/02/01": (
                "击坠克瓦特罗或卡缪。\n"
                "（两者都会在HP降至4000以下时撤退）"
            ),
            "story/004/condition/02/00": (
                "在4回合内击坠伊安；或在4回合内击坠斯汀、\n"
                "奥尔和史黛拉后，最后击坠尼奥。"
            ),
            "story/042/condition/01/00": "：被击坠。",
            "story/054/condition/01/01": "：或卡缪任一人被击坠。",
            "story/083/condition/01/01": "霍兰德或：被击坠。",
            "story/130/condition/02/00": (
                "在5回合内击坠其他所有敌人后，\n"
                "最后击坠超限恶魔。"
            ),
            "story/144/condition/00/00": (
                "在5回合内让兰顿到达司令簇。"
            ),
            "story/185/condition/00/01": "敌全灭",
        }
        self.assertEqual(
            {
                entry_id: entries[entry_id]["translation"]
                for entry_id in expected
            },
            expected,
        )
        for entry_id in (
            "story/042/condition/01/00",
            "story/054/condition/01/01",
            "story/083/condition/01/01",
        ):
            self.assertIn("冒号", entries[entry_id]["notes"])
            self.assertIn("不推测", entries[entry_id]["notes"])

    def test_condition_glossary_is_complete_and_separately_reviewable(self):
        terms = self.glossary["terms"]
        self.assertEqual(
            self.glossary["glossary_id"],
            "srwz-zh-story-conditions-v1",
        )
        self.assertEqual(len(terms), 146)
        self.assertEqual(len({term["id"] for term in terms}), 146)
        self.assertTrue(all(term["notes"] for term in terms))
        self.assertEqual(
            Counter(term["category"] for term in terms),
            {
                "system": 12,
                "people": 56,
                "unit": 73,
                "organization": 3,
                "species": 1,
                "technology": 1,
            },
        )
        referenced = {
            term_id
            for entry in self.translations["entries"]
            for term_id in entry["glossary_refs"]
        }
        self.assertTrue(
            {term["id"] for term in terms}.issubset(referenced)
        )
        by_id = {term["id"]: term for term in terms}
        self.assertEqual(by_id["system/annihilation"]["translation"], "全灭")
        self.assertEqual(by_id["unit/shurouga"]["translation"], "修罗神")
        self.assertFalse(by_id["people/ian"]["enforce"])
        self.assertFalse(by_id["people/sara"]["enforce"])

    def test_v1_release_registers_complete_story_condition_batch(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-conditions.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-conditions-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            batch
            for batch in release["coverage_plan"]
            if batch["batch_id"] == "v1-story-conditions"
        )
        self.assertEqual(batch["target_entry_count"], 558)
        self.assertEqual(batch["status"], "draft_complete")


if __name__ == "__main__":
    unittest.main()
