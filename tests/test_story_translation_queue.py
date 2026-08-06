import unittest
from pathlib import Path

from tools.report_story_translation_queue import (
    DEFAULT_SOURCE,
    DEFAULT_UPSTREAM,
    build_report,
)


class StoryTranslationQueueTests(unittest.TestCase):
    def test_queue_separates_reviewed_batches_from_drafts(self):
        report = build_report(DEFAULT_SOURCE, DEFAULT_UPSTREAM)
        self.assertEqual(report["stage_count"], 154)
        self.assertEqual(report["source_story_dialogue_entry_count"], 82719)
        stages = {stage["stage_index"]: stage for stage in report["stages"]}
        self.assertEqual(stages[1]["status"], "committed_reviewed")
        self.assertEqual(stages[6]["status"], "committed_reviewed")
        self.assertEqual(stages[18]["status"], "committed_reviewed")
        self.assertEqual(stages[13]["status"], "draft_ready")
        self.assertEqual(stages[13]["upstream_pointer_match_count"], 251)
        self.assertEqual(stages[153]["status"], "source_only")


if __name__ == "__main__":
    unittest.main()
