#!/usr/bin/env python3
"""Extract first-pass revisions that returned an unchanged translation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import run_aliyun_library_v02_batch as api
    import run_library_v02_full_editorial_audit as audit
    from srwz.library import LibraryScopeError
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools import run_aliyun_library_v02_batch as api
    from tools import run_library_v02_full_editorial_audit as audit
    from tools.srwz.library import LibraryScopeError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "work/review/editorial/library-v0.2-noop-revisions-v1/reviews.jsonl"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=audit.DEFAULT_CANDIDATE)
    parser.add_argument("--audit-dir", type=Path, default=audit.DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=audit.DEFAULT_MODEL)
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


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    temporary.replace(path)


def extract_noops(
    *,
    candidate_path: Path,
    audit_dir: Path,
    model: str,
) -> tuple[list[dict[str, object]], list[str]]:
    document = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidates = [
        row for row in document.get("rows", []) if row.get("category") == "library"
    ]
    if len(candidates) != 2709:
        raise LibraryScopeError("no-op extraction requires 2709 candidate rows")
    by_id = {str(row["id"]): row for row in candidates}
    aggregate_path = audit_dir / "aggregate/reviews.jsonl"
    aggregate = api.read_jsonl(aggregate_path)
    aggregate_by_id = {str(row["id"]): row for row in aggregate}
    if len(aggregate_by_id) != 2709 or set(aggregate_by_id) != set(by_id):
        raise LibraryScopeError("first-pass aggregate coverage drift")

    noops: dict[str, dict[str, object]] = {}
    phases = ("metadata", "prose")
    jobs, _counts = audit.plan_jobs(
        candidates,
        phases,
        metadata_chunk_size=80,
        prose_chunk_size=16,
    )
    for job in jobs:
        directory = audit.strict_attempt_dir(audit_dir, job, model)
        if directory is None:
            raise LibraryScopeError(f"first-pass batch is not strict: {job.key}")
        response = json.loads((directory / "response.json").read_text(encoding="utf-8"))
        raw = json.loads(str(response["response_text"]))
        values = raw.get("reviews")
        if not isinstance(values, list):
            raise LibraryScopeError(f"first-pass response is malformed: {job.key}")
        for value in values:
            if not isinstance(value, dict) or value.get("verdict") != "revise":
                continue
            row_id = str(value.get("id", ""))
            text = value.get("text")
            candidate = by_id.get(row_id, {}).get("candidate_translation")
            if isinstance(text, str) and text.strip() == candidate:
                if aggregate_by_id[row_id].get("verdict") != "keep":
                    raise LibraryScopeError(f"no-op normalization drift: {row_id}")
                noops[row_id] = {
                    "schema_version": 1,
                    "id": row_id,
                    "verdict": "revise",
                    "translation": candidate,
                    "issues": value.get("issues", []),
                    "reason": str(value.get("reason", "")).strip(),
                }

    ordered_ids = [str(row["id"]) for row in candidates]
    synthetic: list[dict[str, object]] = []
    for row_id in ordered_ids:
        if row_id in noops:
            synthetic.append(noops[row_id])
        else:
            synthetic.append(
                {
                    "schema_version": 1,
                    "id": row_id,
                    "verdict": "keep",
                    "translation": str(by_id[row_id]["candidate_translation"]),
                    "issues": [],
                    "reason": "not_in_noop_repair_scope",
                }
            )
    return synthetic, [row_id for row_id in ordered_ids if row_id in noops]


def main() -> int:
    args = parse_args()
    candidate_path = project_path(args.candidate).resolve()
    audit_dir = project_path(args.audit_dir).resolve()
    output = project_path(args.output).resolve()
    if PROJECT_ROOT not in output.parents or "work" not in output.parts:
        raise LibraryScopeError("no-op repair output must remain below project work/")
    rows, no_op_ids = extract_noops(
        candidate_path=candidate_path,
        audit_dir=audit_dir,
        model=args.model,
    )
    write_jsonl(output, rows)
    manifest = {
        "schema_version": 1,
        "kind": "library_v0.2_noop_revision_repair_scope",
        "source": {
            "candidate_path": str(candidate_path.relative_to(PROJECT_ROOT)),
            "candidate_sha256": sha256_file(candidate_path),
            "first_pass_audit_dir": str(audit_dir.relative_to(PROJECT_ROOT)),
            "first_pass_reviews_sha256": sha256_file(
                audit_dir / "aggregate/reviews.jsonl"
            ),
        },
        "coverage": {
            "all_entry_count": len(rows),
            "no_op_revision_count": len(no_op_ids),
            "unique_no_op_revision_count": len(set(no_op_ids)),
        },
        "output": {
            "path": str(output.relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(output),
        },
    }
    write_json(output.parent / "manifest.json", manifest)
    print(
        f"no-op revisions: count={len(no_op_ids)} all_rows={len(rows)} "
        f"sha256={manifest['output']['sha256']}"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
