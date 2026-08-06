#!/usr/bin/env python3
"""Apply auditable editorial fixes and build drafts for the remaining stages.

The DeepSeek batch is deliberately not promoted into ``corpus/zh``.  This
tool first emits a complete strict-failure review queue.  Once every failure
has an explicit deterministic repair or glossary exception, it writes
validator-clean per-stage draft documents plus a conservative semantic-risk
queue for later line editing.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping, Sequence

try:
    from import_story_dialogue_local_model_batch import (
        _validate_translation,
        build_stage_drafts,
        load_queue,
        validate_model_output,
    )
    from run_aliyun_remaining_story_dialogue_stages import (
        MODEL_DIR,
        QUEUE,
        ROOT,
        RUN_ROOT,
        stage_output,
    )
    from srwz.translation_review import TranslationReviewError
except ModuleNotFoundError:  # pragma: no cover
    from tools.import_story_dialogue_local_model_batch import (
        _validate_translation,
        build_stage_drafts,
        load_queue,
        validate_model_output,
    )
    from tools.run_aliyun_remaining_story_dialogue_stages import (
        MODEL_DIR,
        QUEUE,
        ROOT,
        RUN_ROOT,
        stage_output,
    )
    from tools.srwz.translation_review import TranslationReviewError


OUTPUT_ROOT = RUN_ROOT / "finalized"
DEFAULT_DECISIONS = RUN_ROOT / "editorial-decisions.json"
ASCII_WORD = re.compile(r"[A-Za-z]{3,}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def key_for(row: Mapping[str, object]) -> tuple[int, int]:
    return int(row["stage_index"]), int(row["unique_index"])


def append_note(candidate: dict[str, object], note: str) -> None:
    prior = str(candidate.get("notes", "")).strip()
    candidate["notes"] = f"{prior}\n{note}".strip()


def decision_document(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {
            "schema_version": 1,
            "term_replacements": [],
            "text_replacements": [],
            "term_exceptions": [],
            "row_overrides": [],
            "glossary_exceptions": [],
            "semantic_allowlist": {"ascii_terms": []},
        }
    value = read_json(path)
    if value.get("schema_version") != 1:
        raise ValueError(f"unsupported editorial decision schema: {path}")
    return value


def scoped_keys(raw: Mapping[str, object]) -> set[tuple[int, int]] | None:
    keys = raw.get("keys")
    if keys is None:
        return None
    if not isinstance(keys, list) or not all(isinstance(item, str) for item in keys):
        raise ValueError("decision keys must be an array of 'stage:index' strings")
    result: set[tuple[int, int]] = set()
    for item in keys:
        stage, unique = item.split(":", 1)
        result.add((int(stage), int(unique)))
    return result


def apply_decisions(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    candidates: dict[tuple[int, int], dict[str, object]],
    decisions: Mapping[str, object],
) -> list[dict[str, object]]:
    audit: list[dict[str, object]] = []
    for raw in decisions.get("term_replacements", []):
        if not isinstance(raw, Mapping):
            raise ValueError("term_replacements entries must be objects")
        term_id = str(raw["term_id"])
        find = str(raw["find"])
        replace = str(raw["replace"])
        reason = str(raw["reason"])
        scope = scoped_keys(raw)
        if not find or not replace or not reason:
            raise ValueError("term replacement find/replace/reason must be non-empty")
        matched = 0
        for key, candidate in sorted(candidates.items()):
            if scope is not None and key not in scope:
                continue
            terms = {
                str(term["id"]): term
                for term in queue_by_key[key].get("glossary_terms", [])
                if isinstance(term, Mapping)
            }
            term = terms.get(term_id)
            if term is None or not term.get("enforce"):
                continue
            canonical = str(term.get("translation", ""))
            translation = str(candidate["translation"])
            if canonical in translation or find not in translation:
                continue
            candidate["translation"] = translation.replace(find, replace)
            append_note(candidate, reason)
            audit.append(
                {
                    "stage_index": key[0],
                    "unique_index": key[1],
                    "kind": "term_replacement",
                    "term_id": term_id,
                    "before": translation,
                    "after": candidate["translation"],
                    "reason": reason,
                }
            )
            matched += 1
        if matched == 0:
            raise ValueError(f"term replacement matched no rows: {term_id} {find!r}")

    for raw in decisions.get("text_replacements", []):
        if not isinstance(raw, Mapping):
            raise ValueError("text_replacements entries must be objects")
        find = str(raw["find"])
        replace = str(raw["replace"])
        reason = str(raw["reason"])
        scope = scoped_keys(raw)
        if scope is None:
            raise ValueError("text replacements must have explicit keys")
        if not find or not replace or not reason or find == replace:
            raise ValueError("text replacement find/replace/reason must be distinct and non-empty")
        unmatched: list[tuple[int, int]] = []
        for key in sorted(scope):
            candidate = candidates.get(key)
            if candidate is None or find not in str(candidate["translation"]):
                unmatched.append(key)
                continue
            translation = str(candidate["translation"])
            candidate["translation"] = translation.replace(find, replace)
            append_note(candidate, reason)
            audit.append(
                {
                    "stage_index": key[0],
                    "unique_index": key[1],
                    "kind": "text_replacement",
                    "before": translation,
                    "after": candidate["translation"],
                    "reason": reason,
                }
            )
        if unmatched:
            rendered = ", ".join(f"{stage}:{unique}" for stage, unique in unmatched)
            raise ValueError(f"text replacement did not match scoped rows: {rendered}")

    for raw in decisions.get("term_exceptions", []):
        if not isinstance(raw, Mapping):
            raise ValueError("term_exceptions entries must be objects")
        term_id = str(raw["term_id"])
        reason = str(raw["reason"])
        scope = scoped_keys(raw)
        matched = 0
        for key, candidate in sorted(candidates.items()):
            if scope is not None and key not in scope:
                continue
            terms = {
                str(term["id"]): term
                for term in queue_by_key[key].get("glossary_terms", [])
                if isinstance(term, Mapping)
            }
            term = terms.get(term_id)
            if term is None or not term.get("enforce"):
                continue
            canonical = str(term.get("translation", ""))
            if canonical in str(candidate["translation"]):
                continue
            refs = set(candidate.get("glossary_refs", []))
            exceptions = set(candidate.get("glossary_exceptions", []))
            refs.discard(term_id)
            exceptions.add(term_id)
            candidate["glossary_refs"] = sorted(refs)
            candidate["glossary_exceptions"] = sorted(exceptions)
            append_note(candidate, reason)
            audit.append(
                {
                    "stage_index": key[0],
                    "unique_index": key[1],
                    "kind": "term_exception",
                    "term_id": term_id,
                    "reason": reason,
                }
            )
            matched += 1
        if matched == 0:
            raise ValueError(f"term exception matched no rows: {term_id}")

    for raw in decisions.get("row_overrides", []):
        if not isinstance(raw, Mapping):
            raise ValueError("row_overrides entries must be objects")
        key = int(raw["stage_index"]), int(raw["unique_index"])
        candidate = candidates[key]
        before = str(candidate["translation"])
        candidate["translation"] = str(raw["translation"])
        reason = str(raw["reason"])
        append_note(candidate, reason)
        audit.append(
            {
                "stage_index": key[0],
                "unique_index": key[1],
                "kind": "row_override",
                "before": before,
                "after": candidate["translation"],
                "reason": reason,
            }
        )

    for raw in decisions.get("glossary_exceptions", []):
        if not isinstance(raw, Mapping):
            raise ValueError("glossary_exceptions entries must be objects")
        key = int(raw["stage_index"]), int(raw["unique_index"])
        term_id = str(raw["term_id"])
        reason = str(raw["reason"])
        candidate = candidates[key]
        relevant_ids = {
            str(term["id"])
            for term in queue_by_key[key].get("glossary_terms", [])
            if isinstance(term, Mapping)
        }
        if term_id not in relevant_ids:
            raise ValueError(f"irrelevant glossary exception {key}: {term_id}")
        refs = set(candidate.get("glossary_refs", []))
        exceptions = set(candidate.get("glossary_exceptions", []))
        refs.discard(term_id)
        exceptions.add(term_id)
        candidate["glossary_refs"] = sorted(refs)
        candidate["glossary_exceptions"] = sorted(exceptions)
        append_note(candidate, reason)
        audit.append(
            {
                "stage_index": key[0],
                "unique_index": key[1],
                "kind": "glossary_exception",
                "term_id": term_id,
                "reason": reason,
            }
        )
    return audit


def strict_failures(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    candidates: Mapping[tuple[int, int], Mapping[str, object]],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for key in sorted(queue_by_key):
        source = queue_by_key[key]
        candidate = candidates[key]
        try:
            _validate_translation(source, candidate)
        except TranslationReviewError as error:
            failures.append(
                {
                    "stage_index": key[0],
                    "unique_index": key[1],
                    "source_text": source["source_text"],
                    "translation": candidate["translation"],
                    "error": str(error),
                    "enforced_glossary_terms": [
                        term
                        for term in source.get("glossary_terms", [])
                        if isinstance(term, Mapping) and term.get("enforce")
                    ],
                }
            )
    return failures


def semantic_risks(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    candidates: Mapping[tuple[int, int], Mapping[str, object]],
    allowed_ascii_words: set[str] | None = None,
    allowed_unchanged_keys: set[tuple[int, int]] | None = None,
) -> list[dict[str, object]]:
    allowed_ascii_words = allowed_ascii_words or set()
    allowed_unchanged_keys = allowed_unchanged_keys or set()
    risks: list[dict[str, object]] = []
    for key in sorted(candidates):
        source = str(queue_by_key[key]["source_text"])
        translation = str(candidates[key]["translation"])
        reasons: list[str] = []
        introduced = sorted(
            set(ASCII_WORD.findall(translation))
            - set(ASCII_WORD.findall(source))
            - allowed_ascii_words
        )
        if introduced:
            reasons.append("introduced_ascii:" + ",".join(introduced))
        if (
            translation == source
            and candidates[key].get("translation_action") != "preserve"
            and key not in allowed_unchanged_keys
        ):
            reasons.append("unchanged_source")
        source_length = len(re.sub(r"\s", "", source))
        translation_length = len(re.sub(r"\s", "", translation))
        if source_length >= 12 and (
            translation_length < source_length * 0.25
            or translation_length > source_length * 2.5
        ):
            reasons.append(
                f"length_ratio:{translation_length / max(1, source_length):.3f}"
            )
        if not reasons:
            continue
        risks.append(
            {
                "stage_index": key[0],
                "unique_index": key[1],
                "reasons": reasons,
                "source_text": source,
                "translation": translation,
            }
        )
    return risks


def semantic_ascii_allowlist(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    decisions: Mapping[str, object],
) -> set[str]:
    """Return audited ASCII terms that should not create semantic-risk noise."""
    allowed: set[str] = set()
    for row in queue_by_key.values():
        for term in row.get("glossary_terms", []):
            if isinstance(term, Mapping):
                allowed.update(ASCII_WORD.findall(str(term.get("translation", ""))))
    semantic_allowlist = decisions.get("semantic_allowlist", {})
    if not isinstance(semantic_allowlist, Mapping):
        raise ValueError("semantic_allowlist must be an object")
    for raw in semantic_allowlist.get("ascii_terms", []):
        if not isinstance(raw, Mapping):
            raise ValueError("semantic_allowlist.ascii_terms entries must be objects")
        term = str(raw.get("term", ""))
        reason = str(raw.get("reason", ""))
        if not term or not reason:
            raise ValueError("semantic allowlist term/reason must be non-empty")
        words = ASCII_WORD.findall(term)
        if not words:
            raise ValueError(f"semantic allowlist term has no ASCII word: {term!r}")
        allowed.update(words)
    return allowed


def semantic_unchanged_allowlist(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    decisions: Mapping[str, object],
) -> set[tuple[int, int]]:
    semantic_allowlist = decisions.get("semantic_allowlist", {})
    if not isinstance(semantic_allowlist, Mapping):
        raise ValueError("semantic_allowlist must be an object")
    allowed: set[tuple[int, int]] = set()
    for raw in semantic_allowlist.get("unchanged_source_rows", []):
        if not isinstance(raw, Mapping):
            raise ValueError(
                "semantic_allowlist.unchanged_source_rows entries must be objects"
            )
        key_text = str(raw.get("key", ""))
        reason = str(raw.get("reason", ""))
        if not key_text or not reason:
            raise ValueError("unchanged-source allowlist key/reason must be non-empty")
        stage, unique = key_text.split(":", 1)
        key = int(stage), int(unique)
        if key not in queue_by_key:
            raise ValueError(f"unknown unchanged-source allowlist row: {key_text}")
        source = str(queue_by_key[key]["source_text"])
        if not source:
            raise ValueError(f"empty unchanged-source allowlist row: {key_text}")
        allowed.add(key)
    return allowed


def main() -> int:
    args = parse_args()
    batch_report = read_json(RUN_ROOT / "report.json")
    if batch_report.get("status") != "complete":
        raise SystemExit("remaining-stage API batch is not complete")
    stages = [int(item["stage_index"]) for item in batch_report.get("stages", [])]
    queue = [row for row in load_queue(QUEUE) if int(row["stage_index"]) in stages]
    queue_by_key = {key_for(row): row for row in queue}
    candidates: dict[tuple[int, int], dict[str, object]] = {}
    for stage in stages:
        for row in read_jsonl(stage_output(stage) / "parsed.jsonl"):
            key = key_for(row)
            if key in candidates:
                raise ValueError(f"duplicate candidate: {key}")
            candidates[key] = row
    if set(candidates) != set(queue_by_key):
        raise ValueError("remaining-stage candidate coverage does not match queue")

    decisions_path = args.decisions if args.decisions.is_absolute() else ROOT / args.decisions
    decisions = decision_document(decisions_path)
    audit = apply_decisions(queue_by_key, candidates, decisions)
    failures = strict_failures(queue_by_key, candidates)
    write_jsonl(OUTPUT_ROOT / "editorial-audit.jsonl", audit)
    write_jsonl(OUTPUT_ROOT / "strict-failure-review.jsonl", failures)
    if failures:
        write_json(
            OUTPUT_ROOT / "report.json",
            {
                "schema_version": 1,
                "kind": "aliyun_remaining_story_dialogue_drafts",
                "status": "strict_failures_pending",
                "stage_count": len(stages),
                "candidate_count": len(candidates),
                "editorial_decision_count": len(audit),
                "strict_failure_count": len(failures),
                "strict_failure_review": str(
                    (OUTPUT_ROOT / "strict-failure-review.jsonl").relative_to(ROOT)
                ),
            },
        )
        print(f"strict_failures={len(failures)} decisions={len(audit)}")
        return 2

    merged = [candidates[key] for key in sorted(candidates)]
    validated, validated_by_key, missing = validate_model_output(queue, merged)
    if missing or len(validated_by_key) != len(queue):
        raise ValueError("final validated coverage is incomplete")
    write_jsonl(OUTPUT_ROOT / "merged-model-output.jsonl", merged)
    write_jsonl(OUTPUT_ROOT / "validated.jsonl", validated)
    drafts = build_stage_drafts(
        queue, validated_by_key, OUTPUT_ROOT / "drafts", force=args.force
    )
    allowed_ascii_words = semantic_ascii_allowlist(queue_by_key, decisions)
    allowed_unchanged_keys = semantic_unchanged_allowlist(queue_by_key, decisions)
    risks = semantic_risks(
        queue_by_key,
        validated_by_key,
        allowed_ascii_words,
        allowed_unchanged_keys,
    )
    write_jsonl(OUTPUT_ROOT / "semantic-review.jsonl", risks)
    write_json(
        OUTPUT_ROOT / "report.json",
        {
            "schema_version": 1,
            "kind": "aliyun_remaining_story_dialogue_drafts",
            "status": "validated_draft_pending_editorial_review",
            "stage_count": len(stages),
            "validated_count": len(validated_by_key),
            "draft_count": len(drafts),
            "editorial_decision_count": len(audit),
            "strict_failure_count": 0,
            "semantic_risk_count": len(risks),
            "semantic_ascii_allowlist_word_count": len(allowed_ascii_words),
            "semantic_unchanged_allowlist_row_count": len(allowed_unchanged_keys),
            "batch_estimated_cost_cny": batch_report.get("estimated_cost_cny"),
            "artifacts": {
                "validated": str((OUTPUT_ROOT / "validated.jsonl").relative_to(ROOT)),
                "drafts": [str(path.relative_to(ROOT)) for path in drafts],
                "semantic_review": str(
                    (OUTPUT_ROOT / "semantic-review.jsonl").relative_to(ROOT)
                ),
                "editorial_audit": str(
                    (OUTPUT_ROOT / "editorial-audit.jsonl").relative_to(ROOT)
                ),
            },
            "promotion": {
                "allowed": False,
                "next_step": "editorial semantic review before writing corpus/zh",
            },
        },
    )
    print(
        f"validated={len(validated_by_key)} drafts={len(drafts)} "
        f"semantic_risks={len(risks)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
