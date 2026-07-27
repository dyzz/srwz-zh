#!/usr/bin/env python3
"""Build one committed SRWZ story-dialogue stage from an ignored draft."""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Mapping, Sequence

try:
    from srwz.translation_review import (
        GlossaryTerm,
        TranslationRecord,
        TranslationReviewError,
        VALID_EDITORIAL_STATUSES,
        audit_translation_release,
        load_glossary,
        load_source_corpus,
        term_occurs,
    )
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.srwz.translation_review import (
        GlossaryTerm,
        TranslationRecord,
        TranslationReviewError,
        VALID_EDITORIAL_STATUSES,
        audit_translation_release,
        load_glossary,
        load_source_corpus,
        term_occurs,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
TRANSLATION_ROOT = PROJECT_ROOT / "corpus" / "zh" / "story-dialogue"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument(
        "--release",
        type=Path,
        default=PROJECT_ROOT / "corpus" / "releases" / "v1.json",
    )
    parser.add_argument(
        "--draft",
        type=Path,
        help=(
            "ignored unique-decision JSON; defaults to "
            "work/review/story-dialogue-stage-NNN-unique-draft.json"
        ),
    )
    parser.add_argument(
        "--additional-glossary",
        action="append",
        type=Path,
        default=[],
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "committed translation JSON; defaults to "
            "corpus/zh/story-dialogue/stage-NNN.json"
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _project_path(raw: str) -> Path:
    return (PROJECT_ROOT / raw).resolve()


def _bounded_path(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise TranslationReviewError(
            f"{label} must stay under {root.resolve()}"
        ) from error
    return resolved


def _index_mapping(
    draft: Mapping[str, object],
    field: str,
    unique_count: int,
) -> dict[int, object]:
    raw = draft.get(field, {})
    if not isinstance(raw, dict):
        raise TranslationReviewError(f"draft {field} must be an object")
    parsed = {}
    for key, value in raw.items():
        try:
            index = int(key)
        except (TypeError, ValueError) as error:
            raise TranslationReviewError(
                f"draft {field} key {key!r} is not an integer"
            ) from error
        if str(index) != str(key) or not 0 <= index < unique_count:
            raise TranslationReviewError(
                f"draft {field} key {key!r} is out of range"
            )
        parsed[index] = value
    return parsed


def _is_punctuation_only(source_text: str) -> bool:
    content = source_text.translate(
        str.maketrans("", "", "「」『』（）()　 \t\r\n")
    )
    return (
        bool(content)
        and "●" not in content
        and not any(character.isalnum() for character in content)
    )


def build_stage_document(
    source_entries: Sequence[Mapping[str, object]],
    glossary: Sequence[GlossaryTerm],
    *,
    stage_index: int,
    draft: Mapping[str, object],
) -> tuple[dict, tuple[TranslationRecord, ...]]:
    if stage_index < 0:
        raise TranslationReviewError("stage_index must be non-negative")
    if draft.get("stage_index") != stage_index:
        raise TranslationReviewError(
            "draft stage_index does not match requested stage"
        )
    stage_sources = [
        entry
        for entry in source_entries
        if entry.get("domain") == "story"
        and entry.get("kind") == "dialogue"
        and entry.get("scope_index") == stage_index
    ]
    if not stage_sources:
        raise TranslationReviewError(
            f"source corpus has no story dialogue for stage {stage_index:03d}"
        )

    groups: OrderedDict[str, list[Mapping[str, object]]] = OrderedDict()
    for source in stage_sources:
        source_hash = str(source["source_text_sha256"])
        groups.setdefault(source_hash, []).append(source)
    raw_translations = draft.get("translations")
    if not isinstance(raw_translations, list) or not all(
        isinstance(translation, str) and translation
        for translation in raw_translations
    ):
        raise TranslationReviewError(
            "draft translations must be an array of non-empty strings"
        )
    if len(raw_translations) != len(groups):
        raise TranslationReviewError(
            "draft unique translation count does not match source corpus: "
            f"{len(raw_translations)}/{len(groups)}"
        )

    notes = _index_mapping(draft, "notes_by_index", len(groups))
    explicit_refs = _index_mapping(
        draft,
        "glossary_refs_by_index",
        len(groups),
    )
    explicit_exceptions = _index_mapping(
        draft,
        "glossary_exceptions_by_index",
        len(groups),
    )
    editorial_statuses = _index_mapping(
        draft,
        "editorial_status_by_index",
        len(groups),
    )
    default_editorial_status = draft.get("editorial_status", "draft")
    if default_editorial_status not in VALID_EDITORIAL_STATUSES:
        raise TranslationReviewError(
            "draft editorial_status must be one of "
            f"{VALID_EDITORIAL_STATUSES!r}"
        )
    for index, status in editorial_statuses.items():
        if status not in VALID_EDITORIAL_STATUSES:
            raise TranslationReviewError(
                f"draft editorial_status_by_index[{index}] must be one of "
                f"{VALID_EDITORIAL_STATUSES!r}"
            )
    term_by_id = {term.term_id: term for term in glossary}
    raw_auto_reference_ids = draft.get("auto_reference_term_ids", [])
    if not isinstance(raw_auto_reference_ids, list) or not all(
        isinstance(term_id, str) and term_id
        for term_id in raw_auto_reference_ids
    ):
        raise TranslationReviewError(
            "draft auto_reference_term_ids must be an array of term ids"
        )
    unknown_auto_reference_ids = sorted(
        set(raw_auto_reference_ids) - set(term_by_id)
    )
    if unknown_auto_reference_ids:
        raise TranslationReviewError(
            "draft auto_reference_term_ids has unknown ids: "
            f"{unknown_auto_reference_ids!r}"
        )
    auto_reference_ids = set(raw_auto_reference_ids)
    entries = []
    records = []
    for index, ((source_hash, group), translation) in enumerate(
        zip(groups.items(), raw_translations)
    ):
        editorial_status = editorial_statuses.get(
            index,
            default_editorial_status,
        )
        source_text = str(group[0]["source_text"])
        refs = {
            term.term_id
            for term in glossary
            if (term.enforce or term.term_id in auto_reference_ids)
            and "story" in term.domains
            and term_occurs(term, source_text)
            and term.translation in translation
        }
        raw_refs = explicit_refs.get(index, [])
        raw_exceptions = explicit_exceptions.get(index, [])
        for field, raw in (
            ("glossary_refs_by_index", raw_refs),
            ("glossary_exceptions_by_index", raw_exceptions),
        ):
            if not isinstance(raw, list) or not all(
                isinstance(term_id, str) and term_id for term_id in raw
            ):
                raise TranslationReviewError(
                    f"draft {field}[{index}] must be an array of term ids"
                )
            unknown = sorted(set(raw) - set(term_by_id))
            if unknown:
                raise TranslationReviewError(
                    f"draft {field}[{index}] has unknown ids: {unknown!r}"
                )
        refs.update(raw_refs)
        exceptions = set(raw_exceptions)
        if refs & exceptions:
            raise TranslationReviewError(
                f"draft index {index}: refs and exceptions overlap"
            )
        note = notes.get(index, "")
        if not isinstance(note, str):
            raise TranslationReviewError(
                f"draft notes_by_index[{index}] must be a string"
            )

        for source in group:
            entry = {
                "id": source["id"],
                "source_text_sha256": source_hash,
                "translation": translation,
                "editorial_status": editorial_status,
                "translation_action": "translate",
                "glossary_refs": sorted(refs),
                "notes": note,
            }
            if exceptions:
                entry["glossary_exceptions"] = sorted(exceptions)
            entries.append(entry)
            records.append(
                TranslationRecord(
                    entry_id=str(source["id"]),
                    source_text_sha256=source_hash,
                    translation=translation,
                    editorial_status=editorial_status,
                    translation_action="translate",
                    glossary_refs=tuple(sorted(refs)),
                    glossary_exceptions=tuple(sorted(exceptions)),
                    notes=note,
                    batch_id="v1-story-dialogue",
                    source_path=(
                        f"corpus/zh/story-dialogue/"
                        f"stage-{stage_index:03d}.json"
                    ),
                )
            )

    source_order = {
        str(source["id"]): index
        for index, source in enumerate(stage_sources)
    }
    entries.sort(key=lambda entry: source_order[str(entry["id"])])
    records.sort(key=lambda record: source_order[record.entry_id])
    audit_translation_release(stage_sources, tuple(records), glossary)
    document = {
        "schema_version": 1,
        "batch_id": "v1-story-dialogue",
        "language": "zh-Hans",
        "scope": {
            "domain": "story",
            "kind": "dialogue",
            "stage_indices": [stage_index],
            "entry_count": len(entries),
            "unique_source_text_count": len(groups),
            "translated_entry_count": len(entries),
            "punctuation_only_entry_count": sum(
                _is_punctuation_only(str(source["source_text"]))
                for source in stage_sources
            ),
        },
        "entries": entries,
    }
    return document, tuple(records)


def main() -> int:
    args = parse_args()
    if args.stage < 0:
        raise TranslationReviewError("--stage must be non-negative")
    release = json.loads(args.release.read_text(encoding="utf-8"))
    source_config = release.get("source_corpus")
    if not isinstance(source_config, dict):
        raise TranslationReviewError("release has no source_corpus object")
    source_path = _project_path(str(source_config.get("path")))
    glossary_paths = [
        _project_path(str(raw))
        for raw in release.get("glossary_sources", ())
    ]
    for additional_path in args.additional_glossary:
        resolved = additional_path.resolve()
        if resolved not in glossary_paths:
            glossary_paths.append(resolved)
    draft_path = args.draft or (
        WORK_ROOT
        / "review"
        / f"story-dialogue-stage-{args.stage:03d}-unique-draft.json"
    )
    draft_path = _bounded_path(draft_path, WORK_ROOT, label="draft")
    output = args.output or (
        TRANSLATION_ROOT / f"stage-{args.stage:03d}.json"
    )
    output = _bounded_path(output, TRANSLATION_ROOT, label="output")
    if output.exists() and not args.force:
        raise TranslationReviewError(f"output exists; use --force: {output}")

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        raise TranslationReviewError("draft root must be an object")
    document, _ = build_stage_document(
        load_source_corpus(source_path),
        load_glossary(glossary_paths),
        stage_index=args.stage,
        draft=draft,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    scope = document["scope"]
    print(
        f"story dialogue translation: stage={args.stage:03d} "
        f"entries={scope['entry_count']} "
        f"unique={scope['unique_source_text_count']} "
        f"punctuation_only={scope['punctuation_only_entry_count']}"
    )
    print(f"translation JSON: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"story dialogue build failed: {error}", file=sys.stderr)
        raise SystemExit(1)
