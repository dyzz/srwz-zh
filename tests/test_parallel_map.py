"""Pure jobs fan out over worker processes and come back in order."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz import parallel


def square(value):
    return (os.getpid(), value * value)


class ParallelMapTests(unittest.TestCase):
    def test_results_keep_order_across_processes(self):
        results = parallel.map_processes(square, range(12), chunksize=2)
        self.assertEqual([v for _, v in results], [n * n for n in range(12)])
        self.assertGreater(len({pid for pid, _ in results}), 1)
        self.assertNotIn(os.getpid(), {pid for pid, _ in results})

    def test_short_lists_and_single_worker_run_inline(self):
        self.assertEqual(parallel.map_processes(square, [3]), [(os.getpid(), 9)])
        with patch.dict(os.environ, {parallel.ENV_WORKERS: "1"}):
            self.assertEqual([p for p, _ in parallel.map_processes(square, range(12))], [os.getpid()] * 12)



class ShardMergeTests(unittest.TestCase):
    def test_contiguous_shards_keep_order(self):
        with patch.dict(os.environ, {parallel.ENV_WORKERS: "3"}):
            self.assertEqual(parallel.split_shards(range(7)), [[0, 1, 2], [3, 4, 5], [6]])
        self.assertEqual(parallel.split_shards([]), [])

    def test_merge_rules_by_type(self):
        from collections import Counter
        merge = parallel.merge_shard_values
        self.assertEqual(merge("total", 0, [2, 3]), 5)
        self.assertEqual(merge("maximum_width", 1, [4, 2]), 4)
        self.assertEqual(merge("reports", [], [[1, 2], [3]]), [1, 2, 3])
        self.assertEqual(merge("stages", set(), [{1}, {2, 3}]), {1, 2, 3})
        self.assertEqual(merge("quotes", Counter(), [Counter(a=1), Counter(a=2, b=1)]), Counter(a=3, b=1))
        self.assertEqual(merge("readbacks", {}, [{"a": 1}, {"b": 2}]), {"a": 1, "b": 2})
        self.assertEqual(merge("examples", {}, [{"a": 1}, {"a": 2}], first_wins=True), {"a": 1})
        with self.assertRaises(ValueError):
            merge("readbacks", {}, [{"a": 1}, {"a": 2}])
        self.assertIsNone(merge("reported", None, [None, None]))
        self.assertEqual(merge("reported", None, [None, "x"]), "x")
        with self.assertRaises(ValueError):
            merge("reported", None, ["x", "y"])


if __name__ == "__main__":
    unittest.main()
