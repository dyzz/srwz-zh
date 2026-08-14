import json
import re
import unittest
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
GLOSSARY_ROOT = PROJECT_ROOT / "corpus/glossary"
RELEASE_PATH = PROJECT_ROOT / "corpus/releases/v1.json"
KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff]")
DYNAMIC_MALE_TITLE_RE = re.compile(
    r"\$(?:n|f|F|l)[ \n　]*(?:先生|大哥|哥哥|兄弟|老兄|大叔|小伙|男士)"
)
DYNAMIC_FEMALE_TITLE_RE = re.compile(
    r"\$(?:n|f|F|l)[ \n　]*(?:小姐|女士|太太|姑娘|大姐|姐姐)"
)

# These are STAGE archive indices, classified from their embedded
# stg_NNN*.bin resource names and docs/STAGE_ROUTE_MAP.md.
SETSUKO_EXCLUSIVE_STAGE_INDICES = frozenset(
    {
        *range(1, 13),
        41,
        *range(50, 73),
        110,
        *range(141, 146),
    }
)
LAND_EXCLUSIVE_STAGE_INDICES = frozenset(
    {
        *range(13, 23),
        42,
        *range(73, 102),
        111,
        *range(146, 151),
    }
)

# Shared resources contain separate protagonist branches. These records are
# tied to Setsuko by nearby first-person dialogue and route-specific terms.
SETSUKO_CONTEXT_ENTRY_IDS = frozenset(
    {
        "story/028/dialogue/01.15/0010",
        "story/029/dialogue/01.09/0014",
        "story/029/dialogue/02.02/0189",
        "story/029/dialogue/02.02/0194",
        "story/032/dialogue/01.16/0000",
        "story/032/dialogue/01.21/0003",
        "story/032/dialogue/02.03/0094",
        "story/035/dialogue/02.02/0009",
        "story/035/dialogue/02.02/0015",
        "story/035/dialogue/02.02/0037",
        "story/043/dialogue/02.01/0009",
        "story/048/dialogue/02.02/0098",
        "story/103/dialogue/01.05/0009",
        "story/103/dialogue/01.05/0011",
        "story/103/dialogue/01.10/0007",
        "story/116/dialogue/02.01/0009",
        "story/116/dialogue/02.01/0086",
        "story/122/dialogue/01.20/0001",
        "story/122/dialogue/02.01/0074",
        "story/140/dialogue/01.30/0001",
        "story/151/dialogue/01.07/0001",
        "story/152/dialogue/02.01/0006",
        "story/152/dialogue/02.01/0008",
    }
)
MIXED_PROTAGONIST_NEUTRAL_ENTRY_IDS = frozenset(
    {
        "story/025/dialogue/01.05/0000",
        "story/025/dialogue/01.07/0000",
        "story/103/dialogue/01.10/0001",
        "story/103/dialogue/01.11/0001",
        "story/104/dialogue/02.01/0211",
        "story/104/dialogue/02.01/0243",
    }
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class StoryDialogueTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = sorted(DIALOGUE_ROOT.glob("stage-*.json"))
        cls.documents = [(path, load_json(path)) for path in cls.paths]
        cls.release = load_json(RELEASE_PATH)

    def test_release_registers_the_complete_story_dialogue_corpus(self):
        actual_sources = {
            path.relative_to(PROJECT_ROOT).as_posix() for path in self.paths
        }
        registered_sources = {
            path
            for path in self.release["translation_sources"]
            if path.startswith("corpus/zh/story-dialogue/stage-")
        }
        self.assertEqual(len(actual_sources), 170)
        self.assertEqual(registered_sources, actual_sources)

        batch = next(
            item
            for item in self.release["coverage_plan"]
            if item["batch_id"] == "v1-story-dialogue"
        )
        self.assertEqual(batch["target_entry_count"], 83507)
        self.assertEqual(batch["status"], "draft_complete")

    def test_every_stage_document_has_stable_ids_and_complete_scope_counts(self):
        all_ids = set()
        total_entries = 0
        for path, document in self.documents:
            stage_index = int(path.stem.removeprefix("stage-"))
            entries = document["entries"]
            scope = document["scope"]
            source_hashes = {entry["source_text_sha256"] for entry in entries}

            self.assertEqual(document["schema_version"], 1, path.name)
            self.assertEqual(document["language"], "zh-Hans", path.name)
            self.assertEqual(document["batch_id"], "v1-story-dialogue", path.name)
            self.assertEqual(scope["domain"], "story", path.name)
            self.assertEqual(scope["kind"], "dialogue", path.name)
            self.assertEqual(scope["stage_indices"], [stage_index], path.name)
            self.assertEqual(scope["entry_count"], len(entries), path.name)
            self.assertEqual(
                scope["translated_entry_count"], len(entries), path.name
            )
            self.assertEqual(
                scope["unique_source_text_count"],
                len(source_hashes),
                path.name,
            )

            for entry in entries:
                self.assertRegex(
                    entry["id"],
                    rf"^story/{stage_index:03d}/dialogue/\d{{2}}\.\d{{2,3}}/\d{{4}}$",
                )
                self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
                self.assertNotIn("source_text", entry)
                self.assertNotIn(entry["id"], all_ids)
                self.assertIn(entry["editorial_status"], {"draft", "reviewed"})
                self.assertEqual(entry["translation_action"], "translate")
                self.assertTrue(entry["translation"])
                self.assertIsInstance(entry["glossary_refs"], list)
                self.assertIsInstance(entry["notes"], str)
                all_ids.add(entry["id"])
            total_entries += len(entries)

        self.assertEqual(total_entries, 83507)
        self.assertEqual(len(all_ids), total_entries)

    def test_compact_transition_route_and_bazaar_stages_are_registered(self):
        actual_stages = {
            int(path.stem.removeprefix("stage-")) for path in self.paths
        }
        self.assertTrue(
            {
                46,
                154,
                155,
                156,
                157,
                160,
                163,
                164,
                169,
                170,
                175,
                176,
                177,
                178,
                179,
                180,
            }.issubset(actual_stages)
        )

    def test_stage_040_feedback_dialogue_is_registered(self):
        stage_040 = next(
            document
            for path, document in self.documents
            if path.name == "stage-040.json"
        )
        translations = {
            entry["id"]: entry["translation"]
            for entry in stage_040["entries"]
        }
        hidden_branch_ids = {
            f"story/040/dialogue/01.21/{ordinal:04d}"
            for ordinal in range(7)
        }
        self.assertTrue(hidden_branch_ids.issubset(translations))
        self.assertEqual(
            translations["story/040/dialogue/01.21/0003"],
            "“哦哦！这份真心非常强烈！”",
        )
        self.assertEqual(
            translations["story/040/dialogue/02.01/0078"],
            "“看~招！趁你们退缩，继续上！”",
        )

    def test_translations_use_chinese_punctuation_and_contain_no_kana(self):
        for _path, document in self.documents:
            for entry in document["entries"]:
                translation = entry["translation"]
                self.assertIsNone(KANA_RE.search(translation), entry["id"])
                self.assertNotIn("...", translation, entry["id"])
                self.assertNotIn("「", translation, entry["id"])
                self.assertNotIn("」", translation, entry["id"])

    def test_repeated_source_text_has_one_decision_within_each_stage(self):
        for path, document in self.documents:
            by_source_hash = defaultdict(list)
            for entry in document["entries"]:
                by_source_hash[entry["source_text_sha256"]].append(entry)
            for source_hash, entries in by_source_hash.items():
                decisions = {
                    (
                        entry["translation"],
                        entry["translation_action"],
                        tuple(entry["glossary_refs"]),
                        tuple(entry.get("glossary_exceptions", [])),
                    )
                    for entry in entries
                }
                self.assertEqual(
                    len(decisions),
                    1,
                    f"{path.name}:{source_hash}",
                )

    def test_dynamic_protagonist_titles_match_route_gender(self):
        entries = {
            entry["id"]: entry["translation"]
            for _path, document in self.documents
            for entry in document["entries"]
        }

        for path, document in self.documents:
            stage_index = int(path.stem.removeprefix("stage-"))
            if stage_index in SETSUKO_EXCLUSIVE_STAGE_INDICES:
                for entry in document["entries"]:
                    self.assertIsNone(
                        DYNAMIC_MALE_TITLE_RE.search(entry["translation"]),
                        entry["id"],
                    )
            if stage_index in LAND_EXCLUSIVE_STAGE_INDICES:
                for entry in document["entries"]:
                    self.assertIsNone(
                        DYNAMIC_FEMALE_TITLE_RE.search(entry["translation"]),
                        entry["id"],
                    )

        for entry_id in SETSUKO_CONTEXT_ENTRY_IDS:
            self.assertIsNone(
                DYNAMIC_MALE_TITLE_RE.search(entries[entry_id]),
                entry_id,
            )
        for entry_id in MIXED_PROTAGONIST_NEUTRAL_ENTRY_IDS:
            self.assertIsNone(
                DYNAMIC_MALE_TITLE_RE.search(entries[entry_id]),
                entry_id,
            )
            self.assertIsNone(
                DYNAMIC_FEMALE_TITLE_RE.search(entries[entry_id]),
                entry_id,
            )

        self.assertEqual(
            entries["story/026/dialogue/02.01/0124"],
            "“欢迎来到三位一体城，\n　$f先生。”",
        )

    def test_player_choice_records_preserve_three_runtime_rows(self):
        entries = {
            entry["id"]: entry["translation"]
            for _path, document in self.documents
            for entry in document["entries"]
        }
        expected = {
            "story/002/dialogue/01.18/0008": (
                "“丹泽尔的选择”\n“1．撤出殖民卫星”\n"
                "“2．拦截被夺走的高达”"
            ),
            "story/007/dialogue/01.05/0013": (
                "“$n的选择”\n“1．听取队形说明”\n“2．跳过队形说明”"
            ),
            "story/016/dialogue/01.03/0005": (
                "“贝洛的选择”\n“1．听取队形说明”\n“2．跳过队形说明”"
            ),
            "story/035/dialogue/02.02/0035": (
                "“$n的选择”\n“1．加入莎拉队”\n“2．加入亚蒂特队”"
            ),
            "story/035/dialogue/02.02/0155": (
                "“$n的选择”\n“1．加入莎拉队”\n“2．加入亚蒂特队”"
            ),
            "story/110/dialogue/02.02/0087": (
                "“塔丽亚的选择”\n“1．作为$c战斗”\n“2．返回ZAFT”"
            ),
            "story/111/dialogue/02.02/0104": (
                "“塔丽亚的选择”\n“1．作为$c战斗”\n“2．返回ZAFT”"
            ),
            "story/140/dialogue/01.30/0095": (
                "“罗杰的选择”\n“1．舍弃记忆留在城里”\n"
                "“2．履行自己的职责”"
            ),
            "story/140/dialogue/01.39/0043": (
                "“罗杰的选择”\n“1．舍弃记忆留在城里”\n"
                "“2．履行自己的职责”"
            ),
            "story/142/dialogue/01.10/0008": (
                "“$n的选择”\n“1．希望一切恢复原样”\n“2．希望世界稳定”"
            ),
            "story/142/dialogue/01.14/0008": (
                "“$n的选择”\n“1．希望世界稳定”\n“2．无法自行决定”"
            ),
            "story/147/dialogue/01.10/0010": (
                "“$n的选择”\n“1．希望一切恢复原样”\n“2．希望世界稳定”"
            ),
            "story/147/dialogue/01.14/0010": (
                "“$n的选择”\n“1．希望世界稳定”\n“2．无法自行决定”"
            ),
            "story/154/dialogue/00.01/0152": (
                "“$n的选择”\n“1．希望加入太平洋部队”\n"
                "“2．希望加入加利亚部队”"
            ),
            "story/154/dialogue/00.01/0185": (
                "“兰德的选择”\n“1．希望加入太平洋部队”\n"
                "“2．希望加入加利亚部队”"
            ),
            "story/157/dialogue/00.01/0023": (
                "“布莱德的选择”\n“1．让$n前往直布罗陀基地”\n"
                "“2．让$n负责周边警戒”"
            ),
            "story/160/dialogue/00.01/0058": (
                "“$n的选择”\n“1．去找兰顿”\n“2．留下来看家”"
            ),
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )
        for entry_id, translation in expected.items():
            rows = translation.splitlines()
            self.assertEqual(len(rows), 3, entry_id)
            self.assertTrue(all(row.startswith("“") for row in rows), entry_id)
            self.assertTrue(all(row.endswith("”") for row in rows), entry_id)
            self.assertTrue(rows[1].startswith("“1．"), entry_id)
            self.assertTrue(rows[2].startswith("“2．"), entry_id)

    def test_every_glossary_reference_resolves(self):
        glossary_ids = {
            term["id"]
            for path in GLOSSARY_ROOT.glob("*.json")
            for term in load_json(path).get("terms", [])
        }
        references = {
            glossary_id
            for _path, document in self.documents
            for entry in document["entries"]
            for glossary_id in entry["glossary_refs"]
        }
        self.assertEqual(references - glossary_ids, set())

        stage_glossaries = {
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in GLOSSARY_ROOT.glob("story-dialogue-stage-*.json")
        }
        self.assertTrue(
            stage_glossaries.issubset(set(self.release["glossary_sources"]))
        )


if __name__ == "__main__":
    unittest.main()
