#!/usr/bin/env python3
"""Promote the locked, risk-free LIBRARY review into the v0.2 corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = (
    PROJECT_ROOT / "work/review/editorial/stage0-library/candidate.json"
)
DEFAULT_QUEUE = PROJECT_ROOT / "work/review/aliyun/library-v0.2/source-queue.jsonl"
DEFAULT_DRAFT = PROJECT_ROOT / (
    "work/review/aliyun/library-v0.2/deepseek-v4-flash-0731/"
    "aggregate/validated.jsonl"
)
DEFAULT_FINAL_DECISIONS = PROJECT_ROOT / (
    "work/review/editorial/library-v0.2-final-v1/final-decisions.jsonl"
)
DEFAULT_FINAL_MANIFEST = PROJECT_ROOT / (
    "work/review/editorial/library-v0.2-final-v1/manifest.json"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "corpus/zh/library/v0.2-reviewed.json"

CANDIDATE_SHA256 = "9ced95407498e55eaa98914fbcc034a1782202ef14434bda85d7f9f12459816e"
QUEUE_SHA256 = "63b0a9a9bfa2862060169a32cb3a61cefb549f9a06d6568f334543ae53d56acc"
DRAFT_SHA256 = "fca7262d099ae1b64410bc4dc834952dedda0925609ba03489990c23982f8fbc"
FINAL_DECISIONS_SHA256 = "99ec9938dd61fc576503e7e90b9769e0a6e4d7bf87f0bd97cdcfc0d88ed198e7"
FINAL_MANIFEST_SHA256 = "f6bc837d87cee82d9ed2daee398775dc85475a70b4abce87640af95e59125a5e"
EXPECTED_COUNT = 2709
EXPECTED_FIELD_REFERENCE_COUNT = 4921
EXPECTED_HUMAN_REVIEWED_COUNT = 2709


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument(
        "--final-decisions", type=Path, default=DEFAULT_FINAL_DECISIONS
    )
    parser.add_argument(
        "--final-manifest", type=Path, default=DEFAULT_FINAL_MANIFEST
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def locked_bytes(path: Path, expected: str, label: str) -> bytes:
    data = path.resolve().read_bytes()
    actual = sha256_bytes(data)
    if actual != expected:
        raise SystemExit(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")
    return data


def jsonl_rows(data: bytes, label: str) -> list[dict]:
    rows = []
    for number, raw in enumerate(data.decode("utf-8").splitlines(), start=1):
        row = json.loads(raw)
        if not isinstance(row, dict):
            raise SystemExit(f"{label} row {number} is not an object")
        rows.append(row)
    return rows


def main() -> int:
    args = parse_args()
    candidate_data = locked_bytes(args.candidate, CANDIDATE_SHA256, "candidate")
    queue_data = locked_bytes(args.queue, QUEUE_SHA256, "source queue")
    draft_data = locked_bytes(args.draft, DRAFT_SHA256, "validated draft")
    final_data = locked_bytes(
        args.final_decisions,
        FINAL_DECISIONS_SHA256,
        "final editorial decisions",
    )
    final_manifest_data = locked_bytes(
        args.final_manifest,
        FINAL_MANIFEST_SHA256,
        "final editorial manifest",
    )
    candidate = json.loads(candidate_data)
    library_summary = candidate.get("summary", {}).get("library", {})
    if (
        not isinstance(candidate, dict)
        or candidate.get("schema_version") != 1
        or candidate.get("promotion_allowed") is not False
        or library_summary.get("total") != EXPECTED_COUNT
        or library_summary.get("risk") != 0
        or library_summary.get("human_reviewed") != 106
    ):
        raise SystemExit("LIBRARY editorial review is incomplete or has unresolved risk")

    queue = jsonl_rows(queue_data, "source queue")
    draft = jsonl_rows(draft_data, "validated draft")
    final = jsonl_rows(final_data, "final editorial decisions")
    final_manifest = json.loads(final_manifest_data)
    if (
        len(queue) != EXPECTED_COUNT
        or len(draft) != EXPECTED_COUNT
        or len(final) != EXPECTED_COUNT
    ):
        raise SystemExit("LIBRARY fixed-snapshot coverage drift")
    queue_by_id = {str(row.get("id")): row for row in queue}
    draft_by_id = {str(row.get("id")): row for row in draft}
    final_by_id = {str(row.get("id")): row for row in final}
    if (
        len(queue_by_id) != EXPECTED_COUNT
        or len(final_by_id) != EXPECTED_COUNT
        or set(queue_by_id) != set(draft_by_id)
        or set(queue_by_id) != set(final_by_id)
        or final_manifest.get("status") != "reviewed"
        or final_manifest.get("release_eligible") is not True
        or final_manifest.get("validation", {}).get("strict_passed") is not True
        or final_manifest.get("output", {}).get("sha256")
        != FINAL_DECISIONS_SHA256
    ):
        raise SystemExit("LIBRARY queue/draft ID coverage drift")

    rows = [row for row in candidate.get("rows", []) if row.get("category") == "library"]
    if len(rows) != EXPECTED_COUNT:
        raise SystemExit("LIBRARY editorial candidate coverage drift")
    entries = []
    seen_ids = set()
    reference_count = 0
    domain_counts: dict[str, int] = {}
    human_reviewed_count = 0
    deterministic_reviewed_count = 0
    for row in sorted(rows, key=lambda item: str(item.get("id"))):
        entry_id = str(row.get("id"))
        if entry_id in seen_ids or entry_id not in queue_by_id:
            raise SystemExit(f"duplicate or unknown LIBRARY candidate ID: {entry_id}")
        seen_ids.add(entry_id)
        source_hash = row.get("source_text_sha256")
        queue_row = queue_by_id[entry_id]
        draft_row = draft_by_id[entry_id]
        final_row = final_by_id[entry_id]
        if (
            source_hash != queue_row.get("source_text_sha256")
            or source_hash != draft_row.get("source_text_sha256")
            or source_hash != final_row.get("source_text_sha256")
            or row.get("source_status") != ["machine_draft"]
            or row.get("risk_details")
        ):
            raise SystemExit(f"LIBRARY candidate provenance/risk drift: {entry_id}")
        translation = final_row.get("translation")
        if not isinstance(translation, str) or not translation:
            raise SystemExit(f"LIBRARY candidate translation is empty: {entry_id}")
        references = queue_row.get("references")
        if not isinstance(references, list) or not references:
            raise SystemExit(f"LIBRARY candidate has no field references: {entry_id}")
        reference_count += len(references)
        domains = sorted({str(item.get("domain")) for item in references})
        for domain in domains:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
        review_origin = final_row.get("decision_origin")
        if not isinstance(review_origin, str) or not review_origin:
            raise SystemExit(f"missing final review origin: {entry_id}")
        human_reviewed_count += 1
        entries.append(
            {
                "id": entry_id,
                "source_text_sha256": source_hash,
                "translation": translation,
                "editorial_status": "reviewed",
                "review_origin": review_origin,
                "domains": domains,
                "tags": sorted({str(item.get("tag")) for item in references}),
                "glossary_refs": sorted(
                    {
                        str(item.get("id"))
                        for item in row.get("glossary_terms", [])
                        if (
                            isinstance(item, dict)
                            and item.get("id")
                            and isinstance(item.get("translation"), str)
                            and str(item["translation"])
                            in translation.replace("\n", "").replace("　", "")
                        )
                    }
                ),
            }
        )

    if (
        reference_count != EXPECTED_FIELD_REFERENCE_COUNT
        or human_reviewed_count != EXPECTED_HUMAN_REVIEWED_COUNT
        or human_reviewed_count + deterministic_reviewed_count != EXPECTED_COUNT
    ):
        raise SystemExit("LIBRARY review/reference count drift")
    document = {
        "schema_version": 1,
        "kind": "library_v0.2_reviewed_corpus",
        "release": "0.2.0",
        "status": "reviewed",
        "release_eligible": True,
        "source_text_in_corpus": False,
        "source": {
            "provider": "Alibaba Cloud DashScope",
            "model": "deepseek-v4-flash-0731",
            "candidate_sha256": CANDIDATE_SHA256,
            "source_queue_sha256": QUEUE_SHA256,
            "validated_draft_sha256": DRAFT_SHA256,
            "final_editorial_decisions_sha256": FINAL_DECISIONS_SHA256,
            "final_editorial_manifest_sha256": FINAL_MANIFEST_SHA256,
        },
        "review": {
            "method": "full source-first audit, revision adjudication, no-op revision repair, authoritative display-name preservation, manual source-verified overrides, and strict final validation",
            "candidate_changed_count": final_manifest.get("coverage", {}).get(
                "changed_from_candidate_count"
            ),
            "human_reviewed_count": human_reviewed_count,
            "deterministic_reviewed_count": deterministic_reviewed_count,
            "unresolved_risk_count": 0,
        },
        "summary": {
            "entry_count": len(entries),
            "field_reference_count": reference_count,
            "human_reviewed_count": human_reviewed_count,
            "deterministic_reviewed_count": deterministic_reviewed_count,
            "domain_unique_text_counts": dict(sorted(domain_counts.items())),
        },
        "entries": entries,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(
        f"library reviewed corpus: entries={len(entries)} refs={reference_count} "
        f"human={human_reviewed_count} deterministic={deterministic_reviewed_count} "
        f"sha256={sha256_bytes(output.read_bytes())}"
    )
    print(output.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
