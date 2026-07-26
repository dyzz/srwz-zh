import struct
import unittest

from tools.srwz.tim2 import (
    Tim2Error,
    extract_tim2_record,
    parse_tim2,
    scan_tim2,
)


def make_tim2(
    *,
    width=8,
    height=8,
    image_type=4,
    image_size=32,
    clut_color_count=16,
    clut_type=3,
    clut_size=64,
):
    header_size = 48
    picture = struct.pack(
        "<IIIHHBBBBHHQQII",
        header_size + image_size + clut_size,
        clut_size,
        image_size,
        header_size,
        clut_color_count,
        0,
        1,
        clut_type,
        image_type,
        width,
        height,
        0,
        0,
        0,
        0,
    )
    file_header = struct.pack("<4sBBH8x", b"TIM2", 4, 0, 1)
    return file_header + picture + bytes(image_size + clut_size)


def make_two_picture_tim2_with_shared_palette():
    first = make_tim2()
    first_picture = first[16:]
    second_header = struct.pack(
        "<IIIHHBBBBHHQQII",
        48 + 32,
        0,
        32,
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
    return file_header + first_picture + second_header + bytes(32)


class Tim2Tests(unittest.TestCase):
    def test_parses_indexed_picture_metadata(self):
        data = make_tim2()

        record = parse_tim2(data)

        self.assertEqual(record.size, len(data))
        self.assertEqual(len(record.pictures), 1)
        picture = record.pictures[0]
        self.assertEqual((picture.width, picture.height), (8, 8))
        self.assertEqual(picture.bits_per_pixel, 4)
        self.assertEqual(picture.clut_bits_per_color, 32)

    def test_scans_embedded_record_and_rejects_false_magic(self):
        false_candidate = b"TIM2" + bytes(20)
        valid = make_tim2(width=16, height=4)
        data = b"prefix" + false_candidate + b"gap" + valid + b"tail"

        records = scan_tim2(data)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].offset, len(b"prefix" + false_candidate + b"gap"))
        self.assertEqual(records[0].pictures[0].width, 16)

    def test_rejects_disagreeing_size_fields(self):
        data = bytearray(make_tim2())
        struct.pack_into("<I", data, 16, 999)

        with self.assertRaisesRegex(Tim2Error, "size fields disagree"):
            parse_tim2(data)

    def test_rejects_zero_dimensions(self):
        data = make_tim2(width=0)

        with self.assertRaisesRegex(Tim2Error, "invalid 0x8 dimensions"):
            parse_tim2(data)

    def test_rejects_indexed_picture_without_palette(self):
        data = make_tim2(clut_color_count=0, clut_size=0)

        with self.assertRaisesRegex(Tim2Error, "no indexed palette"):
            parse_tim2(data)

    def test_accepts_later_picture_sharing_compatible_palette(self):
        record = parse_tim2(make_two_picture_tim2_with_shared_palette())

        self.assertEqual(len(record.pictures), 2)
        self.assertFalse(record.pictures[0].uses_shared_clut)
        self.assertTrue(record.pictures[1].uses_shared_clut)

    def test_extracts_exact_embedded_record_bytes(self):
        tim2 = make_tim2()
        record, stored = extract_tim2_record(b"prefix" + tim2 + b"tail", 0)

        self.assertEqual(record.offset, 6)
        self.assertEqual(stored, tim2)

    def test_rejects_out_of_range_record_index(self):
        with self.assertRaisesRegex(Tim2Error, "outside 0..0"):
            extract_tim2_record(make_tim2(), 1)


if __name__ == "__main__":
    unittest.main()
