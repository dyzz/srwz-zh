#!/usr/bin/env python3
"""Apply reviewed Chinese variants only in Japanese-source-bound rows.

This is deliberately narrower than a global search-and-replace.  It first
runs the complete glossary audit so longer Japanese forms can shadow shorter
ones, then replaces only declared ``deprecated_translations`` for explicitly
selected term IDs.  Dry-run is the default; ``--apply`` writes the affected
story or SRVC corpus documents and adds their formal glossary references.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from audit_source_bound_glossary import audit_source_terms, load_source_translations
from srwz.glossary import (
    apply_glossary_variants,
    global_glossary_by_id,
    load_global_glossary,
)


DEFAULT_REPORT = PROJECT_ROOT / "work/review/source-bound-variant-apply.json"
BATTLE_CORPUS = PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json"
STORY_ID = re.compile(r"^story/(?P<stage>\d{3})/dialogue/")
APPLIED_TERM_ID = re.compile(r"\[([^\]]+)\]$")


class SourceBoundApplyError(ValueError):
    """A corpus preimage or selected glossary contract is unsafe to apply."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--term-id",
        action="append",
        required=True,
        help="Reviewed global term ID to apply; repeat for multiple terms.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fail-on-unresolved", action="store_true")
    return parser.parse_args()


def _corpus_path(surface: str, entry_id: str) -> Path:
    if surface == "battle":
        return BATTLE_CORPUS
    if surface != "story":
        raise SourceBoundApplyError(f"unsupported corpus surface: {surface}")
    match = STORY_ID.match(entry_id)
    if match is None:
        raise SourceBoundApplyError(f"invalid story entry ID: {entry_id}")
    return PROJECT_ROOT / (
        f"corpus/zh/story-dialogue/stage-{match.group('stage')}.json"
    )


def _apply_bound_terms(
    translation: str,
    terms: Sequence[Mapping[str, object]],
) -> tuple[str, list[str], list[str]]:
    candidate, applied = apply_glossary_variants(translation, terms)
    applied_ids: set[str] = set()
    for label in applied:
        match = APPLIED_TERM_ID.search(label)
        if match is None:
            raise SourceBoundApplyError(f"cannot parse applied glossary label: {label}")
        applied_ids.add(match.group(1))

    # Machine drafts occasionally insert a visual line break in the middle of
    # a Chinese name.  Preserve that layout when the deprecated and canonical
    # forms have equal character counts (皮埃\n尔 -> 皮耶\n尔), rather than
    # silently removing a control-sensitive line break.
    for term in terms:
        term_id = str(term["id"])
        canonical = str(term["translation"])
        for variant in term.get("deprecated_translations", []):
            variant = str(variant)
            if len(variant) != len(canonical):
                continue
            characters = list(candidate)
            positions = [
                index
                for index, character in enumerate(characters)
                if not character.isspace() and character != "　"
            ]
            compact = "".join(characters[index] for index in positions)
            cursor = 0
            changed = False
            while True:
                start = compact.find(variant, cursor)
                if start < 0:
                    break
                source_positions = positions[start : start + len(variant)]
                if any(
                    right - left > 1
                    for left, right in zip(source_positions, source_positions[1:])
                ):
                    for position, replacement in zip(source_positions, canonical):
                        characters[position] = replacement
                    changed = True
                cursor = start + len(variant)
            if changed:
                candidate = "".join(characters)
                applied.append(f"{variant}→{canonical}[{term_id}:split-layout]")
                applied_ids.add(term_id)
    return candidate, sorted(applied_ids), applied


def _append_note(existing: str, term_ids: Sequence[str]) -> str:
    note = "按日文源词绑定统一全局术语：" + "、".join(term_ids) + "。"
    if not existing:
        return note
    if note in existing:
        return existing
    separator = "" if existing.endswith(("。", "！", "？")) else "；"
    return existing + separator + note


def _write_updates(updates: Sequence[dict[str, object]]) -> list[str]:
    by_path: dict[Path, list[dict[str, object]]] = defaultdict(list)
    for update in updates:
        by_path[_corpus_path(str(update["surface"]), str(update["id"]))].append(
            update
        )

    changed_paths: list[str] = []
    for path, path_updates in sorted(by_path.items()):
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = document.get("entries")
        if not isinstance(entries, list):
            raise SourceBoundApplyError(f"corpus entries are missing: {path}")
        by_id = {
            str(entry.get("id")): entry
            for entry in entries
            if isinstance(entry, dict)
        }
        for update in path_updates:
            entry_id = str(update["id"])
            entry = by_id.get(entry_id)
            if entry is None:
                raise SourceBoundApplyError(f"corpus row is missing: {entry_id}")
            if entry.get("translation") != update["before"]:
                raise SourceBoundApplyError(
                    f"translation preimage drifted for {entry_id}: "
                    f"{entry.get('translation')!r} != {update['before']!r}"
                )
            refs = entry.get("glossary_refs")
            notes = entry.get("notes")
            surface = str(update["surface"])
            if surface == "battle":
                if refs is None:
                    refs = []
                if not isinstance(refs, list):
                    raise SourceBoundApplyError(f"invalid corpus metadata: {entry_id}")
            elif not isinstance(refs, list) or not isinstance(notes, str):
                raise SourceBoundApplyError(f"invalid corpus metadata: {entry_id}")
            term_ids = [str(value) for value in update["applied_term_ids"]]
            entry["translation"] = update["after"]
            entry["glossary_refs"] = sorted(set(map(str, refs)) | set(term_ids))
            if surface == "story":
                entry["notes"] = _append_note(str(notes), term_ids)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        changed_paths.append(path.relative_to(PROJECT_ROOT).as_posix())
    return changed_paths


def main() -> int:
    args = _parse_args()
    glossary = load_global_glossary(PROJECT_ROOT / "corpus/glossary")
    glossary_by_id = global_glossary_by_id(glossary)
    selected_ids = list(dict.fromkeys(args.term_id))
    missing = sorted(set(selected_ids) - set(glossary_by_id))
    if missing:
        raise SystemExit(f"unknown glossary term IDs: {missing}")

    rows = load_source_translations(PROJECT_ROOT)
    rows_by_key = {(row.surface, row.entry_id): row for row in rows}
    audit = audit_source_terms(rows, glossary)
    selected_mismatches = [
        item
        for item in audit["mismatches"]
        if item["term_id"] in selected_ids
    ]
    mismatches_by_row: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for mismatch in selected_mismatches:
        mismatches_by_row[(str(mismatch["surface"]), str(mismatch["id"]))].append(
            mismatch
        )

    updates: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    for key, mismatches in sorted(mismatches_by_row.items()):
        row = rows_by_key[key]
        term_ids = sorted({str(item["term_id"]) for item in mismatches})
        terms = [glossary_by_id[term_id] for term_id in term_ids]
        candidate, applied_ids, applied = _apply_bound_terms(row.translation, terms)
        if candidate == row.translation:
            unresolved.extend(mismatches)
            continue
        unresolved.extend(
            item for item in mismatches if item["term_id"] not in applied_ids
        )
        updates.append(
            {
                "surface": row.surface,
                "id": row.entry_id,
                "before": row.translation,
                "after": candidate,
                "applied_term_ids": applied_ids,
                "applied": applied,
            }
        )

    changed_paths = _write_updates(updates) if args.apply else []
    report = {
        "schema_version": 1,
        "mode": "apply" if args.apply else "dry-run",
        "selected_term_ids": selected_ids,
        "source_mismatch_count": len(selected_mismatches),
        "changed_entry_count": len(updates),
        "unresolved_count": len(unresolved),
        "changed_paths": changed_paths,
        "changes": updates,
        "unresolved": unresolved,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "source-bound variant apply: "
        f"mode={report['mode']} mismatches={len(selected_mismatches)} "
        f"changed={len(updates)} unresolved={len(unresolved)} "
        f"report={args.report}"
    )
    return int(bool(args.fail_on_unresolved and unresolved))


if __name__ == "__main__":
    raise SystemExit(main())
