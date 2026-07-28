import json
import unittest
from collections import Counter
from pathlib import Path

from tools.srwz.chinese_layout import (
    ChineseLayoutError,
    dialogue_line_widths,
    logical_dialogue_text,
    partition_chinese_text,
    reflow_chinese_dialogue,
)


class ChineseLayoutTests(unittest.TestCase):
    def test_short_source_shaped_dialogue_collapses_to_one_line(self):
        original = "“所谓新兵器评估\n　测试，和实战相比不过是\n　儿戏”"
        result = reflow_chinese_dialogue(original)
        self.assertEqual(
            result.text,
            "“所谓新兵器评估测试，和实战相比不过是儿戏”",
        )
        self.assertEqual(
            logical_dialogue_text(result.text), logical_dialogue_text(original)
        )

    def test_prefers_chinese_sentence_boundary_and_indents_continuation(self):
        original = "“隶属月面驻军战技研究班\n　‘荣耀之星’。\n　我在10天前到任”"
        result = reflow_chinese_dialogue(
            original,
            protected_terms=("月面驻军战技研究班", "荣耀之星"),
        )
        self.assertEqual(
            result.text,
            "“隶属月面驻军战技研究班‘荣耀之星’。\n　我在10天前到任”",
        )
        self.assertEqual(result.line_widths, (19, 9))

    def test_player_name_token_reserves_six_runtime_cells(self):
        text = "“你可是背负着‘荣耀之星’的招牌，$n应该堂堂正正一点”"
        result = reflow_chinese_dialogue(
            text,
            protected_terms=("荣耀之星",),
        )
        self.assertEqual(len(result.line_widths), 2)
        self.assertLessEqual(max(result.line_widths), 24)
        self.assertEqual(dialogue_line_widths("“$n！”"), (9,))

    def test_does_not_split_protected_name_or_lead_with_punctuation(self):
        result = reflow_chinese_dialogue(
            "“我们将与阿斯兰·萨拉一同追击敌舰并夺回军械库一号”",
            protected_terms=("阿斯兰·萨拉", "军械库一号"),
            line_width=16,
        )
        self.assertIn("阿斯兰·萨拉", result.text)
        self.assertNotIn("阿斯兰·\n", result.text)
        self.assertTrue(
            all(
                line.lstrip("　")[0] not in "，。！？；：、”’）》】"
                for line in result.text.splitlines()
            )
        )

    def test_does_not_split_common_words_or_lead_with_modal_particle(self):
        result = reflow_chinese_dialogue(
            "“我们正在开发中距离兵器项目，这不是儿戏啊”",
            line_width=12,
        )
        for word in ("我们", "开发", "中距离", "兵器", "项目", "不是"):
            self.assertTrue(
                any(word in line for line in result.text.splitlines()),
                word,
            )
        self.assertFalse(
            any(
                line.lstrip("　 ").startswith("啊")
                for line in result.text.splitlines()[1:]
            )
        )

    def test_preserves_location_cards_and_separate_choice_lines(self):
        location = "　　　　～军械库一号　船坞附近～"
        choices = "“丹泽尔选择”\n“1．撤出殖民卫星”\n“2．拦截被夺走的高达”"
        self.assertEqual(
            reflow_chinese_dialogue(location).text,
            location,
        )
        self.assertEqual(
            reflow_chinese_dialogue(choices).text,
            choices,
        )

    def test_fails_closed_when_three_lines_are_not_enough(self):
        with self.assertRaisesRegex(ChineseLayoutError, "more than 3 lines"):
            reflow_chinese_dialogue("“" + "甲" * 80 + "”")

    def test_partition_without_dialogue_indentation_preserves_logical_text(self):
        lines = partition_chinese_text(
            "民众积压的焦虑彻底爆发，最终演变为暴动。",
            protected_terms=("暴动",),
            line_width=16,
            max_lines=3,
        )
        self.assertEqual("".join(lines), "民众积压的焦虑彻底爆发，最终演变为暴动。")
        self.assertLessEqual(max(map(len, lines)), 16)
        self.assertTrue(all(not line.startswith("　") for line in lines))
        self.assertTrue(any("暴动" in line for line in lines))

    def test_partition_rejects_embedded_authoring_newline(self):
        with self.assertRaisesRegex(ChineseLayoutError, "one non-empty logical line"):
            partition_chinese_text(
                "第一行\n第二行",
                line_width=16,
                max_lines=2,
            )


class FirstFiveChineseLayoutIntegrationTests(unittest.TestCase):
    def test_committed_first_five_dialogue_is_canonical(self):
        project_root = Path(__file__).resolve().parents[1]
        release = json.loads(
            (project_root / "corpus/releases/v1.json").read_text(encoding="utf-8")
        )
        protected_terms = set()
        for raw_path in release["glossary_sources"]:
            glossary = json.loads((project_root / raw_path).read_text(encoding="utf-8"))
            protected_terms.update(
                term["translation"]
                for term in glossary["terms"]
                if len(term["translation"]) > 1
            )

        distribution = Counter()
        total_lines = 0
        for stage_index in range(1, 6):
            document = json.loads(
                (
                    project_root
                    / "corpus/zh/story-dialogue"
                    / f"stage-{stage_index:03d}.json"
                ).read_text(encoding="utf-8")
            )
            for entry in document["entries"]:
                result = reflow_chinese_dialogue(
                    entry["translation"],
                    protected_terms=protected_terms,
                )
                self.assertEqual(
                    result.text,
                    entry["translation"],
                    entry["id"],
                )
                line_count = entry["translation"].count("\n") + 1
                distribution[line_count] += 1
                total_lines += line_count

        self.assertEqual(
            distribution,
            {1: 1266, 2: 441, 3: 4},
        )
        self.assertEqual(total_lines, 2160)


if __name__ == "__main__":
    unittest.main()
