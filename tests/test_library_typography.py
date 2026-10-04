"""Encyclopedia surface metrics and source-bound SP supplementation."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.library_typography import library_typography
from srwz.text import CONTROL_NOTATION
from build_library_v02_component import reflow_body
from special_disc.writeback.shared_library import authoring

class LibraryTypographyTests(unittest.TestCase):
    def test_work_title_restores_native_metadata_and_preserves_english(self):
        text='机动战士高达SEED DESTINY中文'
        result=library_typography(text,'PRDC')
        self.assertIn('<width:0E><space:0A><height:0A>SEED DESTINY<width:15><space:15><height:0A>中文', result)
        self.assertEqual(CONTROL_NOTATION.sub('', result), text)
        self.assertEqual(library_typography(result,'PRDC'), result)

    def test_short_digits_sigma_and_brackets_use_closed_scopes(self):
        for text,tag,w,h in [('超重神GRAVION ZweiΣ','PRDC','15','0A'),
                            ('钢铁齿轮（LS）','RBTN','12','0A'),
                            ('头翅（托马）','CHFN','12','0A'),
                            ('20米中文','DSCR','16',None)]:
            result=library_typography(text,tag)
            self.assertEqual(CONTROL_NOTATION.sub('',result),text)
            self.assertIn('<width:0E><space:' + ('0A' if tag=='PRDC' else '0C') + '>',result)
            self.assertIn(f'<width:{w}><space:{w}>' + (f'<height:{h}>' if h else ''),result)
            self.assertEqual(library_typography(result,tag),result)
        self.assertNotIn('<height:',library_typography('20米','DSCR'))

    def test_work_title_recompiles_previous_scope_without_nested_controls(self):
        old='<width:0E><space:0C><height:0A>The Big O<width:15><space:15><height:0A> 第二季'
        result=library_typography(old,'PRDC')
        self.assertEqual(result,'<width:0E><space:0A><height:0A>The Big O<width:15><space:15><height:0A> 第二季')
        self.assertEqual(library_typography(result,'PRDC'),result)
        for text in ('无敌超人赞波特3','∀高达'):
            self.assertNotIn('<space:0A>',library_typography(text,'PRDC'))
        self.assertIn('<space:0C>',library_typography('The Big O','DSCR'))

    def test_parameters_preserve_native_horizontal_metrics_and_reduce_height(self):
        for tag in ('HEIT','WEIT'):
            result=library_typography('18.0m',tag)
            self.assertEqual(result,'<width:0C><space:0C><height:09>18.0m<width:0C><space:0C><height:0A>')
            self.assertEqual(library_typography(result,tag),result)

    def test_gran_sigma_is_one_closed_run_and_dome_name_has_more_room(self):
        text=library_typography('以创星机Gran Σ为核心','DSCR')
        self.assertEqual(text,'以创星机<width:0E><space:0C>Gran Σ<width:16><space:16>为核心')
        dome=library_typography('D.O.M.E.G-Bit','RBTN')
        self.assertEqual(dome,'<width:10><space:0E><height:0A>D.O.M.E.G-Bit<width:12><space:12><height:0A>')
        self.assertEqual(library_typography(dome,'RBTN'),dome)

    def test_native_controls_templates_and_percent_survive(self):
        text='<color:03>中文<tm>ABC123</tm>$n<width:14><space:14>99%尾'
        result=library_typography(text,'DSCR')
        self.assertIn('<tm>ABC123</tm>$n<width:14><space:14>',result)
        self.assertIn('99%<space:14><width:14>尾',result)
        self.assertEqual(CONTROL_NOTATION.sub('',result),CONTROL_NOTATION.sub('',text))

    def test_short_scopes_are_atomic_during_reflow(self):
        text=library_typography('甲'*13+'SEED DESTINY中文20米。','DSCR')
        result,widths=reflow_body(text,16)
        self.assertTrue(all(width<=16 for width in widths))
        self.assertTrue(any('SEED DESTINY' in line for line in result.splitlines()))
        self.assertEqual(CONTROL_NOTATION.sub('',result).replace('\n',''),'甲'*13+'SEED DESTINY中文20米。')

    def test_production_year_form_is_unified_across_line_breaks(self):
        import re
        root=Path(__file__).resolve().parents[1]
        alternate=re.compile(r'(?:12000|1万2千|1万2000|一万二千|1\.2万)(?:多)?年')
        for path in (root/'corpus/zh').rglob('*.json'):
            def check(node):
                if isinstance(node,dict):
                    text=node.get('translation')
                    if isinstance(text,str):
                        visible=CONTROL_NOTATION.sub('',text).replace('\n','')
                        self.assertIsNone(alternate.search(visible),(str(path),node.get('id')))
                    for item in node.values():check(item)
                elif isinstance(node,list):
                    for item in node:check(item)
            check(json.loads(path.read_text()))

    def test_sp_library_corpora_invalidate_system_cache(self):
        from special_disc.writeback.incremental import component_inputs, COMPONENTS
        for path in ('corpus/zh/library/v0.2-reviewed.json', 'corpus/zh/library/sp-reviewed-supplement.json'):
            rows=[dict(path=path,size=1,sha256='a'*64)]
            self.assertEqual({name for name in COMPONENTS if component_inputs(rows,name)}, {'system'})

    def test_sp_supplement_binds_all_84_fields_to_native_hashes(self):
        rows,*_=authoring()
        root=Path(__file__).resolve().parents[1]
        supplement=json.loads((root/'corpus/zh/library/sp-reviewed-supplement.json').read_text())
        self.assertEqual(len(supplement['entries']),55)
        self.assertEqual(sum(len(r['field_ids']) for r in supplement['entries']),84)
        for r in supplement['entries']:
            self.assertEqual(rows[r['source_text_sha256']]['translation'],r['translation'])

    def test_sp_exact_duplicate_body_can_use_reviewed_translation_in_dsc2(self):
        from special_disc.writeback.shared_library import extend_shared_scopes
        root=Path(__file__).resolve().parents[1]
        supplement=json.loads((root/'corpus/zh/library/sp-reviewed-supplement.json').read_text())
        binding,=supplement['shared_scope_extensions']
        rows,*_=authoring()
        self.assertEqual(binding['field_ids'],['robot/321/DSC2'])
        self.assertEqual(rows[binding['source_text_sha256']]['tags'],['DSCR','DSC2'])
        source=json.loads((root/'corpus/zh/library/v0.2-reviewed.json').read_text())
        row=next(r for r in source['entries'] if r['id']==binding['shared_id'])
        bad={**binding,'source_text_sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'identity drift'):
            extend_shared_scopes({row['source_text_sha256']:row},{'shared_scope_extensions':[bad]})

if __name__=='__main__':unittest.main()
