"""Select researched display-name translations without committing source text."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, TextIO

from .display_names import build_display_name_report, load_display_name_source
from .font import (
    decode_vt1_font_segment,
    read_extended_glyph_table,
    sha256_bytes,
)
from .text import SrwzTextEncodeError, encode_text, load_text_table
from .ui_inventory import audit_entry_font
from .ui_menu import load_ui_font_overrides


class DisplayNameCoverageError(ValueError):
    """The researched-name selection or one of its locks has drifted."""


_SELECTION_POLICY = {
    "source_match": "exact",
    "require_one_translation_per_source": True,
    "exclude_prior_translation_ids": True,
    "source_text_in_git": False,
    "writer_relationship": "separate_component",
}


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DisplayNameCoverageError(
            f"cannot load JSON object {path}"
        ) from error
    if not isinstance(value, dict):
        raise DisplayNameCoverageError(f"JSON root must be an object: {path}")
    return value


def _project_path(root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise DisplayNameCoverageError("project path must be a non-empty string")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise DisplayNameCoverageError("project path must be relative")
    project_root = root.resolve()
    path = (project_root / relative).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as error:
        raise DisplayNameCoverageError(f"path escapes project root: {raw}") from error
    return path


def _locked_json(
    root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, dict]:
    path = _project_path(root, reference.get("path"))
    if not path.is_file() or sha256_bytes(path.read_bytes()) != reference.get(
        "sha256"
    ):
        raise DisplayNameCoverageError(f"{label} SHA-256 drift")
    return path, _json_object(path)


def _selection_sha256(entries: list[dict]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["id"]):
        digest.update(
            json.dumps(
                {
                    "id": entry["id"],
                    "source_text_sha256": entry["source_text_sha256"],
                    "translation": entry["translation"],
                    "source_refs": entry["source_refs"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _assignment_index(path: Path) -> dict[str, dict]:
    document = _json_object(path)
    raw_assignments = document.get("assignments")
    if not isinstance(raw_assignments, list):
        raise DisplayNameCoverageError(
            f"assignment file has no assignments: {path}"
        )
    assignments = {}
    for raw in raw_assignments:
        if not isinstance(raw, dict):
            raise DisplayNameCoverageError(
                f"malformed assignment in {path}"
            )
        character = raw.get("character")
        code = raw.get("code")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, str)
            or character in assignments
        ):
            raise DisplayNameCoverageError(
                f"malformed or duplicate assignment in {path}"
            )
        assignments[character] = {
            **raw,
            "code_value": int(code, 16),
        }
    return assignments


def _renderer_baseline(
    root: Path,
    config: Mapping[str, object],
    font_manifest: Mapping[str, object],
    table,
) -> tuple[dict, dict]:
    component = font_manifest.get("font_component")
    proposal = font_manifest.get("proposal")
    if not isinstance(component, dict) or not isinstance(proposal, dict):
        raise DisplayNameCoverageError(
            "font candidate lacks component or proposal locks"
        )
    report_path = _project_path(root, component.get("report"))
    if (
        not report_path.is_file()
        or sha256_bytes(report_path.read_bytes())
        != component.get("report_sha256")
    ):
        raise DisplayNameCoverageError("font component report SHA-256 drift")
    component_report = _json_object(report_path)
    paths = {
        "slps": report_path.parent / "SLPS_258.87",
        "vt1": report_path.parent / "DATA/VT1.BIN",
    }
    payloads = {}
    for label, path in paths.items():
        expected = component.get("outputs", {}).get(label)
        if (
            not isinstance(expected, dict)
            or not path.is_file()
            or path.stat().st_size != expected.get("size")
            or sha256_bytes(path.read_bytes()) != expected.get("sha256")
        ):
            raise DisplayNameCoverageError(
                f"font component {label} output drift"
            )
        payloads[label] = path.read_bytes()
    proposal_path = _project_path(root, proposal.get("path"))
    if (
        not proposal_path.is_file()
        or sha256_bytes(proposal_path.read_bytes()) != proposal.get("sha256")
    ):
        raise DisplayNameCoverageError("font proposal SHA-256 drift")
    base_path = _project_path(root, config["base_codebook"]["path"])
    baseline = {
        "table": table,
        "extended_entries": read_extended_glyph_table(payloads["slps"]),
        "font": decode_vt1_font_segment(
            payloads["slps"],
            payloads["vt1"],
        ).decoded,
        "base_assignments": _assignment_index(base_path),
        "proposal_assignments": _assignment_index(proposal_path),
        "retired_characters": tuple(
            _json_object(proposal_path)
            .get("allocation_registry", {})
            .get("retired_characters", [])
        ),
    }
    return baseline, {
        "report": str(report_path.relative_to(root.resolve())),
        "report_sha256": sha256_bytes(report_path.read_bytes()),
        "slps": {
            "path": str(paths["slps"].relative_to(root.resolve())),
            **component["outputs"]["slps"],
        },
        "vt1": {
            "path": str(paths["vt1"].relative_to(root.resolve())),
            **component["outputs"]["vt1"],
        },
        "proposal": {
            "path": str(proposal_path.relative_to(root.resolve())),
            "sha256": sha256_bytes(proposal_path.read_bytes()),
        },
        "component_status": component_report["status"],
    }


def _glossary_index(
    root: Path,
    release_reference: Mapping[str, object],
) -> tuple[dict[str, dict], dict]:
    release_path, release = _locked_json(
        root,
        release_reference,
        label="glossary release",
    )
    if release.get("release_id") != release_reference.get("release_id"):
        raise DisplayNameCoverageError("glossary release ID drift")
    accepted = release_reference.get("accepted_term_statuses")
    if (
        not isinstance(accepted, list)
        or not accepted
        or any(not isinstance(status, str) or not status for status in accepted)
    ):
        raise DisplayNameCoverageError("accepted glossary statuses are invalid")
    accepted_set = set(accepted)
    raw_sources = release.get("glossary_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise DisplayNameCoverageError("glossary release has no sources")

    by_source: defaultdict[str, list[dict]] = defaultdict(list)
    source_reports = []
    accepted_term_count = 0
    for raw_path in raw_sources:
        path = _project_path(root, raw_path)
        document = _json_object(path)
        terms = document.get("terms")
        if not isinstance(terms, list):
            raise DisplayNameCoverageError(f"glossary has no terms: {path}")
        source_accepted = 0
        for term in terms:
            if not isinstance(term, dict):
                raise DisplayNameCoverageError(f"malformed glossary term: {path}")
            if term.get("status") not in accepted_set:
                continue
            term_id = term.get("id")
            translation = term.get("translation")
            source_terms = term.get("source_terms")
            if (
                not isinstance(term_id, str)
                or not term_id
                or not isinstance(translation, str)
                or not translation
                or not isinstance(source_terms, list)
                or not source_terms
            ):
                raise DisplayNameCoverageError(
                    f"accepted glossary term is incomplete: {path}"
                )
            for source in source_terms:
                if not isinstance(source, str) or not source:
                    raise DisplayNameCoverageError(
                        f"accepted glossary source term is invalid: {path}"
                    )
                by_source[source].append(
                    {
                        "translation": translation,
                        "source_ref": term_id,
                    }
                )
            source_accepted += 1
            accepted_term_count += 1
        source_reports.append(
            {
                "path": str(path.relative_to(root.resolve())),
                "sha256": sha256_bytes(path.read_bytes()),
                "term_count": len(terms),
                "accepted_term_count": source_accepted,
            }
        )

    index = {}
    conflict_source_count = 0
    same_translation_multi_ref_count = 0
    for source, decisions in by_source.items():
        translations = {decision["translation"] for decision in decisions}
        if len(translations) != 1:
            conflict_source_count += 1
            continue
        source_refs = sorted({decision["source_ref"] for decision in decisions})
        if len(source_refs) > 1:
            same_translation_multi_ref_count += 1
        index[source] = {
            "translation": next(iter(translations)),
            "source_refs": source_refs,
        }
    return index, {
        "release": {
            "path": str(release_path.relative_to(root.resolve())),
            "sha256": sha256_bytes(release_path.read_bytes()),
            "release_id": release["release_id"],
        },
        "accepted_statuses": sorted(accepted_set),
        "sources": source_reports,
        "accepted_term_count": accepted_term_count,
        "exact_source_count": len(by_source),
        "eligible_exact_source_count": len(index),
        "conflict_source_count": conflict_source_count,
        "same_translation_multi_ref_count": same_translation_multi_ref_count,
    }


def _prior_ids(
    root: Path,
    references: object,
    source_by_id: Mapping[str, object],
) -> tuple[set[str], list[dict]]:
    if not isinstance(references, list) or not references:
        raise DisplayNameCoverageError("prior translation sources are missing")
    selected = set()
    reports = []
    for raw in references:
        if not isinstance(raw, dict):
            raise DisplayNameCoverageError("prior translation source is invalid")
        path, document = _locked_json(
            root,
            raw,
            label="prior display-name translation",
        )
        if document.get("batch_id") != raw.get("batch_id"):
            raise DisplayNameCoverageError("prior translation batch drift")
        entries = document.get("entries")
        if not isinstance(entries, list) or len(entries) != raw.get("entry_count"):
            raise DisplayNameCoverageError("prior translation count drift")
        for entry in entries:
            if not isinstance(entry, dict):
                raise DisplayNameCoverageError("prior translation entry is invalid")
            entry_id = entry.get("id")
            source = source_by_id.get(entry_id)
            if source is None:
                raise DisplayNameCoverageError("prior translation ID drift")
            if entry.get("source_text_sha256") != source.source_text_sha256:
                raise DisplayNameCoverageError("prior translation source hash drift")
            if entry_id in selected:
                raise DisplayNameCoverageError("duplicate prior translation ID")
            selected.add(entry_id)
        reports.append(
            {
                "path": str(path.relative_to(root.resolve())),
                "sha256": sha256_bytes(path.read_bytes()),
                "batch_id": document["batch_id"],
                "entry_count": len(entries),
            }
        )
    return selected, reports


def _missing_characters(
    translation: str,
    table,
    overrides: Mapping[str, int],
) -> tuple[str, ...]:
    missing = []
    for character in sorted(set(translation)):
        try:
            encode_text(character, table, overrides=overrides)
        except SrwzTextEncodeError:
            missing.append(character)
    return tuple(missing)


def _projected_encoded_size(
    translation: str,
    missing: set[str],
    table,
    overrides: Mapping[str, int],
) -> int:
    size = 1
    for character in translation:
        if character in missing:
            size += 2
        else:
            size += len(encode_text(character, table, overrides=overrides))
    return size


def audit_display_name_coverage(
    project_root: Path,
    config_path: Path,
) -> tuple[dict, dict]:
    """Build a local review and bounded researched-name selection manifest."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise DisplayNameCoverageError("unsupported display-name coverage schema")
    if config.get("selection_policy") != _SELECTION_POLICY:
        raise DisplayNameCoverageError("display-name selection policy drift")

    structure = config.get("structure")
    if not isinstance(structure, dict):
        raise DisplayNameCoverageError("display-name structure lock is missing")
    structure_config_path, _ = _locked_json(
        root,
        {
            "path": structure.get("config"),
            "sha256": structure.get("config_sha256"),
        },
        label="display-name structure config",
    )
    structure_manifest_path, structure_manifest = _locked_json(
        root,
        {
            "path": structure.get("manifest"),
            "sha256": structure.get("manifest_sha256"),
        },
        label="display-name structure manifest",
    )
    if structure_manifest.get("status") != structure.get("required_status"):
        raise DisplayNameCoverageError("display-name structure status drift")
    _, expected_structure_manifest = build_display_name_report(
        root,
        structure_config_path,
    )
    if expected_structure_manifest != structure_manifest:
        raise DisplayNameCoverageError(
            "display-name structure manifest is not reproducible"
        )
    structure_config, _, parsed, structure_context = load_display_name_source(
        root,
        structure_config_path,
    )
    source_by_id = {entry.entry_id: entry for entry in parsed.entries}

    glossary, glossary_report = _glossary_index(
        root,
        config.get("glossary_release", {}),
    )
    prior, prior_reports = _prior_ids(
        root,
        config.get("prior_translation_sources"),
        source_by_id,
    )

    font_reference = config.get("font_candidate")
    if not isinstance(font_reference, dict):
        raise DisplayNameCoverageError("font candidate lock is missing")
    font_manifest_path, font_manifest = _locked_json(
        root,
        {
            "path": font_reference.get("manifest"),
            "sha256": font_reference.get("sha256"),
        },
        label="font candidate",
    )
    if font_manifest.get("status") != font_reference.get("required_status"):
        raise DisplayNameCoverageError("font candidate status drift")
    try:
        overrides, codebook_report = load_ui_font_overrides(
            root,
            config,
            font_manifest,
        )
    except ValueError as error:
        raise DisplayNameCoverageError(str(error)) from error
    table = load_text_table(
        _project_path(root, structure_config["text_table"]["path"])
    )
    renderer_baseline, renderer_baseline_report = _renderer_baseline(
        root,
        config,
        font_manifest,
        table,
    )

    selected = []
    rows = []
    missing_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    table_selected_counts: Counter[str] = Counter()
    selected_sources = set()
    projected_overflow_ids = []
    non_empty_entries = [entry for entry in parsed.entries if entry.text]
    for entry in non_empty_entries:
        decision = glossary.get(entry.text)
        if entry.entry_id in prior:
            disposition = "prior_translation"
            translation = ""
            source_refs = []
            missing = ()
            projected_size = None
        elif decision is None:
            disposition = "unresolved"
            translation = ""
            source_refs = []
            missing = ()
            projected_size = None
        else:
            disposition = "selected_researched_exact"
            translation = decision["translation"]
            source_refs = decision["source_refs"]
            missing = _missing_characters(translation, table, overrides)
            projected_size = _projected_encoded_size(
                translation,
                set(missing),
                table,
                overrides,
            )
            overflow = projected_size > entry.capacity
            if overflow:
                projected_overflow_ids.append(entry.entry_id)
            for character in missing:
                missing_counts[character] += 1
            selected_entry = {
                "id": entry.entry_id,
                "table": entry.table,
                "record_index": entry.record_index,
                "field": entry.field,
                "source_text_sha256": entry.source_text_sha256,
                "translation": translation,
                "source_refs": source_refs,
                "current_font_status": (
                    "missing_characters" if missing else "ready"
                ),
                "current_font_missing_characters": "".join(missing),
                "projected_encoded_size": projected_size,
                "capacity": entry.capacity,
                "projected_overflow": overflow,
            }
            selected.append(selected_entry)
            selected_sources.add(entry.text)
            table_selected_counts[entry.table] += 1
        disposition_counts[disposition] += 1
        rows.append(
            {
                "id": entry.entry_id,
                "table": entry.table,
                "record_index": entry.record_index,
                "field": entry.field,
                "source_text": entry.text,
                "source_text_sha256": entry.source_text_sha256,
                "disposition": disposition,
                "translation": translation,
                "source_refs": ";".join(source_refs),
                "current_font_missing_characters": "".join(missing),
                "projected_encoded_size": (
                    "" if projected_size is None else projected_size
                ),
                "capacity": entry.capacity,
                "projected_overflow": (
                    "" if projected_size is None else projected_size > entry.capacity
                ),
            }
        )

    selected.sort(key=lambda entry: entry["id"])
    rows.sort(key=lambda entry: entry["id"])
    ready_count = sum(
        entry["current_font_status"] == "ready" for entry in selected
    )
    missing_count = len(selected) - ready_count
    renderer_coverage = audit_entry_font(selected, renderer_baseline)
    renderer_missing_characters = renderer_coverage["missing_characters"]
    renderer_missing_set = set(renderer_missing_characters)
    reactivatable_characters = "".join(
        character
        for character in renderer_missing_characters
        if character in renderer_baseline["retired_characters"]
    )
    new_allocation_character_count = (
        len(renderer_missing_characters) - len(reactivatable_characters)
    )
    renderer_missing_entry_count = sum(
        bool(set(entry["translation"]) & renderer_missing_set)
        for entry in selected
    )
    renderer_original_han = renderer_coverage[
        "original_font_han_characters"
    ]
    renderer_original_han_set = set(renderer_original_han)
    renderer_original_han_entry_count = sum(
        bool(set(entry["translation"]) & renderer_original_han_set)
        for entry in selected
    )
    remaining_slots = font_manifest.get("capacity", {}).get(
        "remaining_candidate_slot_count"
    )
    if not isinstance(remaining_slots, int) or isinstance(
        remaining_slots,
        bool,
    ):
        raise DisplayNameCoverageError(
            "font candidate remaining-slot count is invalid"
        )
    projected_remaining_slots = (
        remaining_slots - new_allocation_character_count
    )
    ratchet = config.get("ratchet")
    actual_ratchet = {
        "structure_entry_count": len(parsed.entries),
        "non_empty_entry_count": len(non_empty_entries),
        "prior_translation_entry_count": len(prior),
        "selected_entry_count": len(selected),
        "selected_pilot_entry_count": table_selected_counts["pilot"],
        "selected_unit_entry_count": table_selected_counts["unit"],
        "selected_unique_source_count": len(selected_sources),
        "current_font_ready_entry_count": ready_count,
        "current_font_missing_entry_count": missing_count,
        "current_font_missing_character_count": len(missing_counts),
        "current_renderer_ready_entry_count": (
            len(selected) - renderer_missing_entry_count
        ),
        "current_renderer_missing_entry_count": (
            renderer_missing_entry_count
        ),
        "current_renderer_missing_character_count": len(
            renderer_missing_characters
        ),
        "current_renderer_reactivatable_character_count": len(
            reactivatable_characters
        ),
        "current_renderer_new_allocation_character_count": (
            new_allocation_character_count
        ),
        "current_renderer_original_han_character_count": len(
            renderer_original_han
        ),
        "current_renderer_original_han_entry_count": (
            renderer_original_han_entry_count
        ),
        "projected_remaining_candidate_slot_count": (
            projected_remaining_slots
        ),
        "projected_overflow_entry_count": len(projected_overflow_ids),
        "unresolved_entry_count": disposition_counts["unresolved"],
    }
    if actual_ratchet != ratchet:
        raise DisplayNameCoverageError(
            f"display-name coverage ratchet drift: {actual_ratchet}"
        )

    report = {
        "schema_version": 1,
        "status": "researched_selection_ready",
        "content_policy": (
            "This ignored report and TSV contain original Japanese display "
            "names. The committed manifest contains counts, hashes, missing "
            "characters and decision provenance only."
        ),
        "selection_id": config["selection_id"],
        "scope": config["scope"],
        "inputs": {
            "config": {
                "path": str(config_path.relative_to(root)),
                "sha256": sha256_bytes(config_path.read_bytes()),
            },
            "structure": {
                "config": structure_context["config"],
                "manifest": {
                    "path": str(structure_manifest_path.relative_to(root)),
                    "sha256": sha256_bytes(structure_manifest_path.read_bytes()),
                    "status": structure_manifest["status"],
                    "entry_signature_sha256": structure_manifest["totals"][
                        "entry_signature_sha256"
                    ],
                },
            },
            "glossary": glossary_report,
            "prior_translations": prior_reports,
            "font_candidate": {
                "manifest": str(font_manifest_path.relative_to(root)),
                "sha256": sha256_bytes(font_manifest_path.read_bytes()),
                "status": font_manifest["status"],
                "codebook": codebook_report,
                "renderer_baseline": renderer_baseline_report,
            },
        },
        "summary": actual_ratchet,
        "selection": {
            "entry_count": len(selected),
            "selection_sha256": _selection_sha256(selected),
            "font_ready_entry_count": ready_count,
            "font_missing_entry_count": missing_count,
            "missing_character_count": len(missing_counts),
            "missing_characters": "".join(sorted(missing_counts)),
            "missing_character_occurrence_counts": dict(
                sorted(missing_counts.items())
            ),
            "projected_overflow_entry_count": len(projected_overflow_ids),
            "projected_overflow_ids": projected_overflow_ids,
            "entries": selected,
        },
        "renderer_readiness": {
            "entry_count": len(selected),
            "ready_entry_count": (
                len(selected) - renderer_missing_entry_count
            ),
            "missing_entry_count": renderer_missing_entry_count,
            "missing_character_count": len(renderer_missing_characters),
            "missing_characters": renderer_missing_characters,
            "missing_character_occurrence_count": renderer_coverage[
                "missing_character_occurrence_count"
            ],
            "missing": renderer_coverage["missing"],
            "reactivatable_registered_character_count": len(
                reactivatable_characters
            ),
            "reactivatable_registered_characters": (
                reactivatable_characters
            ),
            "new_allocation_character_count": (
                new_allocation_character_count
            ),
            "original_font_han_character_count": len(renderer_original_han),
            "original_font_han_characters": renderer_original_han,
            "original_font_han_entry_count": (
                renderer_original_han_entry_count
            ),
            "available_candidate_slot_count": remaining_slots,
            "projected_remaining_candidate_slot_count": (
                projected_remaining_slots
            ),
        },
        "review_queue": {
            "row_count": len(rows),
            "disposition_counts": dict(sorted(disposition_counts.items())),
            "rows": rows,
        },
        "next_gate": (
            "A separate font profile and fixed-allocation COMPDATA component "
            "must consume this exact selection. Their static and runtime "
            "acceptance remain independent from this selection manifest."
        ),
    }
    manifest = {
        "schema_version": 1,
        "status": report["status"],
        "selection_id": report["selection_id"],
        "scope": report["scope"],
        "content_policy": report["content_policy"],
        "inputs": report["inputs"],
        "summary": report["summary"],
        "selection": {
            key: value
            for key, value in report["selection"].items()
            if key != "entries"
        },
        "renderer_readiness": report["renderer_readiness"],
        "review_queue": {
            "row_count": report["review_queue"]["row_count"],
            "disposition_counts": report["review_queue"]["disposition_counts"],
        },
        "acceptance": {
            "structure_reproducible": True,
            "researched_exact_match_only": True,
            "conflicting_researched_sources_excluded": True,
            "prior_translation_ids_excluded": True,
            "source_text_absent_from_manifest": True,
            "selection_hash_locked": True,
            "current_font_readiness_measured": True,
            "renderer_readiness_measured": True,
            "renderer_allocation_fits_available_slots": (
                projected_remaining_slots >= 0
            ),
            "projected_fixed_allocation_overflow_count_zero": (
                not projected_overflow_ids
            ),
            "selection_only_no_game_write": True,
            "runtime_not_tested": True,
        },
        "next_gate": report["next_gate"],
    }
    return report, manifest


_TSV_FIELDS = (
    "id",
    "table",
    "record_index",
    "field",
    "source_text",
    "source_text_sha256",
    "disposition",
    "translation",
    "source_refs",
    "current_font_missing_characters",
    "projected_encoded_size",
    "capacity",
    "projected_overflow",
)


def write_display_name_coverage_tsv(
    report: Mapping[str, object],
    stream: TextIO,
) -> None:
    """Write the ignored, source-bearing display-name review queue."""

    writer = csv.DictWriter(
        stream,
        fieldnames=_TSV_FIELDS,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in report["review_queue"]["rows"]:
        writer.writerow({field: row[field] for field in _TSV_FIELDS})


__all__ = [
    "DisplayNameCoverageError",
    "audit_display_name_coverage",
    "write_display_name_coverage_tsv",
]
