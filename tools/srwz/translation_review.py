"""Fail-closed review contracts for committed SRWZ translations and terms."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


VALID_EDITORIAL_STATUSES = ("todo", "draft", "reviewed", "final")
EDITORIAL_STATUS_RANK = {
    status: rank for rank, status in enumerate(VALID_EDITORIAL_STATUSES)
}
VALID_TRANSLATION_ACTIONS = ("translate", "preserve")
VALID_GLOSSARY_STATUSES = ("proposed", "researched", "approved")
VALID_GLOSSARY_MATCH_MODES = ("substring", "token")
VALID_GLOSSARY_CATEGORIES = (
    "era",
    "event",
    "organization",
    "faction",
    "people",
    "place",
    "technology",
    "species",
    "unit",
    "item",
    "weapon",
    "system",
)
VALID_BATCH_STATUSES = (
    "planned",
    "in_progress",
    "draft_complete",
    "reviewed_complete",
    "final_complete",
)
VALID_TERMINOLOGY_DECISION_STATUSES = (
    "needs_human_review",
    "keep_current",
    "adopt_variant",
)
# Exclude Japanese punctuation such as the middle dot U+30FB. It is also used
# as a list marker in Chinese UI text and is not untranslated kana by itself.
KANA_PATTERN = re.compile(
    r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]"
)
STRUCTURAL_TOKEN_PATTERN = re.compile(
    r"\{[0-9A-Fa-f]{2}\}"
    r"|<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>"
    r"|%(?:\d+\$)?[diouxXeEfFgGcrsa]"
    r"|\$[A-Za-z]"
    r"|●+"
)


class TranslationReviewError(ValueError):
    """A translation release is stale, inconsistent, or not reviewable."""


@dataclass(frozen=True)
class GlossaryTerm:
    term_id: str
    source_terms: tuple[str, ...]
    translation: str
    category: str
    status: str
    domains: tuple[str, ...]
    enforce: bool
    notes: str
    source_match: str = "substring"


@dataclass(frozen=True)
class TranslationRecord:
    entry_id: str
    source_text_sha256: str
    translation: str
    editorial_status: str
    translation_action: str
    glossary_refs: tuple[str, ...]
    glossary_exceptions: tuple[str, ...]
    notes: str
    batch_id: str
    source_path: str


def _load_json_object(path: Path) -> Mapping[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TranslationReviewError(f"cannot load JSON {path}: {error}") from error
    if not isinstance(document, dict):
        raise TranslationReviewError(f"JSON root must be an object: {path}")
    return document


def _require_string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise TranslationReviewError(f"{context} must be a non-empty string")
    return value


def _require_string_list(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise TranslationReviewError(
            f"{context} must be an array of non-empty strings"
        )
    if len(value) != len(set(value)):
        raise TranslationReviewError(f"{context} contains duplicates")
    return tuple(value)


def load_source_corpus(path: Path) -> tuple[dict, ...]:
    entries = []
    seen = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TranslationReviewError(
            f"cannot load source corpus {path}: {error}"
        ) from error
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise TranslationReviewError(
                f"invalid source corpus JSON at {path}:{line_number}: {error}"
            ) from error
        if not isinstance(entry, dict):
            raise TranslationReviewError(
                f"source corpus row must be an object at {path}:{line_number}"
            )
        entry_id = _require_string(
            entry.get("id"),
            context=f"source corpus id at {path}:{line_number}",
        )
        if entry_id in seen:
            raise TranslationReviewError(
                f"duplicate source corpus id {entry_id!r}"
            )
        seen.add(entry_id)
        entries.append(entry)
    return tuple(entries)


def source_corpus_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise TranslationReviewError(
            f"cannot hash source corpus {path}: {error}"
        ) from error


def load_glossary(paths: Iterable[Path]) -> tuple[GlossaryTerm, ...]:
    terms = []
    seen = set()
    for path in paths:
        document = _load_json_object(path)
        if document.get("schema_version") != 1:
            raise TranslationReviewError(
                f"unsupported glossary schema in {path}"
            )
        raw_terms = document.get("terms")
        if not isinstance(raw_terms, list):
            raise TranslationReviewError(f"glossary terms must be an array: {path}")
        default_source_match = document.get(
            "default_source_match",
            "substring",
        )
        if default_source_match not in VALID_GLOSSARY_MATCH_MODES:
            raise TranslationReviewError(
                f"invalid default_source_match in {path}: "
                f"{default_source_match!r}"
            )
        for index, raw in enumerate(raw_terms):
            context = f"{path} term {index}"
            if not isinstance(raw, dict):
                raise TranslationReviewError(f"{context} must be an object")
            term_id = _require_string(raw.get("id"), context=f"{context} id")
            if term_id in seen:
                raise TranslationReviewError(
                    f"duplicate glossary term id {term_id!r}"
                )
            seen.add(term_id)
            category = _require_string(
                raw.get("category"),
                context=f"{context} category",
            )
            if category not in VALID_GLOSSARY_CATEGORIES:
                raise TranslationReviewError(
                    f"{context} has invalid category {category!r}"
                )
            status = _require_string(
                raw.get("status"),
                context=f"{context} status",
            )
            if status not in VALID_GLOSSARY_STATUSES:
                raise TranslationReviewError(
                    f"{context} has invalid status {status!r}"
                )
            domains = _require_string_list(
                raw.get("domains"),
                context=f"{context} domains",
            )
            if not set(domains) <= {"menu", "story", "summary"}:
                raise TranslationReviewError(
                    f"{context} has an invalid domain"
                )
            enforce = raw.get("enforce")
            if not isinstance(enforce, bool):
                raise TranslationReviewError(
                    f"{context} enforce must be boolean"
                )
            source_match = raw.get(
                "source_match",
                default_source_match,
            )
            if source_match not in VALID_GLOSSARY_MATCH_MODES:
                raise TranslationReviewError(
                    f"{context} has invalid source_match "
                    f"{source_match!r}"
                )
            terms.append(
                GlossaryTerm(
                    term_id=term_id,
                    source_terms=_require_string_list(
                        raw.get("source_terms"),
                        context=f"{context} source_terms",
                    ),
                    translation=_require_string(
                        raw.get("translation"),
                        context=f"{context} translation",
                    ),
                    category=category,
                    status=status,
                    domains=domains,
                    enforce=enforce,
                    notes=(
                        raw.get("notes")
                        if isinstance(raw.get("notes"), str)
                        else ""
                    ),
                    source_match=str(source_match),
                )
            )
    return tuple(terms)


def _term_occurs(term: GlossaryTerm, source_text: str) -> bool:
    if term.source_match == "substring":
        return any(
            source_term in source_text
            for source_term in term.source_terms
        )
    return any(
        source_text == source_term
        or f"「{source_term}」" in source_text
        or f"『{source_term}』" in source_text
        for source_term in term.source_terms
    )


def term_occurs(term: GlossaryTerm, source_text: str) -> bool:
    """Return whether one glossary term applies to the complete source text."""

    return _term_occurs(term, source_text)


def load_translations(paths: Iterable[Path]) -> tuple[TranslationRecord, ...]:
    records = []
    seen = set()
    for path in paths:
        document = _load_json_object(path)
        if document.get("schema_version") != 1:
            raise TranslationReviewError(
                f"unsupported translation schema in {path}"
            )
        batch_id = _require_string(
            document.get("batch_id"),
            context=f"{path} batch_id",
        )
        raw_entries = document.get("entries")
        if not isinstance(raw_entries, list):
            raise TranslationReviewError(
                f"translation entries must be an array: {path}"
            )
        for index, raw in enumerate(raw_entries):
            context = f"{path} entry {index}"
            if not isinstance(raw, dict):
                raise TranslationReviewError(f"{context} must be an object")
            if "source_text" in raw:
                raise TranslationReviewError(
                    f"{context} must not duplicate Japanese source text"
                )
            entry_id = _require_string(raw.get("id"), context=f"{context} id")
            if entry_id in seen:
                raise TranslationReviewError(
                    f"duplicate translation id {entry_id!r}"
                )
            seen.add(entry_id)
            source_hash = _require_string(
                raw.get("source_text_sha256"),
                context=f"{context} source_text_sha256",
            )
            if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
                raise TranslationReviewError(
                    f"{context} source_text_sha256 is malformed"
                )
            status = _require_string(
                raw.get("editorial_status"),
                context=f"{context} editorial_status",
            )
            if status not in VALID_EDITORIAL_STATUSES:
                raise TranslationReviewError(
                    f"{context} has invalid editorial status {status!r}"
                )
            translation = raw.get("translation")
            if not isinstance(translation, str):
                raise TranslationReviewError(
                    f"{context} translation must be a string"
                )
            action = raw.get("translation_action", "translate")
            if action not in VALID_TRANSLATION_ACTIONS:
                raise TranslationReviewError(
                    f"{context} has invalid translation_action {action!r}"
                )
            if (
                action == "translate"
                and status != "todo"
                and not translation
            ):
                raise TranslationReviewError(
                    f"{context} status {status!r} requires translation"
                )
            records.append(
                TranslationRecord(
                    entry_id=entry_id,
                    source_text_sha256=source_hash,
                    translation=translation,
                    editorial_status=status,
                    translation_action=str(action),
                    glossary_refs=_require_string_list(
                        raw.get("glossary_refs"),
                        context=f"{context} glossary_refs",
                    ),
                    glossary_exceptions=_require_string_list(
                        raw.get("glossary_exceptions", []),
                        context=f"{context} glossary_exceptions",
                    ),
                    notes=(
                        raw.get("notes")
                        if isinstance(raw.get("notes"), str)
                        else ""
                    ),
                    batch_id=batch_id,
                    source_path=str(path),
                )
            )
    return tuple(records)


def audit_translation_release(
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    glossary: Sequence[GlossaryTerm],
) -> dict:
    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    term_by_id = {term.term_id: term for term in glossary}
    errors = []
    term_usage = Counter()
    term_exceptions = Counter()

    for record in translations:
        source = source_by_id.get(record.entry_id)
        if source is None:
            errors.append(f"{record.entry_id}: no matching source corpus entry")
            continue
        if source.get("source_text_sha256") != record.source_text_sha256:
            errors.append(f"{record.entry_id}: stale source text SHA-256")
        source_text = source.get("source_text")
        domain = source.get("domain")
        if not isinstance(source_text, str) or not isinstance(domain, str):
            errors.append(f"{record.entry_id}: malformed source corpus record")
            continue
        if (
            record.translation_action == "preserve"
            and record.translation != source_text
        ):
            errors.append(
                f"{record.entry_id}: preserve decision differs from source"
            )
        if (
            record.translation_action == "translate"
            and KANA_PATTERN.search(record.translation)
        ):
            errors.append(
                f"{record.entry_id}: translation contains Japanese kana"
            )
        if "..." in record.translation:
            errors.append(
                f"{record.entry_id}: use the Chinese ellipsis character"
            )
        source_tokens = Counter(STRUCTURAL_TOKEN_PATTERN.findall(source_text))
        translated_tokens = Counter(
            STRUCTURAL_TOKEN_PATTERN.findall(record.translation)
        )
        if source_tokens != translated_tokens:
            errors.append(
                f"{record.entry_id}: structural/control token set changed"
            )

        refs = set(record.glossary_refs)
        exceptions = set(record.glossary_exceptions)
        overlap = refs & exceptions
        if overlap:
            errors.append(
                f"{record.entry_id}: glossary refs and exceptions overlap: "
                f"{sorted(overlap)!r}"
            )
        for term_id in record.glossary_refs:
            term = term_by_id.get(term_id)
            if term is None:
                errors.append(
                    f"{record.entry_id}: unknown glossary ref {term_id!r}"
                )
                continue
            term_usage[term_id] += 1
            if domain not in term.domains:
                errors.append(
                    f"{record.entry_id}: glossary ref {term_id!r} "
                    f"does not apply to {domain}"
                )
            if not _term_occurs(term, source_text):
                errors.append(
                    f"{record.entry_id}: glossary ref {term_id!r} "
                    "does not occur in source text"
                )
            if term.translation not in record.translation:
                errors.append(
                    f"{record.entry_id}: canonical translation "
                    f"{term.translation!r} for {term_id!r} is missing"
                )

        for term_id in record.glossary_exceptions:
            term = term_by_id.get(term_id)
            if term is None:
                errors.append(
                    f"{record.entry_id}: unknown glossary exception "
                    f"{term_id!r}"
                )
                continue
            term_exceptions[term_id] += 1
            if domain not in term.domains:
                errors.append(
                    f"{record.entry_id}: glossary exception {term_id!r} "
                    f"does not apply to {domain}"
                )
            if not _term_occurs(term, source_text):
                errors.append(
                    f"{record.entry_id}: glossary exception {term_id!r} "
                    "does not occur in source text"
                )

        for term in glossary:
            if (
                term.enforce
                and domain in term.domains
                and _term_occurs(term, source_text)
                and term.term_id not in refs
                and term.term_id not in exceptions
            ):
                errors.append(
                    f"{record.entry_id}: missing enforced glossary ref "
                    f"{term.term_id!r}"
                )

    if errors:
        detail = "\n".join(f"- {error}" for error in errors)
        raise TranslationReviewError(
            f"translation release has {len(errors)} error(s):\n{detail}"
        )

    source_domains = Counter(str(entry["domain"]) for entry in source_entries)
    translated_domains = Counter(
        str(source_by_id[record.entry_id]["domain"])
        for record in translations
    )
    editorial_statuses = Counter(
        record.editorial_status for record in translations
    )
    glossary_statuses = Counter(term.status for term in glossary)
    glossary_categories = Counter(term.category for term in glossary)
    batches = Counter(record.batch_id for record in translations)
    return {
        "schema_version": 1,
        "source_entry_count": len(source_entries),
        "source_domain_counts": dict(sorted(source_domains.items())),
        "translation_entry_count": len(translations),
        "translation_domain_counts": dict(sorted(translated_domains.items())),
        "editorial_status_counts": dict(sorted(editorial_statuses.items())),
        "batch_counts": dict(sorted(batches.items())),
        "coverage_percent": round(
            100 * len(translations) / len(source_entries),
            6,
        ),
        "glossary_term_count": len(glossary),
        "glossary_status_counts": dict(sorted(glossary_statuses.items())),
        "glossary_category_counts": dict(sorted(glossary_categories.items())),
        "glossary_referenced_term_count": len(term_usage),
        "glossary_reference_count": sum(term_usage.values()),
        "glossary_exception_term_count": len(term_exceptions),
        "glossary_exception_count": sum(term_exceptions.values()),
    }


def audit_coverage_plan(
    plan: object,
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
) -> dict:
    if not isinstance(plan, list) or not plan:
        raise TranslationReviewError(
            "release coverage_plan must be a non-empty array"
        )
    source_domains = Counter(str(entry["domain"]) for entry in source_entries)
    planned_domains = Counter()
    translated_batches = Counter(record.batch_id for record in translations)
    records_by_batch = {}
    for record in translations:
        records_by_batch.setdefault(record.batch_id, []).append(record)
    seen = set()
    errors = []
    status_counts = Counter()

    for index, raw in enumerate(plan):
        context = f"coverage plan item {index}"
        if not isinstance(raw, dict):
            errors.append(f"{context}: must be an object")
            continue
        batch_id = raw.get("batch_id")
        domain = raw.get("domain")
        target = raw.get("target_entry_count")
        status = raw.get("status")
        if not isinstance(batch_id, str) or not batch_id:
            errors.append(f"{context}: batch_id is invalid")
            continue
        if batch_id in seen:
            errors.append(f"{context}: duplicate batch_id {batch_id!r}")
            continue
        seen.add(batch_id)
        if domain not in source_domains:
            errors.append(f"{context}: domain {domain!r} is invalid")
            continue
        if not isinstance(target, int) or target <= 0:
            errors.append(f"{context}: target_entry_count is invalid")
            continue
        if status not in VALID_BATCH_STATUSES:
            errors.append(f"{context}: status {status!r} is invalid")
            continue
        planned_domains[str(domain)] += target
        status_counts[str(status)] += 1
        actual = translated_batches[batch_id]
        if actual > target:
            errors.append(
                f"{batch_id}: {actual} translations exceed target {target}"
            )
        if status == "planned" and actual:
            errors.append(
                f"{batch_id}: planned batch already has {actual} translations"
            )
        if str(status).endswith("_complete") and actual != target:
            errors.append(
                f"{batch_id}: complete batch has {actual}/{target} translations"
            )
        batch_records = records_by_batch.get(batch_id, ())
        if str(status).endswith("_complete") and any(
            record.editorial_status == "todo" for record in batch_records
        ):
            errors.append(
                f"{batch_id}: complete batch still contains todo records"
            )
        minimum_status = {
            "reviewed_complete": "reviewed",
            "final_complete": "final",
        }.get(str(status))
        if minimum_status is not None and any(
            EDITORIAL_STATUS_RANK[record.editorial_status]
            < EDITORIAL_STATUS_RANK[minimum_status]
            for record in batch_records
        ):
            errors.append(
                f"{batch_id}: {status} batch has records below "
                f"{minimum_status}"
            )

    unknown_batches = sorted(set(translated_batches) - seen)
    for batch_id in unknown_batches:
        errors.append(
            f"translation batch {batch_id!r} is absent from coverage plan"
        )
    if planned_domains != source_domains:
        errors.append(
            "coverage plan domain totals do not match source corpus: "
            f"planned={dict(sorted(planned_domains.items()))} "
            f"source={dict(sorted(source_domains.items()))}"
        )
    if errors:
        detail = "\n".join(f"- {error}" for error in errors)
        raise TranslationReviewError(
            f"coverage plan has {len(errors)} error(s):\n{detail}"
        )
    return {
        "coverage_batch_count": len(plan),
        "coverage_batch_status_counts": dict(sorted(status_counts.items())),
        "coverage_target_domain_counts": dict(sorted(planned_domains.items())),
    }


def write_review_tsv(
    path: Path,
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
) -> None:
    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "id",
                "batch_id",
                "domain",
                "kind",
                "scope_index",
                "section",
                "source_text",
                "translation",
                "translation_action",
                "editorial_status",
                "glossary_refs",
                "glossary_exceptions",
                "notes",
            )
        )
        for record in translations:
            source = source_by_id[record.entry_id]
            writer.writerow(
                (
                    record.entry_id,
                    record.batch_id,
                    source["domain"],
                    source["kind"],
                    source["scope_index"],
                    source["section"],
                    source["source_text"],
                    record.translation,
                    record.translation_action,
                    record.editorial_status,
                    ", ".join(record.glossary_refs),
                    ", ".join(record.glossary_exceptions),
                    record.notes,
                )
            )


def write_glossary_tsv(
    path: Path,
    glossary: Sequence[GlossaryTerm],
    translations: Sequence[TranslationRecord],
) -> None:
    usage = Counter(
        term_id
        for record in translations
        for term_id in record.glossary_refs
    )
    exceptions = Counter(
        term_id
        for record in translations
        for term_id in record.glossary_exceptions
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "id",
                "source_terms",
                "translation",
                "category",
                "status",
                "source_match",
                "domains",
                "enforce",
                "reference_count",
                "exception_count",
                "notes",
            )
        )
        for term in glossary:
            writer.writerow(
                (
                    term.term_id,
                    " / ".join(term.source_terms),
                    term.translation,
                    term.category,
                    term.status,
                    term.source_match,
                    ", ".join(term.domains),
                    str(term.enforce).lower(),
                    usage[term.term_id],
                    exceptions[term.term_id],
                    term.notes,
                )
            )


def write_terminology_variant_tsv(
    path: Path,
    review: Mapping[str, object],
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    glossary: Sequence[GlossaryTerm],
) -> dict:
    if review.get("schema_version") != 1:
        raise TranslationReviewError(
            "unsupported terminology variant review schema"
        )
    review_id = _require_string(
        review.get("review_id"),
        context="terminology variant review id",
    )
    if review.get("language") != "zh-Hans":
        raise TranslationReviewError(
            "terminology variant review language must be zh-Hans"
        )
    scope = review.get("scope")
    if not isinstance(scope, dict):
        raise TranslationReviewError(
            "terminology variant review scope must be an object"
        )
    raw_stages = scope.get("stage_indices")
    if (
        not isinstance(raw_stages, list)
        or not raw_stages
        or not all(isinstance(stage, int) and stage >= 0 for stage in raw_stages)
        or len(set(raw_stages)) != len(raw_stages)
    ):
        raise TranslationReviewError(
            "terminology variant review stage_indices must be unique "
            "non-negative integers"
        )
    stage_indices = tuple(sorted(raw_stages))
    stage_set = set(stage_indices)
    raw_kinds = scope.get("kinds")
    if (
        not isinstance(raw_kinds, list)
        or not raw_kinds
        or not all(
            isinstance(kind, str) and kind in {"dialogue", "speaker"}
            for kind in raw_kinds
        )
        or len(set(raw_kinds)) != len(raw_kinds)
    ):
        raise TranslationReviewError(
            "terminology variant review kinds must contain unique "
            "dialogue or speaker values"
        )
    kind_set = set(raw_kinds)
    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    term_by_id = {term.term_id: term for term in glossary}
    usage: dict[str, list[tuple[TranslationRecord, Mapping[str, object]]]] = {}
    for record in translations:
        source = source_by_id.get(record.entry_id)
        if (
            source is None
            or source.get("domain") != "story"
            or source.get("kind") not in kind_set
            or source.get("scope_index") not in stage_set
        ):
            continue
        for term_id in record.glossary_refs:
            usage.setdefault(term_id, []).append((record, source))

    raw_decisions = review.get("decisions")
    if not isinstance(raw_decisions, list) or not raw_decisions:
        raise TranslationReviewError(
            "terminology variant review decisions must be a non-empty array"
        )
    seen_decision_ids = set()
    output_rows = []
    status_counts = Counter()
    for index, raw in enumerate(raw_decisions):
        context = f"terminology variant review decision {index}"
        if not isinstance(raw, dict):
            raise TranslationReviewError(f"{context} must be an object")
        decision_id = _require_string(
            raw.get("id"),
            context=f"{context} id",
        )
        if decision_id in seen_decision_ids:
            raise TranslationReviewError(
                f"duplicate terminology variant decision id {decision_id!r}"
            )
        seen_decision_ids.add(decision_id)
        term_ids = _require_string_list(
            raw.get("term_ids"),
            context=f"{context} term_ids",
        )
        unknown_term_ids = sorted(set(term_ids) - set(term_by_id))
        if unknown_term_ids:
            raise TranslationReviewError(
                f"{context} has unknown term ids {unknown_term_ids!r}"
            )
        current_translation = _require_string(
            raw.get("current_translation"),
            context=f"{context} current_translation",
        )
        mismatched_terms = sorted(
            term_id
            for term_id in term_ids
            if term_by_id[term_id].translation != current_translation
        )
        if mismatched_terms:
            raise TranslationReviewError(
                f"{context} current_translation does not match glossary "
                f"terms {mismatched_terms!r}"
            )
        official_variant = _require_string(
            raw.get("official_variant"),
            context=f"{context} official_variant",
        )
        if official_variant == current_translation:
            raise TranslationReviewError(
                f"{context} official_variant must differ from current_translation"
            )
        decision_status = _require_string(
            raw.get("decision_status"),
            context=f"{context} decision_status",
        )
        if decision_status not in VALID_TERMINOLOGY_DECISION_STATUSES:
            raise TranslationReviewError(
                f"{context} has invalid decision_status "
                f"{decision_status!r}"
            )
        evidence_url = _require_string(
            raw.get("evidence_url"),
            context=f"{context} evidence_url",
        )
        if not evidence_url.startswith("https://"):
            raise TranslationReviewError(
                f"{context} evidence_url must use https"
            )
        current_rationale = _require_string(
            raw.get("current_rationale"),
            context=f"{context} current_rationale",
        )
        review_question = _require_string(
            raw.get("review_question"),
            context=f"{context} review_question",
        )
        decision_usage = [
            pair
            for term_id in term_ids
            for pair in usage.get(term_id, ())
        ]
        if not decision_usage:
            raise TranslationReviewError(
                f"{context} is not referenced by the selected dialogue stages"
            )
        used_stages = sorted(
            {int(source["scope_index"]) for _, source in decision_usage}
        )
        example_entry_ids = []
        for record, _ in decision_usage:
            if record.entry_id not in example_entry_ids:
                example_entry_ids.append(record.entry_id)
            if len(example_entry_ids) == 5:
                break
        output_rows.append(
            (
                decision_id,
                ", ".join(term_ids),
                " / ".join(
                    dict.fromkeys(
                        source_term
                        for term_id in term_ids
                        for source_term in term_by_id[term_id].source_terms
                    )
                ),
                current_translation,
                official_variant,
                decision_status,
                len(decision_usage),
                ", ".join(f"{stage:03d}" for stage in used_stages),
                ", ".join(example_entry_ids),
                evidence_url,
                current_rationale,
                review_question,
            )
        )
        status_counts[decision_status] += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "id",
                "term_ids",
                "source_terms",
                "current_translation",
                "official_variant",
                "decision_status",
                "reference_count",
                "stages_used",
                "example_entry_ids",
                "evidence_url",
                "current_rationale",
                "review_question",
            )
        )
        writer.writerows(output_rows)

    return {
        "review_id": review_id,
        "stage_indices": list(stage_indices),
        "kinds": sorted(kind_set),
        "decision_count": len(output_rows),
        "status_counts": dict(sorted(status_counts.items())),
    }


def _dialogue_milestone_records(
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    *,
    stage_indices: Sequence[int],
) -> tuple[
    dict[str, Mapping[str, object]],
    tuple[tuple[TranslationRecord, Mapping[str, object]], ...],
]:
    stages = set(stage_indices)
    if not stages or any(
        not isinstance(stage, int) or stage < 0 for stage in stages
    ):
        raise TranslationReviewError(
            "dialogue milestone needs non-negative stage indices"
        )
    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    selected = []
    for record in translations:
        if record.batch_id != "v1-story-dialogue":
            continue
        source = source_by_id.get(record.entry_id)
        if source is None:
            raise TranslationReviewError(
                f"translation has no source entry: {record.entry_id}"
            )
        if (
            source.get("domain") == "story"
            and source.get("kind") == "dialogue"
            and source.get("scope_index") in stages
        ):
            selected.append((record, source))
    if not selected:
        raise TranslationReviewError(
            "dialogue milestone has no translated records"
        )
    return source_by_id, tuple(selected)


def write_dialogue_milestone_term_tsv(
    path: Path,
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    glossary: Sequence[GlossaryTerm],
    *,
    term_origins: Mapping[str, tuple[int, str]],
    stage_indices: Sequence[int],
) -> dict[str, object]:
    """Write a focused term queue for one translated dialogue milestone."""

    _, selected_records = _dialogue_milestone_records(
        source_entries,
        translations,
        stage_indices=stage_indices,
    )
    stages = set(stage_indices)
    term_by_id = {term.term_id: term for term in glossary}
    unknown_origins = sorted(set(term_origins) - set(term_by_id))
    if unknown_origins:
        raise TranslationReviewError(
            f"dialogue term origins contain unknown ids: {unknown_origins!r}"
        )
    selected_terms = [
        term_by_id[term_id]
        for term_id, (origin_stage, _) in term_origins.items()
        if origin_stage in stages
    ]
    if not selected_terms:
        raise TranslationReviewError(
            "dialogue milestone has no stage-specific glossary terms"
        )

    references: dict[
        str,
        list[tuple[TranslationRecord, Mapping[str, object]]],
    ] = {}
    exceptions: dict[
        str,
        list[tuple[TranslationRecord, Mapping[str, object]]],
    ] = {}
    for record, source in selected_records:
        for term_id in record.glossary_refs:
            references.setdefault(term_id, []).append((record, source))
        for term_id in record.glossary_exceptions:
            exceptions.setdefault(term_id, []).append((record, source))

    terms_by_source: dict[str, list[GlossaryTerm]] = {}
    for term in glossary:
        for source_term in term.source_terms:
            terms_by_source.setdefault(source_term, []).append(term)

    rows = []
    for term in selected_terms:
        ref_rows = references.get(term.term_id, [])
        exception_rows = exceptions.get(term.term_id, [])
        usage_rows = ref_rows + exception_rows
        if not usage_rows:
            raise TranslationReviewError(
                f"stage glossary term is unused in milestone: {term.term_id}"
            )
        related = {}
        conflict_details = []
        for source_term in term.source_terms:
            for other in terms_by_source[source_term]:
                if other.term_id == term.term_id:
                    continue
                related[other.term_id] = other
                if other.translation != term.translation:
                    conflict_details.append(
                        f"{source_term}:"
                        f"{other.term_id}={other.translation}"
                    )
        used_stages = sorted(
            {
                int(source["scope_index"])
                for _, source in usage_rows
            }
        )
        example_ids = []
        for record, _ in usage_rows:
            if record.entry_id not in example_ids:
                example_ids.append(record.entry_id)
        if term.status == "proposed" or conflict_details:
            priority = "high"
        elif exception_rows:
            priority = "medium"
        else:
            priority = "normal"
        origin_stage, origin_path = term_origins[term.term_id]
        rows.append(
            (
                priority,
                origin_stage,
                origin_path,
                term,
                len(ref_rows),
                len(exception_rows),
                used_stages,
                example_ids[:5],
                related,
                sorted(set(conflict_details)),
            )
        )

    priority_rank = {"high": 0, "medium": 1, "normal": 2}
    rows.sort(
        key=lambda row: (
            priority_rank[row[0]],
            row[1],
            row[3].term_id,
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "review_priority",
                "origin_stage",
                "origin_glossary",
                "id",
                "source_terms",
                "translation",
                "category",
                "status",
                "source_match",
                "enforce",
                "reference_count",
                "exception_count",
                "stages_used",
                "example_entry_ids",
                "same_source_terms",
                "translation_conflicts",
                "notes",
            )
        )
        for (
            priority,
            origin_stage,
            origin_path,
            term,
            reference_count,
            exception_count,
            used_stages,
            example_ids,
            related,
            conflict_details,
        ) in rows:
            writer.writerow(
                (
                    priority,
                    f"{origin_stage:03d}",
                    origin_path,
                    term.term_id,
                    " / ".join(term.source_terms),
                    term.translation,
                    term.category,
                    term.status,
                    term.source_match,
                    str(term.enforce).lower(),
                    reference_count,
                    exception_count,
                    ", ".join(f"{stage:03d}" for stage in used_stages),
                    ", ".join(example_ids),
                    ", ".join(
                        f"{term_id}={other.translation}"
                        for term_id, other in sorted(related.items())
                    ),
                    " / ".join(conflict_details),
                    term.notes,
                )
            )

    priority_counts = Counter(row[0] for row in rows)
    return {
        "stage_indices": sorted(stages),
        "term_count": len(rows),
        "proposed_term_count": sum(
            term.status == "proposed" for term in selected_terms
        ),
        "researched_term_count": sum(
            term.status == "researched" for term in selected_terms
        ),
        "translation_conflict_term_count": sum(
            bool(row[-1]) for row in rows
        ),
        "priority_counts": dict(sorted(priority_counts.items())),
    }


def write_dialogue_milestone_exception_tsv(
    path: Path,
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    *,
    stage_indices: Sequence[int],
) -> dict[str, object]:
    """Write every explicit glossary exception with speaker and context."""

    _, selected_records = _dialogue_milestone_records(
        source_entries,
        translations,
        stage_indices=stage_indices,
    )
    translation_by_id = {
        record.entry_id: record for record in translations
    }
    rows = []
    for record, source in selected_records:
        if not record.glossary_exceptions:
            continue
        if not record.notes:
            raise TranslationReviewError(
                f"glossary exception needs review notes: {record.entry_id}"
            )
        stage_index = int(source["scope_index"])
        provenance = source.get("provenance")
        speaker_id = (
            provenance.get("speaker_id")
            if isinstance(provenance, Mapping)
            else None
        )
        speaker_zh = ""
        if isinstance(speaker_id, int) and speaker_id >= 0:
            speaker = translation_by_id.get(
                f"story/{stage_index:03d}/speaker/{speaker_id:03d}"
            )
            if speaker is not None:
                speaker_zh = speaker.translation
        rows.append(
            (
                stage_index,
                record,
                source,
                speaker_zh,
            )
        )

    rows.sort(key=lambda row: row[1].entry_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "stage",
                "id",
                "section",
                "speaker_zh",
                "source_text",
                "translation",
                "glossary_exceptions",
                "notes",
            )
        )
        for stage_index, record, source, speaker_zh in rows:
            writer.writerow(
                (
                    f"{stage_index:03d}",
                    record.entry_id,
                    source["section"],
                    speaker_zh,
                    source["source_text"],
                    record.translation,
                    ", ".join(record.glossary_exceptions),
                    record.notes,
                )
            )
    exception_counts = Counter(
        term_id
        for _, record, _, _ in rows
        for term_id in record.glossary_exceptions
    )
    return {
        "stage_indices": sorted(set(stage_indices)),
        "record_count": len(rows),
        "exception_counts": dict(sorted(exception_counts.items())),
    }


def write_unique_review_tsv(
    path: Path,
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    *,
    batch_id: str,
) -> None:
    """Write one row per unique source/decision pair for a translation batch."""

    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    groups: dict[tuple[object, ...], list[str]] = {}
    for record in translations:
        if record.batch_id != batch_id:
            continue
        source = source_by_id[record.entry_id]
        key = (
            source["domain"],
            source["kind"],
            source["source_text"],
            source["source_text_sha256"],
            record.translation,
            record.translation_action,
            record.editorial_status,
            record.glossary_refs,
            record.glossary_exceptions,
            record.notes,
        )
        groups.setdefault(key, []).append(record.entry_id)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "batch_id",
                "domain",
                "kind",
                "source_text",
                "translation",
                "translation_action",
                "editorial_status",
                "occurrence_count",
                "first_id",
                "last_id",
                "source_text_sha256",
                "glossary_refs",
                "glossary_exceptions",
                "notes",
            )
        )
        for key, entry_ids in groups.items():
            (
                domain,
                kind,
                source_text,
                source_hash,
                translation,
                action,
                status,
                refs,
                exceptions,
                notes,
            ) = key
            writer.writerow(
                (
                    batch_id,
                    domain,
                    kind,
                    source_text,
                    translation,
                    action,
                    status,
                    len(entry_ids),
                    entry_ids[0],
                    entry_ids[-1],
                    source_hash,
                    ", ".join(refs),
                    ", ".join(exceptions),
                    notes,
                )
            )


def write_stage_dialogue_source_tsv(
    path: Path,
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    *,
    stage_index: int,
) -> dict:
    """Write one complete story stage with its translated speaker context."""

    if stage_index < 0:
        raise TranslationReviewError("stage_index must be non-negative")
    translation_by_id = {
        record.entry_id: record for record in translations
    }
    rows = [
        entry
        for entry in source_entries
        if entry.get("domain") == "story"
        and entry.get("kind") == "dialogue"
        and entry.get("scope_index") == stage_index
    ]
    if not rows:
        raise TranslationReviewError(
            f"source corpus has no story dialogue for stage {stage_index:03d}"
        )

    unique_source_hashes = set()
    unique_index_by_hash = {}
    translated_entry_count = 0
    missing_speakers = []
    output_rows = []
    for source in rows:
        entry_id = str(source["id"])
        source_hash = str(source["source_text_sha256"])
        unique_source_hashes.add(source_hash)
        unique_index = unique_index_by_hash.setdefault(
            source_hash,
            len(unique_index_by_hash),
        )
        provenance = source.get("provenance")
        speaker_id = (
            provenance.get("speaker_id")
            if isinstance(provenance, Mapping)
            else None
        )
        if not isinstance(speaker_id, int) or speaker_id < 0:
            raise TranslationReviewError(
                f"{entry_id}: dialogue speaker_id is malformed"
            )
        speaker_entry_id = (
            f"story/{stage_index:03d}/speaker/{speaker_id:03d}"
        )
        speaker = translation_by_id.get(speaker_entry_id)
        if speaker is None:
            missing_speakers.append(speaker_entry_id)
            speaker_zh = ""
        else:
            speaker_zh = speaker.translation

        translation = translation_by_id.get(entry_id)
        if translation is not None:
            translated_entry_count += 1
        output_rows.append(
            (
                entry_id,
                unique_index,
                source["section"],
                speaker_id,
                speaker_zh,
                source["source_text"],
                source_hash,
                translation.translation if translation else "",
                translation.translation_action if translation else "",
                translation.editorial_status if translation else "",
                ", ".join(translation.glossary_refs) if translation else "",
                (
                    ", ".join(translation.glossary_exceptions)
                    if translation
                    else ""
                ),
                translation.notes if translation else "",
            )
        )

    if missing_speakers:
        missing = ", ".join(sorted(set(missing_speakers)))
        raise TranslationReviewError(
            f"stage {stage_index:03d} has untranslated speaker slots: {missing}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            (
                "id",
                "unique_index",
                "section",
                "speaker_id",
                "speaker_zh",
                "source_text",
                "source_text_sha256",
                "translation",
                "translation_action",
                "editorial_status",
                "glossary_refs",
                "glossary_exceptions",
                "notes",
            )
        )
        writer.writerows(output_rows)

    return {
        "stage_index": stage_index,
        "entry_count": len(rows),
        "unique_source_text_count": len(unique_source_hashes),
        "translated_entry_count": translated_entry_count,
    }


def write_stage_dialogue_unique_draft(
    path: Path,
    source_entries: Sequence[Mapping[str, object]],
    translations: Sequence[TranslationRecord],
    *,
    stage_index: int,
) -> dict:
    """Reconstruct one ignored unique-decision draft from committed records."""

    if stage_index < 0:
        raise TranslationReviewError("stage_index must be non-negative")
    translation_by_id = {
        record.entry_id: record for record in translations
    }
    stage_sources = [
        entry
        for entry in source_entries
        if entry.get("domain") == "story"
        and entry.get("kind") == "dialogue"
        and entry.get("scope_index") == stage_index
    ]
    if not stage_sources:
        raise TranslationReviewError(
            f"source corpus has no story dialogue for stage {stage_index:03d}"
        )

    grouped: dict[str, list[tuple[Mapping[str, object], TranslationRecord]]] = {}
    for source in stage_sources:
        entry_id = str(source["id"])
        record = translation_by_id.get(entry_id)
        if record is None:
            raise TranslationReviewError(
                f"{entry_id}: no committed dialogue translation"
            )
        source_hash = str(source["source_text_sha256"])
        grouped.setdefault(source_hash, []).append((source, record))

    document: dict[str, object] = {
        "stage_index": stage_index,
        "ordering": (
            "first occurrence of each source_text_sha256 in the fixed "
            "source corpus"
        ),
        "translations": [],
    }
    notes_by_index = {}
    refs_by_index = {}
    exceptions_by_index = {}
    statuses_by_index = {}
    for index, pairs in enumerate(grouped.values()):
        _, first = pairs[0]
        decision = (
            first.translation,
            first.translation_action,
            first.editorial_status,
            first.glossary_refs,
            first.glossary_exceptions,
            first.notes,
        )
        for source, record in pairs[1:]:
            candidate = (
                record.translation,
                record.translation_action,
                record.editorial_status,
                record.glossary_refs,
                record.glossary_exceptions,
                record.notes,
            )
            if candidate != decision:
                raise TranslationReviewError(
                    f"{source['id']}: repeated source text has divergent "
                    "committed decisions"
                )
        if first.translation_action != "translate":
            raise TranslationReviewError(
                f"{pairs[0][0]['id']}: story dialogue draft only supports "
                "translate actions"
            )
        document["translations"].append(first.translation)
        if first.notes:
            notes_by_index[str(index)] = first.notes
        if first.glossary_refs:
            refs_by_index[str(index)] = list(first.glossary_refs)
        if first.glossary_exceptions:
            exceptions_by_index[str(index)] = list(
                first.glossary_exceptions
            )
        if first.editorial_status != "draft":
            statuses_by_index[str(index)] = first.editorial_status
    if notes_by_index:
        document["notes_by_index"] = notes_by_index
    if refs_by_index:
        document["glossary_refs_by_index"] = refs_by_index
    if exceptions_by_index:
        document["glossary_exceptions_by_index"] = exceptions_by_index
    if statuses_by_index:
        document["editorial_status_by_index"] = statuses_by_index

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "stage_index": stage_index,
        "entry_count": len(stage_sources),
        "unique_source_text_count": len(grouped),
        "reviewed_unique_count": sum(
            status == "reviewed" for status in statuses_by_index.values()
        ),
    }


__all__ = [
    "GlossaryTerm",
    "TranslationRecord",
    "TranslationReviewError",
    "audit_coverage_plan",
    "audit_translation_release",
    "load_glossary",
    "load_source_corpus",
    "load_translations",
    "source_corpus_sha256",
    "term_occurs",
    "write_glossary_tsv",
    "write_terminology_variant_tsv",
    "write_dialogue_milestone_exception_tsv",
    "write_dialogue_milestone_term_tsv",
    "write_review_tsv",
    "write_stage_dialogue_source_tsv",
    "write_stage_dialogue_unique_draft",
    "write_unique_review_tsv",
]
