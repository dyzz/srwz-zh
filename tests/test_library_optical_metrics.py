"""Production patch boundaries and mixed-run typography contracts."""
from pathlib import Path
import struct,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.library_body_metrics import EDITIONS,apply_library_body_metrics,write_ranges as body_ranges
from srwz.library_optical_metrics import native_preimages,write_ranges,apply_library_optical_metrics,verify_library_optical_metrics
from srwz.library_typography import library_typography
from srwz.text import CONTROL_NOTATION
from build_library_v02_component import reflow_body

class OpticalMetricsTests(unittest.TestCase):
    def fixture(self,edition):
        s=EDITIONS[edition];data=bytearray(max(b for a,b in write_ranges(edition)))
        for va,before in native_preimages(edition):
            off=va-s['delta'];data[off:off+len(before)]=before
        hook=s['hook']-s['delta'];data[hook-8:hook]=bytes.fromhex('2d4080022110c200')
        struct.pack_into('<I',data,hook,3<<26|s['draw']>>2);data[hook+4:hook+8]=bytes.fromhex('000040a0')
        return bytes(data)

    def test_guarded_regions_are_disjoint_and_idempotent(self):
        for ed in EDITIONS:
            with self.subTest(edition=ed):
                native=self.fixture(ed);patched,report=apply_library_optical_metrics(native,ed)
                allowed={i for lo,hi in write_ranges(ed) for i in range(lo,hi)}
                changed={i for i,(a,b) in enumerate(zip(native,patched)) if a!=b}
                self.assertTrue(changed);self.assertLessEqual(changed,allowed)
                self.assertEqual(len(native),len(patched));self.assertTrue(verify_library_optical_metrics(patched,ed)['already_applied'])
                self.assertEqual(apply_library_optical_metrics(patched,ed)[0],patched)
                body_owned={i for lo,hi in body_ranges(ed) for i in range(lo,hi)}
                self.assertFalse(body_owned&allowed)
                left=apply_library_body_metrics(patched,ed)[0]
                right=apply_library_optical_metrics(apply_library_body_metrics(native,ed)[0],ed)[0]
                self.assertEqual(left,right)
                for at,_ in write_ranges(ed):
                    bad=bytearray(native);bad[at]^=1
                    with self.assertRaisesRegex(ValueError,'preimage drift'):
                        apply_library_optical_metrics(bytes(bad),ed)
                mixed=bytearray(native);a,b=write_ranges(ed)[0];mixed[a:b]=patched[a:b]
                with self.assertRaisesRegex(ValueError,'partial patch'):
                    apply_library_optical_metrics(bytes(mixed),ed)

    def test_mixed_identifier_switches_height_inside_one_horizontal_scope(self):
        for domain,letters,digits,restore in (('character','8C','0B','0C'),('robot','8B','8A','8A')):
            text='中文RX-78F14 99.9%中文'
            result=library_typography(text,'DSCR',domain=domain)
            expected=f'<height:{letters}>RX-<height:{digits}>78<height:{letters}>F<height:{digits}>14 99.9%'
            self.assertIn(expected,result)
            self.assertEqual(result.count('<width:0E><space:0C>'),1)
            self.assertIn(f'<space:15><width:15><height:{restore}>中文',result)
            self.assertEqual(CONTROL_NOTATION.sub('',result),text)
            self.assertEqual(library_typography(result,'DSCR',domain=domain),result)
            # Recompilation after a domain change must discard every generated
            # inner height while preserving logical identifiers and percentages.
            other='robot' if domain=='character' else 'character'
            self.assertEqual(library_typography(result,'DSCR',domain=other),library_typography(text,'DSCR',domain=other))

    def test_mixed_scope_remains_atomic_when_reflowed(self):
        text='甲'*13+'RX-78F14中文'
        compiled=library_typography(text,'DSCR',domain='character');flow,widths=reflow_body(compiled,16)
        self.assertTrue(any('RX-78F14' in CONTROL_NOTATION.sub('',line) for line in flow.splitlines()))
        self.assertTrue(all(width<=16 for width in widths))
        self.assertEqual(CONTROL_NOTATION.sub('',flow).replace('\n',''),text)

    def test_custom_body_height_keeps_control_safety_and_idempotence(self):
        for h in (8,9,10,12,14,16):
            source=f'<height:{h:02X}>中文F14米'
            compiled=library_typography(source,'DSCR',domain='character')
            self.assertNotIn('<height:0A>',compiled)
            self.assertEqual(library_typography(compiled,'DSCR',domain='character'),compiled)
            self.assertEqual(CONTROL_NOTATION.sub('',compiled),'中文F14米')
