#!/usr/bin/env python3
"""Audit or atomically apply the checked-in Simplified-Chinese layouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

try:
    from audit_stage_keyword_links import load_story_keyword_occurrences
    from build_library_v02_component import reflow_body as current_library_reflow
    from srwz.chinese_layout import (
        FORBIDDEN_LINE_END_CHARACTERS,
        FORBIDDEN_LINE_START_CHARACTERS,
        ChineseLayoutError,
        ChineseLayoutProfile,
        dialogue_line_widths,
        load_layout_profiles,
        load_release_protected_terms,
        logical_dialogue_text,
        reflow_chinese_dialogue,
        reflow_chinese_paragraph,
    )
    from srwz.diagnostics import require_work_output
    from srwz.text import (
        encode_text,
        load_text_table,
        original_fullwidth_ascii_overrides,
    )
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.audit_stage_keyword_links import load_story_keyword_occurrences
    from tools.build_library_v02_component import (
        reflow_body as current_library_reflow,
    )
    from tools.srwz.chinese_layout import (
        FORBIDDEN_LINE_END_CHARACTERS,
        FORBIDDEN_LINE_START_CHARACTERS,
        ChineseLayoutError,
        ChineseLayoutProfile,
        dialogue_line_widths,
        load_layout_profiles,
        load_release_protected_terms,
        logical_dialogue_text,
        reflow_chinese_dialogue,
        reflow_chinese_paragraph,
    )
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.text import (
        encode_text,
        load_text_table,
        original_fullwidth_ascii_overrides,
    )


WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_PROFILES = PROJECT_ROOT / "config/text-layout/zh-layout-profiles.json"
DEFAULT_RELEASE = PROJECT_ROOT / "corpus/releases/v1.json"
DEFAULT_REPORT = WORK_ROOT / "review/zh-text-layout-audit.json"
STORY_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
LIBRARY_CORPUS = PROJECT_ROOT / "corpus/zh/library/v0.2-reviewed.json"
STAGE_OVERVIEWS = PROJECT_ROOT / "corpus/zh/menu/stage-overviews.json"
HSFC_OVERVIEWS = PROJECT_ROOT / "corpus/zh/menu/hsfc-overviews.json"
WORLD_HISTORY_SUMMARY = PROJECT_ROOT / "corpus/zh/summary.json"
WORLD_HISTORY_MAX_PARAGRAPH_WIDTH_SPREAD = 4
TABLE_PATH = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
FONT_ASSIGNMENTS = PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply every validated non-library proposal atomically",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ChineseLayoutError(f"JSON document is not an object: {path}")
    return document


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_protected_terms(release_path: Path) -> tuple[str, ...]:
    return load_release_protected_terms(
        release_path,
        project_root=PROJECT_ROOT,
    )


def edge_violations(text: str) -> list[dict[str, object]]:
    violations = []
    for index, line in enumerate(text.splitlines()):
        content = line.lstrip("　 ")
        if not content:
            continue
        if index and content[0] in FORBIDDEN_LINE_START_CHARACTERS:
            violations.append(
                {
                    "kind": "forbidden_line_start",
                    "line": index + 1,
                    "character": content[0],
                }
            )
        if content[-1] in FORBIDDEN_LINE_END_CHARACTERS:
            violations.append(
                {
                    "kind": "forbidden_line_end",
                    "line": index + 1,
                    "character": content[-1],
                }
            )
    return violations


def layout_violations(
    text: str,
    *,
    profile: ChineseLayoutProfile,
    protected_terms: Iterable[str],
    required_line_count: int | None = None,
    stage_keyword_links: bool = False,
) -> list[dict[str, object]]:
    """Return hard punctuation, width, and line-count violations."""

    violations = edge_violations(text)
    widths = dialogue_line_widths(
        text,
        protected_terms=protected_terms,
        stage_keyword_links=stage_keyword_links,
    )
    for index, width in enumerate(widths):
        limit = (
            profile.first_line_maximum_width
            if index == 0 and profile.first_line_maximum_width is not None
            else profile.maximum_width
        )
        if width > limit:
            violations.append(
                {
                    "kind": "line_too_wide",
                    "line": index + 1,
                    "width": width,
                    "limit": limit,
                }
            )
    if profile.maximum_lines is not None and len(widths) > profile.maximum_lines:
        violations.append(
            {
                "kind": "too_many_lines",
                "line_count": len(widths),
                "limit": profile.maximum_lines,
            }
        )
    if required_line_count is not None and len(widths) != required_line_count:
        violations.append(
            {
                "kind": "wrong_line_count",
                "line_count": len(widths),
                "required": required_line_count,
            }
        )
    return violations


def width_metrics(
    text: str,
    *,
    protected_terms: Iterable[str],
    profile: ChineseLayoutProfile | None = None,
    stage_keyword_links: bool = False,
) -> dict[str, object]:
    widths = dialogue_line_widths(
        text,
        protected_terms=protected_terms,
        stage_keyword_links=stage_keyword_links,
    )
    return {
        "line_widths": list(widths),
        "line_count": len(widths),
        "maximum_width": max(widths, default=0),
        "spread": max(widths, default=0) - min(widths, default=0),
    }


def preferred_offsets(lines: list[str]) -> frozenset[int]:
    offsets = set()
    current = 0
    for index, line in enumerate(lines):
        current += len(line)
        if index < len(lines) - 1:
            offsets.add(current)
    return frozenset(offsets)


def audit_story(
    profile: ChineseLayoutProfile,
    protected_terms: tuple[str, ...],
) -> dict[str, object]:
    entry_count = 0
    changed = []
    failures = []
    existing_violation_count = 0
    proposed_violation_count = 0
    keyword_occurrences = load_story_keyword_occurrences()
    keyword_entry_ids = {row.entry_id for row in keyword_occurrences}
    if len(keyword_occurrences) != 122 or len(keyword_entry_ids) != 111:
        raise ChineseLayoutError(
            "source-bound STAGE keyword-link inventory drift: "
            f"links={len(keyword_occurrences)} entries={len(keyword_entry_ids)}"
        )
    for path in sorted(STORY_ROOT.glob("stage-*.json")):
        document = load_json(path)
        for entry in document["entries"]:
            entry_count += 1
            original = entry["translation"]
            has_keyword_links = entry["id"] in keyword_entry_ids
            before_violations = layout_violations(
                original,
                profile=profile,
                protected_terms=protected_terms,
                stage_keyword_links=has_keyword_links,
            )
            existing_violation_count += len(before_violations)
            try:
                result = reflow_chinese_dialogue(
                    original,
                    protected_terms=protected_terms,
                    profile=profile,
                    stage_keyword_links=has_keyword_links,
                )
            except ChineseLayoutError as error:
                failures.append(
                    {
                        "id": entry["id"],
                        "path": str(path.relative_to(PROJECT_ROOT)),
                        "before": original,
                        "before_metrics": width_metrics(
                            original,
                            protected_terms=protected_terms,
                            profile=profile,
                            stage_keyword_links=has_keyword_links,
                        ),
                        "before_violations": before_violations,
                        "error": str(error),
                    }
                )
                continue
            if logical_dialogue_text(result.text) != logical_dialogue_text(original):
                raise AssertionError(
                    f"story layout changed logical text: {entry['id']}"
                )
            after_violations = layout_violations(
                result.text,
                profile=profile,
                protected_terms=protected_terms,
                stage_keyword_links=has_keyword_links,
            )
            proposed_violation_count += len(after_violations)
            if result.text != original or before_violations or after_violations:
                changed.append(
                    {
                        "id": entry["id"],
                        "path": str(path.relative_to(PROJECT_ROOT)),
                        "before": original,
                        "after": result.text,
                        "before_metrics": width_metrics(
                            original,
                            protected_terms=protected_terms,
                            profile=profile,
                            stage_keyword_links=has_keyword_links,
                        ),
                        "after_metrics": width_metrics(
                            result.text,
                            protected_terms=protected_terms,
                            profile=profile,
                            stage_keyword_links=has_keyword_links,
                        ),
                        "before_violations": before_violations,
                        "after_violations": after_violations,
                        "preserved_reason": result.preserved_reason,
                    }
                )
    return {
        "profile": profile.profile_id,
        "runtime_keyword_link_entry_count": len(keyword_entry_ids),
        "runtime_keyword_link_occurrence_count": len(keyword_occurrences),
        "entry_count": entry_count,
        "changed_entry_count": len(changed),
        "existing_violation_count": existing_violation_count,
        "proposed_violation_count": proposed_violation_count,
        "failure_count": len(failures),
        "failures": failures,
        "changes": changed,
    }


def split_stage_paragraphs(lines: list[str]) -> list[list[str]]:
    paragraphs = []
    current = []
    for line in lines:
        if line.startswith("　") and current:
            paragraphs.append(current)
            current = []
        current.append(line)
    if current:
        paragraphs.append(current)
    return paragraphs


def reflow_preserved_paragraph(
    lines: list[str],
    *,
    profile: ChineseLayoutProfile,
    protected_terms: tuple[str, ...],
    prefer_existing_breaks: bool = True,
) -> list[str]:
    if not any(line.strip("　 ") for line in lines):
        return lines
    indent = "　" if lines[0].startswith("　") else ""
    content_lines = list(lines)
    if indent:
        content_lines[0] = content_lines[0][1:]
    logical = "".join(content_lines)
    result = reflow_chinese_paragraph(
        logical,
        profile=profile,
        protected_terms=protected_terms,
        exact_lines=len(lines),
        preferred_break_offsets=(
            preferred_offsets(content_lines)
            if prefer_existing_breaks
            else frozenset()
        ),
    )
    output = result.text.splitlines()
    if indent:
        output[0] = indent + output[0]
    return output


def audit_world_history_scroll(
    profile: ChineseLayoutProfile,
    protected_terms: tuple[str, ...],
) -> dict[str, object]:
    """Audit MTV_PROS vertical prose while preserving scroll height."""

    document = load_json(WORLD_HISTORY_SUMMARY)
    table, overrides = font_encoder_inputs()
    changes = []
    failures = []
    existing_violation_count = 0
    proposed_violation_count = 0
    maximum_paragraph_line_width_spread = 0
    for entry in document["entries"]:
        original = entry["translation"]
        original_lines = original.splitlines()
        before_violations = layout_violations(
            original,
            profile=profile,
            protected_terms=protected_terms,
        )
        existing_violation_count += len(before_violations)
        try:
            output_lines = []
            for paragraph in split_stage_paragraphs(original_lines):
                output_lines.extend(
                    reflow_preserved_paragraph(
                        paragraph,
                        profile=profile,
                        protected_terms=protected_terms,
                        prefer_existing_breaks=False,
                    )
                )
            proposed = "\n".join(output_lines)
            if proposed.replace("\n", "") != original.replace("\n", ""):
                raise AssertionError(
                    f"world-history scroll changed logical text: {entry['id']}"
                )
            if proposed.count("\n") != original.count("\n"):
                raise AssertionError(
                    f"world-history scroll height drift: {entry['id']}"
                )
            before_encoded = encode_text(
                original,
                table,
                overrides=overrides,
                terminate=True,
            )
            after_encoded = encode_text(
                proposed,
                table,
                overrides=overrides,
                terminate=True,
            )
            if len(after_encoded) != len(before_encoded):
                raise AssertionError(
                    f"world-history encoded size drift: {entry['id']}"
                )
            for paragraph in split_stage_paragraphs(proposed.splitlines()):
                widths = [
                    width
                    for width in dialogue_line_widths(
                        "\n".join(paragraph),
                        protected_terms=(*profile.unbroken_terms, *protected_terms),
                    )
                    if width
                ]
                if len(widths) < 2:
                    continue
                spread = max(widths) - min(widths)
                maximum_paragraph_line_width_spread = max(
                    maximum_paragraph_line_width_spread,
                    spread,
                )
                if spread > WORLD_HISTORY_MAX_PARAGRAPH_WIDTH_SPREAD:
                    raise ChineseLayoutError(
                        "world-history paragraph line-width spread "
                        f"{spread}>{WORLD_HISTORY_MAX_PARAGRAPH_WIDTH_SPREAD}"
                    )
        except (ChineseLayoutError, ValueError) as error:
            failures.append({"id": entry["id"], "error": str(error)})
            continue
        after_violations = layout_violations(
            proposed,
            profile=profile,
            protected_terms=protected_terms,
        )
        proposed_violation_count += len(after_violations)
        if proposed != original or before_violations or after_violations:
            changes.append(
                {
                    "id": entry["id"],
                    "before": original,
                    "after": proposed,
                    "before_metrics": width_metrics(
                        original,
                        protected_terms=protected_terms,
                        profile=profile,
                    ),
                    "after_metrics": width_metrics(
                        proposed,
                        protected_terms=protected_terms,
                        profile=profile,
                    ),
                    "before_violations": before_violations,
                    "after_violations": after_violations,
                    "encoded_size": len(after_encoded),
                    "line_count_preserved": True,
                }
            )
    return {
        "profile": profile.profile_id,
        "entry_count": len(document["entries"]),
        "changed_entry_count": len(changes),
        "existing_violation_count": existing_violation_count,
        "proposed_violation_count": proposed_violation_count,
        "fixed_allocation_encoded_sizes_preserved": True,
        "scroll_line_counts_preserved": True,
        "maximum_paragraph_line_width_spread": (
            maximum_paragraph_line_width_spread
        ),
        "maximum_allowed_paragraph_line_width_spread": (
            WORLD_HISTORY_MAX_PARAGRAPH_WIDTH_SPREAD
        ),
        "failure_count": len(failures),
        "failures": failures,
        "changes": changes,
    }


def audit_stage_overviews(
    profile: ChineseLayoutProfile,
    protected_terms: tuple[str, ...],
) -> dict[str, object]:
    document = load_json(STAGE_OVERVIEWS)
    changes = []
    failures = []
    existing_violation_count = 0
    proposed_violation_count = 0
    for entry in document["entries"]:
        original = entry["translation"]
        trailing_newline = original.endswith("\n")
        original_lines = original.rstrip("\n").splitlines()
        before_violations = layout_violations(
            original.rstrip("\n"),
            profile=profile,
            protected_terms=protected_terms,
        )
        existing_violation_count += len(before_violations)
        try:
            output_lines = []
            for paragraph in split_stage_paragraphs(original_lines):
                output_lines.extend(
                    reflow_preserved_paragraph(
                        paragraph,
                        profile=profile,
                        protected_terms=protected_terms,
                    )
                )
            proposed = "\n".join(output_lines) + ("\n" if trailing_newline else "")
        except ChineseLayoutError as error:
            failures.append({"id": entry["id"], "error": str(error)})
            continue
        if proposed.count("\n") != original.count("\n"):
            raise AssertionError(f"stage overview line-count drift: {entry['id']}")
        after_violations = layout_violations(
            proposed.rstrip("\n"),
            profile=profile,
            protected_terms=protected_terms,
        )
        proposed_violation_count += len(after_violations)
        if proposed != original or before_violations or after_violations:
            changes.append(
                {
                    "id": entry["id"],
                    "before": original,
                    "after": proposed,
                    "before_metrics": width_metrics(
                        original.rstrip("\n"),
                        protected_terms=protected_terms,
                        profile=profile,
                    ),
                    "after_metrics": width_metrics(
                        proposed.rstrip("\n"),
                        protected_terms=protected_terms,
                        profile=profile,
                    ),
                    "before_violations": before_violations,
                    "after_violations": after_violations,
                }
            )
    return {
        "profile": profile.profile_id,
        "entry_count": len(document["entries"]),
        "changed_entry_count": len(changes),
        "existing_violation_count": existing_violation_count,
        "proposed_violation_count": proposed_violation_count,
        "failure_count": len(failures),
        "failures": failures,
        "changes": changes,
    }


def font_encoder_inputs() -> tuple[object, dict[str, int]]:
    table = load_text_table(TABLE_PATH)
    snapshot = load_json(FONT_ASSIGNMENTS)
    overrides = {
        row["character"]: int(row["code"], 16)
        for row in snapshot["primary_assignments"]
    }
    overrides.update(
        {
            row["character"]: int(row["code"], 16)
            for row in snapshot["surface_alias_assignments"]
        }
    )
    overrides.update(original_fullwidth_ascii_overrides(table))
    return table, overrides


def audit_hsfc_overviews(
    profile: ChineseLayoutProfile,
    protected_terms: tuple[str, ...],
) -> dict[str, object]:
    document = load_json(HSFC_OVERVIEWS)
    table, overrides = font_encoder_inputs()
    changes = []
    failures = []
    existing_violation_count = 0
    proposed_violation_count = 0
    minimum_cell_headroom = 50
    for entry in document["entries"]:
        original = entry["translation"]
        original_lines = original.splitlines()
        before_violations = layout_violations(
            original,
            profile=profile,
            protected_terms=protected_terms,
            required_line_count=3,
        )
        existing_violation_count += len(before_violations)
        indent = "　" if original_lines[0].startswith("　") else ""
        content_lines = list(original_lines)
        if indent:
            content_lines[0] = content_lines[0][1:]
        try:
            result = reflow_chinese_paragraph(
                "".join(content_lines),
                profile=profile,
                protected_terms=protected_terms,
                exact_lines=3,
                preferred_break_offsets=preferred_offsets(content_lines),
            )
            output_lines = result.text.splitlines()
            if indent:
                output_lines[0] = indent + output_lines[0]
            for line in output_lines:
                encoded = encode_text(
                    line,
                    table,
                    overrides=overrides,
                    terminate=True,
                )
                if len(encoded) > 50:
                    raise ChineseLayoutError(
                        f"fixed HSFC cell overflow: {len(encoded)}>50"
                    )
                minimum_cell_headroom = min(
                    minimum_cell_headroom,
                    50 - len(encoded),
                )
            proposed = "\n".join(output_lines)
        except (ChineseLayoutError, ValueError) as error:
            failures.append({"id": entry["id"], "error": str(error)})
            continue
        after_violations = layout_violations(
            proposed,
            profile=profile,
            protected_terms=protected_terms,
            required_line_count=3,
        )
        proposed_violation_count += len(after_violations)
        if proposed != original or before_violations or after_violations:
            changes.append(
                {
                    "id": entry["id"],
                    "before": original,
                    "after": proposed,
                    "before_metrics": width_metrics(
                        original,
                        protected_terms=protected_terms,
                        profile=profile,
                    ),
                    "after_metrics": width_metrics(
                        proposed,
                        protected_terms=protected_terms,
                        profile=profile,
                    ),
                    "before_violations": before_violations,
                    "after_violations": after_violations,
                }
            )
    return {
        "profile": profile.profile_id,
        "entry_count": len(document["entries"]),
        "changed_entry_count": len(changes),
        "existing_violation_count": existing_violation_count,
        "proposed_violation_count": proposed_violation_count,
        "minimum_cell_headroom": minimum_cell_headroom,
        "failure_count": len(failures),
        "failures": failures,
        "changes": changes,
    }


def audit_library(
    profiles: dict[str, ChineseLayoutProfile],
    protected_terms: tuple[str, ...],
) -> dict[str, object]:
    document = load_json(LIBRARY_CORPUS)
    domain_profiles = {
        "robot": profiles["library_robot"],
        "character": profiles["library_character"],
        "glossary": profiles["library_glossary"],
    }
    counts = {domain: 0 for domain in domain_profiles}
    changes = []
    failures = []
    existing_violation_count = 0
    proposed_violation_count = 0
    seen = set()
    for entry in document["entries"]:
        if not set(entry.get("tags", ())) & {"DSCR", "DSC2"}:
            continue
        for domain in entry.get("domains", ()):
            if domain not in domain_profiles or (entry["id"], domain) in seen:
                continue
            seen.add((entry["id"], domain))
            counts[domain] += 1
            profile = domain_profiles[domain]
            logical = entry["translation"].replace("\r", "").replace("\n", "")
            try:
                current, current_widths = current_library_reflow(
                    logical,
                    profile.maximum_width,
                    profile=profile,
                    protected_terms=protected_terms,
                )
                proposed_result = reflow_chinese_paragraph(
                    logical,
                    profile=profile,
                    protected_terms=protected_terms,
                )
                proposed = proposed_result.text
            except (ChineseLayoutError, ValueError) as error:
                failures.append(
                    {"id": entry["id"], "domain": domain, "error": str(error)}
                )
                continue
            if proposed.replace("\n", "") != logical:
                raise AssertionError(f"LIBRARY layout changed text: {entry['id']}")
            before_violations = layout_violations(
                current,
                profile=profile,
                protected_terms=protected_terms,
            )
            after_violations = layout_violations(
                proposed,
                profile=profile,
                protected_terms=protected_terms,
            )
            existing_violation_count += len(before_violations)
            proposed_violation_count += len(after_violations)
            if proposed != current or before_violations or after_violations:
                changes.append(
                    {
                        "id": entry["id"],
                        "domain": domain,
                        "before": current,
                        "after": proposed,
                        "before_metrics": {
                            "line_widths": list(current_widths),
                            "line_count": len(current_widths),
                            "maximum_width": max(current_widths, default=0),
                            "spread": (
                                max(current_widths, default=0)
                                - min(current_widths, default=0)
                            ),
                        },
                        "after_metrics": width_metrics(
                            proposed,
                            protected_terms=protected_terms,
                            profile=profile,
                        ),
                        "before_violations": before_violations,
                        "after_violations": after_violations,
                    }
                )
    return {
        "profiles": {
            domain: profile.profile_id for domain, profile in domain_profiles.items()
        },
        "body_field_count_by_domain": counts,
        "changed_field_count": len(changes),
        "existing_violation_count": existing_violation_count,
        "proposed_violation_count": proposed_violation_count,
        "requires_component_capacity_check": True,
        "failure_count": len(failures),
        "failures": failures,
        "changes": changes,
    }


def collect_surfaces(
    profiles: dict[str, ChineseLayoutProfile],
    protected_terms: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    return {
        "story_dialogue": audit_story(
            profiles["story_dialogue"],
            protected_terms,
        ),
        "library": audit_library(profiles, protected_terms),
        "stage_scroll_overview": audit_stage_overviews(
            profiles["stage_scroll_overview"],
            protected_terms,
        ),
        "world_history_scroll": audit_world_history_scroll(
            profiles["world_history_scroll"],
            protected_terms,
        ),
        "scenario_chart_overview": audit_hsfc_overviews(
            profiles["scenario_chart_overview"],
            protected_terms,
        ),
    }


def surface_summary(
    surfaces: dict[str, dict[str, object]],
) -> dict[str, int]:
    return {
        "changed_count": sum(
            int(
                surface.get(
                    "changed_entry_count",
                    surface.get("changed_field_count", 0),
                )
            )
            for surface in surfaces.values()
        ),
        "existing_violation_count": sum(
            int(surface["existing_violation_count"])
            for surface in surfaces.values()
        ),
        "failure_count": sum(
            int(surface["failure_count"]) for surface in surfaces.values()
        ),
        "proposed_violation_count": sum(
            int(surface["proposed_violation_count"])
            for surface in surfaces.values()
        ),
    }


def _write_document(path: Path, document: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    if path.resolve() == HSFC_OVERVIEWS.resolve():
        entries = document.get("entries")
        if not isinstance(entries, list):
            raise ChineseLayoutError("HSFC layout target has no entries")
        metadata = {key: value for key, value in document.items() if key != "entries"}
        prefix = json.dumps(metadata, ensure_ascii=False, indent=2)
        if not prefix.endswith("\n}"):
            raise AssertionError("unexpected HSFC JSON serialization")
        compact_entries = ",\n".join(
            "    "
            + json.dumps(
                entry,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for entry in entries
        )
        serialized = (
            prefix[:-2]
            + ',\n  "entries": [\n'
            + compact_entries
            + "\n  ]\n}\n"
        )
    else:
        serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)


def _apply_document_changes(path: Path, changes: list[dict]) -> int:
    document = load_json(path)
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ChineseLayoutError(f"layout target has no entries: {path}")
    by_id = {
        entry.get("id"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    applied = 0
    for change in changes:
        if change["before"] == change["after"]:
            continue
        entry = by_id.get(change["id"])
        if entry is None or entry.get("translation") != change["before"]:
            raise ChineseLayoutError(
                f"layout apply preimage drift: {change['id']}"
            )
        entry["translation"] = change["after"]
        applied += 1
    if applied:
        _write_document(path, document)
    return applied


def apply_validated_changes(
    surfaces: dict[str, dict[str, object]],
) -> int:
    library_changes = int(surfaces["library"]["changed_field_count"])
    if library_changes:
        raise ChineseLayoutError(
            "LIBRARY production reflow is not using the reviewed layout profiles"
        )

    story_by_path: dict[Path, list[dict]] = {}
    for change in surfaces["story_dialogue"]["changes"]:
        path = (PROJECT_ROOT / change["path"]).resolve()
        story_by_path.setdefault(path, []).append(change)
    applied = sum(
        _apply_document_changes(path, changes)
        for path, changes in sorted(story_by_path.items())
    )
    for surface_name, path in (
        ("stage_scroll_overview", STAGE_OVERVIEWS),
        ("world_history_scroll", WORLD_HISTORY_SUMMARY),
        ("scenario_chart_overview", HSFC_OVERVIEWS),
    ):
        applied += _apply_document_changes(
            path,
            list(surfaces[surface_name]["changes"]),
        )
    return applied


def main() -> int:
    args = parse_args()
    report_path = require_work_output(args.report_output, WORK_ROOT)
    if report_path.exists() and not args.force:
        raise ChineseLayoutError(f"report exists; use --force: {report_path}")
    profile_path = args.profiles.resolve()
    profiles = load_layout_profiles(profile_path)
    required_profiles = {
        "story_dialogue",
        "library_robot",
        "library_character",
        "library_glossary",
        "stage_scroll_overview",
        "world_history_scroll",
        "scenario_chart_overview",
    }
    if set(profiles) != required_profiles:
        raise ChineseLayoutError(f"layout profile inventory drift: {sorted(profiles)}")
    protected_terms = load_protected_terms(args.release.resolve())
    surfaces = collect_surfaces(profiles, protected_terms)
    summary = surface_summary(surfaces)
    if args.apply and (
        summary["failure_count"] or summary["proposed_violation_count"]
    ):
        raise ChineseLayoutError(
            "refusing to apply a layout proposal with failures or violations"
        )
    applied_count = apply_validated_changes(surfaces) if args.apply else 0
    post_apply_summary = None
    if args.apply:
        post_apply_summary = surface_summary(
            collect_surfaces(profiles, protected_terms)
        )
        if any(
            post_apply_summary[key]
            for key in (
                "changed_count",
                "failure_count",
                "proposed_violation_count",
            )
        ):
            raise ChineseLayoutError(
                f"layout apply is not idempotent: {post_apply_summary}"
            )
    report = {
        "schema_version": 1,
        "status": (
            "applied"
            if args.apply
            else (
                "failed"
                if summary["failure_count"]
                or summary["proposed_violation_count"]
                else (
                    "changes_proposed" if summary["changed_count"] else "passed"
                )
            )
        ),
        "mode": "apply" if args.apply else "check_only",
        "corpus_modified": bool(applied_count),
        "applied_change_count": applied_count,
        "profile_source": {
            "path": str(profile_path.relative_to(PROJECT_ROOT)),
            "size": profile_path.stat().st_size,
            "sha256": sha256_file(profile_path),
        },
        "protected_term_count": len(protected_terms),
        "profile_unbroken_term_count": len(profiles["story_dialogue"].unbroken_terms),
        "summary": summary,
        "post_apply_summary": post_apply_summary,
        "surfaces": surfaces,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)
    print(
        "Chinese layout audit: "
        f"status={report['status']} changes={summary['changed_count']} "
        f"applied={applied_count} failures={summary['failure_count']} "
        f"violations={summary['proposed_violation_count']}"
    )
    for name, surface in surfaces.items():
        changed = surface.get(
            "changed_entry_count",
            surface.get("changed_field_count", 0),
        )
        print(
            f"  {name}: changes={changed} failures={surface['failure_count']} "
            f"violations={surface['proposed_violation_count']}"
        )
    print(f"layout report: {report_path}")
    return (
        1
        if summary["failure_count"] or summary["proposed_violation_count"]
        else 0
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, ChineseLayoutError) as error:
        print(f"Chinese layout audit failed: {error}", file=sys.stderr)
        raise SystemExit(1)
