"""Complete control tokens must have one layout contract in both width paths."""
from pathlib import Path
import sys,unittest,json,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.chinese_layout import (tokenize_dialogue,dialogue_line_widths,
    fit_chinese_dialogue_layout,ChineseLayoutProfile,ChineseLayoutError)
from srwz.renderer_metrics import text_extent
from srwz.text import TextTable,decode_text,runtime_control_bytes

class ControlLayoutContractTests(unittest.TestCase):
    def test_composites_stay_atomic_and_have_identical_cell_and_pixel_budgets(self):
        table=TextTable({}, {0x31:'color',0x32:'width',0x33:'height',0x34:'space'})
        for native,cells in ((b'<0>',1),(b'<-3>',1),(b'<10>',1),(b'{4.4.0}',0),
                             (b'%02d',6),(b'% 2d',6),(b'$n',6)):
            token=decode_text(native,0,table,allow_end=True).text
            plain='甲'+token+'乙'
            controlled='<width:15><space:15>'+plain
            with self.subTest(token=token):
                tokens=tokenize_dialogue(plain,default_advance_px=21)
                self.assertTrue(any(token in t.text for t in tokens))
                self.assertEqual(dialogue_line_widths(plain,default_advance_px=21),(2+cells,))
                self.assertEqual(dialogue_line_widths(controlled,default_advance_px=21),(2+cells,))
                self.assertEqual(text_extent(plain,default_advance_px=21).occupied_px,(2+cells)*21)
                self.assertEqual(text_extent(controlled,default_advance_px=21).occupied_px,(2+cells)*21)
                profile=ChineseLayoutProfile('probe',max(2+cells,3),None,3,'minimum',default_advance_px=21)
                fitted=fit_chinese_dialogue_layout(plain,profile=profile)
                self.assertEqual(runtime_control_bytes(fitted.text),runtime_control_bytes(plain))
                self.assertIn(token,fitted.text)

    def test_generated_production_preview_cannot_be_written_into_authoring_corpus(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/text_layout'))
        from apply_prose_layout import apply
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);preview=root/'preview.json'
            preview.write_text(json.dumps({'records':[{'variant':'production_typography'}]}))
            with self.assertRaisesRegex(ValueError,'generated preview'):
                apply(preview,root/'receipt.json',root/'snapshot')
            self.assertFalse((root/'receipt.json').exists())
            self.assertFalse((root/'snapshot').exists())

    def test_dynamic_template_repeat_and_unknown_variables_require_explicit_owner(self):
        for text in ('甲＜ｔｍ＞123＜／ｔｍ＞乙','甲<tm>123</tm>乙','@11','@<width:00>','甲$x乙','甲[<space:5D>乙'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):text_extent(text,default_advance_px=21)
                with self.assertRaises(ChineseLayoutError):tokenize_dialogue(text,default_advance_px=21)

if __name__=='__main__':unittest.main()
