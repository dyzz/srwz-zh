import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.library_button_labels import SITES, apply_library_button_labels, verify_library_button_labels

class LibraryButtonLabelsTests(unittest.TestCase):
    def native(self, edition):
        at = SITES[edition][0]
        fixture = json.loads((ROOT / 'tests/fixtures/library-button-labels-native.json').read_text())[edition]
        return b'\xa5' * at + bytes.fromhex(fixture) + b'\x5a' * 32

    def test_three_editions_change_only_the_shared_enable_call(self):
        for edition, (at, before, after, _) in SITES.items():
            with self.subTest(edition=edition):
                native = self.native(edition)
                out, report = apply_library_button_labels(native, edition)
                self.assertFalse(report['already_applied'])
                self.assertEqual(out[:at], native[:at])
                self.assertEqual(out[at+4:], native[at+4:])
                self.assertEqual(out[at:at+4], bytes.fromhex(after))
                # Call the existing reset helper, leaving the original trailing reset intact.
                self.assertEqual(out[at:at+4], native[at+168:at+172])
                self.assertEqual(apply_library_button_labels(out, edition)[0], out)
                self.assertTrue(verify_library_button_labels(out, edition)['already_applied'])

    def test_rejects_unpatched_readback(self):
        with self.assertRaisesRegex(ValueError, 'patch missing'):
            verify_library_button_labels(self.native('sp'), 'sp')

    def test_rejects_changed_call_and_neighboring_context(self):
        for delta, message in [(0, 'preimage'), (8, 'context')]:
            data = bytearray(self.native('original'))
            data[SITES['original'][0] + delta] ^= 1
            with self.assertRaisesRegex(ValueError, message):
                apply_library_button_labels(bytes(data), 'original')

if __name__ == '__main__':
    unittest.main()
