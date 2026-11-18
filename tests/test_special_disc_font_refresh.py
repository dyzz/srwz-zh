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
        start, end = cls.offsets[fonts.FONT_CHUNK:fonts.FONT_CHUNK + 2]
        cls.fits_current_slot = decode_production(cls.font).consumed <= end - start

    def test_font_refresh_preserves_every_other_byte(self):
        if not self.fits_current_slot:
            # The verified font grew past the slot of the current SP ISO (a font refresh before the next SP
            # release); the build then borrows padding, which test_growth_preserves_audio_and_later_chunks covers.
            self.skipTest('verified font is larger than the current SP ISO font slot')
        self._refresh_in_slot()

    def _refresh_in_slot(self):
        output = fonts.replace_font_slot(self.vt1, self.exe, self.font, self.digest)
        a, b = self.offsets[3:5]
        self.assertEqual(len(output), len(self.vt1))
        self.assertEqual(output[:a], self.vt1[:a])
        self.assertEqual(output[b:], self.vt1[b:])
        self.assertEqual(decode_production(output[a:b]).output, decode_production(self.font).output)

    def test_growth_preserves_audio_and_later_chunks(self):
        size = (len(self.font) + 15) // 16 * 16
        offsets = [0, 16, 1024, 2048, 2048 + size - 16, 2048 + size + 64]
        exe = bytearray(fonts.VT1_TABLE + 24)
        struct.pack_into('<6I', exe, fonts.VT1_TABLE, *offsets)
        vt = bytearray(offsets[-1]); vt[1024:2048] = bytes(range(256)) * 4
        vt[offsets[4]:] = b'Z' * (offsets[-1] - offsets[4])
        output, patched, proof = fonts.replace_font_with_relocation(bytes(vt), bytes(exe), self.font, self.digest)
        self.assertEqual(proof['borrowed_bytes'], 16)
        self.assertEqual(output[1008:2032], vt[1024:2048])
        self.assertEqual(output[offsets[4]:], vt[offsets[4]:])
        self.assertEqual(len(output), len(vt))
        self.assertEqual(fonts.sp_offsets(patched, fonts.VT1_TABLE, len(output)), [0,16,1008,2032,*offsets[4:]])
        vt[1023] = 1
        with self.assertRaisesRegex(ValueError, 'nonzero donor'):
            fonts.replace_font_with_relocation(bytes(vt), bytes(exe), self.font, self.digest)

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
