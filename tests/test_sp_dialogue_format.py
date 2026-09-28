import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/editorial_review')]
from normalize_sp_dialogue import (
    STRUCTURAL, ending_mark, line_edge_issues, normalize_battle,
    normalize_dialogue, profile_for, visible_ascii_identity,
)
from srwz.chinese_layout import dialogue_layout_issues, load_layout_profiles, logical_dialogue_text


class SpDialogueFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['story_dialogue']

    def test_native_number_tokens_survive_identity_and_reflow(self):
        text = '“敌机击坠数为＜ｔｍ＞击坠数＜／ｔｍ＞！拉迪修及其他舰艇的突击即将开始！”'
        after, _, _ = normalize_dialogue(text, self.profile)
        self.assertEqual(STRUCTURAL.findall(text), STRUCTURAL.findall(after))
        self.assertEqual(logical_dialogue_text(after), text)

    def test_real_split_name_is_repaired_without_wording_change(self):
        text = '“听说这台加布斯雷是西罗\n　克上校亲自设计的机体。”'
        after, _, _ = normalize_dialogue(text, self.profile)
        self.assertEqual(logical_dialogue_text(after), logical_dialogue_text(text))
        self.assertEqual(dialogue_layout_issues(after, profile=self.profile), ())
        self.assertIn('西罗克', after)

    def test_number_and_time_are_atomic_and_repeat_run_is_stable(self):
        text = '“测试时间是两天后的18:\n　00……地点是X13Y24。”'
        after, _, _ = normalize_dialogue(text, self.profile)
        self.assertIn('18:00', after)
        self.assertIn('X13Y24', after)
        self.assertEqual(normalize_dialogue(after, self.profile)[0], after)

    def test_visible_digits_change_width_identity_but_not_value(self):
        text = '“目标是在作战时间４分钟内击坠１５０架MS。”'
        after, _, _ = normalize_dialogue(text, self.profile)
        self.assertEqual(logical_dialogue_text(after), visible_ascii_identity(text))
        self.assertIn('4分钟', after)
        self.assertIn('150架', after)

    def test_battle_question_keeps_native_break_and_indentation(self):
        text = '“果然，\\n　目标锁定在密涅瓦号上了吗”'
        after, _ = normalize_battle(text)
        self.assertEqual(after, '“果然，\\n　目标锁定在密涅瓦号上了吗？”')
        self.assertEqual(after.count('\\n'), text.count('\\n'))

    def test_silence_waves_and_quoted_titles_have_no_added_period(self):
        for text in ['“………………”', '“等等～”', '（……）', '另一面“记录”']:
            self.assertFalse(ending_mark(text))
        self.assertEqual(normalize_dialogue('“………………”', self.profile)[0], '“………………”')


if __name__ == '__main__':
    unittest.main()
