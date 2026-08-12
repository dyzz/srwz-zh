import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tools.build_story_component import (
    _runtime_keyword_catalog,
    _validate_runtime_keywords,
)
from tools.audit_stage_keyword_links import (
    KeywordOccurrence,
    audit_keyword_links,
    load_canonical_keyword_catalog,
    load_original_keyword_entries,
    load_story_keyword_occurrences,
)


class StageKeywordLinkAuditTests(unittest.TestCase):
    def test_original_stage_links_cover_every_unique_kywd_word(self):
        occurrences = load_story_keyword_occurrences()
        original_entries = load_original_keyword_entries()
        linked_source_words = {row.source_word for row in occurrences}

        self.assertEqual(len(occurrences), 122)
        self.assertEqual(len(linked_source_words), 52)
        self.assertEqual(len(original_entries), 52)
        self.assertEqual(linked_source_words, set(original_entries))
        self.assertTrue(
            all(len(indices) == 1 for indices in original_entries.values())
        )
        self.assertEqual(
            {indices[0] for indices in original_entries.values()},
            set(range(52)),
        )

    def test_approved_catalog_matches_original_slots_and_all_story_links(self):
        canonical_words, canonical_entries = load_canonical_keyword_catalog()
        original_entries = load_original_keyword_entries()
        self.assertEqual(canonical_entries, original_entries)
        self.assertEqual(len(canonical_words), 52)

        report = audit_keyword_links(
            load_story_keyword_occurrences(),
            canonical_words,
            original_entries,
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["link_occurrence_count"], 122)
        self.assertEqual(report["matched_occurrence_count"], 122)
        self.assertEqual(report["mismatch_occurrence_count"], 0)

    def test_story_builder_fails_closed_on_runtime_keyword_drift(self):
        config = {
            "path": "corpus/runtime/stage-keywords-v1.json",
            "size": 9710,
            "sha256": "76d6e7e6a48ac336a62301260c6ac5cad9ba13322f092c9061c818a5a0cc4f4e",
        }
        catalog = _runtime_keyword_catalog(config)
        self.assertEqual(
            _validate_runtime_keywords(
                "《コントリズム》の《ジオン・ズム・ダイクン》",
                "《康提主义》的《吉翁·兹姆·戴肯》",
                catalog,
                label="canary",
            ),
            2,
        )
        with self.assertRaisesRegex(SystemExit, "runtime-keyword mismatch"):
            _validate_runtime_keywords(
                "《コントリズム》の《ジオン・ズム・ダイクン》",
                "《吉翁·兹姆·戴肯》的《康提主义》",
                catalog,
                label="swapped-canary",
            )

    def test_exact_runtime_key_match_passes(self):
        occurrences = [
            KeywordOccurrence(1, "story/001/dialogue/02.01/0006", 0, "用語", "术语"),
            KeywordOccurrence(1, "story/001/dialogue/02.01/0007", 0, "用語", "术语"),
        ]
        from hashlib import sha256

        report = audit_keyword_links(
            occurrences,
            {sha256("用語".encode("utf-8")).hexdigest(): "术语"},
            {"用語": (12,)},
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["matched_occurrence_count"], 2)
        self.assertEqual(report["mismatch_occurrence_count"], 0)
        self.assertEqual(report["original_keyword_entry_count"], 1)

    def test_runtime_key_mismatch_is_source_bound(self):
        occurrences = [
            KeywordOccurrence(1, "story/001/dialogue/02.01/0020", 0, "エゥーゴ", "奥古"),
        ]
        from hashlib import sha256

        report = audit_keyword_links(
            occurrences,
            {sha256("エゥーゴ".encode("utf-8")).hexdigest(): "奥古士兵"},
            {"エゥーゴ": (8,)},
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["mismatch_occurrence_count"], 1)
        self.assertEqual(
            report["translation_mismatches"][0]["source_word"],
            "エゥーゴ",
        )
        self.assertEqual(
            report["translation_mismatches"][0]["expected_word"],
            "奥古士兵",
        )
        self.assertEqual(
            report["translation_mismatches"][0]["keyword_entry_indices"],
            [8],
        )

    def test_missing_and_inconsistent_keys_are_separate_failures(self):
        occurrences = [
            KeywordOccurrence(2, "story/002/dialogue/01.01/0001", 0, "語", "词"),
            KeywordOccurrence(3, "story/003/dialogue/01.01/0001", 0, "語", "术语"),
        ]
        report = audit_keyword_links(occurrences, {})
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["missing_library_word_count"], 1)
        self.assertEqual(report["inconsistent_story_word_count"], 1)

    def test_missing_or_ambiguous_original_keyword_slot_fails(self):
        occurrences = [
            KeywordOccurrence(4, "story/004/dialogue/01.01/0001", 0, "甲", "甲"),
            KeywordOccurrence(4, "story/004/dialogue/01.01/0002", 0, "乙", "乙"),
        ]
        from hashlib import sha256

        library_words = {
            sha256(word.encode("utf-8")).hexdigest(): word for word in ("甲", "乙")
        }
        report = audit_keyword_links(
            occurrences,
            library_words,
            {"乙": (2, 3)},
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["missing_original_keyword_word_count"], 1)
        self.assertEqual(report["ambiguous_original_keyword_word_count"], 1)


if __name__ == "__main__":
    unittest.main()
