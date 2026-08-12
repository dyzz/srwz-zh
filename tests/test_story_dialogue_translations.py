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
        self.assertEqual(batch["target_entry_count"], 83500)
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

        self.assertEqual(total_entries, 83500)
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
