import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.translation_review import (
    load_glossary,
    load_source_corpus,
    load_translations,
    write_dialogue_milestone_exception_tsv,
    write_dialogue_milestone_term_tsv,
    write_terminology_variant_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"
REVIEW_PATH = (
    PROJECT_ROOT
    / "corpus"
    / "review"
    / "first-five-official-variants-v1.json"
)


class FirstFiveTerminologyReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
        cls.source_entries = load_source_corpus(
            PROJECT_ROOT / cls.release["source_corpus"]["path"]
        )
        cls.translations = load_translations(
            PROJECT_ROOT / path
            for path in cls.release["translation_sources"]
        )
        cls.glossary = load_glossary(
            PROJECT_ROOT / path
            for path in cls.release["glossary_sources"]
        )

    def test_committed_review_matches_current_first_five_glossary(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "variants.tsv"
            report = write_terminology_variant_tsv(
                output,
                self.review,
                self.source_entries,
                self.translations,
                self.glossary,
            )
            self.assertEqual(
                report,
                {
                    "review_id": "srwz-zh-first-five-official-variants-v1",
                    "stage_indices": [1, 2, 3, 4, 5],
                    "kinds": ["dialogue", "speaker"],
                    "decision_count": 9,
                    "status_counts": {
                        "keep_current": 4,
                        "needs_human_review": 5,
                    },
                },
            )
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 9)
            self.assertTrue(
                all(int(row["reference_count"]) > 0 for row in rows)
            )
            self.assertTrue(
                all(row["stages_used"] for row in rows)
            )
            self.assertTrue(
                all(
                    row["evidence_url"].startswith(
                        "https://gundam-official.cn/"
                    )
                    for row in rows
                )
            )

    def test_selected_biligame_names_are_explicitly_recorded(self):
        statuses = {
            decision["id"]: decision["decision_status"]
            for decision in self.review["decisions"]
        }
        self.assertEqual(
            {
                decision_id
                for decision_id, status in statuses.items()
                if status == "keep_current"
            },
            {
                "seed-destiny-neo-short",
                "seed-destiny-neo-full",
                "seed-destiny-talia",
                "seed-destiny-lunamaria",
            },
        )
        self.assertTrue(
            all(
                decision["current_translation"]
                != decision["official_variant"]
                for decision in self.review["decisions"]
            )
        )

    def test_first_five_human_review_queues_are_complete(self):
        term_origins = {}
        for stage_index in range(1, 6):
            relative_path = (
                "corpus/glossary/"
                f"story-dialogue-stage-{stage_index:03d}-v1.json"
            )
            path = PROJECT_ROOT / relative_path
            for term in load_glossary((path,)):
                term_origins[term.term_id] = (
                    stage_index,
                    relative_path,
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            terms_path = root / "terms.tsv"
            exceptions_path = root / "exceptions.tsv"
            terms_report = write_dialogue_milestone_term_tsv(
                terms_path,
                self.source_entries,
                self.translations,
                self.glossary,
                term_origins=term_origins,
                stage_indices=(1, 2, 3, 4, 5),
            )
            exceptions_report = write_dialogue_milestone_exception_tsv(
                exceptions_path,
                self.source_entries,
                self.translations,
                stage_indices=(1, 2, 3, 4, 5),
            )

            self.assertEqual(
                terms_report,
                {
                    "stage_indices": [1, 2, 3, 4, 5],
                    "term_count": 112,
                    "proposed_term_count": 3,
                    "researched_term_count": 109,
                    "translation_conflict_term_count": 1,
                    "priority_counts": {
                        "high": 4,
                        "medium": 2,
                        "normal": 106,
                    },
                },
            )
            self.assertEqual(
                exceptions_report,
                {
                    "stage_indices": [1, 2, 3, 4, 5],
                    "record_count": 65,
                    "exception_counts": {
                        "people/rey-za-burrel-short": 1,
                        "skill/extreme": 1,
                        "skill/guard": 2,
                        "system/damage": 3,
                        "system/evasion": 1,
                        "system/level": 1,
                        "system/pilot": 1,
                        "system/turn": 52,
                        "system/unknown-machine": 5,
                    },
                },
            )

            with terms_path.open(encoding="utf-8", newline="") as handle:
                term_rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(term_rows), 112)
            self.assertEqual(
                sum(row["review_priority"] == "high" for row in term_rows),
                4,
            )
            self.assertTrue(
                all(
                    row["origin_stage"] in {
                        "001",
                        "002",
                        "003",
                        "004",
                        "005",
                    }
                    and row["origin_glossary"].startswith(
                        "corpus/glossary/story-dialogue-stage-"
                    )
                    and int(row["reference_count"])
                    + int(row["exception_count"])
                    > 0
                    and row["notes"]
                    for row in term_rows
                )
            )

            with exceptions_path.open(
                encoding="utf-8",
                newline="",
            ) as handle:
                exception_rows = list(
                    csv.DictReader(handle, delimiter="\t")
                )
            self.assertEqual(len(exception_rows), 65)
            self.assertTrue(
                all(
                    row["stage"] in {"001", "002", "004", "005"}
                    and row["source_text"]
                    and row["translation"]
                    and row["glossary_exceptions"]
                    and row["notes"]
                    for row in exception_rows
                )
            )


if __name__ == "__main__":
    unittest.main()
