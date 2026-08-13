import json
import unittest
from pathlib import Path

from tools.audit_zh_text_layout import (
    edge_violations,
    layout_violations,
    reflow_preserved_paragraph,
)
from tools.build_full_story_components import _apply_world_history_layout
from tools.srwz.chinese_layout import load_layout_profiles


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ZhTextLayoutAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_layout_profiles(
            PROJECT_ROOT / "config/text-layout/zh-layout-profiles.json"
        )

    def test_edge_audit_distinguishes_punctuation_from_modal_particles(self):
        self.assertEqual(
            edge_violations("第一行\n，第二行"),
            [
                {
                    "kind": "forbidden_line_start",
                    "line": 2,
                    "character": "，",
                }
            ],
        )
        self.assertEqual(edge_violations("第一行。\n啊，第二行。"), [])

    def test_layout_audit_reports_width_and_line_count_separately(self):
        profile = self.profiles["story_dialogue"]
        violations = layout_violations(
            "第一行\n" + "超" * 22 + "\n第三行\n第四行",
            profile=profile,
            protected_terms=(),
        )
        self.assertIn(
            {"kind": "line_too_wide", "line": 2, "width": 22, "limit": 21},
            violations,
        )
        self.assertIn(
            {"kind": "too_many_lines", "line_count": 4, "limit": 3},
            violations,
        )

    def test_preserved_overview_paragraph_repairs_leading_period(self):
        output = reflow_preserved_paragraph(
            ["　察觉异常的众人出动迎击", "。战斗随后开始。"],
            profile=self.profiles["stage_scroll_overview"],
            protected_terms=(),
        )
        self.assertEqual(len(output), 2)
        self.assertTrue(output[0].startswith("　"))
        self.assertFalse(output[1].startswith("。"))
        self.assertEqual(
            "".join(output).replace("　", ""), "察觉异常的众人出动迎击。战斗随后开始。"
        )

    def test_preserved_scroll_blank_line_remains_one_line(self):
        output = reflow_preserved_paragraph(
            ["　"],
            profile=self.profiles["world_history_scroll"],
            protected_terms=(),
        )
        self.assertEqual(output, ["　"])

    def test_built_world_history_member_uses_reflowed_corpus(self):
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        font_manifest = json.loads(
            (PROJECT_ROOT / "manifests/zh-release-font-validation.json").read_text(
                encoding="utf-8"
            )
        )
        slps = (
            PROJECT_ROOT
            / "work/build/zh-release-full-story/components/SLPS_258.87"
        ).read_bytes()
        base = (
            PROJECT_ROOT
            / "work/build/release-base-ui/components/DATA/MTV_PROS.BIN"
        ).read_bytes()
        expected = (
            PROJECT_ROOT
            / "work/build/zh-release-full-story/components/DATA/MTV_PROS.BIN"
        ).read_bytes()
        output, report, _path = _apply_world_history_layout(
            slps,
            base,
            config["world_history"],
            font_manifest,
        )
        self.assertEqual(output, expected)
        self.assertEqual(report["changed_entry_count"], 2)
        self.assertTrue(report["runtime_text_reread_exact"])


if __name__ == "__main__":
    unittest.main()
