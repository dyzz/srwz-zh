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
    / "stage-002.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "glossary"
    / "story-dialogue-stage-002-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StoryDialogueStage002TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_stage_002_is_complete_and_contains_no_japanese_source_text(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-story-dialogue")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "dialogue",
                "stage_indices": [2],
                "entry_count": 542,
                "unique_source_text_count": 321,
                "translated_entry_count": 542,
                "punctuation_only_entry_count": 16,
            },
        )
        self.assertEqual(len(entries), 542)
        self.assertEqual(len({entry["id"] for entry in entries}), 542)
        self.assertEqual(
            entries[0]["id"],
            "story/002/dialogue/01.01/0000",
        )
        self.assertEqual(
            entries[-1]["id"],
            "story/002/dialogue/02.02/0028",
        )
        self.assertEqual(
            Counter(entry["editorial_status"] for entry in entries),
            {"reviewed": 542},
        )

        for entry in entries:
            self.assertRegex(
                entry["id"],
                r"^story/002/dialogue/\d{2}\.\d{2}/\d{4}$",
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

    def test_repeated_source_lines_keep_one_stage_translation_decision(self):
        by_source_hash = defaultdict(list)
        for entry in self.translations["entries"]:
            by_source_hash[entry["source_text_sha256"]].append(entry)
        self.assertEqual(len(by_source_hash), 321)
        self.assertEqual(
            {
                entry["source_text_sha256"]
                for entry in self.translations["entries"]
                if entry["editorial_status"] == "reviewed"
            },
            set(by_source_hash),
        )
        self.assertEqual(
            Counter(len(group) for group in by_source_hash.values()),
            {1: 265, 2: 21, 3: 10, 4: 3, 6: 1, 7: 10, 10: 9, 11: 1, 16: 1},
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

    def test_layout_shape_and_player_name_token_are_locked(self):
        entries = self.translations["entries"]
        newline_counts = [
            entry["translation"].count("\n") for entry in entries
        ]
        self.assertEqual(Counter(newline_counts), {0: 446, 1: 95, 2: 1})
        pattern = "".join(str(count) for count in newline_counts)
        self.assertEqual(
            hashlib.sha256(pattern.encode("ascii")).hexdigest(),
            "8aebee1c0b1a5fa59f2e1e559ffb1c7703f56d6a7721ad0d169affb78e8a8264",
        )
        tokens = Counter(
            token
            for entry in entries
            for token in re.findall(r"\$[A-Za-z]|●+", entry["translation"])
        )
        self.assertEqual(tokens, {"$n": 10})

    def test_punctuation_only_and_location_cards_are_explicit(self):
        punctuation_only = [
            entry
            for entry in self.translations["entries"]
            if entry["notes"].startswith("纯标点演出")
        ]
        self.assertEqual(len(punctuation_only), 16)
        self.assertTrue(
            all(
                entry["translation"] == "“……”"
                for entry in punctuation_only
            )
        )

        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        self.assertEqual(
            entries["story/002/dialogue/02.01/0003"]["translation"],
            "　　　　～军械库一号　船坞附近～",
        )
        self.assertEqual(
            entries["story/002/dialogue/02.01/0061"]["translation"],
            "　　　　　～军械库一号　市区～",
        )

    def test_representative_story_tone_and_setting_terms(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        expected = {
            "story/002/dialogue/01.18/0008": (
                "“丹泽尔选择”\n"
                "“1．撤出殖民卫星”\n"
                "“2．拦截被夺走的高达”"
            ),
            "story/002/dialogue/01.55/0008": (
                "“真，听得见吗？现在按他说的做，\n"
                "　优先夺回混沌、深渊和盖亚”"
            ),
            "story/002/dialogue/02.01/0034": (
                "“科幻小说？想必公主也知道\n"
                "　《Evidence 01》吧”"
            ),
            "story/002/dialogue/02.02/0013": (
                "“脉冲高达模块选择巨剑型。开启2号剪影机库”"
            ),
            "story/002/dialogue/02.02/0014": (
                "“剪影飞行器准备射出。\n"
                "　发射平台设置完毕。中央弹射器已联机”"
            ),
        }
        self.assertEqual(
            {
                entry_id: entries[entry_id]["translation"]
                for entry_id in expected
            },
            expected,
        )

        bodyguard = entries["story/002/dialogue/02.01/0056"]
        self.assertEqual(
            bodyguard["glossary_exceptions"],
            ["skill/guard"],
        )
        self.assertIn("保镖", bodyguard["translation"])
        self.assertIn("子串误命中", bodyguard["notes"])

    def test_stage_glossary_is_separate_and_fully_referenced(self):
        terms = self.glossary["terms"]
        self.assertEqual(
            self.glossary["glossary_id"],
            "srwz-zh-story-dialogue-stage-002-v1",
        )
        self.assertEqual(len(terms), 46)
        self.assertEqual(len({term["id"] for term in terms}), 46)
        self.assertEqual(
            Counter(term["status"] for term in terms),
            {"researched": 46},
        )
        self.assertEqual(
            Counter(term["category"] for term in terms),
            {
                "people": 14,
                "unit": 10,
                "system": 9,
                "technology": 4,
                "place": 3,
                "species": 3,
                "event": 2,
                "organization": 1,
            },
        )
        self.assertTrue(all(term["notes"] for term in terms))

        referenced = {
            term_id
            for entry in self.translations["entries"]
            for term_id in entry["glossary_refs"]
        }
        self.assertTrue({term["id"] for term in terms}.issubset(referenced))
        self.assertNotIn("people/ray", referenced)
        self.assertIn("people/rey-za-burrel-short", referenced)

        by_id = {term["id"]: term for term in terms}
        self.assertEqual(
            by_id["place/armory-one"]["translation"],
            "军械库一号",
        )
        self.assertEqual(
            by_id["technology/mirage-colloid"]["translation"],
            "幻象化粒子",
        )
        self.assertEqual(
            by_id["unit/core-splendor"]["translation"],
            "核心飞梭",
        )
        self.assertEqual(
            by_id["system/silhouette-hangar"]["status"],
            "researched",
        )

    def test_v1_release_registers_stage_002(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-dialogue/stage-002.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-dialogue-stage-002-v1.json",
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
