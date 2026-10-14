"""Protect the native effect loader's next-offset length contract."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from special_disc.event_gallery.subtitles import _pack_records, records


class EventRecordPackingTests(unittest.TestCase):
    def test_native_lengths_include_a_bounded_last_record(self):
        for count in (7, 8):
            with self.subTest(record_count=count):
                # The real Sigma header's large first word used to become a
                # bogus end offset when the sentinel was missing.
                source = [struct.pack('<4I', 0x01f80063, 0, 0, 0)]
                source += [bytes([i]) * (16 * i) for i in range(1, count)]
                packed = _pack_records(source)
                n, base = struct.unpack_from('<II', packed)
                self.assertEqual(n, count)
                self.assertGreaterEqual(base, 8 + (count + 1) * 8)
                self.assertEqual(records(packed), source)
                for i, record in enumerate(source):
                    start = struct.unpack_from('<I', packed, 8 + i * 8)[0]
                    end = struct.unpack_from('<I', packed, 8 + (i + 1) * 8)[0]
                    self.assertEqual(end - start, len(record))
                    self.assertLessEqual(base + end, len(packed))
                self.assertEqual(struct.unpack_from('<II', packed, 8 + n * 8),
                                 (len(packed) - base, 0))

    def test_non_aligned_records_preserve_logical_size_and_native_padding(self):
        source = [b'header', b'audio']
        packed = _pack_records(source)
        self.assertEqual(records(packed), source)
        base = struct.unpack_from('<I', packed, 4)[0]
        for i in range(len(source)):
            start = struct.unpack_from('<I', packed, 8 + i * 8)[0]
            end = struct.unpack_from('<I', packed, 8 + (i + 1) * 8)[0]
            self.assertEqual(end - start, 16)
            self.assertEqual(packed[base + start + len(source[i]):base + end],
                             bytes(16 - len(source[i])))


if __name__ == '__main__':
    unittest.main()
