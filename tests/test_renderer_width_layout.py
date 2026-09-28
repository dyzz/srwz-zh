"""Validate line fitting against renderer controls, independent of encoding width."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.chinese_layout import (ChineseLayoutProfile, ChineseLayoutError,
    partition_chinese_text, reflow_chinese_dialogue, dialogue_line_widths,
    fit_chinese_dialogue_layout, logical_dialogue_text, tokenize_dialogue)
from srwz.renderer_metrics import RendererState, text_extent, compact_latin_runs


class RendererWidthLayoutTest(unittest.TestCase):
    def setUp(self):
        self.profile = ChineseLayoutProfile('sp-probe', 10, None, 3, 'minimum',
            continuation_indent='　', default_advance_px=22)

    def test_storage_character_width_does_not_determine_advance(self):
        a = text_extent('<width:0C><space:0C>MAX 56000', default_advance_px=22)
        b = text_extent('<width:0C><space:0C>ＭＡＸ　５６０００', default_advance_px=22)
        self.assertEqual(a, b)
        self.assertEqual(a.advance_px, 108)
        self.assertEqual(text_extent('<width:0C>MAX',default_advance_px=22).advance_px,66)

    def test_restore_changes_chinese_metrics(self):
        text = '<width:0E><space:0C>Black Gale<width:16><space:16>中文'
        extent = text_extent(text,default_advance_px=22)
        self.assertEqual(extent.advance_px, 164)
        self.assertEqual(extent.occupied_px,164)
        self.assertEqual(extent.state,RendererState(22,22))

    def test_glyph_overhang_is_included_at_boundary(self):
        text = '<width:0E><space:0C>AB'
        self.assertEqual(text_extent(text,default_advance_px=22).occupied_px,26)
        profile=replace(self.profile,maximum_width=1)
        with self.assertRaises(ChineseLayoutError):
            fit_chinese_dialogue_layout(text,profile=profile)

    def test_compact_long_latin_can_fit_when_plain_cannot(self):
        plain='“ABCDEFGHIJKLMNO，中文。”'
        tagged=compact_latin_runs(plain,default_advance_px=22)
        profile=replace(self.profile,maximum_width=15,maximum_lines=1)
        with self.assertRaises(ChineseLayoutError):fit_chinese_dialogue_layout(plain,profile=profile)
        fitted=fit_chinese_dialogue_layout(tagged,profile=profile)
        self.assertEqual(fitted.text,tagged)
        self.assertLessEqual(fitted.line_widths[0],15)

    def test_reflow_conserves_tags_and_punctuation(self):
        tagged=compact_latin_runs('“我们今天遇到了Black Gale，那是一支新的行动队。”',default_advance_px=22)
        result=reflow_chinese_dialogue(tagged,profile=self.profile)
        self.assertEqual(logical_dialogue_text(result.text),tagged)
        self.assertTrue(all(w<=10 for w in result.line_widths))
        for line in result.text.splitlines():
            self.assertFalse(line.rstrip().endswith('<width:0E><space:0C>'))
            self.assertFalse(line.lstrip('　').startswith(('，','。”')))

    def test_metric_state_carries_across_physical_lines(self):
        self.assertEqual(dialogue_line_widths('<space:0C>AB\n　CD<space:16>中',default_advance_px=22),(2,3))

    def test_only_advance_controls_change_fitting(self):
        profile=replace(self.profile,maximum_width=5,maximum_lines=1)
        with self.assertRaises(ChineseLayoutError):
            fit_chinese_dialogue_layout('<width:0C>ABCDEFGHI',profile=profile)
        self.assertEqual(fit_chinese_dialogue_layout('<width:0C><space:0C>ABCDEFGHI',profile=profile).line_widths,(5,))

    def test_authoring_preserves_short_ids_and_numeric_values(self):
        text='Z高达、MS、40000、56000；MAX、ＺＡＦＴ；Black Gale'
        tagged=compact_latin_runs(text,default_advance_px=22)
        self.assertTrue(tagged.startswith('Z高达、MS、40000、56000；'))
        self.assertIn('<width:0E><space:0C>MAX<width:16><space:16>',tagged)
        self.assertIn('<width:0E><space:0C>ZAFT<width:16><space:16>',tagged)
        self.assertIn('<width:0E><space:0C>Black Gale<width:16><space:16>',tagged)
        self.assertEqual(tagged.count('<width:0E>'),3)
        with self.assertRaises(ValueError):compact_latin_runs('<color:01>Black Gale',default_advance_px=22)

    def test_closed_identifier_scope_is_not_split_between_words(self):
        text=compact_latin_runs('Black Gale',default_advance_px=22)
        tokens=tokenize_dialogue(text,default_advance_px=22)
        self.assertEqual(len(tokens),1)
        self.assertTrue(tokens[0].atomic)
        with self.assertRaises(ChineseLayoutError):
            fit_chinese_dialogue_layout(text,profile=replace(self.profile,maximum_width=5))

    def test_hyphenated_identifier_has_one_closed_scope(self):
        for identifier in ('BIG-DUO', 'MA-BAR72', 'M7045/F7'):
            text=compact_latin_runs(identifier+'中文',default_advance_px=22)
            self.assertEqual(text, '<width:0E><space:0C>'+identifier+'<width:16><space:16>中文')
            tokens=tokenize_dialogue(text,default_advance_px=22)
            self.assertTrue(tokens[0].atomic)
            self.assertIn(identifier,tokens[0].text)

    def test_unicode_punctuation_does_not_join_latin_scopes(self):
        text=compact_latin_runs('BIG、DUO',default_advance_px=22)
        self.assertEqual(text.count('<width:0E>'),2)
        self.assertIn('<width:16><space:16>、<width:0E>',text)

    def test_authoring_retains_alignment_outside_latin_runs(self):
        text='　ＭＳ，Black　Gale\n　第二行'
        result=compact_latin_runs(text,default_advance_px=22)
        self.assertTrue(result.startswith('　MS，'))
        self.assertTrue(result.endswith('\n　第二行'))
        self.assertIn('Black Gale',result)

    def test_invalid_dimensions_fail_closed(self):
        for value in ('00','40','FF'):
            with self.assertRaises(ValueError):text_extent(f'<space:{value}>AB',default_advance_px=22)

    def test_placeholder_reservation_uses_current_advance(self):
        e=text_extent('<width:0C><space:0C>$n<space:16>中',default_advance_px=22)
        self.assertEqual(e.advance_px,94)

if __name__=='__main__':unittest.main()
