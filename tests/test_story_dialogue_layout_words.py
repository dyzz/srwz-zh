"""Story dialogue layout: unbroken word list, 21x3 profile, and corpus state."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))

from srwz.chinese_layout import (  # noqa: E402
    ChineseLayoutError,
    dialogue_layout_issues,
    fit_chinese_dialogue_layout,
    load_layout_profiles,
    load_unbroken_terms_file,
    logical_dialogue_text,
    reflow_chinese_dialogue,
)

PROFILES_PATH = PROJECT_ROOT / "config/text-layout/zh-layout-profiles.json"
WORDS_PATH = PROJECT_ROOT / "config/text-layout/zh-story-unbroken-words.json"


class StoryDialogueLayoutWordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]

    def test_profile_is_21_cells_by_3_lines_with_word_list(self) -> None:
        self.assertEqual(self.profile.first_line_maximum_width, 21)
        self.assertEqual(self.profile.maximum_width, 21)
        self.assertEqual(self.profile.maximum_lines, 3)
        terms = set(self.profile.unbroken_terms)
        self.assertIn("世界", terms)
        self.assertIn("帕普提马斯", terms)
        self.assertIn("艾岱尔·贝尔纳尔", terms)
        self.assertGreater(len(terms), 2000)

    def test_word_file_is_generated_from_checked_in_sources(self) -> None:
        import build_story_unbroken_words as generator

        document = json.loads(WORDS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(generator.render(generator.build_document()), generator.render(document))
        self.assertEqual(len(load_unbroken_terms_file(WORDS_PATH)),
                         len(document["common_words"]) + len(document["proper_names"]))

    def test_reflow_keeps_common_words_intact(self) -> None:
        # Without the word list the cheapest balanced break splits 炸弹.
        source = "“盖佐克把抓来的地球人身体里埋入炸\n　弹送回去，进行无差别恐怖袭击……”"
        result = reflow_chinese_dialogue(source, profile=self.profile)
        self.assertEqual(logical_dialogue_text(result.text), logical_dialogue_text(source))
        for line in result.text.split("\n"):
            self.assertNotIn(line.strip("　").rstrip(), ("炸",))
        self.assertIn("埋入\n　炸弹", result.text)
        self.assertLessEqual(max(result.line_widths), 21)

    def test_reflow_keeps_proper_names_intact(self) -> None:
        source = "“这就是新联邦军的准将，极·艾岱尔·贝尔纳尔所追求的世界吗……！”"
        result = fit_chinese_dialogue_layout(source, profile=self.profile)
        self.assertEqual(result.preserved_reason, "reflowed_to_fit")
        self.assertIn("极·艾岱尔·贝尔纳尔", result.text)
        self.assertLessEqual(len(result.line_widths), 3)

    def test_fitting_manual_breaks_are_preserved_even_inside_words(self) -> None:
        # fit_* only reflows when the text overflows; rebalancing existing
        # breaks is the corpus tool's job, not the builder's.
        source = "“第一行文字，\n　第二行文字。”"
        result = fit_chinese_dialogue_layout(source, profile=self.profile)
        self.assertEqual(result.preserved_reason, "already_fits")
        self.assertEqual(result.text, source)

    def test_overflow_without_legal_layout_raises(self) -> None:
        with self.assertRaises(ChineseLayoutError):
            fit_chinese_dialogue_layout("甲" * 64, profile=self.profile)

    def test_layout_issues_name_overflow_and_split_terms(self) -> None:
        clean = "“第一行文字，\n　第二行文字。”"
        self.assertEqual(dialogue_layout_issues(clean, profile=self.profile), ())
        wide = "“" + "甲" * 21 + "”"
        self.assertEqual(
            dialogue_layout_issues(wide, profile=self.profile),
            ("first line 23 cells exceeds 21",),
        )
        split = "“盖佐克把抓来的地球人身体里埋入炸\n　弹送回去，进行无差别恐怖袭击……”"
        self.assertEqual(
            dialogue_layout_issues(split, profile=self.profile),
            ("line break inside '炸弹'",),
        )
        four = "“一。\n　二。\n　三。\n　四。”"
        self.assertIn("4 lines exceed 3", dialogue_layout_issues(four, profile=self.profile))

    def test_continuation_indent_gate_and_repair(self) -> None:
        import rebalance_story_dialogue as tool

        for source in ("“第一句。\n第二句。”", "“第一句。\n 第二句。”", "“第一句。\n　 第二句。”"):
            with self.subTest(source=source):
                self.assertIn(
                    "line 2 lacks one full-width continuation indent",
                    dialogue_layout_issues(source, profile=self.profile),
                )
                fixed = tool.normalize_indent(source, self.profile.continuation_indent)
                self.assertEqual(fixed, "“第一句。\n　第二句。”")
                self.assertEqual(logical_dialogue_text(fixed), logical_dialogue_text(source))
                self.assertEqual(dialogue_layout_issues(fixed, profile=self.profile), ())

        choices = "“要怎么做？”\n“1．继续”\n“2．返回”"
        self.assertEqual(dialogue_layout_issues(choices, profile=self.profile), ())
        self.assertEqual(tool.normalize_indent(choices, self.profile.continuation_indent), choices)
        quoted_prose = "“他说完了。”\n“然后我们出发。”"
        self.assertIn(
            "line 2 lacks one full-width continuation indent",
            dialogue_layout_issues(quoted_prose, profile=self.profile),
        )

    def test_check_tool_reports_no_problems_for_current_corpus(self) -> None:
        import check_story_dialogue_layout as checker

        self.assertEqual(checker.check(None), [])

    def test_corpus_has_no_break_inside_unbroken_terms(self) -> None:
        import rebalance_story_dialogue as tool

        # Keyword-link status comes from the Japanese source, as in the builder.
        link_ids = tool.keyword_link_ids()
        self.assertTrue(link_ids)
        # Tutorial dialogue quotes the game title with plain book-title marks.
        self.assertNotIn("story/186/dialogue/02.01/0012", link_ids)
        for path in sorted((PROJECT_ROOT / "corpus/zh/story-dialogue").glob("stage-*.json")):
            entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
            for entry in entries:
                text = entry["translation"]
                links = entry["id"] in link_ids
                with self.subTest(entry=entry["id"]):
                    self.assertEqual(
                        tool.split_terms(text, self.profile, stage_keyword_links=links), []
                    )
                    self.assertTrue(tool.fits(text, self.profile, stage_keyword_links=links))


if __name__ == "__main__":
    unittest.main()
