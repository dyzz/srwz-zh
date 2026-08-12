import json
import unittest
from pathlib import Path

from tools.srwz.text import (
    decode_text,
    encode_text,
    load_text_table,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POPUP_HINTS = {
    "0x33DC02": "切换术语",
    "0x33E112": "切换术语",
}


class KeywordPopupUiTests(unittest.TestCase):
    def test_both_original_popup_hints_are_localized_in_place(self):
        source = json.loads(
            (PROJECT_ROOT / "config/story-component.json").read_text(
                encoding="utf-8"
            )
        )["source"]
        slps = (PROJECT_ROOT / source["slps"]["path"]).read_bytes()
        table = load_text_table(PROJECT_ROOT / source["text_table"]["path"])
        translations = json.loads(
            (PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
                encoding="utf-8"
            )
        )["slps_context_ui_by_offset"]

        assignments = json.loads(
            (
                PROJECT_ROOT
                / "config/encoding/zh-release-font-assignments.json"
            ).read_text(encoding="utf-8")
        )
        overrides = {
            row["character"]: int(row["code"], 16)
            for row in assignments["primary_assignments"]
        }
        overrides.update(
            {
                row["character"]: int(row["code"], 16)
                for row in assignments["surface_alias_assignments"]
            }
        )
        output_table = project_runtime_text_table(table, overrides)

        for raw_offset, expected in POPUP_HINTS.items():
            offset = int(raw_offset, 16)
            original = decode_text(slps, offset, table)
            self.assertEqual(original.text, "用語の切り替え")
            self.assertEqual(original.consumed, 15)
            self.assertEqual(translations[raw_offset], expected)

            encoded = encode_text(
                expected,
                table,
                overrides=overrides,
                terminate=True,
            )
            self.assertLessEqual(len(encoded), original.consumed)
            replacement = encoded + bytes(original.consumed - len(encoded))
            self.assertEqual(decode_text(replacement, 0, output_table).text, expected)


if __name__ == "__main__":
    unittest.main()
