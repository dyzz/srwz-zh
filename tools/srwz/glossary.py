"""Global terminology registry and consistency helpers.

Every file below ``corpus/glossary`` is a maintenance component of one
logical registry.  Consumers must load the complete directory through this
module so that duplicate IDs, conflicting translations, stale variants, and
effective enforcement rules have one implementation.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path


class GlossaryError(ValueError):
    """The global terminology registry is malformed or contradictory."""


STATUS_PRIORITY = {
    "": 0,
    "proposed": 1,
    "researched": 2,
    "approved": 3,
}


def _string_list(value: object, *, label: str, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise GlossaryError(f"{label} must be an array of non-empty strings")
    if required and not value:
        raise GlossaryError(f"{label} must not be empty")
    return list(value)


def load_global_glossary(glossary_dir: Path) -> list[dict[str, object]]:
    """Load and merge every glossary component into one fail-closed registry."""

    directory = Path(glossary_dir)
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise GlossaryError(f"no glossary components found: {directory}")

    terms: dict[str, dict[str, object]] = {}
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GlossaryError(f"cannot read glossary component: {path}") from exc
        if not isinstance(document, dict) or not isinstance(document.get("terms"), list):
            raise GlossaryError(f"glossary terms must be an array: {path}")

        for index, raw in enumerate(document["terms"]):
            label = f"{path}:{index}"
            if not isinstance(raw, Mapping):
                raise GlossaryError(f"glossary term must be an object: {label}")
            term_id = raw.get("id")
            translation = raw.get("translation")
            if not isinstance(term_id, str) or not term_id:
                raise GlossaryError(f"glossary term ID is missing: {label}")
            if not isinstance(translation, str) or not translation:
                raise GlossaryError(f"glossary translation is missing: {label}")

            source_terms = _string_list(
                raw.get("source_terms"), label=f"{label} source_terms", required=True
            )
            deprecated = _string_list(
                raw.get("deprecated_translations"),
                label=f"{label} deprecated_translations",
            )
            domains = _string_list(raw.get("domains"), label=f"{label} domains")
            status = str(raw.get("status", ""))
            if status not in STATUS_PRIORITY:
                raise GlossaryError(f"unsupported glossary status {status!r}: {label}")

            candidate: dict[str, object] = {
                "id": term_id,
                "source_terms": source_terms,
                "translation": translation,
                "deprecated_translations": deprecated,
                "domains": domains,
                "status": status,
                "declared_enforce": bool(raw.get("enforce", False)),
                "variant_scope": str(raw.get("variant_scope", "source_bound")),
                "source_files": [path.name],
            }
            if candidate["variant_scope"] not in {"source_bound", "global"}:
                raise GlossaryError(
                    f"unsupported variant_scope {candidate['variant_scope']!r}: {label}"
                )
            category = raw.get("category")
            if isinstance(category, str) and category:
                candidate["category"] = category

            prior = terms.get(term_id)
            if prior is None:
                terms[term_id] = candidate
                continue
            if prior["translation"] != translation:
                raise GlossaryError(
                    f"conflicting glossary translation for {term_id}: "
                    f"{prior['translation']!r} != {translation!r}"
                )
            prior_category = prior.get("category")
            candidate_category = candidate.get("category")
            if (
                prior_category
                and candidate_category
                and prior_category != candidate_category
            ):
                raise GlossaryError(
                    f"conflicting glossary category for {term_id}: "
                    f"{prior_category!r} != {candidate_category!r}"
                )
            if not prior_category and candidate_category:
                prior["category"] = candidate_category

            for key in (
                "source_terms",
                "deprecated_translations",
                "domains",
                "source_files",
            ):
                prior[key] = sorted(
                    set(str(item) for item in prior[key])
                    | set(str(item) for item in candidate[key])
                )
            prior["declared_enforce"] = bool(
                prior["declared_enforce"] or candidate["declared_enforce"]
            )
            if candidate["variant_scope"] == "global":
                prior["variant_scope"] = "global"
            if STATUS_PRIORITY[status] > STATUS_PRIORITY[str(prior["status"])]:
                prior["status"] = status

    result = [terms[term_id] for term_id in sorted(terms)]
    for term in result:
        canonical = str(term["translation"])
        term["deprecated_translations"] = [
            value
            for value in term["deprecated_translations"]
            if value != canonical
        ]
        # A hint becomes a hard corpus contract only after explicit approval.
        term["enforce"] = bool(
            term["declared_enforce"] and term["status"] == "approved"
        )
    return result


def global_glossary_by_id(
    terms: Iterable[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for term in terms:
        term_id = term.get("id")
        if not isinstance(term_id, str) or not term_id:
            raise GlossaryError("loaded glossary term is missing its ID")
        if term_id in result:
            raise GlossaryError(f"duplicate loaded glossary ID: {term_id}")
        result[term_id] = term
    return result


def _kana_script(character: str) -> str | None:
    if "\u3041" <= character <= "\u3096":
        return "hiragana"
    if (
        "\u30a1" <= character <= "\u30fa"
        or "\u30fc" <= character <= "\u30ff"
        or "\u31f0" <= character <= "\u31ff"
    ):
        return "katakana"
    return None


def _bounded_contains(text: str, source: str) -> bool:
    cursor = 0
    while True:
        index = text.find(source, cursor)
        if index < 0:
            return False
        end = index + len(source)
        left_script = _kana_script(source[0]) if source else None
        right_script = _kana_script(source[-1]) if source else None
        left_ok = not (
            left_script is not None
            and index > 0
            and _kana_script(text[index - 1]) == left_script
        )
        right_ok = not (
            right_script is not None
            and end < len(text)
            and _kana_script(text[end]) == right_script
        )
        if left_ok and right_ok:
            return True
        cursor = index + 1


def relevant_glossary_terms(
    text: str,
    terms: Sequence[Mapping[str, object]],
    *,
    context_sensitive_hard_prefixes: Sequence[str] = (),
) -> list[dict[str, object]]:
    """Return the global terms whose Japanese source forms occur in ``text``."""

    matches: list[dict[str, object]] = []
    prefixes = tuple(context_sensitive_hard_prefixes)
    for term in terms:
        sources = term.get("source_terms")
        if not isinstance(sources, list):
            raise GlossaryError(f"term {term.get('id')} has no source_terms")
        matched = [str(source) for source in sources if _bounded_contains(text, str(source))]
        if not matched:
            continue
        term_id = str(term["id"])
        exact_field_match = any(
            text.strip("\u3000 ") == source.strip("\u3000 ") for source in matched
        )
        enforce = bool(term.get("enforce", False))
        if term_id.startswith(prefixes):
            enforce = enforce and exact_field_match
        matches.append(
            {
                "id": term_id,
                "matched_source_terms": matched,
                "translation": term["translation"],
                "deprecated_translations": list(
                    term.get("deprecated_translations", [])
                ),
                "variant_scope": str(term.get("variant_scope", "source_bound")),
                "enforce": enforce,
                "declared_enforce": bool(term.get("declared_enforce", False)),
                "status": str(term.get("status", "")),
            }
        )
    return matches


def apply_glossary_variants(
    text: str,
    terms: Iterable[Mapping[str, object]],
) -> tuple[str, list[str]]:
    """Replace deprecated Chinese forms for the terms bound to one source row."""

    replacements: dict[str, tuple[str, str]] = {}
    for term in terms:
        term_id = str(term["id"])
        canonical = str(term["translation"])
        for variant in term.get("deprecated_translations", []):
            variant = str(variant)
            prior = replacements.get(variant)
            if prior is not None and prior[0] != canonical:
                raise GlossaryError(
                    f"deprecated form {variant!r} is ambiguous in this source: "
                    f"{prior[1]} -> {prior[0]!r}, {term_id} -> {canonical!r}"
                )
            replacements[variant] = (canonical, term_id)

    candidate = text
    applied: list[str] = []
    for variant in sorted(replacements, key=lambda value: (-len(value), value)):
        canonical, term_id = replacements[variant]
        if variant not in candidate:
            continue
        candidate = candidate.replace(variant, canonical)
        applied.append(f"{variant}→{canonical}[{term_id}]")
    return candidate, applied


def deprecated_translation_conflicts(
    text: str,
    terms: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    for term in terms:
        matched = [
            str(variant)
            for variant in term.get("deprecated_translations", [])
            if str(variant) in text
        ]
        if matched:
            conflicts.append(
                {
                    "code": "term_conflict",
                    "id": term["id"],
                    "matched": matched,
                    "canonical": term["translation"],
                }
            )
    return conflicts
