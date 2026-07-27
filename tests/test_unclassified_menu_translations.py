import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT / "corpus" / "zh" / "menu" / "unclassified.json"
)
MENU_GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "menu-terms-v1.json"
)
GENERAL_GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "terms-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class UnclassifiedMenuTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.menu_glossary = json.loads(
            MENU_GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_batch_has_every_stable_id_and_explicit_preserve_decision(self):
        entries = self.translations["entries"]
        self.assertEqual(
            self.translations["batch_id"],
            "v1-menu-unclassified",
        )
        self.assertEqual(self.translations["scope"]["entry_count"], 382)
        self.assertEqual(len(entries), 382)
        self.assertEqual(
            sum(
                entry.get("translation_action") == "preserve"
                for entry in entries
            ),
            68,
        )
        for ordinal, entry in enumerate(entries):
            self.assertEqual(
                entry["id"],
                f"menu/SLPS/00/{ordinal:04d}",
            )
            self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(entry["editorial_status"], "draft")
            if entry.get("translation_action") == "preserve":
                self.assertTrue(entry["notes"])

    def test_high_risk_fragments_and_terms_remain_explicit(self):
        entries = {
            int(entry["id"].rsplit("/", 1)[1]): entry
            for entry in self.translations["entries"]
        }
        expected = {
            71: "钢狮",
            72: "节子",
            73: "小原",
            83: "刀z%s〜",
            94: "进行TRI攻击时，\n无法选择攻击目标。",
            150: "是否切换为TRI队形？",
            193: "尚未设置页面内的列表数量Yo。\n",
            259: "话为止已通关",
            262: "　流浪的修理工",
            263: "　太空先锋",
            296: "精神指令目标",
            360: "・中断保存",
            381: "读取",
        }
        self.assertEqual(
            {ordinal: entries[ordinal]["translation"] for ordinal in expected},
            expected,
        )
        self.assertEqual(
            entries[83]["translation_action"],
            "preserve",
        )
        self.assertIn(
            "system/sp",
            entries[296]["glossary_exceptions"],
        )
        self.assertIn(
            "system/tri-attack",
            entries[94]["glossary_refs"],
        )
        self.assertIn(
            "system/tri-formation",
            entries[150]["glossary_refs"],
        )

        general_glossary = json.loads(
            GENERAL_GLOSSARY_PATH.read_text(encoding="utf-8")
        )
        ohara = next(
            term
            for term in general_glossary["terms"]
            if term["id"] == "people/ohara"
        )
        self.assertEqual(ohara["translation"], "小原")

    def test_v1_release_registers_complete_unclassified_batch(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/menu/unclassified.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/menu-terms-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            batch
            for batch in release["coverage_plan"]
            if batch["batch_id"] == "v1-menu-unclassified"
        )
        self.assertEqual(batch["target_entry_count"], 382)
        self.assertEqual(batch["status"], "draft_complete")
        self.assertEqual(len(self.menu_glossary["terms"]), 20)


if __name__ == "__main__":
    unittest.main()
