"""The integrated project defaults must stay tag-free, independently of legacy fixtures."""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.typography_policy import load_policy, options
from srwz.compact_scopes import expand
from srwz.compact_authoring import compact_controlled_text
from srwz.build_layout import verify_stored

class ProjectTypographyTests(unittest.TestCase):
    def test_project_default_uses_proportional_compact_punctuation(self):
        self.assertEqual(load_policy(ROOT),{'mode':'proportional','chinese_punctuation':'compact'})
        self.assertEqual(options(),('proportional','compact'))
        self.assertEqual(expand('<z>Side 3</z>'),'Side 3')
        self.assertEqual(compact_controlled_text('CIWS/RX-78',default_width=21),'CIWS/RX-78')
        self.assertEqual(verify_stored([('default-mode','I'*60,False)],'story'),1)
        with self.assertRaisesRegex(ValueError,'geometry'):
            verify_stored([('native-mode','I'*60,False)],'story',typography='native',chinese_punctuation='native')

    def test_current_translation_corpus_contains_no_z_scopes(self):
        count=0
        def walk(value,path):
            nonlocal count
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=='translation' and isinstance(item,str):
                        count+=1
                        self.assertNotIn('<z>',item,str(path))
                        self.assertNotIn('</z>',item,str(path))
                    else:walk(item,path)
            elif isinstance(value,list):
                for item in value:walk(item,path)
        for path in (ROOT/'corpus/zh').rglob('*.json'):
            walk(json.loads(path.read_text()),path)
        self.assertGreater(count,140000)
