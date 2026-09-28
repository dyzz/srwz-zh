import unittest

from tools.srwz.runtime_keywords import (
    AllocationReference, EmbeddedAllocation, EmbeddedRecord,
    RuntimeKeywordError, _stage_relocation_plan,
)


class RuntimeKeywordRelocationTests(unittest.TestCase):
    def inventory(self, *, donor_capacity=64, extra_pointer=None):
        source = EmbeddedAllocation(2, 0x20, 8, bytes(8), b'keyword body\0',
                                    (AllocationReference(25, 'WORD', 0x100),))
        donor = EmbeddedAllocation(2, 0x40, donor_capacity, bytes(donor_capacity),
                                   b'updated text\0',
                                   (AllocationReference(25, 'DSCR', 0x100),))
        fields = (0x20, 0x30, 0x40, extra_pointer or 0x90)
        records = [EmbeddedRecord(2, 0x100, 25, fields)]
        row = dict(stage_index=2, keyword_index=25, tag='WORD',
                   source_offset=0x20, donor_offset=0x40,
                   relocation_offset=0x4E, reason='fixed_allocation_overflow')
        return row, [source, donor], records

    def test_changed_donor_requires_updated_exact_position(self):
        row, allocations, records = self.inventory()
        stale = dict(row, relocation_offset=0x48)
        with self.assertRaisesRegex(RuntimeKeywordError, 'contract drift'):
            _stage_relocation_plan([stale], allocations, records, runtime_base=0x7566F0)
        plan, report = _stage_relocation_plan([row], allocations, records,
                                              runtime_base=0x7566F0)
        self.assertEqual(plan[(2, 0x20)][0], 0x4E)
        self.assertEqual(plan[(2, 0x20)][1], b'keyword body\0')
        self.assertTrue(report[0]['source_allocation_preserved'])

    def test_updated_position_must_fit_owned_donor(self):
        row, allocations, records = self.inventory(donor_capacity=24)
        with self.assertRaisesRegex(RuntimeKeywordError, 'contract drift'):
            _stage_relocation_plan([row], allocations, records, runtime_base=0x7566F0)

    def test_existing_pointer_target_cannot_be_reclaimed(self):
        row, allocations, records = self.inventory(extra_pointer=0x4E)
        with self.assertRaisesRegex(RuntimeKeywordError, 'contract drift'):
            _stage_relocation_plan([row], allocations, records, runtime_base=0x7566F0)


if __name__ == '__main__':
    unittest.main()
