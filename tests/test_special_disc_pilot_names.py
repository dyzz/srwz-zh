"""Pilot name writeback must stay inside the seven reviewed records."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.writeback import pilot_names as names
from srwz.codec import decode_production


class SpecialDiscPilotNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from migrate_slps_text import encoding_tables
        proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
        from special_disc.source import CURRENT_ISO
        from build_text_candidate import read_member
        from srwz.iso9660 import member_map, scan_iso9660
        base = CURRENT_ISO
        if not proposal.exists() or not base.exists():
            raise unittest.SkipTest('requires local SP component and verified font proposal')
        cls.table, cls.overrides, _, cls.readback = encoding_tables(proposal)
        cls.before = read_member(base, member_map(scan_iso9660(base)), names.MEMBER)
        cls.contract, cls.rows, cls.corpus_path = names.inputs()
        cls.output, cls.report = cls.apply(cls.before)

    @classmethod
    def apply(cls, archive):
        return names.apply_pilot_names(archive, cls.table, cls.overrides, cls.readback)

    def test_names_roundtrip_and_other_bytes_preserved(self):
        self.assertEqual(self.report['entries'], 14)
        self.assertEqual({r['translation'] for r in self.report['labels']},
                         {'伊内', '贰威', '叁洛', '四条', '伍克', '陆克斯', '柒普特'})
        original = decode_production(self.before).output
        restored = bytearray(decode_production(self.output).output)
        for slot in self.contract['entries']:
            at, size = slot['offset'], slot['capacity']
            restored[at:at + size] = original[at:at + size]
        self.assertEqual(restored, original)
        self.assertEqual(len(self.output), len(self.before))

    def test_idempotent(self):
        output, report = self.apply(self.output)
        self.assertEqual(output, self.output)
        self.assertEqual(report['changed_ids'], [])

    def test_rejects_overflow(self):
        rows = copy.deepcopy(self.rows)
        rows[self.contract['entries'][0]['id']]['translation'] = '伊内' * 12
        with patch.object(names, 'inputs', return_value=(self.contract, rows, self.corpus_path)):
            with self.assertRaisesRegex(ValueError, 'overflow'):
                self.apply(self.before)

    def test_rejects_unknown_preimage(self):
        from dataclasses import replace
        decoded = decode_production(self.before)
        data = bytearray(decoded.output)
        data[self.contract['entries'][0]['offset']] ^= 1
        with patch.object(names, 'decode_production', return_value=replace(decoded, output=bytes(data))):
            with self.assertRaisesRegex(ValueError, 'preimage drift'):
                self.apply(self.before)

    def test_rejects_redirected_fields_and_missing_coverage(self):
        for change in ('offset', 'coverage'):
            contract = copy.deepcopy(self.contract)
            if change == 'offset':
                contract['entries'][0]['offset'] += 1
            else:
                contract['entries'].pop()
            original = Path.read_text
            def read(path, *args, **kwargs):
                return json.dumps(contract) if path == names.CONTRACT else original(path, *args, **kwargs)
            with self.subTest(change=change), patch.object(Path, 'read_text', read):
                with self.assertRaisesRegex(ValueError, 'binding drift|coverage drift'):
                    names.inputs()


if __name__ == '__main__':
    unittest.main()
