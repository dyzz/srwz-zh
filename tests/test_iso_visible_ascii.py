import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from tools.verify_full_story_iso_content import raw_visible_ascii_glyphs


class IsoVisibleAsciiTests(unittest.TestCase):
    def test_native_dimensions_are_controls_and_fullwidth_text_is_safe(self):
        # width 14, advance 12, fullwidth A/1, restore width/advance 22.
        payload = bytes.fromhex('320e340c826082503216341600')
        self.assertEqual(raw_visible_ascii_glyphs(payload), ())

    def test_tag_parameter_is_not_a_visible_ascii_character(self):
        self.assertEqual(raw_visible_ascii_glyphs(b'\x31A\x33Z\x35!\0'), ())

    def test_real_raw_ascii_after_tag_is_still_rejected(self):
        self.assertEqual(raw_visible_ascii_glyphs(b'\x32\x0eA9\0'), ((2, 'A'), (3, '9')))

    def test_runtime_tokens_keep_their_existing_exemption(self):
        self.assertEqual(raw_visible_ascii_glyphs(b'$n%s\\n\x82\x60\0'), ())

    def test_truncated_tag_fails(self):
        with self.assertRaisesRegex(ValueError, 'truncated native text tag'):
            raw_visible_ascii_glyphs(b'\x32')


if __name__ == '__main__':
    unittest.main()
