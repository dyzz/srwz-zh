"""Byte accounting for SP members relocated after the baseline image."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from special_disc.iso_relocation import merge_spans, verify_untouched
from special_disc.writeback.build_text_candidate import verify_iso_ranges
import hashlib
import tempfile


class SpanMergeTests(unittest.TestCase):
    def test_overlapping_and_adjacent_spans_merge_in_order(self):
        spans = [(100, 200), (150, 250), (300, 300), (250, 260), (10, 20)]
        self.assertEqual(merge_spans(spans), [(10, 20), (100, 260)])

    def test_disjoint_spans_keep_their_gaps(self):
        self.assertEqual(merge_spans([(4096, 6144), (0, 2048)]), [(0, 2048), (4096, 6144)])


class UntouchedByteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root / 'base.iso'
        self.base.write_bytes(bytes(range(256)) * 64)  # 16 KiB
        final = bytearray(self.base.read_bytes())
        final[1000:1010] = b'0123456789'
        final[5000:5004] = b'ABCD'
        final += b'tail' * 600
        self.final = self.root / 'final.iso'
        self.final.write_bytes(final)
        self.spans = [(1000, 1010), (5000, 5004)]

    def test_full_candidate_hash_comes_with_the_untouched_proof(self):
        expected = hashlib.sha256(self.final.read_bytes()).hexdigest()
        untouched = verify_untouched(self.base, self.final, [(5000, 5004), (1000, 1004), (1004, 1010)])
        self.assertEqual(untouched['final_sha256'], expected)
        self.assertEqual(untouched['compared_bytes'], 16384 - 14)
        self.assertEqual(untouched['spans'], [(1000, 1010), (5000, 5004)])
        ranges = verify_iso_ranges(self.base, self.final, self.spans)
        self.assertEqual(ranges['after_sha256'], expected)
        self.assertEqual(ranges['bytes'], 16384 - 14)
        self.assertEqual(ranges['sha256'], untouched['sha256'])

    def test_changes_outside_the_spans_fail(self):
        with self.assertRaisesRegex(AssertionError, 'unowned ISO range changed'):
            verify_untouched(self.base, self.final, [(1000, 1010)])
        with self.assertRaisesRegex(ValueError, 'unowned ISO range changed'):
            verify_iso_ranges(self.base, self.final, [(5000, 5004)])


if __name__ == '__main__':
    unittest.main()
