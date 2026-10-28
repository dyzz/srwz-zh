"""Regression cases from the 2026-10-28 LRPS2 story/battle mixed probes."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.compact_scopes import BATTLE, STORY, expand, collapse
from srwz.chinese_layout import (load_layout_profiles, battle_subtitle_line_widths,
    battle_subtitle_layout_issues, dialogue_line_widths, reflow_chinese_dialogue,
    dialogue_layout_issues, logical_dialogue_text, reflow_battle_subtitle, ChineseLayoutError)
from srwz.renderer_metrics import RendererState, text_extent


class DialogueSceneMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_layout_profiles(ROOT / 'config/text-layout/zh-layout-profiles.json')

    def test_scene_restoration_and_native_roundtrip(self):
        for step, height, metrics in [(21, 12, STORY), (22, 11, BATTLE)]:
            for run in ['MS-013', 'Gundam01', '013', '80%']:
                text = f'甲<z>{run}</z>乙'
                native = expand(text, metrics)
                self.assertTrue(native.endswith(f'<height:{height:02X}>乙'))
                self.assertEqual(collapse(native, metrics), text)
                extent = text_extent(text, default_advance_px=step)
                self.assertEqual(extent.advance_px, step * 2 + len(run) * 12)
                self.assertEqual(extent.state, RendererState(step, step))
                self.assertEqual(extent, text_extent(native, default_advance_px=step))
                self.assertEqual(dialogue_line_widths(text, default_advance_px=step),
                                 dialogue_line_widths(native, default_advance_px=step))

    def test_battle_counts_quotes_and_indent(self):
        valid = '“' + '国' * 20 + '\\n　' + '国' * 19 + '”'
        self.assertEqual(battle_subtitle_line_widths(valid), (462, 462))
        self.assertEqual(battle_subtitle_layout_issues(valid), ())
        self.assertTrue(battle_subtitle_layout_issues('“' + '国' * 20 + '”'))
        self.assertTrue(battle_subtitle_layout_issues('“甲\\n　' + '国' * 20 + '”'))
        self.assertTrue(battle_subtitle_layout_issues('“甲\\n乙”'))

    def test_compact_final_glyph_overhang_is_not_lost(self):
        # 15*22 + 11*12 = 462 advance, but the last glyph is 14px wide.
        text = '国' * 15 + '<z>ABCDEFGHIJK</z>'
        self.assertEqual(battle_subtitle_line_widths(text), (464,))
        self.assertTrue(battle_subtitle_layout_issues(text))

    def test_mixed_lrps2_probe_pixel_widths(self):
        text = '“准备攻击。\\n　目标<z>MS-013</z>已锁定，立即开火！”'
        self.assertEqual(battle_subtitle_line_widths(text), (132, 358))
        self.assertEqual(battle_subtitle_layout_issues(text), ())
        self.assertEqual(battle_subtitle_line_widths(text.replace('\\n', '\n')), (132, 358))
        text = '“目标<z>013</z>已锁定，能量<z>80%</z>！攻击！”'
        self.assertEqual(battle_subtitle_line_widths(text), (380,))

    def test_reflow_uses_each_surface_budget_and_keeps_author_scopes(self):
        text = '“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任务后返回基地！”'
        for name, step, budget in [('story_dialogue', 21, 483), ('battle_subtitle', 22, 462)]:
            profile = self.profiles[name]
            self.assertEqual(profile.default_advance_px, step)
            result = reflow_chinese_dialogue(text, profile=profile)
            self.assertEqual(logical_dialogue_text(result.text), text)
            self.assertIn('<z>MS-013</z>', result.text)
            self.assertNotIn('<width:', result.text)
            self.assertEqual(dialogue_layout_issues(result.text, profile=profile), ())
            for line in result.text.split('\n'):
                self.assertLessEqual(text_extent(line, default_advance_px=step).occupied_px, budget)
            if step == 22:
                self.assertEqual(battle_subtitle_layout_issues(result.text), ())

    def test_algorithm_matches_lrps2_mixed_fill_samples(self):
        source = '“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任务后返回基地！”'
        samples = {
            'story_dialogue': ('“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任务后\n　返回基地！”', (471, 147)),
            'battle_subtitle': ('“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任\n　务后返回基地！”', (446, 198)),
        }
        for key, (expected, widths) in samples.items():
            p = self.profiles[key]
            result = reflow_chinese_dialogue(source, profile=p)
            self.assertEqual(result.text, expected)
            self.assertEqual(tuple(text_extent(line, default_advance_px=p.default_advance_px).occupied_px
                                   for line in result.text.split('\n')), widths)

    def test_srvc_reflow_keeps_literal_newline_and_timing_row_count(self):
        text = '“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任务后\\n　返回基地！”'
        result = reflow_battle_subtitle(text, profile=self.profiles['battle_subtitle'])
        self.assertEqual(result.text.count('\\n'), 1)
        self.assertNotIn('\n', result.text)
        self.assertIn('<z>MS-013</z>', result.text)
        self.assertEqual(battle_subtitle_layout_issues(result.text), ())
        self.assertEqual(logical_dialogue_text(result.text.replace('\\n', '\n')),
                         logical_dialogue_text(text.replace('\\n', '\n')))
        with self.assertRaises(ChineseLayoutError):
            reflow_battle_subtitle('“' + '国'*30 + '”', profile=self.profiles['battle_subtitle'])

    def test_story_total_23_including_indent(self):
        profile = self.profiles['story_dialogue']
        text = '“' + '国' * 22 + '\n　' + '国' * 21 + '”'
        self.assertEqual(dialogue_layout_issues(text, profile=profile), ())
        self.assertTrue(dialogue_layout_issues(text + '国', profile=profile))


if __name__ == '__main__':
    unittest.main()
