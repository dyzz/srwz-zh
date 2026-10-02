"""Natural prose breaks, paragraph boundaries and per-row pixel budgets."""
import sys
import json
import unittest
from dataclasses import replace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
from srwz.chinese_layout import ChineseLayoutProfile,load_layout_profiles
from srwz.chinese_prose import logical_prose_text,reflow_chinese_prose
from srwz.renderer_metrics import compact_visible_runs
from srwz.text import CONTROL_NOTATION,encode_text,load_text_table
from build_library_v02_component import reflow_body
from write_frame_text import paragraphs,flow_synopsis


class BalancedProseTests(unittest.TestCase):
    def test_world_history_separators_keep_native_drawable_space_rows(self):
        profile=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['world_history_scroll']
        text='　甲\n\n　乙\n　\n　丙\n\n　丁'
        result=reflow_chinese_prose(text,profile=profile)
        self.assertEqual(result.text,'　甲\n　\n　乙\n　\n　丙\n　\n　丁')
        self.assertEqual(logical_prose_text(result.text),logical_prose_text(text))
        table=load_text_table(ROOT/'vendor/upstream-python/project/tbl_all.json')
        self.assertEqual(encode_text('\n　\n',table,terminate=False),b'\x0a\x81\x40\x0a')

    def test_world_history_corpus_retains_all_fourteen_native_separators(self):
        document=json.loads((ROOT/'corpus/zh/summary.json').read_text())
        separators={}
        for entry in document['entries']:
            lines=entry['translation'].split('\n')
            self.assertNotIn('',lines,entry['id'])
            count=lines.count('　')
            if count:separators[entry['id']]=count
        self.assertEqual(separators,{'summary/00/000':4,'summary/01/000':2,
                                    'summary/05/000':4,'summary/07/000':4})

    def test_sp_narration_keeps_native_single_and_multispace_rows(self):
        from srwz.summary import validate_scroll_placeholders
        profile=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['sp_narration_scroll']
        rows=json.loads((ROOT/'corpus/zh/special-disc/frame-text.json').read_text())['entries']
        for row in rows:
            if row.get('kind')!='narration':continue
            with self.subTest(entry=row['id']):
                validate_scroll_placeholders(row['source_text'],row['translation'],label=row['id'])
                result=reflow_chinese_prose(row['translation'],profile=profile,
                                           maximum_lines=len(row['source_text'].split('\n')))
                validate_scroll_placeholders(row['source_text'],result.text,label=row['id'])
        result=reflow_chinese_prose('　甲\n'+'　'*21+'\n　乙',profile=profile)
        self.assertIn('\n'+'　'*21+'\n',result.text)

    def test_generic_prose_keeps_existing_placeholder_rows_and_empty_rows(self):
        profile=ChineseLayoutProfile('prose',24,None,None,'minimum')
        text='　甲\n　　\n　乙\n\n　丙'
        self.assertEqual(reflow_chinese_prose(text,profile=profile).text,text)
        self.assertEqual(paragraphs('　甲\n　　\n　乙\n\n　丙',24),text.split('\n'))

    def test_reviewed_sp_authoring_rows_keep_native_placeholders(self):
        from srwz.summary import validate_scroll_placeholders
        rows=json.loads((ROOT/'corpus/zh/special-disc/reviewed-non-stage-text.json').read_text())['entries']
        targets=[row for row in rows if row.get('corpus_id','').startswith('narration/')]
        self.assertEqual(len(targets),10)
        for row in targets:
            with self.subTest(entry=row['id']):
                validate_scroll_placeholders(row['source_text'],row['translation'],label=row['id'])

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

    def test_balance_counts_first_row_indent_as_occupied_width(self):
        profile=ChineseLayoutProfile('prose',12,None,None,'minimum')
        result=reflow_chinese_prose('　　'+'甲'*18,profile=profile)
        self.assertEqual(result.line_widths_px,(240,240))
        self.assertEqual(result.text,'　　'+'甲'*8+'\n'+'甲'*10)

    def test_existing_controls_and_variables_survive_reflow_in_order(self):
        profile=ChineseLayoutProfile('prose',12,None,None,'minimum')
        text='　<color:01>甲甲$n乙乙<color:02>丙丙丙丙\n\n　丁丁丁'
        result=reflow_chinese_prose(text,profile=profile)
        self.assertEqual(CONTROL_NOTATION.findall(result.text),CONTROL_NOTATION.findall(text))
        self.assertEqual(logical_prose_text(result.text),logical_prose_text(text))
        self.assertIn('\n\n　',result.text)

    def test_selected_full_names_break_only_between_complete_english_words(self):
        profile=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['library_glossary']
        for phrase in ('Fast Acting Integrate Tactical Headquarters',
                       'Production Location Ally on Nexas Technology'):
            tagged=compact_visible_runs(phrase,default_advance_px=22,breakable_phrases=(phrase,))
            result,_=reflow_body(tagged,22,profile=replace(profile,maximum_width=22))
            visible=CONTROL_NOTATION.sub('',result)
            self.assertIn('\n',visible)
            self.assertEqual(visible.replace('\n',''),phrase)
            for line in visible.splitlines()[:-1]:
                self.assertTrue(line.endswith(' '),line)
            self.assertEqual(tagged.count('<width:0E>'),len(phrase.split()))

    def test_unselected_identifier_keeps_one_closed_compact_scope(self):
        tagged=compact_visible_runs('ABC-DEF',default_advance_px=22,
            breakable_phrases=('Fast Acting Integrate Tactical Headquarters',))
        self.assertEqual(tagged.count('<width:0E>'),1)

    def test_prose_profiles_protect_words_seen_at_real_preview_breaks(self):
        profiles=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')
        for key in ('library_glossary','world_history_scroll'):
            for term in ('结合性技术','特权阶级','超级机器人','反地球联邦组织'):
                result=reflow_chinese_prose('　'+'甲'*19+term+'乙'*18,profile=profiles[key])
                self.assertIn(term,result.text)


if __name__=='__main__':unittest.main()
