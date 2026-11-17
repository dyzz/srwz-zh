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


OPTIONS = 0x3800


class GlyphBankHookTests(unittest.TestCase):
    def run_hook(self, code, *, native_index=1234, size=(21, 12), explicit=True, source=0x2010, owner=0x2000, end=0x2040,
                 options=None):
        hook = glyph_bank_hook(GLOBALS, DESCRIPTORS, STATE, SITE, bank_base=BASE, punctuation=PUNCTUATION, dynamic_path=DYNAMIC,
                               options=None if options is None else OPTIONS)

        def attempt(stop, trap):
            memory = Memory()
            memory[CODE:CODE + len(hook)] = hook
            memory[trap:trap + 4] = b'\xff\xff\xff\xff'           # the other exit must not be reached
            memory[GLOBALS:GLOBALS + 8] = struct.pack('<II', owner, end)
            # Scenes: 21x12 dialogue, 20x11 map dialogue, 16x9 list; a zero word ends the table.
            memory[DESCRIPTORS:DESCRIPTORS + 76] = (struct.pack('<6I', 21, 12, 0, 0, 21, 0) + struct.pack('<6I', 20, 11, 0, 0, 20, 0)
                                                    + struct.pack('<6I', 16, 9, 0, 0, 16, 0) + bytes(4))
            if options is not None:
                memory[OPTIONS:OPTIONS + 4] = struct.pack('<I', options)
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

    def test_display_options_zero_word_keeps_the_default_look(self):
        for code in (0x824F, 0x8250, 0x8260):
            self.assertEqual(self.run_hook(code, options=0), self.run_hook(code), hex(code))
        for code in (0x9141, 0x8167, 0x8FE7, 0x8168):
            self.assertEqual(self.run_hook(code, options=0)[:3], (SITE + 8, 1234, 1234), hex(code))

    def test_plain_zero_option_swaps_only_the_zero(self):
        stop, _, scratch_index, published = self.run_hook(0x824F, options=1)
        self.assertEqual((stop, scratch_index, published), (DYNAMIC, BASE + 10, BASE + 10))
        stop, _, scratch_index, _ = self.run_hook(0x8255, options=1)
        self.assertEqual((stop, scratch_index), (DYNAMIC, BASE + 6))
        self.assertEqual(self.run_hook(0x9141, options=1)[:3], (SITE + 8, 1234, 1234))

    def test_japanese_quote_option_only_in_the_dialogue_scenes(self):
        for code, slot in ((0x9141, 80), (0x8167, 80), (0x8FE7, 81), (0x8168, 81)):
            for size in ((21, 12), (20, 11)):
                self.assertEqual(self.run_hook(code, options=2, size=size)[:3], (SITE + 8, BASE + slot, BASE + slot), hex(code))
            self.assertEqual(self.run_hook(code, options=2, size=(16, 9))[:3], (SITE + 8, 1234, 1234), hex(code))
            self.assertEqual(self.run_hook(code, options=2, owner=0)[:3], (SITE + 8, 1234, 1234), hex(code))
        self.assertEqual(self.run_hook(0x824F, options=2)[2], BASE)        # the zero keeps its dot

    def test_extra_slots_are_free_bank_cells(self):
        self.assertFalse(set(latin_bank.EXTRA_SLOTS) & set(latin_bank.slot_characters()))
        self.assertTrue(all(0 <= slot < latin_bank.SLOT_COUNT for slot in latin_bank.EXTRA_SLOTS))


if __name__ == '__main__':
    unittest.main()
