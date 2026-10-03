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
        self.assertEqual(profiles['original']['restored_chunks'],[159,160,161,162])
        self.assertEqual(profiles['sp']['restored_chunks'],[163,164,165,169])
        for c in profiles.values():
            self.assertEqual(len(c['cells']),5)
            for p in c['patches']:
                if p['operation']=='native_restore':self.assertEqual(p['native_hex'],p['after_hex'])
                else:self.assertNotIn(p['chunk'],c['restored_chunks'])
        self.assertTrue({p['chunk'] for p in profiles['original']['patches']}.isdisjoint({20,192,730}))

if __name__=='__main__':unittest.main()
