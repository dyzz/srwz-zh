"""Regression checks against the locked native selector tables (when available)."""
import struct
import unittest
from pathlib import Path

from tools.srwz.srvc_selector_fixes import repair_srvc_selectors, candidate_sequences, FIXES, _sequence

ROOT = Path(__file__).resolve().parents[1]


class SelectorRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = ROOT / 'work/disc/BTL/SRVC.BIN'
        if not p.exists():
            raise unittest.SkipTest('locked native SRVC source unavailable')
        cls.source = p.read_bytes()
        seg = (p.parent / 'SRVC.SEG').read_bytes()
        cls.offsets = struct.unpack('<' + str(len(seg)//4) + 'I', seg)
        cls.output, cls.proof = repair_srvc_selectors(cls.source, cls.offsets)

    def test_only_six_effective_conditions_change(self):
        changes = set()
        for ci in range(len(self.offsets)-1):
            lo, hi = self.offsets[ci:ci+2]
            if ci not in (59, 60, 335):
                self.assertEqual(self.source[lo:hi], self.output[lo:hi])
                continue
            old = candidate_sequences(self.source[lo:hi])
            new = candidate_sequences(self.output[lo:hi])
            for candidate in old:
                if old[candidate] != new[candidate]:
                    changes.add((ci, candidate))
                    self.assertEqual(new[candidate], _sequence(FIXES[ci,candidate][1]))
        self.assertEqual(changes, set(FIXES))
        self.assertEqual(len(self.source), len(self.output))

    def test_shared_witnesses_keep_their_original_targets(self):
        for ci, candidates in [(59, [48,50]), (60,[0,13,15,150,152]), (335,[16,48])]:
            lo,hi=self.offsets[ci:ci+2]
            a=candidate_sequences(self.source[lo:hi]);b=candidate_sequences(self.output[lo:hi])
            for candidate in candidates:self.assertEqual(a[candidate],b[candidate])
        lo,hi=self.offsets[60:62]
        sara=candidate_sequences(self.output[lo:hi])[162]
        self.assertIn(bytes.fromhex('0100010000006800'),sara)
        self.assertNotIn(bytes.fromhex('0100010000006600'),sara)
        self.assertIn(bytes.fromhex('0201010000003000'),sara)

    def test_text_indices_metadata_payloads_and_tail_unchanged(self):
        for ci in (59,60,335):
            lo,hi=self.offsets[ci:ci+2]
            _,pc,n,_=struct.unpack_from('<4H',self.source,lo)
            end=lo+324+n*8+(pc&255)*8+(pc>>8)*4
            self.assertEqual(self.source[end:hi],self.output[end:hi])
            self.assertEqual(self.source[lo:lo+324],self.output[lo:lo+324])

    def test_fail_closed_on_source_drift_or_double_application(self):
        altered=bytearray(self.source);altered[self.offsets[60]+324+162*8+2]^=1
        with self.assertRaisesRegex(ValueError,'source lock drift'):
            repair_srvc_selectors(bytes(altered),self.offsets)
        with self.assertRaisesRegex(ValueError,'source lock drift'):
            repair_srvc_selectors(self.output,self.offsets)
