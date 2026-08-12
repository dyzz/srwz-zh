#!/usr/bin/env python3
"""Run a source-first editorial audit over every v0.2 LIBRARY text.

This is an audit, not an automatic corpus promotion step.  It compares the
immutable Japanese field with the current Codex-reviewed candidate, includes
the sibling DSCR/DSC2 field when one exists, and asks the locked translation
snapshot to either keep the candidate byte-for-byte or return a complete
replacement.  All billable artifacts remain below ``work/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    import run_aliyun_library_v02_batch as api
    from srwz.library import LibraryScopeError
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools import run_aliyun_library_v02_batch as api
    from tools.srwz.library import LibraryScopeError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = (
    PROJECT_ROOT / "work/review/editorial/stage0-library/candidate.json"
)
DEFAULT_QUEUE = PROJECT_ROOT / "work/review/aliyun/library-v0.2/source-queue.jsonl"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "work/review/editorial/library-v0.2-full-audit-v1"
)
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_MODEL = "deepseek-v4-flash-0731"
PROSE_TAGS = {"DSCR", "DSC2"}
ISSUE_CODES = {
    "accuracy",
    "omission",
    "addition",
    "proper_name",
    "terminology",
    "grammar",
    "fluency",
    "consistency",
    "punctuation",
    "spacing",
    "format",
}

# Metadata was first requested before ``compact_siblings`` was restricted to
# prose rows.  Those responses can contain a robot/character description in a
# short-name field, so they are deliberately incompatible with the corrected
# prompt.  Prose attempt artifacts were generated with the intended sibling
# context and remain reusable.
PROMPT_VERSIONS = {"metadata": 2, "prose": 1}


@dataclass(frozen=True)
class Job:
    phase: str
    offset: int
    count: int

    @property
    def key(self) -> str:
        return f"{self.phase}-{self.offset:04d}-{self.count:04d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--metadata-chunk-size", type=int, default=80)
    parser.add_argument("--prose-chunk-size", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--phase", choices=("metadata", "prose"), action="append")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def load_rows(
    candidate_path: Path, queue_path: Path
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    document = json.loads(candidate_path.read_text(encoding="utf-8"))
    rows = [
        row
        for row in document.get("rows", [])
        if row.get("category") == "library"
    ]
    queue = api.read_jsonl(queue_path)
    api.validate_queue(queue)
    queue_by_id = {str(row["id"]): row for row in queue}
    if len(rows) != 2709 or len(queue_by_id) != 2709:
        raise LibraryScopeError("full editorial audit requires exactly 2709 rows")
    ids = [str(row.get("id", "")) for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(queue_by_id):
        raise LibraryScopeError("candidate/source queue ID set mismatch")
    for row in rows:
        source = queue_by_id[str(row["id"])]
        if row.get("source_text_sha256") != source.get("source_text_sha256"):
            raise LibraryScopeError(f"source hash mismatch: {row['id']}")
        if row.get("source_text") != source.get("source_text"):
            raise LibraryScopeError(f"source text mismatch: {row['id']}")
    return rows, queue_by_id


def phase_of(row: Mapping[str, object]) -> str:
    tags = set(row.get("tags", []))
    return "prose" if tags & PROSE_TAGS else "metadata"


def phase_rows(
    rows: Sequence[dict[str, object]], phase: str
) -> list[dict[str, object]]:
    return [row for row in rows if phase_of(row) == phase]


def plan_jobs(
    rows: Sequence[dict[str, object]],
    phases: Sequence[str],
    *,
    metadata_chunk_size: int,
    prose_chunk_size: int,
) -> tuple[list[Job], dict[str, int]]:
    jobs: list[Job] = []
    counts: dict[str, int] = {}
    for phase in phases:
        selected = phase_rows(rows, phase)
        counts[phase] = len(selected)
        chunk_size = (
            prose_chunk_size if phase == "prose" else metadata_chunk_size
        )
        for offset in range(0, len(selected), chunk_size):
            jobs.append(
                Job(phase, offset, min(chunk_size, len(selected) - offset))
            )
    return jobs, counts


def sibling_index(
    rows: Sequence[dict[str, object]],
) -> dict[tuple[str, int], list[dict[str, object]]]:
    result: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in rows:
        if phase_of(row) != "prose":
            continue
        for reference in row.get("references", []):
            if not isinstance(reference, Mapping):
                continue
            domain = reference.get("domain")
            entry_index = reference.get("entry_index")
            if isinstance(domain, str) and isinstance(entry_index, int):
                result.setdefault((domain, entry_index), []).append(row)
    return result


def compact_terms(row: Mapping[str, object]) -> list[dict[str, object]]:
    terms: list[dict[str, object]] = []
    for term in row.get("glossary_terms", []):
        if not isinstance(term, Mapping):
            continue
        target = term.get("translation")
        matched = term.get("matched_source_terms")
        if not isinstance(target, str) or not target:
            continue
        terms.append(
            {
                "id": term.get("id"),
                "source": matched if isinstance(matched, list) else [],
                "target": target,
                "status": term.get("status"),
                "required": term.get("enforce") is True,
            }
        )
    return terms


def compact_siblings(
    row: Mapping[str, object],
    index: Mapping[tuple[str, int], Sequence[dict[str, object]]],
) -> list[dict[str, object]]:
    if phase_of(row) != "prose":
        return []
    values: dict[str, dict[str, object]] = {}
    row_id = str(row["id"])
    for reference in row.get("references", []):
        if not isinstance(reference, Mapping):
            continue
        domain = reference.get("domain")
        entry_index = reference.get("entry_index")
        if not isinstance(domain, str) or not isinstance(entry_index, int):
            continue
        for sibling in index.get((domain, entry_index), []):
            sibling_id = str(sibling["id"])
            if sibling_id == row_id:
                continue
            values[sibling_id] = {
                "id": sibling_id,
                "tags": sibling.get("tags", []),
                "jp": sibling.get("source_text", ""),
                "zh": sibling.get("candidate_translation", ""),
            }
    return list(values.values())


def build_messages(
    rows: Sequence[dict[str, object]],
    siblings: Mapping[tuple[str, int], Sequence[dict[str, object]]],
) -> list[dict[str, str]]:
    items = [
        {
            "id": row["id"],
            "tags": row.get("tags", []),
            "jp": row["source_text"],
            "zh": row["candidate_translation"],
            "terms": compact_terms(row),
            "siblings": compact_siblings(row, siblings),
        }
        for row in rows
    ]
    system = """你是《超级机器人大战Z》简体中文图鉴的终审校对。逐条对照不可变日文原文和当前中文候选，检查事实、语义、专名、术语、语法、流畅度、标点、空格，以及同一条目DSCR/DSC2长短介绍的一致性。

硬性要求：
1. 只返回一个JSON对象：{"reviews":[{"id":"library-text/...","verdict":"keep|revise","text":"","issues":[],"reason":"简短理由"}]}。不得输出Markdown或额外字段。
2. ID必须恰好各返回一次且顺序不变。
3. 当前译文准确自然时必须keep，text必须为空字符串；有任何确定问题则revise，text必须给出完整最终中文，不得只给修改片段。
4. 不增删原文事实，不凭作品知识擅自补充。terms中的已批准译名优先；不得把不同人物、机体、舰船和组织混为一谈。
5. 原文换行只是游戏硬换行；最终中文必须是单段，不得含换行、日文假名、日式直角引号或三个英文句点。
6. 作品标题用《》；人物话语、称号、武器名、招式名、作战名及一般强调用“”。英文型号内部不要插入多余空格。
7. siblings只作同条目长短版本参照。若日文正文去除硬换行后完全相同，中文必须完全相同；若长版比短版多事实，应保持共同部分的术语和表述一致。
8. issues只能从accuracy, omission, addition, proper_name, terminology, grammar, fluency, consistency, punctuation, spacing, format中选择。keep时issues必须为空；revise时至少一项。
9. reason用简体中文简述核对依据，不得声称查阅了未提供的资料。"""
    user = "请终审以下条目：\n" + json.dumps(
        items, ensure_ascii=False, separators=(",", ":")
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_reviews(
    response_text: str, rows: Sequence[Mapping[str, object]]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    try:
        document = json.loads(response_text)
    except json.JSONDecodeError as exc:
        return [], {"json_valid": False, "error": str(exc)}
    reviews = document.get("reviews") if isinstance(document, Mapping) else None
    if not isinstance(reviews, list):
        return [], {"json_valid": True, "error": "reviews is not an array"}
    expected = [str(row["id"]) for row in rows]
    actual: list[str] = []
    parsed: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    candidates = {str(row["id"]): str(row["candidate_translation"]) for row in rows}
    for index, value in enumerate(reviews):
        context = f"item {index + 1}"
        if not isinstance(value, Mapping) or set(value) != {
            "id",
            "verdict",
            "text",
            "issues",
            "reason",
        }:
            errors[context] = "malformed fields"
            continue
        row_id = value.get("id")
        verdict = value.get("verdict")
        text = value.get("text")
        issues = value.get("issues")
        reason = value.get("reason")
        if not isinstance(row_id, str):
            errors[context] = "id is not a string"
            continue
        actual.append(row_id)
        if verdict not in {"keep", "revise"}:
            errors[row_id] = "invalid verdict"
            continue
        if not isinstance(text, str) or not isinstance(reason, str) or not reason.strip():
            errors[row_id] = "text/reason is malformed"
            continue
        if not isinstance(issues, list) or not all(
            isinstance(issue, str) and issue in ISSUE_CODES for issue in issues
        ):
            errors[row_id] = "issues are malformed"
            continue
        if len(issues) != len(set(issues)):
            errors[row_id] = "issues contain duplicates"
            continue
        candidate = candidates.get(row_id, "")
        if verdict == "keep":
            if text or issues:
                errors[row_id] = "keep must have empty text and issues"
                continue
            final_text = candidate
        else:
            final_text = text.strip()
            if not issues or not final_text:
                errors[row_id] = "revise must change the complete text"
                continue
            # Some otherwise valid model responses mark a row ``revise`` for
            # a suspected issue and then return the candidate unchanged.  It
            # has proposed no actionable edit, so record the result as keep
            # rather than discarding coverage or pretending a change exists.
            if final_text == candidate:
                verdict = "keep"
                issues = []
            if (
                "\n" in final_text
                or "\r" in final_text
                or api.KANA_PATTERN.search(final_text)
                or any(mark in final_text for mark in ("「", "」", "『", "』"))
                or "..." in final_text
            ):
                errors[row_id] = "revised text violates format policy"
                continue
        parsed.append(
            {
                "schema_version": 1,
                "id": row_id,
                "verdict": verdict,
                "translation": final_text,
                "issues": issues,
                "reason": reason.strip(),
            }
        )
    audit = {
        "json_valid": True,
        "review_item_count": len(reviews),
        "well_formed_item_count": len(parsed),
        "exact_id_order": actual == expected,
        "exact_id_set": (
            len(actual) == len(expected)
            and len(set(actual)) == len(actual)
            and set(actual) == set(expected)
        ),
        "missing_ids": sorted(set(expected) - set(actual)),
        "unexpected_ids": sorted(set(actual) - set(expected)),
        "duplicate_ids": sorted(
            row_id for row_id in set(actual) if actual.count(row_id) > 1
        ),
        "errors": errors,
    }
    return parsed, audit


def attempt_dir(output_dir: Path, job: Job, attempt: int) -> Path:
    return output_dir / "batches" / job.key / f"attempt-{attempt}"


def strict_attempt_dir(output_dir: Path, job: Job, model: str) -> Path | None:
    parent = output_dir / "batches" / job.key
    for directory in sorted(parent.glob("attempt-*")):
        if artifact_ok(directory, job, model):
            return directory
    return None


def prompt_version_ok(manifest: Mapping[str, object], job: Job) -> bool:
    value = manifest.get("prompt_version")
    if value is None:
        return job.phase == "prose" and PROMPT_VERSIONS[job.phase] == 1
    return value == PROMPT_VERSIONS[job.phase]


def artifact_ok(directory: Path, job: Job, model: str) -> bool:
    manifest_path = directory / "manifest.json"
    reviews_path = directory / "reviews.jsonl"
    if not manifest_path.is_file() or not reviews_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reviews = api.read_jsonl(reviews_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        manifest.get("requested_model") == model
        and prompt_version_ok(manifest, job)
        and manifest.get("phase") == job.phase
        and manifest.get("offset") == job.offset
        and manifest.get("selected_count") == job.count
        and manifest.get("validation", {}).get("strict_passed") is True
        and len(reviews) == job.count
    )


def execute_job(
    job: Job,
    *,
    all_rows: Sequence[dict[str, object]],
    siblings: Mapping[tuple[str, int], Sequence[dict[str, object]]],
    output_dir: Path,
    env: Mapping[str, str],
    model: str,
    max_tokens: int,
    timeout: float,
) -> tuple[Path, bool]:
    selected = phase_rows(all_rows, job.phase)[job.offset : job.offset + job.count]
    strict_directory = strict_attempt_dir(output_dir, job, model)
    if strict_directory is not None:
        return strict_directory, True
    # Reparse previous raw responses after validator-only fixes.  This never
    # changes the billable evidence and avoids requesting the same review a
    # second time when the response already contains every source ID.
    parent = output_dir / "batches" / job.key
    for previous in sorted(parent.glob("attempt-*")):
        response_path = previous / "response.json"
        manifest_path = previous / "manifest.json"
        if not response_path.is_file() or not manifest_path.is_file():
            continue
        previous_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        if not prompt_version_ok(previous_manifest, job):
            continue
        response = json.loads(response_path.read_text(encoding="utf-8"))
        reviews, format_audit = parse_reviews(str(response["response_text"]), selected)
        strict_passed = bool(format_audit.get("exact_id_set")) and not format_audit.get(
            "errors"
        ) and len(reviews) == len(selected)
        missing_ids = format_audit.get("missing_ids", [])
        if (
            not strict_passed
            and isinstance(missing_ids, list)
            and missing_ids
            and not format_audit.get("unexpected_ids")
            and not format_audit.get("duplicate_ids")
            and not format_audit.get("errors")
        ):
            missing_set = {str(row_id) for row_id in missing_ids}
            supplemental_rows = [
                row for row in selected if str(row["id"]) in missing_set
            ]
            if len(supplemental_rows) == len(missing_set):
                supplemental_messages = build_messages(supplemental_rows, siblings)
                supplemental_payload = api.request_payload(
                    model, supplemental_messages, max_tokens
                )
                supplemental_dir = previous / "supplemental-missing"
                if supplemental_dir.exists() and any(supplemental_dir.iterdir()):
                    supplemental_response = json.loads(
                        (supplemental_dir / "response.json").read_text(encoding="utf-8")
                    )
                    supplemental_text = str(supplemental_response["response_text"])
                else:
                    supplemental_dir.mkdir(parents=True, exist_ok=True)
                    write_json(
                        supplemental_dir / "request.json",
                        {
                            "schema_version": 1,
                            "model": model,
                            "selected_ids": [row["id"] for row in supplemental_rows],
                            "messages": supplemental_messages,
                            "temperature": supplemental_payload["temperature"],
                            "max_tokens": max_tokens,
                        },
                    )
                    supplemental_call = api.call_api(
                        api_key=str(env["DASHSCOPE_API_KEY"]),
                        base_url=api.validate_base_url(
                            str(env["DASHSCOPE_BASE_URL"])
                        ),
                        payload=supplemental_payload,
                        timeout=timeout,
                    )
                    supplemental_text = supplemental_call.response_text
                    write_json(
                        supplemental_dir / "response.json",
                        {"response_text": supplemental_text},
                    )
                supplemental_reviews, supplemental_audit = parse_reviews(
                    supplemental_text, supplemental_rows
                )
                write_jsonl(supplemental_dir / "reviews.jsonl", supplemental_reviews)
                write_json(supplemental_dir / "validation.json", supplemental_audit)
                if (
                    supplemental_audit.get("exact_id_set") is True
                    and not supplemental_audit.get("errors")
                    and len(supplemental_reviews) == len(supplemental_rows)
                ):
                    combined_by_id = {
                        str(review["id"]): review
                        for review in [*reviews, *supplemental_reviews]
                    }
                    reviews = [
                        combined_by_id[str(row["id"])] for row in selected
                    ]
                    format_audit["supplemented_missing_ids"] = sorted(missing_set)
                    format_audit["combined_exact_id_set"] = True
                    strict_passed = True
        write_jsonl(previous / "reviews.jsonl", reviews)
        manifest = previous_manifest
        manifest["format_audit"] = format_audit
        manifest["validation"] = {
            "passed_count": len(reviews),
            "strict_passed": strict_passed,
        }
        manifest["reparsed_with_current_validator"] = True
        write_json(manifest_path, manifest)
        if strict_passed:
            return previous, True

    attempt = 1
    while attempt_dir(output_dir, job, attempt).exists():
        attempt += 1
    directory = attempt_dir(output_dir, job, attempt)
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(f"refusing to overwrite audit attempt: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    messages = build_messages(selected, siblings)
    payload = api.request_payload(model, messages, max_tokens)
    write_json(
        directory / "request.json",
        {
            "schema_version": 1,
            "model": model,
            "phase": job.phase,
            "offset": job.offset,
            "selected_ids": [row["id"] for row in selected],
            "messages": messages,
            "temperature": payload["temperature"],
            "max_tokens": max_tokens,
        },
    )
    call = api.call_api(
        api_key=str(env["DASHSCOPE_API_KEY"]),
        base_url=api.validate_base_url(str(env["DASHSCOPE_BASE_URL"])),
        payload=payload,
        timeout=timeout,
    )
    write_json(directory / "response.json", {"response_text": call.response_text})
    reviews, format_audit = parse_reviews(call.response_text, selected)
    write_jsonl(directory / "reviews.jsonl", reviews)
    strict_passed = bool(format_audit.get("exact_id_set")) and not format_audit.get(
        "errors"
    ) and len(reviews) == len(selected)
    write_json(
        directory / "manifest.json",
        {
            "schema_version": 1,
            "kind": "library_v0.2_full_editorial_audit_batch",
            "requested_model": model,
            "response_model": call.response_model,
            "prompt_version": PROMPT_VERSIONS[job.phase],
            "phase": job.phase,
            "offset": job.offset,
            "selected_count": len(selected),
            "run": {
                "finish_reason": call.finish_reason,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "cached_tokens": call.cached_tokens,
                "elapsed_seconds": round(call.elapsed_seconds, 6),
            },
            "format_audit": format_audit,
            "validation": {
                "passed_count": len(reviews),
                "strict_passed": strict_passed,
            },
        },
    )
    return directory, strict_passed


def aggregate(
    *,
    output_dir: Path,
    jobs: Sequence[Job],
    all_rows: Sequence[dict[str, object]],
    model: str,
    candidate_path: Path,
    queue_path: Path,
) -> dict[str, object]:
    by_id: dict[str, dict[str, object]] = {}
    batch_manifests: list[dict[str, object]] = []
    for job in jobs:
        directory = strict_attempt_dir(output_dir, job, model)
        if directory is None:
            raise LibraryScopeError(f"audit batch is not strict: {job.key}")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        batch_manifests.append(manifest)
        for review in api.read_jsonl(directory / "reviews.jsonl"):
            row_id = str(review["id"])
            if row_id in by_id:
                raise LibraryScopeError(f"duplicate aggregate review: {row_id}")
            by_id[row_id] = review
    selected_ids = {
        str(row["id"])
        for row in all_rows
        if phase_of(row) in {job.phase for job in jobs}
    }
    if set(by_id) != selected_ids:
        raise LibraryScopeError("aggregate audit coverage mismatch")
    ordered = [by_id[str(row["id"])] for row in all_rows if str(row["id"]) in by_id]
    aggregate_path = output_dir / "aggregate/reviews.jsonl"
    write_jsonl(aggregate_path, ordered)
    verdicts = {"keep": 0, "revise": 0}
    issue_counts = {issue: 0 for issue in sorted(ISSUE_CODES)}
    for review in ordered:
        verdicts[str(review["verdict"])] += 1
        for issue in review["issues"]:
            issue_counts[str(issue)] += 1
    manifest = {
        "schema_version": 1,
        "kind": "library_v0.2_full_editorial_audit",
        "status": "machine_editorial_audit_complete_manual_adjudication_pending",
        "model": model,
        "inputs": {
            "candidate": {
                "path": str(candidate_path.relative_to(PROJECT_ROOT)),
                "sha256": sha256_file(candidate_path),
            },
            "source_queue": {
                "path": str(queue_path.relative_to(PROJECT_ROOT)),
                "sha256": sha256_file(queue_path),
            },
        },
        "coverage": {
            "reviewed_count": len(ordered),
            "expected_count": len(selected_ids),
            "exact_id_set": set(by_id) == selected_ids,
        },
        "verdicts": verdicts,
        "issue_counts": issue_counts,
        "run": {
            "batch_count": len(jobs),
            "prompt_tokens": sum(m["run"]["prompt_tokens"] for m in batch_manifests),
            "completion_tokens": sum(
                m["run"]["completion_tokens"] for m in batch_manifests
            ),
            "cached_tokens": sum(m["run"]["cached_tokens"] for m in batch_manifests),
            "elapsed_seconds_sum": round(
                sum(m["run"]["elapsed_seconds"] for m in batch_manifests), 6
            ),
        },
        "artifacts": {
            "reviews": str(aggregate_path.relative_to(PROJECT_ROOT)),
            "reviews_sha256": sha256_file(aggregate_path),
        },
    }
    write_json(output_dir / "aggregate/manifest.json", manifest)
    return manifest


def main() -> int:
    args = parse_args()
    if min(
        args.workers,
        args.metadata_chunk_size,
        args.prose_chunk_size,
        args.max_tokens,
    ) <= 0 or args.timeout <= 0:
        raise LibraryScopeError("workers, chunk sizes, tokens, and timeout must be positive")
    candidate_path = project_path(args.candidate).resolve()
    queue_path = project_path(args.queue).resolve()
    output_dir = project_path(args.output_dir).resolve()
    if PROJECT_ROOT not in output_dir.parents or "work" not in output_dir.parts:
        raise LibraryScopeError("audit output must remain below project work/")
    rows, _queue = load_rows(candidate_path, queue_path)
    phases = args.phase or ["metadata", "prose"]
    jobs, counts = plan_jobs(
        rows,
        phases,
        metadata_chunk_size=args.metadata_chunk_size,
        prose_chunk_size=args.prose_chunk_size,
    )
    print(f"audit plan: counts={counts} jobs={len(jobs)} model={args.model}")
    if args.dry_run:
        return 0
    env = api.load_env(project_path(args.env_file).resolve())
    if not env.get("DASHSCOPE_API_KEY"):
        raise LibraryScopeError("DASHSCOPE_API_KEY is missing or empty")
    api.validate_base_url(env.get("DASHSCOPE_BASE_URL", ""))
    siblings = sibling_index(rows)
    started = time.perf_counter()
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                execute_job,
                job,
                all_rows=rows,
                siblings=siblings,
                output_dir=output_dir,
                env=env,
                model=args.model,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            ): job
            for job in jobs
        }
        completed = 0
        for future in as_completed(futures):
            job = futures[future]
            try:
                _directory, strict = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve failed batch evidence
                failures.append(f"{job.key}: {exc}")
                strict = False
            completed += 1
            print(
                f"[{completed}/{len(jobs)}] {job.key} strict={strict}",
                flush=True,
            )
    if failures:
        write_json(output_dir / "run-failures.json", {"failures": failures})
        raise LibraryScopeError(f"{len(failures)} editorial audit batches failed")
    manifest = aggregate(
        output_dir=output_dir,
        jobs=jobs,
        all_rows=rows,
        model=args.model,
        candidate_path=candidate_path,
        queue_path=queue_path,
    )
    print(
        f"audit complete: reviewed={manifest['coverage']['reviewed_count']} "
        f"verdicts={manifest['verdicts']} elapsed={time.perf_counter()-started:.1f}s"
    )
    print(output_dir / "aggregate/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
