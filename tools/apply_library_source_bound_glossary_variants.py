#!/usr/bin/env python3
"""Apply selected glossary variants to the reviewed LIBRARY corpus.

The released LIBRARY corpus keeps only source hashes.  This tool joins it to
the immutable source queue by ID and hash, resolves glossary terms against the
Japanese text, and rewrites only declared deprecated Chinese translations.
Dry-run is the default.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from srwz.glossary import (
    apply_glossary_variants,
    global_glossary_by_id,
    load_global_glossary,
    relevant_glossary_terms,
)


DEFAULT_SOURCE = PROJECT_ROOT / "work/review/aliyun/library-v0.2/source-queue.jsonl"
DEFAULT_CORPUS = PROJECT_ROOT / "corpus/zh/library/v0.2-reviewed.json"
DEFAULT_REPORT = PROJECT_ROOT / "work/review/library-source-bound-variant-apply.json"


class LibrarySourceBoundApplyError(ValueError):
    """The immutable LIBRARY source/corpus pairing is unsafe to update."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--term-id",
        action="append",
        required=True,
        help="Reviewed global term ID to apply; repeat for multiple terms.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fail-on-unresolved", action="store_true")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise LibrarySourceBoundApplyError(
                f"source row {number} is not an object: {path}"
            )
        rows.append(value)
    return rows


def unique_by_id(
    rows: Sequence[Mapping[str, object]], label: str
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id or row_id in result:
            raise LibrarySourceBoundApplyError(f"{label} has duplicate or missing IDs")
        result[row_id] = row
    return result


def main() -> int:
    args = parse_args()
    glossary = load_global_glossary(PROJECT_ROOT / "corpus/glossary")
    glossary_by_id = global_glossary_by_id(glossary)
    selected_ids = list(dict.fromkeys(args.term_id))
    missing_ids = sorted(set(selected_ids) - set(glossary_by_id))
    if missing_ids:
        raise LibrarySourceBoundApplyError(
            f"unknown glossary term IDs: {missing_ids}"
        )

    source_rows = load_jsonl(args.source.resolve())
    source_by_id = unique_by_id(source_rows, "LIBRARY source queue")
    document = json.loads(args.corpus.resolve().read_text(encoding="utf-8"))
    entries = document.get("entries")
    if not isinstance(entries, list) or not all(isinstance(row, dict) for row in entries):
        raise LibrarySourceBoundApplyError("LIBRARY corpus entries are missing")
    entry_by_id = unique_by_id(entries, "LIBRARY corpus")
    if set(entry_by_id) != set(source_by_id):
        raise LibrarySourceBoundApplyError("LIBRARY source/corpus ID coverage drift")

    changes: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    matched_entry_count = 0
    matched_occurrence_count = 0
    for entry_id in sorted(entry_by_id):
        entry = entry_by_id[entry_id]
        source = source_by_id[entry_id]
        if entry.get("source_text_sha256") != source.get("source_text_sha256"):
            raise LibrarySourceBoundApplyError(
                f"LIBRARY source hash mismatch: {entry_id}"
            )
        source_text = source.get("model_source_text", source.get("source_text"))
        translation = entry.get("translation")
        if not isinstance(source_text, str) or not isinstance(translation, str):
            raise LibrarySourceBoundApplyError(
                f"LIBRARY source or translation is invalid: {entry_id}"
            )
        relevant = relevant_glossary_terms(source_text, glossary)
        selected = [term for term in relevant if str(term["id"]) in selected_ids]
        if not selected:
            continue
        matched_entry_count += 1
        matched_occurrence_count += sum(
            len(term.get("matched_source_terms", [])) for term in selected
        )
        candidate, applied = apply_glossary_variants(translation, selected)
        applied_ids = sorted(
            {
                str(term["id"])
                for term in selected
                if any(
                    str(variant) in translation
                    for variant in term.get("deprecated_translations", [])
                )
                and str(term["translation"]) in candidate
            }
        )
        for term in selected:
            canonical = str(term["translation"])
            if term.get("enforce") is True and canonical not in candidate:
                unresolved.append(
                    {
                        "id": entry_id,
                        "term_id": str(term["id"]),
                        "matched_source_terms": term.get("matched_source_terms", []),
                        "expected_translation": canonical,
                        "source_text": source_text,
                        "translation": candidate,
                    }
                )
        if candidate == translation:
            continue
        changes.append(
            {
                "id": entry_id,
                "before": translation,
                "after": candidate,
                "applied_term_ids": applied_ids,
                "applied": applied,
            }
        )
        entry["translation"] = candidate
        refs = entry.get("glossary_refs", [])
        if not isinstance(refs, list):
            raise LibrarySourceBoundApplyError(
                f"LIBRARY glossary_refs is invalid: {entry_id}"
            )
        entry["glossary_refs"] = sorted(set(map(str, refs)) | set(applied_ids))

    if args.apply and changes:
        args.corpus.resolve().write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report = {
        "schema_version": 1,
        "mode": "apply" if args.apply else "dry-run",
        "selected_term_ids": selected_ids,
        "matched_entry_count": matched_entry_count,
        "matched_occurrence_count": matched_occurrence_count,
        "changed_entry_count": len(changes),
        "unresolved_count": len(unresolved),
        "changed_paths": (
            [args.corpus.resolve().relative_to(PROJECT_ROOT).as_posix()]
            if args.apply and changes
            else []
        ),
        "changes": changes,
        "unresolved": unresolved,
    }
    args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.report.resolve().write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "LIBRARY source-bound variant apply: "
        f"mode={report['mode']} matched={matched_entry_count} "
        f"changed={len(changes)} unresolved={len(unresolved)} "
        f"report={args.report}"
    )
    return int(bool(args.fail_on_unresolved and unresolved))


if __name__ == "__main__":
    raise SystemExit(main())
