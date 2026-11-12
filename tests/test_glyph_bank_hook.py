"""The early draw hook swaps Latin glyph indices to the HarmonyOS bank in proportional scenes only."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
from test_library_protagonist_names import run_mips
from srwz import latin_bank
from srwz.proportional_hooks import glyph_bank_hook

SCRATCH, GLOBALS, DESCRIPTORS, STATE, CODE, SITE, DYNAMIC = 0x70000000, 0x3000, 0x3100, 0x3400, 0x4000, 0x5000, 0x5800
PUNCTUATION = [0x9868, 0x9873, 0xE6C3, 0x8FFF]
BASE = latin_bank.base_glyph_index()


class Memory:
    """Flat low RAM plus the scratchpad page the renderer keeps its glyph state in."""

    def __init__(self):
        self.low, self.pad = bytearray(0x10000), bytearray(0x100)

    def __len__(self):
        return SCRATCH + len(self.pad)

    def _at(self, item):
        start = item.start
        return (self.pad, start - SCRATCH, item.stop - SCRATCH) if start >= SCRATCH else (self.low, start, item.stop)

    def __getitem__(self, item):
        store, start, stop = self._at(item)
        return store[start:stop]

    def __setitem__(self, item, value):
        store, start, stop = self._at(item)
        store[start:stop] = value


class GlyphBankHookTests(unittest.TestCase):
    def run_hook(self, code, *, native_index=1234, size=(21, 12), explicit=True, source=0x2010, owner=0x2000, end=0x2040):
        hook = glyph_bank_hook(GLOBALS, DESCRIPTORS, STATE, SITE, bank_base=BASE, punctuation=PUNCTUATION, dynamic_path=DYNAMIC)

        def attempt(stop, trap):
            memory = Memory()
            memory[CODE:CODE + len(hook)] = hook
            memory[trap:trap + 4] = b'\xff\xff\xff\xff'           # the other exit must not be reached
            memory[GLOBALS:GLOBALS + 8] = struct.pack('<II', owner, end)
            # Two scenes: 21x12 dialogue and 16x9 list; a zero word ends the table.
            memory[DESCRIPTORS:DESCRIPTORS + 52] = struct.pack('<6I', 21, 12, 0, 0, 21, 0) + struct.pack('<6I', 16, 9, 0, 0, 16, 0) + bytes(4)
            memory[SCRATCH + 0x60:SCRATCH + 0x62] = struct.pack('<H', code)
            memory[SCRATCH + 0x62:SCRATCH + 0x64] = struct.pack('<H', native_index)
            if explicit:
                memory[SCRATCH + 0x3C:SCRATCH + 0x40] = struct.pack('<HH', *size)
            else:
                memory[SCRATCH + 0x68:SCRATCH + 0x6A] = struct.pack('<H', 1)
                memory[STATE + 0x38:STATE + 0x3C] = struct.pack('<HH', *size)
            registers = [0] * 32
            registers[20], registers[29] = source, 0x8000      # s4 points past the two-byte code
            registers[24], registers[25] = 0x1111, 0x2222      # t8/t9 must survive
            run_mips(memory, registers, CODE, stop)
            return memory, registers

        try:
            stop = SITE + 8; memory, final = attempt(stop, DYNAMIC)
        except AssertionError:
            stop = DYNAMIC; memory, final = attempt(stop, SITE + 8)
        self.assertEqual((final[24], final[25], final[29]), (0x1111, 0x2222, 0x8000))
        scratch_index = struct.unpack('<H', memory[SCRATCH + 0x62:SCRATCH + 0x64])[0]
        published = struct.unpack('<I', memory[SCRATCH:SCRATCH + 4])[0]
        return stop, final[2], scratch_index, published

    def test_letters_and_punctuation_use_the_bank_and_resume(self):
        for code, slot in ((0x8260, 17), (0x8279, 42), (0x8281, 50), (0x829A, 75), (0x9868, 76), (0x9873, 77), (0xE6C3, 78), (0x8FFF, 79)):
            stop, v0, scratch_index, _ = self.run_hook(code)
            self.assertEqual((stop, v0, scratch_index), (SITE + 8, BASE + slot, BASE + slot), hex(code))

    def test_digits_use_the_bank_through_the_per_occurrence_path(self):
        for digit in range(10):
            stop, v0, scratch_index, published = self.run_hook(0x824F + digit)
            self.assertEqual((stop, scratch_index, published), (DYNAMIC, BASE + digit, BASE + digit))

    def test_other_characters_keep_the_native_glyph(self):
        for code in (0x8140, 0x9864, 0x96C1, 0x8FD3, 0x8259, 0x825F, 0x827A, 0x8280, 0x829B, 0x8440):
            self.assertEqual(self.run_hook(code)[:3], (SITE + 8, 1234, 1234), hex(code))

    def test_only_owned_strings_in_proportional_scenes(self):
        native = (SITE + 8, 1234, 1234)
        self.assertEqual(self.run_hook(0x8260, owner=0)[:3], native)                       # string not captured
        self.assertEqual(self.run_hook(0x8260, source=0x2001)[:3], native)                 # code before the string
        self.assertEqual(self.run_hook(0x8260, source=0x2042)[:3], native)                 # past the terminator
        self.assertEqual(self.run_hook(0x8260, size=(24, 9))[:3], native)                  # unknown cell size
        self.assertEqual(self.run_hook(0x8260, size=(21, 9))[:3], native)                  # width alone is not a scene
        self.assertEqual(self.run_hook(0x8260, size=(16, 9))[:3], (SITE + 8, BASE + 17, BASE + 17))
        self.assertEqual(self.run_hook(0x8260, explicit=False)[:3], (SITE + 8, BASE + 17, BASE + 17))
        self.assertEqual(self.run_hook(0x8260, explicit=False, size=(30, 12))[:3], native)


if __name__ == '__main__':
    unittest.main()
