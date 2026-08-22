import json
import re
import unittest
from pathlib import Path

from tools.srwz.chinese_layout import (
    DEFAULT_CONTINUATION_LINE_WIDTH,
    DEFAULT_LINE_WIDTH,
    DEFAULT_MAX_LINES,
    dialogue_line_widths,
)
from tools.audit_stage_keyword_links import load_story_keyword_occurrences
from tools.audit_zh_text_layout import edge_violations


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
SYSTEM_DIALOGUE_PATH = PROJECT_ROOT / "corpus/zh/story-system-dialogue.json"


class StoryDialogueLayoutTests(unittest.TestCase):
    def test_all_player_choice_transitions_have_three_bounded_rows(self):
        pattern = re.compile(r"^“.+的选择”\n“1．.+”\n“2．.+”$")
        choices = []
        for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            choices.extend(
                entry
                for entry in document["entries"]
                if pattern.fullmatch(entry["translation"])
            )
        self.assertEqual(len(choices), 17)
        for entry in choices:
            widths = dialogue_line_widths(entry["translation"])
            self.assertEqual(len(widths), 3, entry["id"])
            self.assertLessEqual(max(widths), DEFAULT_LINE_WIDTH, entry["id"])

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
                    or (widths and widths[0] > DEFAULT_LINE_WIDTH)
                    or any(
                        width > DEFAULT_CONTINUATION_LINE_WIDTH
                        for width in widths[1:]
                    )
                    or edge_violations(entry["translation"])
                ):
                    violations.append(
                        (
                            entry["id"],
                            widths,
                            edge_violations(entry["translation"]),
                        )
                    )
        self.assertEqual(entry_count, 83668)
        self.assertEqual(violations, [])

    def test_stg00_suspend_save_and_quit_dialogue_fits_the_runtime_21x3_box(self):
        document = json.loads(SYSTEM_DIALOGUE_PATH.read_text(encoding="utf-8"))
        violations = []
        for entry in document["entries"]:
            widths = dialogue_line_widths(entry["translation"])
            if (
                len(widths) > DEFAULT_MAX_LINES
                or (widths and widths[0] > DEFAULT_LINE_WIDTH)
                or any(
                    width > DEFAULT_CONTINUATION_LINE_WIDTH
                    for width in widths[1:]
                )
                or edge_violations(entry["translation"])
            ):
                violations.append(
                    (
                        entry["id"],
                        widths,
                        edge_violations(entry["translation"]),
                    )
                )
        self.assertEqual(len(document["entries"]), 379)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
