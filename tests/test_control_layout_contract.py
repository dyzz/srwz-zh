"""Complete control tokens must have one layout contract in both width paths."""
from pathlib import Path
import sys,unittest,json,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.chinese_layout import (tokenize_dialogue,dialogue_line_widths,
    fit_chinese_dialogue_layout,ChineseLayoutProfile,ChineseLayoutError)
from srwz.renderer_metrics import text_extent
from srwz.text import TM_STOCK_KEYS, TextTable,decode_text,encode_text,runtime_control_bytes

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

    def test_numeric_template_delimiters_bypass_the_visible_slash_alias(self):
        table=TextTable({0x93BE:'得'}, {})
        overrides={'／':0x8FDE}
        native='＜ｔｍ＞得＜／ｔｍ＞'.encode('cp932')
        for template in ('＜tm＞得＜／tm＞', '＜ｔｍ＞得＜／ｔｍ＞', '<tm>得</tm>'):
            self.assertEqual(encode_text(template+'／',table,overrides=overrides), native+bytes.fromhex('8fde'))

    def test_stock_numeric_keys_ignore_the_visible_font_mapping(self):
        original = TextTable({0x8294: 'ｔ', 0x828D: 'ｍ'}, {})
        projected = TextTable({0x8294: 't', 0x828D: 'm', 0x8A6C: '获'}, {})
        for key in TM_STOCK_KEYS:
            with self.subTest(key=key):
                original_scope = f'＜ｔｍ＞{key}＜／ｔｍ＞'
                projected_scope = f'＜tm＞{key}＜／tm＞'
                raw = original_scope.encode('cp932')
                self.assertEqual(encode_text(projected_scope, projected, overrides={'獲': 0x8FDE}), raw)
                self.assertEqual(decode_text(raw+b'\0', 0, original).text, original_scope)
                self.assertEqual(decode_text(raw+b'\0', 0, projected).text, projected_scope)

if __name__=='__main__':unittest.main()
