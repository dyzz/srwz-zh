from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.writeback.weapon_detail_labels import (
    apply_weapon_detail_labels, inputs, verify_weapon_detail_labels,
)
from srwz.text import load_text_table, project_runtime_text_table


class SpecialDiscWeaponDetailTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract, _ = inputs()
        cls.table = load_text_table(ROOT / 'vendor/upstream-python/project/tbl_all.json')
        codebook = json.loads((ROOT / 'config/encoding/release-menu-codebook.json').read_text())
        assignments = json.loads((ROOT / 'config/encoding/zh-release-font-assignments.json').read_text())
        cls.overrides = {r['character']: int(r['code'], 16)
                         for key in ('primary_assignments', 'surface_alias_assignments')
                         for r in assignments[key]}
        cls.overrides.update({r['character']: int(r['code'], 16) for r in codebook['assignments']})
        cls.readback = project_runtime_text_table(cls.table, cls.overrides)
        for key in ('primary_assignments', 'surface_alias_assignments'):
            cls.readback = project_runtime_text_table(cls.readback,
                {r['character']: int(r['code'], 16) for r in assignments[key]})
        data = bytearray(0x2BBD00)
        for site in cls.contract['runtime_weapon_category_labels']['sites']:
            at = int(site['file_offset'], 0)
            block = bytes.fromhex(site['original_block_hex'])
            data[at:at+len(block)] = block
        for context in cls.contract['effect_contexts']:
            at = int(context['file_offset'], 0)
            block = bytes.fromhex(context['original_hex'])
            data[at:at+len(block)] = block
        cls.source = bytes(data)

    def apply(self, source):
        return apply_weapon_detail_labels(source, self.table, self.overrides, self.readback)

    def test_labels_idempotency_and_sp_operands(self):
        output, report = self.apply(self.source)
        self.assertEqual(report['labels'], dict(melee='格斗武器（　　）', ranged='射击武器（　　）',
                                              **{'ignore-size-correction': '无视体型修正',
                                                 'barrier-pierce': '屏障贯通'}))
        self.assertEqual(report['changed_byte_count'], 26)
        self.assertEqual(len(output), len(self.source))
        self.assertEqual(output[0x2BB1A8:0x2BB1AC], bytes.fromhex('d8010224'))
        # Every byte outside the 14 approved instruction immediates is protected.
        offsets = [0x2BB158, 0x2BB1B0] + [int(x, 16) for x in report['effects']['instruction_offsets']]
        restored = bytearray(output)
        for at in offsets:
            self.assertEqual(output[at+2:at+4], self.source[at+2:at+4])
            restored[at:at+2] = self.source[at:at+2]
        self.assertEqual(bytes(restored), self.source)
        again, second = self.apply(output)
        self.assertEqual(again, output)
        self.assertEqual(second['changed_byte_count'], 0)

    def test_rejects_icon_store_branch_and_builder_drift(self):
        for at in (0x2BB1A8, 0x2BBC24, 0x2BBC60, 0x2BBC7E):
            with self.subTest(offset=hex(at)):
                damaged = bytearray(self.source)
                damaged[at] ^= 1
                with self.assertRaises(ValueError):
                    self.apply(bytes(damaged))

    def test_iso_verifier_rejects_unpatched_and_damaged_output(self):
        with self.assertRaises(ValueError):
            verify_weapon_detail_labels(self.source, self.readback)
        output, _ = self.apply(self.source)
        for at in (0x2BB159, 0x2BBC60, 0x2BBC7C, 0x2BBC96):
            with self.subTest(offset=hex(at)):
                damaged = bytearray(output)
                damaged[at] ^= 1
                with self.assertRaises(ValueError):
                    verify_weapon_detail_labels(bytes(damaged), self.readback)


if __name__ == '__main__':
    unittest.main()
