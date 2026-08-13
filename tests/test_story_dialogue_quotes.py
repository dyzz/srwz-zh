import unittest
from pathlib import Path

from tools.audit_story_dialogue_quotes import audit
from tools.srwz.story_quotes import (
    KEYWORD_EXEMPT,
    PARENTHETICAL,
    SPOKEN_QUOTE,
    UNQUOTED,
    evaluate_story_quote,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StoryDialogueQuoteTests(unittest.TestCase):
    def test_source_driven_quote_policy(self):
        cases = (
            ("「了解」", "“明白”", "甲", False, SPOKEN_QUOTE),
            ("（まさか…）", "（怎么会……）", "甲", False, PARENTHETICAL),
            ("艦内　格納庫", "舰内　机库", "", False, UNQUOTED),
            ("「《用語》だ」", "“《术语》啊”", "甲", True, KEYWORD_EXEMPT),
        )
        for source, translation, speaker, keyword, expected in cases:
            with self.subTest(source=source):
                verdict = evaluate_story_quote(
                    source,
                    translation,
                    speaker,
                    has_keyword_links=keyword,
                )
                self.assertEqual(verdict.expected, expected)
                self.assertTrue(verdict.exact)

    def test_all_170_stages_have_exact_outer_punctuation(self):
        report = audit(PROJECT_ROOT / "config/story-component.json")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["stage_count"], 170)
        self.assertEqual(report["entry_count"], 83507)
        self.assertEqual(report["runtime_keyword_link_count"], 122)
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["source_hash_mismatch_count"], 0)
        self.assertTrue(report["counts_exact"])


if __name__ == "__main__":
    unittest.main()
