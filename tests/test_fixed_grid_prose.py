import sys,unittest,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.fixed_grid_prose import fill_fixed_grid_paragraphs

class FixedGridProseTests(unittest.TestCase):
 def test_intro_fills_cells_without_preserving_words(self):
  rows=json.loads((ROOT/'corpus/zh/special-disc/frame-text.json').read_text())['entries']
  text=next(r['translation'] for r in rows if r['id']=='vt1-page/000').rsplit('\n',1)[0]
  lines=fill_fixed_grid_paragraphs(text)
  self.assertTrue(lines[0].startswith('　ZEUTH'))
  self.assertEqual(len(lines[0]),28)
  self.assertTrue(lines[0].endswith('新地'))
  self.assertTrue(lines[1].startswith('球联邦军'))
  self.assertEqual(''.join(lines),text.replace('\n',''))
  self.assertEqual(sum(line.startswith('　') for line in lines),3)
 def test_latin_and_digits_each_take_one_native_cell(self):
  self.assertEqual(fill_fixed_grid_paragraphs('　ABCDE013甲乙丙',columns=6),['　ABCDE','013甲乙丙'])
 def test_punctuation_and_paragraph_separators(self):
  self.assertEqual(fill_fixed_grid_paragraphs('　甲乙丙，丁。\n\n　戊己',columns=4),['　甲乙','丙，丁。','','　戊己'])
 def test_controls_are_rejected_in_two_byte_grid(self):
  with self.assertRaisesRegex(ValueError,'controls'):
   fill_fixed_grid_paragraphs('<width:0C>013')
if __name__=='__main__':unittest.main()
