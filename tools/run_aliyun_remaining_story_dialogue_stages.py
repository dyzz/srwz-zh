#!/usr/bin/env python3
"""Run resumable DeepSeek drafts for every unfinished story-dialogue stage."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    from import_story_dialogue_local_model_batch import _validate_translation, load_queue
    from run_qwen_mt_story_dialogue_stage import preserved_candidate, select_stage_rows
    from run_aliyun_general_story_dialogue_stage import translated_stage_rows
    from srwz.translation_review import TranslationReviewError
except ModuleNotFoundError:  # pragma: no cover
    from tools.import_story_dialogue_local_model_batch import _validate_translation, load_queue
    from tools.run_qwen_mt_story_dialogue_stage import preserved_candidate, select_stage_rows
    from tools.run_aliyun_general_story_dialogue_stage import translated_stage_rows
    from tools.srwz.translation_review import TranslationReviewError


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
QUEUE = WORK / "review" / "local-model" / "story-dialogue-unique.jsonl"
RUN_ROOT = WORK / "review" / "local-model" / "aliyun" / "remaining-stages"
RUNNER = ROOT / "tools" / "run_aliyun_general_story_dialogue_stage.py"
MODEL = "deepseek-v4-flash"
MODEL_DIR = "deepseek-v4-flash-relevant-compact-lines"
REVIEWED_OR_DONE = {10, 11, 12, 13, 14, 15}


@dataclass(frozen=True)
class Job:
    stage: int
    ordinal: int
    indices: tuple[int, ...]
    full_stage: bool
    stage_unique_count: int
    stage_translated_count: int

    @property
    def key(self) -> str:
        return f"{self.stage:03d}:{self.ordinal:03d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-size", type=int, default=450)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--fallback-chunk-size", type=int, default=150)
    parser.add_argument("--stage", type=int, action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def json_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def manifest_cost(path: Path) -> float:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    value = manifest.get("pricing", {}).get("estimated_run_cost_cny")
    return float(value) if isinstance(value, (int, float)) else 0.0


def stage_output(stage: int) -> Path:
    return (
        WORK / "review" / "local-model" / "aliyun" / f"stage-{stage:03d}"
        / "general-models" / MODEL_DIR
    )


def attempt_dir(job: Job, attempt: int) -> Path:
    return stage_output(job.stage) / "requests" / f"chunk-{job.ordinal:03d}" / f"attempt-{attempt}"


def artifact_ok(job: Job, directory: Path) -> bool:
    manifest_path = directory / "manifest.json"
    parsed_path = directory / "parsed.jsonl"
    if not manifest_path.is_file() or not parsed_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected_translated = job.stage_translated_count if job.full_stage else len(job.indices)
    expected_parsed = job.stage_unique_count if job.full_stage else len(job.indices)
    return bool(
        manifest.get("run", {}).get("finish_reason") == "stop"
        and manifest.get("format_audit", {}).get("exact_id_order") is True
        and manifest.get("format_audit", {}).get("translation_item_count") == expected_translated
        and len(json_rows(parsed_path)) == expected_parsed
    )


def max_tokens(row_count: int) -> int:
    # DeepSeek occasionally needs close to 20K completion tokens for a
    # 450-row compact-lines request.  Leave enough headroom for verbose lines;
    # max_tokens is only a ceiling, so clean shorter responses are unaffected.
    target = max(4096, row_count * 80 + 4096)
    return min(65536, int(math.ceil(target / 1024)) * 1024)


def execute_request(
    job: Job,
    directory: Path,
    *,
    indices: Sequence[int],
    full_stage: bool,
) -> tuple[int, float]:
    row_count = job.stage_translated_count if full_stage else len(indices)
    command = [
        sys.executable,
        str(RUNNER),
        "--stage", str(job.stage),
        "--model", MODEL,
        "--glossary-scope", "stage-relevant",
        "--prompt-profile", "compact-lines",
        "--max-tokens", str(max_tokens(row_count)),
        "--timeout", "900",
        "--skip-probe",
        "--nonstream",
        "--output-dir", str(directory.relative_to(ROOT)),
    ]
    if not full_stage:
        for index in indices:
            command.extend(("--unique-index", str(index)))
    started = time.time()
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=960,
        )
        output = result.stdout
        code = result.returncode
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + "\nsubprocess timeout\n"
        code = 124
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "runner.log").write_text(output, encoding="utf-8")
    return code, time.time() - started


def fallback_dir(job: Job, chunk_size: int | None = None) -> Path:
    name = "fallback" if chunk_size is None else f"fallback-{chunk_size:03d}"
    return stage_output(job.stage) / "requests" / f"chunk-{job.ordinal:03d}" / name


def run_fallback(job: Job, max_attempts: int, chunk_size: int) -> dict[str, object] | None:
    legacy_output = fallback_dir(job)
    if artifact_ok(job, legacy_output):
        return {
            "key": job.key,
            "status": "complete",
            "attempt": "fallback",
            "directory": str(legacy_output.relative_to(ROOT)),
            "resumed": True,
        }
    output = fallback_dir(job, chunk_size)
    if artifact_ok(job, output):
        return {
            "key": job.key,
            "status": "complete",
            "attempt": f"fallback-{chunk_size}",
            "directory": str(output.relative_to(ROOT)),
            "resumed": True,
        }
    if len(job.indices) <= chunk_size:
        return None
    pieces = [job.indices[start : start + chunk_size] for start in range(0, len(job.indices), chunk_size)]
    accepted_dirs: list[Path] = []
    total_seconds = 0.0
    piece_attempts = min(max_attempts, 3)
    for ordinal, indices in enumerate(pieces):
        piece = Job(job.stage, ordinal, tuple(indices), False, len(indices), len(indices))
        accepted: Path | None = None
        for attempt in range(1, piece_attempts + 1):
            directory = output / f"part-{ordinal:03d}" / f"attempt-{attempt}"
            if artifact_ok(piece, directory):
                accepted = directory
                break
            if directory.exists() and any(directory.iterdir()):
                continue
            _, seconds = execute_request(
                piece, directory, indices=indices, full_stage=False
            )
            total_seconds += seconds
            if artifact_ok(piece, directory):
                accepted = directory
                break
            if attempt < piece_attempts:
                time.sleep(5 * attempt)
        if accepted is None:
            return None
        accepted_dirs.append(accepted)

    candidates = [
        row for directory in accepted_dirs for row in json_rows(directory / "parsed.jsonl")
    ]
    if job.full_stage:
        stage_rows = select_stage_rows(load_queue(QUEUE), job.stage)
        for row in stage_rows:
            if row.get("source_quote_shape") == "control_or_punctuation":
                candidates.append(_validate_translation(row, preserved_candidate(row)))
        expected_indices = {int(row["unique_index"]) for row in stage_rows}
    else:
        expected_indices = set(job.indices)
    by_index = {int(row["unique_index"]): row for row in candidates}
    if set(by_index) != expected_indices:
        return None
    ordered = [by_index[index] for index in sorted(by_index)]
    write_jsonl(output / "parsed.jsonl", ordered)
    manifests = [
        json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for directory in accepted_dirs
    ]
    translated_count = job.stage_translated_count if job.full_stage else len(job.indices)
    write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "kind": "aliyun_split_fallback_aggregate",
            "aggregate_only": True,
            "run": {
                "finish_reason": "stop",
                "prompt_tokens": sum(int(item["run"]["prompt_tokens"]) for item in manifests),
                "completion_tokens": sum(int(item["run"]["completion_tokens"]) for item in manifests),
            },
            "format_audit": {
                "exact_id_order": True,
                "translation_item_count": translated_count,
            },
            "pricing": {
                "estimated_run_cost_cny": round(
                    sum(
                        float(item.get("pricing", {}).get("estimated_run_cost_cny") or 0)
                        for item in manifests
                    ),
                    6,
                )
            },
            "parts": [str(directory.relative_to(ROOT)) for directory in accepted_dirs],
        },
    )
    return {
        "key": job.key,
        "status": "complete",
        "attempt": f"fallback-{chunk_size}",
        "directory": str(output.relative_to(ROOT)),
        "resumed": False,
        "seconds": round(total_seconds, 3),
    }


def run_job(job: Job, max_attempts: int, fallback_chunk_size: int) -> dict[str, object]:
    code = 0
    for attempt in range(1, max_attempts + 1):
        directory = attempt_dir(job, attempt)
        if artifact_ok(job, directory):
            return {
                "key": job.key,
                "status": "complete",
                "attempt": attempt,
                "directory": str(directory.relative_to(ROOT)),
                "resumed": True,
            }
        # An invalid attempt is still a completed, billable API call.  Preserve
        # it as evidence and advance to a fresh attempt directory on resume
        # instead of silently overwriting and paying for the same slot again.
        if directory.exists() and any(directory.iterdir()):
            continue
        code, seconds = execute_request(
            job, directory, indices=job.indices, full_stage=job.full_stage
        )
        if artifact_ok(job, directory):
            return {
                "key": job.key,
                "status": "complete",
                "attempt": attempt,
                "directory": str(directory.relative_to(ROOT)),
                "resumed": False,
                "seconds": round(seconds, 3),
                "exit_code": code,
            }
        if attempt < max_attempts:
            time.sleep(5 * attempt)
    fallback = run_fallback(job, max_attempts, fallback_chunk_size)
    if fallback is not None:
        return fallback
    return {"key": job.key, "status": "failed", "attempt": max_attempts, "exit_code": code}


def plan_jobs(queue: Sequence[Mapping[str, object]], stages: Sequence[int], chunk_size: int) -> list[Job]:
    jobs: list[Job] = []
    for stage in stages:
        stage_rows = select_stage_rows(queue, stage)
        translated = translated_stage_rows(stage_rows)
        indices = [int(row["unique_index"]) for row in translated]
        if len(indices) <= chunk_size:
            jobs.append(Job(stage, 0, tuple(indices), True, len(stage_rows), len(translated)))
            continue
        for ordinal, start in enumerate(range(0, len(indices), chunk_size)):
            jobs.append(
                Job(
                    stage,
                    ordinal,
                    tuple(indices[start : start + chunk_size]),
                    False,
                    len(stage_rows),
                    len(translated),
                )
            )
    return jobs


def finalize_stage(queue: Sequence[Mapping[str, object]], stage: int, jobs: Sequence[Job], results: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    stage_rows = select_stage_rows(queue, stage)
    candidates: list[dict[str, object]] = []
    request_manifests: list[Path] = []
    for job in jobs:
        result = results[job.key]
        directory = ROOT / str(result["directory"])
        candidates.extend(json_rows(directory / "parsed.jsonl"))
        request_manifests.append(directory / "manifest.json")
    if not any(job.full_stage for job in jobs):
        for row in stage_rows:
            if row.get("source_quote_shape") == "control_or_punctuation":
                candidates.append(_validate_translation(row, preserved_candidate(row)))
    by_key = {(int(row["stage_index"]), int(row["unique_index"])): row for row in candidates}
    expected = {(stage, int(row["unique_index"])) for row in stage_rows}
    if set(by_key) != expected:
        raise ValueError(f"stage {stage:03d} merged coverage mismatch")
    ordered = [by_key[key] for key in sorted(by_key)]
    errors: dict[str, str] = {}
    valid = 0
    for source in stage_rows:
        key = (stage, int(source["unique_index"]))
        try:
            _validate_translation(source, by_key[key])
            valid += 1
        except TranslationReviewError as error:
            errors[f"{stage}:{key[1]}"] = str(error)
    output = stage_output(stage)
    write_jsonl(output / "parsed.jsonl", ordered)
    accepted_cost = 0.0
    prompt = completion = 0
    for path in request_manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        prompt += int(manifest["run"]["prompt_tokens"])
        completion += int(manifest["run"]["completion_tokens"])
        accepted_cost += manifest_cost(path)
    all_attempt_manifests = sorted(
        path
        for job in jobs
        for path in (stage_output(stage) / "requests" / f"chunk-{job.ordinal:03d}").glob(
            "**/attempt-*/manifest.json"
        )
    )
    all_attempt_cost = sum(manifest_cost(path) for path in all_attempt_manifests)
    summary = {
        "schema_version": 1,
        "kind": "aliyun_resumable_stage_batch",
        "stage_index": stage,
        "row_count": len(stage_rows),
        "translated_row_count": len(translated_stage_rows(stage_rows)),
        "request_count": len(jobs),
        "format_complete": True,
        "strict_valid_count": valid,
        "strict_failure_count": len(errors),
        "validation_errors": errors,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "estimated_cost_cny": round(all_attempt_cost, 6),
        "accepted_output_cost_cny": round(accepted_cost, 6),
        "failed_or_superseded_attempt_cost_cny": round(
            max(0.0, all_attempt_cost - accepted_cost), 6
        ),
        "all_attempt_count": len(all_attempt_manifests),
        "requests": [str(path.relative_to(ROOT)) for path in request_manifests],
        "parsed_output": str((output / "parsed.jsonl").relative_to(ROOT)),
    }
    write_json(output / "batch-manifest.json", summary)
    return summary


def main() -> int:
    args = parse_args()
    if (
        args.workers <= 0
        or args.chunk_size <= 0
        or args.max_attempts <= 0
        or args.fallback_chunk_size <= 0
    ):
        raise SystemExit(
            "workers, chunk-size, max-attempts, and fallback-chunk-size must be positive"
        )
    queue = load_queue(QUEUE)
    available = sorted({int(row["stage_index"]) for row in queue})
    locked = {
        stage
        for stage in available
        if all(
            row.get("review_state") == "locked_reviewed"
            for row in queue
            if int(row["stage_index"]) == stage
        )
    }
    stages = sorted(set(args.stage)) if args.stage else [
        stage for stage in available if stage not in locked | REVIEWED_OR_DONE
    ]
    jobs = plan_jobs(queue, stages, args.chunk_size)
    plan = {
        "stages": stages,
        "stage_count": len(stages),
        "job_count": len(jobs),
        "workers": args.workers,
        "chunk_size": args.chunk_size,
        "fallback_chunk_size": args.fallback_chunk_size,
        "jobs": [
            {"key": job.key, "stage": job.stage, "rows": len(job.indices), "full_stage": job.full_stage}
            for job in jobs
        ],
    }
    write_json(RUN_ROOT / "plan.json", plan)
    print(f"stages={len(stages)} jobs={len(jobs)} workers={args.workers}", flush=True)
    if args.dry_run:
        return 0

    results: dict[str, dict[str, object]] = {}
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = {
            executor.submit(
                run_job, job, args.max_attempts, args.fallback_chunk_size
            ): job
            for job in jobs
        }
        for future in as_completed(pending):
            job = pending[future]
            result = future.result()
            with lock:
                results[job.key] = result
                complete = sum(item["status"] == "complete" for item in results.values())
                failed = sum(item["status"] == "failed" for item in results.values())
                write_json(
                    RUN_ROOT / "progress.json",
                    {
                        "status": "running",
                        "completed_jobs": complete,
                        "failed_jobs": failed,
                        "total_jobs": len(jobs),
                        "results": results,
                    },
                )
            print(
                f"[{complete + failed}/{len(jobs)}] {job.key} {result['status']} "
                f"attempt={result.get('attempt')}",
                flush=True,
            )

    failed_jobs = [key for key, result in results.items() if result["status"] != "complete"]
    stage_summaries: list[dict[str, object]] = []
    if not failed_jobs:
        jobs_by_stage = {stage: [job for job in jobs if job.stage == stage] for stage in stages}
        for stage in stages:
            stage_summaries.append(finalize_stage(queue, stage, jobs_by_stage[stage], results))
    report = {
        "schema_version": 1,
        "kind": "aliyun_remaining_story_dialogue_stages",
        "status": "complete" if not failed_jobs else "incomplete",
        "stage_count": len(stages),
        "job_count": len(jobs),
        "failed_jobs": failed_jobs,
        "strict_failure_count": sum(item.get("strict_failure_count", 0) for item in stage_summaries),
        "estimated_cost_cny": round(sum(item.get("estimated_cost_cny", 0) for item in stage_summaries), 6),
        "accepted_output_cost_cny": round(
            sum(item.get("accepted_output_cost_cny", 0) for item in stage_summaries), 6
        ),
        "failed_or_superseded_attempt_cost_cny": round(
            sum(
                item.get("failed_or_superseded_attempt_cost_cny", 0)
                for item in stage_summaries
            ),
            6,
        ),
        "stages": stage_summaries,
    }
    write_json(RUN_ROOT / "report.json", report)
    write_json(
        RUN_ROOT / "progress.json",
        {"status": report["status"], "completed_jobs": len(jobs) - len(failed_jobs), "failed_jobs": len(failed_jobs), "total_jobs": len(jobs), "results": results},
    )
    print(
        f"status={report['status']} stages={len(stage_summaries)}/{len(stages)} "
        f"strict_failures={report['strict_failure_count']} cost=¥{report['estimated_cost_cny']}",
        flush=True,
    )
    return 0 if not failed_jobs else 2


if __name__ == "__main__":
    raise SystemExit(main())
