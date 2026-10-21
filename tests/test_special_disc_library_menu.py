from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.source import SOURCE_ISO
from special_disc.writeback.library_menu import apply_library_menu, verify_library_menu, TABLE
from special_disc.writeback.install_font import sp_offsets
from srwz.iso9660 import scan_iso9660, member_map
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.tim2 import scan_tim2


@unittest.skipUnless(SOURCE_ISO.is_file(), 'local SP source disc required')
class SpecialDiscLibraryMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        members = member_map(scan_iso9660(SOURCE_ISO))
        def read(name):
            m = members[name]
            with SOURCE_ISO.open('rb') as stream:
                stream.seek(m.extent_lba * 2048)
                return stream.read(m.size)
        cls.source = read('DATA/NISVDATA.BIN')
        cls.exe = read('SLPS_259.20')
        cls.output, cls.report = apply_library_menu(cls.source, cls.exe, cls.source)

    def test_shared_labels_fit_sp_slot_and_roundtrip(self):
        self.assertEqual(verify_library_menu(self.output, self.exe, self.source), self.report)
        self.assertEqual(self.report['labels']['攻略Ｑ＆Ａ'], '攻略问答')
        self.assertEqual(self.report['point_size'], 22)
        self.assertEqual(len(self.output), len(self.source))
        end = sp_offsets(self.exe, TABLE, len(self.source))[1]
        self.assertEqual(self.output[end:], self.source[end:])
        self.assertEqual(apply_library_menu(self.output, self.exe, self.source)[0], self.output)

    def test_untranslated_labels_fail_readback(self):
        with self.assertRaisesRegex(ValueError, 'label readback drift'):
            verify_library_menu(self.source, self.exe, self.source)

    def test_unrelated_decoded_bytes_survive(self):
        end = sp_offsets(self.exe, TABLE, len(self.source))[1]
        result = decode_production(self.output[:end])
        data = bytearray(result.output)
        # A different TIM2 record belongs to SP, not the shared six labels.
        record = next(r for r in scan_tim2(data) if r.offset != self.report['record_offset'])
        at = record.pictures[0].offset + record.pictures[0].header_size
        data[at] ^= 1
        encoded = reencode_changed_suffix(self.output[:result.consumed], bytes(data),
                                          strategy='rust-fit', original_result=result, max_output_size=end)
        changed = encoded + bytes(end-len(encoded)) + self.output[end:]
        reapplied, _ = apply_library_menu(changed, self.exe, self.source)
        self.assertEqual(reapplied, changed)

    def test_source_identity_drift_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source TIM2 identity drift'):
            apply_library_menu(self.output, self.exe, self.output)
