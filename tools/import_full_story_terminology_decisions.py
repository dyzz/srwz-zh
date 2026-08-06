#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate and normalize an exported full-story terminology review.

This importer creates an editorial decision layer only.  It never edits the
formal glossary or translated corpus.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "work/review/full-story-terminology"
REVIEW_HTML = REVIEW / "review.html"
DECISION_OVERRIDES = REVIEW / "user-decision-overrides.json"
OUT_JSON = REVIEW / "imported-decisions.json"
RESOLVED_TSV = REVIEW / "resolved-decisions.tsv"
UNRESOLVED_TSV = REVIEW / "unresolved-decisions.tsv"
DATA_PATTERN = re.compile(
    r'<script id="review-data" type="application/json">([\s\S]*?)</script>'
)
ALLOWED_ACTIONS = {"accept", "subtitle", "custom", "defer"}


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def write_tsv(path: Path, rows: list[Mapping[str, object]]) -> None:
    fields = [
        "id",
        "item_type",
        "work",
        "category",
        "source_terms",
        "action",
        "chosen_translation",
        "resolution_status",
        "seeded_from",
        "note",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: str(row.get(field, "")).replace("\n", " / ")
                    for field in fields
                }
            )
    temporary.replace(path)


def review_data() -> dict[str, object]:
    match = DATA_PATTERN.search(REVIEW_HTML.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError("review.html does not contain embedded review data")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("embedded review data must be an object")
    return value


def selected_translation(
    decision: Mapping[str, object], item: Mapping[str, object]
) -> str:
    action = str(decision["action"])
    if action == "accept":
        return str(item.get("proposed_translation") or "").strip()
    if action == "subtitle":
        return str(item.get("alternate_translation") or "").strip()
    if action == "custom":
        return str(decision.get("custom_translation") or "").strip()
    return ""


def decision_overrides() -> dict[str, dict[str, object]]:
    if not DECISION_OVERRIDES.exists():
        return {}
    document = json.loads(DECISION_OVERRIDES.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("unsupported decision override schema")
    result: dict[str, dict[str, object]] = {}
    for row in document.get("decisions", []):
        if not isinstance(row, Mapping):
            raise ValueError("decision override must be an object")
        item_id = str(row.get("id", ""))
        if not item_id or item_id in result:
            raise ValueError(f"invalid or duplicate decision override: {item_id!r}")
        result[item_id] = dict(row)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path, help="review export JSON")
    args = parser.parse_args()

    exported = json.loads(args.export.read_text(encoding="utf-8"))
    if exported.get("schema_version") != 1:
        raise ValueError("unsupported decision export schema")
    if exported.get("kind") != "srwz_full_story_terminology_review_decisions":
        raise ValueError("unexpected decision export kind")
    decisions = exported.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("decision export must contain a decisions array")
    if int(exported.get("decision_count", -1)) != len(decisions):
        raise ValueError("decision_count does not match decisions array")

    current = review_data()
    current_items = {
        str(item["id"]): item
        for item in current.get("items", [])
        if isinstance(item, Mapping)
    }
    overrides = decision_overrides()
    ids = [str(decision.get("id", "")) for decision in decisions]
    duplicates = [item_id for item_id, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate decision ids: {duplicates}")
    missing = sorted(set(current_items) - set(ids))
    unknown = sorted(set(ids) - set(current_items))
    if missing or unknown:
        raise ValueError(f"decision coverage mismatch: missing={missing} unknown={unknown}")
    unknown_overrides = sorted(set(overrides) - set(current_items))
    if unknown_overrides:
        raise ValueError(f"decision overrides do not match current review: {unknown_overrides}")

    normalized: list[dict[str, object]] = []
    for decision in decisions:
        item_id = str(decision["id"])
        item = current_items[item_id]
        decision = overrides.get(item_id, decision)
        action = str(decision.get("action", ""))
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported action for {item_id}: {action!r}")
        chosen = selected_translation(decision, item)
        if action == "defer":
            status = "deferred"
        elif not chosen:
            status = "invalid_empty_selection"
        else:
            status = "resolved"
        normalized.append(
            {
                "id": item_id,
                "item_type": item.get("item_type", ""),
                "term_id": item.get("term_id", ""),
                "work": " / ".join(str(value) for value in item.get("work_hints", [])),
                "category": item.get("category", ""),
                "source_terms": " | ".join(
                    str(value) for value in item.get("source_terms", [])
                ),
                "action": action,
                "chosen_translation": chosen,
                "resolution_status": status,
                "seeded_from": decision.get("seeded_from") or "human",
                "note": str(decision.get("note") or ""),
            }
        )

    counts = Counter(str(row["resolution_status"]) for row in normalized)
    document = {
        "schema_version": 1,
        "kind": "srwz_full_story_terminology_imported_decisions",
        "source_export": str(args.export.resolve()),
        "source_exported_at": exported.get("exported_at"),
        "policy": {
            "writes_back_formal_translation": False,
            "writes_back_formal_glossary": False,
            "selection_recomputed_against_current_review": True,
        },
        "summary": {
            "decision_count": len(normalized),
            "resolution_counts": dict(counts),
            "all_current_review_ids_covered": True,
        },
        "decisions": normalized,
    }
    resolved = [row for row in normalized if row["resolution_status"] == "resolved"]
    unresolved = [row for row in normalized if row["resolution_status"] != "resolved"]
    write_json(OUT_JSON, document)
    write_tsv(RESOLVED_TSV, resolved)
    write_tsv(UNRESOLVED_TSV, unresolved)
    print(
        f"decisions={len(normalized)} resolved={len(resolved)} "
        f"unresolved={len(unresolved)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
