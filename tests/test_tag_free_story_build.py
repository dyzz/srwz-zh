"""Candidate builds must use actual proportional geometry without losing structure."""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_story_component import _entry_translations
from srwz.build_layout import verify_stored
from srwz.chinese_layout import dialogue_layout_issues,load_layout_profiles

class TagFreeStoryBuildTests(unittest.TestCase):
 def test_candidate_reader_rejects_leftover_markup_instead_of_expanding_it(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'stage-001.json'
   def write(text):path.write_text(json.dumps(dict(schema_version=1,entries=[dict(id='story/001/dialogue/test',translation=text)])))
   write('<z>Side 3</z>')
   with self.assertRaisesRegex(SystemExit,'compact markup'):_entry_translations(path,{1},typography='proportional')
   self.assertIn('<width:',next(iter(_entry_translations(path,{1}).values())))
   write('Side 3')
   result=next(iter(_entry_translations(path,{1},typography='proportional').values()))
   self.assertNotIn('<',result)

 def test_geometry_changes_only_with_explicit_candidate_policy(self):
  rows=[('mixed','I'*60,False)]
  with self.assertRaisesRegex(ValueError,'geometry'):verify_stored(rows,'story',typography='native',chinese_punctuation='native')
  self.assertEqual(verify_stored(rows,'story',typography='proportional',chinese_punctuation='compact'),1)
  with self.assertRaisesRegex(ValueError,'geometry'):
   verify_stored([('too-wide','中'*30,False)],'story',typography='proportional',chinese_punctuation='compact')

 def test_shared_geometry_does_not_disable_indent_or_line_count_checks(self):
  profile=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['story_dialogue']
  issues=dialogue_layout_issues('第一行\n第二行\n第三行\n第四行',profile=profile,check_width=False)
  self.assertTrue(any('lines exceed' in x for x in issues))
  self.assertTrue(any('indent' in x for x in issues))
