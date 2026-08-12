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
    for row in rows:
        compact_translation = _compact(row.translation)
        raw_matches: list[tuple[int, int, str, Mapping[str, object]]] = []
        for term in terms:
            term_id = str(term["id"])
            domains = term.get("domains", [])
            if domains and row.surface not in domains:
                continue
            for source_term in term.get("source_terms", []):
                if not isinstance(source_term, str):
                    continue
                start = 0
                while True:
                    start = row.source_text.find(source_term, start)
                    if start < 0:
                        break
                    raw_matches.append(
                        (start, start + len(source_term), source_term, term)
                    )
                    start += len(source_term)
        # Prefer the longest glossary source form at an overlapping position.
        # This prevents ドギー matching inside ムーンドギー and フリーダム
        # matching inside ストライクフリーダム.
        matches_by_id: dict[str, tuple[Mapping[str, object], set[str]]] = {}
        for start, end, source_term, term in raw_matches:
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
            if _compact(canonical) in compact_translation:
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
