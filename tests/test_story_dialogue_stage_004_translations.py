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
    / "stage-004.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "glossary"
    / "story-dialogue-stage-004-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StoryDialogueStage004TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_stage_004_is_complete_and_contains_no_japanese_source_text(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-story-dialogue")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "dialogue",
                "stage_indices": [4],
                "entry_count": 523,
                "unique_source_text_count": 469,
                "translated_entry_count": 523,
                "punctuation_only_entry_count": 30,
            },
        )
        self.assertEqual(len(entries), 523)
        self.assertEqual(len({entry["id"] for entry in entries}), 523)
        self.assertEqual(
            entries[0]["id"],
            "story/004/dialogue/01.01/0000",
        )
        self.assertEqual(
            entries[-1]["id"],
            "story/004/dialogue/02.03/0048",
        )
        self.assertEqual(
            Counter(entry["editorial_status"] for entry in entries),
            {"reviewed": 523},
        )

        for entry in entries:
            self.assertRegex(
                entry["id"],
                r"^story/004/dialogue/\d{2}\.\d{2}/\d{4}$",
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
        self.assertEqual(len(by_source_hash), 469)
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
            {1: 452, 2: 11, 3: 3, 6: 2, 28: 1},
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

    def test_layout_shape_and_player_name_tokens_are_locked(self):
        entries = self.translations["entries"]
        newline_counts = [
            entry["translation"].count("\n") for entry in entries
        ]
        self.assertEqual(Counter(newline_counts), {0: 394, 1: 127, 2: 2})
        pattern = "".join(str(count) for count in newline_counts)
        self.assertEqual(
            hashlib.sha256(pattern.encode("ascii")).hexdigest(),
            "c0bed5f21c9edc2d4ad10cf5cf6b673ed7105eff80ce59c638532f452fe4b453",
        )
        tokens = Counter(
            token
            for entry in entries
            for token in re.findall(r"\$[A-Za-z]|●+", entry["translation"])
        )
        self.assertEqual(tokens, {"$F": 1, "$n": 1})
        self.assertLessEqual(
            max(
                len(line.lstrip("　 "))
                for entry in entries
                for line in entry["translation"].splitlines()
            ),
            24,
        )

    def test_punctuation_only_and_location_cards_are_explicit(self):
        punctuation_only = [
            entry
            for entry in self.translations["entries"]
            if entry["notes"].startswith("纯标点演出")
        ]
        self.assertEqual(len(punctuation_only), 30)
        self.assertEqual(
            Counter(entry["translation"] for entry in punctuation_only),
            {"“……”": 28, "“！”": 1, "“……！”": 1},
        )

        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        self.assertEqual(
            entries["story/004/dialogue/02.01/0000"]["translation"],
            "密涅瓦　机库",
        )
        self.assertEqual(
            entries["story/004/dialogue/02.01/0016"]["translation"],
            "MS　机库",
        )
        self.assertEqual(
            entries["story/004/dialogue/02.03/0003"]["translation"],
            "　　　　　　　～密涅瓦　机库～",
        )

    def test_representative_crossover_tone_and_setting_terms(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        expected = {
            "story/004/dialogue/01.03/0000": (
                "“接下来，脉冲高达准备出击！\n"
                "　模块选择轰击型。开启3号剪影机库！”"
            ),
            "story/004/dialogue/01.09/0007": (
                "“她听到BLOCK WORD了吗……！”"
            ),
            "story/004/dialogue/01.26/0008": (
                "“另外，将敌对的未知机体称为‘黑方’，\n"
                "　我军支援的未知机体称为‘白方’！”"
            ),
            "story/004/dialogue/01.29/0014": (
                "“遵命，队长大人！托比·沃森中尉将\n"
                "　以密涅瓦俘虏的身份，为自卫而战！”"
            ),
            "story/004/dialogue/01.29/0037": "“是、是的”",
            "story/004/dialogue/02.01/0050": (
                "“投降者先放一边，现在追击逃跑的\n"
                "　不明舰1号。密涅瓦初次出战，\n"
                "　要把整艘舰运作起来，舰桥上一个人都不能少”"
            ),
            "story/004/dialogue/02.01/0070": (
                "“长、长官！是，长官！”"
            ),
            "story/004/dialogue/02.02/0029": (
                "“长官！是，长官！”"
            ),
            "story/004/dialogue/02.03/0021": (
                "“说漂亮话果然是阿斯哈家的拿手好戏！”"
            ),
            "story/004/dialogue/02.03/0047": (
                "“阿斯兰·萨拉……”"
            ),
        }
        self.assertEqual(
            {
                entry_id: entries[entry_id]["translation"]
                for entry_id in expected
            },
            expected,
        )

    def test_cross_context_glossary_exceptions_are_explicit(self):
        exceptions = Counter(
            term_id
            for entry in self.translations["entries"]
            for term_id in entry.get("glossary_exceptions", [])
        )
        self.assertEqual(
            exceptions,
            {
                "system/turn": 25,
                "system/damage": 3,
                "system/unknown-machine": 4,
                "system/evasion": 1,
            },
        )
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        self.assertIn(
            "误命中",
            entries["story/004/dialogue/01.24/0002"]["notes"],
        )
        self.assertIn(
            "整艘战舰",
            entries["story/004/dialogue/02.03/0004"]["notes"],
        )

    def test_stage_glossary_is_separate_and_fully_referenced(self):
        terms = self.glossary["terms"]
        self.assertEqual(
            self.glossary["glossary_id"],
            "srwz-zh-story-dialogue-stage-004-v1",
        )
        self.assertEqual(len(terms), 20)
        self.assertEqual(len({term["id"] for term in terms}), 20)
        self.assertEqual(
            Counter(term["status"] for term in terms),
            {"researched": 20},
        )
        self.assertEqual(
            Counter(term["category"] for term in terms),
            {
                "unit": 8,
                "system": 4,
                "organization": 3,
                "place": 3,
                "technology": 1,
                "people": 1,
            },
        )
        self.assertTrue(all(term["notes"] for term in terms))

        referenced = {
            term_id
            for entry in self.translations["entries"]
            for term_id in entry["glossary_refs"]
        }
        self.assertTrue({term["id"] for term in terms}.issubset(referenced))
        self.assertIn("organization/titans", referenced)
        self.assertIn("organization/aeug", referenced)
        self.assertIn("unit/girty-lue", referenced)
        self.assertIn("unit/minerva", referenced)
        self.assertIn("unit/virgola", referenced)
        self.assertIn("technology/gs-combat-action", referenced)

        by_id = {term["id"]: term for term in terms}
        self.assertEqual(
            by_id["system/block-word"]["translation"],
            "BLOCK WORD",
        )
        self.assertEqual(
            by_id["people/jamaican-daninghan-full"]["translation"],
            "牙买加·达宁汉",
        )
        self.assertEqual(
            by_id["unit/blast-silhouette"]["translation"],
            "轰击型剪影",
        )
        self.assertEqual(
            by_id["system/black-unknown-callsign"]["enforce"],
            False,
        )

    def test_v1_release_registers_stage_004(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-dialogue/stage-004.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-dialogue-stage-004-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            item
            for item in release["coverage_plan"]
            if item["batch_id"] == "v1-story-dialogue"
        )
        self.assertEqual(batch["target_entry_count"], 82719)
        self.assertEqual(batch["status"], "draft_complete")
        self.assertIn("All 82,719 story-dialogue records", release["notes"])
        self.assertIn("154 text stages", release["notes"])


if __name__ == "__main__":
    unittest.main()
