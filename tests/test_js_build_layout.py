"""Real production adapters must execute the browser core, preserve text and bind caches."""
import json,math,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from srwz.build_layout import library_batch,verify_stored,reflow_story,runtime_inputs,check_runtime,verify_prose
from srwz.js_layout import request_layout
from srwz.chinese_layout import load_layout_profiles
from srwz.build_fingerprints import is_component_build_definition
from srwz.release_inputs import is_build_input
from build_library_v02_component import reflow_body,reflow_bodies

class JsBuildLayoutTests(unittest.TestCase):
 def test_library_production_single_batch_and_browser_match(self):
  profiles=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')
  for kind,domain,width in [('CHAR','character',16),('ROBO','robot',26),('KYWD','glossary',25)]:
   text='地球统合政府<z>EFA</z>所属，目标<z>MS-013</z>已经进入指定区域。'*3
   profile=profiles['library_'+domain]
   one=reflow_body(text,width,profile=profile)
   batch=reflow_bodies([(kind,text)],{kind:width},{kind:profile},())[(kind,text)]
   browser=request_layout(text,'library_'+domain)
   self.assertTrue(batch[0]);self.assertEqual(one,batch[1]);self.assertEqual(one[0],browser['text'])
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
  self.assertEqual(reflow_story(text,profile=p).text,request_layout(text,'story')['text'])
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

 def test_frozen_runtime_resolves_without_source_workspace(self):
  import os,shutil,subprocess,tempfile
  with tempfile.TemporaryDirectory()as temp:
   root=Path(temp);(root/'shared/text-layout').mkdir(parents=True);(root/'tools/srwz').mkdir(parents=True)
   for name in ['engine.mjs','contracts.mjs','cli.mjs','cli-handler.mjs']:shutil.copyfile(ROOT/'shared/text-layout'/name,root/'shared/text-layout'/name)
   for name in ['build_layout.py','js_layout.py']:shutil.copyfile(ROOT/'tools/srwz'/name,root/'tools/srwz'/name)
   (root/'tools/srwz/__init__.py').write_text('')
   output=subprocess.check_output([sys.executable,'-c',"from pathlib import Path; from srwz.build_layout import check_runtime; print(check_runtime(Path.cwd())['scenes'])"],cwd=root,env={**os.environ,'PYTHONPATH':str(root/'tools')},text=True)
   self.assertEqual(output.strip(),'10')
