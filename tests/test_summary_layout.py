import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.chinese_layout import (
    FORBIDDEN_LINE_END_CHARACTERS,
    FORBIDDEN_LINE_START_CHARACTERS,
    rendered_line_width,
)
from tools.srwz.summary_layout import logical_summary_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/summary/world-history-layout.json"
CORPUS_PATH = PROJECT_ROOT / "corpus/zh/summary.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/world-history-layout.json"


class SummaryLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.entries = {entry["id"]: entry for entry in cls.corpus["entries"]}

    def test_logical_text_ignores_visual_indent_and_blank_rows(self):
        self.assertEqual(
            logical_summary_text("　第一段。\n续行。\n　\n　第二段。"),
            "第一段。续行。第二段。",
        )

    def test_committed_world_history_layout_is_bounded_and_pending(self):
        manifest = self.manifest
        self.assertEqual(
            manifest["status"],
            "layout_validated_editorial_font_runtime_pending",
        )
        self.assertEqual(manifest["selection"]["entry_count"], 28)
        self.assertEqual(manifest["selection"]["text_chunk_count"], 12)
        self.assertEqual(
            manifest["inputs"]["config"]["sha256"],
            hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["inputs"]["translation_source"]["current_sha256"],
            manifest["inputs"]["translation_source"]["projected_sha256"],
        )

        layout = manifest["layout"]
        self.assertEqual(layout["output_line_count"], 146)
        self.assertEqual(layout["maximum_line_width"], 22)
        self.assertEqual(layout["source_blank_line_count"], 14)
        self.assertEqual(layout["output_blank_line_count"], 14)
        self.assertEqual(layout["noncanonical_entry_count"], 0)
        self.assertEqual(layout["fixed_line_group_count"], 3)
        self.assertEqual(layout["fixed_line_group_entry_count"], 14)
        self.assertTrue(layout["logical_text_preserved"])

        self.assertEqual(manifest["allocation"]["overflow_count"], 0)
        self.assertEqual(manifest["editorial"]["status_counts"]["draft"], 28)
        self.assertFalse(manifest["editorial"]["ready_for_production"])
        self.assertEqual(manifest["font_capacity"]["missing_character_count"], 41)
        self.assertEqual(
            manifest["font_capacity"]["remaining_safe_candidate_slot_count"],
            3,
        )
        self.assertEqual(manifest["font_capacity"]["candidate_shortfall"], 38)
        self.assertEqual(
            manifest["inputs"]["font"]["missing_reason_counts"],
            {"resolver_unreachable": 14, "unmapped": 27},
        )
        self.assertFalse(manifest["font_capacity"]["ready_for_component"])
        self.assertEqual(manifest["runtime"]["status"], "not_tested")
        self.assertTrue(manifest["ratchet"]["passed"])

    def test_corpus_lines_obey_width_and_punctuation_rules(self):
        line_count = 0
        blank_count = 0
        for entry in self.corpus["entries"]:
            for line in entry["translation"].splitlines():
                content = line.lstrip("　 ")
                line_count += 1
                if not content:
                    blank_count += 1
                    continue
                self.assertLessEqual(
                    rendered_line_width(content),
                    22,
                    entry["id"],
                )
                self.assertNotIn(
                    content[0],
                    FORBIDDEN_LINE_START_CHARACTERS,
                    entry["id"],
                )
                self.assertNotIn(
                    content[-1],
                    FORBIDDEN_LINE_END_CHARACTERS,
                    entry["id"],
                )
        self.assertEqual(line_count, 146)
        self.assertEqual(blank_count, 14)

    def test_fixed_group_moves_glossary_reference_with_un_text(self):
        first = self.entries["summary/09/000"]
        second = self.entries["summary/09/001"]
        third = self.entries["summary/09/002"]
        self.assertTrue(first["translation"].endswith("演变为"))
        self.assertTrue(second["translation"].startswith("暴动；"))
        self.assertIn("UN", third["translation"])
        self.assertNotIn("system/un-network", second["glossary_refs"])
        self.assertIn("system/un-network", third["glossary_refs"])


if __name__ == "__main__":
    unittest.main()
