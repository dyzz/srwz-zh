#!/usr/bin/env python3
"""Build an ignored editorial-risk queue for the LIBRARY machine draft."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

try:
    from srwz.diagnostics import require_work_output
    from srwz.library import LibraryScopeError
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.library import LibraryScopeError

try:
    import run_aliyun_library_v02_batch as batch
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools import run_aliyun_library_v02_batch as batch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_QUEUE = WORK_ROOT / "review/aliyun/library-v0.2/source-queue.jsonl"
DEFAULT_DRAFT = (
    WORK_ROOT
    / "review/aliyun/library-v0.2/deepseek-v4-flash-0731/aggregate/validated.jsonl"
)
DEFAULT_OUTPUT = (
    WORK_ROOT
    / "review/aliyun/library-v0.2/deepseek-v4-flash-0731/editorial-audit"
)
ASCII_WORD = re.compile(r"[A-Za-z]{3,}")
NUMERIC_METADATA = re.compile(r"[\d\s.,+\-/%°ｍｍｔｋｇｃｃ]+", re.IGNORECASE)
BODY_TAGS = {"DSCR", "DSC2"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    temporary.replace(path)


def row_tags(row: Mapping[str, object]) -> set[str]:
    return {
        str(reference["tag"])
        for reference in row["references"]
        if isinstance(reference, Mapping) and isinstance(reference.get("tag"), str)
    }


def risk_reasons(
    source: Mapping[str, object], translation: str
) -> list[dict[str, object]]:
    reasons: list[dict[str, object]] = []
    source_text = str(source["source_text"])
    normalized_source = unicodedata.normalize("NFKC", source_text).strip()
    normalized_translation = unicodedata.normalize("NFKC", translation).strip()

    if (
        normalized_source == normalized_translation
        and not NUMERIC_METADATA.fullmatch(normalized_source)
    ):
        reasons.append({"code": "unchanged_source"})

    ascii_words = sorted(set(ASCII_WORD.findall(translation)))
    if ascii_words:
        reasons.append({"code": "ascii_word", "values": ascii_words})

    missing_terms: list[dict[str, str]] = []
    for term in source.get("glossary_terms", []):
        if not isinstance(term, Mapping):
            continue
        target = term.get("translation")
        if isinstance(target, str) and target and target not in translation:
            missing_terms.append(
                {
                    "id": str(term.get("id", "")),
                    "target": target,
                    "status": str(term.get("status", "")),
                }
            )
    if missing_terms:
        reasons.append({"code": "glossary_hint_mismatch", "terms": missing_terms})

    if row_tags(source) & BODY_TAGS and source_text:
        ratio = len(translation) / len(source_text)
        if ratio < 0.2 or ratio > 1.6:
            reasons.append({"code": "body_length_ratio", "ratio": round(ratio, 3)})
    return reasons


def build_audit(
    queue: Sequence[Mapping[str, object]],
    draft: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    batch.validate_queue(queue)
    if len(draft) != len(queue):
        raise LibraryScopeError(
            f"draft count mismatch: expected {len(queue)}, got {len(draft)}"
        )
    queue_ids = [str(row["id"]) for row in queue]
    draft_ids = [str(row.get("id", "")) for row in draft]
    if draft_ids != queue_ids:
        raise LibraryScopeError("draft row order does not match source queue")
    queue_by_id = {str(row["id"]): row for row in queue}
    draft_by_id: dict[str, Mapping[str, object]] = {}
    translations_to_ids: dict[str, list[str]] = defaultdict(list)
    for row in draft:
        row_id = str(row.get("id", ""))
        if row_id not in queue_by_id or row_id in draft_by_id:
            raise LibraryScopeError(f"unexpected or duplicate draft id: {row_id}")
        source = queue_by_id[row_id]
        if row.get("source_text_sha256") != source["source_text_sha256"]:
            raise LibraryScopeError(f"source hash mismatch in draft: {row_id}")
        translation = row.get("translation")
        if not isinstance(translation, str):
            raise LibraryScopeError(f"draft translation is not text: {row_id}")
        batch.validate_translation(source, translation)
        draft_by_id[row_id] = row
        translations_to_ids[translation].append(row_id)
    if set(draft_by_id) != set(queue_by_id):
        raise LibraryScopeError("draft ID set does not match source queue")

    collision_sizes = {
        row_id: len(ids)
        for translation, ids in translations_to_ids.items()
        if len(ids) > 1
        and len(translation.strip()) >= 2
        and len({str(queue_by_id[row_id]["source_text"]) for row_id in ids}) > 1
        for row_id in ids
    }
    review_rows: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    for source in queue:
        row_id = str(source["id"])
        translation = str(draft_by_id[row_id]["translation"])
        reasons = risk_reasons(source, translation)
        if row_id in collision_sizes:
            reasons.append(
                {
                    "code": "translation_collision",
                    "group_size": collision_sizes[row_id],
                }
            )
        if not reasons:
            continue
        counts.update(str(reason["code"]) for reason in reasons)
        review_rows.append(
            {
                "schema_version": 1,
                "id": row_id,
                "source_text": source["source_text"],
                "source_text_sha256": source["source_text_sha256"],
                "translation": translation,
                "references": source["references"],
                "glossary_terms": source.get("glossary_terms", []),
                "risk_reasons": reasons,
                "editorial_status": "needs_review",
            }
        )
    manifest = {
        "schema_version": 1,
        "kind": "library_v0.2_machine_draft_editorial_audit",
        "source_queue_count": len(queue),
        "draft_count": len(draft),
        "exact_id_set": True,
        "exact_source_hashes": True,
        "source_order_preserved": True,
        "strict_translation_rows": True,
        "review_row_count": len(review_rows),
        "risk_counts": dict(sorted(counts.items())),
        "editorial_status": "machine_draft_pending_review",
        "sound_track_titles_included": False,
        "review_queue": "review-queue.jsonl",
    }
    return manifest, review_rows


def main() -> int:
    args = parse_args()
    queue = batch.read_jsonl(project_path(args.queue))
    draft = batch.read_jsonl(project_path(args.draft))
    output = require_work_output(project_path(args.output_dir), WORK_ROOT).resolve()
    manifest, review_rows = build_audit(queue, draft)
    write_jsonl(output / "review-queue.jsonl", review_rows)
    write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(output / "review-queue.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
