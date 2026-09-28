"""Natural prose breaks, paragraph boundaries and per-row pixel budgets."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
from srwz.chinese_layout import ChineseLayoutProfile,load_layout_profiles
from srwz.chinese_prose import logical_prose_text,reflow_chinese_prose
from srwz.renderer_metrics import compact_visible_runs
from srwz.text import CONTROL_NOTATION
from build_library_v02_component import reflow_body
from write_frame_text import paragraphs,flow_synopsis


class BalancedProseTests(unittest.TestCase):
    def test_short_character_body_breaks_at_sentence_before_name_phrase(self):
        profile=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['library_character']
        tagged=compact_visible_runs('贝克的部下。与Dove一起帮助贝克越狱。',default_advance_px=22)
        text,_=reflow_body(tagged,16,profile=profile)
        self.assertTrue(text.startswith('<width:16><space:16>'))
        self.assertEqual(CONTROL_NOTATION.sub('',text),'贝克的部下。\n与Dove一起帮助贝克越狱。')

    def test_balances_within_paragraph_without_moving_paragraph_starts(self):
        profile=ChineseLayoutProfile('prose',12,None,None,'minimum')
        text='　'+'甲'*8+'\n'+'乙'*10+'\n\n　'+'丙'*7
        result=reflow_chinese_prose(text,profile=profile)
        self.assertEqual(logical_prose_text(result.text),logical_prose_text(text))
        first=result.text.split('\n\n')[0].splitlines()
        self.assertLessEqual(abs(len(first[0])-len(first[1])),2)
        self.assertEqual(result.paragraph_count,2)
        self.assertIn('\n\n　',result.text)

    def test_indent_reduces_only_first_row_budget(self):
        profile=ChineseLayoutProfile('indent',10,9,None,'minimum',line_packing='fill')
        result=reflow_chinese_prose('　'+'甲'*19,profile=profile,maximum_lines=2)
        self.assertEqual(tuple(len(x) for x in result.text.splitlines()),(10,10))
        self.assertEqual(result.line_widths_px,(240,240))

    def test_equal_rows_do_not_split_known_words(self):
        result=flow_synopsis('　'+'甲'*24+'战斗结束后，双方恢复精神平衡。')
        self.assertFalse(any(line.endswith('结') or line.startswith('束') for line in result.splitlines()))
        self.assertTrue(any('精神' in line for line in result.splitlines()))

    def test_scroll_paragraphs_offer_balanced_rows(self):
        rows=paragraphs('甲'*40,22,line_packing='balanced')
        self.assertEqual([len(row) for row in rows],[20,20])
        self.assertEqual(''.join(rows),'甲'*40)


if __name__=='__main__':unittest.main()
