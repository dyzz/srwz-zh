"""Exercise the real chart initializer's boolean result and patch boundary."""
import hashlib
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
import chart_visibility as cv


class ChartVisibilityTests(unittest.TestCase):
    def fixture(self):
        data=bytearray(0x1000)
        data[cv.CONTEXT_START:cv.CONTEXT_START+len(cv.CONTEXT)]=cv.CONTEXT
        return bytes(data)

    def test_only_result_instruction_changes_not_query_or_save(self):
        data=self.fixture()
        with patch.object(cv,'INITIALIZER_SHA256',hashlib.sha256(data[0xB70:0xF50]).hexdigest()):
            after=cv.patch_flow(data)
        self.assertEqual(after[:cv.SITE],data[:cv.SITE])
        self.assertEqual(after[cv.SITE+4:],data[cv.SITE+4:])
        self.assertEqual(after[0xD80:0xD84],bytes.fromhex('1054050c'))  # original jal
        w=struct.unpack_from('<I',after,cv.SITE)[0]
        # Execute ADDIU: value is independent of the queried progress bit.
        self.assertEqual((w>>26,(w>>21)&31,(w>>16)&31,w&65535),(9,0,10,1))
        for progress in (0,1,2,0x8000,0xFFFF):
            registers=[0]*32;registers[2]=progress
            registers[(w>>16)&31]=registers[(w>>21)&31]+(w&65535)
            self.assertEqual(registers[10],1)
            self.assertEqual(registers[2],progress)

    def test_initializer_drift_fails_closed(self):
        data=self.fixture();expected=hashlib.sha256(data[0xB70:0xF50]).hexdigest()
        for site in (0xB70,0xD18,0xD70,0xD80,cv.SITE):
            changed=bytearray(data);changed[site]^=1
            with patch.object(cv,'INITIALIZER_SHA256',expected):
                with self.assertRaisesRegex(ValueError,'function drift'):cv.patch_flow(changed)

    def test_short_or_already_patched_input_rejected(self):
        for data in (b'',bytes(20),self.fixture()[:cv.SITE]+cv.AFTER+self.fixture()[cv.SITE+4:]):
            with self.assertRaises(ValueError):cv.patch_flow(data)

if __name__=='__main__':unittest.main()
