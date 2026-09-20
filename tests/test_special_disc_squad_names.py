from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback'),
               str(ROOT / 'tools/special_disc/verification')]
from scan_squad_names import discover_chunk, indexed_pointer_owners
from squad_names import load_names, patch_slots, sha, validate_slot
from srwz.text import TextTable


class SpecialDiscSquadTests(unittest.TestCase):
    def owner_fixture(self):
        data = bytearray(0x100)
        site, target = 0x30, 0x80
        data[site - 8:site - 6] = b'\xff\xff'
        data[site - 2:site] = b'\xff\xff'
        struct.pack_into('<4I', data, site, 0x8045F0 + target, 0xff, 0, 0)
        data[target:target + 3] = b'\x81\x41\0'
        return data, TextTable({0x8141: '桂'}, {})

    def test_one_character_name_requires_complete_pointer_owner(self):
        data, table = self.owner_fixture()
        groups = discover_chunk(bytes(data), table, 47, set())
        self.assertEqual([(c.offset, c.source_text, g.slot_size) for g in groups for c in g.cells],
                         [(0x80, '桂', 8)])
        data[0x30 + 8] = 1  # Damaged owner tail must not prove a short table.
        self.assertFalse(discover_chunk(bytes(data), table, 47, set()))

    def test_parser_owned_speaker_is_not_a_squad_slot(self):
        data, table = self.owner_fixture()
        self.assertFalse(discover_chunk(bytes(data), table, 47, {'桂'}, [(0x80, 0x83)]))

    def test_populated_member_pointer_records_require_adjacent_owned_records(self):
        data = bytearray(0x180)
        table = TextTable({}, {})
        for site, target, text in ((0x30, 0x100, b'Team1\0'), (0x50, 0x108, b'Team2\0')):
            struct.pack_into('<6H', data, site - 12, 1, 2, 3, 4, 5, 6)
            struct.pack_into('<4I', data, site, 0x8045F0 + target, 0x00ff0201, 0xffffffff, 0)
            data[target:target + len(text)] = text
        self.assertEqual(indexed_pointer_owners(bytes(data), table), {0x30: 0x100, 0x50: 0x108})
        data[0x50 + 12] = 1
        self.assertFalse(indexed_pointer_owners(bytes(data), table))

    def slot_fixture(self):
        data = b'HEAD' + b'AB\0' + bytes(5) + b'TAIL'
        slot = dict(offset=4, capacity=8, prefix_hex=b'HEAD'.hex(), trailer_hex=b'TAIL'.hex(),
                    source_text='AB', source_slot_sha256=sha(data[4:12]))
        return data, slot

    def test_patch_preserves_owner_metadata_and_rejects_overflow(self):
        data, slot = self.slot_fixture()
        table = TextTable({}, {})
        out = patch_slots(data, [slot], {'AB': {'translation': 'CD'}}, table, {}, table)
        self.assertEqual(out, b'HEAD' + b'CD\0' + bytes(5) + b'TAIL')
        with self.assertRaisesRegex(ValueError, 'capacity'):
            patch_slots(data, [slot], {'AB': {'translation': 'ABCDEFGHI'}}, table, {}, table)

    def test_preimage_and_owner_drift_are_rejected(self):
        data, slot = self.slot_fixture()
        with self.assertRaisesRegex(ValueError, 'source slot drift'):
            validate_slot(data[:4] + b'X' + data[5:], slot, TextTable({}, {}))
        with self.assertRaisesRegex(ValueError, 'owner metadata drift'):
            validate_slot(b'X' + data[1:], slot, TextTable({}, {}))
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            patch_slots(data, [slot, slot], {'AB': {'translation': 'CD'}}, TextTable({}, {}), {}, TextTable({}, {}))

    def test_frozen_coverage_includes_short_and_populated_tables_and_excludes_debug(self):
        inventory, entries = load_names(ROOT)
        self.assertEqual(inventory['counts'], dict(slots=1451, stage_slots=1338,
            nisv_slots=113, stage_chunks=42, unique_sources=266))
        locations = {(s['member'], s['chunk'], s['offset']) for s in inventory['slots']}
        self.assertIn(('DATA/STAGE.BIN', 47, 0x3808), locations)
        self.assertIn(('DATA/STAGE.BIN', 40, 0x3AD0), locations)
        slot = next(s for s in inventory['slots'] if (s['member'], s['chunk'], s['offset']) == ('DATA/STAGE.BIN', 40, 0x3AD0))
        self.assertEqual(slot['layout'], 'pointer8-24')
        self.assertTrue(slot['pointer_owners'])
        self.assertFalse(any(s['member'] == 'DATA/STAGE.BIN' and s['chunk'] in (0, 66, 67)
                             for s in inventory['slots']))
        self.assertEqual(entries['オレンジ']['translation'], 'Orange')
        self.assertEqual(entries['ＸＡＮ']['translation'], 'XAN')
        frame = json.loads((ROOT / 'corpus/zh/special-disc/frame-text.json').read_text())
        for row in frame['entries']:
            if row.get('kind') == 'formation_name':
                self.assertEqual(entries[row['source_text']]['translation'], row['translation'])


if __name__ == '__main__':
    unittest.main()
