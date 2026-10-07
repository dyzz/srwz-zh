"""Approved Gravion labels must update the SP baseline without moving pointers."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.writeback import gravion_labels as labels
from special_disc.writeback.migrate_slps_text import encoding_tables
from special_disc.source import CURRENT_ISO
from build_text_candidate import read_member
from srwz.codec import decode_production
from srwz.iso9660 import member_map, scan_iso9660


class GravionLabelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
        if not CURRENT_ISO.exists() or not proposal.exists():
            raise unittest.SkipTest('requires local SP image and shared font')
        cls.table, _, cls.overrides, cls.readback = encoding_tables(proposal)
        archive = read_member(CURRENT_ISO, member_map(scan_iso9660(CURRENT_ISO)), 'DATA/COMPDATA.BN')
        cls.data = decode_production(archive).output

    def test_reviewed_labels_preserve_every_unowned_byte(self):
        out, report = labels.patch_decoded(self.data, self.table, self.overrides, self.readback)
        contract, _, _ = labels.inputs()
        owned = {i for r in contract['entries'] for i in range(r['offset'], r['offset'] + r['capacity'])}
        self.assertEqual(len(report['labels']), 18)
        self.assertTrue(all(a == b for i, (a, b) in enumerate(zip(self.data, out)) if i not in owned))
        self.assertEqual(labels.patch_decoded(out, self.table, self.overrides, self.readback)[0], out)

    def test_unexpected_preimage_is_rejected(self):
        broken = bytearray(self.data)
        broken[0x80c10] ^= 1
        with self.assertRaisesRegex(ValueError, 'preimage drift'):
            labels.patch_decoded(bytes(broken), self.table, self.overrides, self.readback)

    def test_reference_drift_is_rejected(self):
        broken = bytearray(self.data)
        contract, _, _ = labels.inputs()
        at = contract['entries'][0]['reference_sites'][0]
        broken[at:at + 4] = bytes(4)
        with self.assertRaisesRegex(ValueError, 'reference drift'):
            labels.patch_decoded(bytes(broken), self.table, self.overrides, self.readback)
