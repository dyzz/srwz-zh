"""Real production adapters must execute the browser core, preserve text and bind caches."""
import json,math,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from srwz.typography_policy import options as typography_options
from srwz.build_layout import library_batch,verify_stored,reflow_story,runtime_inputs,check_runtime,verify_prose,prose_row_width,PROSE_HANGING_PX
from srwz.js_layout import request_layout
from srwz.chinese_layout import load_layout_profiles
from srwz.build_fingerprints import is_component_build_definition
from srwz.release_inputs import is_build_input
from build_library_v02_component import reflow_body,reflow_bodies

def project_options():
 mode,punctuation=typography_options();return dict(typography=mode,chinesePunctuation=punctuation)

class JsBuildLayoutTests(unittest.TestCase):
 def test_library_adapter_preserves_paragraph_ownership_like_other_prose(self):
  text='　'+'甲'*36+'\n\n　'+'乙'*29
  result=library_batch([('CHAR',text)])[('CHAR',text)]
  self.assertTrue(result[0]);self.assertEqual(result[1][0],request_layout(text,'library_character',options=project_options())['text'])
  self.assertIn('\n\n　',result[1][0]);self.assertTrue(result[1][0].startswith('　'))

 def test_library_production_single_batch_and_browser_match(self):
  profiles=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')
  for kind,domain,width in [('CHAR','character',16),('ROBO','robot',26),('KYWD','glossary',25)]:
   text='地球统合政府<z>EFA</z>所属，目标<z>MS-013</z>已经进入指定区域。'*3
   profile=profiles['library_'+domain]
   one=reflow_body(text,width,profile=profile)
   batch=reflow_bodies([(kind,text)],{kind:width},{kind:profile},())[(kind,text)]
   browser=request_layout(text,'library_'+domain,options=project_options())
   self.assertTrue(batch[0]);self.assertEqual(one,batch[1]);self.assertEqual(one[0],browser['text'])
 def test_candidate_library_bridge_uses_compact_punctuation_policy(self):
  text='高达Mk-II，目标是Side 3。确认后出击！'*3
  result=library_batch([('CHAR',text)],typography='proportional',chinese_punctuation='compact')[('CHAR',text)]
  expected=request_layout(text,'library_character',options=dict(typography='proportional',chinesePunctuation='compact'))
  self.assertTrue(result[0]);self.assertEqual(result[1][0],expected['text'])
  self.assertNotIn('<z>',result[1][0])

 def test_unknown_node_failure_cannot_fall_back_to_python(self):
  with patch('srwz.build_layout.layout_batch',side_effect=RuntimeError('missing Node')):
   with self.assertRaisesRegex(RuntimeError,'missing Node'):library_batch([('CHAR','中文')])
 def test_stored_dialogue_is_checked_without_reflowing_or_retiming(self):
  self.assertEqual(verify_stored([('story','“目标<z>MS-013</z>已锁定！\n　立即攻击！”',False)],'story'),1)
  with self.assertRaisesRegex(ValueError,'geometry'):verify_stored([('battle','中'*22,False)],'battle')
  self.assertEqual(verify_stored([('battle','中'*21,False)],'battle'),1)
 def test_story_authoring_and_browser_use_identical_engine(self):
  p=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')['story_dialogue']
  text='“目标<z>MS-013</z>已经锁定，立即攻击并掩护友军撤退，完成任务后返回基地！”'
  self.assertEqual(reflow_story(text,profile=p).text,request_layout(text,'story',options=project_options())['text'])
 def test_js_runtime_is_in_snapshot_cache_and_receipt(self):
  for value in runtime_inputs().values():
   self.assertTrue(is_component_build_definition(value['path']));self.assertTrue(is_build_input(value['path']))
   self.assertEqual((ROOT/value['path']).stat().st_size,value['size'])
  self.assertFalse(is_build_input('shared/text-layout/assets/native-glyphs.json'))
  self.assertFalse(is_component_build_definition('shared/text-layout/demo.mjs'))

 def test_all_edition_preflight_runs_real_node_core(self):
  result=check_runtime(ROOT);self.assertEqual(result['scenes'],10);self.assertEqual(set(result['inputs']),set(runtime_inputs()))

 def test_narrow_scroll_owner_retains_504_pixel_cap(self):
  self.assertEqual(verify_prose([('summary/01/000','中'*22,None)],'main_scroll'),1)
  with self.assertRaisesRegex(ValueError,'504px'):verify_prose([('summary/03/000','中'*22,None)],'main_scroll')

 def test_narrow_scroll_hangs_only_the_last_punctuation(self):
  line='时，埃曼人也派遣商队前往世界各地，从事贸易。'
  row=lambda text: [('summary/04/000',text,1)]
  with self.assertRaisesRegex(ValueError,'504px'):
   verify_prose(row(line),'main_scroll')
  self.assertEqual(verify_prose(row(line),'main_scroll',hanging_px=PROSE_HANGING_PX),1)
  for invalid in (line+'中', '中'+line, line+'。'):
   with self.assertRaisesRegex(ValueError,'504px'):
    verify_prose(row(invalid),'main_scroll',hanging_px=PROSE_HANGING_PX)

 def test_hanging_width_keeps_body_advance_before_a_left_bearing_glyph(self):
  row={'advancePx':514,'occupiedPx':515,'glyphs':[
   {'text':'中','x':480,'width':20,'advance':25},
   {'text':'。','x':503,'width':12,'advance':9},
  ]}
  self.assertEqual(prose_row_width(row,PROSE_HANGING_PX),505)

 def test_frozen_runtime_resolves_without_source_workspace(self):
  import os,shutil,subprocess,tempfile
  with tempfile.TemporaryDirectory()as temp:
   root=Path(temp);(root/'shared/text-layout').mkdir(parents=True);(root/'tools/srwz').mkdir(parents=True)
   for name in ['engine.mjs','contracts.mjs','cli.mjs','cli-handler.mjs','proportional-selection.mjs','proportional-metrics.mjs']:shutil.copyfile(ROOT/'shared/text-layout'/name,root/'shared/text-layout'/name)
   for name in ['build_layout.py','js_layout.py','typography_policy.py']:shutil.copyfile(ROOT/'tools/srwz'/name,root/'tools/srwz'/name)
   (root/'tools/srwz/__init__.py').write_text('')
   output=subprocess.check_output([sys.executable,'-c',"from pathlib import Path; from srwz.build_layout import check_runtime; print(check_runtime(Path.cwd())['scenes'])"],cwd=root,env={**os.environ,'PYTHONPATH':str(root/'tools')},text=True)
   self.assertEqual(output.strip(),'10')
