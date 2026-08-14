#!/usr/bin/env python3
"""Merge all v0.2 LIBRARY audit layers into final locked decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

try:
    import run_aliyun_library_v02_batch as api
    import run_library_v02_full_editorial_audit as first_pass
    from srwz.library import (
        LibraryScopeError,
        apply_library_rules,
        apply_source_bound_review_replacements,
        apply_source_surface_replacements,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools import run_aliyun_library_v02_batch as api
    from tools import run_library_v02_full_editorial_audit as first_pass
    from tools.srwz.library import (
        LibraryScopeError,
        apply_library_rules,
        apply_source_bound_review_replacements,
        apply_source_surface_replacements,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = first_pass.DEFAULT_CANDIDATE
DEFAULT_FIRST_PASS = first_pass.DEFAULT_OUTPUT / "aggregate/reviews.jsonl"
DEFAULT_PROPOSED_ADJUDICATION = PROJECT_ROOT / (
    "work/review/editorial/library-v0.2-adjudication-v1/aggregate/decisions.jsonl"
)
DEFAULT_NOOP_SCOPE = PROJECT_ROOT / (
    "work/review/editorial/library-v0.2-noop-revisions-v1/reviews.jsonl"
)
DEFAULT_NOOP_ADJUDICATION = PROJECT_ROOT / (
    "work/review/editorial/library-v0.2-noop-adjudication-v1/aggregate/decisions.jsonl"
)
DEFAULT_OVERRIDES = (
    PROJECT_ROOT / "config/library/v0.2-editorial-overrides.json"
)
LIBRARY_POLISH = PROJECT_ROOT / "config/editorial/library-polish.json"
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "work/review/editorial/library-v0.2-final-v1"
)
PROSE_TAGS = {"DSCR", "DSC2"}
KNOWN_BAD_SUBSTRINGS = (
    "与与",
    "与和迪兰达尔",
    "被受到",
    "活动活性化",
    "青骑士青骑士",
    "赤骑士赤骑士",
    "开发的 神意高达",
    "发现了 原形",
    "的 阿芙洛黛A",
    "玛尤·阿斯哈",
    "Z GMF",
    "Z G M F",
    "新地球联邦军军人",
    "迪安娜反击军军曹",
    "迪安娜回归军军曹",
)
REQUIRED_TERM_ALLOWLIST = {
    # フリーダム is part of Freedom Space Corps, not Freedom Gundam.
    ("library-text/436b18a376794818", "unit/freedom-gundam"),
    ("library-text/bd12a38ef638c247", "unit/freedom-gundam"),
    # Preserve the authoritative work-title surface.
    ("library-text/621a52ab33ae7a7c", "unit/god-sigma"),
    # 強化人間 is explanatory prose for the C.E. Extended category here,
    # not the Universal Century Cyber-Newtype proper noun.
    ("library-text/3dcda804caa2dbbc", "skill/cyber-newtype"),
    ("library-text/75b88504bff44899", "skill/cyber-newtype"),
    ("library-text/b1bfeb34cfaf8c3e", "skill/cyber-newtype"),
}


def reconcile_current_candidate_rules(
    translation: str,
    candidate: Mapping[str, object],
) -> tuple[str, list[str]]:
    """Replay current source-bound terminology after the fixed old audit.

    The prose audit is an immutable snapshot.  Names and unit terms continue
    to improve afterwards, so accepting an old prose revision must not restore
    a superseded Chinese surface.  Explicit final overrides remain later in
    the pipeline and therefore retain the highest priority.
    """

    config = json.loads(LIBRARY_POLISH.read_text(encoding="utf-8"))
    raw_terms = candidate.get("glossary_terms", [])
    if not isinstance(raw_terms, list) or not all(
        isinstance(term, Mapping) for term in raw_terms
    ):
        raise LibraryScopeError(
            f"invalid candidate glossary terms: {candidate.get('id')}"
        )
    terms = [dict(term) for term in raw_terms]
    reconciled, applied = apply_library_rules(
        translation,
        config,
        terms,
    )
    reconciled, source_bound_applied = (
        apply_source_bound_review_replacements(
            reconciled,
            config,
            {str(term["id"]) for term in terms},
        )
    )
    applied.extend(source_bound_applied)
    source_text = candidate.get("source_text")
    if not isinstance(source_text, str):
        raise LibraryScopeError(
            f"invalid candidate source text: {candidate.get('id')}"
        )
    reconciled, surface_applied = apply_source_surface_replacements(
        reconciled,
        source_text,
        config,
    )
    applied.extend(surface_applied)
    return reconciled, applied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--first-pass", type=Path, default=DEFAULT_FIRST_PASS)
    parser.add_argument(
        "--proposed-adjudication",
        type=Path,
        default=DEFAULT_PROPOSED_ADJUDICATION,
    )
    parser.add_argument("--noop-scope", type=Path, default=DEFAULT_NOOP_SCOPE)
    parser.add_argument(
        "--noop-adjudication", type=Path, default=DEFAULT_NOOP_ADJUDICATION
    )
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
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


def unique_by_id(rows: Sequence[dict[str, object]], label: str) -> dict[str, dict[str, object]]:
    result = {str(row.get("id")): row for row in rows}
    if len(result) != len(rows) or "None" in result:
        raise LibraryScopeError(f"{label} has duplicate or missing IDs")
    return result


def normalized_source(text: str) -> str:
    return re.sub(r"[\s　]+", "", text)


def load_overrides(path: Path, candidates: Mapping[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise LibraryScopeError("editorial override entries are missing")
    result = unique_by_id(entries, "editorial overrides")
    for row_id, entry in result.items():
        candidate = candidates.get(row_id)
        if candidate is None:
            raise LibraryScopeError(f"unknown editorial override ID: {row_id}")
        if entry.get("source_text_sha256") != candidate.get("source_text_sha256"):
            raise LibraryScopeError(f"editorial override source drift: {row_id}")
        if not isinstance(entry.get("translation"), str) or not entry["translation"]:
            raise LibraryScopeError(f"empty editorial override: {row_id}")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise LibraryScopeError(f"missing editorial override reason: {row_id}")
    return result


def final_rows(
    *,
    candidate_rows: Sequence[dict[str, object]],
    first_reviews: Sequence[dict[str, object]],
    proposed_decisions: Sequence[dict[str, object]],
    noop_scope: Sequence[dict[str, object]],
    noop_decisions: Sequence[dict[str, object]],
    overrides: Mapping[str, dict[str, object]],
) -> list[dict[str, object]]:
    candidates = unique_by_id(candidate_rows, "candidate")
    first = unique_by_id(first_reviews, "first-pass reviews")
    if len(candidates) != 2709 or set(first) != set(candidates):
        raise LibraryScopeError("candidate/first-pass coverage drift")
    proposed = unique_by_id(proposed_decisions, "proposed adjudication")
    expected_proposed = {
        row_id for row_id, row in first.items() if row.get("verdict") == "revise"
    }
    if set(proposed) != expected_proposed:
        raise LibraryScopeError("proposed adjudication coverage drift")
    noop_scope_by_id = unique_by_id(noop_scope, "no-op scope")
    if len(noop_scope_by_id) != 2709 or set(noop_scope_by_id) != set(candidates):
        raise LibraryScopeError("no-op scope coverage drift")
    noop = unique_by_id(noop_decisions, "no-op adjudication")
    expected_noop = {
        row_id
        for row_id, row in noop_scope_by_id.items()
        if row.get("verdict") == "revise"
    }
    if set(noop) != expected_noop:
        raise LibraryScopeError("no-op adjudication coverage drift")

    output: list[dict[str, object]] = []
    for candidate in candidate_rows:
        row_id = str(candidate["id"])
        translation = str(candidate["candidate_translation"])
        origin = "first_pass_keep"
        review = first[row_id]
        is_prose = bool(set(candidate.get("tags", [])) & PROSE_TAGS)
        if review.get("verdict") == "revise":
            decision = proposed[row_id]
            choice = str(decision.get("choice"))
            if not is_prose:
                origin = "authoritative_surface_preserved"
            elif choice == "proposed":
                translation = str(review["translation"])
                origin = "first_pass_revision_adjudicated"
            elif choice == "custom":
                translation = str(decision["translation"])
                origin = "proposed_revision_custom_adjudication"
            elif choice == "current":
                origin = "proposed_revision_rejected"
            else:
                raise LibraryScopeError(f"unknown proposed decision: {row_id}")
        if row_id in noop:
            decision = noop[row_id]
            choice = str(decision.get("choice"))
            if not is_prose:
                origin = "authoritative_surface_preserved"
            elif choice == "custom":
                translation = str(decision["translation"])
                origin = "noop_revision_repaired"
            elif choice == "current":
                origin = "noop_revision_rejected"
            else:
                raise LibraryScopeError(f"unknown no-op decision: {row_id}")
        reconciled, terminology_applied = reconcile_current_candidate_rules(
            translation,
            candidate,
        )
        if reconciled != translation:
            translation = reconciled
            origin = f"{origin}_current_terminology"
        if row_id in overrides:
            translation = str(overrides[row_id]["translation"])
            origin = "manual_source_verified_override"
        normalized_translation = translation.replace("＜", "（").replace("＞", "）")
        if normalized_translation != translation:
            translation = normalized_translation
            origin = "deterministic_bracket_normalization"
        output.append(
            {
                "schema_version": 1,
                "id": row_id,
                "source_text_sha256": candidate["source_text_sha256"],
                "translation": translation,
                "decision_origin": origin,
                "changed_from_candidate": translation
                != candidate["candidate_translation"],
                "domains": sorted(
                    {
                        str(reference["domain"])
                        for reference in candidate.get("references", [])
                    }
                ),
                "tags": sorted({str(tag) for tag in candidate.get("tags", [])}),
            }
        )
    return output


def validate_final(
    rows: Sequence[dict[str, object]],
    candidates: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    failures: list[dict[str, str]] = []
    bad_substrings: list[dict[str, str]] = []
    required_term_failures: list[dict[str, str]] = []
    for row in rows:
        row_id = str(row["id"])
        text = str(row["translation"])
        if (
            not text
            or "\n" in text
            or "\r" in text
            or api.KANA_PATTERN.search(text)
            or any(mark in text for mark in ("「", "」", "『", "』", "＜", "＞"))
            or "..." in text
        ):
            failures.append({"id": row_id, "kind": "format", "text": text})
        for token in KNOWN_BAD_SUBSTRINGS:
            if token in text:
                bad_substrings.append({"id": row_id, "token": token})
        candidate = candidates[row_id]
        for term in candidate.get("glossary_terms", []):
            if not isinstance(term, Mapping) or term.get("enforce") is not True:
                continue
            target = term.get("translation")
            term_id = str(term.get("id"))
            if (
                isinstance(target, str)
                and target
                and target not in text
                and (row_id, term_id) not in REQUIRED_TERM_ALLOWLIST
            ):
                required_term_failures.append(
                    {"id": row_id, "term_id": term_id, "target": target}
                )

    groups: dict[str, list[str]] = defaultdict(list)
    for row_id, candidate in candidates.items():
        groups[normalized_source(str(candidate["source_text"]))].append(row_id)
    identical_source_mismatches: list[dict[str, object]] = []
    final_by_id = {str(row["id"]): str(row["translation"]) for row in rows}
    for source, row_ids in groups.items():
        translations = {final_by_id[row_id] for row_id in row_ids}
        if len(row_ids) > 1 and len(translations) > 1:
            identical_source_mismatches.append(
                {
                    "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    "ids": row_ids,
                    "translations": sorted(translations),
                }
            )
    strict = not (
        failures
        or bad_substrings
        or required_term_failures
        or identical_source_mismatches
    )
    return {
        "strict_passed": strict,
        "format_failures": failures,
        "known_bad_substrings": bad_substrings,
        "required_term_failures": required_term_failures,
        "identical_source_mismatches": identical_source_mismatches,
    }


def main() -> int:
    args = parse_args()
    paths = {
        name: project_path(value).resolve()
        for name, value in {
            "candidate": args.candidate,
            "first_pass": args.first_pass,
            "proposed_adjudication": args.proposed_adjudication,
            "noop_scope": args.noop_scope,
            "noop_adjudication": args.noop_adjudication,
            "overrides": args.overrides,
        }.items()
    }
    output_dir = project_path(args.output_dir).resolve()
    if PROJECT_ROOT not in output_dir.parents or "work" not in output_dir.parts:
        raise LibraryScopeError("final editorial output must remain below project work/")
    candidate_doc = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    candidate_rows = [
        row
        for row in candidate_doc.get("rows", [])
        if row.get("category") == "library"
    ]
    candidates = unique_by_id(candidate_rows, "candidate")
    overrides = load_overrides(paths["overrides"], candidates)
    rows = final_rows(
        candidate_rows=candidate_rows,
        first_reviews=api.read_jsonl(paths["first_pass"]),
        proposed_decisions=api.read_jsonl(paths["proposed_adjudication"]),
        noop_scope=api.read_jsonl(paths["noop_scope"]),
        noop_decisions=api.read_jsonl(paths["noop_adjudication"]),
        overrides=overrides,
    )
    output_path = output_dir / "final-decisions.jsonl"
    write_jsonl(output_path, rows)
    validation = validate_final(rows, candidates)
    write_json(output_dir / "validation.json", validation)
    origin_counts = Counter(str(row["decision_origin"]) for row in rows)
    changed_count = sum(bool(row["changed_from_candidate"]) for row in rows)
    manifest = {
        "schema_version": 1,
        "kind": "library_v0.2_final_editorial_decisions",
        "status": "reviewed" if validation["strict_passed"] else "blocked",
        "release_eligible": validation["strict_passed"],
        "source": {
            name: {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "sha256": sha256_file(path),
            }
            for name, path in paths.items()
        },
        "coverage": {
            "entry_count": len(rows),
            "changed_from_candidate_count": changed_count,
            "unchanged_count": len(rows) - changed_count,
            "decision_origin_counts": dict(sorted(origin_counts.items())),
            "manual_override_count": len(overrides),
        },
        "validation": validation,
        "output": {
            "path": str(output_path.relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(output_path),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    print(
        f"final editorial decisions: entries={len(rows)} changed={changed_count} "
        f"strict={validation['strict_passed']}"
    )
    print(f"origins={dict(sorted(origin_counts.items()))}")
    print(output_dir / "manifest.json")
    if not validation["strict_passed"]:
        raise LibraryScopeError("final editorial validation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
