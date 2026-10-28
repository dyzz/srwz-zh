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
    def test_maximum_width_ignores_old_wraps_and_short_tail(self):
        profile=ChineseLayoutProfile('prose',12,None,None,'minimum',
                                     line_packing='max_width',minimum_line_width=8)
        result=reflow_chinese_prose('　'+'甲'*7+'\n'+'乙'*6,profile=profile)
        self.assertEqual(result.text,'　'+'甲'*7+'乙'*4+'\n'+'乙'*2)
        self.assertEqual(result.line_widths_px,(288,48))
        self.assertEqual(reflow_chinese_prose(result.text,profile=profile).text,result.text)

    def test_maximum_width_still_obeys_punctuation_and_complete_words(self):
        profile=ChineseLayoutProfile('prose',10,None,None,'minimum',
                                     line_packing='max_width',unbroken_terms=('超级机器人',))
        self.assertEqual(reflow_chinese_prose('甲'*6+'超级机器人乙乙',profile=profile).text,
                         '甲'*6+'\n超级机器人乙乙')
        result=reflow_chinese_prose('甲'*10+'。乙乙',profile=profile).text
        self.assertFalse(any(row.startswith('。') for row in result.splitlines()))

    def test_flow_and_scroll_profiles_fill_but_library_keeps_balancing(self):
        profiles=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')
        for key,width in (('stage_scroll_overview',30),('world_history_scroll',22),('sp_narration_scroll',23)):
            self.assertEqual(profiles[key].line_packing,'max_width')
            self.assertEqual(profiles[key].maximum_width,width)
        self.assertEqual(profiles['library_character'].line_packing,'balanced')

    def test_flow_fills_first_row_even_inside_a_name(self):
        profile=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['stage_scroll_overview']
        text='　此前一直推动与月之民谈判的领主古恩，为打破僵局而采取了下一步行动。'
        fitted=reflow_chinese_prose(text,profile=profile).text
        self.assertEqual(fitted.replace('\n',''),text)
        self.assertEqual(len(fitted.split('\n')[0]),30)

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
        self.assertTrue(text.startswith('<width:15><space:15>'))
        self.assertEqual(CONTROL_NOTATION.sub('',text),'贝克的部下。与Dove\n一起帮助贝克越狱。')

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

    def test_flow_does_not_protect_word_boundaries(self):
        result=flow_synopsis('　'+'甲'*26+'战斗结束后，双方恢复精神平衡。')
        self.assertEqual(len(result.split('\n')[0]),30)
        self.assertIn('结\n束',result)

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
                self.assertIn(term,result.text.replace('\n',''))


if __name__=='__main__':unittest.main()
