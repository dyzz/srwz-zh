"""Protect old glyphs and complete map title ownership during incremental updates."""
from pathlib import Path
import copy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
from special_disc.writeback.update_current_font import appended_assignments, verify_glyph_delta


class FontAppendTests(unittest.TestCase):
    def test_existing_mapping_and_alias_cannot_move(self):
        old = dict(assignments=[dict(character='中', code='8141', glyph_index=1)],
                   surface_alias_assignments=[], source_compatibility_assignments=[])
        new = copy.deepcopy(old)
        new['assignments'].append(dict(character='讥', code='8142', glyph_index=2))
        self.assertEqual(len(appended_assignments(old, new)), 1)
        new['assignments'][0]['glyph_index'] = 3
        with self.assertRaisesRegex(ValueError, 'moved or changed'):
            appended_assignments(old, new)
        new = copy.deepcopy(old)
        new['assignments'].append(dict(character='讥', code='8142', glyph_index=1))
        with self.assertRaisesRegex(ValueError, 'overwrites'):
            appended_assignments(old, new)

    def test_rasterizer_may_only_change_new_glyphs(self):
        old = bytes(1290240); new = bytearray(old)
        new[288] = 1
        self.assertEqual(verify_glyph_delta(old, bytes(new), [dict(glyph_index=1)]), [1])
        new[576] = 2
        with self.assertRaisesRegex(ValueError, 'previous glyph pixels changed'):
            verify_glyph_delta(old, bytes(new), [dict(glyph_index=1)])
        with self.assertRaisesRegex(ValueError, 'blank'):
            verify_glyph_delta(old, old, [dict(glyph_index=1)])


if __name__ == '__main__':
    unittest.main()
