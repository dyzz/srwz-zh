import struct
import unittest

from tools.srwz.tim2_writeback import (
    CANARY_HEIGHT,
    CANARY_WIDTH,
    Tim2WritebackError,
    VT1_TITLE_CLUT_COLOR_COUNT,
    VT1_TITLE_CLUT_SIZE,
    VT1_TITLE_HEIGHT,
    VT1_TITLE_IMAGE_SIZE,
    VT1_TITLE_PICTURE_COUNT,
    VT1_TITLE_WIDTH,
    extract_vt1_title_indexes,
    inject_indexed4_rgba,
    inject_vt1_title_indexes,
    render_vt1_title_rgba,
    replace_vt1_title_index,
    swizzle_psmt8,
    unswizzle_psmt8,
)


PIXEL_COUNT = CANARY_WIDTH * CANARY_HEIGHT


def make_canary_tim2(
    *,
    width=CANARY_WIDTH,
    height=CANARY_HEIGHT,
    image_type=4,
    image_data=None,
    clut_type=1,
    clut_color_count=256,
    clut_size=512,
    mipmap_count=1,
):
    if image_data is None:
        image_data = bytes([0x21]) * (PIXEL_COUNT // 2)
    header_size = 48
    picture = struct.pack(
        "<IIIHHBBBBHHQQII",
        header_size + len(image_data) + clut_size,
        clut_size,
        len(image_data),
        header_size,
        clut_color_count,
        0,
        mipmap_count,
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
    return file_header + picture + image_data + bytes(clut_size)


def rgba_for_indexes(indexes, overrides=None):
    overrides = overrides or {}
    colors = {
        index: bytes((index * 10, index * 7, index * 3, 255))
        for index in range(16)
    }
    colors.update(overrides)
    return b"".join(colors[index] for index in indexes)


def alternating_indexes():
    return bytes((1, 2)) * (PIXEL_COUNT // 2)


def make_vt1_title_tim2(
    *,
    picture_count=VT1_TITLE_PICTURE_COUNT,
    width=VT1_TITLE_WIDTH,
    first_image=None,
    first_clut=None,
):
    if first_image is None:
        first_image = (
            bytes([63]) * 3
            + bytes([97])
            + bytes(VT1_TITLE_IMAGE_SIZE - 4)
        )
    file_header = struct.pack(
        "<4sBBH8x",
        b"TIM2",
        4,
        0,
        picture_count,
    )
    if first_clut is None:
        first_clut = bytes(VT1_TITLE_CLUT_SIZE)
    if len(first_clut) != VT1_TITLE_CLUT_SIZE:
        raise ValueError("first CLUT size mismatch")
    pictures = []
    for picture_index in range(picture_count):
        image = (
            first_image
            if picture_index == 0
            else bytes(VT1_TITLE_IMAGE_SIZE)
        )
        clut_size = VT1_TITLE_CLUT_SIZE if picture_index == 0 else 0
        clut_color_count = (
            VT1_TITLE_CLUT_COLOR_COUNT if picture_index == 0 else 0
        )
        header = struct.pack(
            "<IIIHHBBBBHHQQII",
            48 + len(image) + clut_size,
            clut_size,
            len(image),
            48,
            clut_color_count,
            0,
            1,
            3,
            5,
            width,
            VT1_TITLE_HEIGHT,
            0x225320000,
            0x260,
            0,
            0,
        )
        clut = first_clut if picture_index == 0 else b""
        pictures.append(header + image + clut)
    return file_header + b"".join(pictures)


class Tim2WritebackTests(unittest.TestCase):
    def test_noop_is_byte_identical(self):
        source = make_canary_tim2()
        indexes = alternating_indexes()
        original = rgba_for_indexes(indexes)

        result = inject_indexed4_rgba(source, original, original)

        self.assertEqual(result.data, source)
        self.assertEqual(result.changed_pixel_count, 0)
        self.assertEqual(result.changed_image_byte_count, 0)
        self.assertEqual(result.changed_image_byte_ranges, ())

    def test_replaces_low_and_high_nibbles_only(self):
        source = make_canary_tim2()
        indexes = alternating_indexes()
        original = rgba_for_indexes(indexes)
        edited_indexes = bytearray(indexes)
        edited_indexes[0] = 2
        edited_indexes[1] = 1
        edited = rgba_for_indexes(edited_indexes)

        result = inject_indexed4_rgba(source, original, edited)

        self.assertEqual(result.data[64], 0x12)
        self.assertEqual(result.data[65:], source[65:])
        self.assertEqual(result.changed_pixel_count, 2)
        self.assertEqual(result.changed_image_byte_count, 1)
        self.assertEqual(result.changed_image_byte_ranges, ((0, 1),))

    def test_rejects_color_not_present_in_source_picture(self):
        source = make_canary_tim2()
        indexes = alternating_indexes()
        original = rgba_for_indexes(indexes)
        edited = bytearray(original)
        edited[:4] = b"\xAA\xBB\xCC\xDD"

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "not present in the source picture",
        ):
            inject_indexed4_rgba(source, original, bytes(edited))

    def test_rejects_wrong_rgba_size(self):
        source = make_canary_tim2()
        pixels = rgba_for_indexes(alternating_indexes())

        with self.assertRaisesRegex(Tim2WritebackError, "original RGBA"):
            inject_indexed4_rgba(source, pixels[:-4], pixels)

    def test_rejects_inconsistent_rendered_index_color(self):
        source = make_canary_tim2()
        indexes = alternating_indexes()
        original = bytearray(rgba_for_indexes(indexes))
        original[8:12] = b"\x01\x02\x03\x04"

        with self.assertRaisesRegex(Tim2WritebackError, "is inconsistent"):
            inject_indexed4_rgba(source, bytes(original), bytes(original))

    def test_rejects_wrong_dimensions(self):
        source = make_canary_tim2(width=128)
        pixels = rgba_for_indexes(alternating_indexes())

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "unsupported canary width",
        ):
            inject_indexed4_rgba(source, pixels, pixels)

    def test_rejects_8bpp_texture(self):
        source = make_canary_tim2(image_type=5)
        pixels = rgba_for_indexes(alternating_indexes())

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "unsupported canary image type",
        ):
            inject_indexed4_rgba(source, pixels, pixels)

    def test_rejects_noncanonical_clut(self):
        source = make_canary_tim2(
            clut_type=3,
            clut_size=1024,
        )
        pixels = rgba_for_indexes(alternating_indexes())

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "unsupported canary CLUT type",
        ):
            inject_indexed4_rgba(source, pixels, pixels)

    def test_rejects_trailing_bytes(self):
        source = make_canary_tim2() + b"tail"
        pixels = rgba_for_indexes(alternating_indexes())

        with self.assertRaisesRegex(Tim2WritebackError, "trailing bytes"):
            inject_indexed4_rgba(source, pixels, pixels)

    def test_vt1_title_replaces_one_existing_index_only(self):
        source = make_vt1_title_tim2()

        result = replace_vt1_title_index(
            source,
            source_index=63,
            replacement_index=97,
            expected_occurrence_count=3,
        )

        self.assertEqual(result.changed_pixel_count, 3)
        self.assertEqual(result.changed_image_byte_count, 3)
        self.assertEqual(result.changed_image_byte_ranges, ((0, 3),))
        self.assertEqual(result.available_index_count, 3)
        self.assertEqual(result.data[64:68], bytes([97]) * 4)
        self.assertEqual(result.data[:64], source[:64])
        self.assertEqual(result.data[68:], source[68:])

    def test_vt1_title_noop_is_byte_identical(self):
        source = make_vt1_title_tim2()

        result = replace_vt1_title_index(
            source,
            source_index=63,
            replacement_index=63,
            expected_occurrence_count=3,
        )

        self.assertEqual(result.data, source)
        self.assertEqual(result.changed_pixel_count, 0)
        self.assertEqual(result.changed_image_byte_count, 0)
        self.assertEqual(result.changed_image_byte_ranges, ())

    def test_vt1_title_rejects_occurrence_count_mismatch(self):
        source = make_vt1_title_tim2()

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "occurs 3 times, expected 4",
        ):
            replace_vt1_title_index(
                source,
                source_index=63,
                replacement_index=97,
                expected_occurrence_count=4,
            )

    def test_vt1_title_rejects_missing_replacement_index(self):
        source = make_vt1_title_tim2()

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "replacement index 12 is not present",
        ):
            replace_vt1_title_index(
                source,
                source_index=63,
                replacement_index=12,
                expected_occurrence_count=3,
            )

    def test_vt1_title_rejects_noncanonical_picture_count(self):
        source = make_vt1_title_tim2(picture_count=5)

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "must contain exactly 6 pictures",
        ):
            replace_vt1_title_index(
                source,
                source_index=63,
                replacement_index=97,
                expected_occurrence_count=3,
            )

    def test_vt1_title_rejects_noncanonical_geometry(self):
        source = make_vt1_title_tim2(width=256)

        with self.assertRaisesRegex(
            Tim2WritebackError,
            "picture 0 width",
        ):
            replace_vt1_title_index(
                source,
                source_index=63,
                replacement_index=97,
                expected_occurrence_count=3,
            )

    def test_psmt8_round_trip_covers_every_pixel(self):
        logical = bytes(
            index & 0xFF
            for index in range(VT1_TITLE_IMAGE_SIZE)
        )

        stored = swizzle_psmt8(
            logical,
            VT1_TITLE_WIDTH,
            VT1_TITLE_HEIGHT,
        )

        self.assertEqual(
            unswizzle_psmt8(
                stored,
                VT1_TITLE_WIDTH,
                VT1_TITLE_HEIGHT,
            ),
            logical,
        )

    def test_vt1_indexed_injection_changes_logical_pixel_only(self):
        logical = bytes(
            48 + index % 32
            for index in range(VT1_TITLE_IMAGE_SIZE)
        )
        source = make_vt1_title_tim2(
            first_image=swizzle_psmt8(
                logical,
                VT1_TITLE_WIDTH,
                VT1_TITLE_HEIGHT,
            )
        )
        edited = bytearray(logical)
        edited[12345] = 79

        result = inject_vt1_title_indexes(source, bytes(edited))

        self.assertEqual(result.changed_pixel_count, 1)
        self.assertEqual(
            extract_vt1_title_indexes(result.data),
            bytes(edited),
        )
        self.assertEqual(result.data[:64], source[:64])
        self.assertEqual(
            result.data[64 + VT1_TITLE_IMAGE_SIZE :],
            source[64 + VT1_TITLE_IMAGE_SIZE :],
        )

    def test_vt1_static_renderer_applies_csm1_palette_shuffle(self):
        logical = bytearray(VT1_TITLE_IMAGE_SIZE)
        logical[0] = 9
        logical[1] = 17
        palette = bytearray(VT1_TITLE_CLUT_SIZE)
        palette[9 * 4 : 9 * 4 + 4] = b"\x09\x19\x29\x39"
        palette[17 * 4 : 17 * 4 + 4] = b"\x11\x21\x31\x41"
        source = make_vt1_title_tim2(
            first_image=swizzle_psmt8(
                bytes(logical),
                VT1_TITLE_WIDTH,
                VT1_TITLE_HEIGHT,
            ),
            first_clut=bytes(palette),
        )

        rendered = render_vt1_title_rgba(source)

        self.assertEqual(rendered[:4], b"\x11\x21\x31\x41")
        self.assertEqual(rendered[4:8], b"\x09\x19\x29\x39")

    def test_psmt8_rejects_noncanonical_geometry(self):
        with self.assertRaisesRegex(
            Tim2WritebackError,
            "positive multiple of 16",
        ):
            unswizzle_psmt8(bytes(17 * 16), 17, 16)


if __name__ == "__main__":
    unittest.main()
