"""Real Node subprocess integration for the browser/backend shared JS core."""
import sys,shutil,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.js_layout import request_layout,layout_batch,JsLayoutError

@unittest.skipUnless(shutil.which('node'),'Node.js required for JS layout adapter')
class JsLayoutAdapterTests(unittest.TestCase):
    def test_unicode_batch_and_error_isolation(self):
        result=layout_batch([dict(scene='story',text='甲<z>MS-013</z>乙',action='measure'),dict(scene='missing',text='甲'),dict(scene='battle',text='甲')])
        self.assertEqual(result[0]['result']['rows'][0]['advancePx'],114)
        self.assertEqual(result[1]['error']['code'],'unknown_scene')
        self.assertTrue(result[2]['ok'])

    def test_battle_authored_newline_and_native_restore(self):
        result=request_layout('“目标<z>MS-013</z>已锁定！\\n　马上攻击！”','battle',options=dict(escapedNewlines=True))
        self.assertIn('\\n　',result['text'])
        self.assertIn('<width:16><space:16><height:0B>',result['compiledText'])
        self.assertTrue(result['valid'])

    def test_real_backend_overflow_error_remains_structured(self):
        with self.assertRaises(JsLayoutError) as caught:
            request_layout('甲'*40,'battle')
        self.assertEqual(caught.exception.code,'overflow')
        self.assertEqual(caught.exception.details['widthPx'],462)

    def test_prose_owner_budget_is_enforced(self):
        with self.assertRaises(JsLayoutError):
            request_layout('　'+'国'*80,'sp_flow',options=dict(maxLines=2))
        result=request_layout('　'+'国'*80,'sp_flow',options=dict(maxLines=4))
        self.assertEqual(len(result['rows']),3)
        self.assertEqual(result['step'],16)
