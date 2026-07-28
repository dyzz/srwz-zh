"""Deterministic Chinese layout audit for MTV_PROS world-history text."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

from .chinese_layout import (
    FORBIDDEN_LINE_END_CHARACTERS,
    FORBIDDEN_LINE_START_CHARACTERS,
    partition_chinese_text,
    rendered_line_width,
    tokenize_dialogue,
)
from .codec import decode
from .corpus import text_sha256
from .font import sha256_bytes
from .iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from .summary import SummaryTextEntry, parse_summary
from .text import SrwzTextEncodeError, TextTable, encode_text, load_text_table
from .ui_menu import load_ui_font_overrides


class SummaryLayoutError(ValueError):
    """World-history source, decisions, or layout constraints have drifted."""


_STRONG_BREAK_END = frozenset("。！？!?")
_CLAUSE_BREAK_END = frozenset("，、；：,;:")
_WEAK_BREAK_END = frozenset("…—")
_EDITORIAL_STATUSES = ("todo", "draft", "reviewed", "final")


@dataclass(frozen=True)
class SummarySource:
    chunk_index: int
    entry: SummaryTextEntry


def _project_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise SummaryLayoutError("world-history path must be a non-empty string")
    root = project_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise SummaryLayoutError(
            f"world-history path escapes project: {raw}"
        ) from error
    return path


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SummaryLayoutError(f"cannot load world-history JSON {path}") from error
    if not isinstance(value, dict):
        raise SummaryLayoutError(f"world-history JSON root is not an object: {path}")
    return value


def _object(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise SummaryLayoutError(f"{context} must be an object")
    return value


def _verified_file(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    context: str,
) -> Path:
    path = _project_path(project_root, reference.get("path"))
    payload = path.read_bytes()
    expected_size = reference.get("size")
    if expected_size is not None and len(payload) != expected_size:
        raise SummaryLayoutError(f"{context} size drift")
    if sha256_bytes(payload) != reference.get("sha256"):
        raise SummaryLayoutError(f"{context} SHA-256 drift")
    return path


def _load_sources(
    project_root: Path,
    config: Mapping[str, object],
) -> tuple[tuple[SummarySource, ...], TextTable, dict]:
    source = _object(config.get("source"), context="world-history source")
    slps_path = _verified_file(
        project_root,
        _object(source.get("slps"), context="world-history SLPS"),
        context="world-history SLPS",
    )
    member_path = _verified_file(
        project_root,
        _object(source.get("member"), context="world-history member"),
        context="world-history member",
    )
    table_reference = _object(
        source.get("text_table"),
        context="world-history text table",
    )
    table_path = _verified_file(
        project_root,
        table_reference,
        context="world-history text table",
    )
    table = load_text_table(table_path)

    slps = slps_path.read_bytes()
    member = member_path.read_bytes()
    offsets = read_executable_archive_offsets(
        slps,
        CORE_ARCHIVE_SPECS["MTV_PROS.BIN"],
        len(member),
    )
    sources = []
    chunk_reports = []
    for chunk_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        stream = member[start:end]
        decoded = decode(stream)
        padding = stream[decoded.consumed :]
        if any(padding):
            raise SummaryLayoutError(
                f"MTV_PROS chunk {chunk_index:02d} has nonzero stream padding"
            )
        parsed = parse_summary(
            decoded.output,
            table,
            chunk_index=chunk_index,
        )
        for entry in parsed.entries:
            if entry.unknown_code_count:
                raise SummaryLayoutError(
                    f"{entry.entry_id} contains unknown source text codes"
                )
            sources.append(SummarySource(chunk_index=chunk_index, entry=entry))
        chunk_reports.append(
            {
                "chunk_index": chunk_index,
                "stored_size": len(stream),
                "stored_sha256": sha256_bytes(stream),
                "consumed_size": decoded.consumed,
                "padding_size": len(padding),
                "decoded_size": len(decoded.output),
                "decoded_sha256": sha256_bytes(decoded.output),
                "entry_count": len(parsed.entries),
            }
        )

    root = project_root.resolve()
    context = {
        "slps": {
            "path": str(slps_path.relative_to(root)),
            "size": len(slps),
            "sha256": sha256_bytes(slps),
        },
        "member": {
            "path": str(member_path.relative_to(root)),
            "size": len(member),
            "sha256": sha256_bytes(member),
            "offset_count": len(offsets),
            "offsets_sha256": sha256_bytes(
                b"".join(offset.to_bytes(4, "little") for offset in offsets)
            ),
        },
        "text_table": {
            "path": str(table_path.relative_to(root)),
            "sha256": sha256_bytes(table_path.read_bytes()),
        },
        "chunks": chunk_reports,
    }
    return tuple(sources), table, context


def _load_glossary_terms(
    project_root: Path,
    config: Mapping[str, object],
) -> tuple[dict[str, str], dict]:
    reference = _object(config.get("release"), context="world-history release")
    path = _verified_file(
        project_root,
        reference,
        context="world-history release",
    )
    release = _json_object(path)
    if release.get("release_id") != reference.get("release_id"):
        raise SummaryLayoutError("world-history release ID drift")
    raw_sources = release.get("glossary_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise SummaryLayoutError("world-history release has no glossary sources")
    terms = {}
    reports = []
    for raw in raw_sources:
        glossary_path = _project_path(project_root, raw)
        document = _json_object(glossary_path)
        raw_terms = document.get("terms")
        if not isinstance(raw_terms, list):
            raise SummaryLayoutError(f"glossary has no terms: {glossary_path}")
        source_count = 0
        for term in raw_terms:
            if not isinstance(term, dict):
                raise SummaryLayoutError(f"malformed glossary term: {glossary_path}")
            term_id = term.get("id")
            translation = term.get("translation")
            if not isinstance(term_id, str) or not isinstance(translation, str):
                raise SummaryLayoutError(f"malformed glossary term: {glossary_path}")
            previous = terms.setdefault(term_id, translation)
            if previous != translation:
                raise SummaryLayoutError(f"conflicting glossary term: {term_id}")
            source_count += 1
        reports.append(
            {
                "path": str(glossary_path.relative_to(project_root.resolve())),
                "sha256": sha256_bytes(glossary_path.read_bytes()),
                "term_count": source_count,
            }
        )
    return terms, {
        "path": str(path.relative_to(project_root.resolve())),
        "sha256": sha256_bytes(path.read_bytes()),
        "release_id": release["release_id"],
        "glossary_sources": reports,
    }


def _load_font_context(
    project_root: Path,
    config: Mapping[str, object],
    table: TextTable,
    translations: Sequence[str],
) -> tuple[dict[str, int], dict[str, int], dict]:
    reference = _object(
        config.get("font_candidate"),
        context="world-history font candidate",
    )
    manifest_path = _project_path(project_root, reference.get("manifest"))
    manifest = _json_object(manifest_path)
    if manifest.get("status") != reference.get("required_status"):
        raise SummaryLayoutError("world-history font candidate status drift")
    try:
        overrides, codebook_report = load_ui_font_overrides(
            project_root,
            config,
            manifest,
        )
    except ValueError as error:
        raise SummaryLayoutError(str(error)) from error

    missing = set()
    for text in translations:
        for character in text:
            try:
                encode_text(character, table, overrides=overrides)
            except SrwzTextEncodeError:
                missing.add(character)
    sizing_overrides = dict(overrides)
    used_codes = set(sizing_overrides.values())
    candidate = 0xE000
    for character in sorted(missing):
        while candidate in used_codes:
            candidate += 1
        if candidate > 0xFFFF:
            raise SummaryLayoutError("cannot assign sizing-only text codes")
        sizing_overrides[character] = candidate
        used_codes.add(candidate)
        candidate += 1

    capacity = _object(manifest.get("capacity"), context="UI font capacity")
    remaining = capacity.get("remaining_candidate_slot_count")
    if not isinstance(remaining, int) or remaining < 0:
        raise SummaryLayoutError("UI font remaining capacity is invalid")
    return (
        overrides,
        sizing_overrides,
        {
            "manifest": {
                "path": str(manifest_path.relative_to(project_root.resolve())),
                "sha256": sha256_bytes(manifest_path.read_bytes()),
                "status": manifest["status"],
            },
            "codebook": codebook_report,
            "missing_character_count": len(missing),
            "missing_characters": "".join(sorted(missing)),
            "remaining_safe_candidate_slot_count": remaining,
            "candidate_shortfall": max(0, len(missing) - remaining),
            "sizing_policy": (
                "Missing characters are counted as two-byte codes only for fixed-"
                "allocation feasibility; they are not allocated or written."
            ),
        },
    )


def logical_summary_text(text: str) -> str:
    """Remove authoring line breaks, blank rows, and leading visual indentation."""

    return "".join(
        line.lstrip("　 ") for line in text.splitlines() if line.strip("　 ")
    )


def _preferred_offsets(texts: Sequence[str]) -> frozenset[int]:
    offsets = set()
    cursor = 0
    for text in texts[:-1]:
        cursor += len(logical_summary_text(text))
        offsets.add(cursor)
    return frozenset(offsets)


def _break_penalty(previous: str) -> int:
    last = previous[-1]
    if last in _STRONG_BREAK_END:
        return 0
    if last in _WEAK_BREAK_END:
        return 25
    if last in _CLAUSE_BREAK_END:
        return 40
    return 400


def _valid_break(previous: str, following: str) -> bool:
    return (
        previous[-1] not in FORBIDDEN_LINE_END_CHARACTERS
        and following[0] not in FORBIDDEN_LINE_START_CHARACTERS
    )


def _partition_fixed_group(
    sources: Sequence[SummarySource],
    translations: Sequence[str],
    *,
    table: TextTable,
    sizing_overrides: Mapping[str, int],
    protected_terms: Sequence[str],
    line_width: int,
    indent: str,
) -> tuple[str, ...]:
    logical = "".join(logical_summary_text(text) for text in translations)
    if not logical:
        raise SummaryLayoutError("fixed world-history group is empty")
    tokens = tokenize_dialogue(logical, protected_terms=protected_terms)
    widths = [0]
    encoded_sizes = [0]
    character_offsets = [0]
    for token in tokens:
        widths.append(widths[-1] + token.width)
        encoded_sizes.append(
            encoded_sizes[-1]
            + len(encode_text(token.text, table, overrides=sizing_overrides))
        )
        character_offsets.append(character_offsets[-1] + len(token.text))
    preferred = _preferred_offsets(translations)
    indent_size = len(encode_text(indent, table, overrides=sizing_overrides))

    @lru_cache(maxsize=None)
    def solve(
        start: int,
        line_index: int,
    ) -> tuple[int, int, tuple[tuple[int, int], ...]] | None:
        if line_index == len(sources):
            return (0, 0, ()) if start == len(tokens) else None
        remaining_lines = len(sources) - line_index - 1
        last_end = len(tokens) - remaining_lines
        entry = sources[line_index].entry
        prefix_size = indent_size if line_index == 0 else 0
        terminator_size = 1 if entry.terminator == "nul" else 0
        byte_capacity = entry.allocated_length - prefix_size - terminator_size
        if byte_capacity < 0:
            return None
        best = None
        for end in range(start + 1, last_end + 1):
            width = widths[end] - widths[start]
            size = encoded_sizes[end] - encoded_sizes[start]
            if width > line_width or size > byte_capacity:
                break
            if end < len(tokens) and not _valid_break(
                tokens[end - 1].text,
                tokens[end].text,
            ):
                continue
            tail = solve(end, line_index + 1)
            if tail is None:
                continue
            penalty = 0 if end == len(tokens) else _break_penalty(tokens[end - 1].text)
            raggedness = (line_width - width) ** 2
            moved_authored_boundary = (
                end < len(tokens) and character_offsets[end] not in preferred
            )
            candidate = (
                int(moved_authored_boundary) + tail[0],
                penalty + raggedness + tail[1],
                ((start, end), *tail[2]),
            )
            if best is None or candidate < best:
                best = candidate
        return best

    solution = solve(0, 0)
    if solution is None:
        ids = [source.entry.entry_id for source in sources]
        raise SummaryLayoutError(f"fixed world-history group cannot fit: {ids}")
    output = []
    for line_index, (start, end) in enumerate(solution[2]):
        line = "".join(token.text for token in tokens[start:end])
        if line_index == 0:
            line = indent + line
        output.append(line)
    if logical_summary_text("\n".join(output)) != logical:
        raise AssertionError("fixed world-history group changed logical text")
    return tuple(output)


def _reflow_single_entry(
    source: SummarySource,
    translation: str,
    *,
    protected_terms: Sequence[str],
    line_width: int,
    indent: str,
    blank_line: str,
) -> str:
    output = []
    paragraph_start = True
    source_uses_paragraph_indent = source.entry.text.startswith(indent)
    for authored_line in translation.split("\n"):
        content = authored_line.lstrip("　 ")
        if not content:
            output.append(blank_line)
            paragraph_start = True
            continue
        lines = partition_chinese_text(
            content,
            protected_terms=protected_terms,
            line_width=line_width,
            max_lines=max(
                1, len(tokenize_dialogue(content, protected_terms=protected_terms))
            ),
        )
        if authored_line.startswith(indent) or (
            paragraph_start and source_uses_paragraph_indent
        ):
            lines = (indent + lines[0], *lines[1:])
        output.extend(lines)
        paragraph_start = False
    reflowed = "\n".join(output)
    if logical_summary_text(reflowed) != logical_summary_text(translation):
        raise AssertionError(f"{source.entry.entry_id} reflow changed logical text")
    return reflowed


def _group_chunk_sources(
    sources: Sequence[SummarySource],
    *,
    indent: str,
) -> tuple[tuple[SummarySource, ...], ...]:
    if not sources:
        return ()
    starts = [0]
    starts.extend(
        index
        for index, source in enumerate(sources[1:], start=1)
        if source.entry.text.startswith(indent)
    )
    starts.append(len(sources))
    return tuple(tuple(sources[start:end]) for start, end in zip(starts, starts[1:]))


def _encoded_size(
    text: str,
    source: SummarySource,
    table: TextTable,
    overrides: Mapping[str, int],
) -> int:
    return len(encode_text(text, table, overrides=overrides)) + (
        1 if source.entry.terminator == "nul" else 0
    )


def build_world_history_layout(
    project_root: Path,
    config_path: Path,
) -> tuple[dict, dict, dict]:
    """Return projected corpus, detailed report, and bounded manifest."""

    root = project_root.resolve()
    config_path = config_path.resolve()
    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise SummaryLayoutError("unsupported world-history layout schema")
    layout = _object(config.get("layout"), context="world-history layout")
    line_width = layout.get("line_width")
    indent = layout.get("paragraph_indent")
    blank_line = layout.get("blank_line")
    if (
        not isinstance(line_width, int)
        or line_width <= 0
        or not isinstance(indent, str)
        or not indent
        or not isinstance(blank_line, str)
    ):
        raise SummaryLayoutError("world-history layout settings are invalid")

    sources, table, source_context = _load_sources(root, config)
    translation_reference = _object(
        config.get("translation_source"),
        context="world-history translation source",
    )
    translation_path = _project_path(root, translation_reference.get("path"))
    translation_document = _json_object(translation_path)
    if (
        translation_document.get("batch_id") != translation_reference.get("batch_id")
        or translation_document.get("language") != "zh-Hans"
    ):
        raise SummaryLayoutError("world-history translation metadata drift")
    raw_decisions = translation_document.get("entries")
    if not isinstance(raw_decisions, list) or len(raw_decisions) != (
        translation_reference.get("expected_entry_count")
    ):
        raise SummaryLayoutError("world-history translation count drift")
    decisions = {}
    for raw in raw_decisions:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise SummaryLayoutError("malformed world-history translation")
        if raw["id"] in decisions:
            raise SummaryLayoutError(f"duplicate world-history ID: {raw['id']}")
        if (
            not isinstance(raw.get("translation"), str)
            or not raw["translation"]
            or raw.get("editorial_status") not in _EDITORIAL_STATUSES
            or not isinstance(raw.get("glossary_refs"), list)
        ):
            raise SummaryLayoutError(f"malformed world-history decision: {raw['id']}")
        decisions[raw["id"]] = raw

    source_by_id = {source.entry.entry_id: source for source in sources}
    if set(decisions) != set(source_by_id):
        raise SummaryLayoutError("world-history source/translation IDs differ")
    for entry_id, decision in decisions.items():
        if decision.get("source_text_sha256") != text_sha256(
            source_by_id[entry_id].entry.text
        ):
            raise SummaryLayoutError(f"world-history source hash drift: {entry_id}")

    glossary_terms, release_context = _load_glossary_terms(root, config)
    referenced_ids = {
        term_id
        for decision in decisions.values()
        for term_id in decision["glossary_refs"]
    }
    missing_term_ids = sorted(referenced_ids - set(glossary_terms))
    if missing_term_ids:
        raise SummaryLayoutError(
            f"world-history glossary refs are unknown: {missing_term_ids}"
        )

    _, sizing_overrides, font_context = _load_font_context(
        root,
        config,
        table,
        [decision["translation"] for decision in decisions.values()],
    )
    projected = copy.deepcopy(translation_document)
    projected_by_id = {entry["id"]: entry for entry in projected["entries"]}
    fixed_groups = []
    sources_by_chunk = {}
    for source in sources:
        sources_by_chunk.setdefault(source.chunk_index, []).append(source)

    for chunk_index in sorted(sources_by_chunk):
        for group in _group_chunk_sources(
            sources_by_chunk[chunk_index],
            indent=indent,
        ):
            group_decisions = [decisions[source.entry.entry_id] for source in group]
            protected_terms = tuple(
                sorted(
                    {
                        glossary_terms[term_id]
                        for decision in group_decisions
                        for term_id in decision["glossary_refs"]
                        if len(glossary_terms[term_id]) > 1
                    },
                    key=lambda term: (-len(term), term),
                )
            )
            if len(group) == 1:
                output = (
                    _reflow_single_entry(
                        group[0],
                        group_decisions[0]["translation"],
                        protected_terms=protected_terms,
                        line_width=line_width,
                        indent=indent,
                        blank_line=blank_line,
                    ),
                )
            else:
                output = _partition_fixed_group(
                    group,
                    [decision["translation"] for decision in group_decisions],
                    table=table,
                    sizing_overrides=sizing_overrides,
                    protected_terms=protected_terms,
                    line_width=line_width,
                    indent=indent,
                )
                fixed_groups.append(
                    {
                        "chunk_index": chunk_index,
                        "entry_ids": [source.entry.entry_id for source in group],
                        "logical_text_sha256": text_sha256(
                            "".join(
                                logical_summary_text(decision["translation"])
                                for decision in group_decisions
                            )
                        ),
                    }
                )
            for source, text in zip(group, output):
                projected_by_id[source.entry.entry_id]["translation"] = text

    changed_ids = [
        entry_id
        for entry_id in sorted(decisions)
        if decisions[entry_id]["translation"]
        != projected_by_id[entry_id]["translation"]
    ]
    allocation_entries = []
    overflow_ids = []
    line_count = 0
    maximum_width = 0
    output_blank_lines = 0
    for source in sources:
        decision = projected_by_id[source.entry.entry_id]
        text = decision["translation"]
        size = _encoded_size(text, source, table, sizing_overrides)
        margin = source.entry.allocated_length - size
        if margin < 0:
            overflow_ids.append(source.entry.entry_id)
        widths = tuple(
            rendered_line_width(
                line,
                protected_terms=(
                    glossary_terms[term_id] for term_id in decision["glossary_refs"]
                ),
            )
            for line in text.splitlines()
        )
        if max(widths, default=0) > line_width:
            raise SummaryLayoutError(
                f"{source.entry.entry_id} exceeds world-history line width"
            )
        line_count += len(widths)
        maximum_width = max(maximum_width, max(widths, default=0))
        output_blank_lines += sum(not line.strip("　 ") for line in text.splitlines())
        allocation_entries.append(
            {
                "id": source.entry.entry_id,
                "chunk_index": source.chunk_index,
                "ordinal": source.entry.ordinal,
                "allocated_length": source.entry.allocated_length,
                "terminator": source.entry.terminator,
                "output_encoded_size": size,
                "margin": margin,
                "line_count": len(widths),
                "maximum_line_width": max(widths, default=0),
                "translation_sha256": text_sha256(text),
            }
        )
    if overflow_ids:
        raise SummaryLayoutError(
            f"world-history fixed allocations overflow: {overflow_ids}"
        )

    source_blank_lines = sum(
        sum(not line.strip("　 ") for line in source.entry.text.splitlines())
        for source in sources
    )
    editorial_counts = {
        status: sum(
            decision["editorial_status"] == status
            for decision in projected_by_id.values()
        )
        for status in _EDITORIAL_STATUSES
    }
    allocation_signature = sha256_bytes(
        json.dumps(
            allocation_entries,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    ratchet = _object(config.get("ratchet"), context="world-history ratchet")
    actual_ratchet = {
        "entry_count": len(sources),
        "text_chunk_count": sum(bool(items) for items in sources_by_chunk.values()),
        "source_blank_line_count": source_blank_lines,
        "output_blank_line_count": output_blank_lines,
        "maximum_line_width": maximum_width,
        "fixed_allocation_overflow_count": len(overflow_ids),
        "editorial_draft_entry_count": editorial_counts["draft"],
        "font_missing_character_count": font_context["missing_character_count"],
        "remaining_safe_candidate_slot_count": font_context[
            "remaining_safe_candidate_slot_count"
        ],
        "font_candidate_shortfall": font_context["candidate_shortfall"],
    }
    ratchet_checks = {
        key: actual_ratchet.get(key) == expected for key, expected in ratchet.items()
    }
    if not all(ratchet_checks.values()):
        raise SummaryLayoutError(
            f"world-history layout ratchet failed: {ratchet_checks}"
        )

    projected_payload = (
        json.dumps(projected, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    common = {
        "schema_version": 1,
        "status": (
            "changes_required"
            if changed_ids
            else "layout_validated_editorial_font_runtime_pending"
        ),
        "layout_id": config["layout_id"],
        "scope": config["scope"],
        "inputs": {
            "config": {
                "path": str(config_path.relative_to(root)),
                "sha256": sha256_bytes(config_path.read_bytes()),
            },
            "source": source_context,
            "translation_source": {
                "path": str(translation_path.relative_to(root)),
                "current_sha256": sha256_bytes(translation_path.read_bytes()),
                "projected_sha256": sha256_bytes(projected_payload),
                "batch_id": translation_document["batch_id"],
            },
            "release": release_context,
            "font": font_context,
        },
        "selection": {
            "entry_count": len(sources),
            "text_chunk_count": actual_ratchet["text_chunk_count"],
            "source_entry_signature_sha256": sha256_bytes(
                json.dumps(
                    [
                        {
                            "id": source.entry.entry_id,
                            "chunk_index": source.chunk_index,
                            "ordinal": source.entry.ordinal,
                            "text_offset": source.entry.text_offset,
                            "allocated_length": source.entry.allocated_length,
                            "terminator": source.entry.terminator,
                            "source_text_sha256": text_sha256(source.entry.text),
                        }
                        for source in sources
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
        },
        "layout": {
            "line_width": line_width,
            "output_line_count": line_count,
            "maximum_line_width": maximum_width,
            "source_blank_line_count": source_blank_lines,
            "output_blank_line_count": output_blank_lines,
            "noncanonical_entry_count": len(changed_ids),
            "fixed_line_group_count": len(fixed_groups),
            "fixed_line_group_entry_count": sum(
                len(group["entry_ids"]) for group in fixed_groups
            ),
            "logical_text_preserved": True,
        },
        "allocation": {
            "overflow_count": len(overflow_ids),
            "minimum_margin": min(entry["margin"] for entry in allocation_entries),
            "maximum_margin": max(entry["margin"] for entry in allocation_entries),
            "entry_signature_sha256": allocation_signature,
        },
        "editorial": {
            "status_counts": editorial_counts,
            "ready_for_production": (
                editorial_counts["todo"] == 0 and editorial_counts["draft"] == 0
            ),
        },
        "font_capacity": {
            "missing_character_count": font_context["missing_character_count"],
            "missing_characters": font_context["missing_characters"],
            "remaining_safe_candidate_slot_count": font_context[
                "remaining_safe_candidate_slot_count"
            ],
            "candidate_shortfall": font_context["candidate_shortfall"],
            "ready_for_component": font_context["candidate_shortfall"] == 0,
        },
        "ratchet": {
            "expected": ratchet,
            "actual": actual_ratchet,
            "checks": ratchet_checks,
            "passed": True,
        },
        "runtime": {
            "status": "not_tested",
            "reason": (
                "No full Chinese world-history font/component/ISO exists; "
                "scroll start, middle and end are not runtime-verified."
            ),
        },
    }
    report = {
        **common,
        "changes": [
            {
                "id": entry_id,
                "before": decisions[entry_id]["translation"],
                "after": projected_by_id[entry_id]["translation"],
            }
            for entry_id in changed_ids
        ],
        "fixed_line_groups": fixed_groups,
        "allocation_entries": allocation_entries,
    }
    manifest = copy.deepcopy(common)
    return projected, report, manifest


__all__ = [
    "SummaryLayoutError",
    "build_world_history_layout",
    "logical_summary_text",
]
