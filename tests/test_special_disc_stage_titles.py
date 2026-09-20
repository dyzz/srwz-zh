"""SP title ownership, branch binding and fixed-slot writeback regressions."""
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
from special_disc.writeback import stage_titles as titles
from migrate_stage_dialogue import read_disc_member
from srwz.codec import decode_production


class StageTitleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = read_disc_member('SLPS_259.20')
        cls.source = read_disc_member(titles.MEMBER)
        cls.cd = decode_production(read_disc_member('DATA/COMPDATA.BN')).output
        cls.snapshot = json.loads(titles.SNAPSHOT.read_text())

    def test_all_titles_roundtrip_without_moving_or_touching_other_data(self):
        output, report = titles.apply_stage_titles(self.source, self.exe)
        self.assertEqual(report['count'], 21)
        self.assertEqual(report['rewritten'], 20)
        self.assertEqual(len(output), len(self.source))
        snapshot, offsets, a, b = titles.inputs(self.exe)
        self.assertEqual(output[:a+offsets[6]], self.source[:a+offsets[6]])
        self.assertEqual(output[b:], self.source[b:])
        english = snapshot['titles'][14]['table_index']
        lo, hi = a+offsets[english], a+offsets[english+1]
        self.assertEqual(output[lo:hi], self.source[lo:hi])
        self.assertEqual(titles.verify_stage_titles(output, self.exe)['count'], 21)
        with self.assertRaisesRegex(ValueError, 'source group drift'):
            titles.apply_stage_titles(output, self.exe)

    def test_translated_title_pointer_allowed_but_selector_drift_rejected(self):
        data = bytearray(self.cd)
        struct.pack_into('<I', data, titles.RECORD_START, 0x765000)
        titles.verify_title_bindings(data)
        struct.pack_into('<H', data, titles.RECORD_START+28, 2)
        with self.assertRaisesRegex(ValueError, 'selector/branch binding drift'):
            titles.verify_title_bindings(data)

    def test_branch_aliases_are_bound_and_covered(self):
        by_selector = {t['selector']:t for t in self.snapshot['titles']}
        self.assertEqual(by_selector[6]['stage_chunks'], [7,8])
        self.assertEqual(by_selector[18]['stage_chunks'], [24,25])
        self.assertEqual(by_selector[19]['stage_chunks'], [26,27])
        self.assertEqual(sum(len(t['stage_chunks']) for t in by_selector.values()), 24)
        titles.verify_title_bindings(self.cd)

    def test_translation_change_requires_refreeze(self):
        rows = titles.title_entries()
        rows['episode-title/000']['translation'] = '未冻结的新话名'
        with patch.object(titles, 'title_entries', return_value=rows):
            with self.assertRaisesRegex(ValueError, 'translation/binding drift'):
                titles.inputs(self.exe)

    def test_loader_table_drift_rejected(self):
        exe = bytearray(self.exe)
        exe[titles.TITLE_TABLE+24] ^= 16
        with self.assertRaisesRegex(ValueError, 'placement drift'):
            titles.inputs(exe)


if __name__ == '__main__':
    unittest.main()
