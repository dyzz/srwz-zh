import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from srwz.chinese_layout import location_caption


from typography_fixtures import NativeTypographyTestCase

class LocationCaptionTest(NativeTypographyTestCase):
    def test_matches_the_japanese_centring(self):
        self.assertEqual(location_caption("～卢特提姆基地　通道～"), "<z>　</z>" + "　" * 6 + "〜卢特提姆基地　通道〜")
        self.assertEqual(location_caption("——月光号机库——"), "<z>　</z>" + "　" * 8 + "〜月光号机库〜")

    def test_is_idempotent_and_keeps_inner_spaces(self):
        once = location_caption("〜奥布　市区〜")
        self.assertEqual(location_caption(once), once)
        self.assertIn("奥布　市区", once)

    def test_latin_is_measured_at_its_displayed_width(self):
        self.assertEqual(
            location_caption("〜<z>DEAVA</z>元素学校〜"),
            "<z>　</z>" + "　" * 7 + "〜<z>DEAVA</z>元素学校〜",
        )


if __name__ == "__main__":
    unittest.main()


class ProportionalLocationCaptionTest(unittest.TestCase):
    def test_tag_free_caption_is_centered_and_idempotent(self):
        from srwz.renderer_metrics import text_extent
        source = "〜<z>DEAVA</z>元素学校〜"
        result = location_caption(source)
        self.assertNotIn('<z>', result)
        self.assertEqual(location_caption(result), result)
        core = "〜DEAVA元素学校〜"
        width = text_extent(core, default_advance_px=21).occupied_px
        total = text_extent(result, default_advance_px=21).occupied_px
        self.assertLessEqual(abs((total-width) + width/2 - 252), 0.5)
