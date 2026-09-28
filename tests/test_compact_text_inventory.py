"""Inventory controls, nested authoring fields and explicit source precedence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/text_layout')]
from audit_compact_text_inventory import build,candidates,rows


class CompactTextInventoryTests(unittest.TestCase):
    def test_control_parameters_and_placeholders_are_not_numeric_candidates(self):
        runs,_=candidates('<width:16><space:16>$n，99%。%s。')
        self.assertEqual([r['text'] for r in runs],['99%'])
        runs,_=candidates(r'甲\n　MS。乙\n　S-1。丙\n　PLANT。')
        self.assertEqual([r['text'] for r in runs],['S-1','PLANT'])

    def test_division_is_protected_and_unicode_minus_is_reviewed(self):
        runs,_=candidates('100÷200、−10%')
        self.assertTrue(runs[0]['division_protected'])
        self.assertIn('−',runs[1]['adjacent_symbol_review'])

    def test_nested_qa_and_unit_segments_are_counted(self):
        document=dict(pages=[dict(records=[dict(translation='PLANT')])],segments=[dict(range=[3,4],translations=['606','909'])])
        result=list(rows(document))
        self.assertEqual(len(result),3)
        self.assertEqual(result[0][1],'/pages/0/records/0/translation')
        self.assertEqual(result[-1][0]['id'],'display-name/unit/0004/name')

    def test_release_alias_is_counted_once_and_review_ledger_is_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);row=dict(id='menu/1',source_text_sha256='same',translation='PLANT')
            for name,value in [('menu/source.json',dict(entries=[row])),('menu/release-v0.3.json',dict(entries=[row])),
                               ('special-disc/reviewed-non-stage-text.json',dict(entries=[row]))]:
                path=root/'corpus/zh'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
            result=build(root)
            self.assertEqual(result['candidate_owners'],1)
            self.assertEqual(len(result['aliases']),1)
            self.assertEqual(len(result['excluded']),1)


if __name__=='__main__':unittest.main()
