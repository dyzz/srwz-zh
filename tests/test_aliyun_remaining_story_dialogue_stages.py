from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import run_aliyun_remaining_story_dialogue_stages as remaining


def write_piece(directory: Path, indices: tuple[int, ...], cost: float = 0.01) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "parsed.jsonl").write_text(
        "".join(
            json.dumps({"stage_index": 25, "unique_index": index}) + "\n"
            for index in indices
        ),
        encoding="utf-8",
    )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "run": {
                    "finish_reason": "stop",
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                },
                "format_audit": {
                    "exact_id_order": True,
                    "translation_item_count": len(indices),
                },
                "pricing": {"estimated_run_cost_cny": cost},
            }
        ),
        encoding="utf-8",
    )


class RemainingStageBatchTests(unittest.TestCase):
    def test_max_tokens_leaves_headroom_and_caps(self) -> None:
        self.assertEqual(remaining.max_tokens(238), 23552)
        self.assertEqual(remaining.max_tokens(450), 40960)
        self.assertEqual(remaining.max_tokens(1000), 65536)

    def test_split_fallback_merges_all_parts_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stage-025"
            job = remaining.Job(25, 0, tuple(range(6)), False, 6, 6)

            def execute(job, directory, *, indices, full_stage):
                self.assertFalse(full_stage)
                write_piece(directory, tuple(indices))
                return 0, 0.25

            with mock.patch.object(remaining, "ROOT", root), mock.patch.object(
                remaining, "stage_output", return_value=output
            ), mock.patch.object(remaining, "execute_request", side_effect=execute):
                result = remaining.run_fallback(job, max_attempts=2, chunk_size=2)

            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "complete")
            merged = remaining.json_rows(
                output / "requests/chunk-000/fallback-002/parsed.jsonl"
            )
            self.assertEqual([row["unique_index"] for row in merged], list(range(6)))
            manifest = json.loads(
                (output / "requests/chunk-000/fallback-002/manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["format_audit"]["translation_item_count"], 6)
            self.assertEqual(manifest["run"]["prompt_tokens"], 30)
            self.assertAlmostEqual(manifest["pricing"]["estimated_run_cost_cny"], 0.03)


if __name__ == "__main__":
    unittest.main()
