import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.summary_layout_capacity import (fixed_field_size, load_production_summary_capacity,
                                         preflight_summary_fields, layout_summary_group)
from srwz.writeback import WritebackError


class SummaryLayoutCapacityTests(unittest.TestCase):
    def test_reported_44_byte_regression_does_not_fit_38_byte_field(self):
        entry = SimpleNamespace(entry_id='summary/09/000', allocated_length=38, terminator='none')
        with self.assertRaisesRegex(WritebackError, 'summary/09/000: needs 44 bytes, fixed capacity 38'):
            fixed_field_size(entry, b'\x81\x40'*22)
        self.assertEqual(fixed_field_size(entry, b'\x81\x40'*19), 38)

    def test_neighbouring_capacity_cannot_cover_an_overflow(self):
        left = SimpleNamespace(entry_id='summary/10/000', allocated_length=38, terminator='none')
        right = SimpleNamespace(entry_id='summary/10/001', allocated_length=100, terminator='none')
        self.assertEqual(fixed_field_size(right, b'\x81\x40'*2), 4)
        with self.assertRaises(WritebackError):
            fixed_field_size(left, b'\x81\x40'*22)

    def test_nul_owner_reserves_one_byte_for_terminator(self):
        entry = SimpleNamespace(entry_id='summary/00/000', allocated_length=38, terminator='nul')
        self.assertEqual(fixed_field_size(entry, bytes(37)), 38)
        with self.assertRaises(WritebackError):
            fixed_field_size(entry, bytes(38))


class NativeSummaryCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        if not (cls.root/'rom/original.iso').is_file():
            raise unittest.SkipTest('native source ISO not installed')
        cls.context = load_production_summary_capacity(cls.root)

    def test_real_native_field_rejects_the_rebalanced_44_byte_string(self):
        self.assertEqual(self.context['entries']['summary/09/000'].allocated_length, 38)
        with self.assertRaisesRegex(WritebackError, 'needs 44 bytes, fixed capacity 38'):
            preflight_summary_fields({'summary/09/000':
                '　民众积压的焦虑彻底爆发，最终演变为暴动；相'}, self.context)

    def test_all_current_world_history_fields_pass_production_fixed_writer(self):
        import json
        data = json.loads((self.root/'corpus/zh/summary.json').read_text())
        sizes = preflight_summary_fields({r['id']:r['translation']for r in data['entries']}, self.context)
        self.assertEqual(len(sizes), 28)
        self.assertTrue(all(r['encodedBytes']<=r['capacityBytes']for r in sizes))

    def test_real_group_is_reflowed_within_all_three_native_allocations(self):
        # Retain the original overflow-regression wording independently of
        # subsequent editorial changes to the production corpus.
        texts = {'summary/09/000':'　民众积压的焦虑彻底爆发，最终演变为',
                 'summary/09/001':'暴动；相关消息又裹挟着不负责任的谣言，',
                 'summary/09/002':'在UN上四处传播，进一步煽动着人们的不安。'}
        result = layout_summary_group(texts, self.context)
        self.assertEqual(''.join(f['text']for f in result['fields']), ''.join(texts.values()))
        self.assertEqual([f['encodedBytes']for f in result['fields']], [38,38,40])
        self.assertEqual(result['widthSelection']['spreadPx'], 0)
