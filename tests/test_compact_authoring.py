import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.compact_authoring import compact_controlled_text, unscoped_text


class CompactAuthoringTests(unittest.TestCase):
    def test_native_controls_and_templates_are_exact(self):
        text = '“<color:03>MAX伤害10000，$n与＜ｔｍ＞击坠数＜／ｔｍ＞。”'
        result = compact_controlled_text(text, default_width=22)
        self.assertEqual(unscoped_text(result), text)
        self.assertIn('<color:03>', result)
        self.assertIn('＜ｔｍ＞击坠数＜／ｔｍ＞', result)
        self.assertEqual(compact_controlled_text(result, default_width=22), result)

    def test_restore_native_state(self):
        result = compact_controlled_text('<width:12><space:13>PLANT中文', default_width=22)
        self.assertIn('PLANT<width:12><space:13>中文', result)

    def test_percent_restores_space_first(self):
        result = compact_controlled_text('99%与0.5％', default_width=22)
        self.assertIn('99%<space:16><width:16>', result)
        self.assertIn('0.5％<space:16><width:16>', result)

    def test_cataloged_keyword_keeps_inner_text(self):
        result = compact_controlled_text('《PLANT》与PLANT', default_width=22, keyword_links=True)
        self.assertIn('<width:0E><space:0C>《PLANT》<width:16><space:16>', result)
        self.assertEqual(unscoped_text(result), '《PLANT》与PLANT')

    def test_exact_confirmed_symbol_boundary(self):
        text = 'Big O·Final Stage——！'
        result = compact_controlled_text(text, default_width=22, spans=[[0,len('Big O·Final Stage')]])
        self.assertIn('Big O·Final Stage<width:16>', result)
        self.assertEqual(unscoped_text(result), text)

    def test_mixed_keyword_label_keeps_catalog_identity(self):
        text = '《PLANT评议会议长》与PLANT'
        result = compact_controlled_text(text, default_width=22, keyword_links=True)
        self.assertIn('《PLANT评议会议长》', result)
        self.assertIn('与<width:0E><space:0C>PLANT', result)

    def test_template_overlap_rejected(self):
        with self.assertRaises(ValueError):
            compact_controlled_text('＜ｔｍ＞击坠数＜／ｔｍ＞100', default_width=22, spans=[[1,3]])

    def test_native_dimension_change_is_not_ignored(self):
        self.assertEqual(unscoped_text('<width:10>中文'), '<width:10>中文')


if __name__ == '__main__':
    unittest.main()
