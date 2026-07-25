import unittest

from tools.srwz.corpus import (
    CorpusEntry,
    CorpusError,
    corpus_digest,
    export_corpus,
    text_sha256,
    validate_corpus,
    validate_status_transition,
)


HASH = "1" * 64


def fixture_entry(identifier="menu/SLPS/00/0000"):
    return CorpusEntry(
        entry_id=identifier,
        domain="menu",
        kind="menu",
        source_member="SLPS_258.87",
        source_member_sha256=HASH,
        scope_index=None,
        section="Menu",
        ordinal=0,
        source_text="開始",
        source_text_sha256=text_sha256("開始"),
        provenance={"pointer_offsets": [4]},
    )


class CorpusContractTests(unittest.TestCase):
    def test_validates_source_text_hash_and_status(self):
        entry = fixture_entry()
        self.assertEqual(entry.status, "todo")
        with self.assertRaisesRegex(CorpusError, "requires translation"):
            CorpusEntry(
                **{
                    **entry.__dict__,
                    "status": "reviewed",
                }
            )

    def test_rejects_duplicate_ids(self):
        entry = fixture_entry()
        with self.assertRaisesRegex(CorpusError, "duplicate corpus id"):
            validate_corpus((entry, entry))

    def test_status_transition_is_monotonic_and_runtime_evidenced(self):
        validate_status_transition("draft", "final")
        with self.assertRaisesRegex(CorpusError, "backwards"):
            validate_status_transition("reviewed", "draft")
        with self.assertRaisesRegex(CorpusError, "runtime evidence"):
            validate_status_transition("final", "runtime_verified")
        validate_status_transition(
            "final",
            "runtime_verified",
            runtime_evidence=True,
        )

    def test_digest_is_order_sensitive_and_deterministic(self):
        first = fixture_entry("menu/SLPS/00/0000")
        second = fixture_entry("menu/SLPS/00/0001")
        self.assertEqual(
            corpus_digest((first, second)),
            corpus_digest((first, second)),
        )
        self.assertNotEqual(
            corpus_digest((first, second)),
            corpus_digest((second, first)),
        )

    def test_exports_all_three_domains(self):
        report = {
            "sources": {
                "SLPS_258.87": {"sha256": HASH},
                "COMPDATA.BN": {"sha256": "2" * 64},
                "STAGE.BIN": {"sha256": "3" * 64},
                "MTV_PROS.BIN": {"sha256": "4" * 64},
            },
            "parsed": {
                "menu": [
                    {
                        "friendly_name": "SLPS",
                        "entries": [
                            {
                                "id": "menu/SLPS/00/0000",
                                "section": "Menu",
                                "ordinal": 0,
                                "text": "開始",
                                "pointer_offsets": [4],
                                "target_offsets": [8],
                                "embedded_hi": [],
                                "embedded_lo": [],
                            }
                        ],
                    }
                ],
                "story": [
                    {
                        "stage_index": 1,
                        "entries": [
                            {
                                "id": "story/001/dialogue/01.01/0000",
                                "kind": "dialogue",
                                "section": "Section 1.1",
                                "ordinal": 0,
                                "text": "話",
                                "pointer_offset": 4,
                                "text_offset": 8,
                                "speaker_id": 1,
                            }
                        ],
                    }
                ],
                "summary": [
                    {
                        "chunk_index": 0,
                        "entries": [
                            {
                                "id": "summary/00/000",
                                "section": "Text",
                                "ordinal": 0,
                                "text": "概要",
                                "text_offset": 8,
                                "allocated_length": 16,
                            }
                        ],
                    }
                ],
            },
        }
        entries = export_corpus(report)
        self.assertEqual(len(entries), 3)
        self.assertEqual(
            {entry.domain for entry in entries},
            {"menu", "story", "summary"},
        )


if __name__ == "__main__":
    unittest.main()
