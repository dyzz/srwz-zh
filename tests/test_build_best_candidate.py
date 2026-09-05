"""Small fixtures for the experimental three-way migration safety boundary."""
import importlib.util
import struct
import unittest
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'tools/build_best_candidate.py'
spec=importlib.util.spec_from_file_location('best_candidate',path)
best=importlib.util.module_from_spec(spec)
spec.loader.exec_module(best)

def packed(*values):
    return struct.pack('<'+'I'*len(values),*values)

class BestMergeTests(unittest.TestCase):
    def test_player_name_uses_native_dollar_n_token(self):
        self.assertEqual(best.replace_default_player_name(b'speaker\n\x81\x40RAND!\0', b'RAND'), b'speaker\n\x81\x40$n!\0')
        with self.assertRaises(AssertionError):
            best.replace_default_player_name(b'already $n!\0', b'RAND')

    def test_relocated_chinese_pointer_and_best_native_change(self):
        source=packed(0x756800,7)
        native=packed(0x757000,9)
        chinese=packed(0x756840,7)
        self.assertEqual(best.port_word_changes(source,native,chinese),packed(0x757040,9))

    def test_unknown_nontext_overlap_fails(self):
        with self.assertRaises(AssertionError):
            best.port_word_changes(packed(1),packed(2),packed(3))

    def test_text_ownership_does_not_authorize_neighbor_field(self):
        with self.assertRaises(AssertionError):
            best.port_word_changes(b'abcd',b'AbcD',b'Xbcd',text_mask=b'\1\0\0\0')

    def test_owned_text_overlap_is_allowed(self):
        self.assertEqual(best.port_word_changes(b'abcd',b'Abcd',b'Xbcd',text_mask=b'\1\0\0\0'),b'Xbcd')

    def test_inserted_best_bytes_are_preserved(self):
        self.assertEqual(best.port_word_changes(b'abcd',b'NEW!abcd',b'Abcd',shift=4),b'NEW!Abcd')

    def test_piecewise_data_relocation(self):
        self.assertEqual(best.port_word_changes(b'abcdEFGH',b'1111abcd2222EFGH',b'AbcdEfGH',shift=lambda o:4 if o<4 else 8),b'1111Abcd2222EfGH')

if __name__=='__main__':
    unittest.main()
