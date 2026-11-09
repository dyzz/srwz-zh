import base64
import json
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.ui_text_clarity import apply_atlas,apply_native_select,apply_native_title_atlas,sha

class ClarityGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.atlas=bytearray(b'h'*64+bytes([0x55])*32768+b'p'*512)
        # Odd-aligned cell: its two outside neighbour nibbles must survive.
        self.before=bytes([1,15,7,8]);self.after=bytes([2,14,6,9]);self.pos=[257,258,513,514]
        for i,v in zip(self.pos,self.before):
            s=i%2*4;self.atlas[64+i//2]=(self.atlas[64+i//2]&~(15<<s))|(v<<s)
        enc=lambda b:base64.b64encode(zlib.compress(b)).decode()
        cell=dict(id='test',page=0,rect=[1,1,2,2],container_sha256=sha(self.atlas[:64]+self.atlas[32832:]),before_sha256=sha(self.before),after_sha256=sha(self.after),before_zlib_base64=enc(self.before),after_zlib_base64=enc(self.after))
        path=self.root/'config/assets/ui-text-clarity.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(dict(profiles=dict(original=dict(size=len(self.atlas),cells=[cell])))))
        parser=patch('srwz.ui_text_clarity.parse_tim2',return_value=SimpleNamespace(pictures=[SimpleNamespace(width=256,height=256,image_type=4,offset=16,header_size=48,image_size=32768)]));parser.start();self.addCleanup(parser.stop)
    def test_only_owned_nibbles_change_and_roundtrip_is_exact(self):
        result,_=apply_atlas(bytes(self.atlas),self.root)
        old=[v for b in self.atlas[64:32832] for v in (b&15,b>>4)];new=[v for b in result[64:32832]for v in(b&15,b>>4)]
        self.assertEqual([i for i in range(len(old))if old[i]!=new[i]],self.pos)
        self.assertEqual(result[:64]+result[32832:],self.atlas[:64]+self.atlas[32832:])
        self.assertEqual(apply_atlas(result,self.root)[0],result)
        self.assertEqual(apply_atlas(result,self.root,reverse=True,strict=True)[0],self.atlas)
    def test_preimage_and_clut_drift_fail_closed(self):
        for offset,error in [(64+257//2,'preimage'),(32832,'palette')]:
            bad=bytearray(self.atlas);bad[offset]^=255
            with self.assertRaisesRegex(ValueError,error):apply_atlas(bytes(bad),self.root)
    def test_verifier_rejects_old_pixels(self):
        with self.assertRaisesRegex(ValueError,'preimage'):apply_atlas(bytes(self.atlas),self.root,reverse=True,strict=True)

    def test_native_atlas_preserves_outside_nibbles_and_reverses(self):
        cell=json.loads((self.root/'config/assets/ui-text-clarity.json').read_text())['profiles']['original']['cells'][0]
        (self.root/'config/assets/ui-select-native.json').write_text(json.dumps({'profiles':{'original':{'atlas_cell':cell}}}))
        out=apply_native_title_atlas(bytes(self.atlas),self.root)
        self.assertEqual(out,apply_atlas(bytes(self.atlas),self.root)[0])
        self.assertEqual(apply_native_title_atlas(out,self.root),out)
        self.assertEqual(apply_native_title_atlas(out,self.root,reverse=True,strict=True),self.atlas)
        bad=bytearray(out);bad[64+257//2]^=16
        with self.assertRaisesRegex(ValueError,'preimage'):apply_native_title_atlas(bytes(bad),self.root)

    def test_native_select_restores_records_and_preserves_other_bytes(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'config/assets/ui-select-native.json').read_text())
        (self.root/'config/assets/ui-select-native.json').write_text(json.dumps(config))
        for ed,c in config['profiles'].items():
            data=bytearray(c['size']);owned=set()
            for p in c['patches']:
                off=p['offset'];before=bytes.fromhex(p['before_hex']);data[off:off+34]=before;owned.update(range(off,off+34))
            out,_=apply_native_select(bytes(data),self.root,ed)
            self.assertTrue(all(i in owned for i,(a,b)in enumerate(zip(data,out))if a!=b))
            self.assertEqual(apply_native_select(out,self.root,ed,reverse=True,strict=True)[0],data)
            bad=bytearray(out);bad[c['patches'][0]['offset']]^=1
            with self.assertRaisesRegex(ValueError,'preimage'):apply_native_select(bytes(bad),self.root,ed)

if __name__=='__main__':unittest.main()
