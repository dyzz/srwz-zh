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
    from srwz.display_names import (
        load_display_name_source,
        load_full_unit_name_corpus,
    )
    from srwz.glossary import (
        apply_glossary_variants,
        deprecated_translation_conflicts,
        global_glossary_by_id,
        load_global_glossary,
        relevant_glossary_terms,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.srwz.display_names import (
        load_display_name_source,
        load_full_unit_name_corpus,
    )
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
DISPLAY_NAME_CONFIG = ROOT / "config/display-names/compdata.json"
UNIT_NAME_CORPUS = ROOT / "corpus/zh/display-names/units-full.json"
STORY_SPEAKERS = ROOT / "corpus/zh/story-speakers.json"
REMAINING_UI = ROOT / "corpus/zh/menu/remaining-ui.json"
AUTO_DEMO_TITLES = ROOT / "corpus/zh/auto-demo-work-titles.json"
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


def apply_source_bound_review_replacements(
    text: str,
    config: dict[str, Any],
    relevant_term_ids: set[str],
) -> tuple[str, list[str]]:
    """Apply reviewed machine-variant fixes only when Japanese binds the term."""

    candidate = text
    applied: list[str] = []
    replacements: list[tuple[str, str, str]] = []
    for rule in config.get("source_bound_replacements", []):
        term_id = rule.get("glossary_id")
        target = rule.get("to")
        variants = rule.get("from", [])
        if (
            term_id not in relevant_term_ids
            or not isinstance(target, str)
            or not target
            or not isinstance(variants, list)
        ):
            continue
        replacements.extend(
            (str(variant), target, str(term_id))
            for variant in variants
            if isinstance(variant, str) and variant
        )
    for variant, target, term_id in sorted(
        set(replacements),
        key=lambda item: (-len(item[0]), item[0], item[2]),
    ):
        parts = candidate.split(target) if variant in target else [candidate]
        replaced = target.join(part.replace(variant, target) for part in parts)
        if replaced == candidate:
            continue
        candidate = replaced
        applied.append(f"{variant}→{target}[{term_id}:library-review]")
    return candidate, applied


def apply_source_surface_replacements(
    text: str,
    source_text: str,
    config: dict[str, Any],
) -> tuple[str, list[str]]:
    """Apply reviewed variants only when a Japanese source surface is present.

    These contracts cover names whose authoritative display-name corpus is
    stronger than the machine draft, but which are not yet approved global
    glossary entries (for example Megadeus and Baldios).  Source binding keeps
    a spelling such as ``奥加斯`` from touching unrelated words such as
    ``奥加斯塔研究所``.
    """

    compact_source = compact_source_surface(source_text)
    candidate = text
    applied: list[str] = []
    replacements: list[tuple[str, str, str]] = []
    for rule in config.get("source_surface_replacements", []):
        source_terms = rule.get("source_terms", [])
        variants = rule.get("from", [])
        target = rule.get("to")
        rule_id = rule.get("id")
        if (
            not isinstance(source_terms, list)
            or not isinstance(variants, list)
            or not isinstance(target, str)
            or not target
            or not isinstance(rule_id, str)
            or not rule_id
        ):
            raise ValueError("invalid LIBRARY source-surface replacement")
        if not any(
            isinstance(term, str)
            and term
            and compact_source_surface(term) in compact_source
            for term in source_terms
        ):
            continue
        replacements.extend(
            (str(variant), target, rule_id)
            for variant in variants
            if isinstance(variant, str) and variant
        )
    for variant, target, rule_id in sorted(
        set(replacements),
        key=lambda item: (-len(item[0]), item[0], item[2]),
    ):
        parts = candidate.split(target) if variant in target else [candidate]
        replaced = target.join(part.replace(variant, target) for part in parts)
        if replaced == candidate:
            continue
        candidate = replaced
        applied.append(f"{variant}→{target}[{rule_id}:source-surface]")
    return candidate, applied


BODY_TAGS = {"DSC2", "DSCR", "CHFN", "CHNN"}
JAPANESE_KANA_RE = re.compile(r"[ぁ-ゖァ-ヺー]")


def library_row_kind(tags: Iterable[str]) -> str:
    return "body" if any(tag in BODY_TAGS for tag in tags) else "name_or_metadata"


def normalized_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def compact_source_surface(text: str) -> str:
    """Normalize source display surfaces without changing semantic letters."""

    return re.sub(r"[\s・\-−－]", "", normalized_text(text)).lower()


def load_library_authoritative_surfaces(
    source_rows: list[dict[str, Any]],
    draft_by_id: dict[str, dict[str, Any]],
    reviewed_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """Bind LIBRARY names to the same reviewed surfaces used by the game UI.

    The encyclopedia repeats unit names, pilot names, and work titles already
    localized elsewhere.  Reusing those decisions is both stronger and safer
    than accepting an independent machine transliteration in ZKAN.
    """

    _config, _decoded, parsed, _context = load_display_name_source(
        ROOT,
        DISPLAY_NAME_CONFIG,
    )
    unit_decisions, _unit_report = load_full_unit_name_corpus(
        ROOT,
        UNIT_NAME_CORPUS,
        parsed.unit_entries,
    )
    unit_by_source = {
        normalized_text(entry.text): unit_decisions[entry.entry_id]["translation"].replace(
            "・", "·"
        ).replace("Ⅱ", "II")
        for entry in parsed.unit_entries
    }

    speaker_by_hash: dict[str, str] = {}
    for entry in load_json(STORY_SPEAKERS).get("entries", []):
        source_hash = entry.get("source_text_sha256")
        translation = entry.get("translation")
        if not isinstance(source_hash, str) or not isinstance(translation, str) or not translation:
            continue
        previous = speaker_by_hash.setdefault(source_hash, translation)
        if previous != translation:
            raise ValueError(f"conflicting story speaker surface: {source_hash}")

    remaining_by_source = load_json(REMAINING_UI).get(
        "display_names_by_source_text", {}
    )
    if not isinstance(remaining_by_source, dict):
        raise ValueError("remaining display-name surface map is malformed")

    work_by_source = {
        compact_source_surface(entry["source_text"]): entry["translation"]
        for entry in load_json(AUTO_DEMO_TITLES).get("entries", [])
    }
    # The ZKAN spellings differ slightly from the executable title cards.
    work_by_source.update(
        {
            compact_source_surface("OVERMANキングゲイナー"): "返乡战士",
            compact_source_surface("THE ビッグオー"): "The Big O",
            compact_source_surface("THE ビッグオー Second Season"): "The Big O 第二季",
        }
    )

    exact_by_id: dict[str, dict[str, str]] = {}
    propagation_rules: list[dict[str, str]] = []
    for source in source_rows:
        row_id = str(source["id"])
        references = source.get("references", [])
        tags = {str(reference.get("tag", "")) for reference in references}
        source_text = str(source["source_text"])
        source_hash = str(source["source_text_sha256"])
        canonical = ""
        authority = ""
        normalized_source = normalized_text(source_text)
        if "RBTN" in tags and normalized_source in unit_by_source:
            canonical = unit_by_source[normalized_source]
            authority = "reviewed unit display-name corpus"
        elif tags & {"CHFN", "CHNN", "PLTN"} and source_hash in speaker_by_hash:
            canonical = speaker_by_hash[source_hash]
            authority = "reviewed story speaker corpus"
        elif tags & {"CHFN", "CHNN", "PLTN"} and source_text in remaining_by_source:
            value = remaining_by_source[source_text]
            if isinstance(value, str) and value:
                canonical = value
                authority = "reviewed residual display-name corpus"
        elif "PRDC" in tags:
            value = work_by_source.get(compact_source_surface(source_text))
            if isinstance(value, str) and value:
                canonical = value
                authority = "reviewed work-title corpus"

        # A source-hash-pinned human override is allowed to resolve genuine
        # context collisions such as a personal name versus a generic role.
        if not canonical or row_id in reviewed_by_id:
            continue
        exact_by_id[row_id] = {
            "translation": canonical,
            "authority": authority,
        }
        draft = draft_by_id.get(row_id, {})
        draft_translation = draft.get("translation")
        compact_source = re.sub(r"\s+", "", normalized_source)
        if (
            isinstance(draft_translation, str)
            and draft_translation
            and draft_translation != canonical
            and len(compact_source) >= 3
            and len(draft_translation) >= 2
        ):
            propagation_rules.append(
                {
                    "source": compact_source,
                    "from": draft_translation,
                    "to": canonical,
                    "authority": authority,
                }
            )
    propagation_rules.sort(key=lambda item: len(item["source"]), reverse=True)
    return exact_by_id, propagation_rules


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
    candidate: str,
    glossary_terms: Iterable[dict[str, Any]],
    *,
    ambiguous_term_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    ambiguous = set(ambiguous_term_ids)
    enforced = [
        term
        for term in glossary_terms
        if term.get("status") == "approved" and term.get("enforce") is True
        and not (
            str(term.get("id", "")) in ambiguous
            and str(term.get("translation", "")) in candidate
        )
    ]
    protected = candidate
    canonicals = sorted(
        {
            str(term.get("translation", ""))
            for term in enforced
            if term.get("translation")
        },
        key=lambda value: (-len(value), value),
    )
    for canonical in canonicals:
        protected = protected.replace(canonical, "")
    return [
        dict(item)
        for item in deprecated_translation_conflicts(protected, enforced)
    ]


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


def apply_reviewed_replacements(
    text: str,
    replacements: Iterable[dict[str, Any]],
    *,
    row_id: str,
) -> tuple[str, list[str]]:
    """Apply source-hash-pinned, occurrence-aware human review edits.

    A plain global replacement is unsafe for entries where the machine draft
    renders both the organization ``Gekkostate`` and the ship ``Gekko-go`` as
    ``月光号``.  Review records can therefore select exact 1-based
    occurrences while retaining a compact, independently checkable patch.
    """

    result = text
    applied: list[str] = []
    for index, item in enumerate(replacements):
        old = item.get("from")
        new = item.get("to")
        occurrences = item.get("occurrences", "all")
        if not isinstance(old, str) or not old:
            raise ValueError(f"LIBRARY reviewed replacement {row_id}[{index}] has empty from")
        if not isinstance(new, str) or old == new:
            raise ValueError(f"LIBRARY reviewed replacement {row_id}[{index}] has invalid to")
        parts = result.split(old)
        match_count = len(parts) - 1
        if match_count == 0:
            raise ValueError(
                f"LIBRARY reviewed replacement {row_id}[{index}] no longer matches {old!r}"
            )
        if occurrences == "all":
            selected = set(range(1, match_count + 1))
        elif (
            isinstance(occurrences, list)
            and occurrences
            and all(isinstance(value, int) and value > 0 for value in occurrences)
            and len(set(occurrences)) == len(occurrences)
        ):
            selected = set(occurrences)
            if max(selected) > match_count:
                raise ValueError(
                    f"LIBRARY reviewed replacement {row_id}[{index}] selects occurrence "
                    f"{max(selected)} but only {match_count} exist"
                )
        else:
            raise ValueError(
                f"LIBRARY reviewed replacement {row_id}[{index}] has invalid occurrences"
            )
        rebuilt = [parts[0]]
        for occurrence, suffix in enumerate(parts[1:], 1):
            rebuilt.extend([new if occurrence in selected else old, suffix])
        result = "".join(rebuilt)
        label = "all" if occurrences == "all" else ",".join(map(str, occurrences))
        applied.append(f"{old}→{new}（第{label}处）")
    return result, applied


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
    replacement_by_id = require_unique(
        reviewed.get("replacement_entries", []),
        "id",
        "LIBRARY reviewed replacement entries",
    )
    overlap = set(reviewed_by_id) & set(replacement_by_id)
    if overlap:
        raise ValueError(
            f"LIBRARY full and replacement reviews overlap: {sorted(overlap)}"
        )
    authoritative_by_id, authoritative_propagation = (
        load_library_authoritative_surfaces(
            source_rows,
            draft_by_id,
            reviewed_by_id,
        )
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
        contextual_variant_ids = set(
            config.get("contextual_variant_glossary_ids", [])
        )
        rule_terms = [
            term
            for term in rule_terms_by_id.values()
            if str(term.get("id", "")) not in contextual_variant_ids
        ]
        references = source.get("references", [])
        domains = sorted({reference.get("domain", "unknown") for reference in references})
        tags = sorted({reference.get("tag", "") for reference in references if reference.get("tag")})
        kind = library_row_kind(tags)
        human_review = reviewed_by_id.get(row_id)
        replacement_review = replacement_by_id.get(row_id)
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
        candidate, reviewed_applied = apply_source_bound_review_replacements(
            candidate,
            config,
            {str(term["id"]) for term in glossary_terms},
        )
        applied.extend(reviewed_applied)
        candidate, surface_applied = apply_source_surface_replacements(
            candidate,
            glossary_match_text,
            config,
        )
        applied.extend(surface_applied)
        if human_review is None and row_id in authoritative_by_id:
            authoritative = authoritative_by_id[row_id]
            if candidate != authoritative["translation"]:
                candidate = authoritative["translation"]
                applied.append(
                    f"同步{authoritative['authority']}"
                )
        if kind == "body":
            compact_match_text = re.sub(
                r"\s+", "", normalized_text(glossary_match_text)
            )
            for rule in authoritative_propagation:
                if (
                    rule["source"] not in compact_match_text
                    or rule["from"] not in candidate
                    or rule["to"] in candidate
                ):
                    continue
                # Do not perform a global Chinese replacement when the row
                # contains more occurrences of that surface than the bound
                # Japanese name.  This happens in mixed Grendizer/Spazer
                # prose where the machine draft used one Chinese name for
                # two different source entities.  Such rows require a
                # source-hash-pinned, occurrence-aware review entry below.
                if compact_match_text.count(rule["source"]) != candidate.count(
                    rule["from"]
                ):
                    continue
                candidate = candidate.replace(rule["from"], rule["to"])
                applied.append(
                    f"{rule['from']}→{rule['to']}（{rule['authority']}）"
                )
        if replacement_review is not None:
            seen_reviewed.add(row_id)
            if replacement_review.get("source_text_sha256") != source["source_text_sha256"]:
                raise ValueError(
                    f"LIBRARY reviewed replacement source hash mismatch for {row_id}"
                )
            candidate, replacement_applied = apply_reviewed_replacements(
                candidate,
                replacement_review.get("replacements", []),
                row_id=row_id,
            )
            applied.extend(replacement_applied)
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
        contextual_ids = set(config.get("contextual_glossary_ids", []))
        contextual_prefixes = tuple(
            config.get("body_contextual_glossary_prefixes", [])
        )
        existing_missing_ids = {
            str(term.get("id", ""))
            for detail in risk_details
            if detail.get("code") == "glossary_hint_mismatch"
            for term in detail.get("terms", [])
        }
        for term in glossary_terms:
            term_id = str(term.get("id", ""))
            canonical = str(term.get("translation", ""))
            if (
                term.get("status") != "approved"
                or term.get("enforce") is not True
                or not canonical
                or canonical in candidate
                or term_id in contextual_ids
                or (kind == "body" and term_id.startswith(contextual_prefixes))
                or term_id in existing_missing_ids
                or (row_id in authoritative_by_id and "PRDC" in tags)
            ):
                continue
            risk_details.append(
                {
                    "code": "canonical_term_missing",
                    "id": term_id,
                    "canonical": canonical,
                    "matched_source_terms": list(
                        term.get("matched_source_terms", [])
                    ),
                }
            )
        accepted_audit_risks: list[str] = []
        review_record = human_review or replacement_review
        if review_record is not None:
            raw_accepted = review_record.get("accepted_audit_risks", [])
            if not isinstance(raw_accepted, list) or not all(
                isinstance(code, str) and code for code in raw_accepted
            ):
                raise ValueError(
                    f"LIBRARY reviewed accepted_audit_risks is invalid for {row_id}"
                )
            accepted_audit_risks = sorted(set(raw_accepted))
        risks = [risk.get("code", "unknown") for risk in risk_details]
        conflicts = find_term_conflicts(
            candidate,
            rule_terms,
            ambiguous_term_ids=config.get("ambiguous_deprecated_glossary_ids", []),
        )
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
                    if review_record is not None
                    else (
                        "authoritative_surface_sync"
                        if row_id in authoritative_by_id or applied
                        else "codex_consistency_pass"
                    )
                ),
                "editorial_note": (
                    "；".join(
                        [
                            *(
                                [str(review_record.get("note", "Codex 人工复核。"))]
                                if review_record is not None
                                else []
                            ),
                            *applied,
                        ]
                    )
                    if review_record is not None or applied
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
    missing_reviewed = (set(reviewed_by_id) | set(replacement_by_id)) - seen_reviewed
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
        DISPLAY_NAME_CONFIG,
        UNIT_NAME_CORPUS,
        STORY_SPEAKERS,
        REMAINING_UI,
        AUTO_DEMO_TITLES,
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
