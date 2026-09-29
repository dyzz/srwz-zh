"""Local-disc integration checks for terrain coverage and archive preservation."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.writeback.terrain_names import apply_terrain_names, inputs, verify_terrain_names, MEMBER
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import decode_text, project_runtime_text_table


class SpecialDiscTerrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from special_disc.source import SOURCE_ISO
        cls.component = ROOT / 'work/build/special-disc/full-text/image-labels' / MEMBER
        proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
        if not all(p.exists() for p in (SOURCE_ISO, cls.component, proposal)):
            raise unittest.SkipTest('requires local SP disc and font/image components')
        from migrate_stage_dialogue import read_disc_member
        from migrate_slps_text import encoding_tables
        cls.table, _, cls.overrides, cls.readback = encoding_tables(proposal)
        cls.source = read_disc_member(MEMBER)
        cls.exe = read_disc_member('SLPS_259.20')
        cls.before = cls.component.read_bytes()
        cls.output, cls.report = cls.apply(cls.before)

    @classmethod
    def apply(cls, archive):
        return apply_terrain_names(archive, cls.exe, cls.source, cls.table, cls.overrides, cls.readback)

    def test_complete_coverage_and_reported_military_facilities(self):
        self.assertEqual(verify_terrain_names(self.output, self.exe, self.readback, self.table, self.overrides),
                         {'occurrence_count': 621, 'member_count': 200})
        _, offsets, _, _ = inputs(self.exe, self.output)
        data = decode_production(self.output[offsets[76]:offsets[77]]).output
        for at in (2056, 2084):
            self.assertEqual(decode_text(data, at, self.readback).text, '军事设施')

    def test_only_locked_text_spans_change_and_titles_survive(self):
        self.assertEqual(len(self.output), len(self.before))
        _, offsets, _, grouped = inputs(self.exe, self.output)
        for index in range(len(offsets) - 1):
            a, b = offsets[index:index + 2]
            if index not in self.report['changed_members']:
                self.assertEqual(self.output[a:b], self.before[a:b])
                continue
            old = decode_production(self.before[a:b]).output
            new = bytearray(decode_production(self.output[a:b]).output)
            for row in grouped[index]:
                at, size = row['decoded_offset'], row['source_consumed']
                new[at:at + size] = old[at:at + size]
            self.assertEqual(new, old, f'non-text bytes changed in {index}')

    def test_idempotent(self):
        output, report = self.apply(self.output)
        self.assertEqual(output, self.output)
        self.assertEqual(report['changed_members'], [])

    def test_migrates_old_slots_even_if_legacy_decoder_claims_correct_text(self):
        legacy = json.loads((ROOT / 'config/encoding/release-menu-codebook.json').read_text())
        codes = dict(self.overrides)
        codes.update({r['character']: int(r['code'], 16) for r in legacy['assignments']})
        permissive = project_runtime_text_table(self.readback, codes)
        contract, offsets, _, grouped = inputs(self.exe, self.output)
        # Reproduce one real retired slot without rebuilding 200 source maps.
        a, b = offsets[76:78]
        decoded = decode_production(self.output[a:b])
        data = bytearray(decoded.output)
        data[2056:2065] = bytes.fromhex(contract['accepted_previous_hex']['军事设施'])
        packed = reencode_changed_suffix(self.output[a:b], bytes(data), strategy='rust-fit',
                                         max_output_size=b-a, original_result=decoded)
        old = self.output[:a] + packed.ljust(b-a, b'\0') + self.output[b:]
        with self.assertRaisesRegex(ValueError, 'canonical encoding drift'):
            verify_terrain_names(old, self.exe, permissive, self.table, self.overrides)
        fixed, report = apply_terrain_names(old, self.exe, self.source, self.table, self.overrides, permissive)
        self.assertTrue(report['changed_members'])
        # Compression may depend on the preimage; compare every decoded member.
        for index in grouped:
            a, b = offsets[index:index + 2]
            self.assertEqual(decode_production(fixed[a:b]).output,
                             decode_production(self.output[a:b]).output)

    def test_rejects_unpatched_output_and_offset_drift(self):
        with self.assertRaises(ValueError):
            verify_terrain_names(self.before, self.exe, self.readback, self.table, self.overrides)
        exe = bytearray(self.exe)
        exe[0x3542F0] ^= 1
        with self.assertRaises(ValueError):
            verify_terrain_names(self.output, exe, self.readback, self.table, self.overrides)


if __name__ == '__main__':
    unittest.main()
