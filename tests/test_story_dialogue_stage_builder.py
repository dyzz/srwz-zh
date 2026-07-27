import unittest

from tools.build_story_dialogue_stage_translation import (
    build_stage_document,
)
from tools.srwz.translation_review import (
    GlossaryTerm,
    TranslationReviewError,
)


class StoryDialogueStageBuilderTests(unittest.TestCase):
    def setUp(self):
        self.sources = (
            {
                "id": "story/002/dialogue/01.01/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.1",
                "source_text": "「アーモリーワンだ」",
                "source_text_sha256": "a" * 64,
            },
            {
                "id": "story/002/dialogue/01.02/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.2",
                "source_text": "「アーモリーワンだ」",
                "source_text_sha256": "a" * 64,
            },
            {
                "id": "story/002/dialogue/01.02/0001",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.2",
                "source_text": "「………」",
                "source_text_sha256": "b" * 64,
            },
        )
        self.glossary = (
            GlossaryTerm(
                term_id="place/armory-one",
                source_terms=("アーモリーワン",),
                translation="军械库一号",
                category="place",
                status="researched",
                domains=("story",),
                enforce=True,
                notes="",
            ),
            GlossaryTerm(
                term_id="people/ambiguous-armory",
                source_terms=("アーモリーワン",),
                translation="军械库一号",
                category="people",
                status="proposed",
                domains=("story",),
                enforce=False,
                notes="",
            ),
        )

    def test_builds_all_occurrences_from_unique_decisions(self):
        document, records = build_stage_document(
            self.sources,
            self.glossary,
            stage_index=2,
            draft={
                "stage_index": 2,
                "translations": [
                    "“这里是军械库一号”",
                    "“……”",
                ],
                "notes_by_index": {
                    "1": "纯标点演出。",
                },
            },
        )
        self.assertEqual(
            document["scope"],
            {
                "domain": "story",
                "kind": "dialogue",
                "stage_indices": [2],
                "entry_count": 3,
                "unique_source_text_count": 2,
                "translated_entry_count": 3,
                "punctuation_only_entry_count": 1,
            },
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(
            document["entries"][0]["glossary_refs"],
            ["place/armory-one"],
        )
        self.assertEqual(
            document["entries"][0]["translation"],
            document["entries"][1]["translation"],
        )
        self.assertEqual(
            [entry["id"] for entry in document["entries"]],
            [source["id"] for source in self.sources],
        )
        self.assertNotIn("source_text", document["entries"][0])

    def test_non_enforced_term_requires_explicit_auto_reference_policy(self):
        document, _ = build_stage_document(
            self.sources,
            self.glossary,
            stage_index=2,
            draft={
                "stage_index": 2,
                "auto_reference_term_ids": [
                    "people/ambiguous-armory",
                ],
                "translations": [
                    "“这里是军械库一号”",
                    "“……”",
                ],
            },
        )
        self.assertEqual(
            document["entries"][0]["glossary_refs"],
            [
                "people/ambiguous-armory",
                "place/armory-one",
            ],
        )

    def test_supports_reviewed_default_and_per_decision_status(self):
        document, records = build_stage_document(
            self.sources,
            self.glossary,
            stage_index=2,
            draft={
                "stage_index": 2,
                "editorial_status": "reviewed",
                "editorial_status_by_index": {
                    "1": "draft",
                },
                "translations": [
                    "“这里是军械库一号”",
                    "“……”",
                ],
            },
        )
        self.assertEqual(
            [entry["editorial_status"] for entry in document["entries"]],
            ["reviewed", "reviewed", "draft"],
        )
        self.assertEqual(
            [record.editorial_status for record in records],
            ["reviewed", "reviewed", "draft"],
        )

    def test_rejects_invalid_editorial_status(self):
        with self.assertRaisesRegex(
            TranslationReviewError,
            "editorial_status",
        ):
            build_stage_document(
                self.sources,
                self.glossary,
                stage_index=2,
                draft={
                    "stage_index": 2,
                    "editorial_status": "verified",
                    "translations": [
                        "“这里是军械库一号”",
                        "“……”",
                    ],
                },
            )

    def test_masked_dialogue_is_not_counted_as_punctuation_only(self):
        source = (
            {
                "id": "story/002/dialogue/01.01/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.1",
                "source_text": "「●、●●…」",
                "source_text_sha256": "c" * 64,
            },
        )
        document, _ = build_stage_document(
            source,
            (),
            stage_index=2,
            draft={
                "stage_index": 2,
                "translations": ["“●、●●……”"],
            },
        )
        self.assertEqual(
            document["scope"]["punctuation_only_entry_count"],
            0,
        )

    def test_rejects_missing_unique_decision_but_allows_chinese_reflow(self):
        with self.assertRaisesRegex(
            TranslationReviewError,
            "unique translation count",
        ):
            build_stage_document(
                self.sources,
                self.glossary,
                stage_index=2,
                draft={
                    "stage_index": 2,
                    "translations": ["“这里是军械库一号”"],
                },
            )
        changed_line_source = (
            {
                **self.sources[0],
                "source_text": "「第一行\n第二行」",
            },
        )
        document, _ = build_stage_document(
            changed_line_source,
            (),
            stage_index=2,
            draft={
                "stage_index": 2,
                "translations": ["“只有一行”"],
            },
        )
        self.assertEqual(
            document["entries"][0]["translation"],
            "“只有一行”",
        )


if __name__ == "__main__":
    unittest.main()
