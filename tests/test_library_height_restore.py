"""Safe height operand and edition-specific patch ownership contracts."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.library_body_metrics import EDITIONS, apply_library_body_metrics, write_ranges as body_ranges
from srwz.library_height_restore import NATIVE_WORDS, apply_library_height_restore, verify_library_height_restore, write_ranges
from srwz.library_typography import library_typography
from srwz.text import CONTROL_NOTATION


class LibraryHeightRestoreTests(unittest.TestCase):
    def fixture(self, edition):
        spec = EDITIONS[edition]
        ranges = write_ranges(edition)
        data = bytearray(max(b for _, b in ranges))
        h = ranges[0][0]
        data[h:h + 32] = struct.pack('<8I', *NATIVE_WORDS)
        hook = spec['hook'] - spec['delta']
        data[hook-8:hook] = bytes.fromhex('2d4080022110c200')
        struct.pack_into('<I', data, hook, 3 << 26 | spec['draw'] >> 2)
        data[hook+4:hook+8] = bytes.fromhex('000040a0')
        return bytes(data)

    def test_patch_ownership_preimages_and_composition(self):
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                native = self.fixture(edition)
                patched, _ = apply_library_height_restore(native, edition)
                allowed = {i for lo, hi in write_ranges(edition) for i in range(lo, hi)}
                changed = {i for i, (a, b) in enumerate(zip(native, patched)) if a != b}
                self.assertTrue(changed)
                self.assertLessEqual(changed, allowed)
                self.assertEqual(len(patched), len(native))
                self.assertTrue(verify_library_height_restore(patched, edition)['already_applied'])
                body_owned = {i for lo, hi in body_ranges(edition) for i in range(lo, hi)}
                self.assertFalse(allowed & body_owned)
                first = apply_library_body_metrics(patched, edition)[0]
                second = apply_library_height_restore(apply_library_body_metrics(native, edition)[0], edition)[0]
                self.assertEqual(first, second)
                for at in (write_ranges(edition)[0][0], write_ranges(edition)[1][0]):
                    bad = bytearray(native)
                    bad[at] ^= 1
                    with self.assertRaisesRegex(ValueError, 'preimage drift'):
                        apply_library_height_restore(bytes(bad), edition)

    def test_body_height_tracks_panel_and_preserves_visible_text(self):
        for domain, letter_height, digit_height, restore in (
            ('character', '0C', '0B', '0C'),
            ('robot', '0B', '8A', '8A'),
            ('glossary', '0C', '0B', '0C'),
        ):
            for tag in ('DSCR', 'DSC2'):
                with self.subTest(domain=domain, tag=tag):
                    text = '中文EFA士兵14岁Geo圣剑'
                    result = library_typography(text, tag, domain=domain)
                    self.assertIn(f'<height:{letter_height}>EFA<width:15><space:15><height:{restore}>士', result)
                    self.assertIn(f'<height:{digit_height}>14<width:15><space:15><height:{restore}>岁', result)
                    self.assertNotIn('<height:0A>', result)
                    self.assertEqual(CONTROL_NOTATION.sub('', result), text)
                    self.assertEqual(library_typography(result, tag, domain=domain), result)

    def test_previous_character_scopes_recompile_for_robot(self):
        old = library_typography('中文Geo圣剑14岁', 'DSCR', domain='character')
        corrected = library_typography(old, 'DSCR', domain='robot')
        self.assertEqual(corrected, library_typography('中文Geo圣剑14岁', 'DSCR', domain='robot'))
        self.assertIn('<height:8A>圣剑', corrected)

    def test_raw_height10_is_encoded_before_body_line_splitting(self):
        result = library_typography('<height:0A>中文14岁', 'DSCR', domain='robot')
        self.assertTrue(result.startswith('<height:8A>中文'))
        self.assertNotIn('<height:0A>', result)
        self.assertEqual(library_typography(result, 'DSCR', domain='robot'), result)
