"""SP patch guards against wrong-edition locations and preserves unrelated edits."""
import copy
import json
import unittest
from pathlib import Path
from tools.srwz.battle_square_skip import (
    apply_battle_square_skip, verify_battle_square_skip, executable_write_ranges,
    BattleSquareSkipError,
)
from tests.test_battle_square_skip import _synthetic_executable

ROOT = Path(__file__).resolve().parents[1]


class SpecialDiscSquareSkipTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT/'config/products/special-disc/battle-square-skip.json').read_text())
        self.pristine = _synthetic_executable(self.contract, 'sp')

    def test_patch_roundtrip_preserves_other_localization(self):
        source = bytearray(self.pristine)
        source[0x12000:0x12008] = b'ZH-TEXT!'
        source = bytes(source)
        patched, _ = apply_battle_square_skip(source, self.contract, 'sp')
        verify_battle_square_skip(patched, self.contract, 'sp')
        again, _ = apply_battle_square_skip(patched, self.contract, 'sp')
        self.assertEqual(again, patched)
        restored, _ = apply_battle_square_skip(patched, {**self.contract,'enabled':False}, 'sp')
        self.assertEqual(restored, source)
        ranges = executable_write_ranges(self.contract,'sp')
        for i,(a,b) in enumerate(zip(source,patched)):
            if a!=b:self.assertTrue(any(lo<=i<hi for lo,hi in ranges))

    def test_unknown_cave_and_partial_install_fail(self):
        ranges = executable_write_ranges(self.contract,'sp')
        for lo,hi in ranges:
            with self.subTest(offset=lo):
                corrupt=bytearray(self.pristine);corrupt[lo:lo+4]=b'BAD!'
                with self.assertRaises(BattleSquareSkipError):
                    apply_battle_square_skip(bytes(corrupt),self.contract,'sp')
        patched,_=apply_battle_square_skip(self.pristine,self.contract,'sp')
        mixed=bytearray(self.pristine);lo,hi=ranges[0];mixed[lo:hi]=patched[lo:hi]
        with self.assertRaises(BattleSquareSkipError):
            apply_battle_square_skip(bytes(mixed),self.contract,'sp')

    def test_wrong_edition_cave_is_rejected(self):
        contract=copy.deepcopy(self.contract)
        contract['editions']['sp']['cave']['virtual_address']='0x3f6000'
        with self.assertRaises(BattleSquareSkipError):
            apply_battle_square_skip(self.pristine,contract,'sp')
