"""SP HSFC has three 66-byte cells, independently of dialogue layout."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.chinese_layout import load_layout_profiles, fit_chinese_dialogue_layout


class SpHsfcLayoutTests(unittest.TestCase):
    def setUp(self):
        self.profiles = load_layout_profiles(ROOT / 'config/text-layout/zh-layout-profiles.json')
        self.profile = self.profiles['sp_hsfc_summary']

    def test_full_reviewed_synopses_fit_without_text_loss(self):
        texts = [
            '013特别小队在麦康奈尔基地与布兰少校等人会合，随后前往迎击出现在附近城镇的异星人部队。在当地的两名不合群者相助下获胜后，一架新型机和一位古怪人物又被送了过来。',
            '万丈与罗杰讲述了黑历史的终结与执行者的存在。了解其中毁灭与再生的含义后，众人前往日本，却遭到金卡拉姆袭击。击败倒X后，他们继续追踪神秘的超限人。',
        ]
        for text in texts:
            laid = fit_chinese_dialogue_layout(text, profile=self.profile,
                protected_terms=('麦康奈尔', '布兰少校', '金卡拉姆', '不合群者')).text
            lines = laid.split('\n')
            self.assertEqual(len(lines), 3)
            self.assertEqual(''.join(lines), text)
            self.assertTrue(all(len(line) * 2 + 1 <= 66 for line in lines))

    def test_native_capacity_boundary_and_overflow(self):
        laid = fit_chinese_dialogue_layout('甲' * 96, profile=self.profile).text
        self.assertEqual([len(line) for line in laid.split('\n')], [32, 32, 32])
        with self.assertRaises(ValueError):
            fit_chinese_dialogue_layout('甲' * 97, profile=self.profile)

    def test_generic_layout_is_not_expanded(self):
        self.assertEqual(self.profiles['scenario_chart_overview'].maximum_width, 21)


if __name__ == '__main__':
    unittest.main()
