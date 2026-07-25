import struct
import unittest

from tools.srwz.iso_layout import (
    ExecutableOffsetSpec,
    IsoLayoutError,
    read_executable_archive_offsets,
)


class ExecutableArchiveOffsetTests(unittest.TestCase):
    def test_reads_non_aligned_end_and_appends_archive_size(self):
        executable = bytearray(32)
        struct.pack_into("<III", executable, 4, 0, 10, 20)
        spec = ExecutableOffsetSpec("TEST", "DATA/TEST.BIN", 4, 15)
        self.assertEqual(
            read_executable_archive_offsets(bytes(executable), spec, 30),
            (0, 10, 20, 30),
        )

    def test_rejects_non_monotonic_offsets(self):
        executable = bytearray(16)
        struct.pack_into("<II", executable, 4, 0, 0)
        spec = ExecutableOffsetSpec("TEST", "DATA/TEST.BIN", 4, 12)
        with self.assertRaisesRegex(IsoLayoutError, "strictly increasing"):
            read_executable_archive_offsets(bytes(executable), spec, 30)


if __name__ == "__main__":
    unittest.main()
