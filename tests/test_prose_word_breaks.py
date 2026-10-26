"""Prose opt-out must bypass implicit words without weakening control scopes."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.chinese_layout import tokenize_dialogue,_valid_break

class ProseWordBreakTests(unittest.TestCase):
 def test_default_retains_common_and_explicit_words(self):
  tokens=tokenize_dialogue('我们开发兵器他们',protected_terms=('他们',))
  self.assertEqual([t.text for t in tokens],['我们','开发','兵器','他们'])
 def test_prose_optout_splits_common_names_and_number_units(self):
  text='我们开发兵器他们14岁罗兰'
  tokens=tokenize_dialogue(text,protected_terms=('他们','罗兰'),protect_words=False)
  self.assertEqual([t.text for t in tokens],list(text))
 def test_optout_still_obeys_punctuation(self):
  tokens=tokenize_dialogue('甲（乙）丙。',protect_words=False)
  self.assertFalse(_valid_break(tokens,2));self.assertFalse(_valid_break(tokens,3));self.assertFalse(_valid_break(tokens,5))
 def test_native_compact_scope_remains_whole_and_measures_step(self):
  scope='<width:0C><space:0B><height:09>013<width:10><space:10><height:8A>'
  tokens=tokenize_dialogue('甲'+scope+'特别小队',default_advance_px=16,protect_words=False)
  self.assertEqual([t.text for t in tokens],['甲',scope,'特','别','小','队'])
  self.assertEqual(tokens[1].width*16,33)
if __name__=='__main__':unittest.main()
