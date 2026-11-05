"""Keep reviewed ti/w glyphs local and match their visible baseline to o."""
import sys, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.font import encode_glyph, decode_glyph, standard_glyph_index
from special_disc.event_gallery.ligature import build, build_w, showtime_text, CODE, INDEX, CHARACTER, W_CODE, W_INDEX, W_CHARACTER
from special_disc.event_gallery.menu import compact_list_name

class GalleryLigatureTests(unittest.TestCase):
    def fixture(self):
        font = bytearray(4480 * 288)
        for code, box in [(0x8294,(7,4,10,17)),(0x8289,(10,3,4,18)),(0x8297,(6,7,12,15)),(0x828F,(6,8,13,13))]:
            pix = bytearray(576);x,y,w,h = box
            for row in range(y,y+h):
                for col in range(x,x+w):pix[row*24+col] = 1+(row+col)%15
            off=standard_glyph_index(code)*288;font[off:off+288]=encode_glyph(pix)
        return bytes(font), dict(assignments=[],surface_alias_assignments=[],source_compatibility_assignments=[]), SimpleNamespace(characters={})

    def test_ti_trim_and_ink_bottom_match_o(self):
        font,p,t=self.fixture();packed,r=build(font,p,t);pixels=decode_glyph(packed,0)
        self.assertEqual(len(packed),288);self.assertEqual(r['ink_bottom'],20)
        for c,code in [('t',0x8294),('i',0x8289)]:
            pos=r['sources'][c];b=pos['source_bbox'];source=decode_glyph(font,standard_glyph_index(code))
            for y in range(b['bbox_y']+(2 if c=='t' else 0),b['bbox_y']+b['bbox_height']):
                for x in range(b['bbox_x'],b['bbox_x']+b['bbox_width']):
                    self.assertEqual(pixels[(y+pos['y_delta'])*24+pos['x']+x-b['bbox_x']],source[y*24+x])
            self.assertEqual(pos['y_delta'],0)
        self.assertEqual(sum(v>0 for v in pixels),10*15+4*18)
        self.assertFalse(any(pixels[22*24:]));self.assertFalse(any(decode_glyph(font,INDEX)))

    def test_slot_conflicts_fail_closed(self):
        font,p,t=self.fixture()
        t.characters[CODE]='other'
        with self.assertRaisesRegex(ValueError,'conflicts'):build(font,p,t)
        t.characters.clear();p['assignments']=[dict(character='other',code='9000',glyph_index=INDEX)]
        with self.assertRaisesRegex(ValueError,'conflicts'):build(font,p,t)
        p['assignments']=[];changed=bytearray(font);changed[INDEX*288]=1
        with self.assertRaisesRegex(ValueError,'no longer blank'):build(bytes(changed),p,t)

    def test_author_title_and_reviewed_showtime_metrics(self):
        s=compact_list_name('BIG-O·Showtime')
        self.assertEqual(s,'<width:0E><space:0A><height:09>BIG-O·Showtime<width:14><space:14><height:09>')
        self.assertNotIn(CHARACTER,s)
        rendered=showtime_text()
        self.assertIn('<width:0E><space:0C><height:09>'+W_CHARACTER,rendered)
        self.assertIn('<width:10><space:0C><height:09>'+CHARACTER,rendered)
        self.assertIn('<width:10><space:0C><height:09>m',rendered)
        self.assertIn('<width:0E><space:0A><height:09>e',rendered)
        self.assertTrue(rendered.endswith('<width:14><space:14><height:09>'))

    def test_hanzi_before_and_after_compact_runs_have_explicit_full_metrics(self):
        full = '<width:14><space:14><height:09>'
        self.assertEqual(compact_list_name('脉冲高达出击'), full+'脉冲高达出击')
        for text,left,right in [('赞波特3合体','赞波特','合体'),
                                ('奥拉托里奥No.8发射','奥拉托里奥','发射'),
                                ('赞波特3赞波特','赞波特','赞波特')]:
            compiled=compact_list_name(text)
            self.assertTrue(compiled.startswith(full+left))
            self.assertTrue(compiled.endswith(full+right))

    def test_private_w_height_and_slot_guard(self):
        font,p,t=self.fixture();packed,receipt=build_w(font,p,t)
        from srwz.font import glyph_raster_metrics
        box=glyph_raster_metrics(decode_glyph(packed,0))
        self.assertEqual((box['bbox_y'],box['bbox_height']),(8,13))
        self.assertEqual((box['bbox_x'],box['bbox_width']),(6,12))
        t.characters[W_CODE]='other'
        with self.assertRaisesRegex(ValueError,'conflicts'):build_w(font,p,t)
        t.characters.clear();p['assignments']=[dict(character=W_CHARACTER,code='9000',glyph_index=1000)]
        with self.assertRaisesRegex(ValueError,'conflicts'):build_w(font,p,t)
        p['assignments']=[];changed=bytearray(font);changed[W_INDEX*288]=1
        with self.assertRaisesRegex(ValueError,'no longer blank'):build_w(bytes(changed),p,t)
