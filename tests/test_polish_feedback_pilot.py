from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from tools.editorial_review.build_polish_feedback_pilot import (
    PilotValidationError,
    build_summary,
    load_corpus_targets,
    validate_seed,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = PROJECT_ROOT / "config/editorial/polish-feedback-pilot-v1.json"


class PolishFeedbackPilotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    def test_seed_covers_both_contributors_and_all_resolved_outcomes(self) -> None:
        decisions = validate_seed(self.document)
        summary = build_summary(self.document, decisions)

        self.assertEqual(summary["decision_count"], 11)
        self.assertEqual(summary["target_count"], 15)
        self.assertEqual(
            summary["contributor_counts"],
            {"天敌Nep": 7, "要开心": 4},
        )
        self.assertEqual(
            summary["finding_validity_counts"],
            {"invalid": 4, "partially_valid": 4, "valid": 3},
        )
        self.assertEqual(
            summary["proposal_disposition_counts"],
            {
                "accept_direction_rewrite": 4,
                "accept_exact": 1,
                "accept_partial": 2,
                "reject_keep_current": 4,
            },
        )
        self.assertEqual(summary["target_domain_counts"], {"story": 13, "battle": 2})

    def test_seed_targets_match_current_committed_corpus(self) -> None:
        decisions = validate_seed(self.document)
        expected = {
            target["id"]: target
            for decision in decisions
            for target in decision["targets"]
        }
        actual = load_corpus_targets(PROJECT_ROOT, expected)

        self.assertEqual(set(actual), set(expected))
        for target_id, target in expected.items():
            self.assertEqual(
                actual[target_id]["source_text_sha256"],
                target["expected_source_text_sha256"],
            )
            self.assertEqual(
                actual[target_id]["translation"],
                target["expected_translation"],
            )

    def test_seed_rejects_any_automatic_promotion_permission(self) -> None:
        unsafe = deepcopy(self.document)
        unsafe["policy"]["promotion"]["allowed"] = True

        with self.assertRaisesRegex(PilotValidationError, "policy is unsafe"):
            validate_seed(unsafe)


if __name__ == "__main__":
    unittest.main()
