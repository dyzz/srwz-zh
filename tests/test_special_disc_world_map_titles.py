"""Protect old glyphs and complete map title ownership during incremental updates."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
from special_disc.writeback import world_map_titles as titles
from special_disc.writeback.install_font import sp_offsets
from migrate_stage_dialogue import read_disc_member
from srwz.codec import decode_production


class WorldMapTitleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = read_disc_member('SLPS_259.20')
        cls.source = read_disc_member(titles.MEMBER)
        cls.config = titles.inputs()

    def test_all_ten_titles_roundtrip_with_non_title_bytes_preserved(self):
        output, report = titles.apply_world_map_titles(self.source, self.exe)
        self.assertEqual(report['count'], 10)
        offsets = sp_offsets(self.exe, self.config['table_offset'], len(self.source))
        owned = {r['chunk']:r for r in self.config['bindings']}
        for i,(a,b) in enumerate(zip(offsets, offsets[1:])):
            if i not in owned:
                self.assertEqual(output[a:b], self.source[a:b])
                continue
            before = decode_production(self.source[a:b]).output
            after = decode_production(output[a:b]).output
            at = owned[i]['offset']
            self.assertEqual(after[:at], before[:at])
            self.assertEqual(after[at+8192:], before[at+8192:])
            self.assertEqual(after[at:at+8192], owned[i]['pixels'])
        self.assertEqual(titles.apply_world_map_titles(output, self.exe)[0], output)

    def test_sparse_migration_residue_is_replaced_and_unknown_pixels_rejected(self):
        old = bytes([255])*8192
        new = bytes(8192)  # Background pixels must erase the old Japanese strokes.
        row = dict(chunk=1,offset=6,pixels=new, source_raw_sha256=titles.sha(old),
                   previous_raw_sha256=titles.sha(old), output_raw_sha256=titles.sha(new))
        self.assertEqual(titles.replace_bitmap(b'header'+old+b'trailer',row),
                         b'header'+new+b'trailer')
        with self.assertRaisesRegex(ValueError, 'preimage drift'):
            titles.replace_bitmap(b'header'+bytes([128])*8192+b'trailer',row)


if __name__ == '__main__':
    unittest.main()
