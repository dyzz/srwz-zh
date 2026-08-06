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
    / "stage-005.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "glossary"
    / "story-dialogue-stage-005-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class StoryDialogueStage005TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_stage_005_is_complete_and_contains_no_japanese_source_text(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-story-dialogue")
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "dialogue",
                "stage_indices": [5],
                "entry_count": 298,
                "unique_source_text_count": 280,
                "translated_entry_count": 298,
                "punctuation_only_entry_count": 9,
            },
        )
        self.assertEqual(len(entries), 298)
        self.assertEqual(len({entry["id"] for entry in entries}), 298)
        self.assertEqual(
            entries[0]["id"],
            "story/005/dialogue/01.01/0000",
        )
        self.assertEqual(
            entries[-1]["id"],
            "story/005/dialogue/02.02/0106",
        )
        self.assertEqual(
            Counter(entry["editorial_status"] for entry in entries),
            {"reviewed": 298},
        )

        for entry in entries:
            self.assertRegex(
                entry["id"],
                r"^story/005/dialogue/\d{2}\.\d{2}/\d{4}$",
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
        self.assertEqual(len(by_source_hash), 280)
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
            {1: 274, 3: 4, 6: 2},
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
        self.assertEqual(Counter(newline_counts), {0: 190, 1: 107, 2: 1})
        pattern = "".join(str(count) for count in newline_counts)
        self.assertEqual(
            hashlib.sha256(pattern.encode("ascii")).hexdigest(),
            "b8cb8da126e0e66e13f4901d73f03cfad17c976112c1afa970ef5435f385382a",
        )
        tokens = Counter(
            token
            for entry in entries
            for token in re.findall(r"\$[A-Za-z]|●+", entry["translation"])
        )
        self.assertEqual(tokens, {"$F": 1})

    def test_punctuation_black_screen_and_location_cards_are_explicit(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        punctuation = [
            entry
            for entry in entries.values()
            if entry["translation"] in {"“……”", "？？？"}
        ]
        self.assertEqual(
            Counter(entry["translation"] for entry in punctuation),
            {"“……”": 6, "？？？": 3},
        )

        black_screens = [
            entry
            for entry in entries.values()
            if entry["translation"] == "黑屏"
        ]
        self.assertEqual(len(black_screens), 6)
        self.assertTrue(
            all("不是角色对白" in entry["notes"] for entry in black_screens)
        )
        self.assertEqual(
            entries["story/005/dialogue/02.01/0000"]["translation"],
            "日本　藤泽地区",
        )
        self.assertEqual(
            entries["story/005/dialogue/02.02/0000"]["translation"],
            "阿伽玛　舰内",
        )
        self.assertEqual(
            entries["story/005/dialogue/02.02/0063"]["translation"],
            "骏河湾　渔港",
        )
        self.assertEqual(
            entries["story/005/dialogue/02.02/0066"]["translation"],
            "　　　　　　　　～骏河湾　渔港～",
        )

    def test_representative_crossover_tone_and_setting_terms(self):
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        expected = {
            "story/005/dialogue/01.01/0008": (
                "“杜克·弗里德！只要打倒你，\n"
                "　返回月球的骷髅月基地，我们就能东山再起！”"
            ),
            "story/005/dialogue/01.05/0002": (
                "“太好了！地狱王者和宇宙王者都在！”"
            ),
            "story/005/dialogue/01.13/0003": (
                "“我知道，蕾蒂·甘达尔！这里交给我！！”"
            ),
            "story/005/dialogue/02.01/0021": (
                "“就是《第二次雅金·杜威攻防战》吧？\n"
                "　听说那场战斗可厉害了！”"
            ),
            "story/005/dialogue/02.02/0031": (
                "（《PLANT评议会议长》这个头衔……\n"
                "　听到现在，他可说是把世界一分为二的\n"
                "　两大阵营之一的最高领袖……）"
            ),
            "story/005/dialogue/02.02/0103": (
                "“那颗蓝色星球被火焰包围后，\n"
                "　一定会更加美丽。让班多克出击”"
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
                "system/turn": 3,
                "skill/guard": 1,
                "skill/extreme": 1,
                "system/unknown-machine": 1,
            },
        )
        entries = {
            entry["id"]: entry for entry in self.translations["entries"]
        }
        self.assertIn(
            "人物职能",
            entries["story/005/dialogue/02.01/0009"]["notes"],
        )
        self.assertIn(
            "片假名子串",
            entries["story/005/dialogue/02.02/0016"]["notes"],
        )
        self.assertIn(
            "地名方位",
            entries["story/005/dialogue/02.02/0040"]["notes"],
        )

    def test_stage_glossary_is_separate_and_fully_referenced(self):
        terms = self.glossary["terms"]
        self.assertEqual(
            self.glossary["glossary_id"],
            "srwz-zh-story-dialogue-stage-005-v1",
        )
        self.assertEqual(len(terms), 18)
        self.assertEqual(len({term["id"] for term in terms}), 18)
        self.assertEqual(
            Counter(term["status"] for term in terms),
            {"proposed": 1, "researched": 17},
        )
        self.assertEqual(
            Counter(term["category"] for term in terms),
            {
                "unit": 5,
                "place": 4,
                "people": 3,
                "organization": 3,
                "technology": 1,
                "event": 1,
                "system": 1,
            },
        )
        self.assertTrue(all(term["notes"] for term in terms))

        referenced = {
            term_id
            for entry in self.translations["entries"]
            for term_id in entry["glossary_refs"]
        }
        self.assertTrue({term["id"] for term in terms}.issubset(referenced))
        self.assertIn("organization/vega-alliance-force", referenced)
        self.assertIn("organization/dinosaur-empire", referenced)
        self.assertIn("organization/titans", referenced)
        self.assertIn("organization/aeug", referenced)
        self.assertIn("unit/bandok", referenced)
        self.assertIn("species/coordinator", referenced)

        by_id = {term["id"]: term for term in terms}
        self.assertEqual(
            by_id["unit/grendizer"]["translation"],
            "古连泰沙",
        )
        self.assertEqual(
            by_id["unit/grendizer"]["status"],
            "researched",
        )
        self.assertEqual(
            by_id["place/fleed-planet"]["status"],
            "researched",
        )
        self.assertEqual(
            by_id["event/second-battle-of-jachin-due"]["status"],
            "researched",
        )
        self.assertEqual(
            by_id["organization/earth-alliance-forces-short"]["enforce"],
            False,
        )

    def test_v1_release_registers_stage_005(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/story-dialogue/stage-005.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/story-dialogue-stage-005-v1.json",
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
