#!/usr/bin/env python3
"""Build the offline Stage 0 and LIBRARY editorial review artifact.

The generated files live under work/review and are deliberately separate from
the formal corpus.  This builder never promotes translations or writes an ISO.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

try:
    from srwz.glossary import (
        apply_glossary_variants,
        deprecated_translation_conflicts,
        global_glossary_by_id,
        load_global_glossary,
        relevant_glossary_terms,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.srwz.glossary import (
        apply_glossary_variants,
        deprecated_translation_conflicts,
        global_glossary_by_id,
        load_global_glossary,
        relevant_glossary_terms,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "work/review/editorial/stage0-library"
STAGE_SOURCE = ROOT / "work/review/aliyun/stage0-system-dialogue/source.json"
STAGE_CORPUS = ROOT / "corpus/zh/story-system-dialogue.json"
STAGE_POLISH = ROOT / "config/editorial/stage0-polish.json"
LIBRARY_SOURCE = ROOT / "work/review/aliyun/library-v0.2/source-queue.jsonl"
LIBRARY_DRAFT = ROOT / (
    "work/review/aliyun/library-v0.2/deepseek-v4-flash-0731/"
    "aggregate/validated.jsonl"
)
LIBRARY_AUDIT = ROOT / (
    "work/review/aliyun/library-v0.2/deepseek-v4-flash-0731/"
    "editorial-audit/review-queue.jsonl"
)
LIBRARY_POLISH = ROOT / "config/editorial/library-polish.json"
LIBRARY_REVIEWED = ROOT / "config/editorial/library-reviewed.json"
GLOSSARY_DIR = ROOT / "corpus/glossary"
TEMPLATE = ROOT / "tools/editorial_review/index.template.html"
DATA_MARKER = "__SRWZ_REVIEW_DATA__"
CONTEXT_SENSITIVE_HARD_TERM_PREFIXES = ("spirit/",)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            rows.append(row)
    return rows


def require_unique(rows: Iterable[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label}: missing {key}")
        if value in result:
            raise ValueError(f"{label}: duplicate {key} {value}")
        result[value] = row
    return result


def target_hex(target: dict[str, Any]) -> str:
    return f"{int(target['text_offset']):06X}"


def build_stage_rows() -> tuple[list[dict[str, Any]], dict[str, int]]:
    source = load_json(STAGE_SOURCE)
    corpus = load_json(STAGE_CORPUS)
    polish = load_json(STAGE_POLISH)
    if polish.get("promotion_allowed") is not False:
        raise ValueError("Stage 0 polish config must remain candidate-only")

    corpus_by_id = require_unique(corpus["entries"], "id", "Stage 0 corpus")
    source_invocations = require_unique(source["invocations"], "id", "Stage 0 source invocations")
    polish_by_target = require_unique(polish["entries"], "target", "Stage 0 polish")
    seen_polish: set[str] = set()
    rows: list[dict[str, Any]] = []

    for target in source["targets"]:
        target_id = target_hex(target)
        translations: list[str] = []
        statuses: list[str] = []
        for invocation_id in target["invocation_ids"]:
            entry = corpus_by_id.get(invocation_id)
            if entry is None:
                raise ValueError(f"Stage 0 target {target_id}: missing {invocation_id}")
            if entry["source_text_sha256"] != target["source_text_sha256"]:
                raise ValueError(f"Stage 0 target {target_id}: source hash mismatch")
            translations.append(entry["translation"])
            statuses.append(entry.get("editorial_status", "unknown"))
        unique_translations = list(dict.fromkeys(translations))
        if len(unique_translations) != 1:
            raise ValueError(f"Stage 0 target {target_id}: divergent invocation translations")

        current = unique_translations[0]
        override = polish_by_target.get(target_id)
        note = "Codex 已逐条对照日文和现有译文；未发现必须改写的问题。"
        risks: list[str] = []
        if override:
            seen_polish.add(target_id)
            if override["source_text_sha256"] != target["source_text_sha256"]:
                raise ValueError(f"Stage 0 polish {target_id}: source hash mismatch")
            candidate = override["translation"]
            note = override["note"]
            risks = list(override.get("risks", []))
        else:
            candidate = current

        rows.append(
            {
                "id": target["id"],
                "short_id": target_id,
                "category": "stage0",
                "domains": ["stage0"],
                "kind": "system_dialogue",
                "speaker": target.get("speaker_zh") or target.get("speaker") or "",
                "source_text": target["source_text"],
                "source_text_sha256": target["source_text_sha256"],
                "current_translation": current,
                "candidate_translation": candidate,
                "changed": candidate != current,
                "review_origin": "codex_reworded" if candidate != current else "codex_checked",
                "editorial_note": note,
                "risks": risks,
                "risk_details": [],
                "glossary_terms": [],
                "references": [
                    {
                        "field_id": invocation_id,
                        "domain": "stage0",
                        "scene": source_invocations[invocation_id]["scene"],
                    }
                    for invocation_id in target["invocation_ids"]
                ],
                "scenes": target.get("scenes", []),
                "tags": [],
                "source_status": list(dict.fromkeys(statuses)),
            }
        )

    missing = set(polish_by_target) - seen_polish
    if missing:
        raise ValueError(f"Stage 0 polish targets not found: {sorted(missing)}")
    if len(rows) != int(source["unique_text_target_count"]):
        raise ValueError("Stage 0 unique target count mismatch")
    stats = {
        "total": len(rows),
        "changed": sum(row["changed"] for row in rows),
        "risk": sum(bool(row["risks"]) for row in rows),
    }
    return rows, stats


def apply_library_rules(
    text: str,
    config: dict[str, Any],
    glossary_terms: Iterable[dict[str, Any]] = (),
) -> tuple[str, list[str]]:
    candidate, applied = apply_glossary_variants(text, glossary_terms)
    for rule in config["literal_replacements"]:
        if rule["from"] in candidate:
            candidate = candidate.replace(rule["from"], rule["to"])
            applied.append(f"{rule['from']}→{rule['to']}")

    style = config["style_rules"]
    if style.get("normalize_curly_single_quote_pairs"):
        normalized = re.sub(r"‘([^’\n]+)’", r"“\1”", candidate)
        if normalized != candidate:
            candidate = normalized
            applied.append("中文单引号→中文双引号")
    if style.get("normalize_ascii_quote_pairs"):
        normalized = re.sub(r'"([^"\n]+)"', r"“\1”", candidate)
        if normalized != candidate:
            candidate = normalized
            applied.append("ASCII双引号→中文双引号")
    if style.get("normalize_plant_token"):
        normalized = re.sub(r"(?<![A-Za-z])plant(?![A-Za-z])", "PLANT", candidate, flags=re.I)
        if normalized != candidate:
            candidate = normalized
            applied.append("PLANT大小写")
    return candidate, applied


BODY_TAGS = {"DSC2", "DSCR", "CHFN", "CHNN"}
JAPANESE_KANA_RE = re.compile(r"[ぁ-ゖァ-ヺー]")


def library_row_kind(tags: Iterable[str]) -> str:
    return "body" if any(tag in BODY_TAGS for tag in tags) else "name_or_metadata"


def normalized_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def ascii_key(text: str) -> str:
    """Return a comparison key for Latin/digit audit values.

    Punctuation and spacing differ freely between the Japanese source, the
    glossary and a translated field (for example ``GAT-X`` versus ``GAT X``).
    The audit only needs to know whether the Latin token has provenance in one
    of those two deterministic sources.
    """

    return re.sub(r"[^a-z0-9]", "", normalized_text(text).lower())


def unresolved_ascii_values(
    values: Iterable[Any],
    *,
    candidate: str,
    source_match_text: str,
    glossary_by_id: dict[str, Any],
    relevant_term_ids: set[str],
) -> list[Any]:
    """Keep only residual Latin values not grounded in source or glossary."""

    candidate_key = ascii_key(candidate)
    source_key = ascii_key(source_match_text)
    glossary_keys = [
        ascii_key(str(glossary_by_id[term_id].get("translation", "")))
        for term_id in relevant_term_ids
        if term_id in glossary_by_id
    ]
    glossary_keys = [key for key in glossary_keys if key]
    unresolved: list[Any] = []
    for value in values:
        key = ascii_key(str(value))
        # Audit values describe the immutable machine draft.  A deterministic
        # terminology rule or human edit may already have removed one from the
        # final candidate, in which case it is no longer a residual risk.
        if key and key not in candidate_key:
            continue
        if key and key in source_key:
            continue
        if key and any(key in glossary_key or glossary_key in key for glossary_key in glossary_keys):
            continue
        unresolved.append(value)
    return unresolved


def filter_library_risk_details(
    risk_details: Iterable[dict[str, Any]],
    *,
    source_text: str,
    source_match_text: str,
    candidate: str,
    kind: str,
    config: dict[str, Any],
    glossary_by_id: dict[str, Any],
    relevant_term_ids: set[str],
) -> list[dict[str, Any]]:
    """Re-evaluate fixed-draft warnings after deterministic editorial rules."""

    contextual_ids = set(config.get("contextual_glossary_ids", []))
    contextual_prefixes = tuple(config.get("body_contextual_glossary_prefixes", []))
    filtered: list[dict[str, Any]] = []

    for detail in risk_details:
        code = detail.get("code")
        if code == "unchanged_source":
            # Numeric specifications, Latin product names and Han-only labels
            # may legitimately be identical in Japanese and Chinese.  Only an
            # unchanged field that still contains Japanese kana needs a human.
            if (
                normalized_text(candidate) == normalized_text(source_text)
                and JAPANESE_KANA_RE.search(source_match_text)
            ):
                filtered.append(detail)
            continue

        # The collision audit belongs to the fixed machine snapshot.  Manual
        # rewrites and deterministic terminology rules can change collision
        # groups, so they are recomputed from final candidates below.
        if code == "translation_collision":
            continue

        if code == "ascii_word":
            unresolved = unresolved_ascii_values(
                detail.get("values", []),
                candidate=candidate,
                source_match_text=source_match_text,
                glossary_by_id=glossary_by_id,
                relevant_term_ids=relevant_term_ids,
            )
            if unresolved:
                updated = dict(detail)
                updated["values"] = unresolved
                filtered.append(updated)
            continue

        if code != "glossary_hint_mismatch":
            filtered.append(detail)
            continue

        unresolved: list[dict[str, Any]] = []
        for term in detail.get("terms", []):
            term_id = term.get("id", "")
            # The machine-draft audit was produced before the global glossary
            # matcher became the single source of truth.  Do not carry a stale
            # extraction hint into the human queue when the Japanese source no
            # longer binds that term under the current boundary rules.
            if term_id not in relevant_term_ids:
                continue
            global_term = glossary_by_id.get(term_id, {})
            # Proposed/researched terms are useful editorial hints, not global
            # consistency contracts.  Only an approved, explicitly enforced
            # term is allowed to create a blocking/manual risk.
            if not (
                global_term.get("status") == "approved"
                and global_term.get("enforce") is True
            ):
                continue
            canonical = global_term.get("translation", term.get("target", ""))
            if canonical and canonical in candidate:
                continue
            if term_id in contextual_ids:
                continue
            if kind == "body" and term_id.startswith(contextual_prefixes):
                continue
            unresolved_term = dict(term)
            if canonical and canonical != term.get("target"):
                unresolved_term["canonical"] = canonical
            unresolved.append(unresolved_term)
        if unresolved:
            updated = dict(detail)
            updated["terms"] = unresolved
            filtered.append(updated)

    return filtered


def find_term_conflicts(
    candidate: str, glossary_terms: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [dict(item) for item in deprecated_translation_conflicts(candidate, glossary_terms)]


def add_library_collision_risks(
    rows: list[dict[str, Any]],
    accepted_groups: Iterable[dict[str, Any]] = (),
) -> None:
    accepted: dict[tuple[str, frozenset[str]], str] = {}
    for item in accepted_groups:
        translation = item.get("translation")
        ids = item.get("ids")
        reason = item.get("reason")
        if (
            not isinstance(translation, str)
            or not translation
            or not isinstance(ids, list)
            or len(ids) < 2
            or not all(isinstance(row_id, str) and row_id for row_id in ids)
            or len(set(ids)) != len(ids)
            or not isinstance(reason, str)
            or not reason
        ):
            raise ValueError("invalid accepted LIBRARY collision group")
        key = (translation, frozenset(ids))
        if key in accepted:
            raise ValueError(f"duplicate accepted LIBRARY collision group: {translation}")
        accepted[key] = reason

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["candidate_translation"], []).append(row)

    seen_accepted: set[tuple[str, frozenset[str]]] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        distinct_sources = {
            re.sub(r"\s+", "", normalized_text(row["source_text"]))
            for row in group
        }
        # Full-width and line-wrapped duplicates are the same source surface,
        # not a localization collision.
        if len(distinct_sources) < 2:
            continue
        group_key = (
            group[0]["candidate_translation"],
            frozenset(str(row.get("id", "")) for row in group),
        )
        if group_key in accepted:
            seen_accepted.add(group_key)
            continue
        detail = {"code": "translation_collision", "group_size": len(group)}
        for row in group:
            row["risk_details"].append(dict(detail))
            row["risks"] = sorted(set([*row["risks"], "translation_collision"]))

    stale = set(accepted) - seen_accepted
    if stale:
        labels = sorted(f"{translation}: {sorted(ids)}" for translation, ids in stale)
        raise ValueError(f"stale accepted LIBRARY collision groups: {labels}")


def build_library_rows() -> tuple[list[dict[str, Any]], dict[str, int]]:
    source_rows = load_jsonl(LIBRARY_SOURCE)
    draft_rows = load_jsonl(LIBRARY_DRAFT)
    audit_rows = load_jsonl(LIBRARY_AUDIT)
    config = load_json(LIBRARY_POLISH)
    reviewed = load_json(LIBRARY_REVIEWED)
    if config.get("promotion_allowed") is not False:
        raise ValueError("LIBRARY polish config must remain candidate-only")
    if reviewed.get("promotion_allowed") is not False:
        raise ValueError("LIBRARY reviewed corpus must remain candidate-only")

    global_glossary = load_global_glossary(GLOSSARY_DIR)
    glossary_by_id = dict(global_glossary_by_id(global_glossary))
    global_variant_terms = [
        term
        for term in global_glossary
        if term.get("variant_scope") == "global"
        and term.get("deprecated_translations")
    ]

    draft_by_id = require_unique(draft_rows, "id", "LIBRARY draft")
    audit_by_id = require_unique(audit_rows, "id", "LIBRARY audit")
    reviewed_by_id = require_unique(
        reviewed.get("entries", []), "id", "LIBRARY reviewed entries"
    )
    seen_reviewed: set[str] = set()
    rows: list[dict[str, Any]] = []
    for source in source_rows:
        row_id = source["id"]
        draft = draft_by_id.get(row_id)
        if draft is None:
            raise ValueError(f"LIBRARY draft missing {row_id}")
        if draft["source_text_sha256"] != source["source_text_sha256"]:
            raise ValueError(f"LIBRARY source hash mismatch for {row_id}")
        if draft.get("model") != config["source_model"]:
            raise ValueError(f"LIBRARY {row_id}: unexpected model {draft.get('model')}")

        current = draft["translation"]
        # Bind terminology against the extraction-time unwrapped text.  The
        # raw game field contains visual line breaks which can split one
        # katakana name (for example ダイク\nン) and create false substring
        # matches.  Provenance remains pinned to the raw source hash below.
        glossary_match_text = source.get("model_source_text", source["source_text"])
        glossary_terms = relevant_glossary_terms(
            glossary_match_text,
            global_glossary,
            context_sensitive_hard_prefixes=(
                CONTEXT_SENSITIVE_HARD_TERM_PREFIXES
            ),
        )
        rule_terms_by_id = {
            str(term["id"]): term for term in global_variant_terms
        }
        rule_terms_by_id.update(
            {str(term["id"]): term for term in glossary_terms}
        )
        rule_terms = list(rule_terms_by_id.values())
        human_review = reviewed_by_id.get(row_id)
        if human_review is not None:
            seen_reviewed.add(row_id)
            if human_review.get("source_text_sha256") != source["source_text_sha256"]:
                raise ValueError(f"LIBRARY reviewed source hash mismatch for {row_id}")
            reviewed_translation = human_review.get("translation")
            if not isinstance(reviewed_translation, str) or not reviewed_translation:
                raise ValueError(f"LIBRARY reviewed translation is empty for {row_id}")
            candidate_input = reviewed_translation
        else:
            candidate_input = current
        candidate, applied = apply_library_rules(candidate_input, config, rule_terms)
        references = source.get("references", [])
        domains = sorted({reference.get("domain", "unknown") for reference in references})
        tags = sorted({reference.get("tag", "") for reference in references if reference.get("tag")})
        kind = library_row_kind(tags)
        audit = audit_by_id.get(row_id)
        risk_details = filter_library_risk_details(
            audit.get("risk_reasons", []) if audit else [],
            source_text=source["source_text"],
            source_match_text=glossary_match_text,
            candidate=candidate,
            kind=kind,
            config=config,
            glossary_by_id=glossary_by_id,
            relevant_term_ids={str(term["id"]) for term in glossary_terms},
        )
        accepted_audit_risks: list[str] = []
        if human_review is not None:
            raw_accepted = human_review.get("accepted_audit_risks", [])
            if not isinstance(raw_accepted, list) or not all(
                isinstance(code, str) and code for code in raw_accepted
            ):
                raise ValueError(
                    f"LIBRARY reviewed accepted_audit_risks is invalid for {row_id}"
                )
            accepted_audit_risks = sorted(set(raw_accepted))
        risks = [risk.get("code", "unknown") for risk in risk_details]
        conflicts = find_term_conflicts(candidate, rule_terms)
        if conflicts:
            risks.append("term_conflict")
            risk_details.extend(conflicts)

        rows.append(
            {
                "id": row_id,
                "short_id": row_id.rsplit("/", 1)[-1],
                "category": "library",
                "domains": domains,
                "kind": kind,
                "speaker": "",
                "source_text": source["source_text"],
                "source_text_sha256": source["source_text_sha256"],
                "current_translation": current,
                "candidate_translation": candidate,
                "changed": candidate != current,
                "review_origin": (
                    "codex_human_review"
                    if human_review is not None
                    else "codex_consistency_pass"
                ),
                "editorial_note": (
                    "；".join(
                        [
                            *(
                                [str(human_review.get("note", "Codex 人工复核。"))]
                                if human_review is not None
                                else []
                            ),
                            *applied,
                        ]
                    )
                    if human_review is not None or applied
                    else "已按当前剧情术语层复核；仍需人工确认内容和语气。"
                ),
                "risks": sorted(set(risks)),
                "risk_details": risk_details,
                "accepted_audit_risks": accepted_audit_risks,
                "glossary_terms": glossary_terms,
                "references": references,
                "scenes": [],
                "tags": tags,
                "source_status": [draft.get("editorial_status", "machine_draft")],
            }
        )

    if len(source_rows) != len(draft_rows):
        raise ValueError("LIBRARY source/draft row count mismatch")
    if set(draft_by_id) != {row["id"] for row in source_rows}:
        raise ValueError("LIBRARY source/draft ID set mismatch")
    missing_reviewed = set(reviewed_by_id) - seen_reviewed
    if missing_reviewed:
        raise ValueError(
            f"LIBRARY reviewed IDs not found in source queue: {sorted(missing_reviewed)}"
        )

    add_library_collision_risks(rows, config.get("accepted_collision_groups", []))
    for row in rows:
        accepted_audit_risks = set(row["accepted_audit_risks"])
        if "term_conflict" in accepted_audit_risks:
            raise ValueError(
                f"LIBRARY reviewed term conflicts cannot be accepted for {row['id']}"
            )
        available_audit_risks = {
            str(detail.get("code", "unknown")) for detail in row["risk_details"]
        }
        stale_acceptances = accepted_audit_risks - available_audit_risks
        if stale_acceptances:
            raise ValueError(
                f"LIBRARY reviewed accepted risks are stale for {row['id']}: "
                f"{sorted(stale_acceptances)}"
            )
        row["risk_details"] = [
            detail
            for detail in row["risk_details"]
            if detail.get("code") not in accepted_audit_risks
        ]
        row["risks"] = sorted(
            {
                str(detail.get("code", "unknown"))
                for detail in row["risk_details"]
            }
        )

    stats = {
        "total": len(rows),
        "changed": sum(row["changed"] for row in rows),
        "risk": sum(bool(row["risks"]) for row in rows),
        "human_reviewed": sum(
            row["review_origin"] == "codex_human_review" for row in rows
        ),
    }
    return rows, stats


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build(output_dir: Path) -> dict[str, Any]:
    stage_rows, stage_stats = build_stage_rows()
    library_rows, library_stats = build_library_rows()
    rows = stage_rows + library_rows
    data = {
        "schema_version": 1,
        "kind": "srwz_editorial_review",
        "promotion_allowed": False,
        "dataset_id": "",
        "summary": {
            "total": len(rows),
            "stage0": stage_stats,
            "library": library_stats,
        },
        "rows": rows,
    }
    dataset_seed = compact_json({"summary": data["summary"], "rows": rows}).encode("utf-8")
    data["dataset_id"] = sha256_bytes(dataset_seed)

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_bytes = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    candidate_path = output_dir / "candidate.json"
    candidate_path.write_bytes(candidate_bytes)

    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(DATA_MARKER) != 1:
        raise ValueError(f"Template must contain exactly one {DATA_MARKER} marker")
    embedded = compact_json(data).replace("</script", "<\\/script")
    html = template.replace(DATA_MARKER, embedded)
    html_path = output_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")

    inputs = [
        STAGE_SOURCE,
        STAGE_CORPUS,
        STAGE_POLISH,
        LIBRARY_SOURCE,
        LIBRARY_DRAFT,
        LIBRARY_AUDIT,
        LIBRARY_POLISH,
        LIBRARY_REVIEWED,
        *sorted(GLOSSARY_DIR.glob("*.json")),
        TEMPLATE,
    ]
    manifest = {
        "schema_version": 1,
        "kind": "srwz_editorial_review_manifest",
        "promotion_allowed": False,
        "dataset_id": data["dataset_id"],
        "summary": data["summary"],
        "inputs": [
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256_file(path),
            }
            for path in inputs
        ],
        "outputs": [
            {"path": "candidate.json", "sha256": sha256_file(candidate_path)},
            {"path": "index.html", "sha256": sha256_file(html_path)},
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT.relative_to(ROOT)})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    manifest = build(output_dir.resolve())
    print(json.dumps(manifest["summary"], ensure_ascii=False, sort_keys=True))
    print(output_dir / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
