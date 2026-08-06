import json
import unittest
from pathlib import Path

from tools.build_story_viewer import (
    DEFAULT_QUEUE,
    build_viewer_data,
    parse_route_map,
)


class StoryViewerDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.data = build_viewer_data()

    def test_route_map_retains_branch_titles_and_nonchapter_items(self):
        groups = parse_route_map()
        self.assertEqual(len(groups), 13)
        ordinals = {
            title["ordinal"]
            for group in groups
            for row in group["rows"]
            for title in row["titles"]
            if title
        }
        self.assertEqual(set(range(107)), ordinals)
        self.assertEqual(groups[-1]["heading"], "非章节标题项")
        self.assertEqual(len(groups[-1]["rows"]), 15)

    def test_resource_order_is_not_route_ordinal_order(self):
        stages = [stage["stage_index"] for stage in self.data["resource_stages"]]
        self.assertEqual(stages[:3], [1, 2, 3])
        self.assertEqual(stages[-2:], [185, 186])
        self.assertEqual(stages, sorted(stages))
        self.assertEqual(len(stages), 154)
        self.assertIn(
            "story/NNN",
            self.data["source"]["ordering_note"],
        )

    def test_queue_and_counts_are_preserved(self):
        with DEFAULT_QUEUE.open(encoding="utf-8") as handle:
            queue_count = sum(1 for line in handle if line.strip())
        self.assertEqual(self.data["counts"]["unique"], queue_count)
        self.assertEqual(self.data["counts"]["occurrences"], 82719)
        self.assertEqual(self.data["counts"]["unique"], 69167)
        self.assertEqual(len(self.data["stage_titles"]), 122)

    def test_entries_have_source_identity_and_display_state(self):
        entries = [
            entry
            for stage in self.data["resource_stages"]
            for section in stage["sections"]
            for entry in section["entries"]
        ]
        self.assertEqual(len(entries), 69167)
        self.assertTrue(all(len(entry["source_hash"]) == 64 for entry in entries))
        self.assertTrue(all(entry["source_text"] for entry in entries))
        statuses = {entry["display_status"] for entry in entries}
        self.assertTrue({"已审校", "机器草稿", "待翻译"}.issubset(statuses))

    def test_data_is_json_serializable(self):
        json.dumps(self.data, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
