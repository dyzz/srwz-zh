#!/usr/bin/env python3
"""Validate a local-model story translation batch without promoting it.

The exporter deliberately emits an input-only queue.  This command is the
other side of that boundary: it accepts JSONL containing only stable IDs,
source hashes, and model translations, verifies every structural/layout and
terminology contract, and writes ignored validated rows plus complete
per-stage drafts.  Nothing here writes ``corpus/zh`` or changes a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

try:
    from srwz.diagnostics import require_work_output
    from srwz.translation_review import (
        STRUCTURAL_TOKEN_PATTERN,
        TranslationReviewError,
    )
except ModuleNotFoundError:  # pragma: no cover - direct checkout invocation
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.translation_review import (
        STRUCTURAL_TOKEN_PATTERN,
        TranslationReviewError,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_QUEUE = (
    WORK_ROOT / "review" / "local-model" / "story-dialogue-unique.jsonl"
)
DEFAULT_OUTPUT = (
    WORK_ROOT / "review" / "local-model" / "validated"
    / "story-dialogue-validated.jsonl"
)
DEFAULT_REPORT = (
    WORK_ROOT / "review" / "local-model" / "validated"
    / "story-dialogue-validation.json"
)
DEFAULT_DRAFT_DIR = (
    WORK_ROOT / "review" / "local-model" / "validated" / "drafts"
)

KANA_PATTERN = re.compile(
    r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]"
)
MODEL_ARTIFACT_PATTERN = re.compile(r"```|(?:\}\s*\]|\]\s*\})")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ALLOWED_MODEL_FIELDS = {
    "stage_index",
    "unique_index",
    "source_text_sha256",
    "translation",
    "translation_action",
    "glossary_refs",
    "glossary_exceptions",
    "notes",
}


def _project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _output(path: Path) -> Path:
    return require_work_output(_project_path(path), WORK_ROOT).resolve()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument(
        "--model-output",
        type=Path,
        help=(
            "local model JSONL; if omitted, non-empty model_output fields in "
            "the input queue are used"
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="validate an incomplete response; complete per-stage drafts are still required",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TranslationReviewError(f"cannot read JSONL {path}: {error}") from error
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise TranslationReviewError(
                f"invalid JSONL at {path}:{line_number}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise TranslationReviewError(
                f"JSONL row must be an object at {path}:{line_number}"
            )
        rows.append(value)
    return rows


def _as_int(value: object, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TranslationReviewError(f"{context} must be an integer")
    if value < 0:
        raise TranslationReviewError(f"{context} must be non-negative")
    return value


def _as_string_list(value: object, *, context: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise TranslationReviewError(f"{context} must be an array of strings")
    if len(value) != len(set(value)):
        raise TranslationReviewError(f"{context} contains duplicates")
    return list(value)


def _source_tokens(text: str) -> list[str]:
    return sorted(STRUCTURAL_TOKEN_PATTERN.findall(text))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_queue(path: Path) -> list[dict[str, object]]:
    """Load and fail closed on a queue that is not self-consistent."""

    rows = _read_jsonl(path)
    seen_keys: set[tuple[int, int]] = set()
    seen_hashes: set[tuple[int, str]] = set()
    stage_indices: dict[int, list[int]] = defaultdict(list)
    required = {
        "schema_version",
        "stage_index",
        "unique_index",
        "source_text",
        "source_text_sha256",
        "review_state",
        "structural_tokens",
        "must_preserve",
    }
    for row_number, row in enumerate(rows, start=1):
        missing = sorted(required - set(row))
        if missing:
            raise TranslationReviewError(
                f"queue row {row_number} is missing fields: {missing!r}"
            )
        if row.get("schema_version") != 1:
            raise TranslationReviewError(f"queue row {row_number} has unsupported schema")
        stage = _as_int(row["stage_index"], context=f"queue row {row_number} stage_index")
        unique = _as_int(
            row["unique_index"], context=f"queue row {row_number} unique_index"
        )
        source_text = row["source_text"]
        if not isinstance(source_text, str):
            raise TranslationReviewError(f"queue row {row_number} source_text must be a string")
        source_hash = row["source_text_sha256"]
        if not isinstance(source_hash, str) or not SHA256_PATTERN.fullmatch(source_hash):
            raise TranslationReviewError(
                f"queue row {row_number} source_text_sha256 is malformed"
            )
        if _hash_text(source_text) != source_hash:
            raise TranslationReviewError(
                f"queue row {row_number} source_text_sha256 does not match source_text"
            )
        key = (stage, unique)
        hash_key = (stage, source_hash)
        if key in seen_keys:
            raise TranslationReviewError(f"duplicate queue key {key!r}")
        if hash_key in seen_hashes:
            raise TranslationReviewError(f"duplicate queue source hash {hash_key!r}")
        seen_keys.add(key)
        seen_hashes.add(hash_key)
        expected_tokens = _source_tokens(source_text)
        if sorted(row["structural_tokens"]) != expected_tokens:
            raise TranslationReviewError(
                f"queue row {row_number} structural_tokens disagree with source"
            )
        if sorted(row["must_preserve"]) != expected_tokens:
            raise TranslationReviewError(
                f"queue row {row_number} must_preserve disagrees with source"
            )
        stage_indices[stage].append(unique)
    for stage, indices in stage_indices.items():
        if sorted(indices) != list(range(len(indices))):
            raise TranslationReviewError(
                f"stage {stage:03d} unique_index values are not contiguous"
            )
    return rows


def _load_model_rows(
    queue_rows: Sequence[Mapping[str, object]],
    path: Path | None,
) -> list[dict[str, object]]:
    if path is None:
        return [
            {
                "stage_index": row["stage_index"],
                "unique_index": row["unique_index"],
                "source_text_sha256": row["source_text_sha256"],
                "translation": row.get("model_output", ""),
            }
            for row in queue_rows
            if row.get("model_output", "")
        ]
    return _read_jsonl(path)


def _relevant_terms(row: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = row.get("glossary_terms", [])
    if not isinstance(raw, list):
        raise TranslationReviewError("queue glossary_terms must be an array")
    result = {}
    for term in raw:
        if not isinstance(term, Mapping):
            raise TranslationReviewError("queue glossary_terms contains a non-object")
        term_id = term.get("id")
        if not isinstance(term_id, str) or not term_id:
            raise TranslationReviewError("queue glossary term id is malformed")
        if term_id in result:
            raise TranslationReviewError(f"queue glossary term id is duplicated: {term_id}")
        result[term_id] = term
    return result


def _validate_translation(
    row: Mapping[str, object],
    candidate: Mapping[str, object],
) -> dict[str, object]:
    context = f"stage {int(row['stage_index']):03d} unique {int(row['unique_index'])}"
    translation = candidate.get("translation")
    if not isinstance(translation, str) or not translation:
        raise TranslationReviewError(f"{context}: translation must be non-empty")
    action = candidate.get("translation_action", "translate")
    if action not in {"translate", "preserve"}:
        raise TranslationReviewError(f"{context}: invalid translation_action {action!r}")
    if action == "preserve":
        if translation != row["source_text"]:
            raise TranslationReviewError(f"{context}: preserve must equal source_text")
    else:
        if KANA_PATTERN.search(translation):
            raise TranslationReviewError(f"{context}: translation contains Japanese kana（日文假名）")
        if "「" in translation or "」" in translation or "『" in translation or "』" in translation:
            raise TranslationReviewError(f"{context}: use Chinese quotation marks, not Japanese corner quotes")
        if "..." in translation:
            raise TranslationReviewError(f"{context}: use the Chinese ellipsis character")
        if "\n" in translation or "\r" in translation:
            raise TranslationReviewError(
                f"{context}: model output must not contain manual line breaks"
            )
        if MODEL_ARTIFACT_PATTERN.search(translation):
            raise TranslationReviewError(
                f"{context}: translation contains JSON/Markdown response residue"
            )
        source_shape = str(row.get("source_quote_shape", ""))
        if source_shape == "dialogue_quoted":
            stripped = translation.strip()
            if not (stripped.startswith("“") and stripped.endswith("”")):
                raise TranslationReviewError(
                    f"{context}: quoted source requires paired Chinese quotation marks"
                )
    source_tokens = _source_tokens(str(row["source_text"]))
    if _source_tokens(translation) != source_tokens:
        raise TranslationReviewError(f"{context}: structural/control token set changed（结构控制码发生变化）")
    refs = _as_string_list(candidate.get("glossary_refs", []), context=f"{context} glossary_refs")
    exceptions = _as_string_list(
        candidate.get("glossary_exceptions", []),
        context=f"{context} glossary_exceptions",
    )
    overlap = set(refs) & set(exceptions)
    if overlap:
        raise TranslationReviewError(f"{context}: glossary refs/exceptions overlap: {sorted(overlap)!r}")
    terms = _relevant_terms(row)
    unknown = sorted((set(refs) | set(exceptions)) - set(terms))
    if unknown:
        raise TranslationReviewError(f"{context}: unknown or irrelevant glossary ids: {unknown!r}")
    # Enforced terms are auto-referenced when their approved text is present;
    # an explicit exception is the only way for a local draft to defer one.
    for term_id, term in terms.items():
        if not term.get("enforce") or term_id in exceptions:
            continue
        term_translation = term.get("translation")
        if not isinstance(term_translation, str) or not term_translation:
            raise TranslationReviewError(f"{context}: malformed glossary term {term_id}")
        if term_translation not in translation:
            raise TranslationReviewError(
                f"{context}: missing enforced glossary translation {term_translation!r}"
            )
        if term_id not in refs:
            refs.append(term_id)
    notes = candidate.get("notes", "")
    if not isinstance(notes, str):
        raise TranslationReviewError(f"{context}: notes must be a string")
    return {
        "stage_index": int(row["stage_index"]),
        "unique_index": int(row["unique_index"]),
        "source_text_sha256": str(row["source_text_sha256"]),
        "translation": translation,
        "translation_action": action,
        "glossary_refs": sorted(refs),
        "glossary_exceptions": sorted(exceptions),
        "notes": notes,
    }


def validate_model_output(
    queue_rows: Sequence[Mapping[str, object]],
    model_rows: Sequence[Mapping[str, object]],
    *,
    allow_partial: bool = False,
) -> tuple[list[dict[str, object]], dict[tuple[int, int], dict[str, object]], list[dict[str, object]]]:
    queue_by_key = {
        (int(row["stage_index"]), int(row["unique_index"])): row
        for row in queue_rows
    }
    queue_by_hash = {
        (int(row["stage_index"]), str(row["source_text_sha256"])): row
        for row in queue_rows
    }
    model_by_key: dict[tuple[int, int], dict[str, object]] = {}
    for row_number, candidate in enumerate(model_rows, start=1):
        unknown = sorted(set(candidate) - ALLOWED_MODEL_FIELDS)
        if unknown:
            raise TranslationReviewError(
                f"model row {row_number} has unsupported fields: {unknown!r}"
            )
        stage = _as_int(candidate.get("stage_index"), context=f"model row {row_number} stage_index")
        unique = _as_int(candidate.get("unique_index"), context=f"model row {row_number} unique_index")
        source_hash = candidate.get("source_text_sha256")
        if not isinstance(source_hash, str) or not SHA256_PATTERN.fullmatch(source_hash):
            raise TranslationReviewError(f"model row {row_number} source_text_sha256 is malformed")
        queue_row = queue_by_key.get((stage, unique))
        if queue_row is None:
            raise TranslationReviewError(f"model row {row_number} does not match the queue key")
        if queue_row["source_text_sha256"] != source_hash:
            raise TranslationReviewError(f"model row {row_number} source hash does not match queue")
        if (stage, source_hash) not in queue_by_hash:
            raise TranslationReviewError(f"model row {row_number} source hash is not in queue")
        if (stage, unique) in model_by_key:
            raise TranslationReviewError(f"duplicate model output key {(stage, unique)!r}")
        if queue_row.get("review_state") == "locked_reviewed":
            raise TranslationReviewError(
                f"model row {row_number} targets locked reviewed text; omit it"
            )
        model_by_key[(stage, unique)] = _validate_translation(queue_row, candidate)

    required_keys = {
        (int(row["stage_index"]), int(row["unique_index"]))
        for row in queue_rows
        if row.get("review_state") != "locked_reviewed"
    }
    missing_keys = sorted(required_keys - set(model_by_key))
    if missing_keys and not allow_partial:
        preview = missing_keys[:12]
        suffix = "..." if len(missing_keys) > len(preview) else ""
        raise TranslationReviewError(
            f"model output is incomplete: missing {len(missing_keys)} rows {preview!r}{suffix}; "
            "use --allow-partial only for an intentional chunk"
        )

    validated_rows = []
    for row in queue_rows:
        key = (int(row["stage_index"]), int(row["unique_index"]))
        if row.get("review_state") == "locked_reviewed":
            existing = row.get("existing_translations", [])
            if not isinstance(existing, list) or len(existing) != 1:
                raise TranslationReviewError(
                    f"queue locked row {key!r} has no single existing translation"
                )
            existing_decision = existing[0]
            validated_rows.append(
                {
                    "stage_index": key[0],
                    "unique_index": key[1],
                    "source_text_sha256": str(row["source_text_sha256"]),
                    "translation": existing_decision["translation"],
                    "translation_action": existing_decision["translation_action"],
                    "glossary_refs": sorted(existing_decision.get("glossary_refs", [])),
                    "glossary_exceptions": sorted(existing_decision.get("glossary_exceptions", [])),
                    "notes": "\n".join(existing_decision.get("notes", [])),
                    "decision_source": "committed_reviewed",
                }
            )
        elif key in model_by_key:
            validated = dict(model_by_key[key])
            validated["decision_source"] = "local_model_draft"
            validated_rows.append(validated)
    missing_rows = [
        {
            "stage_index": stage,
            "unique_index": unique,
            "reason": "missing_model_output",
        }
        for stage, unique in missing_keys
    ]
    return validated_rows, model_by_key, missing_rows


def build_stage_drafts(
    queue_rows: Sequence[Mapping[str, object]],
    validated_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    draft_dir: Path,
    *,
    force: bool,
) -> list[Path]:
    by_stage: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for row in queue_rows:
        by_stage[int(row["stage_index"])].append(row)
    written: list[Path] = []
    for stage, rows in sorted(by_stage.items()):
        rows = sorted(rows, key=lambda row: int(row["unique_index"]))
        if any(
            (stage, int(row["unique_index"])) not in validated_by_key
            for row in rows
        ):
            continue
        translations = []
        refs_by_index: dict[str, list[str]] = {}
        exceptions_by_index: dict[str, list[str]] = {}
        notes_by_index: dict[str, str] = {}
        statuses_by_index: dict[str, str] = {}
        for row in rows:
            index = int(row["unique_index"])
            decision = validated_by_key[(stage, index)]
            translations.append(str(decision["translation"]))
            refs = list(decision.get("glossary_refs", []))
            exceptions = list(decision.get("glossary_exceptions", []))
            notes = str(decision.get("notes", ""))
            if refs:
                refs_by_index[str(index)] = refs
            if exceptions:
                exceptions_by_index[str(index)] = exceptions
            if notes:
                notes_by_index[str(index)] = notes
            statuses_by_index[str(index)] = (
                "reviewed"
                if decision.get("decision_source") == "committed_reviewed"
                else "draft"
            )
        document: dict[str, object] = {
            "schema_version": 1,
            "draft_kind": "local_model_validated",
            "stage_index": stage,
            "ordering": "unique_index from story-dialogue-unique.jsonl",
            "editorial_status": "draft",
            "translations": translations,
            "editorial_status_by_index": statuses_by_index,
        }
        if refs_by_index:
            document["glossary_refs_by_index"] = refs_by_index
        if exceptions_by_index:
            document["glossary_exceptions_by_index"] = exceptions_by_index
        if notes_by_index:
            document["notes_by_index"] = notes_by_index
        path = draft_dir / f"stage-{stage:03d}-unique-draft.json"
        if path.exists() and not force:
            raise TranslationReviewError(f"draft exists; use --force: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def main() -> int:
    args = _parse_args()
    input_path = _output(args.input)
    model_path = _output(args.model_output) if args.model_output else None
    output_path = _output(args.output)
    report_path = _output(args.report)
    draft_dir = _output(args.draft_dir)
    targets = [output_path, report_path, *draft_dir.glob("stage-*-unique-draft.json")]
    if not args.force and any(path.exists() for path in targets):
        raise TranslationReviewError("validation output exists; use --force")
    queue_rows = load_queue(input_path)
    model_rows = _load_model_rows(queue_rows, model_path)
    validated_rows, model_by_key, missing_rows = validate_model_output(
        queue_rows, model_rows, allow_partial=args.allow_partial
    )
    validated_by_key = {
        (int(row["stage_index"]), int(row["unique_index"])): row
        for row in validated_rows
    }
    drafts = build_stage_drafts(
        queue_rows,
        validated_by_key,
        draft_dir,
        force=args.force,
    )
    _write_jsonl(output_path, validated_rows)
    stage_counts = defaultdict(int)
    for row in model_by_key.values():
        stage_counts[int(row["stage_index"])] += 1
    report = {
        "schema_version": 1,
        "kind": "story_dialogue_local_model_validation",
        "status": "partial" if missing_rows else "validated",
        "input": str(input_path.relative_to(PROJECT_ROOT)),
        "model_output": str(model_path.relative_to(PROJECT_ROOT)) if model_path else None,
        "counts": {
            "queue_unique_count": len(queue_rows),
            "model_output_count": len(model_rows),
            "validated_count": len(validated_rows),
            "model_draft_count": len(model_by_key),
            "missing_model_count": len(missing_rows),
            "complete_stage_count": len(drafts),
        },
        "model_rows_by_stage": dict(sorted(stage_counts.items())),
        "missing_rows": missing_rows,
        "drafts": [str(path.relative_to(PROJECT_ROOT)) for path in drafts],
        "promotion": {
            "allowed": False,
            "next_step": "human glossary/layout review, then build_story_dialogue_stage_translation.py",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "local model output validated: "
        f"queue={len(queue_rows)} model={len(model_rows)} "
        f"validated={len(validated_rows)} missing={len(missing_rows)} "
        f"complete_stages={len(drafts)}"
    )
    print(f"validated JSONL: {output_path}")
    print(f"validation report: {report_path}")
    if drafts:
        print(f"stage drafts: {draft_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"local model validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
