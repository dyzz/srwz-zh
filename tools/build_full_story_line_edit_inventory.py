#!/usr/bin/env python3
"""Rebuild the current full-story editorial risk inventory after promotion."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

try:
    from promote_full_story_dialogue_drafts import exact_occurrences
except ModuleNotFoundError:  # pragma: no cover
    from tools.promote_full_story_dialogue_drafts import exact_occurrences


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "work/review"
QUEUE = REVIEW / "local-model/story-dialogue-unique.jsonl"
SEMANTIC = REVIEW / "local-model/aliyun/remaining-stages/finalized/semantic-review.jsonl"
COMPLEX = REVIEW / "local-model/aliyun/five-stage-011-015/complex-review.jsonl"
OVERRIDES = ROOT / "corpus/review/full-story-line-edits-v1.json"
DECISIONS = REVIEW / "full-story-terminology/imported-decisions.json"
TRANSLATIONS = ROOT / "corpus/zh/story-dialogue"
OUTPUT = REVIEW / "full-story-line-editing"


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row is not an object: {path}")
            rows.append(value)
    return rows


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def key_for(row: dict[str, object]) -> tuple[int, int]:
    return int(row["stage_index"]), int(row["unique_index"])


def main() -> int:
    queue = read_jsonl(QUEUE)
    queue_by_key = {key_for(row): row for row in queue}
    key_by_hash = {
        (int(row["stage_index"]), str(row["source_text_sha256"])): key_for(row)
        for row in queue
    }
    current: dict[tuple[int, int], dict[str, object]] = {}
    for path in sorted(TRANSLATIONS.glob("stage-*.json")):
        stage = int(path.stem.split("-")[1])
        for entry in read_json(path).get("entries", []):
            if not isinstance(entry, dict):
                continue
            key = key_by_hash.get((stage, str(entry["source_text_sha256"])))
            if key is not None:
                current.setdefault(key, entry)
    if set(current) != set(queue_by_key):
        raise ValueError("current story translation coverage differs from the unique source queue")

    override_entries = read_json(OVERRIDES).get("entries", [])
    override_keys = {
        (int(row["stage_index"]), int(row["unique_index"]))
        for row in override_entries
        if isinstance(row, dict)
    }
    occurrence_decisions = exact_occurrences()
    resolved_decision_ids = {
        str(row["id"])
        for row in read_json(DECISIONS).get("decisions", [])
        if isinstance(row, dict) and row.get("resolution_status") == "resolved"
    }

    legacy_rows = []
    legacy_statuses = Counter()
    legacy_decisions = Counter()
    for old in read_jsonl(SEMANTIC):
        key = key_for(old)
        translation = str(current[key]["translation"])
        decision_ids = sorted({item_id for item_id, _ in occurrence_decisions.get(key, [])})
        unresolved_decision_ids = sorted(set(decision_ids) - resolved_decision_ids)
        if key in override_keys:
            status = "reviewed_line_edit"
        elif translation != str(old["translation"]):
            status = "resolved_by_promotion"
        elif decision_ids and not unresolved_decision_ids:
            status = "retained_by_reviewed_term_or_style_decision"
        else:
            status = "needs_editorial_review"
        legacy_statuses[status] += 1
        legacy_decisions.update(decision_ids)
        legacy_rows.append({
            "stage_index": key[0],
            "unique_index": key[1],
            "source_text_sha256": queue_by_key[key]["source_text_sha256"],
            "status": status,
            "original_reasons": old["reasons"],
            "decision_ids": decision_ids,
            "unresolved_decision_ids": unresolved_decision_ids,
            "source_text": queue_by_key[key]["source_text"],
            "translation": translation,
        })

    complex_rows = []
    complex_statuses = Counter()
    for old in read_jsonl(COMPLEX):
        key = key_for(old)
        status = "reviewed_line_edit" if key in override_keys else "needs_editorial_review"
        complex_statuses[status] += 1
        complex_rows.append({
            "stage_index": key[0],
            "unique_index": key[1],
            "source_text_sha256": queue_by_key[key]["source_text_sha256"],
            "status": status,
            "source_text": queue_by_key[key]["source_text"],
            "translation": current[key]["translation"],
        })

    objective_patterns = {
        "serialization_or_model_marker": re.compile(r"\}\s*,\s*\{|reasoning_content|```|作为AI|JSON", re.I),
        "known_duplicate_or_bad_collocation": re.compile(
            r"公司公司|系统系统|亲爱的的|驾驶员的的|做了了断"
        ),
        "replacement_character": re.compile("�"),
        "hiragana_or_katakana_remnant": re.compile(r"[\u3040-\u30ff]"),
    }
    objective_rows = []
    objective_counts = Counter()
    unique_statuses = Counter()
    for key, entry in sorted(current.items()):
        unique_statuses[str(entry.get("editorial_status", ""))] += 1
        translation = str(entry["translation"])
        reasons = [name for name, pattern in objective_patterns.items() if pattern.search(translation)]
        if not reasons:
            continue
        objective_counts.update(reasons)
        objective_rows.append({
            "stage_index": key[0],
            "unique_index": key[1],
            "source_text_sha256": queue_by_key[key]["source_text_sha256"],
            "reasons": reasons,
            "source_text": queue_by_key[key]["source_text"],
            "translation": translation,
        })

    style_keys = sorted(
        key
        for key, items in occurrence_decisions.items()
        if any(item_id == "P:style-catchphrases" for item_id, _ in items)
    )
    unresolved_term_keys = {
        key: sorted({item_id for item_id, _ in items if item_id not in resolved_decision_ids})
        for key, items in occurrence_decisions.items()
        if any(item_id not in resolved_decision_ids for item_id, _ in items)
    }
    next_rows = []
    added: set[tuple[int, int]] = set()
    for row in objective_rows:
        key = key_for(row)
        added.add(key)
        next_rows.append({**row, "queue_kind": "objective"})
    for key in style_keys:
        if key in override_keys or key in added:
            continue
        next_rows.append({
            "stage_index": key[0],
            "unique_index": key[1],
            "source_text_sha256": queue_by_key[key]["source_text_sha256"],
            "queue_kind": "catchphrase_style",
            "source_text": queue_by_key[key]["source_text"],
            "translation": current[key]["translation"],
        })
    for row in legacy_rows:
        key = key_for(row)
        if row["status"] != "needs_editorial_review" or key in added:
            continue
        added.add(key)
        next_rows.append({**row, "queue_kind": "unresolved_semantic"})
    for key, decision_ids in sorted(unresolved_term_keys.items()):
        if key in added:
            continue
        added.add(key)
        next_rows.append({
            "stage_index": key[0],
            "unique_index": key[1],
            "source_text_sha256": queue_by_key[key]["source_text_sha256"],
            "queue_kind": "unresolved_terminology",
            "decision_ids": decision_ids,
            "source_text": queue_by_key[key]["source_text"],
            "translation": current[key]["translation"],
        })

    write_jsonl(OUTPUT / "legacy-semantic-inventory.jsonl", legacy_rows)
    write_jsonl(OUTPUT / "complex-inventory.jsonl", complex_rows)
    write_jsonl(OUTPUT / "next-review.jsonl", next_rows)
    report = {
        "schema_version": 1,
        "kind": "srwz_full_story_line_edit_inventory",
        "status": "line_editing_in_progress",
        "scope": {
            "unique_text_row_count": len(queue),
            "current_unique_editorial_status_counts": dict(sorted(unique_statuses.items())),
            "tracked_editorial_override_count": len(override_keys),
        },
        "legacy_semantic_queue": {
            "row_count": len(legacy_rows),
            "status_counts": dict(sorted(legacy_statuses.items())),
            "decision_counts": dict(sorted(legacy_decisions.items())),
        },
        "five_stage_complex_queue": {
            "row_count": len(complex_rows),
            "status_counts": dict(sorted(complex_statuses.items())),
        },
        "objective_scan": {
            "flagged_row_count": len(objective_rows),
            "reason_counts": dict(sorted(objective_counts.items())),
        },
        "next_review": {
            "row_count": len(next_rows),
            "catchphrase_style_source_row_count": len(style_keys),
            "unresolved_terminology_source_row_count": len(unresolved_term_keys),
            "path": str((OUTPUT / "next-review.jsonl").relative_to(ROOT)),
        },
    }
    write_json(OUTPUT / "report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
