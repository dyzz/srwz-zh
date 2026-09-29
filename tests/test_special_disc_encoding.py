"""SP writers must never reintroduce the retired menu-code overlay."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.writeback.migrate_slps_text import encoding_tables
from srwz.text import encode_text, decode_text


class SpecialDiscEncodingTests(unittest.TestCase):
    def test_all_writer_positions_use_shared_assignments_without_legacy_reads(self):
        registry = json.loads((ROOT / 'config/encoding/zh-release-font-assignments.json').read_text())
        proposal = dict(assignments=registry['primary_assignments'],
                        surface_alias_assignments=registry['surface_alias_assignments'],
                        source_compatibility_assignments=registry['source_compatibility_assignments'])
        original_read = Path.read_text

        def guarded_read(path, *args, **kwargs):
            self.assertNotEqual(path.name, 'release-menu-codebook.json')
            return original_read(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'proposal.json'
            path.write_text(json.dumps(proposal))
            with patch.object(Path, 'read_text', guarded_read):
                table, former_menu, stored, readback = encoding_tables(path)
        self.assertEqual(former_menu, stored)
        self.assertIsNot(former_menu, stored)
        for character, expected in [('尔', 0x9247), ('军', 0x90C4), ('无', 0x93F6)]:
            self.assertEqual(stored[character], expected)
            raw = encode_text(character, table, overrides=stored, terminate=True)
            self.assertEqual(decode_text(raw, 0, readback).text, character)
        # Old menu glyphs are absent from the installed font. A permissive
        # decoder must no longer falsely identify those bytes as Chinese.
        for raw, wrong in [(b'\x84\x6d\0', '尔'), (b'\x82\x7d\0', '军'), (b'\x85\x9f\0', '无')]:
            self.assertNotEqual(decode_text(raw, 0, readback).text, wrong)


if __name__ == '__main__':
    unittest.main()
