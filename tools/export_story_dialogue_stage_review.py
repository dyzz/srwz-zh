#!/usr/bin/env python3
"""Export one complete SRWZ story stage with translated speaker context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.translation_review import (
    TranslationReviewError,
    load_source_corpus,
    load_translations,
    write_stage_dialogue_source_tsv,
    write_stage_dialogue_unique_draft,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument(
        "--release",
        type=Path,
        default=PROJECT_ROOT / "corpus" / "releases" / "v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "TSV destination under work/; defaults to "
            "work/review/srwz-story-dialogue-stage-NNN-source.tsv"
        ),
    )
    parser.add_argument(
        "--unique-draft-output",
        type=Path,
        help=(
            "optional ignored unique-decision JSON destination under work/"
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _project_path(raw: str) -> Path:
    return (PROJECT_ROOT / raw).resolve()


def main() -> int:
    args = parse_args()
    if args.stage < 0:
        raise TranslationReviewError("--stage must be non-negative")
    release = json.loads(args.release.read_text(encoding="utf-8"))
    source_config = release.get("source_corpus")
    if not isinstance(source_config, dict):
        raise TranslationReviewError("release has no source_corpus object")
    source_path = _project_path(str(source_config.get("path")))
    translation_paths = [
        _project_path(str(raw))
        for raw in release.get("translation_sources", ())
    ]
    output = args.output or (
        WORK_ROOT
        / "review"
        / f"srwz-story-dialogue-stage-{args.stage:03d}-source.tsv"
    )
    output = require_work_output(output, WORK_ROOT)
    source_entries = load_source_corpus(source_path)
    translations = load_translations(translation_paths)
    report = write_stage_dialogue_source_tsv(
        output,
        source_entries,
        translations,
        stage_index=args.stage,
    )
    print(
        f"stage dialogue review: stage={report['stage_index']:03d} "
        f"entries={report['entry_count']} "
        f"unique={report['unique_source_text_count']} "
        f"translated={report['translated_entry_count']}"
    )
    print(f"review TSV: {output}")
    if args.unique_draft_output is not None:
        draft_output = require_work_output(
            args.unique_draft_output,
            WORK_ROOT,
        )
        if draft_output.exists() and not args.force:
            raise TranslationReviewError(
                f"unique draft exists; use --force: {draft_output}"
            )
        draft_report = write_stage_dialogue_unique_draft(
            draft_output,
            source_entries,
            translations,
            stage_index=args.stage,
        )
        print(
            "unique draft: "
            f"unique={draft_report['unique_source_text_count']} "
            f"reviewed={draft_report['reviewed_unique_count']}"
        )
        print(f"unique draft JSON: {draft_output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"stage dialogue review failed: {error}", file=sys.stderr)
        raise SystemExit(1)
