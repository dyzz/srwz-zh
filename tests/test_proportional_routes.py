"""Dispatch must reject ambiguous owners rather than silently select one."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.proportional_routes import build_routed_payload,SP_REPLAY_ROUTES
class RoutedOwnershipTests(unittest.TestCase):
 def test_dynamic_draw_requires_audited_registers_and_surface_guards(self):
  from srwz.proportional_hooks import draw_hook
  with self.assertRaisesRegex(ValueError,'Dynamic bounds require'):
   draw_hook(('s5',0),('s6',1),0x1000,14)
  with self.assertRaisesRegex(ValueError,'Dynamic bounds require'):
   draw_hook(('s5',0),('s7',1),0x1000,14,caller=0x2253cc,native_size=(21,12))
 def test_measure_owner_collision_is_rejected_even_with_distinct_draw_callers(self):
  a=dict(SP_REPLAY_ROUTES[0]);b=dict(a,name='other',caller=a['caller']+4)
  with self.assertRaisesRegex(ValueError,'Ambiguous'):build_routed_payload({},'sp',[a,b])
 def test_source_bounds_outside_ee_ram_rejected(self):
  a=dict(SP_REPLAY_ROUTES[0],draw=(0x1ffffff,0x2000004))
  with self.assertRaisesRegex(ValueError,'bounds'):build_routed_payload({},'sp',[a])
 def test_empty_routes_rejected(self):
  with self.assertRaisesRegex(ValueError,'At least'):build_routed_payload({},'sp',[])
 def test_cjk_three_surface_payload_fits_reserved_segment(self):
  import json
  root=Path(__file__).resolve().parents[1]
  registry=json.loads((root/'shared/text-layout/proportional-metrics.mjs').read_text().split(' = ',1)[1].strip().rstrip(';'))
  payload,patches,report=build_routed_payload(registry,'sp',SP_REPLAY_ROUTES,chinese_punctuation=True)
  self.assertLessEqual(len(payload),6400)
  self.assertEqual(len(patches),2)
  self.assertTrue(report['chinesePunctuation'])
  sections=report['sections']
  for a,b in zip(sections,sections[1:]):self.assertLessEqual(a['address']+a['size'],b['address'])
  self.assertEqual(len([s for s in sections if s['name'].endswith('_cjk')]),3)
