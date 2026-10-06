"""Native syntax must survive glyph overrides and independent raw-byte readback."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.text import (TextTable, encode_text, decode_text, control_notation_tokens,
                       runtime_control_bytes, verify_runtime_control_bytes,
                       two_byte_visible_spaces, unrecognized_control_notation_offsets)


class NativeRuntimeControlTests(unittest.TestCase):
    def setUp(self):
        self.overrides = {ch: 0x9800 + i for i, ch in enumerate('-+%{}<>. 0123456789')}
        self.table = TextTable({code: ch for ch, code in self.overrides.items()},
                               {0x31: 'color', 0x32: 'width', 0x33: 'height', 0x34: 'space'})

    def test_whole_native_controls_survive_all_visible_punctuation_and_digit_overrides(self):
        vectors = [b'<0>', b'<8>', b'<9>', b'<10>', b'<23>', b'<40>', b'<+3>',
                   b'<-1>', b'<-2>', b'<-3>', b'<-4>', b'<-5>', b'{1}', b'{4.4.0}',
                   b'%s', b'%2d', b'%02d', b'%+03d', b'%1$02d', b'%-12.3f',
                   b'%.*s', b'% 2d', b'$c', b'$n', b'$F', b'$f', b'$l']
        for native in vectors:
            with self.subTest(native=native):
                notation = decode_text(native + b'\0', 0, self.table).text
                self.assertEqual(runtime_control_bytes(notation), (native,))
                self.assertEqual(unrecognized_control_notation_offsets(notation), ())
                self.assertEqual([(t.start, t.end) for t in control_notation_tokens(notation)],
                                 [(0, len(notation))])
                encoded = encode_text(notation, self.table, overrides=self.overrides, terminate=True)
                self.assertEqual(encoded, native + b'\0')
                self.assertEqual(verify_runtime_control_bytes(encoded, self.table, notation), (native,))

    def test_independent_readback_rejects_same_text_with_glyph_encoded_control_byte(self):
        vectors = [(b'<0>', b'<' + self.overrides['0'].to_bytes(2, 'big') + b'>'),
                   (b'<-3>', b'<' + self.overrides['-'].to_bytes(2, 'big') + b'3>'),
                   (b'{4.4.0}', b'{4.4.' + self.overrides['0'].to_bytes(2, 'big') + b'}')]
        for native, damaged in vectors:
            with self.subTest(native=native):
                expected = decode_text(native + b'\0', 0, self.table).text
                self.assertEqual(decode_text(damaged + b'\0', 0, self.table).text, expected)
                with self.assertRaisesRegex(ValueError, 'runtime control bytes drift'):
                    verify_runtime_control_bytes(damaged + b'\0', self.table, expected)

    def test_visible_glyphs_layout_tags_and_raw_byte_notation_keep_their_roles(self):
        notation = '0-<0><width:16>{12}'
        self.assertEqual(encode_text(notation, self.table, overrides=self.overrides),
                         self.overrides['0'].to_bytes(2, 'big') +
                         self.overrides['-'].to_bytes(2, 'big') + b'<0>\x32\x16\x12')
        self.assertEqual(runtime_control_bytes(notation), (b'<0>',))
        self.assertEqual(two_byte_visible_spaces('A % 2d B'), 'A　% 2d　B')
        self.assertEqual(runtime_control_bytes('{}'), ())
        self.assertEqual(encode_text('{}', self.table, overrides=self.overrides),
                         self.overrides['{'].to_bytes(2, 'big') + self.overrides['}'].to_bytes(2, 'big'))

    def test_missing_added_or_reordered_controls_fail_readback(self):
        for payload in (b'<0>\0', b'<9><0>\0', b'<0><9><8>\0'):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, 'sequence/order'):
                    verify_runtime_control_bytes(payload, self.table, '<0><9>')


if __name__ == '__main__':
    unittest.main()
