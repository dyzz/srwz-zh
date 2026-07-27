import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.translation_review import (
    GlossaryTerm,
    TranslationRecord,
    TranslationReviewError,
    audit_coverage_plan,
    audit_translation_release,
    load_glossary,
    write_dialogue_milestone_exception_tsv,
    write_dialogue_milestone_term_tsv,
    write_glossary_tsv,
    write_review_tsv,
    write_stage_dialogue_source_tsv,
    write_stage_dialogue_unique_draft,
    write_unique_review_tsv,
)


SOURCE_HASH = "a" * 64


def source_entry(text="地球連邦が発足した。"):
    return {
        "id": "summary/00/000",
        "domain": "summary",
        "kind": "summary",
        "scope_index": 0,
        "section": "Text",
        "source_text": text,
        "source_text_sha256": SOURCE_HASH,
    }


def term():
    return GlossaryTerm(
        term_id="organization/earth-federation",
        source_terms=("地球連邦",),
        translation="地球联邦",
        category="organization",
        status="proposed",
        domains=("summary", "story"),
        enforce=True,
        notes="",
    )


def translation(
    text="地球联邦成立了。",
    *,
    source_hash=SOURCE_HASH,
    refs=("organization/earth-federation",),
):
    return TranslationRecord(
        entry_id="summary/00/000",
        source_text_sha256=source_hash,
        translation=text,
        editorial_status="draft",
        translation_action="translate",
        glossary_refs=refs,
        glossary_exceptions=(),
        notes="",
        batch_id="v1-summary",
        source_path="corpus/zh/summary.json",
    )


class TranslationReviewTests(unittest.TestCase):
    def test_loads_item_glossary_category(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parts.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "default_source_match": "token",
                        "terms": [
                            {
                                "id": "part/booster",
                                "source_terms": ["ブースター"],
                                "translation": "推进器",
                                "category": "item",
                                "status": "proposed",
                                "domains": ["menu"],
                                "enforce": True,
                                "notes": "",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = load_glossary((path,))
            self.assertEqual(loaded[0].category, "item")
            self.assertEqual(loaded[0].source_match, "token")

    def test_loads_weapon_glossary_category(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weapons.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "default_source_match": "token",
                        "terms": [
                            {
                                "id": "weapon/0001",
                                "source_terms": ["ロケットパンチ"],
                                "translation": "火箭飞拳",
                                "category": "weapon",
                                "status": "proposed",
                                "domains": ["menu"],
                                "enforce": True,
                                "notes": "",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = load_glossary((path,))
            self.assertEqual(loaded[0].category, "weapon")
            self.assertEqual(loaded[0].source_match, "token")

    def test_accepts_reconciled_translation_and_term(self):
        report = audit_translation_release(
            (source_entry(),),
            (translation(),),
            (term(),),
        )
        self.assertEqual(report["translation_entry_count"], 1)
        self.assertEqual(report["glossary_referenced_term_count"], 1)

    def test_coverage_plan_must_cover_source_exactly(self):
        plan = [
            {
                "batch_id": "v1-summary",
                "domain": "summary",
                "target_entry_count": 1,
                "status": "draft_complete",
            }
        ]
        report = audit_coverage_plan(
            plan,
            (source_entry(),),
            (translation(),),
        )
        self.assertEqual(report["coverage_batch_count"], 1)
        with self.assertRaisesRegex(
            TranslationReviewError,
            "complete batch has 0/1",
        ):
            audit_coverage_plan(plan, (source_entry(),), ())

    def test_rejects_stale_source_hash(self):
        with self.assertRaisesRegex(
            TranslationReviewError,
            "stale source text",
        ):
            audit_translation_release(
                (source_entry(),),
                (translation(source_hash="b" * 64),),
                (term(),),
            )

    def test_rejects_missing_enforced_glossary_reference(self):
        with self.assertRaisesRegex(
            TranslationReviewError,
            "missing enforced glossary ref",
        ):
            audit_translation_release(
                (source_entry(),),
                (translation(refs=()),),
                (term(),),
            )

    def test_accepts_explicit_glossary_exception_for_split_phrase(self):
        split_translation = TranslationRecord(
            **{
                **translation(text="尚有", refs=()).__dict__,
                "glossary_exceptions": (
                    "organization/earth-federation",
                ),
                "notes": "术语移至运行时拼接的后一片段。",
            }
        )
        report = audit_translation_release(
            (source_entry(),),
            (split_translation,),
            (term(),),
        )
        self.assertEqual(report["glossary_exception_count"], 1)

    def test_rejects_invalid_or_overlapping_glossary_exception(self):
        with self.assertRaisesRegex(
            TranslationReviewError,
            "refs and exceptions overlap",
        ):
            audit_translation_release(
                (source_entry(),),
                (
                    TranslationRecord(
                        **{
                            **translation().__dict__,
                            "glossary_exceptions": (
                                "organization/earth-federation",
                            ),
                        }
                    ),
                ),
                (term(),),
            )
        with self.assertRaisesRegex(
            TranslationReviewError,
            "does not occur in source text",
        ):
            audit_translation_release(
                (source_entry("別の文章"),),
                (
                    TranslationRecord(
                        **{
                            **translation(text="另一句话", refs=()).__dict__,
                            "glossary_exceptions": (
                                "organization/earth-federation",
                            ),
                        }
                    ),
                ),
                (term(),),
            )

    def test_rejects_noncanonical_term_and_kana_residue(self):
        with self.assertRaises(TranslationReviewError) as raised:
            audit_translation_release(
                (source_entry(),),
                (translation(text="联邦ガ成立了。"),),
                (term(),),
            )
        self.assertIn("Japanese kana", str(raised.exception))
        self.assertIn("canonical translation", str(raised.exception))

    def test_accepts_japanese_middle_dot_as_chinese_ui_punctuation(self):
        report = audit_translation_release(
            (source_entry(),),
            (translation(text="・地球联邦"),),
            (term(),),
        )
        self.assertEqual(report["translation_entry_count"], 1)

    def test_token_glossary_match_rejects_compound_false_positive(self):
        token_term = GlossaryTerm(
            **{
                **term().__dict__,
                "source_terms": ("愛",),
                "translation": "爱",
                "source_match": "token",
            }
        )
        report = audit_translation_release(
            (source_entry("愛称"),),
            (translation(text="昵称", refs=()),),
            (token_term,),
        )
        self.assertEqual(report["glossary_reference_count"], 0)
        quoted = source_entry("「愛」が同時にかかる。")
        with self.assertRaisesRegex(
            TranslationReviewError,
            "missing enforced glossary ref",
        ):
            audit_translation_release(
                (quoted,),
                (translation(text="同时生效。", refs=()),),
                (token_term,),
            )

    def test_rejects_changed_structural_and_format_tokens(self):
        with self.assertRaisesRegex(
            TranslationReviewError,
            "structural/control token set changed",
        ):
            audit_translation_release(
                (source_entry("地球連邦：%s @<color:31>"),),
                (translation(text="地球联邦：%d"),),
                (term(),),
            )

    def test_rejects_changed_player_name_and_censorship_tokens(self):
        with self.assertRaisesRegex(
            TranslationReviewError,
            "structural/control token set changed",
        ):
            audit_translation_release(
                (source_entry("$F少尉、●●"),),
                (translation(text="$n少尉、●"),),
                (),
            )

    def test_preserve_action_accepts_empty_source_and_rejects_changes(self):
        empty_source = source_entry("")
        preserved = TranslationRecord(
            **{
                **translation(text="", refs=()).__dict__,
                "translation_action": "preserve",
            }
        )
        report = audit_translation_release(
            (empty_source,),
            (preserved,),
            (),
        )
        self.assertEqual(report["translation_entry_count"], 1)
        with self.assertRaisesRegex(
            TranslationReviewError,
            "preserve decision differs",
        ):
            audit_translation_release(
                (empty_source,),
                (
                    TranslationRecord(
                        **{
                            **preserved.__dict__,
                            "translation": " ",
                        }
                    ),
                ),
                (),
            )

    def test_writes_bilingual_review_tsv_under_requested_path(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "review.tsv"
            write_review_tsv(
                output,
                (source_entry(),),
                (translation(),),
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn(
                "id\tbatch_id\tdomain\tkind\tscope_index\tsection",
                text,
            )
            self.assertIn(
                "v1-summary\tsummary\tsummary",
                text,
            )
            self.assertIn(
                "地球連邦が発足した。\t地球联邦成立了。\ttranslate",
                text,
            )

    def test_writes_glossary_review_tsv_with_usage_count(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "glossary.tsv"
            write_glossary_tsv(
                output,
                (term(),),
                (translation(),),
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn("reference_count", text)
            self.assertIn(
                "地球連邦\t地球联邦\torganization\tproposed\tsubstring",
                text,
            )
            self.assertIn("\t1\t0\t", text)

    def test_writes_focused_dialogue_term_queue_with_conflict_marker(self):
        source = {
            "id": "story/002/dialogue/01.01/0000",
            "domain": "story",
            "kind": "dialogue",
            "scope_index": 2,
            "section": "Section 1.1",
            "source_text": "「ソードを選択する」",
            "source_text_sha256": "b" * 64,
            "provenance": {"speaker_id": 7},
        }
        stage_term = GlossaryTerm(
            term_id="unit/sword-module",
            source_terms=("ソード",),
            translation="巨剑型",
            category="unit",
            status="proposed",
            domains=("story",),
            enforce=False,
            notes="脉冲高达模块短称。",
        )
        generic_term = GlossaryTerm(
            term_id="weapon/sword",
            source_terms=("ソード",),
            translation="剑",
            category="weapon",
            status="proposed",
            domains=("menu",),
            enforce=False,
            notes="普通武器名称。",
        )
        dialogue = TranslationRecord(
            entry_id=source["id"],
            source_text_sha256=source["source_text_sha256"],
            translation="“选择巨剑型”",
            editorial_status="draft",
            translation_action="translate",
            glossary_refs=(stage_term.term_id,),
            glossary_exceptions=(),
            notes="",
            batch_id="v1-story-dialogue",
            source_path="corpus/zh/story-dialogue/stage-002.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "terms.tsv"
            report = write_dialogue_milestone_term_tsv(
                output,
                (source,),
                (dialogue,),
                (stage_term, generic_term),
                term_origins={
                    stage_term.term_id: (
                        2,
                        "corpus/glossary/story-dialogue-stage-002-v1.json",
                    )
                },
                stage_indices=(2,),
            )
            self.assertEqual(report["term_count"], 1)
            self.assertEqual(report["proposed_term_count"], 1)
            self.assertEqual(report["translation_conflict_term_count"], 1)
            with output.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(rows[0]["review_priority"], "high")
            self.assertEqual(rows[0]["origin_stage"], "002")
            self.assertEqual(rows[0]["reference_count"], "1")
            self.assertIn("weapon/sword=剑", rows[0]["same_source_terms"])
            self.assertIn(
                "weapon/sword=剑",
                rows[0]["translation_conflicts"],
            )

    def test_writes_dialogue_exception_queue_with_speaker_and_reason(self):
        source = {
            "id": "story/005/dialogue/02.02/0040",
            "domain": "story",
            "kind": "dialogue",
            "scope_index": 5,
            "section": "Section 2.2",
            "source_text": "「極東で捕獲された」",
            "source_text_sha256": "b" * 64,
            "provenance": {"speaker_id": 3},
        }
        speaker = TranslationRecord(
            entry_id="story/005/speaker/003",
            source_text_sha256="c" * 64,
            translation="雷",
            editorial_status="draft",
            translation_action="translate",
            glossary_refs=(),
            glossary_exceptions=(),
            notes="",
            batch_id="v1-story-speakers",
            source_path="corpus/zh/story-speakers.json",
        )
        dialogue = TranslationRecord(
            entry_id=source["id"],
            source_text_sha256=source["source_text_sha256"],
            translation="“在远东地区被捕获”",
            editorial_status="draft",
            translation_action="translate",
            glossary_refs=(),
            glossary_exceptions=("skill/extreme",),
            notes="“極”是方位词内部字符，并非技能名。",
            batch_id="v1-story-dialogue",
            source_path="corpus/zh/story-dialogue/stage-005.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "exceptions.tsv"
            report = write_dialogue_milestone_exception_tsv(
                output,
                (source,),
                (speaker, dialogue),
                stage_indices=(5,),
            )
            self.assertEqual(report["record_count"], 1)
            self.assertEqual(
                report["exception_counts"],
                {"skill/extreme": 1},
            )
            with output.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(rows[0]["stage"], "005")
            self.assertEqual(rows[0]["speaker_zh"], "雷")
            self.assertEqual(rows[0]["glossary_exceptions"], "skill/extreme")
            self.assertIn("方位词", rows[0]["notes"])

            without_reason = TranslationRecord(
                **{
                    **dialogue.__dict__,
                    "notes": "",
                }
            )
            with self.assertRaisesRegex(
                TranslationReviewError,
                "needs review notes",
            ):
                write_dialogue_milestone_exception_tsv(
                    output,
                    (source,),
                    (speaker, without_reason),
                    stage_indices=(5,),
                )

    def test_writes_unique_batch_review_tsv_with_occurrence_count(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "unique.tsv"
            first = translation()
            second = TranslationRecord(
                **{
                    **first.__dict__,
                    "entry_id": "summary/00/001",
                }
            )
            source_two = {
                **source_entry(),
                "id": "summary/00/001",
            }
            write_unique_review_tsv(
                output,
                (source_entry(), source_two),
                (first, second),
                batch_id="v1-summary",
            )
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("occurrence_count", lines[0])
            self.assertIn(
                "\t2\tsummary/00/000\tsummary/00/001\t",
                lines[1],
            )

    def test_writes_complete_stage_dialogue_with_speaker_context(self):
        source = (
            {
                "id": "story/002/dialogue/01.01/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.1",
                "source_text": "「報告しろ！」",
                "source_text_sha256": "b" * 64,
                "provenance": {"speaker_id": 7},
            },
        )
        speaker = TranslationRecord(
            entry_id="story/002/speaker/007",
            source_text_sha256="c" * 64,
            translation="露娜玛丽亚",
            editorial_status="draft",
            translation_action="translate",
            glossary_refs=("people/lunamaria",),
            glossary_exceptions=(),
            notes="",
            batch_id="v1-story-speakers",
            source_path="corpus/zh/story-speakers.json",
        )
        dialogue = TranslationRecord(
            entry_id="story/002/dialogue/01.01/0000",
            source_text_sha256="b" * 64,
            translation="“快报告！”",
            editorial_status="draft",
            translation_action="translate",
            glossary_refs=(),
            glossary_exceptions=(),
            notes="",
            batch_id="v1-story-dialogue",
            source_path="corpus/zh/story-dialogue/stage-002.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stage.tsv"
            report = write_stage_dialogue_source_tsv(
                output,
                source,
                (speaker, dialogue),
                stage_index=2,
            )
            self.assertEqual(
                report,
                {
                    "stage_index": 2,
                    "entry_count": 1,
                    "unique_source_text_count": 1,
                    "translated_entry_count": 1,
                },
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn(
                "id\tunique_index\tsection\tspeaker_id\t"
                "speaker_zh\tsource_text\t"
                "source_text_sha256\ttranslation",
                text,
            )
            self.assertIn(
                "\t7\t露娜玛丽亚\t「報告しろ！」\t"
                + "b" * 64
                + "\t“快报告！”\ttranslate\tdraft",
                text,
            )

    def test_reconstructs_unique_stage_draft_with_review_status(self):
        source = (
            {
                "id": "story/002/dialogue/01.01/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.1",
                "source_text": "「報告しろ！」",
                "source_text_sha256": "b" * 64,
                "provenance": {"speaker_id": 7},
            },
        )
        dialogue = TranslationRecord(
            entry_id="story/002/dialogue/01.01/0000",
            source_text_sha256="b" * 64,
            translation="“快报告！”",
            editorial_status="reviewed",
            translation_action="translate",
            glossary_refs=("system/report",),
            glossary_exceptions=(),
            notes="逐句复核。",
            batch_id="v1-story-dialogue",
            source_path="corpus/zh/story-dialogue/stage-002.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stage.json"
            report = write_stage_dialogue_unique_draft(
                output,
                source,
                (dialogue,),
                stage_index=2,
            )
            self.assertEqual(
                report,
                {
                    "stage_index": 2,
                    "entry_count": 1,
                    "unique_source_text_count": 1,
                    "reviewed_unique_count": 1,
                },
            )
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["translations"], ["“快报告！”"])
            self.assertEqual(
                document["editorial_status_by_index"],
                {"0": "reviewed"},
            )
            self.assertEqual(
                document["glossary_refs_by_index"],
                {"0": ["system/report"]},
            )
            self.assertEqual(
                document["notes_by_index"],
                {"0": "逐句复核。"},
            )

    def test_stage_dialogue_export_rejects_missing_speaker_translation(self):
        source = (
            {
                "id": "story/002/dialogue/01.01/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.1",
                "source_text": "「報告しろ！」",
                "source_text_sha256": "b" * 64,
                "provenance": {"speaker_id": 7},
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                TranslationReviewError,
                "untranslated speaker slots",
            ):
                write_stage_dialogue_source_tsv(
                    Path(directory) / "stage.tsv",
                    source,
                    (),
                    stage_index=2,
                )


if __name__ == "__main__":
    unittest.main()
