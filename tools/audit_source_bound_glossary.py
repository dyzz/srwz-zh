#!/usr/bin/env python3
"""Audit Chinese terminology against the immutable Japanese source text.

The Chinese corpora intentionally store source hashes rather than duplicated
Japanese strings.  This audit reconstructs the stable source-ID pairing from
the locked original STAGE and SRVC resources, then checks selected glossary
terms in source context.  It therefore distinguishes homophonous translations
such as Freedom Gundam ``フリーダム`` and the Freeden ``フリーデン``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_story_component import (
    _json,
    _locked_file,
    _project_path,
    _read_iso_member,
)
from srwz.codec import decode_production as decode
from srwz.glossary import global_glossary_by_id, load_global_glossary
from srwz.image_export import parse_seg_offsets
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.srvc import parse_srvc_archive
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.text import load_text_table


DEFAULT_REPORT = PROJECT_ROOT / "work/review/source-bound-glossary-audit.json"
SPACE_PATTERN = re.compile(r"[\s　]+")


class SourceGlossaryAuditError(ValueError):
    """The immutable-source/corpus pairing or glossary contract drifted."""


@dataclass(frozen=True)
class SourceTranslation:
    surface: str
    entry_id: str
    source_text: str
    translation: str
    glossary_exceptions: tuple[str, ...]


def _compact(text: str) -> str:
    return SPACE_PATTERN.sub("", text)


def _kana_script(character: str) -> str | None:
    if "\u3041" <= character <= "\u3096":
        return "hiragana"
    if (
        "\u30a1" <= character <= "\u30fa"
        or "\u30fc" <= character <= "\u30ff"
        or "\u31f0" <= character <= "\u31ff"
    ):
        return "katakana"
    return None


def _source_occurrence_is_valid(text: str, source: str, start: int) -> bool:
    hiragana_source = bool(source) and all(
        "\u3041" <= character <= "\u3096" for character in source
    )
    if hiragana_source and (
        hiragana_source and start > 0 and text[start - 1] == source[0]
    ):
        return False

    katakana_source = bool(source) and all(
        _kana_script(character) == "katakana" for character in source
    )
    if not katakana_source or len(source) > 4:
        return True

    end = start + len(source)
    if start > 0 and _kana_script(text[start - 1]) == "katakana":
        return False
    if end >= len(text) or _kana_script(text[end]) != "katakana":
        return True

    # A name may be lengthened in a shout (マユ -> マユーッ！！), but an
    # ordinary katakana continuation means the short form is embedded in a
    # different word (エマージェンシー, ファクトリー, アネモネ).
    suffix = re.match(r"[ーッ]+", text[end:])
    if suffix is None:
        return False
    suffix_end = end + suffix.end()
    return suffix_end == len(text) or _kana_script(text[suffix_end]) is None


def _bounded_source_occurrences(text: str, source: str) -> Iterable[tuple[int, int]]:
    """Yield source positions while rejecting repeated-prefix hiragana words.

    Japanese normally has no lexical whitespace, so a generic kana boundary
    rule wrongly drops valid forms such as ``さやかさん`` and ``マユーッ``.
    Longer glossary forms are resolved later by overlap shadowing.  The narrow
    check here catches the observed false positive ``さやか`` in ``ささやか``
    without treating particles, honorifics, or katakana compounds as word
    boundaries.
    """

    cursor = 0
    while True:
        start = text.find(source, cursor)
        if start < 0:
            return
        end = start + len(source)
        if _source_occurrence_is_valid(text, source, start):
            yield start, end
        cursor = start + 1


def _story_rows(root: Path) -> list[SourceTranslation]:
    config = _json(root / "config/story-component.json")
    source = config["source"]
    _slps_path, source_slps = _locked_file(source["slps"], label="source SLPS")
    _stage_path, source_stage = _locked_file(
        source["stage"], label="source STAGE"
    )
    table = load_text_table(_project_path(source["text_table"]["path"]))
    source_hb = _read_iso_member(_project_path(source["iso"]), source["hb"])
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
    rows: list[SourceTranslation] = []
    for stage_index in range(len(offsets) - 1):
        corpus_path = root / (
            f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json"
        )
        if not corpus_path.exists():
            continue
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        corpus_by_id = {
            entry["id"]: entry for entry in corpus.get("entries", [])
        }
        decoded = decode(
            source_stage[offsets[stage_index] : offsets[stage_index + 1]]
        ).output
        parsed = parse_stage(
            decoded,
            table,
            stage_index=stage_index,
            function_address=functions[stage_index],
        )
        for source_entry in parsed.entries:
            if source_entry.kind != "dialogue":
                continue
            corpus_entry = corpus_by_id.get(source_entry.entry_id)
            if not isinstance(corpus_entry, dict):
                raise SourceGlossaryAuditError(
                    f"story source has no corpus row: {source_entry.entry_id}"
                )
            translation = corpus_entry.get("translation")
            exceptions = corpus_entry.get("glossary_exceptions", [])
            if not isinstance(translation, str) or not isinstance(exceptions, list):
                raise SourceGlossaryAuditError(
                    f"invalid story corpus row: {source_entry.entry_id}"
                )
            rows.append(
                SourceTranslation(
                    surface="story",
                    entry_id=source_entry.entry_id,
                    source_text=source_entry.text,
                    translation=translation,
                    glossary_exceptions=tuple(exceptions),
                )
            )
    return rows


def _battle_rows(root: Path) -> list[SourceTranslation]:
    config = json.loads(
        (root / "config/full-story-components.json").read_text(encoding="utf-8")
    )["srvc_battle_text"]
    source_bin = (root / config["original_bin"]["path"]).read_bytes()
    source_seg = (root / config["original_seg"]["path"]).read_bytes()
    table = load_text_table(
        root / "vendor/upstream-python/project/tbl_all.json"
    )
    offsets = parse_seg_offsets(source_seg, len(source_bin))
    chunks = parse_srvc_archive(source_bin, offsets, table)
    first_records: dict[str, object] = {}
    for chunk in chunks:
        for record in chunk.records:
            first_records.setdefault(record.text, record)
    ordered_sources = sorted(
        first_records,
        key=lambda text: (first_records[text].archive_text_start, text),
    )
    corpus_path = root / config["corpus"]["path"]
    entries = json.loads(corpus_path.read_text(encoding="utf-8"))["entries"]
    if len(entries) != len(ordered_sources):
        raise SourceGlossaryAuditError("SRVC source/corpus entry count drift")
    rows: list[SourceTranslation] = []
    for ordinal, (source_text, entry) in enumerate(zip(ordered_sources, entries)):
        entry_id = f"battle:{ordinal:05d}"
        exceptions = entry.get("glossary_exceptions", [])
        if (
            entry.get("id") != entry_id
            or not isinstance(entry.get("translation"), str)
            or not isinstance(exceptions, list)
        ):
            raise SourceGlossaryAuditError(f"invalid SRVC corpus row: {entry_id}")
        rows.append(
            SourceTranslation(
                surface="battle",
                entry_id=entry_id,
                source_text=source_text,
                translation=entry["translation"],
                glossary_exceptions=tuple(exceptions),
            )
        )
    return rows


def load_source_translations(root: Path = PROJECT_ROOT) -> list[SourceTranslation]:
    return [*_story_rows(root), *_battle_rows(root)]


def audit_source_terms(
    rows: Iterable[SourceTranslation],
    terms: Sequence[Mapping[str, object]],
) -> dict:
    occurrences: dict[str, int] = {str(term["id"]): 0 for term in terms}
    mismatches: list[dict[str, object]] = []
    source_indexes: dict[
        str,
        tuple[re.Pattern[str] | None, dict[str, list[Mapping[str, object]]]],
    ] = {}

    def source_index(
        surface: str,
    ) -> tuple[
        re.Pattern[str] | None,
        dict[str, list[Mapping[str, object]]],
    ]:
        cached = source_indexes.get(surface)
        if cached is not None:
            return cached
        bindings: dict[str, list[Mapping[str, object]]] = {}
        for term in terms:
            for source_term in term.get("source_terms", []):
                if isinstance(source_term, str) and source_term:
                    bindings.setdefault(source_term, []).append(term)
        if bindings:
            alternatives = "|".join(
                re.escape(source_term)
                for source_term in sorted(bindings, key=len, reverse=True)
            )
            pattern: re.Pattern[str] | None = re.compile(
                f"(?=({alternatives}))"
            )
        else:
            pattern = None
        source_indexes[surface] = (pattern, bindings)
        return pattern, bindings

    for row in rows:
        compact_translation = _compact(row.translation)
        raw_matches: list[tuple[int, int, str, Mapping[str, object]]] = []
        pattern, bindings = source_index(row.surface)
        if pattern is not None:
            for match in pattern.finditer(row.source_text):
                source_term = match.group(1)
                start = match.start(1)
                if not _source_occurrence_is_valid(
                    row.source_text, source_term, start
                ):
                    continue
                end = start + len(source_term)
                for term in bindings[source_term]:
                    raw_matches.append((start, end, source_term, term))
        # Prefer the longest glossary source form at an overlapping position.
        # This prevents ドギー matching inside ムーンドギー and フリーダム
        # matching inside ストライクフリーダム.
        matches_by_id: dict[str, tuple[Mapping[str, object], set[str]]] = {}
        for start, end, source_term, term in raw_matches:
            domains = term.get("domains", [])
            if domains and row.surface not in domains:
                continue
            shadowed = any(
                other_start <= start
                and end <= other_end
                and other_end - other_start > end - start
                and str(other_term["id"]) != str(term["id"])
                for other_start, other_end, _other_source, other_term in raw_matches
            )
            if shadowed:
                continue
            term_id = str(term["id"])
            _stored_term, matched = matches_by_id.setdefault(
                term_id, (term, set())
            )
            matched.add(source_term)
        for term_id, (term, matched_set) in matches_by_id.items():
            matched = sorted(matched_set)
            if not matched:
                continue
            occurrences[term_id] += 1
            if term_id in row.glossary_exceptions:
                continue
            canonical = str(term["translation"])
            compact_canonical = _compact(canonical)
            other_canonical_compacts = {
                _compact(str(other_term["translation"]))
                for other_term_id, (other_term, _other_matches) in matches_by_id.items()
                if other_term_id != term_id
            }
            deprecated_hits = [
                str(deprecated)
                for deprecated in term.get("deprecated_translations", [])
                if _compact(str(deprecated))
                and _compact(str(deprecated)) not in compact_canonical
                and not any(
                    _compact(str(deprecated)) in other_canonical
                    for other_canonical in other_canonical_compacts
                )
                and _compact(str(deprecated)) in compact_translation
            ]
            if compact_canonical in compact_translation and not deprecated_hits:
                continue
            mismatches.append(
                {
                    "surface": row.surface,
                    "id": row.entry_id,
                    "term_id": term_id,
                    "matched_source_terms": matched,
                    "expected_translation": canonical,
                    "source_text": row.source_text,
                    "translation": row.translation,
                    "deprecated_translation_hits": deprecated_hits,
                }
            )
    return {
        "schema_version": 1,
        "term_ids": [str(term["id"]) for term in terms],
        "source_occurrences": occurrences,
        "source_occurrence_count": sum(occurrences.values()),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--term-id",
        action="append",
        required=True,
        help="Glossary term ID to audit; repeat for more than one term.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--fail-on-mismatch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    glossary = global_glossary_by_id(
        load_global_glossary(PROJECT_ROOT / "corpus/glossary")
    )
    missing = sorted(set(args.term_id) - set(glossary))
    if missing:
        raise SystemExit(f"unknown glossary term IDs: {missing}")
    terms = [glossary[term_id] for term_id in dict.fromkeys(args.term_id)]
    report = audit_source_terms(load_source_translations(), terms)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "source-bound glossary audit: "
        f"occurrences={report['source_occurrence_count']} "
        f"mismatches={report['mismatch_count']} report={args.report}"
    )
    return int(args.fail_on_mismatch and report["mismatch_count"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
