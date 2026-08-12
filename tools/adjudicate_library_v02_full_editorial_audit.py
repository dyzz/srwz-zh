#!/usr/bin/env python3
"""Adjudicate every proposed v0.2 LIBRARY editorial revision.

The first-pass audit is intentionally sensitive.  This second pass compares
the current candidate and proposed replacement against the immutable Japanese
source, and accepts only a demonstrable correction.  It is still an audit
artifact: promotion consumes a separately locked final-decisions file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    import run_aliyun_library_v02_batch as api
    import run_library_v02_full_editorial_audit as first_pass
    from srwz.library import LibraryScopeError
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools import run_aliyun_library_v02_batch as api
    from tools import run_library_v02_full_editorial_audit as first_pass
    from tools.srwz.library import LibraryScopeError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = first_pass.DEFAULT_CANDIDATE
DEFAULT_REVIEWS = (
    first_pass.DEFAULT_OUTPUT / "aggregate/reviews.jsonl"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "work/review/editorial/library-v0.2-adjudication-v1"
)
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_MODEL = first_pass.DEFAULT_MODEL
PROMPT_VERSION = 2
CHOICES = {"current", "proposed", "custom"}


@dataclass(frozen=True)
class Job:
    offset: int
    count: int

    @property
    def key(self) -> str:
        return f"adjudication-{self.offset:04d}-{self.count:04d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=12)
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--timeout", type=float, default=900.0)
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


def load_scope(
    candidate_path: Path, reviews_path: Path
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    document = json.loads(candidate_path.read_text(encoding="utf-8"))
    rows = [
        row for row in document.get("rows", []) if row.get("category") == "library"
    ]
    if len(rows) != 2709:
        raise LibraryScopeError("adjudication requires exactly 2709 candidate rows")
    by_id = {str(row["id"]): row for row in rows}
    reviews = api.read_jsonl(reviews_path)
    if len(reviews) != 2709 or {str(row["id"]) for row in reviews} != set(by_id):
        raise LibraryScopeError("first-pass audit coverage drift")
    proposed = [row for row in reviews if row.get("verdict") == "revise"]
    if not proposed:
        raise LibraryScopeError("first-pass audit has no revisions to adjudicate")
    return proposed, by_id


def build_messages(
    reviews: Sequence[dict[str, object]],
    candidates: Mapping[str, dict[str, object]],
) -> list[dict[str, str]]:
    no_op_repair = all(
        str(review.get("translation", ""))
        == str(candidates[str(review["id"])]["candidate_translation"])
        for review in reviews
    )
    items = []
    for review in reviews:
        row = candidates[str(review["id"])]
        item = {
                "id": review["id"],
                "tags": row.get("tags", []),
                "jp": row["source_text"],
                "current": row["candidate_translation"],
                "first_pass_issues": review.get("issues", []),
                "first_pass_reason": review.get("reason", ""),
                "terms": first_pass.compact_terms(row),
            }
        if not no_op_repair:
            item["proposed"] = review["translation"]
        items.append(item)
    choice_contract = (
        "choice只能是current或custom。初审没有产出有效改文：理由错误时选current，理由成立时必须选custom并在text中给出真正改过的完整中文。禁止选择proposed。"
        if no_op_repair
        else "current表示保留当前译文；proposed表示完整采用初审译文；两者text必须为空。只有两版都存在确定问题时才选custom，并在text给出完整最终中文。"
    )
    schema_choices = "current|custom" if no_op_repair else "current|proposed|custom"
    system = f"""你是《超级机器人大战Z》简体中文图鉴的修订裁决员。逐条对照不可变日文原文，判断初审建议是否是可证明的纠错，而不是无必要的同义改写。

硬性要求：
1. 只返回一个JSON对象：{{"decisions":[{{"id":"library-text/...","choice":"{schema_choices}","text":"","issues":[],"reason":"简短依据"}}]}}，不得输出Markdown或额外字段。
2. ID必须恰好各返回一次且顺序不变。
3. {choice_contract}
4. 没有可由日文源、给定术语或明确格式规则证明的问题时，优先current。不要仅为了句式偏好、繁简同义词或让长短版逐字一致而改写。
5. terms中required=true为硬约束；其他已批准译名仅在对应日文确实是该含义时采用。专名不得按字面普通名词化，例如地点、组织或机体名不能擅自直译。
6. 原文的『』按内容判断：作品标题用《》，人物话语、称号、武器名、招式名、作战名及一般强调用“”。
7. 不增删事实。最终文本必须为单段，不得含换行、日文假名、日式直角引号或三个英文句点。
8. issues只能从accuracy, omission, addition, proper_name, terminology, grammar, fluency, consistency, punctuation, spacing, format中选择。current可为空；proposed/custom至少一项。
9. reason必须说明日文证据或为何初审只是偏好，不得声称查阅未提供的资料。"""
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": "请裁决以下修订：\n"
            + json.dumps(items, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def parse_decisions(
    response_text: str,
    reviews: Sequence[Mapping[str, object]],
    *,
    current_by_id: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    try:
        document = json.loads(response_text)
    except json.JSONDecodeError as exc:
        return [], {"json_valid": False, "error": str(exc)}
    values = document.get("decisions") if isinstance(document, Mapping) else None
    if not isinstance(values, list):
        return [], {"json_valid": True, "error": "decisions is not an array"}
    expected = [str(row["id"]) for row in reviews]
    actual: list[str] = []
    parsed: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    normalized_non_custom_text_ids: list[str] = []
    for index, value in enumerate(values):
        context = f"item {index + 1}"
        if not isinstance(value, Mapping) or set(value) != {
            "id", "choice", "text", "issues", "reason"
        }:
            errors[context] = "malformed fields"
            continue
        row_id = value.get("id")
        choice = value.get("choice")
        text = value.get("text")
        issues = value.get("issues")
        reason = value.get("reason")
        if not isinstance(row_id, str):
            errors[context] = "id is not a string"
            continue
        actual.append(row_id)
        if choice not in CHOICES:
            errors[row_id] = "invalid choice"
            continue
        if not isinstance(text, str) or not isinstance(reason, str) or not reason.strip():
            errors[row_id] = "text/reason is malformed"
            continue
        if not isinstance(issues, list) or not all(
            isinstance(issue, str) and issue in first_pass.ISSUE_CODES
            for issue in issues
        ) or len(issues) != len(set(issues)):
            errors[row_id] = "issues are malformed"
            continue
        if choice in {"current", "proposed"} and text:
            # Some responses put a complete corrected translation in ``text``
            # while leaving the selector on current/proposed.  A non-empty
            # issue list makes the intent unambiguous, so preserve the edit as
            # a custom decision and record the schema normalization.
            if (
                choice == "current"
                and current_by_id is not None
                and text.strip() == current_by_id.get(row_id)
                and not issues
            ):
                text = ""
            elif issues:
                normalized_non_custom_text_ids.append(row_id)
                choice = "custom"
            else:
                errors[row_id] = "non-custom choice must have empty text"
                continue
        final_text = text.strip()
        if choice == "custom" and (
            not final_text
            or not issues
            or "\n" in final_text
            or "\r" in final_text
            or api.KANA_PATTERN.search(final_text)
            or any(mark in final_text for mark in ("「", "」", "『", "』"))
            or "..." in final_text
        ):
            errors[row_id] = "custom text violates policy"
            continue
        parsed.append(
            {
                "schema_version": 1,
                "id": row_id,
                "choice": choice,
                "translation": final_text,
                "issues": issues,
                "reason": reason.strip(),
            }
        )
    audit = {
        "json_valid": True,
        "decision_count": len(values),
        "well_formed_count": len(parsed),
        "exact_id_order": actual == expected,
        "exact_id_set": len(actual) == len(expected)
        and len(set(actual)) == len(actual)
        and set(actual) == set(expected),
        "missing_ids": sorted(set(expected) - set(actual)),
        "unexpected_ids": sorted(set(actual) - set(expected)),
        "duplicate_ids": sorted(
            row_id for row_id in set(actual) if actual.count(row_id) > 1
        ),
        "normalized_non_custom_text_ids": normalized_non_custom_text_ids,
        "errors": errors,
    }
    return parsed, audit


def attempt_dir(output_dir: Path, job: Job, attempt: int) -> Path:
    return output_dir / "batches" / job.key / f"attempt-{attempt}"


def artifact_ok(directory: Path, job: Job, model: str) -> bool:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        decisions = api.read_jsonl(directory / "decisions.jsonl")
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        manifest.get("requested_model") == model
        and manifest.get("prompt_version") == PROMPT_VERSION
        and manifest.get("offset") == job.offset
        and manifest.get("selected_count") == job.count
        and manifest.get("validation", {}).get("strict_passed") is True
        and len(decisions) == job.count
    )


def strict_attempt_dir(output_dir: Path, job: Job, model: str) -> Path | None:
    for directory in sorted((output_dir / "batches" / job.key).glob("attempt-*")):
        if artifact_ok(directory, job, model):
            return directory
    return None


def execute_job(
    job: Job,
    *,
    reviews: Sequence[dict[str, object]],
    candidates: Mapping[str, dict[str, object]],
    output_dir: Path,
    env: Mapping[str, str],
    model: str,
    max_tokens: int,
    timeout: float,
) -> tuple[Path, bool]:
    selected = reviews[job.offset : job.offset + job.count]
    reusable = strict_attempt_dir(output_dir, job, model)
    if reusable is not None:
        return reusable, True
    attempt = 1
    while attempt_dir(output_dir, job, attempt).exists():
        attempt += 1
    directory = attempt_dir(output_dir, job, attempt)
    directory.mkdir(parents=True, exist_ok=False)
    messages = build_messages(selected, candidates)
    payload = api.request_payload(model, messages, max_tokens)
    write_json(
        directory / "request.json",
        {
            "schema_version": 1,
            "model": model,
            "prompt_version": PROMPT_VERSION,
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
    current_by_id = {
        str(row["id"]): str(candidates[str(row["id"])]["candidate_translation"])
        for row in selected
    }
    decisions, format_audit = parse_decisions(
        call.response_text, selected, current_by_id=current_by_id
    )
    proposed_by_id = {
        str(row["id"]): str(row.get("translation", "")) for row in selected
    }
    no_op_proposed_ids = [
        str(decision["id"])
        for decision in decisions
        if (
            decision["choice"] == "proposed"
            and current_by_id[str(decision["id"])]
            == proposed_by_id[str(decision["id"])]
        )
    ]
    if no_op_proposed_ids:
        format_audit.setdefault("errors", {})["no_op_proposed_ids"] = (
            ",".join(no_op_proposed_ids)
        )
    write_jsonl(directory / "decisions.jsonl", decisions)
    strict = bool(format_audit.get("exact_id_set")) and not format_audit.get(
        "errors"
    ) and len(decisions) == len(selected)
    write_json(
        directory / "manifest.json",
        {
            "schema_version": 1,
            "kind": "library_v0.2_editorial_adjudication_batch",
            "requested_model": model,
            "response_model": call.response_model,
            "prompt_version": PROMPT_VERSION,
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
                "passed_count": len(decisions),
                "strict_passed": strict,
            },
        },
    )
    return directory, strict


def aggregate(
    *,
    output_dir: Path,
    jobs: Sequence[Job],
    reviews: Sequence[dict[str, object]],
    model: str,
    candidate_path: Path,
    reviews_path: Path,
) -> dict[str, object]:
    decisions: list[dict[str, object]] = []
    manifests: list[dict[str, object]] = []
    for job in jobs:
        directory = strict_attempt_dir(output_dir, job, model)
        if directory is None:
            raise LibraryScopeError(f"adjudication batch is not strict: {job.key}")
        decisions.extend(api.read_jsonl(directory / "decisions.jsonl"))
        manifests.append(
            json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        )
    expected_ids = [str(row["id"]) for row in reviews]
    if [str(row["id"]) for row in decisions] != expected_ids:
        raise LibraryScopeError("adjudication aggregate order/coverage drift")
    aggregate_path = output_dir / "aggregate/decisions.jsonl"
    write_jsonl(aggregate_path, decisions)
    choices = {choice: 0 for choice in sorted(CHOICES)}
    for decision in decisions:
        choices[str(decision["choice"])] += 1
    manifest = {
        "schema_version": 1,
        "kind": "library_v0.2_editorial_adjudication",
        "requested_model": model,
        "prompt_version": PROMPT_VERSION,
        "source": {
            "candidate_path": str(candidate_path.relative_to(PROJECT_ROOT)),
            "candidate_sha256": sha256_file(candidate_path),
            "first_pass_reviews_path": str(reviews_path.relative_to(PROJECT_ROOT)),
            "first_pass_reviews_sha256": sha256_file(reviews_path),
        },
        "coverage": {
            "proposed_revision_count": len(reviews),
            "adjudicated_count": len(decisions),
            "strict": len(decisions) == len(reviews),
        },
        "choices": choices,
        "usage": {
            "prompt_tokens": sum(m["run"]["prompt_tokens"] for m in manifests),
            "completion_tokens": sum(
                m["run"]["completion_tokens"] for m in manifests
            ),
            "cached_tokens": sum(m["run"]["cached_tokens"] for m in manifests),
        },
        "aggregate": {
            "path": str(aggregate_path.relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(aggregate_path),
        },
    }
    write_json(output_dir / "aggregate/manifest.json", manifest)
    return manifest


def main() -> int:
    args = parse_args()
    if min(args.workers, args.chunk_size, args.max_tokens) <= 0 or args.timeout <= 0:
        raise LibraryScopeError("workers, chunk size, tokens, and timeout must be positive")
    candidate_path = project_path(args.candidate).resolve()
    reviews_path = project_path(args.reviews).resolve()
    output_dir = project_path(args.output_dir).resolve()
    if PROJECT_ROOT not in output_dir.parents or "work" not in output_dir.parts:
        raise LibraryScopeError("adjudication output must remain below project work/")
    reviews, candidates = load_scope(candidate_path, reviews_path)
    jobs = [
        Job(offset, min(args.chunk_size, len(reviews) - offset))
        for offset in range(0, len(reviews), args.chunk_size)
    ]
    print(f"adjudication plan: revisions={len(reviews)} jobs={len(jobs)} model={args.model}")
    if args.dry_run:
        return 0
    env = api.load_env(project_path(args.env_file).resolve())
    if not env.get("DASHSCOPE_API_KEY"):
        raise LibraryScopeError("DASHSCOPE_API_KEY is missing or empty")
    api.validate_base_url(env.get("DASHSCOPE_BASE_URL", ""))
    started = time.perf_counter()
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                execute_job,
                job,
                reviews=reviews,
                candidates=candidates,
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
            except Exception as exc:  # noqa: BLE001 - preserve failed evidence
                failures.append(f"{job.key}: {exc}")
                strict = False
            completed += 1
            print(f"[{completed}/{len(jobs)}] {job.key} strict={strict}", flush=True)
    if failures:
        write_json(output_dir / "run-failures.json", {"failures": failures})
        raise LibraryScopeError(f"{len(failures)} adjudication batches failed")
    manifest = aggregate(
        output_dir=output_dir,
        jobs=jobs,
        reviews=reviews,
        model=args.model,
        candidate_path=candidate_path,
        reviews_path=reviews_path,
    )
    print(
        f"adjudication complete: choices={manifest['choices']} "
        f"elapsed={time.perf_counter()-started:.1f}s"
    )
    print(output_dir / "aggregate/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
