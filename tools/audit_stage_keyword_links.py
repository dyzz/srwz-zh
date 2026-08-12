#!/usr/bin/env python3
"""Audit native STAGE glossary links against approved runtime keyword keys.

SRWZ stores glossary links as invisible 0x8173/0x8174 delimiters around a
visible term in STAGE dialogue.  The delimited text must exactly equal the
localized WORD field in DATA/MTVZKNKW.BIN; an editorial glossary reference is
not a runtime substitute for that byte-level key.

This command is read-only.  It reconstructs Japanese link terms from the
locked original STAGE, pairs them positionally with the translated spans, and
joins those source terms to the approved 52-slot runtime-keyword catalog by
immutable Japanese source hash.  The independently produced LIBRARY corpus is
reported as a secondary alignment check; it is not allowed to redefine the
runtime key used by dialogue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
for import_root in (PROJECT_ROOT, TOOLS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tools.build_story_component import (  # noqa: E402
    _json,
    _locked_file,
    _project_path,
    _read_iso_member,
)
from srwz.codec import decode_production as decode  # noqa: E402
from srwz.iso_layout import (  # noqa: E402
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.library import parse_zkn_decoded_chunk  # noqa: E402
from srwz.stage import parse_stage, read_stage_function_addresses  # noqa: E402
from srwz.text import load_text_table  # noqa: E402


DEFAULT_STORY_CONFIG = PROJECT_ROOT / "config/story-component.json"
DEFAULT_LIBRARY_CONFIG = (
    PROJECT_ROOT / "config/library/v0.2-reviewed-writeback.json"
)
DEFAULT_CANONICAL_KEYWORDS = (
    PROJECT_ROOT / "corpus/runtime/stage-keywords-v1.json"
)
DEFAULT_REPORT = PROJECT_ROOT / "work/review/stage-keyword-link-audit.json"
KEYWORD_MEMBER = "DATA/MTVZKNKW.BIN"


class StageKeywordAuditError(ValueError):
    """The source, translation, or LIBRARY identity contract drifted."""


@dataclass(frozen=True)
class KeywordOccurrence:
    stage_index: int
    entry_id: str
    span_index: int
    source_word: str
    translated_word: str


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keyword_spans(text: str, *, label: str) -> tuple[str, ...]:
    spans: list[str] = []
    opened_at: int | None = None
    for index, character in enumerate(text):
        if character == "《":
            if opened_at is not None:
                raise StageKeywordAuditError(
                    f"{label} has nested keyword start at character {index}"
                )
            opened_at = index
        elif character == "》":
            if opened_at is None:
                raise StageKeywordAuditError(
                    f"{label} has unmatched keyword end at character {index}"
                )
            if index == opened_at + 1:
                raise StageKeywordAuditError(f"{label} has an empty keyword span")
            spans.append(text[opened_at + 1 : index])
            opened_at = None
    if opened_at is not None:
        raise StageKeywordAuditError(
            f"{label} has unmatched keyword start at character {opened_at}"
        )
    return tuple(spans)


def load_story_keyword_occurrences(
    story_config_path: Path = DEFAULT_STORY_CONFIG,
    *,
    selected_stages: set[int] | None = None,
) -> list[KeywordOccurrence]:
    config = _json(story_config_path)
    if config.get("profile_id") != "srwz-zh-story-component-v1":
        raise StageKeywordAuditError("unexpected story-component profile")
    source = config["source"]
    _slps_path, source_slps = _locked_file(
        source["slps"],
        label="source SLPS",
    )
    _stage_path, source_stage = _locked_file(
        source["stage"],
        label="source STAGE",
    )
    source_hb = _read_iso_member(_project_path(source["iso"]), source["hb"])
    table = load_text_table(_project_path(source["text_table"]["path"]))
    offsets = read_executable_archive_offsets(
        source_hb,
        ExecutableOffsetSpec(
            name="HEDBDY/HB.BIN STAGE offsets",
            member=source["hb"]["member"],
            table_start=30320,
            table_end=31144,
        ),
        len(source_stage),
    )
    functions = read_stage_function_addresses(source_slps)
    dialogue_root = _project_path(config["translations"]["dialogue_root"])
    occurrences: list[KeywordOccurrence] = []

    for stage_index in range(len(offsets) - 1):
        if selected_stages is not None and stage_index not in selected_stages:
            continue
        corpus_path = dialogue_root / f"stage-{stage_index:03d}.json"
        if not corpus_path.is_file():
            continue
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        translated_by_id = {
            row["id"]: row["translation"] for row in corpus.get("entries", [])
        }
        parsed = parse_stage(
            decode(
                source_stage[offsets[stage_index] : offsets[stage_index + 1]]
            ).output,
            table,
            stage_index=stage_index,
            function_address=functions[stage_index],
        )
        for source_entry in parsed.entries:
            if source_entry.kind != "dialogue":
                continue
            source_spans = _keyword_spans(
                source_entry.text,
                label=f"{source_entry.entry_id} source",
            )
            if not source_spans:
                continue
            translation = translated_by_id.get(source_entry.entry_id)
            if not isinstance(translation, str):
                raise StageKeywordAuditError(
                    f"missing translated keyword entry: {source_entry.entry_id}"
                )
            translated_spans = _keyword_spans(
                translation,
                label=f"{source_entry.entry_id} translation",
            )
            if len(source_spans) != len(translated_spans):
                raise StageKeywordAuditError(
                    f"{source_entry.entry_id} keyword span-count mismatch: "
                    f"source={len(source_spans)} translation={len(translated_spans)}"
                )
            for span_index, (source_word, translated_word) in enumerate(
                zip(source_spans, translated_spans)
            ):
                occurrences.append(
                    KeywordOccurrence(
                        stage_index=stage_index,
                        entry_id=source_entry.entry_id,
                        span_index=span_index,
                        source_word=source_word,
                        translated_word=translated_word,
                    )
                )
    if selected_stages is not None:
        missing = sorted(
            stage
            for stage in selected_stages
            if not (dialogue_root / f"stage-{stage:03d}.json").is_file()
        )
        if missing:
            raise StageKeywordAuditError(
                f"selected stages have no translated corpus: {missing}"
            )
    return occurrences


def load_library_word_translations(
    library_config_path: Path = DEFAULT_LIBRARY_CONFIG,
) -> dict[str, str]:
    config = _json(library_config_path)
    corpus_ref = config.get("corpus")
    if not isinstance(corpus_ref, dict):
        raise StageKeywordAuditError("LIBRARY writeback config has no corpus")
    corpus_path = _project_path(str(corpus_ref.get("path", "")))
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    entries = corpus.get("entries")
    if not isinstance(entries, list):
        raise StageKeywordAuditError("LIBRARY corpus has no entries")
    by_source_hash: dict[str, str] = {}
    for row in entries:
        if not isinstance(row, dict):
            raise StageKeywordAuditError("LIBRARY corpus row is malformed")
        if "glossary" not in row.get("domains", []) or "WORD" not in row.get(
            "tags", []
        ):
            continue
        source_hash = row.get("source_text_sha256")
        translation = row.get("translation")
        if (
            not isinstance(source_hash, str)
            or len(source_hash) != 64
            or not isinstance(translation, str)
            or not translation
        ):
            raise StageKeywordAuditError("LIBRARY WORD identity is malformed")
        previous = by_source_hash.setdefault(source_hash, translation)
        if previous != translation:
            raise StageKeywordAuditError(
                f"LIBRARY WORD source hash has conflicting translations: {source_hash}"
            )
    return by_source_hash


def load_canonical_keyword_catalog(
    catalog_path: Path = DEFAULT_CANONICAL_KEYWORDS,
) -> tuple[dict[str, str], dict[str, tuple[int, ...]]]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("profile_id") != "srwz-stage-runtime-keywords-v1":
        raise StageKeywordAuditError("unexpected runtime-keyword catalog profile")
    if catalog.get("status") != "approved":
        raise StageKeywordAuditError("runtime-keyword catalog is not approved")
    entries = catalog.get("entries")
    if not isinstance(entries, list) or len(entries) != 52:
        raise StageKeywordAuditError(
            "runtime-keyword catalog must contain exactly 52 entries"
        )

    by_source_hash: dict[str, str] = {}
    by_source_word: dict[str, tuple[int, ...]] = {}
    indices: set[int] = set()
    for row in entries:
        if not isinstance(row, dict):
            raise StageKeywordAuditError("runtime-keyword catalog row is malformed")
        entry_index = row.get("entry_index")
        source_word = row.get("source_term")
        source_hash = row.get("source_text_sha256")
        translation = row.get("translation")
        if (
            not isinstance(entry_index, int)
            or not isinstance(source_word, str)
            or not source_word
            or not isinstance(source_hash, str)
            or not isinstance(translation, str)
            or not translation
        ):
            raise StageKeywordAuditError(
                "runtime-keyword catalog identity is malformed"
            )
        if source_hash != _sha256_text(source_word):
            raise StageKeywordAuditError(
                f"runtime-keyword source hash drift at slot {entry_index}"
            )
        if entry_index in indices:
            raise StageKeywordAuditError(
                f"duplicate runtime-keyword slot {entry_index}"
            )
        if source_hash in by_source_hash or source_word in by_source_word:
            raise StageKeywordAuditError(
                f"duplicate runtime-keyword source {source_word!r}"
            )
        indices.add(entry_index)
        by_source_hash[source_hash] = translation
        by_source_word[source_word] = (entry_index,)
    if indices != set(range(52)):
        raise StageKeywordAuditError(
            "runtime-keyword slots must be the exact range 0..51"
        )
    return by_source_hash, by_source_word


def load_original_keyword_entries(
    library_config_path: Path = DEFAULT_LIBRARY_CONFIG,
) -> dict[str, tuple[int, ...]]:
    writeback = _json(library_config_path)
    scope_path = _project_path(str(writeback.get("scope_config", "")))
    scope = _json(scope_path)
    locks = scope.get("source_member_locks")
    if not isinstance(locks, dict):
        raise StageKeywordAuditError("LIBRARY scope has no source-member locks")
    executable_ref = locks.get("SLPS_258.87")
    archive_ref = locks.get(KEYWORD_MEMBER)
    if not isinstance(executable_ref, dict) or not isinstance(archive_ref, dict):
        raise StageKeywordAuditError("LIBRARY scope has no locked KYWD resources")
    _executable_path, executable = _locked_file(
        executable_ref,
        label="LIBRARY source SLPS",
    )
    _archive_path, archive = _locked_file(
        archive_ref,
        label="LIBRARY source MTVZKNKW",
    )
    offsets = read_executable_archive_offsets(
        executable,
        ExecutableOffsetSpec(
            name=KEYWORD_MEMBER,
            member=KEYWORD_MEMBER,
            table_start=int(str(archive_ref["slps_table_start"]), 0),
            table_end=int(str(archive_ref["slps_table_end"]), 0),
        ),
        len(archive),
    )
    expected_count = int(archive_ref["expected_chunk_count"])
    if len(offsets) - 1 != expected_count:
        raise StageKeywordAuditError(
            f"KYWD entry-count drift: {len(offsets) - 1} != {expected_count}"
        )
    by_word: dict[str, list[int]] = defaultdict(list)
    for entry_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        stored = archive[start:end]
        result = decode(stored)
        if any(stored[result.consumed :]):
            raise StageKeywordAuditError(
                f"KYWD {entry_index:03d} has nonzero compressed padding"
            )
        document = parse_zkn_decoded_chunk(result.output)
        if document.kind != "KYWD":
            raise StageKeywordAuditError(
                f"ZKAN {entry_index:03d} is {document.kind}, expected KYWD"
            )
        word = document.field("WORD").text
        if not word:
            raise StageKeywordAuditError(f"KYWD {entry_index:03d} has no WORD")
        by_word[word].append(entry_index)
    return {word: tuple(indices) for word, indices in by_word.items()}


def audit_keyword_links(
    occurrences: Iterable[KeywordOccurrence],
    expected_words: Mapping[str, str],
    original_keyword_entries: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, object]:
    rows = list(occurrences)
    by_source: dict[str, list[KeywordOccurrence]] = defaultdict(list)
    for occurrence in rows:
        by_source[occurrence.source_word].append(occurrence)

    missing_library_words: list[dict[str, object]] = []
    missing_original_keyword_words: list[dict[str, object]] = []
    ambiguous_original_keyword_words: list[dict[str, object]] = []
    inconsistent_story_words: list[dict[str, object]] = []
    translation_mismatches: list[dict[str, object]] = []
    matched_occurrence_count = 0
    for source_word in sorted(by_source):
        source_rows = by_source[source_word]
        source_hash = _sha256_text(source_word)
        story_words = sorted({row.translated_word for row in source_rows})
        locations = [
            {
                "stage_index": row.stage_index,
                "entry_id": row.entry_id,
                "span_index": row.span_index,
            }
            for row in source_rows
        ]
        keyword_entry_indices = (
            tuple(original_keyword_entries.get(source_word, ()))
            if original_keyword_entries is not None
            else ()
        )
        if original_keyword_entries is not None and not keyword_entry_indices:
            missing_original_keyword_words.append(
                {
                    "source_word": source_word,
                    "source_text_sha256": source_hash,
                    "occurrence_count": len(source_rows),
                    "locations": locations,
                }
            )
        elif len(keyword_entry_indices) > 1:
            ambiguous_original_keyword_words.append(
                {
                    "source_word": source_word,
                    "source_text_sha256": source_hash,
                    "keyword_entry_indices": list(keyword_entry_indices),
                    "occurrence_count": len(source_rows),
                    "locations": locations,
                }
            )
        if len(story_words) != 1:
            inconsistent_story_words.append(
                {
                    "source_word": source_word,
                    "source_text_sha256": source_hash,
                    "story_words": story_words,
                    "keyword_entry_indices": list(keyword_entry_indices),
                    "occurrence_count": len(source_rows),
                    "locations": locations,
                }
            )
        expected_word = expected_words.get(source_hash)
        if expected_word is None:
            missing_library_words.append(
                {
                    "source_word": source_word,
                    "source_text_sha256": source_hash,
                    "story_words": story_words,
                    "keyword_entry_indices": list(keyword_entry_indices),
                    "occurrence_count": len(source_rows),
                    "locations": locations,
                }
            )
            continue
        mismatched_rows = [
            row for row in source_rows if row.translated_word != expected_word
        ]
        matched_occurrence_count += len(source_rows) - len(mismatched_rows)
        if mismatched_rows:
            translation_mismatches.append(
                {
                    "source_word": source_word,
                    "source_text_sha256": source_hash,
                    "story_words": story_words,
                    "expected_word": expected_word,
                    "library_word": expected_word,
                    "keyword_entry_indices": list(keyword_entry_indices),
                    "occurrence_count": len(source_rows),
                    "mismatch_occurrence_count": len(mismatched_rows),
                    "locations": [
                        {
                            "stage_index": row.stage_index,
                            "entry_id": row.entry_id,
                            "span_index": row.span_index,
                            "story_word": row.translated_word,
                        }
                        for row in mismatched_rows
                    ],
                }
            )

    mismatch_occurrence_count = sum(
        int(row["mismatch_occurrence_count"])
        for row in translation_mismatches
    )
    status = (
        "passed"
        if not missing_library_words
        and not missing_original_keyword_words
        and not ambiguous_original_keyword_words
        and not inconsistent_story_words
        and not translation_mismatches
        else "failed"
    )
    return {
        "schema_version": 1,
        "status": status,
        "contract": (
            "The translated text inside each native STAGE 0x8173/0x8174 "
            "span must exactly equal the localized KYWD WORD selected by "
            "the immutable Japanese source term hash."
        ),
        "link_occurrence_count": len(rows),
        "unique_source_keyword_count": len(by_source),
        "original_keyword_entry_count": (
            sum(len(indices) for indices in original_keyword_entries.values())
            if original_keyword_entries is not None
            else None
        ),
        "unique_original_keyword_count": (
            len(original_keyword_entries)
            if original_keyword_entries is not None
            else None
        ),
        "expected_word_source_count": len(expected_words),
        "library_word_source_count": len(expected_words),
        "matched_occurrence_count": matched_occurrence_count,
        "mismatch_occurrence_count": mismatch_occurrence_count,
        "missing_library_word_count": len(missing_library_words),
        "missing_original_keyword_word_count": len(
            missing_original_keyword_words
        ),
        "ambiguous_original_keyword_word_count": len(
            ambiguous_original_keyword_words
        ),
        "inconsistent_story_word_count": len(inconsistent_story_words),
        "translation_mismatch_term_count": len(translation_mismatches),
        "missing_library_words": missing_library_words,
        "missing_original_keyword_words": missing_original_keyword_words,
        "ambiguous_original_keyword_words": ambiguous_original_keyword_words,
        "inconsistent_story_words": inconsistent_story_words,
        "translation_mismatches": translation_mismatches,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story-config", type=Path, default=DEFAULT_STORY_CONFIG)
    parser.add_argument("--library-config", type=Path, default=DEFAULT_LIBRARY_CONFIG)
    parser.add_argument(
        "--canonical-keywords",
        type=Path,
        default=DEFAULT_CANONICAL_KEYWORDS,
    )
    parser.add_argument(
        "--stage",
        action="append",
        type=int,
        help="Audit only this STAGE index; repeat to select more than one.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--fail-on-mismatch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    selected_stages = set(args.stage) if args.stage is not None else None
    occurrences = load_story_keyword_occurrences(
        args.story_config.resolve(),
        selected_stages=selected_stages,
    )
    canonical_words, canonical_entries = load_canonical_keyword_catalog(
        args.canonical_keywords.resolve()
    )
    original_entries = load_original_keyword_entries(args.library_config.resolve())
    if canonical_entries != original_entries:
        raise StageKeywordAuditError(
            "approved runtime-keyword catalog does not match original KYWD slots"
        )
    report = audit_keyword_links(
        occurrences,
        canonical_words,
        original_entries,
    )
    report["authority"] = "corpus/runtime/stage-keywords-v1.json"
    report["library_alignment"] = audit_keyword_links(
        occurrences,
        load_library_word_translations(args.library_config.resolve()),
        original_entries,
    )
    report["scope"] = {
        "stages": sorted(selected_stages) if selected_stages is not None else "all",
        "story_config": str(args.story_config.resolve().relative_to(PROJECT_ROOT)),
        "library_config": str(args.library_config.resolve().relative_to(PROJECT_ROOT)),
        "canonical_keywords": str(
            args.canonical_keywords.resolve().relative_to(PROJECT_ROOT)
        ),
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "STAGE keyword-link audit: "
        f"status={report['status']} "
        f"links={report['link_occurrence_count']} "
        f"unique={report['unique_source_keyword_count']} "
        f"matched={report['matched_occurrence_count']} "
        f"mismatched={report['mismatch_occurrence_count']} "
        f"missing={report['missing_library_word_count']} "
        f"missing_source={report['missing_original_keyword_word_count']} "
        f"ambiguous_source={report['ambiguous_original_keyword_word_count']} "
        f"library_drift={report['library_alignment']['mismatch_occurrence_count']} "
        f"report={report_path}"
    )
    return int(args.fail_on_mismatch and report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
