import sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path.cwd()/'tools'),str(Path(__file__).parent)]
from srwz.prose_step_partition import balance
class Engine:
 def measure(self,s,scene):return s
 def strip(self,s):return s
class CommonWidthTests(unittest.TestCase):
 def test_each_paragraph_reaches_same_width_without_moving_boundary(self):
  rows,m=balance([('甲'*10,''),'　',('乙'*14,'')],[3,4],SimpleNamespace(step_x=16),SimpleNamespace(maximum_width=4,unbroken_terms=()),Engine(),(),[{}],{},lambda _:0,row_count=7,common_width=True)
  at=rows.index('　');self.assertEqual(max(map(len,rows[:at])),4);self.assertEqual(max(map(len,rows[at+1:])),4)
  self.assertEqual(''.join(rows[:at]),'甲'*10);self.assertEqual(''.join(rows[at+1:]),'乙'*14)
 def test_short_fixed_screen_is_not_forced_into_one_character_row(self):
  rows,m=balance([('甲乙丙丁戊己','')],[2],SimpleNamespace(step_x=16),SimpleNamespace(maximum_width=8,unbroken_terms=()),Engine(),(),[{}],{},lambda _:0,row_count=2,common_width=True)
  self.assertEqual(list(map(len,rows)),[3,3]);self.assertEqual(m['range_px'],0)
 def test_fill_mode_does_not_balance_long_paragraph(self):
  rows,m=balance([('甲'*53,'')],[3],SimpleNamespace(step_x=25),SimpleNamespace(maximum_width=23,unbroken_terms=()),Engine(),(),[{}],{},lambda _:0,row_count=3,fill_rows=True)
  self.assertEqual(list(map(len,rows)),[23,23,7]);self.assertTrue(m['front_to_back_maximum_fill_verified'])
 def test_fill_mode_keeps_period_off_next_line_start(self):
  rows,m=balance([('甲'*65+'西。','')],[4],SimpleNamespace(step_x=24),SimpleNamespace(maximum_width=22,unbroken_terms=()),Engine(),(),[{}],{},lambda _:0,row_count=4,fill_rows=True)
  self.assertEqual(list(map(len,rows)),[22,22,21,2]);self.assertEqual(rows[-1],'西。')
 def test_equal_scores_fill_earlier_row_first(self):
  rows,m=balance([('甲乙丙丁戊','')],[2],SimpleNamespace(step_x=16),SimpleNamespace(maximum_width=3,unbroken_terms=()),Engine(),(),[{}],{},lambda _:0,row_count=2)
  self.assertEqual(rows,['甲乙丙','丁戊'])
if __name__=='__main__':unittest.main(verbosity=2)
