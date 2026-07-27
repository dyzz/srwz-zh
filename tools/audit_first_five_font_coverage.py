#!/usr/bin/env python3
"""Audit first-five text against the renderer and built VT1 font.

This is deliberately stricter than the writeback capacity audit.  A
character is usable only when its encoded value reaches a glyph through the
current executable and that glyph is non-blank.  Merely appearing in the
pinned text table is not sufficient.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

try:
    from srwz.diagnostics import require_work_output
    from srwz.font import (
        GLYPH_SIZE,
        analyze_glyph_code_mapping,
        decode_vt1_font_segment,
        glyph_index_for_code,
        is_cjk_unified_ideograph,
        read_extended_glyph_table,
        sha256_bytes,
    )
    from srwz.text import (
        PRINTABLE_ASCII,
        control_notation_positions,
        load_text_table,
    )
except ModuleNotFoundError:
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.font import (
        GLYPH_SIZE,
        analyze_glyph_code_mapping,
        decode_vt1_font_segment,
        glyph_index_for_code,
        is_cjk_unified_ideograph,
        read_extended_glyph_table,
        sha256_bytes,
    )
    from tools.srwz.text import (
        PRINTABLE_ASCII,
        control_notation_positions,
        load_text_table,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
TEXT_TABLE = (
    PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
)
BASE_CODEBOOK = PROJECT_ROOT / "config/encoding/codebook.json"
PROPOSAL = WORK_ROOT / "writeback/first-five-codebook-proposal.json"
SOURCE_SLPS = WORK_ROOT / "disc/SLPS_258.87"
SOURCE_VT1 = WORK_ROOT / "disc/DATA/VT1.BIN"
BUILT_SLPS = WORK_ROOT / "build/first-five/components/SLPS_258.87"
BUILT_VT1 = WORK_ROOT / "build/first-five/components/DATA/VT1.BIN"

# These windows are already documented by the clean-room static audit.  The
# current build can prove that it still contains the source bytes, but a
# changed window would require a separate implementation contract; byte
# inequality alone never proves that an ASCII patch is valid.
ASCII_HOOK_FILE_OFFSET = 0x3C3E8
ASCII_HOOK_SIZE = 32
ASCII_INJECTED_FILE_OFFSET = 0x2F72A0
ASCII_INJECTED_SIZE = 676

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit first-five translations against the actual executable "
            "code-to-glyph resolver and built VT1 font."
        )
    )
    parser.add_argument("--slps", type=Path, default=BUILT_SLPS)
    parser.add_argument("--vt1", type=Path, default=BUILT_VT1)
    parser.add_argument(
        "--report",
        type=Path,
        default=WORK_ROOT / "review/first-five-font-coverage.json",
    )
    parser.add_argument(
        "--findings",
        type=Path,
        default=(
            WORK_ROOT / "review/first-five-font-coverage-findings.tsv"
        ),
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-findings",
        action="store_true",
        help="write the diagnostic report without returning a failing status",
    )
    return parser.parse_args()


def _translation_documents() -> tuple[tuple[str, dict], ...]:
    documents = []
    for stage in range(1, 6):
        path = (
            PROJECT_ROOT
            / f"corpus/zh/story-dialogue/stage-{stage:03d}.json"
        )
        documents.append(
            (f"dialogue-{stage:03d}", json.loads(path.read_text()))
        )
    for name in ("story-speakers", "story-conditions"):
        document = json.loads(
            (PROJECT_ROOT / f"corpus/zh/{name}.json").read_text()
        )
        document["entries"] = [
            entry
            for entry in document["entries"]
            if int(entry["id"].split("/")[1]) <= 5
        ]
        documents.append((name, document))
    return tuple(documents)


def _assignments(path: Path) -> tuple[dict[str, dict], ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assignments = []
    for raw in document["assignments"]:
        assignment = dict(raw)
        assignment["code_value"] = int(raw["code"], 16)
        assignments.append(assignment)
    return tuple(assignments)


def _control_positions(text: str) -> frozenset[int]:
    return control_notation_positions(text)


def _entry_references(occurrences: list[dict]) -> list[dict]:
    grouped = {}
    for occurrence in occurrences:
        key = (occurrence["document"], occurrence["entry_id"])
        reference = grouped.setdefault(
            key,
            {
                "document": occurrence["document"],
                "stage_index": occurrence["stage_index"],
                "entry_id": occurrence["entry_id"],
                "occurrence_count": 0,
                "positions": [],
                "translation": occurrence["translation"],
            },
        )
        reference["occurrence_count"] += 1
        reference["positions"].append(occurrence["position"])
    return [
        grouped[key]
        for key in sorted(
            grouped,
            key=lambda value: (
                grouped[value]["stage_index"],
                value[0],
                value[1],
            ),
        )
    ]


def _stage_summary(findings: list[dict]) -> dict:
    summary = {}
    for stage in range(1, 6):
        stage_characters = []
        stage_occurrences = 0
        stage_entries = set()
        for finding in findings:
            references = [
                reference
                for reference in finding["references"]
                if reference["stage_index"] == stage
            ]
            if not references:
                continue
            stage_characters.append(finding["character"])
            stage_occurrences += sum(
                reference["occurrence_count"]
                for reference in references
            )
            stage_entries.update(
                reference["entry_id"] for reference in references
            )
        summary[str(stage)] = {
            "character_count": len(stage_characters),
            "occurrence_count": stage_occurrences,
            "entry_count": len(stage_entries),
        }
    return summary


def _finding_summary(findings: list[dict]) -> dict:
    references = [
        reference
        for finding in findings
        for reference in finding["references"]
    ]
    return {
        "character_count": len(findings),
        "occurrence_count": sum(
            reference["occurrence_count"] for reference in references
        ),
        "entry_count": len(
            {reference["entry_id"] for reference in references}
        ),
        "stage_counts": _stage_summary(findings),
    }


def _slice(data: bytes, offset: int, size: int) -> bytes:
    result = data[offset:offset + size]
    if len(result) != size:
        raise ValueError(f"executable window outside file at 0x{offset:X}")
    return result


def _cp932_alignment(table) -> dict:
    exact = 0
    invalid = []
    mismatches = []
    for code, character in sorted(table.characters.items()):
        try:
            decoded = code.to_bytes(2, "big").decode("cp932")
        except UnicodeDecodeError:
            invalid.append(
                {"code": f"{code:04X}", "table_character": character}
            )
            continue
        if decoded == character:
            exact += 1
        else:
            mismatches.append(
                {
                    "code": f"{code:04X}",
                    "table_character": character,
                    "cp932_character": decoded,
                }
            )
    return {
        "text_code_count": len(table.characters),
        "cp932_exact_count": exact,
        "cp932_invalid_count": len(invalid),
        "cp932_mismatch_count": len(mismatches),
        "invalid_codes": invalid,
        "mismatches": mismatches,
        "classification": (
            "The pinned table is a broad CP932-oriented codec table, not "
            "an inventory of glyphs reachable through the game renderer."
        ),
    }


def audit_first_five_font_coverage(
    *,
    slps_path: Path = BUILT_SLPS,
    vt1_path: Path = BUILT_VT1,
) -> tuple[dict, list[dict]]:
    table = load_text_table(TEXT_TABLE)
    base_assignments = _assignments(BASE_CODEBOOK)
    proposal_assignments = _assignments(PROPOSAL)
    base_by_character = {
        assignment["character"]: assignment
        for assignment in base_assignments
    }
    proposal_by_character = {
        assignment["character"]: assignment
        for assignment in proposal_assignments
    }
    overrides = {**base_by_character, **proposal_by_character}

    slps = slps_path.read_bytes()
    vt1 = vt1_path.read_bytes()
    source_slps = SOURCE_SLPS.read_bytes()
    source_vt1 = SOURCE_VT1.read_bytes()
    extended_entries = read_extended_glyph_table(slps)
    built_font = decode_vt1_font_segment(slps, vt1).decoded
    source_font = decode_vt1_font_segment(
        source_slps,
        source_vt1,
    ).decoded

    occurrences = defaultdict(list)
    literal_ascii_occurrences = defaultdict(list)
    entry_provenance = Counter()
    documents = _translation_documents()
    entry_count = 0
    for document_name, document in documents:
        for entry in document["entries"]:
            entry_count += 1
            entry_id = entry["id"]
            stage = int(entry_id.split("/")[1])
            text = entry["translation"]
            controls = _control_positions(text)
            provenance = set()
            for position, character in enumerate(text):
                occurrence = {
                    "document": document_name,
                    "stage_index": stage,
                    "entry_id": entry_id,
                    "position": position,
                    "translation": text,
                }
                if position in controls:
                    continue
                if character in overrides:
                    occurrences[character].append(occurrence)
                    if character in proposal_by_character:
                        provenance.add(
                            "selected_font_han"
                            if is_cjk_unified_ideograph(character)
                            else "selected_font_other"
                        )
                    else:
                        provenance.add("existing_codebook")
                    continue
                if character in PRINTABLE_ASCII:
                    literal_ascii_occurrences[character].append(
                        occurrence
                    )
                    continue
                if character == "\n":
                    continue
                if character in table.inverse_characters:
                    occurrences[character].append(occurrence)
                    if is_cjk_unified_ideograph(character):
                        try:
                            glyph_index_for_code(
                                table.inverse_characters[character],
                                extended_entries,
                            )
                        except ValueError:
                            provenance.add("unresolved_han")
                        else:
                            provenance.add("pinned_original_han")
                    else:
                        provenance.add("pinned_original_non_han")
                    continue
                try:
                    encoded = character.encode("cp932")
                except UnicodeEncodeError:
                    encoded = b""
                if len(encoded) == 1 and 0xA1 <= encoded[0] <= 0xDF:
                    provenance.add("cp932_halfwidth")
                else:
                    occurrences[character].append(occurrence)
                    provenance.add("unencodable")

            if {
                "selected_font_han",
                "pinned_original_han",
            } <= provenance:
                entry_provenance[
                    "mixed_selected_and_original_han"
                ] += 1
            elif {
                "selected_font_han",
                "unresolved_han",
            } <= provenance:
                entry_provenance[
                    "selected_font_han_with_unresolved_han"
                ] += 1
            elif "selected_font_han" in provenance:
                entry_provenance["selected_font_han_only"] += 1
            elif "unresolved_han" in provenance:
                entry_provenance["unresolved_han_without_selected_font"] += 1
            else:
                entry_provenance["no_selected_font_han"] += 1

    findings = []
    used_slots = defaultdict(list)
    for character in sorted(occurrences):
        if character in overrides:
            assignment = overrides[character]
            code = assignment["code_value"]
            mapping_source = (
                "base_codebook"
                if character in base_by_character
                else "first_five_proposal"
            )
        else:
            code = table.inverse_characters.get(character)
            assignment = None
            mapping_source = (
                "pinned_text_table" if code is not None else "unmapped"
            )

        if code is None:
            finding_type = "unencodable"
            glyph_index = None
            reason = "character has no deterministic encoding"
        else:
            try:
                glyph_index = glyph_index_for_code(
                    code,
                    extended_entries,
                )
            except ValueError as error:
                glyph_index = None
                finding_type = "resolver_unreachable"
                reason = str(error)
            else:
                glyph = built_font[
                    glyph_index * GLYPH_SIZE:
                    (glyph_index + 1) * GLYPH_SIZE
                ]
                used_slots[glyph_index].append((character, code))
                if not any(glyph) and character not in {" ", "\u3000"}:
                    finding_type = "blank_glyph"
                    reason = "resolved built glyph is all zero"
                else:
                    continue

        findings.append(
            {
                "severity": "error",
                "finding_type": finding_type,
                "character": character,
                "unicode": f"U+{ord(character):04X}",
                "code": f"{code:04X}" if code is not None else None,
                "mapping_source": mapping_source,
                "glyph_index": glyph_index,
                "reason": reason,
                "references": _entry_references(occurrences[character]),
            }
        )

    findings.sort(
        key=lambda finding: (
            finding["finding_type"],
            finding["code"] or "",
            finding["unicode"],
        )
    )
    collisions = [
        {
            "glyph_index": glyph_index,
            "characters": [
                {"character": character, "code": f"{code:04X}"}
                for character, code in values
            ],
        }
        for glyph_index, values in sorted(used_slots.items())
        if len(values) > 1
    ]

    ascii_findings = [
        {
            "severity": "risk",
            "finding_type": "ascii_runtime_path_not_adopted",
            "character": character,
            "unicode": f"U+{ord(character):04X}",
            "code": f"{ord(character):02X}",
            "mapping_source": "one_byte_ascii",
            "glyph_index": None,
            "reason": (
                "current executable retains the source ASCII hook and "
                "empty injected-code window"
            ),
            "references": _entry_references(values),
        }
        for character, values in sorted(
            literal_ascii_occurrences.items(),
            key=lambda item: ord(item[0]),
        )
    ]

    proposal_slot_reports = []
    for assignment in proposal_assignments:
        glyph_index = assignment["glyph_index"]
        start = glyph_index * GLYPH_SIZE
        source_glyph = source_font[start:start + GLYPH_SIZE]
        built_glyph = built_font[start:start + GLYPH_SIZE]
        proposal_slot_reports.append(
            {
                "character": assignment["character"],
                "code": assignment["code"],
                "glyph_index": glyph_index,
                "status": assignment["status"],
                "mapping": assignment["mapping"],
                "source_glyph_blank": not any(source_glyph),
                "source_preimage_hash_exact": (
                    sha256_bytes(source_glyph)
                    == assignment["allocation"][
                        "glyph_preimage_sha256"
                    ]
                ),
                "built_raster_hash_exact": (
                    sha256_bytes(built_glyph)
                    == assignment["raster"]["packed_glyph_sha256"]
                ),
            }
        )
    allocation_slot_reports = [
        report
        for report in proposal_slot_reports
        if report["status"] == "proposed_allocation"
    ]
    reraster_slot_reports = [
        report
        for report in proposal_slot_reports
        if report["status"] == "proposed_reraster"
    ]

    base_slot_reports = []
    for assignment in base_assignments:
        glyph_index = assignment["glyph_index"]
        start = glyph_index * GLYPH_SIZE
        built_glyph = built_font[start:start + GLYPH_SIZE]
        effective = proposal_by_character.get(
            assignment["character"],
            assignment,
        )
        base_slot_reports.append(
            {
                "character": assignment["character"],
                "code": assignment["code"],
                "glyph_index": glyph_index,
                "built_glyph_blank": not any(built_glyph),
                "superseded_by_first_five_font_plan": (
                    effective is not assignment
                ),
                "built_effective_raster_hash_exact": (
                    sha256_bytes(built_glyph)
                    == effective["raster"]["packed_glyph_sha256"]
                ),
            }
        )

    source_hook = _slice(
        source_slps,
        ASCII_HOOK_FILE_OFFSET,
        ASCII_HOOK_SIZE,
    )
    built_hook = _slice(
        slps,
        ASCII_HOOK_FILE_OFFSET,
        ASCII_HOOK_SIZE,
    )
    source_injected = _slice(
        source_slps,
        ASCII_INJECTED_FILE_OFFSET,
        ASCII_INJECTED_SIZE,
    )
    built_injected = _slice(
        slps,
        ASCII_INJECTED_FILE_OFFSET,
        ASCII_INJECTED_SIZE,
    )
    hook_matches_source = built_hook == source_hook
    injected_matches_source = built_injected == source_injected
    if not ascii_findings:
        ascii_status = "not_required_selected_corpus"
    elif hook_matches_source and injected_matches_source:
        ascii_status = "not_adopted_current_build"
    else:
        ascii_status = "changed_requires_separate_contract_verification"

    mapping_analysis = analyze_glyph_code_mapping(
        table,
        extended_entries,
    )
    hard_summary = _finding_summary(findings)
    ascii_summary = _finding_summary(ascii_findings)
    hard_types = Counter(
        finding["finding_type"] for finding in findings
    )
    affected_entry_ids = {
        reference["entry_id"]
        for finding in findings + ascii_findings
        for reference in finding["references"]
    }
    report = {
        "schema_version": 1,
        "status": "failed" if findings else "passed",
        "classification": (
            "Renderer reachability and non-blank glyph checks are hard "
            "requirements. ASCII and overwritten non-blank proposal slots "
            "remain separately classified risks."
        ),
        "scope": {
            "stage_indices": [1, 2, 3, 4, 5],
            "translation_entry_count": entry_count,
            "documents": [
                {
                    "id": name,
                    "entry_count": len(document["entries"]),
                }
                for name, document in documents
            ],
        },
        "inputs": {
            "text_table": str(TEXT_TABLE.relative_to(PROJECT_ROOT)),
            "base_codebook": str(BASE_CODEBOOK.relative_to(PROJECT_ROOT)),
            "proposal": str(PROPOSAL.relative_to(PROJECT_ROOT)),
            "slps": str(slps_path),
            "slps_sha256": sha256_bytes(slps),
            "vt1": str(vt1_path),
            "vt1_sha256": sha256_bytes(vt1),
        },
        "hard_failures": {
            **hard_summary,
            "finding_type_counts": dict(
                sorted(hard_types.items())
            ),
            "affected_characters": [
                finding["character"] for finding in findings
            ],
        },
        "ascii_runtime": {
            "status": ascii_status,
            "hook_file_offset": ASCII_HOOK_FILE_OFFSET,
            "hook_size": ASCII_HOOK_SIZE,
            "hook_matches_source": hook_matches_source,
            "injected_file_offset": ASCII_INJECTED_FILE_OFFSET,
            "injected_size": ASCII_INJECTED_SIZE,
            "injected_window_matches_source": injected_matches_source,
            "injected_window_all_zero": not any(built_injected),
            "literal_ascii": ascii_summary,
            "classification": (
                "Ordinary printable ASCII in the selected corpus uses "
                "explicit two-byte glyph assignments. The executable "
                "therefore does not need the upstream ASCII runtime path; "
                "$n and $F remain protected runtime tokens."
            ),
        },
        "combined_current_impact": {
            "hard_failure_or_ascii_risk_entry_count": len(
                affected_entry_ids
            ),
        },
        "font_provenance": {
            "font_source": json.loads(PROPOSAL.read_text(encoding="utf-8"))[
                "font_source"
            ],
            "proposal_font_glyph_count": len(proposal_assignments),
            "selected_font_han_glyph_count": sum(
                is_cjk_unified_ideograph(assignment["character"])
                for assignment in proposal_assignments
            ),
            "base_codebook_glyph_count": len(base_assignments),
            "entry_counts": dict(sorted(entry_provenance.items())),
            "classification": (
                "Reachable Han glyphs in the selected corpus are redrawn "
                "from one source. Table-only codes that the renderer "
                "cannot resolve are overridden with standard-branch "
                "assignments. Preserved punctuation and kana are outside "
                "the Han-font classification."
            ),
        },
        "proposal_slot_safety": {
            "assignment_count": len(allocation_slot_reports),
            "blank_source_preimage_count": sum(
                report["source_glyph_blank"]
                for report in allocation_slot_reports
            ),
            "nonblank_source_preimage_count": sum(
                not report["source_glyph_blank"]
                for report in allocation_slot_reports
            ),
            "source_preimage_hash_exact_count": sum(
                report["source_preimage_hash_exact"]
                for report in allocation_slot_reports
            ),
            "built_raster_hash_exact_count": sum(
                report["built_raster_hash_exact"]
                for report in allocation_slot_reports
            ),
            "nonblank_source_preimage_assignments": [
                report
                for report in allocation_slot_reports
                if not report["source_glyph_blank"]
            ],
            "classification": (
                "A glyph absent from the pinned table is not proven unused "
                "globally. Overwriting a non-blank source glyph remains a "
                "cross-surface runtime risk."
            ),
        },
        "reraster_existing_han": {
            "assignment_count": len(reraster_slot_reports),
            "source_preimage_hash_exact_count": sum(
                report["source_preimage_hash_exact"]
                for report in reraster_slot_reports
            ),
            "built_raster_hash_exact_count": sum(
                report["built_raster_hash_exact"]
                for report in reraster_slot_reports
            ),
            "classification": (
                "These reachable Han glyphs are deliberately redrawn for "
                "the selected first-five Chinese corpus. Because glyph "
                "slots are global, emulator routing must still check other "
                "surfaces that reuse them."
            ),
        },
        "base_codebook_writeback": {
            "assignment_count": len(base_slot_reports),
            "blank_built_glyph_count": sum(
                report["built_glyph_blank"]
                for report in base_slot_reports
            ),
            "built_effective_raster_hash_exact_count": sum(
                report["built_effective_raster_hash_exact"]
                for report in base_slot_reports
            ),
            "assignments": base_slot_reports,
        },
        "root_cause_breakdown": {
            "encode_only_false_positive_character_count": hard_types[
                "resolver_unreachable"
            ],
            "base_codebook_assignments_omitted_from_font_build_count": sum(
                report["built_glyph_blank"]
                and not report["built_raster_hash_exact"]
                for report in base_slot_reports
            ),
            "post_proposal_unencodable_character_count": hard_types[
                "unencodable"
            ],
            "ascii_runtime_path_not_adopted": (
                ascii_status == "not_adopted_current_build"
            ),
            "mixed_selected_and_original_han_entry_count": entry_provenance[
                "mixed_selected_and_original_han"
            ],
            "classification": (
                "The selected corpus has no remaining encode-versus-render "
                "gap and no ordinary one-byte ASCII. Reachable selected "
                "Han use one font source."
            ),
        },
        "text_table_semantics": _cp932_alignment(table),
        "resolver_inventory": mapping_analysis.to_mapping(),
        "used_glyph_slot_collision_count": len(collisions),
        "used_glyph_slot_collisions": collisions,
        "findings": findings,
        "ascii_findings": ascii_findings,
    }
    return report, findings + ascii_findings


def _write_findings(path: Path, findings: list[dict]) -> None:
    columns = (
        "severity",
        "finding_type",
        "character",
        "unicode",
        "code",
        "mapping_source",
        "glyph_index",
        "occurrence_count",
        "stage_index",
        "document",
        "entry_id",
        "positions",
        "translation",
        "reason",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for finding in findings:
            for reference in finding["references"]:
                writer.writerow(
                    {
                        "severity": finding["severity"],
                        "finding_type": finding["finding_type"],
                        "character": finding["character"],
                        "unicode": finding["unicode"],
                        "code": finding["code"],
                        "mapping_source": finding["mapping_source"],
                        "glyph_index": finding["glyph_index"],
                        "occurrence_count": reference[
                            "occurrence_count"
                        ],
                        "stage_index": reference["stage_index"],
                        "document": reference["document"],
                        "entry_id": reference["entry_id"],
                        "positions": ",".join(
                            str(position)
                            for position in reference["positions"]
                        ),
                        "translation": reference["translation"],
                        "reason": finding["reason"],
                    }
                )


def main() -> int:
    args = parse_args()
    report_path = require_work_output(args.report, WORK_ROOT)
    findings_path = require_work_output(args.findings, WORK_ROOT)
    for path in (report_path, findings_path):
        if path.exists() and not args.force:
            raise SystemExit(f"output exists; use --force: {path}")

    report, findings = audit_first_five_font_coverage(
        slps_path=args.slps,
        vt1_path=args.vt1,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_findings(findings_path, findings)
    print(
        "first-five font coverage:",
        f"status={report['status']}",
        "hard_chars="
        f"{report['hard_failures']['character_count']}",
        "hard_occurrences="
        f"{report['hard_failures']['occurrence_count']}",
        "hard_entries="
        f"{report['hard_failures']['entry_count']}",
        "ascii_risk_entries="
        f"{report['ascii_runtime']['literal_ascii']['entry_count']}",
        "mixed_han_source_entries="
        f"{report['font_provenance']['entry_counts'].get('mixed_selected_and_original_han', 0)}",
    )
    print(f"report: {report_path}")
    print(f"findings: {findings_path}")
    if report["status"] != "passed" and not args.allow_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
