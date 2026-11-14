import base64
import copy
import json
import sys
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.ui_menu_restore import apply_menu_restore, sha

ROOT = Path(__file__).resolve().parents[1]


def frozen(b):
    return base64.b64encode(zlib.compress(b)).decode()


class MenuRestoreGuardTests(unittest.TestCase):
    def setUp(self):
        self.atlas = b'h' * 64 + bytes(32768) + b'palette-trailer'
        self.draw = bytes.fromhex('07000000440000000000') + bytes(20) + bytes([0, 0, 2, 2])
        after = bytearray(self.draw)
        after[4] = 0x43
        after[-4:] = bytes([1, 1, 3, 3])
        out = bytearray(self.atlas)
        out[64+128:64+130] = b'\x10\x0f'
        out[64+256:64+258] = b'\x70\x08'
        self.after = bytes(out), bytes(after)
        self.config = dict(atlas_size=len(self.atlas), drawings_size=len(self.draw),
            before=dict(atlas=sha(self.atlas), drawings=sha(self.draw)),
            after=dict(atlas=sha(out), drawings=sha(after)),
            pages=[dict(index=3,start=0,end=len(out),container_sha256=sha(self.atlas[:64]+self.atlas[32832:]),
                        protected_uv_zlib_base64=frozen(bytes(65536)))],
            cells=[dict(kind='relocate', page=3, rect=[1,1,2,2],
                        before_sha256=sha(bytes(4)),sha256=sha(bytes([1,15,7,8])),
                        indices_zlib_base64=frozen(bytes([1,15,7,8])))],
            patches=[dict(offset=0,operation='relocate',before_hex=self.draw.hex(),after_hex=after.hex())])
        self.parser = patch('srwz.ui_menu_restore.parse_tim2', return_value=SimpleNamespace(pictures=[
            SimpleNamespace(width=256,height=256,image_type=4,offset=0,header_size=64,image_size=32768)]))
        self.parser.start();self.addCleanup(self.parser.stop)

    def run_config(self, config=None, atlas=None):
        return apply_menu_restore(self.atlas if atlas is None else atlas,self.draw,ROOT,config=config or self.config)

    def test_odd_x_preserves_neighbor_nibbles_palette_and_geometry(self):
        self.assertEqual(self.run_config()[:2], self.after)
        self.assertEqual(apply_menu_restore(*self.after,ROOT,config=self.config)[:2],self.after)
        self.assertEqual(self.after[1][5:30],self.draw[5:30])

    def test_protected_native_uv_is_rejected(self):
        c=copy.deepcopy(self.config);mask=bytearray(65536);mask[257]=1
        c['pages'][0]['protected_uv_zlib_base64']=frozen(mask)
        with self.assertRaisesRegex(ValueError,'overlaps native/current UV'):self.run_config(c)

    def test_palette_drift_rejected_even_if_member_lock_is_changed(self):
        a=self.atlas[:-1]+b'X';c=copy.deepcopy(self.config);c['before']['atlas']=sha(a)
        with self.assertRaisesRegex(ValueError,'CLUT/trailer drift'):self.run_config(c,a)

    def test_cross_page_slot_collision_and_geometry_changes_rejected(self):
        original_draw = self.draw
        for byte,value,error in [(4,0x46,'slot collision'),(14,1,'geometry changed')]:
            self.draw = original_draw
            c=copy.deepcopy(self.config);a=bytearray.fromhex(c['patches'][0]['after_hex']);a[byte]=value
            c['patches'][0]['after_hex']=a.hex()
            if byte==4:
                original=bytearray(self.draw);original[4]=0x54
                self.draw=bytes(original);c['before']['drawings']=sha(self.draw)
                c['patches'][0]['before_hex']=self.draw.hex()
                a[4]=0x56;c['patches'][0]['after_hex']=a.hex()
            with self.assertRaisesRegex(ValueError,error):self.run_config(c)

    def test_native_separator_can_restore_geometry_without_changing_header(self):
        before=bytes(16);after=bytes(8)+bytes(range(8));c=copy.deepcopy(self.config)
        c.update(drawings_size=16,patches=[dict(offset=0,operation='native_restore',before_hex=before.hex(),after_hex=after.hex(),native_hex=after.hex())])
        c['before']['drawings']=sha(before);c['after']['drawings']=sha(after)
        self.assertEqual(apply_menu_restore(self.atlas,before,ROOT,config=c)[1],after)

    def test_recipe_restores_all_requested_chunks_and_keeps_shared_borrowers(self):
        profiles=json.loads((ROOT/'config/assets/ui-menu-native-restore.json').read_text())['profiles']
        self.assertEqual(profiles['original']['restored_chunks'],[158,159,160,161,162,204])
        self.assertEqual(profiles['sp']['restored_chunks'],[162,163,164,165,167,168,169])
        for c in profiles.values():
            self.assertEqual(len(c['cells']),6 if c is profiles['original'] else 5)
            for p in c['patches']:
                if p['operation']=='native_restore':self.assertEqual(p['native_hex'],p['after_hex'])
                else:self.assertNotIn(p['chunk'],c['restored_chunks'])
        self.assertTrue({p['chunk'] for p in profiles['original']['patches']}.isdisjoint({20,192,730}))

    def test_command_headings_are_native_and_item_is_relocated(self):
        profiles=json.loads((ROOT/'config/assets/ui-menu-native-restore.json').read_text())['profiles']
        for edition,c in profiles.items():
            cell=next(x for x in c['cells'] if x['id']=='command')
            self.assertEqual(cell['kind'],'native_restore')
            pixels=zlib.decompress(base64.b64decode(cell['indices_zlib_base64']))
            self.assertEqual(pixels,bytes(cell['rect'][2]*cell['rect'][3]))
            patches=[p for p in c['patches'] if p.get('token')=='command']
            self.assertEqual(len(patches),2 if edition=='original' else 6)
            for p in patches:
                self.assertEqual(p['operation'],'native_restore')
                self.assertEqual(p['after_hex'],p['native_hex'])
        c=profiles['original']
        for token in ('others','command2'):
            patches=[p for p in c['patches'] if p.get('token')==token]
            self.assertEqual(len(patches),1)
            self.assertEqual(patches[0]['operation'],'native_restore')
            self.assertEqual(patches[0]['after_hex'],patches[0]['native_hex'])
        item=next(x for x in c['cells'] if x['id']=='item')
        self.assertEqual(item['kind'],'relocate')
        self.assertEqual((item['page'],item['rect']),(3,[132,235,46,20]))
        native=next(x for x in c['cells'] if x['id']=='native-others-command')
        self.assertEqual(native['kind'],'native_restore')
        self.assertEqual(native['rect'],[40,232,215,23])

    def test_sp_standalone_command_title_reuses_the_main_game_title(self):
        import struct
        sp=json.loads((ROOT/'config/assets/special-disc/menu-atlas-overlap.json').read_bytes())
        main=json.loads((ROOT/'config/assets/ui-command-title-zh.json').read_bytes())
        title=sp['command_title']
        restore=json.loads((ROOT/'config/assets/ui-menu-native-restore.json').read_bytes())['profiles']['sp']['patches']
        approved=bytes.fromhex(main['drawing']['after_hex'])
        x,y,w,h=title['reclaimed_rect']
        self.assertEqual(title['chunks'],{'162':24032,'163':24144,'167':24912,'168':25024})
        tints=set()
        self.assertEqual(title['centre_shift'],{'162':0,'163':34,'167':4,'168':28})
        for chunk,offset in title['chunks'].items():
            block=next(d for d in sp['drawings'] if d['offset']==offset)
            native=next(bytes.fromhex(a['native_hex'])+bytes.fromhex(b['native_hex'])
                        for a,b in zip(restore,restore[1:]) if a['offset']==offset and b['offset']==offset+34)
            self.assertEqual((block['size'],block['before_sha256']),(68,sha(native)))
            delta=zlib.decompress(base64.b64decode(block['xor_zlib_base64']))
            record=bytes(a^b for a,b in zip(native,delta))
            self.assertEqual(sha(record),block['after_sha256'])
            tints.add(record[40:43])
            for at,role,centre in ((0,'border',52),(34,'face',50)):
                # Native material and tint; the approved quad, centred in its window; page 6 texels, page 4 ramp.
                self.assertEqual(record[at:at+4]+record[at+5:at+10],native[at:at+4]+native[at+5:at+10])
                self.assertEqual(record[at+4],0x46)
                u0,v0,u1,v1=record[at+30:at+34]
                self.assertEqual([u0,v0,u1,v1],title[role]['uv'])
                self.assertTrue(x<=u0<u1<=x+w and y<=v0<v1<=y+h)
                dx=struct.unpack_from('<h',native,at+10)[0]-centre
                self.assertIn(dx,(0,6))
                dx+=title['centre_shift'][chunk]
                corners=lambda r,d=0:sorted((px+d,py) for px,py in zip(*[iter(struct.unpack_from('<8h',r,at+14))]*2))
                self.assertEqual(corners(record),corners(approved,dx))
                self.assertEqual(struct.unpack_from('<2h',record,at+10),
                                 (struct.unpack_from('<h',approved,at+10)[0]+dx,struct.unpack_from('<h',approved,at+12)[0]))
        self.assertEqual(len(tints),4)
        face=next(c for c in main['cells'] if c['role']=='face')
        tile=zlib.decompress(base64.b64decode(face['indices_zlib_base64']))
        upright=bytes(tile[col*18+17-row] for row in range(18) for col in range(38))
        self.assertEqual(sha(upright),title['face']['sha256'])
        self.assertLess(title['face']['uv'][2],title['border']['uv'][0])

if __name__=='__main__':unittest.main()
