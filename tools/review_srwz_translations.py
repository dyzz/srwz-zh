#!/usr/bin/env python3
"""Validate one SRWZ translation release and build its local review sheet."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.translation_review import (
    TranslationReviewError,
    audit_coverage_plan,
    audit_translation_release,
    load_glossary,
    load_source_corpus,
    load_translations,
    source_corpus_sha256,
    write_dialogue_milestone_exception_tsv,
    write_dialogue_milestone_term_tsv,
    write_glossary_tsv,
    write_review_tsv,
    write_terminology_variant_tsv,
    write_unique_review_tsv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DIALOGUE_GLOSSARY_PATTERN = re.compile(
    r"story-dialogue-stage-(\d{3})-v1\.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release",
        type=Path,
        default=PROJECT_ROOT / "corpus" / "releases" / "v1.json",
    )
    parser.add_argument(
        "--tsv-output",
        type=Path,
        default=WORK_ROOT / "review" / "srwz-translation-v1.tsv",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=WORK_ROOT / "review" / "srwz-translation-v1-report.json",
    )
    parser.add_argument(
        "--glossary-tsv-output",
        type=Path,
        default=WORK_ROOT / "review" / "srwz-glossary-v1.tsv",
    )
    parser.add_argument(
        "--speaker-tsv-output",
        type=Path,
        default=WORK_ROOT / "review" / "srwz-story-speakers-v1.tsv",
    )
    parser.add_argument(
        "--dialogue-tsv-output",
        type=Path,
        default=WORK_ROOT / "review" / "srwz-story-dialogue-v1.tsv",
    )
    parser.add_argument(
        "--dialogue-term-tsv-output",
        type=Path,
        default=(
            WORK_ROOT
            / "review"
            / "srwz-story-dialogue-milestone-terms.tsv"
        ),
    )
    parser.add_argument(
        "--dialogue-exception-tsv-output",
        type=Path,
        default=(
            WORK_ROOT
            / "review"
            / "srwz-story-dialogue-milestone-exceptions.tsv"
        ),
    )
    parser.add_argument(
        "--terminology-variant-review",
        type=Path,
        default=(
            PROJECT_ROOT
            / "corpus"
            / "review"
            / "first-five-official-variants-v1.json"
        ),
    )
    parser.add_argument(
        "--terminology-variant-tsv-output",
        type=Path,
        default=(
            WORK_ROOT
            / "review"
            / "srwz-first-five-official-variants.tsv"
        ),
    )
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def _path(raw: str) -> Path:
    path = PROJECT_ROOT / raw
    return path.resolve()


def main() -> int:
    args = parse_args()
    release = json.loads(args.release.read_text(encoding="utf-8"))
    if release.get("schema_version") != 1:
        raise TranslationReviewError("unsupported release schema")
    source_config = release.get("source_corpus")
    if not isinstance(source_config, dict):
        raise TranslationReviewError("release has no source_corpus object")
    source_path = _path(str(source_config.get("path")))
    expected_hash = str(source_config.get("aggregate_sha256"))
    actual_hash = source_corpus_sha256(source_path)
    if actual_hash != expected_hash:
        raise TranslationReviewError(
            "source corpus aggregate SHA-256 does not match release"
        )
    translation_paths = [
        _path(str(raw)) for raw in release.get("translation_sources", ())
    ]
    glossary_paths = [
        _path(str(raw)) for raw in release.get("glossary_sources", ())
    ]
    source_entries = load_source_corpus(source_path)
    translations = load_translations(translation_paths)
    glossary = load_glossary(glossary_paths)
    report = audit_translation_release(
        source_entries,
        translations,
        glossary,
    )
    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    dialogue_stage_indices = sorted(
        {
            int(source_by_id[record.entry_id]["scope_index"])
            for record in translations
            if record.batch_id == "v1-story-dialogue"
            and source_by_id[record.entry_id].get("domain") == "story"
            and source_by_id[record.entry_id].get("kind") == "dialogue"
        }
    )
    dialogue_term_origins = {}
    for glossary_path in glossary_paths:
        match = DIALOGUE_GLOSSARY_PATTERN.fullmatch(glossary_path.name)
        if match is None:
            continue
        stage_index = int(match.group(1))
        if stage_index not in dialogue_stage_indices:
            continue
        relative_path = str(glossary_path.relative_to(PROJECT_ROOT))
        for term in load_glossary((glossary_path,)):
            dialogue_term_origins[term.term_id] = (
                stage_index,
                relative_path,
            )
    report.update(
        audit_coverage_plan(
            release.get("coverage_plan"),
            source_entries,
            translations,
        )
    )
    report.update(
        {
            "release_id": release.get("release_id"),
            "release_status": release.get("status"),
            "source_corpus_sha256": actual_hash,
            "translation_sources": [
                str(path.relative_to(PROJECT_ROOT))
                for path in translation_paths
            ],
            "glossary_sources": [
                str(path.relative_to(PROJECT_ROOT))
                for path in glossary_paths
            ],
        }
    )
    if not args.check_only:
        tsv_output = require_work_output(args.tsv_output, WORK_ROOT)
        glossary_tsv_output = require_work_output(
            args.glossary_tsv_output,
            WORK_ROOT,
        )
        speaker_tsv_output = require_work_output(
            args.speaker_tsv_output,
            WORK_ROOT,
        )
        dialogue_tsv_output = require_work_output(
            args.dialogue_tsv_output,
            WORK_ROOT,
        )
        dialogue_term_tsv_output = require_work_output(
            args.dialogue_term_tsv_output,
            WORK_ROOT,
        )
        dialogue_exception_tsv_output = require_work_output(
            args.dialogue_exception_tsv_output,
            WORK_ROOT,
        )
        terminology_variant_tsv_output = require_work_output(
            args.terminology_variant_tsv_output,
            WORK_ROOT,
        )
        report_output = require_work_output(args.report_output, WORK_ROOT)
        write_review_tsv(tsv_output, source_entries, translations)
        write_glossary_tsv(
            glossary_tsv_output,
            glossary,
            translations,
        )
        write_unique_review_tsv(
            speaker_tsv_output,
            source_entries,
            translations,
            batch_id="v1-story-speakers",
        )
        write_unique_review_tsv(
            dialogue_tsv_output,
            source_entries,
            translations,
            batch_id="v1-story-dialogue",
        )
        milestone_terms = write_dialogue_milestone_term_tsv(
            dialogue_term_tsv_output,
            source_entries,
            translations,
            glossary,
            term_origins=dialogue_term_origins,
            stage_indices=dialogue_stage_indices,
        )
        milestone_exceptions = write_dialogue_milestone_exception_tsv(
            dialogue_exception_tsv_output,
            source_entries,
            translations,
            stage_indices=dialogue_stage_indices,
        )
        terminology_variant_review = json.loads(
            args.terminology_variant_review.read_text(encoding="utf-8")
        )
        if not isinstance(terminology_variant_review, dict):
            raise TranslationReviewError(
                "terminology variant review root must be an object"
            )
        terminology_variants = write_terminology_variant_tsv(
            terminology_variant_tsv_output,
            terminology_variant_review,
            source_entries,
            translations,
            glossary,
        )
        report["dialogue_milestone_review"] = {
            "terms": milestone_terms,
            "exceptions": milestone_exceptions,
            "official_variants": terminology_variants,
        }
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"review TSV: {tsv_output}")
        print(f"glossary TSV: {glossary_tsv_output}")
        print(f"speaker TSV: {speaker_tsv_output}")
        print(f"dialogue TSV: {dialogue_tsv_output}")
        print(f"dialogue term TSV: {dialogue_term_tsv_output}")
        print(f"dialogue exception TSV: {dialogue_exception_tsv_output}")
        print(f"official variant TSV: {terminology_variant_tsv_output}")
        print(f"review report: {report_output}")
    print(
        "translation review: "
        f"entries={report['translation_entry_count']}/"
        f"{report['source_entry_count']} "
        f"glossary={report['glossary_term_count']} "
        f"errors=0"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"translation review failed: {error}", file=sys.stderr)
        raise SystemExit(1)
