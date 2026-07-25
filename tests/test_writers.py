import struct
import unittest

from tools.srwz.codec import decode
from tools.srwz.iso_layout import ExecutableOffsetSpec
from tools.srwz.text import TextTable
from tools.srwz.writeback import WritebackError
from tools.srwz.writers import (
    apply_summary_replacements,
    build_executable_offset_patch_plan,
    build_summary_patch_plan,
    rebuild_codec_archive,
)


def summary_fixture():
    data = bytearray(0x90)
    struct.pack_into("<I", data, 0x2C, 1)
    data[0x3C:0x40] = b"text"
    struct.pack_into("<I", data, 0x40, 0x40)
    struct.pack_into("<I", data, 0x66, 8)
    data[0x6A:0x72] = b"Hello\x00\x00\x00"
    return bytes(data)


def full_summary_fixture():
    data = bytearray(0x90)
    struct.pack_into("<I", data, 0x2C, 1)
    data[0x3C:0x40] = b"text"
    struct.pack_into("<I", data, 0x40, 0x40)
    struct.pack_into("<I", data, 0x66, 5)
    data[0x6A:0x6F] = b"Hello"
    return bytes(data)


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.table = TextTable(characters={}, tags={})

    def test_summary_writer_is_fixed_allocation_and_reparses(self):
        source = summary_fixture()
        replacements = {"summary/00/000": "Hi"}
        plan = build_summary_patch_plan(
            source,
            self.table,
            chunk_index=0,
            replacements=replacements,
        )
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].offset, 0x6A)
        self.assertEqual(len(plan.operations[0].after), 8)
        output = apply_summary_replacements(
            source,
            self.table,
            chunk_index=0,
            replacements=replacements,
        )
        self.assertEqual(output[0x6A:0x72], b"Hi\x00\x00\x00\x00\x00\x00")

    def test_summary_writer_fails_on_overflow_and_unknown_id(self):
        source = summary_fixture()
        with self.assertRaisesRegex(WritebackError, "overflow"):
            build_summary_patch_plan(
                source,
                self.table,
                chunk_index=0,
                replacements={"summary/00/000": "too long"},
            )
        with self.assertRaisesRegex(WritebackError, "unknown summary"):
            build_summary_patch_plan(
                source,
                self.table,
                chunk_index=0,
                replacements={"summary/00/999": "x"},
            )

    def test_summary_writer_preserves_full_allocation_terminator_contract(self):
        source = full_summary_fixture()
        identity = build_summary_patch_plan(
            source,
            self.table,
            chunk_index=0,
            replacements={"summary/00/000": "Hello"},
        )
        self.assertEqual(identity.apply(source), source)
        shorter = apply_summary_replacements(
            source,
            self.table,
            chunk_index=0,
            replacements={"summary/00/000": "Hi"},
        )
        self.assertEqual(shorter[0x6A:0x6F], b"Hi\x00\x00\x00")

    def test_archive_rebuild_round_trips_and_aligns_every_chunk(self):
        sources = (b"abcabcabc", bytes(range(64)))
        rebuilt = rebuild_codec_archive(sources)
        self.assertEqual(rebuilt.chunk_count, 2)
        self.assertEqual(rebuilt.offsets[0], 0)
        self.assertTrue(all(offset % 16 == 0 for offset in rebuilt.offsets))
        for index, expected in enumerate(sources):
            result = decode(
                rebuilt.data[
                    rebuilt.offsets[index]:rebuilt.offsets[index + 1]
                ]
            )
            self.assertEqual(result.output, expected)

    def test_slps_offset_patch_writes_starts_not_terminal_size(self):
        executable = bytearray(32)
        struct.pack_into("<II", executable, 8, 0, 16)
        spec = ExecutableOffsetSpec(
            name="fixture",
            member="fixture.bin",
            table_start=8,
            table_end=15,
        )
        plan = build_executable_offset_patch_plan(
            bytes(executable),
            spec,
            (0, 32, 80),
        )
        output = plan.apply(bytes(executable))
        self.assertEqual(struct.unpack_from("<II", output, 8), (0, 32))
        self.assertEqual(output[:8], bytes(8))
        self.assertEqual(output[16:], bytes(16))

    def test_slps_offset_patch_preserves_table_with_terminal_size(self):
        executable = bytearray(32)
        struct.pack_into("<III", executable, 8, 0, 16, 32)
        spec = ExecutableOffsetSpec(
            name="fixture",
            member="fixture.bin",
            table_start=8,
            table_end=19,
        )
        plan = build_executable_offset_patch_plan(
            bytes(executable),
            spec,
            (0, 48, 96),
        )
        output = plan.apply(bytes(executable))
        self.assertEqual(
            struct.unpack_from("<III", output, 8),
            (0, 48, 96),
        )


if __name__ == "__main__":
    unittest.main()
