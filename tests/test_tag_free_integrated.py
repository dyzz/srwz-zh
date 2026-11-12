import json,sys,unittest,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from srwz.tag_free_integrated import build_payload,install
from srwz.proportional_payload import LAYOUTS
from srwz.proportional_metrics import runtime_table, METRIC_BYTES, METRIC_SLOTS

class IntegratedPayloadTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  text=(ROOT/'shared/text-layout/proportional-metrics.mjs').read_text()
  cls.registry=json.loads(text.split(' = ',1)[1].rstrip(';\n'))
 def test_payload_fits_and_all_sections_are_disjoint(self):
  for edition in ['original','sp']:
   payload,patches,report=build_payload(self.registry,edition)
   self.assertEqual(len(payload),LAYOUTS[edition]['capacity'])
   ranges=sorted((s['address'],s['address']+s['size']) for s in report['sections'])
   for (_,end),(start,_) in zip(ranges,ranges[1:]):self.assertLessEqual(end,start)
   self.assertLessEqual(ranges[-1][1],report['base']+len(payload))
   self.assertEqual(len({p[0] for p in patches}),len(patches))
 def test_residual_table_preserves_legacy_records_and_descenders(self):
  for name,p in self.registry['profiles'].items():
   old=runtime_table(p);new=runtime_table(p,include_residuals=True)
   self.assertEqual(new[:METRIC_BYTES],old);self.assertEqual(len(new),METRIC_BYTES+METRIC_SLOTS)
   for c in 'Hgypqj':self.assertEqual(p['glyphs'][c]['baselineResidual16'],p['glyphs']['H']['baselineResidual16'])
   for c in '0123456789':self.assertEqual(p['glyphs'][c]['baselineResidual16'],p['glyphs']['0']['baselineResidual16'])
   # HarmonyOS bank glyphs share the hanzi rasterizer and baseline: every scene draws
   # them in its own hanzi cell, without lift or baseline residual (2026-11-12).
   from srwz.proportional_metrics import CJK_NATIVE
   native=CJK_NATIVE[name]
   for c in 'A0':
    m=p['glyphs'][c]
    self.assertEqual((m['width'],m['height'],m['yOffset'],m['baselineResidual16']),(*native,0,0))
 def test_scene_dispatch_fits_and_keeps_all_body_geometries(self):
  from srwz.proportional_scene_dispatch import SCENES
  from srwz.proportional_metrics import CJK_NATIVE
  for edition in ['original','best','sp']:
   payload,patches,report=build_payload(self.registry,edition,scene_dispatch=True)
   ranges=sorted((s['address'],s['address']+s['size']) for s in report['sections'])
   for (_,end),(start,_) in zip(ranges,ranges[1:]):self.assertLessEqual(end,start)
   self.assertEqual(len({CJK_NATIVE[s] for s in SCENES[edition]}),len(SCENES[edition]))
   self.assertIn('sp_story_map',SCENES[edition])
   self.assertEqual({r['scene'] for r in report['routes']},set(SCENES[edition]))
   self.assertEqual(len({p[0] for p in patches}),len(patches))
   for name in SCENES[edition]:
    section=next(s for s in report['sections'] if s['name']==name+'_geometry')
    at=section['address']-report['base'];actual=struct.unpack('BBbbb',payload[at:at+5])
    letter=self.registry['profiles'][name]['glyphs']['A'];digit=self.registry['profiles'][name]['glyphs']['3']
    self.assertEqual(actual,(letter['height'],digit['height'],letter['yOffset'],letter['baselineResidual16'],digit['baselineResidual16']))
 def test_install_rejects_instruction_drift_without_mutating_input(self):
  for edition in ['original','sp']:
   source=ROOT/f'work/candidates/tag-free-integrated-20261108/{edition}-source.elf'
   if not source.exists():self.skipTest('Optional local source ELF not present')
   raw=source.read_bytes();result,report=install(raw,self.registry,edition)
   self.assertEqual(len(result),len(raw))
   patch=report['patches'][0];address=patch['address']
   ph=struct.unpack_from('<I',raw,28)[0];n=struct.unpack_from('<H',raw,44)[0]
   for i in range(n):
    t,o,v,_,sz,*_=struct.unpack_from('<8I',raw,ph+i*32)
    if t==1 and v<=address<v+sz:
     bad=bytearray(raw);bad[o+address-v]^=1
     with self.assertRaisesRegex(ValueError,'preimage drift'):install(bytes(bad),self.registry,edition)
     break
 def test_battle_opening_quote_keeps_full_width(self):
  # Continuation rows indent by one full-width space; a compact opening quote
  # would leave them 5px to the right of the first row.
  from srwz.proportional_metrics import CJK_FULL_WIDTH,CJK_PUNCTUATION
  self.assertEqual(CJK_FULL_WIDTH,{'battle':'“'})
  for scene,profile in self.registry['profiles'].items():
   expected=[char for char in CJK_PUNCTUATION if char not in CJK_FULL_WIDTH.get(scene,'')]
   self.assertEqual(list(profile['cjkPunctuation']),expected,scene)
 def test_width_only_measure_dispatch_agrees_with_every_draw_geometry(self):
  # The native measure path exposes width but not glyph height. Scenes that
  # share that width must therefore have exactly the same horizontal metrics.
  from srwz.proportional_scene_dispatch import SCENES
  from srwz.proportional_metrics import CJK_NATIVE
  for edition,scenes in SCENES.items():
   seen={}
   for scene in scenes:
    profile=self.registry['profiles'][scene]
    horizontal={group:{char:tuple(metric[key] for key in ('code','bearing','advance'))
                       for char,metric in profile[group].items()}
                for group in ('glyphs','punctuation','cjkPunctuation')}
    horizontal['space']=tuple(profile['space'][key] for key in ('code','bearing','advance'))
    width=CJK_NATIVE[scene][0]
    if width in seen:
     other,expected=seen[width]
     self.assertEqual(horizontal,expected,(edition,other,scene))
    else:seen[width]=(scene,horizontal)
