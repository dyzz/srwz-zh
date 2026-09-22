import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.text import PreparedTextEncoder, TextTable, decode_text
from special_disc.writeback.instruction_overrides import apply_fixed, sha


class InstructionFixedSlotTests(unittest.TestCase):
    def setUp(self):
        self.table = TextTable({0x8141: '甲', 0x8142: '乙', 0x8143: '丙'}, {})
        self.encoder = PreparedTextEncoder(self.table, {})
        source = bytearray(b'\x55' * 128)
        source[64:72] = self.encoder.encode('甲甲', terminate=True).ljust(8, b'\0')
        struct.pack_into('<I', source, 16, 0x764F80 + 64)
        self.source = bytes(source)
        current = bytearray(source)
        current[64:72] = self.encoder.encode('乙乙', terminate=True).ljust(8, b'\0')
        self.current = bytes(current)
        self.row = dict(id='fixture', source_text='甲甲', baseline_translation='乙乙',
                        translation='丙', location=dict(member='DATA/COMPDATA.BN',
                        offset=64, capacity=8, pointer_sites=[16],
                        source_slot_sha256=sha(source[64:72]),
                        baseline_slot_sha256=sha(current[64:72])))

    def apply(self, current=None, row=None):
        return apply_fixed(self.current if current is None else current, self.source,
                           [self.row if row is None else row], self.encoder,
                           self.table, self.table)

    def test_shorter_text_clears_old_suffix_and_preserves_neighbors_and_pointer(self):
        output = self.apply()
        self.assertEqual(decode_text(output, 64, self.table).text, '丙')
        self.assertEqual(output[67:72], bytes(5))
        self.assertEqual(output[:64], self.current[:64])
        self.assertEqual(output[72:], self.current[72:])

    def test_concurrent_slot_edit_is_not_silently_overwritten(self):
        current = bytearray(self.current)
        current[65] = 0x43
        with self.assertRaisesRegex(ValueError, 'preimage drift'):
            self.apply(bytes(current))

    def test_pointer_drift_outside_text_slot_is_rejected(self):
        current = bytearray(self.current)
        struct.pack_into('<I', current, 16, 0x764F80 + 72)
        with self.assertRaisesRegex(ValueError, 'pointer drift'):
            self.apply(bytes(current))

    def test_capacity_overflow_is_rejected_without_truncation(self):
        row = copy.deepcopy(self.row)
        row['translation'] = '丙' * 4
        with self.assertRaisesRegex(ValueError, 'overflow'):
            self.apply(row=row)


if __name__ == '__main__':
    unittest.main()
