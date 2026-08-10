#!/usr/bin/env python3
"""Run and resume all v0.2 LIBRARY DeepSeek review batches.

Rows with names, work titles, dimensions, and other metadata are translated
first in larger batches.  Description-only rows follow in smaller batches.
Strict failures get fresh attempts and then recursively smaller fallback
batches.  Only validator-clean attempts enter the ignored aggregate draft.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    import run_aliyun_library_v02_batch as batch
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools import run_aliyun_library_v02_batch as batch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
RUNNER = PROJECT_ROOT / "tools/run_aliyun_library_v02_batch.py"
DEFAULT_QUEUE = WORK_ROOT / "review/aliyun/library-v0.2/source-queue.jsonl"


@dataclass(frozen=True)
class Job:
    phase: str
    offset: int
    limit: int

    @property
    def key(self) -> str:
        return f"{self.phase}:{self.offset:04d}:{self.limit:04d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--model", default=batch.DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--metadata-chunk-size", type=int, default=150)
    parser.add_argument("--body-chunk-size", type=int, default=24)
    parser.add_argument("--fallback-chunk-size", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=16_384)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--phase", choices=("metadata", "body"), action="append")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


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


def phase_rows(
    queue: Sequence[Mapping[str, object]], phase: str
) -> list[Mapping[str, object]]:
    return batch.select_rows(
        queue,
        domain=None,
        tags=(),
        phase=phase,
        offset=0,
        limit=len(queue),
    )


def expected_rows_for_phases(
    queue: Sequence[Mapping[str, object]], phases: Sequence[str]
) -> list[Mapping[str, object]]:
    """Return selected rows once while retaining extraction queue order."""
    selected_ids = {
        str(row["id"])
        for phase in phases
        for row in phase_rows(queue, phase)
    }
    return [row for row in queue if str(row["id"]) in selected_ids]


def plan_jobs(
    queue: Sequence[Mapping[str, object]],
    phases: Sequence[str],
    metadata_chunk_size: int,
    body_chunk_size: int,
) -> tuple[list[Job], dict[str, int]]:
    jobs: list[Job] = []
    counts: dict[str, int] = {}
    for phase in phases:
        count = len(phase_rows(queue, phase))
        counts[phase] = count
        chunk_size = metadata_chunk_size if phase == "metadata" else body_chunk_size
        for offset in range(0, count, chunk_size):
            jobs.append(Job(phase, offset, min(chunk_size, count - offset)))
    return jobs, counts


def attempt_dir(job: Job, model: str, attempt: int) -> Path:
    return batch.default_output_dir(
        model=model,
        domain=None,
        phase=job.phase,
        tags=(),
        offset=job.offset,
        count=job.limit,
        attempt=attempt,
    )


def artifact_ok(directory: Path, job: Job, model: str) -> bool:
    manifest_path = directory / "manifest.json"
    validated_path = directory / "validated.jsonl"
    if not manifest_path.is_file() or not validated_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = batch.read_jsonl(validated_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return bool(
        manifest.get("requested_model") == model
        and manifest.get("phase") == job.phase
        and manifest.get("offset") == job.offset
        and manifest.get("selected_count") == job.limit
        and manifest.get("validation", {}).get("strict_passed") is True
        and len(rows) == job.limit
    )


def execute_job(
    job: Job,
    *,
    queue_path: Path,
    model: str,
    attempt: int,
    max_tokens: int,
    timeout: float,
) -> tuple[Path, int, float]:
    directory = attempt_dir(job, model, attempt)
    command = [
        sys.executable,
        str(RUNNER),
        "--queue",
        str(queue_path),
        "--model",
        model,
        "--phase",
        job.phase,
        "--offset",
        str(job.offset),
        "--limit",
        str(job.limit),
        "--attempt",
        str(attempt),
        "--max-tokens",
        str(max_tokens),
        "--timeout",
        str(timeout),
    ]
    started = time.time()
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout + 60,
        )
        output = result.stdout
        code = result.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\nsubprocess timeout\n"
        code = 124
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "runner.log").write_text(output, encoding="utf-8")
    return directory, code, time.time() - started


def run_job(
    job: Job,
    *,
    queue_path: Path,
    model: str,
    max_attempts: int,
    fallback_chunk_size: int,
    max_tokens: int,
    timeout: float,
) -> tuple[list[Path], list[dict[str, object]]]:
    audits: list[dict[str, object]] = []
    parent = attempt_dir(job, model, 1).parent
    for directory in sorted(parent.glob("attempt-*")):
        if artifact_ok(directory, job, model):
            audits.append(
                {
                    "job": job.key,
                    "status": "complete",
                    "attempt": int(directory.name.removeprefix("attempt-")),
                    "resumed": True,
                    "directory": str(directory.relative_to(PROJECT_ROOT)),
                }
            )
            return [directory], audits
    for attempt in range(1, max_attempts + 1):
        directory = attempt_dir(job, model, attempt)
        if artifact_ok(directory, job, model):
            audits.append(
                {
                    "job": job.key,
                    "status": "complete",
                    "attempt": attempt,
                    "resumed": True,
                    "directory": str(directory.relative_to(PROJECT_ROOT)),
                }
            )
            return [directory], audits
        if directory.exists() and any(directory.iterdir()):
            audits.append(
                {
                    "job": job.key,
                    "status": "invalid_preserved",
                    "attempt": attempt,
                    "directory": str(directory.relative_to(PROJECT_ROOT)),
                }
            )
            continue
        directory, code, elapsed = execute_job(
            job,
            queue_path=queue_path,
            model=model,
            attempt=attempt,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        accepted = artifact_ok(directory, job, model)
        audits.append(
            {
                "job": job.key,
                "status": "complete" if accepted else "failed_attempt",
                "attempt": attempt,
                "resumed": False,
                "exit_code": code,
                "elapsed_seconds": round(elapsed, 3),
                "directory": str(directory.relative_to(PROJECT_ROOT)),
            }
        )
        if accepted:
            return [directory], audits
        if attempt < max_attempts:
            time.sleep(2 * attempt)

    if job.limit > fallback_chunk_size:
        left_size = job.limit // 2
        children = (
            Job(job.phase, job.offset, left_size),
            Job(job.phase, job.offset + left_size, job.limit - left_size),
        )
        accepted_dirs: list[Path] = []
        for child in children:
            child_dirs, child_audits = run_job(
                child,
                queue_path=queue_path,
                model=model,
                max_attempts=max_attempts,
                fallback_chunk_size=fallback_chunk_size,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            accepted_dirs.extend(child_dirs)
            audits.extend(child_audits)
        return accepted_dirs, audits

    audits.append({"job": job.key, "status": "failed_terminal"})
    return [], audits


def aggregate(
    *,
    queue: Sequence[Mapping[str, object]],
    accepted_dirs: Sequence[Path],
    phases: Sequence[str],
    model: str,
    audits: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    expected_rows = expected_rows_for_phases(queue, phases)
    expected_by_id = {str(row["id"]): row for row in expected_rows}
    translated_by_id: dict[str, dict[str, object]] = {}
    manifests: list[dict[str, object]] = []
    for directory in sorted(set(accepted_dirs)):
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        manifests.append(manifest)
        for row in batch.read_jsonl(directory / "validated.jsonl"):
            row_id = str(row["id"])
            if row_id not in expected_by_id:
                raise ValueError(f"aggregate contains unexpected row: {row_id}")
            prior = translated_by_id.get(row_id)
            if prior is not None and prior != row:
                raise ValueError(f"aggregate has conflicting translations: {row_id}")
            translated_by_id[row_id] = row

    ordered = [
        translated_by_id[str(row["id"])]
        for row in expected_rows
        if str(row["id"]) in translated_by_id
    ]
    missing = [
        str(row["id"])
        for row in expected_rows
        if str(row["id"]) not in translated_by_id
    ]
    root = WORK_ROOT / "review/aliyun/library-v0.2" / model / "aggregate"
    output_path = root / "validated.jsonl"
    report_path = root / "manifest.json"
    write_jsonl(output_path, ordered)
    report = {
        "schema_version": 1,
        "kind": "aliyun_library_v0.2_translation_aggregate",
        "model": model,
        "phases": list(phases),
        "source_queue_count": len(queue),
        "expected_count": len(expected_rows),
        "validated_count": len(ordered),
        "missing_count": len(missing),
        "missing_ids": missing,
        "strict_batches_complete": not missing,
        "editorial_status": "machine_draft_pending_review",
        "sound_track_titles_included": False,
        "run_totals": {
            "accepted_batch_count": len(manifests),
            "prompt_tokens": sum(
                int(item.get("run", {}).get("prompt_tokens", 0))
                for item in manifests
            ),
            "completion_tokens": sum(
                int(item.get("run", {}).get("completion_tokens", 0))
                for item in manifests
            ),
            "elapsed_seconds_sum": round(
                sum(
                    float(item.get("run", {}).get("elapsed_seconds", 0))
                    for item in manifests
                ),
                6,
            ),
        },
        "attempt_audit": list(audits),
        "validated_output": str(output_path.relative_to(PROJECT_ROOT)),
    }
    write_json(report_path, report)
    return report


def main() -> int:
    args = parse_args()
    if min(
        args.workers,
        args.metadata_chunk_size,
        args.body_chunk_size,
        args.fallback_chunk_size,
        args.max_attempts,
        args.max_tokens,
    ) <= 0:
        raise ValueError("worker, chunk, attempt, and token values must be positive")
    queue_path = batch.project_path(args.queue).resolve()
    queue = batch.read_jsonl(queue_path)
    batch.validate_queue(queue)
    phases = args.phase or ["metadata", "body"]
    jobs, counts = plan_jobs(
        queue,
        phases,
        args.metadata_chunk_size,
        args.body_chunk_size,
    )
    plan = {
        "phases": phases,
        "phase_counts": counts,
        "job_count": len(jobs),
        "jobs": [job.key for job in jobs],
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    accepted_dirs: list[Path] = []
    audits: list[dict[str, object]] = []
    lock = threading.Lock()
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(
                run_job,
                job,
                queue_path=queue_path,
                model=args.model,
                max_attempts=args.max_attempts,
                fallback_chunk_size=args.fallback_chunk_size,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            ): job
            for job in jobs
        }
        for future in as_completed(future_map):
            job = future_map[future]
            directories, job_audits = future.result()
            with lock:
                accepted_dirs.extend(directories)
                audits.extend(job_audits)
                completed += 1
                print(
                    f"progress={completed}/{len(jobs)} job={job.key} "
                    f"accepted_parts={len(directories)}",
                    flush=True,
                )

    report = aggregate(
        queue=queue,
        accepted_dirs=accepted_dirs,
        phases=phases,
        model=args.model,
        audits=audits,
    )
    print(
        f"validated={report['validated_count']}/{report['expected_count']} "
        f"strict={report['strict_batches_complete']}",
        flush=True,
    )
    print(
        WORK_ROOT
        / "review/aliyun/library-v0.2"
        / args.model
        / "aggregate/manifest.json"
    )
    return 0 if report["strict_batches_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
