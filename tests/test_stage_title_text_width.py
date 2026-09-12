from __future__ import annotations

import unittest
from pathlib import Path

from tools.srwz.text import (
    decode_text,
    encode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
    trailing_latin_run,
    wrap_trailing_latin_run,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StageTitleTextWidthTest(unittest.TestCase):
    def test_trailing_run_detection(self) -> None:
        self.assertEqual(trailing_latin_run("Blue Sky Fish"), ("", "Blue Sky Fish"))
        self.assertEqual(trailing_latin_run("灵魂的Cosplayer"), ("灵魂的", "Cosplayer"))
        self.assertEqual(trailing_latin_run("Z的脉动"), ("Z的脉动", ""))
        self.assertEqual(trailing_latin_run("第15年的亡灵"), ("第15年的亡灵", ""))
        self.assertEqual(trailing_latin_run("我是D.O.M.E.……"), ("我是D.O.M.E.……", ""))
        self.assertEqual(trailing_latin_run("绯红之路"), ("绯红之路", ""))
        # digits alone are not a Latin run
        self.assertEqual(trailing_latin_run("调试关卡901"), ("调试关卡901", ""))

    def test_wrap_emits_control_notation(self) -> None:
        wrapped = wrap_trailing_latin_run(
            "Over Battle", width=0x0E, space=0x0C, restore_width=0x12, restore_space=0x12
        )
        self.assertEqual(
            wrapped, "<width:0E><space:0C>Over Battle<width:12><space:12>"
        )
        self.assertEqual(
            wrap_trailing_latin_run(
                "灵魂的Cosplayer", width=14, space=12, restore_width=18, restore_space=18
            ),
            "灵魂的<width:0E><space:0C>Cosplayer<width:12><space:12>",
        )
        self.assertEqual(
            wrap_trailing_latin_run("Z的脉动", width=14, space=12, restore_width=18, restore_space=18),
            "Z的脉动",
        )
        with self.assertRaisesRegex(ValueError, "width must be"):
            wrap_trailing_latin_run("Abc", width=0, space=12, restore_width=18, restore_space=18)

    def test_wrapped_title_round_trips_through_the_stock_table(self) -> None:
        table = load_text_table(PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json")
        overrides = dict(original_fullwidth_ascii_overrides(table))
        overrides[" "] = 0x8140
        wrapped = wrap_trailing_latin_run(
            "Gain Over", width=0x0E, space=0x0C, restore_width=0x12, restore_space=0x12
        )
        payload = encode_text(wrapped, table, overrides=overrides, terminate=True)
        self.assertTrue(payload.startswith(bytes.fromhex("320e340c")))
        self.assertTrue(payload.endswith(bytes.fromhex("32123412") + b"\x00"))
        readback = decode_text(
            payload,
            0,
            type(table)(
                characters={**table.characters, **{code: char for char, code in overrides.items()}},
                tags=table.tags,
            ),
        )
        self.assertEqual(readback.text, wrapped)


if __name__ == "__main__":
    unittest.main()
