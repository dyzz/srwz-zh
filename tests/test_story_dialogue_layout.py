import json
import unittest
from pathlib import Path

from tools.srwz.chinese_layout import (
    DEFAULT_LINE_WIDTH,
    DEFAULT_MAX_LINES,
    dialogue_line_widths,
)
from tools.audit_stage_keyword_links import load_story_keyword_occurrences


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"


class StoryDialogueLayoutTests(unittest.TestCase):
    def test_every_story_dialogue_entry_fits_the_runtime_21x3_box(self):
        violations = []
        entry_count = 0
        keyword_entry_ids = {
            row.entry_id for row in load_story_keyword_occurrences()
        }
        self.assertEqual(len(keyword_entry_ids), 111)
        for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document["entries"]:
                entry_count += 1
                widths = dialogue_line_widths(
                    entry["translation"],
                    stage_keyword_links=(entry["id"] in keyword_entry_ids),
                )
                if (
                    len(widths) > DEFAULT_MAX_LINES
                    or (widths and max(widths) > DEFAULT_LINE_WIDTH)
                ):
                    violations.append((entry["id"], widths))
        self.assertEqual(entry_count, 83507)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
