"""Font audits accept decoder notation but reject glyph-encoded native controls."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz.text import TextTable, decode_text
from verify_zh_release_font import runtime_placeholder_bytes_are_exact


class ReleaseFontRuntimeControlTests(unittest.TestCase):
    def setUp(self):
        self.table = TextTable(
            {0x9800: "0", 0x9801: "-", 0x9802: "%"},
            {0x31: "color", 0x32: "width", 0x33: "height", 0x34: "space"},
        )

    def test_accepts_complete_native_controls_in_lossless_decoder_notation(self):
        for native in (b"<0>", b"<10>", b"<-3>", b"{4.4.0}", b"%02d",
                       b"% 2d", b"%s", b"$c", b"$F"):
            with self.subTest(native=native):
                notation = decode_text(native, 0, self.table, allow_end=True).text
                self.assertTrue(runtime_placeholder_bytes_are_exact(notation, self.table))

    def test_rejects_wrong_bytes_even_when_decoded_text_matches(self):
        native = b"<0>"
        damaged = b"<\x98\x00>"
        notation = decode_text(native, 0, self.table, allow_end=True).text
        self.assertEqual(decode_text(damaged, 0, self.table, allow_end=True).text, notation)
        with patch("verify_zh_release_font.encode_text", return_value=damaged):
            self.assertFalse(runtime_placeholder_bytes_are_exact(notation, self.table))

    def test_rejects_missing_extra_or_changed_controls(self):
        for damaged in (b"", b"<9>", b"<0><9>", b"x<0>"):
            with self.subTest(damaged=damaged):
                with patch("verify_zh_release_font.encode_text", return_value=damaged):
                    self.assertFalse(runtime_placeholder_bytes_are_exact("<0>", self.table))


if __name__ == "__main__":
    unittest.main()
