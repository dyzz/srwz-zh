import unittest
from pathlib import Path

from tools.srwz.chinese_layout import (
    DEFAULT_CONTINUATION_LINE_WIDTH,
    DEFAULT_LINE_WIDTH,
    FORBIDDEN_LINE_END_CHARACTERS,
    FORBIDDEN_LINE_START_CHARACTERS,
    ChineseLayoutError,
    dialogue_line_widths,
    load_layout_profiles,
    logical_dialogue_text,
    partition_chinese_text,
    reflow_chinese_dialogue,
    reflow_chinese_paragraph,
    stage_keyword_link_spans,
    tokenize_dialogue,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ChineseLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_layout_profiles(
            PROJECT_ROOT / "config/text-layout/zh-layout-profiles.json"
        )

    def test_source_shaped_dialogue_reflows_to_the_runtime_limit(self):
        original = "“所谓新兵器评估\n　测试，和实战相比不过是\n　儿戏”"
        result = reflow_chinese_dialogue(original)
        self.assertEqual(
            result.text,
            "“所谓新兵器评估测试，\n　和实战相比不过是儿戏”",
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
        self.assertLessEqual(max(result.line_widths), DEFAULT_LINE_WIDTH)
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

    def test_repeated_interjection_can_start_after_sentence_break(self):
        original = "“啊……啊啊……啊啊啊！啊啊啊——！啊啊啊啊啊——！”"
        result = reflow_chinese_dialogue(original)
        self.assertEqual(logical_dialogue_text(result.text), original)
        self.assertLessEqual(len(result.line_widths), 3)
        self.assertLessEqual(max(result.line_widths), DEFAULT_LINE_WIDTH)

    def test_long_unregistered_latin_phrase_wraps_at_spaces(self):
        result = reflow_chinese_dialogue(
            "“称为‘Z Emergency Union of Terrestrial Human’。”"
        )
        self.assertEqual(
            logical_dialogue_text(result.text),
            "“称为‘Z Emergency Union of Terrestrial Human’。”",
        )
        self.assertLessEqual(len(result.line_widths), 3)
        self.assertLessEqual(max(result.line_widths), DEFAULT_LINE_WIDTH)

    def test_runtime_overflow_sample_reflows_with_continuation_margin(self):
        original = (
            "“别为这种无聊事高兴，托比！\n　他们应该就是为了引开提坦斯而行动的那支部队”"
        )
        result = reflow_chinese_dialogue(original)
        self.assertEqual(result.line_widths, (18, 18))
        self.assertEqual(
            result.text,
            "“别为这种无聊事高兴，托比！他们应该\n"
            "　就是为了引开提坦斯而行动的那支部队”",
        )

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

    def test_checked_in_profiles_keep_surface_widths_separate(self):
        self.assertEqual(
            self.profiles["story_dialogue"].maximum_width,
            DEFAULT_CONTINUATION_LINE_WIDTH,
        )
        self.assertEqual(
            self.profiles["story_dialogue"].first_line_maximum_width,
            DEFAULT_LINE_WIDTH,
        )
        self.assertEqual(self.profiles["library_robot"].maximum_width, 26)
        self.assertEqual(self.profiles["library_character"].maximum_width, 16)
        self.assertEqual(self.profiles["library_glossary"].maximum_width, 24)
        self.assertEqual(
            self.profiles["stage_scroll_overview"].maximum_width,
            29,
        )
        self.assertEqual(
            self.profiles["stage_scroll_overview"].line_count_mode,
            "minimum",
        )
        self.assertEqual(
            self.profiles["world_history_scroll"].maximum_width,
            22,
        )
        self.assertEqual(
            self.profiles["scenario_chart_overview"].maximum_lines,
            3,
        )

    def test_stage_keyword_controls_are_zero_width_and_body_is_atomic(self):
        text = "“去找《荣耀之星》吧”"
        self.assertEqual(dialogue_line_widths(text), (11,))
        self.assertEqual(
            dialogue_line_widths(text, stage_keyword_links=True),
            (9,),
        )
        tokens = tokenize_dialogue(
            "甲《荣耀之星》乙",
            stage_keyword_links=True,
        )
        keyword = next(token for token in tokens if token.atomic)
        self.assertEqual(keyword.text, "《荣耀之星》")
        self.assertEqual(keyword.width, 4)

    def test_stage_keyword_can_only_wrap_before_or_after_whole_span(self):
        lines = partition_chinese_text(
            "甲甲甲《荣耀之星》乙",
            line_width=4,
            max_lines=3,
            stage_keyword_links=True,
        )
        self.assertEqual(lines, ("甲甲甲", "《荣耀之星》", "乙"))
        with self.assertRaisesRegex(ChineseLayoutError, "indivisible term"):
            partition_chinese_text(
                "《一二三四五》",
                line_width=4,
                max_lines=2,
                allow_oversized_token_split=True,
                stage_keyword_links=True,
            )

    def test_stage_keyword_parser_rejects_malformed_controls(self):
        self.assertEqual(stage_keyword_link_spans("《奥古》")[0].body, "奥古")
        for malformed in ("《》", "《奥古", "奥古》", "《奥《古》》"):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ChineseLayoutError):
                    stage_keyword_link_spans(malformed)

    def test_exact_three_line_profile_balances_without_orphan_punctuation(self):
        original_lines = [
            "奥古袭击月面卢特提姆基地，",
            "荣耀之星驾驶巴尔戈拉迎击，",
            "却在战斗中卷入空间扭曲。",
        ]
        offsets = frozenset(
            {
                len(original_lines[0]),
                len(original_lines[0]) + len(original_lines[1]),
            }
        )
        result = reflow_chinese_paragraph(
            "".join(original_lines),
            profile=self.profiles["scenario_chart_overview"],
            exact_lines=3,
            preferred_break_offsets=offsets,
        )
        self.assertEqual(len(result.line_widths), 3)
        self.assertLessEqual(max(result.line_widths), 21)
        for line in result.text.splitlines():
            self.assertNotIn(line[0], FORBIDDEN_LINE_START_CHARACTERS)
            self.assertNotIn(line[-1], FORBIDDEN_LINE_END_CHARACTERS)

    def test_number_and_unit_remain_atomic_when_they_fit(self):
        result = partition_chinese_text(
            "距今12000年前曾经发生过战争。",
            line_width=10,
            max_lines=3,
        )
        self.assertNotIn("12000\n年", "\n".join(result))

    def test_quoted_sentence_can_wrap_inside_quote_marks(self):
        text = "“‘约定之地乃禁忌之地……任何人不得触碰’……”"
        result = partition_chinese_text(
            text,
            line_width=21,
            max_lines=3,
        )
        self.assertEqual("".join(result), text)
        self.assertTrue(all(line[0] not in "’”" for line in result[1:]))
        self.assertTrue(all(line[-1] not in "‘“" for line in result[:-1]))

    def test_profile_lexicon_does_not_split_common_word(self):
        original = "“那么，\n　从今以后我们这一团体称为‘$c’。”"
        result = reflow_chinese_dialogue(
            original,
            profile=self.profiles["story_dialogue"],
        )
        self.assertEqual(result.line_widths, (14, 12))
        self.assertIn("这一团体\n", result.text)
        self.assertNotIn("这一团\n　体", result.text)


if __name__ == "__main__":
    unittest.main()
