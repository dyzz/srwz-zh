import unittest

from tools.build_full_story_components import (
    _count_span_groups_containing_offsets,
)


class BuildPerformanceHelperTests(unittest.TestCase):
    def test_counts_each_touched_group_once(self):
        groups = [
            [(10, 20), (30, 40)],
            [(15, 18)],
            [(50, 60)],
        ]
        self.assertEqual(
            _count_span_groups_containing_offsets(groups, {16, 35}),
            2,
        )

    def test_span_end_is_exclusive(self):
        self.assertEqual(
            _count_span_groups_containing_offsets([[(10, 20)]], {20}),
            0,
        )

    def test_empty_change_set_selects_nothing(self):
        self.assertEqual(
            _count_span_groups_containing_offsets([[(10, 20)]], set()),
            0,
        )


if __name__ == "__main__":
    unittest.main()
