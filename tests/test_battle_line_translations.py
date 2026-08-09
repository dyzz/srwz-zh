import hashlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT / "corpus" / "zh" / "menu" / "battle-lines.json"
)
BATTLE_GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "battle-lines-v1.json"
)
GENERAL_GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "terms-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class BattleLineTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            BATTLE_GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_batch_is_complete_and_keeps_the_source_line_break_shape(self):
        document = self.translations
        entries = document["entries"]
        self.assertEqual(document["batch_id"], "v1-menu-battle-lines")
        self.assertEqual(
            document["scope"],
            {
                "domain": "menu",
                "section": "Battle Lines",
                "entry_count": 297,
            },
        )
        self.assertEqual(len(entries), 297)

        for ordinal, entry in enumerate(entries):
            self.assertEqual(
                entry["id"],
                f"menu/Compdata/00/{ordinal:04d}",
            )
            self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(entry["editorial_status"], "draft")
            self.assertEqual(entry["translation_action"], "translate")
            self.assertNotIn("source_text", entry)
            self.assertTrue(entry["translation"].startswith("“"))
            self.assertTrue(entry["translation"].endswith("”"))
            self.assertNotIn("「", entry["translation"])
            self.assertNotIn("」", entry["translation"])
            self.assertNotIn("...", entry["translation"])
            self.assertIsNone(
                re.search(
                    r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff]",
                    entry["translation"],
                )
            )

        newline_counts = [
            entry["translation"].count("\n") for entry in entries
        ]
        self.assertEqual(Counter(newline_counts), {0: 66, 1: 227, 2: 4})
        newline_pattern = "".join(str(count) for count in newline_counts)
        self.assertEqual(
            hashlib.sha256(newline_pattern.encode("ascii")).hexdigest(),
            "5e1d240e8c909b0a62163dd006f51afa61ba315a2f755f62910377b0b6a04ced",
        )

    def test_high_risk_names_tone_and_source_typo_are_explicit(self):
        entries = {
            int(entry["id"].rsplit("/", 1)[1]): entry
            for entry in self.translations["entries"]
        }
        expected = {
            24: "“不行……！\n　Lady Command根本撑不住！”",
            25: "“怎、怎么会……！\n　我布莱竟然会败北！”",
            40: "“加冈总司令，请原谅我！”",
            69: "“哎呀呀……\n　又给加里森添工作了。”",
            80: "“我被打败了，吉隆——！”",
            87: "“我、我的陆行舰啊！！”",
            92: "“到此为止了吗……！\n　克瓦特罗机，撤退！”",
            97: "“唔！\n　不能让阿伽玛沉在这里！！”",
            99: "“太勉强了吗！？\n　爱玛机，后撤！”",
            114: "“再打下去，迦楼罗号就保不住了！\n　后撤！”",
            127: "“不好……！　拉迪修号要沉了！”",
            146: "“竟能让倒X屈膝……！\n　就称赞你们一句打得漂亮吧！”",
            151: "“自由号已经到极限了！\n　后撤！”",
            153: "“迪兰达尔议长究竟打算\n　用这股力量做什么……！”",
            162: "“可恶！　奥古\n　已经完全听命于ZAFT了吗！”",
            176: "“报告受损情况！\n　密涅瓦号开始后撤！”",
            179: "“为什么……！\n　他们为什么会和大天使号一起……！”",
            195: "“尼奥……真……？”",
            205: "“莎拉·柯达玛，现在逃生！\n　接下来拜托各位了！”",
            210: "“不妙……！\n　使出雅邦忍法，隐身术！”",
            219: "“我、我要是倒下了，\n　谁来管理西伯铁的运行时刻表！”",
            221: "“超限恶魔！\n　我要把灵魂献给你！”",
            237: "“对不起，桑德曼……\n　我……”",
            256: "“区区无翼者……呜！”",
            261: "“尼尔瓦修！\n　快……得赶快脱离！”",
            273: "“竟敢……！\n　竟敢把我们的月光号打成这样！！”",
            278: "“好，今天就到这里！\n　回去吧，兰顿！”",
            287: "“我是艾黛尔·贝尔纳尔……！\n　新世界的统治者！”",
            290: "“对不起！\n　雷本·盖涅拉尔，现在逃生！”",
        }
        self.assertEqual(
            {ordinal: entries[ordinal]["translation"] for ordinal in expected},
            expected,
        )
        self.assertIn("原文末尾重复", entries[110]["notes"])
        self.assertEqual(
            entries[195]["glossary_refs"],
            ["people/neo", "people/shinn"],
        )
        self.assertEqual(
            entries[290]["glossary_refs"],
            ["people/leben-general", "people/leben"],
        )

    def test_battle_glossary_is_separate_and_reviewable(self):
        terms = self.glossary["terms"]
        self.assertEqual(
            self.glossary["glossary_id"],
            "srwz-zh-battle-lines-v1",
        )
        self.assertEqual(len(terms), 39)
        self.assertEqual(len({term["id"] for term in terms}), 39)
        self.assertTrue(all(term["notes"] for term in terms))
        self.assertEqual(
            {term["status"] for term in terms},
            {"proposed", "researched"},
        )
        by_id = {term["id"]: term for term in terms}
        self.assertEqual(by_id["unit/turn-x"]["translation"], "逆X")
        self.assertEqual(
            by_id["unit/overdevil"]["translation"],
            "超限恶魔",
        )
        self.assertEqual(
            by_id["people/edel-bernal"]["status"],
            "proposed",
        )
        self.assertFalse(by_id["people/shinn"]["enforce"])

        general = json.loads(
            GENERAL_GLOSSARY_PATH.read_text(encoding="utf-8")
        )
        general_by_id = {term["id"]: term for term in general["terms"]}
        for term_id in (
            "organization/aeug",
            "organization/plant",
            "organization/zaft",
        ):
            self.assertIn("menu", general_by_id[term_id]["domains"])

    def test_v1_release_registers_complete_battle_line_batch(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/menu/battle-lines.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/battle-lines-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            batch
            for batch in release["coverage_plan"]
            if batch["batch_id"] == "v1-menu-battle-lines"
        )
        self.assertEqual(batch["target_entry_count"], 297)
        self.assertEqual(batch["status"], "draft_complete")


if __name__ == "__main__":
    unittest.main()
