import unittest

from tools.srwz.title_menu import (
    SELECTED_RAMP_BASE,
    TITLE_LABEL_COUNT,
    TITLE_LABEL_HEIGHT,
    TITLE_LABEL_WIDTH,
    TITLE_TEXTURE_HEIGHT,
    TITLE_TEXTURE_WIDTH,
    TitleMenuError,
    UNSELECTED_RAMP_BASE,
    apply_title_menu_masks,
    quantize_mask,
)


class TitleMenuTests(unittest.TestCase):
    def test_quantizes_full_grayscale_range_to_existing_ramp(self):
        mask = bytes([0, 8, 127, 128, 247, 255])
        mask += bytes(
            TITLE_LABEL_WIDTH * TITLE_LABEL_HEIGHT - len(mask)
        )

        indexes = quantize_mask(mask, SELECTED_RAMP_BASE)

        self.assertEqual(
            indexes[:6],
            bytes([48, 48, 55, 56, 63, 63]),
        )
        self.assertEqual(set(indexes) - set(range(48, 64)), set())

    def test_replaces_all_eight_slots_and_preserves_right_side(self):
        original = bytes(
            [99] * (TITLE_TEXTURE_WIDTH * TITLE_TEXTURE_HEIGHT)
        )
        masks = [
            bytes(
                [index * 64]
                * (TITLE_LABEL_WIDTH * TITLE_LABEL_HEIGHT)
            )
            for index in range(TITLE_LABEL_COUNT)
        ]

        result = apply_title_menu_masks(original, masks)

        self.assertEqual(len(result.edited_slots), 8)
        for label_index in range(TITLE_LABEL_COUNT):
            y = label_index * TITLE_LABEL_HEIGHT
            selected = result.indexes[
                y * TITLE_TEXTURE_WIDTH :
                y * TITLE_TEXTURE_WIDTH + TITLE_LABEL_WIDTH
            ]
            unselected_y = (
                label_index + TITLE_LABEL_COUNT
            ) * TITLE_LABEL_HEIGHT
            unselected = result.indexes[
                unselected_y * TITLE_TEXTURE_WIDTH :
                unselected_y * TITLE_TEXTURE_WIDTH + TITLE_LABEL_WIDTH
            ]
            level = (label_index * 64 * 15 + 127) // 255
            self.assertEqual(
                selected,
                bytes([SELECTED_RAMP_BASE + level])
                * TITLE_LABEL_WIDTH,
            )
            self.assertEqual(
                unselected,
                bytes([UNSELECTED_RAMP_BASE + level])
                * TITLE_LABEL_WIDTH,
            )
        for y in range(TITLE_TEXTURE_HEIGHT):
            right = result.indexes[
                y * TITLE_TEXTURE_WIDTH + TITLE_LABEL_WIDTH :
                (y + 1) * TITLE_TEXTURE_WIDTH
            ]
            self.assertEqual(
                right,
                bytes([99])
                * (TITLE_TEXTURE_WIDTH - TITLE_LABEL_WIDTH),
            )

    def test_rejects_wrong_mask_count(self):
        original = bytes(
            TITLE_TEXTURE_WIDTH * TITLE_TEXTURE_HEIGHT
        )

        with self.assertRaisesRegex(TitleMenuError, "requires 4 masks"):
            apply_title_menu_masks(original, [])


if __name__ == "__main__":
    unittest.main()
