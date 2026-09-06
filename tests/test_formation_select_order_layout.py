from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FormationSelectOrderLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        corpus = json.loads(
            (PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
                encoding="utf-8"
            )
        )
        cls.translations = corpus["compdata_direct_by_offset"]

    def test_order_descriptions_follow_the_stock_two_line_layout(self) -> None:
        expected = {
            "0x7EDA0": (
                "以全部小队为对象，按照预设方案\n"
                "进行包含换乘在内的编成。"
            ),
            "0x7EDF0": "保留指定小队，将其他小队\n均衡地重新编成。",
        }

        for offset, text in expected.items():
            self.assertEqual(self.translations[offset], text)
            lines = text.splitlines()
            self.assertEqual(len(lines), 2)
            self.assertLessEqual(max(map(len, lines)), 15)

    def test_auto_formation_overlay_starts_after_the_chinese_prefix(self) -> None:
        base = self.translations["0x7EF80"]
        overlay = self.translations["0x7EFE0"]
        prefix = base.rstrip("　")
        leading_spaces = len(overlay) - len(overlay.lstrip("　"))

        self.assertEqual(prefix, "按照上述方针，将")
        self.assertEqual(leading_spaces, len(prefix))
        self.assertEqual(overlay.lstrip("　"), "自动编成")
        self.assertNotIn(" ", base)
        self.assertNotIn(" ", overlay)


if __name__ == "__main__":
    unittest.main()
