import struct
import unittest

from tools.srwz.image_export import (
    ImageExportError,
    parse_seg_offsets,
    safe_member_parts,
    standalone_picture_tim2,
)
from tools.srwz.tim2 import parse_tim2


def make_two_picture_tim2_with_shared_palette(palette_banks=1):
    image_size = 32
    palette = bytes(range(64)) * palette_banks
    first_header = struct.pack(
        "<IIIHHBBBBHHQQII",
        48 + image_size + len(palette),
        len(palette),
        image_size,
        48,
        16 * palette_banks,
        0,
        1,
        3,
        4,
        8,
        8,
        0,
        0,
        0,
        0,
    )
    second_header = struct.pack(
        "<IIIHHBBBBHHQQII",
        48 + image_size,
        0,
        image_size,
        48,
        0,
        0,
        1,
        3,
        4,
        8,
        8,
        0,
        0,
        0,
        0,
    )
    file_header = struct.pack("<4sBBH8x", b"TIM2", 4, 0, 2)
    return (
        file_header
        + first_header
        + bytes([0x12]) * image_size
        + palette
        + second_header
        + bytes([0x34]) * image_size
    )


class ImageExportTests(unittest.TestCase):
    def test_parses_seg_offsets_with_zero_padding(self):
        data = struct.pack("<6I", 0, 16, 48, 100, 0, 0)

        self.assertEqual(parse_seg_offsets(data, 100), (0, 16, 48, 100))

    def test_rejects_seg_without_exact_archive_end(self):
        data = struct.pack("<3I", 0, 16, 48)

        with self.assertRaisesRegex(ImageExportError, "archive size"):
            parse_seg_offsets(data, 100)

    def test_rejects_nonzero_seg_padding(self):
        data = struct.pack("<5I", 0, 16, 100, 4, 0)

        with self.assertRaisesRegex(ImageExportError, "nonzero"):
            parse_seg_offsets(data, 100)

    def test_rejects_non_increasing_seg_offsets(self):
        data = struct.pack("<4I", 0, 16, 16, 100)

        with self.assertRaisesRegex(ImageExportError, "strictly increasing"):
            parse_seg_offsets(data, 100)

    def test_accepts_safe_iso_member_path(self):
        self.assertEqual(
            safe_member_parts("BTL/TWP.BIN"),
            ("BTL", "TWP.BIN"),
        )

    def test_rejects_unsafe_iso_member_path(self):
        with self.assertRaisesRegex(ImageExportError, "unsafe"):
            safe_member_parts("../TWP.BIN")

    def test_extracts_first_picture_as_standalone_tim2(self):
        source = make_two_picture_tim2_with_shared_palette()
        record = parse_tim2(source)

        view = standalone_picture_tim2(
            source,
            record,
            0,
        )

        parsed = parse_tim2(view.data)
        self.assertEqual(len(parsed.pictures), 1)
        self.assertEqual(parsed.pictures[0].clut_color_count, 16)
        self.assertEqual(view.palette_source_picture_index, 0)
        self.assertEqual(view.palette_bank_index, 0)
        self.assertEqual(view.palette_bank_count, 1)
        self.assertEqual(source, make_two_picture_tim2_with_shared_palette())

    def test_materializes_shared_palette_for_later_picture(self):
        source = make_two_picture_tim2_with_shared_palette()
        record = parse_tim2(source)

        view = standalone_picture_tim2(
            source,
            record,
            1,
        )

        parsed = parse_tim2(view.data)
        picture = parsed.pictures[0]
        self.assertEqual(view.palette_source_picture_index, 0)
        self.assertEqual(view.palette_bank_index, 0)
        self.assertEqual(view.palette_bank_count, 1)
        self.assertEqual(picture.clut_color_count, 16)
        self.assertEqual(picture.clut_size, 64)
        self.assertFalse(picture.uses_shared_clut)
        self.assertEqual(view.data[-64:], bytes(range(64)))

    def test_selects_one_4bpp_palette_bank(self):
        source = bytearray(
            make_two_picture_tim2_with_shared_palette(palette_banks=2)
        )
        record = parse_tim2(source)
        first = record.pictures[0]
        palette_start = first.offset + first.header_size + first.image_size
        source[palette_start + 64 : palette_start + 128] = bytes(
            range(64, 128)
        )

        view = standalone_picture_tim2(
            source,
            record,
            0,
            palette_bank_index=1,
        )

        parsed = parse_tim2(view.data)
        self.assertEqual(view.palette_bank_count, 2)
        self.assertEqual(view.palette_bank_index, 1)
        self.assertEqual(parsed.pictures[0].clut_color_count, 16)
        self.assertEqual(view.data[-64:], bytes(range(64, 128)))

    def test_rejects_out_of_range_picture(self):
        source = make_two_picture_tim2_with_shared_palette()
        record = parse_tim2(source)

        with self.assertRaisesRegex(ImageExportError, "outside"):
            standalone_picture_tim2(source, record, 2)


if __name__ == "__main__":
    unittest.main()
