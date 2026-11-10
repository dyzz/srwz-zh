import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from srwz import continuation_indent as indent  # noqa: E402
from srwz.font import standard_glyph_index  # noqa: E402
from srwz.proportional_hooks import cjk_runtime_table  # noqa: E402
from srwz.proportional_metrics import CJK_FULL_WIDTH, CONTINUATION_INDENT_WIDTH  # noqa: E402
from srwz.release_font_policy import RAW_TRAIL_GAP_CLASS, allocation_width_class  # noqa: E402
from srwz.text import load_text_table  # noqa: E402


class ContinuationIndentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "shared/text-layout/proportional-metrics.mjs").read_text(encoding="utf-8")
        cls.registry = json.loads(text.split(" = ", 1)[1].rstrip(";\n"))

    def test_only_single_indents_after_a_compact_opener_are_marked(self):
        marked = "\n" + indent.CHARACTER
        self.assertEqual(indent.store("“甲乙\n　丙丁\n　戊”"), f"“甲乙{marked}丙丁{marked}戊”")
        self.assertEqual(indent.store("<color:01>（甲\n　乙）"), f"<color:01>（甲{marked}乙）")
        for kept in ("“单行”", "旁白\n　继续", "“甲”\n“乙”", "“甲\n　　乙”", "　“甲\n　乙”"):
            self.assertEqual(indent.store(kept), kept)
        self.assertEqual(indent.store("“甲\n　乙\n　　丙”"), f"“甲{marked}乙\n　　丙”")

    def test_store_keeps_length_and_restores_exactly(self):
        text = "“从紧急出动命令下达到出击，用时一分十五秒。算\n　是及格吧。”"
        stored = indent.store(text)
        self.assertEqual(len(stored), len(text))
        self.assertEqual(indent.restore(stored), text)
        with self.assertRaises(ValueError):
            indent.store(stored)

    def test_code_is_a_free_raw_trail_gap(self):
        # Raw-trail gaps are never handed out by the release-font allocator.
        self.assertEqual(allocation_width_class(indent.CODE), RAW_TRAIL_GAP_CLASS)
        self.assertEqual(standard_glyph_index(indent.CODE), indent.GLYPH_INDEX)
        table = load_text_table(ROOT / "vendor/upstream-python/project/tbl_all.json")
        self.assertNotIn(indent.CODE, table.characters)
        snapshot = json.loads((ROOT / "config/encoding/zh-release-font-assignments.json").read_text(encoding="utf-8"))
        for group in ("primary_assignments", "surface_alias_assignments", "source_compatibility_assignments", "remaining_allocation_candidates"):
            for row in snapshot[group]:
                self.assertNotEqual(int(row["code"], 16), indent.CODE, group)
                self.assertNotEqual(row.get("glyph_index"), indent.GLYPH_INDEX, group)
                self.assertNotEqual(row.get("character"), indent.CHARACTER, group)
        # Retired codebooks still feed permissive readback tables.
        for name in ("codebook.json", "release-menu-codebook.json"):
            for row in json.loads((ROOT / "config/encoding" / name).read_text(encoding="utf-8"))["assignments"]:
                self.assertNotEqual(int(row["code"], 16), indent.CODE, name)
                self.assertNotEqual(row.get("character"), indent.CHARACTER, name)

    def test_registry_gives_the_indent_the_opener_advance(self):
        for scene, profile in self.registry["profiles"].items():
            compact = profile["cjkPunctuation"]
            width = compact["，"]["width"]
            expected = width == CONTINUATION_INDENT_WIDTH and "“" not in CJK_FULL_WIDTH.get(scene, "")
            self.assertEqual("continuationIndent" in profile, expected, scene)
            if not expected:
                continue
            record = profile["continuationIndent"]
            self.assertEqual((record["code"], record["width"], record["bearing"], record["openers"]),
                             (indent.CODE, width, 0, indent.OPENERS))
            for opener in indent.OPENERS:
                self.assertEqual(compact[opener]["advance"], record["advance"], (scene, opener))
        self.assertEqual(self.registry["profiles"]["story"]["continuationIndent"]["advance"], 16)
        self.assertNotIn("continuationIndent", self.registry["profiles"]["battle"])

    def test_runtime_table_carries_the_indent_record(self):
        story = cjk_runtime_table(self.registry["profiles"]["story"])
        self.assertEqual(len(story), 6 * (len(self.registry["profiles"]["story"]["cjkPunctuation"]) + 2))
        self.assertEqual(story[-12:-6], bytes((0xFD, 0x93, 0, 16, 21, 0)))
        self.assertEqual(story[-6:], bytes(6))
        battle = cjk_runtime_table(self.registry["profiles"]["battle"])
        self.assertEqual(len(battle), 6 * (len(self.registry["profiles"]["battle"]["cjkPunctuation"]) + 1))
        self.assertNotIn(indent.CODE, [int.from_bytes(battle[at:at + 2], "little") for at in range(0, len(battle), 6)])


if __name__ == "__main__":
    unittest.main()
