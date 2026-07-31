import tempfile
import unittest
from pathlib import Path

from tools.srwz.ui_runtime_fixtures import (
    build_runtime_fixture_preflight,
    inspect_memory_card,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"
SIGNATURE = b"Sony PS2 Memory Card Format"


def _raw_pages(*data_pages):
    return b"".join(
        page.ljust(512, b"\xff") + (b"\xff" * 16)
        for page in data_pages
    )


class UiRuntimeFixtureTests(unittest.TestCase):
    def test_erased_card_is_not_a_target_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "empty.ps2"
            card.write_bytes(b"\xff" * (528 * 2))
            result = inspect_memory_card(card)
        self.assertEqual(result["classification"], "erased_unformatted")
        self.assertTrue(result["all_ff"])
        self.assertFalse(result["formatted"])
        self.assertFalse(result["target_save_candidate"])

    def test_formatted_card_with_game_marker_is_only_a_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "target.ps2"
            card.write_bytes(
                _raw_pages(
                    SIGNATURE,
                    b"directory:BISLPS-25887-save",
                )
            )
            result = inspect_memory_card(card)
        self.assertEqual(
            result["classification"],
            "formatted_target_save_candidate",
        )
        self.assertTrue(result["formatted"])
        self.assertEqual(
            result["target_marker_hits"],
            ["SLPS-25887", "BISLPS-25887"],
        )
        self.assertTrue(result["target_save_candidate"])

    def test_fixture_priority_matches_blocked_runtime_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_runtime_fixture_preflight(
                PROJECT_ROOT,
                MATRIX_PATH,
                [Path(directory)],
            )
        self.assertEqual(report["status"], "fixture_acquisition_required")
        self.assertEqual(
            report["summary"],
            {
                "memory_card_fixture_count": 7,
                "ready_memory_card_fixture_count": 0,
                "not_acquired_memory_card_fixture_count": 7,
                "blocked_case_count": 40,
                "candidate_file_count": 0,
                "unique_candidate_hash_count": 0,
                "target_save_candidate_count": 0,
            },
        )
        priorities = report["fixture_priorities"]
        self.assertEqual(
            [fixture["blocked_case_count"] for fixture in priorities],
            [22, 7, 5, 3, 1, 1, 1],
        )
        self.assertEqual(
            priorities[0]["fixture_id"],
            "first-intermission-card",
        )
        self.assertEqual(priorities[0]["acquisition_rank"], 1)
        self.assertEqual(report["boundary"]["files_copied"], 0)
        self.assertEqual(report["boundary"]["runtime_status"], "not_tested")

    def test_discovered_target_card_does_not_promote_fixture_status(self):
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "candidate.ps2"
            card.write_bytes(
                _raw_pages(SIGNATURE, b"SLPS-25887")
            )
            report = build_runtime_fixture_preflight(
                PROJECT_ROOT,
                MATRIX_PATH,
                [Path(directory)],
            )
        self.assertEqual(
            report["summary"]["target_save_candidate_count"],
            1,
        )
        self.assertEqual(report["status"], "fixture_acquisition_required")
        self.assertTrue(
            all(
                fixture["status"] == "not_acquired"
                for fixture in report["fixture_priorities"]
            )
        )


if __name__ == "__main__":
    unittest.main()
