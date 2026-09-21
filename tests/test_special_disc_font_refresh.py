"""Font refresh must not overwrite the neighbouring audio or move archive chunks."""
import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.writeback import install_font as fonts
from special_disc.source import CURRENT_ISO
from srwz.codec import decode_production
from srwz.iso9660 import member_map, scan_iso9660
from build_text_candidate import read_member


class SpecialDiscFontRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = ROOT / 'work/build/special-disc/text-candidate/sp-font'
        if not CURRENT_ISO.exists() or not (root / 'font.bin').exists():
            raise unittest.SkipTest('requires local SP ISO and verified compressed font')
        members = member_map(scan_iso9660(CURRENT_ISO))
        cls.exe = read_member(CURRENT_ISO, members, fonts.EXE)
        cls.vt1 = read_member(CURRENT_ISO, members, fonts.VT1)
        cls.font = (root / 'font.bin').read_bytes()
        cls.digest = json.loads((root / 'report.json').read_text())['font']['decoded_sha256']
        cls.offsets = fonts.sp_offsets(cls.exe, fonts.VT1_TABLE, len(cls.vt1))

    def test_font_refresh_preserves_every_other_byte(self):
        output = fonts.replace_font_slot(self.vt1, self.exe, self.font, self.digest)
        a, b = self.offsets[3:5]
        self.assertEqual(len(output), len(self.vt1))
        self.assertEqual(output[:a], self.vt1[:a])
        self.assertEqual(output[b:], self.vt1[b:])
        self.assertEqual(decode_production(output[a:b]).output, decode_production(self.font).output)

    def test_rejects_wrong_font_identity(self):
        with self.assertRaisesRegex(ValueError, 'identity drift'):
            fonts.replace_font_slot(self.vt1, self.exe, self.font, '0' * 64)

    def test_rejects_overflow_without_relocating_audio(self):
        exe = bytearray(self.exe)
        struct.pack_into('<I', exe, fonts.VT1_TABLE + 16, self.offsets[3] + len(self.font) - 1)
        with self.assertRaisesRegex(ValueError, 'exceeds existing slot'):
            fonts.replace_font_slot(self.vt1, bytes(exe), self.font, self.digest)


if __name__ == '__main__':
    unittest.main()
