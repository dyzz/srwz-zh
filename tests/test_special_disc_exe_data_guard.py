"""Prevent translated text from corrupting verified executable jump tables."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback'),
               str(ROOT/'tools/special_disc/verification')]
from special_disc.writeback.exe_data_guard import NON_TEXT_WORDS, require_text_range
from audit_exe_non_text import verify_dispatch
from write_system_text import Writer
import export_sd_text


class ExeDataGuardTests(unittest.TestCase):
    def test_known_words_excluded_from_both_exporters_shared_inventory(self):
        self.assertEqual(len(NON_TEXT_WORDS), 7)
        self.assertTrue(set(NON_TEXT_WORDS) <= export_sd_text.EXE_NOT_TEXT)

    def test_overlap_rejected_including_writes_starting_before_word(self):
        for site in NON_TEXT_WORDS:
            for offset, size in [(site, 1), (site+3, 1), (site-2, 4)]:
                with self.assertRaisesRegex(ValueError, 'jump-table'):
                    require_text_range(offset, size)
            if site-4 not in NON_TEXT_WORDS:
                require_text_range(site-1, 1)
        require_text_range(0, 16)

    def test_writer_rejects_before_decoding_or_encoding(self):
        writer = Writer(None, None, None)
        for site in NON_TEXT_WORDS:
            data = bytearray(b'unchanged')
            with self.assertRaisesRegex(ValueError, 'jump-table'):
                writer.put(data, site, '舌(', '译文', [], f'sd/exe/{site:X}')
            self.assertEqual(data, bytearray(b'unchanged'))

    def test_indirect_jump_evidence_requires_actual_indexed_load_and_jump(self):
        # Real SLPS_259.20 instructions at file offset 0x18EBD4, relocated here.
        words = [0x3C04004B, 0x00031880, 0x248416B0, 0x00641821, 0x8C630000, 0x00600008]
        data = bytearray(256)
        struct.pack_into('<6I', data, 0, *words)
        struct.pack_into('<I', data, 128+12*4, 0x28E390)
        result = verify_dispatch(data, 0, 128, 12, 0x4B16B0-128)
        self.assertEqual(result['jump_target'], '0x28E390')
        self.assertEqual(result['loaded_word_offset'], '0xB0')
        for i in [0, 1, 2, 3, 4, 5]:
            changed = bytearray(data)
            struct.pack_into('<I', changed, i*4, 0)
            with self.assertRaises(ValueError):
                verify_dispatch(changed, 0, 128, 12, 0x4B16B0-128)


if __name__ == '__main__':
    unittest.main()
