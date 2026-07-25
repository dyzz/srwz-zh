import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.srwz.codec import decode
from tools.srwz.diagnostics import TraceCollector, require_work_output


class TraceCollectorTests(unittest.TestCase):
    def test_trace_is_bounded_while_statistics_are_complete(self):
        # Header, block and match produce three events; retain only the first two.
        collector = TraceCollector(2)
        decode(b"\x0D\x03\x01\x13abc\x25", trace_sink=collector)

        self.assertEqual(len(collector.events), 2)
        self.assertEqual(collector.total_events, 3)
        self.assertTrue(collector.truncated)
        self.assertEqual(
            collector.statistics(),
            {
                "block_count": 1,
                "match_token_count": 1,
                "advertised_match_count": 1,
                "literal_bytes": 3,
                "match_bytes": 3,
                "extended_distance_count": 0,
                "extended_length_count": 0,
                "max_literal_run": 3,
                "max_match_distance": 3,
                "max_match_length": 3,
            },
        )
        self.assertNotIn("abc", json.dumps(collector.events))

    def test_json_output_must_stay_under_work_directory(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            inside = require_work_output(work / "trace.json", work)
            self.assertEqual(inside, (work / "trace.json").resolve())

            with self.assertRaisesRegex(ValueError, "must stay under"):
                require_work_output(root / "trace.json", work)


if __name__ == "__main__":
    unittest.main()
