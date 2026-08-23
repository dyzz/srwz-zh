#!/usr/bin/env python3
"""Build the offline SRWZ route and hidden-element guide from local data.

The generated HTML is deliberately self-contained.  Route titles, stage
conditions, script provenance and terminology are all resolved from files in
this repository; the browser never needs to fetch JSON, JavaScript or fonts.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.archive import load_offset_layout, slice_archive, verify_archive  # noqa: E402
from srwz.codec import decode_production  # noqa: E402
from srwz.display_names import load_display_name_source  # noqa: E402
from srwz.stage import parse_stage, read_stage_function_addresses  # noqa: E402
from srwz.text import load_text_table  # noqa: E402


ROUTE_MAP = PROJECT_ROOT / "docs/STAGE_ROUTE_MAP.md"
STAGE_NAMES = PROJECT_ROOT / "corpus/zh/menu/stage-names.json"
STAGE_CONDITIONS = PROJECT_ROOT / "corpus/zh/story-conditions.json"
REMAINING_UI = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
UNCLASSIFIED_UI = PROJECT_ROOT / "corpus/zh/menu/unclassified.json"
PILOT_SKILLS_UI = PROJECT_ROOT / "corpus/zh/menu/system-ui-skills.json"
MECH_ABILITIES_UI = PROJECT_ROOT / "corpus/zh/menu/system-ui-special-abilities.json"
LEADERSHIP_UI = PROJECT_ROOT / "corpus/zh/menu/system-ui-leadership.json"
PARTS_UI = PROJECT_ROOT / "corpus/zh/menu/system-ui-parts.json"
HIDDEN_ELEMENTS = PROJECT_ROOT / "guide/data/hidden-elements.json"
PROGRESSION = PROJECT_ROOT / "guide/data/progression.json"
REFERENCE = PROJECT_ROOT / "guide/data/reference.json"
STAGE_LAYOUT = PROJECT_ROOT / "config/stage-offsets.json"
DISPLAY_NAME_CONFIG = PROJECT_ROOT / "config/display-names/compdata.json"
COMPDATA = PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN"
STAGE_ARCHIVE = PROJECT_ROOT / "work/disc/DATA/STAGE.BIN"
SLPS = PROJECT_ROOT / "work/disc/SLPS_258.87"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "guide/srwz-z-flow-guide.html"
DEFAULT_MANIFEST = PROJECT_ROOT / "guide/stage-guide-manifest.json"

TITLE_RE = re.compile(r"\[(\d{3})\]\s*(.*?)（日：(.*?)）")
RESOURCE_RE = re.compile(rb"stg_(\d{3})([a-z]?)\.bin", re.IGNORECASE)
TERM_RE = re.compile(r"\{\{([^{}]+)\}\}")


class GuideBuildError(ValueError):
    """Raised when source data no longer satisfies the guide contract."""


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GuideBuildError(f"JSON root must be an object: {path}")
    return value


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_route_map(path: Path = ROUTE_MAP) -> list[dict[str, Any]]:
    """Parse the checked-in route table and retain its multi-lane structure."""

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    headers: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 非章节"):
            break
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "rows": []}
            sections.append(current)
            headers = None
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = _table_cells(line)
        if cells and cells[0] == "话数":
            headers = cells
            current["headers"] = headers
            continue
        if not headers or not cells or not cells[0].isdigit():
            continue
        stage_number = int(cells[0])
        row: dict[str, Any] = {"stage": stage_number, "cells": []}
        for index, cell in enumerate(cells[1:], start=1):
            matches = list(TITLE_RE.finditer(cell))
            if not matches:
                continue
            lane = headers[index] if index < len(headers) else "路线"
            if lane == "标题":
                lane = "共通"
            if lane == "说明":
                continue
            if headers[-1] == "标题" and len(cells) >= 3:
                lane = cells[1]
            for match in matches:
                row["cells"].append(
                    {
                        "lane": lane,
                        "ordinal": int(match.group(1)),
                        "title": match.group(2).strip("` "),
                        "source_title": match.group(3).strip("` "),
                    }
                )
        # Common rows repeat the same title in both protagonist/route columns.
        unique: list[dict[str, Any]] = []
        seen: set[int] = set()
        for cell in row["cells"]:
            if cell["ordinal"] in seen:
                continue
            seen.add(cell["ordinal"])
            unique.append(cell)
        if len(unique) == 1 and len(row["cells"]) > 1:
            unique[0]["lane"] = "共通"
        row["cells"] = unique
        if unique:
            current["rows"].append(row)

    sections = [section for section in sections if section["rows"]]
    ordinals = {
        cell["ordinal"]
        for section in sections
        for row in section["rows"]
        for cell in row["cells"]
    }
    if ordinals != set(range(107)):
        missing = sorted(set(range(107)) - ordinals)
        extra = sorted(ordinals - set(range(107)))
        raise GuideBuildError(
            f"route map playable-title drift: missing={missing}, extra={extra}"
        )
    return sections


def _load_stage_titles() -> dict[int, dict[str, Any]]:
    entries = _json(STAGE_NAMES).get("entries")
    if not isinstance(entries, list) or len(entries) != 122:
        raise GuideBuildError("stage-name corpus must contain 122 entries")
    result: dict[int, dict[str, Any]] = {}
    for entry in entries:
        ordinal = int(str(entry["id"]).rsplit("/", 1)[-1])
        result[ordinal] = entry
    return result


def _load_terms() -> tuple[dict[str, str], dict[str, str]]:
    translations: dict[str, str] = {}
    sources: dict[str, str] = {}
    for path in sorted((PROJECT_ROOT / "corpus/glossary").glob("*.json")):
        document = _json(path)
        terms = document.get("terms", [])
        if not isinstance(terms, list):
            continue
        for term in terms:
            term_id = term.get("id")
            translation = term.get("translation")
            if not isinstance(term_id, str) or not isinstance(translation, str):
                continue
            if term_id in translations and translations[term_id] != translation:
                # Some narrow glossaries intentionally shadow broader drafts.
                # Prefer an approved entry; otherwise keep deterministic order.
                if term.get("status") == "approved":
                    translations[term_id] = translation
            else:
                translations[term_id] = translation
            sources.setdefault(term_id, path.relative_to(PROJECT_ROOT).as_posix())

    display_path = PROJECT_ROOT / "corpus/zh/display-names/units-full.json"
    display = _json(display_path)
    for segment in display.get("segments", []):
        start, end = segment["range"]
        values = segment["translations"]
        if len(values) != end - start + 1:
            raise GuideBuildError("unit display-name segment length drift")
        for index, translation in enumerate(values, start):
            term_id = f"display-name/unit/{index:04d}/name"
            translations[term_id] = translation
            sources[term_id] = display_path.relative_to(PROJECT_ROOT).as_posix()
    return translations, sources


def _load_term_source_surfaces() -> dict[str, list[str]]:
    """Load original Japanese surfaces used to cross-check Timeline items."""

    surfaces: dict[str, list[str]] = {}
    for path in sorted((PROJECT_ROOT / "corpus/glossary").glob("*.json")):
        for term in _json(path).get("terms", []):
            term_id = term.get("id")
            source_terms = term.get("source_terms", [])
            if not isinstance(term_id, str) or not isinstance(source_terms, list):
                continue
            values = [value for value in source_terms if isinstance(value, str) and value]
            if values:
                surfaces.setdefault(term_id, []).extend(values)

    _, _, parsed, _ = load_display_name_source(PROJECT_ROOT, DISPLAY_NAME_CONFIG)
    for entry in parsed.unit_entries:
        surfaces[entry.entry_id] = [entry.text]
    return {
        term_id: list(dict.fromkeys(values))
        for term_id, values in surfaces.items()
    }


def _expand_terms(value: str, terms: dict[str, str], used: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        term_id = match.group(1)
        if term_id not in terms:
            raise GuideBuildError(f"unknown global term reference: {term_id}")
        used.add(term_id)
        return terms[term_id]

    return TERM_RE.sub(replace, value)


def _expand_hidden_terms(
    document: dict[str, Any], terms: dict[str, str]
) -> tuple[list[dict[str, Any]], set[str]]:
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        raise GuideBuildError("hidden-element data must contain entries")
    used: set[str] = set()

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return _expand_terms(value, terms, used)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    expanded = walk(entries)
    ids = [entry.get("id") for entry in expanded]
    if len(ids) != len(set(ids)) or not all(isinstance(item, str) for item in ids):
        raise GuideBuildError("hidden-element ids must be unique strings")
    return expanded, used


def _expand_progression_terms(
    document: dict[str, Any], terms: dict[str, str]
) -> tuple[list[dict[str, Any]], set[str]]:
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        raise GuideBuildError("progression data must contain entries")
    used: set[str] = set()

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return _expand_terms(value, terms, used)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    expanded = walk(entries)
    timeline_fields = (
        "acquisitions",
        "temporary",
        "availability",
        "upgrades",
        "akurasu_corrections",
    )
    for raw_entry, expanded_entry in zip(entries, expanded):
        expanded_entry["_term_refs"] = {
            field: [TERM_RE.findall(value) for value in raw_entry.get(field, [])]
            for field in timeline_fields
        }
    return expanded, used


def _expand_reference_terms(
    document: dict[str, Any], terms: dict[str, str]
) -> tuple[dict[str, Any], set[str]]:
    used: set[str] = set()

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return _expand_terms(value, terms, used)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return walk(document), used


LEADERSHIP_GROUP_SIZES = (1, 3, 1, 1, 3, 4, 3, 20, 6, 4, 4, 1, 2, 2, 4)
PILOT_SKILL_EFFECT_INDEX = {
    **{index: index + 1 for index in range(2, 62, 2)},
    62: 63,   # ESP
    64: 65,   # Newtype
    66: 65,   # Cyber-Newtype shares the Newtype explanation.
    67: 63,   # Newtype (X) shares the ESP explanation.
    68: 65,   # Artificial Newtype shares the Newtype explanation.
    69: 70,   # Category F
    71: 72,   # SEED has its own non-levelled effect.
    73: 70,   # Extended shares the Category F explanation.
    74: 75,   # Lifting
    76: 77,   # Oversense
    78: 79,   # Gamer
    80: 81,   # Game Champ
    82: 83,   # Negotiator
    84: 85,   # Double Action
    86: 87,   # Very Lucky
}
MECH_ABILITY_DESCRIPTION_INDEX = {
    0: 46, 1: 47, 2: 48, 3: 49, 4: 50, 5: 51, 6: 52, 7: 53,
    8: 54, 9: 54, 10: 55, 11: 56, 12: 57, 13: 58, 14: 58,
    15: 59, 16: 60, 17: 61, 18: 62, 19: 63, 20: 63, 21: 64,
    22: 65, 23: 66, 24: 67, 25: 68, 26: 69, 27: 70, 28: 71,
    29: 72, 30: 73, 31: 74, 32: 75, 33: 76, 35: 83, 36: 83,
    37: 84, 38: 85, 39: 77, 40: 78, 41: 79, 42: 80, 43: 81,
    44: 82, 45: 67,
}


def _load_reference_catalogs(reference: dict[str, Any]) -> dict[str, Any]:
    """Build player reference tables from reviewed original-game UI text."""

    skill_entries = _json(PILOT_SKILLS_UI).get("entries", [])
    if len(skill_entries) != 88:
        raise GuideBuildError("pilot-skill UI count drift")
    rare_pilot_entries = reference.get("rare_pilot_skills", [])
    rare_pilot_skills = {
        item["name"]: item["holders"]
        for item in rare_pilot_entries
    }
    if len(rare_pilot_skills) != len(rare_pilot_entries):
        raise GuideBuildError("duplicate rare pilot-skill annotation")
    if any(not holders for holders in rare_pilot_skills.values()):
        raise GuideBuildError("rare pilot-skill annotation has no holder")
    level_entries = reference.get("pilot_skill_levels", [])
    skill_levels = {item["name"]: item for item in level_entries}
    if len(skill_levels) != len(level_entries):
        raise GuideBuildError("duplicate pilot-skill level table")
    for name, detail in skill_levels.items():
        columns = detail.get("columns", [])
        rows = detail.get("rows", [])
        if len(columns) < 2 or not rows:
            raise GuideBuildError(f"empty pilot-skill level table: {name}")
        if any(len(row) != len(columns) for row in rows):
            raise GuideBuildError(f"pilot-skill level row width drift: {name}")
    note_entries = reference.get("pilot_skill_notes", [])
    skill_notes = {item["name"]: item for item in note_entries}
    if len(skill_notes) != len(note_entries):
        raise GuideBuildError("duplicate pilot-skill note")
    if any(not item.get("label") or not item.get("text") for item in note_entries):
        raise GuideBuildError("empty pilot-skill note")
    pilot_skills = [
        {
            "name": skill_entries[index]["translation"],
            "effect": skill_entries[effect_index]["translation"],
            "holders": rare_pilot_skills.get(
                skill_entries[index]["translation"], []
            ),
            "level_detail": skill_levels.get(
                skill_entries[index]["translation"]
            ),
            "note": skill_notes.get(skill_entries[index]["translation"]),
        }
        for index, effect_index in PILOT_SKILL_EFFECT_INDEX.items()
    ]
    skill_names = {item["name"] for item in pilot_skills}
    if unknown := sorted(set(rare_pilot_skills) - skill_names):
        raise GuideBuildError(f"rare pilot skills are not in game UI: {unknown}")
    if unknown := sorted(set(skill_levels) - skill_names):
        raise GuideBuildError(f"levelled pilot skills are not in game UI: {unknown}")
    if unknown := sorted(set(skill_notes) - skill_names):
        raise GuideBuildError(f"pilot-skill notes are not in game UI: {unknown}")
    levelled_skill_names = {
        item["name"] for item in pilot_skills if "技能等级" in item["effect"]
    }
    if set(skill_levels) != levelled_skill_names:
        missing = sorted(levelled_skill_names - set(skill_levels))
        extra = sorted(set(skill_levels) - levelled_skill_names)
        raise GuideBuildError(
            f"pilot-skill level table coverage drift: missing={missing}, extra={extra}"
        )
    seed = next(item for item in pilot_skills if item["name"] == "SEED")
    extended = next(item for item in pilot_skills if item["name"] == "扩展人")
    if "技能等级" in seed["effect"] or "1.1倍" not in seed["effect"]:
        raise GuideBuildError("SEED effect mapping drift")
    if "技能等级" not in extended["effect"] or "暴击率" not in extended["effect"]:
        raise GuideBuildError("Extended effect mapping drift")

    leadership_labels = [
        entry["translation"] for entry in _json(LEADERSHIP_UI).get("entries", [])
    ]
    leadership_effects = list(
        _json(REMAINING_UI).get("leadership_effect_by_offset", {}).values()
    )
    if len(leadership_labels) != len(LEADERSHIP_GROUP_SIZES):
        raise GuideBuildError("leadership category count drift")
    if len(leadership_effects) != sum(LEADERSHIP_GROUP_SIZES):
        raise GuideBuildError("leadership effect count drift")
    leadership_groups = []
    rare_leadership_entries = reference.get("rare_leadership_effects", [])
    rare_leadership = {
        item["effect"]: item["holders"]
        for item in rare_leadership_entries
    }
    if len(rare_leadership) != len(rare_leadership_entries):
        raise GuideBuildError("duplicate rare leadership annotation")
    if any(not holders for holders in rare_leadership.values()):
        raise GuideBuildError("rare leadership annotation has no holder")
    if unknown := sorted(set(rare_leadership) - set(leadership_effects)):
        raise GuideBuildError(f"rare leadership effects are not in game UI: {unknown}")
    cursor = 0
    for label, size in zip(leadership_labels, LEADERSHIP_GROUP_SIZES):
        effects = leadership_effects[cursor : cursor + size]
        leadership_groups.append(
            {
                "label": label,
                "effects": [
                    {
                        "effect": effect,
                        "holders": rare_leadership.get(effect, []),
                    }
                    for effect in effects
                ],
            }
        )
        cursor += size

    mech_entries = _json(MECH_ABILITIES_UI).get("entries", [])
    if len(mech_entries) != 158:
        raise GuideBuildError("mech-ability UI count drift")
    mech_abilities = []
    for name_index, description_index in MECH_ABILITY_DESCRIPTION_INDEX.items():
        name = mech_entries[name_index]["translation"]
        effect = mech_entries[description_index]["translation"]
        if not name or not effect:
            raise GuideBuildError(
                f"empty mech-ability pair: {name_index}/{description_index}"
            )
        mech_abilities.append({"name": name, "effect": effect})

    part_entries = _json(PARTS_UI).get("entries", [])
    if len(part_entries) != 133:
        raise GuideBuildError("part UI count drift")
    part_effects = {
        part_entries[index]["translation"]: part_entries[index + 1]["translation"]
        for index in range(0, 130, 2)
    }
    bazaar_parts = []
    for item in reference.get("bazaar_parts", []):
        name = item.get("name")
        if name not in part_effects:
            raise GuideBuildError(f"bazaar part missing game effect: {name}")
        bazaar_parts.append({**item, "effect": part_effects[name]})

    return {
        "pilot_skills": pilot_skills,
        "pilot_skill_notices": reference.get("pilot_skill_akurasu_issues", []),
        "leadership_groups": leadership_groups,
        "leadership_notices": reference.get("leadership_akurasu_issues", []),
        "mech_abilities": mech_abilities,
        "bazaar_parts": bazaar_parts,
    }


def _condition_translations() -> dict[str, str]:
    document = _json(STAGE_CONDITIONS)
    result = {}
    for entry in document.get("entries", []):
        if entry.get("translation_action") == "preserve":
            translation = entry.get("translation", "")
        else:
            translation = entry.get("translation", "")
        if not isinstance(translation, str) or not translation:
            raise GuideBuildError(f"empty condition translation: {entry.get('id')}")
        result[entry["id"]] = translation
    return result


def parse_stage_resources() -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    """Decode the original STAGE archive and build reproducible resource facts."""

    layout = load_offset_layout(STAGE_LAYOUT)
    verify_archive(STAGE_ARCHIVE, layout)
    archive = STAGE_ARCHIVE.read_bytes()
    executable = SLPS.read_bytes()
    functions = read_stage_function_addresses(executable)
    table = load_text_table(TEXT_TABLE)
    conditions = _condition_translations()
    resources: dict[int, list[dict[str, Any]]] = defaultdict(list)
    parsed_condition_ids: set[str] = set()

    for stage_index, chunk in enumerate(slice_archive(archive, layout)):
        decoded = decode_production(chunk).output
        match = RESOURCE_RE.search(decoded[:0x200])
        if match is None:
            continue
        resource_number = int(match.group(1))
        suffix = match.group(2).decode("ascii").lower()
        resource_name = f"stg_{resource_number:03d}{suffix}.bin"
        parsed = parse_stage(
            decoded,
            table,
            stage_index=stage_index,
            function_address=functions[stage_index],
        )
        translated_conditions = []
        for entry in parsed.entries:
            if entry.kind != "condition":
                continue
            if entry.entry_id not in conditions:
                raise GuideBuildError(
                    f"condition has no Chinese corpus entry: {entry.entry_id}"
                )
            parsed_condition_ids.add(entry.entry_id)
            translated_conditions.append(
                {
                    "id": entry.entry_id,
                    "kind": {
                        "_Victory Conditions": "胜利条件",
                        "_Defeat Condtions": "失败条件",
                        "_SR Conditions": "SR点数条件",
                    }.get(entry.section, entry.section),
                    "text": conditions[entry.entry_id],
                    "pointer_offset": entry.pointer_offset,
                    "text_offset": entry.text_offset,
                }
            )
        resources[resource_number].append(
            {
                "archive_index": stage_index,
                "resource_name": resource_name,
                "function_address": f"0x{functions[stage_index]:08X}",
                "stored_size": len(chunk),
                "decoded_size": len(decoded),
                "stored_sha256": _sha256_bytes(chunk),
                "decoded_sha256": _sha256_bytes(decoded),
                "dialogue_count": parsed.dialogue_count,
                "speaker_count": parsed.speaker_count,
                "_script_text": "\n".join(
                    entry.text
                    for entry in parsed.entries
                    if entry.kind in {"speaker", "dialogue"}
                ),
                "conditions": translated_conditions,
            }
        )

    missing = sorted(set(range(1, 108)) - set(resources))
    if missing:
        raise GuideBuildError(f"playable STAGE resources missing: {missing}")
    for values in resources.values():
        values.sort(key=lambda item: item["archive_index"])
    report = {
        "archive_chunk_count": layout.chunk_count,
        "named_resource_count": sum(len(value) for value in resources.values()),
        "playable_resource_number_count": 107,
        "playable_chunk_count": sum(
            len(resources[number]) for number in range(1, 108)
        ),
        "parsed_condition_count": len(parsed_condition_ids),
        "corpus_condition_count": len(conditions),
    }
    return dict(resources), report


def _stage_catalog(
    sections: list[dict[str, Any]],
    resources: dict[int, list[dict[str, Any]]],
) -> dict[int, dict[str, Any]]:
    titles = _load_stage_titles()
    catalog: dict[int, dict[str, Any]] = {}
    for section in sections:
        for row in section["rows"]:
            for cell in row["cells"]:
                ordinal = cell["ordinal"]
                corpus = titles[ordinal]
                if corpus["translation"] != cell["title"]:
                    raise GuideBuildError(
                        f"route-map/corpus title drift at ordinal {ordinal}: "
                        f"{cell['title']!r} != {corpus['translation']!r}"
                    )
                record = {
                    **cell,
                    "stage": row["stage"],
                    "section": section["title"],
                    "resource_number": ordinal + 1,
                    "resources": resources[ordinal + 1],
                    "editorial_status": corpus.get("editorial_status"),
                }
                if ordinal in catalog and catalog[ordinal] != record:
                    raise GuideBuildError(f"ordinal {ordinal} maps to multiple stages")
                catalog[ordinal] = record
    return catalog


def _attach_hidden(
    hidden_entries: list[dict[str, Any]], catalog: dict[int, dict[str, Any]]
) -> dict[int, list[dict[str, str]]]:
    attached: dict[int, list[dict[str, str]]] = defaultdict(list)
    for entry in hidden_entries:
        steps = entry.get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise GuideBuildError(f"hidden entry has no steps: {entry['id']}")
        for step_index, step in enumerate(steps, start=1):
            stage = step.get("stage")
            if stage is None:
                continue
            if not isinstance(stage, int) or not 1 <= stage <= 60:
                raise GuideBuildError(f"invalid hidden stage: {entry['id']} step {step_index}")
            ordinals = step.get("ordinals")
            if ordinals is None:
                ordinals = [
                    ordinal
                    for ordinal, record in catalog.items()
                    if record["stage"] == stage
                ]
            if not isinstance(ordinals, list) or not ordinals:
                raise GuideBuildError(
                    f"hidden step has no stage target: {entry['id']} step {step_index}"
                )
            for ordinal in ordinals:
                if ordinal not in catalog or catalog[ordinal]["stage"] != stage:
                    raise GuideBuildError(
                        f"hidden stage/ordinal mismatch: {entry['id']} "
                        f"stage={stage} ordinal={ordinal}"
                    )
                attached[ordinal].append(
                    {
                        "id": entry["id"],
                        "title": entry["title"],
                        "text": step["text"],
                    }
                )
            step["resolved_ordinals"] = ordinals
            step["resource_evidence"] = [
                {
                    "ordinal": ordinal,
                    "resources": [
                        {
                            "name": resource["resource_name"],
                            "archive_index": resource["archive_index"],
                            "function_address": resource["function_address"],
                            "decoded_sha256": resource["decoded_sha256"],
                        }
                        for resource in catalog[ordinal]["resources"]
                    ],
                }
                for ordinal in ordinals
            ]
    return dict(attached)


def _attach_progression(
    entries: list[dict[str, Any]],
    catalog: dict[int, dict[str, Any]],
    source_surfaces: dict[str, list[str]],
) -> tuple[dict[int, dict[str, list[dict[str, str]]]], dict[str, int]]:
    attached: dict[int, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: {
            "acquisitions": [],
            "temporary": [],
            "availability": [],
            "upgrades": [],
            "akurasu_corrections": [],
        }
    )
    allowed = {
        "acquisitions",
        "temporary",
        "availability",
        "upgrades",
        "akurasu_corrections",
    }
    verification_counts: dict[str, int] = defaultdict(int)

    def normalized(value: str) -> str:
        value = unicodedata.normalize("NFKC", value)
        return re.sub(r"[\s・･·\-−－—―（）()【】\[\]]+", "", value).casefold()

    def verification_for(
        entry: dict[str, Any], key: str, value_index: int, ordinal: int
    ) -> str:
        if key == "akurasu_corrections":
            return "source-correction"
        refs = entry.get("_term_refs", {}).get(key, [])[value_index]
        script_text = normalized(
            "\n".join(
                resource.get("_script_text", "")
                for resource in catalog[ordinal]["resources"]
            )
        )
        matched = 0
        checkable = 0
        for term_id in dict.fromkeys(refs):
            candidates = [normalized(value) for value in source_surfaces.get(term_id, [])]
            candidates = [value for value in candidates if len(value) >= 2]
            if not candidates:
                continue
            checkable += 1
            if any(candidate in script_text for candidate in candidates):
                matched += 1
        if checkable and matched == checkable:
            return "stage-script"
        if matched:
            return "stage-script-partial"
        return "guide-supplement"
    for index, entry in enumerate(entries, start=1):
        stage = entry.get("stage")
        if not isinstance(stage, int) or not 1 <= stage <= 60:
            raise GuideBuildError(f"invalid progression stage at entry {index}: {stage}")
        ordinals = entry.get("ordinals")
        if ordinals is None:
            ordinals = [
                ordinal
                for ordinal, record in catalog.items()
                if record["stage"] == stage
            ]
        if not isinstance(ordinals, list) or not ordinals:
            raise GuideBuildError(f"progression entry {index} has no target")
        for key in allowed:
            values = entry.get(key, [])
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise GuideBuildError(
                    f"progression entry {index} has invalid {key} values"
                )
        if not any(entry.get(key) for key in allowed):
            raise GuideBuildError(f"progression entry {index} has no content")
        for ordinal in ordinals:
            if ordinal not in catalog or catalog[ordinal]["stage"] != stage:
                raise GuideBuildError(
                    f"progression stage/ordinal mismatch: entry={index} "
                    f"stage={stage} ordinal={ordinal}"
                )
            for key in allowed:
                for value_index, value in enumerate(entry.get(key, [])):
                    verification = verification_for(entry, key, value_index, ordinal)
                    attached[ordinal][key].append(
                        {"text": value, "verification": verification}
                    )
                    verification_counts[verification] += 1
    return dict(attached), dict(sorted(verification_counts.items()))


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _conditions_html(resources: Iterable[dict[str, Any]]) -> str:
    rows = []
    seen: set[str] = set()
    for resource in resources:
        for condition in resource["conditions"]:
            if condition["id"] in seen:
                continue
            seen.add(condition["id"])
            rows.append(
                f'<li><span class="condition-kind">{_esc(condition["kind"])}</span>'
                f'<span>{_esc(condition["text"])}</span></li>'
            )
    if not rows:
        return '<p class="empty">本关没有可显示的胜败／SR条件。</p>'
    return '<ul class="conditions">' + "".join(rows) + "</ul>"


def _simple_list_block(
    label: str, kind: str, values: list[dict[str, str]]
) -> str:
    if not values:
        return ""
    items = "".join(f'<li>{_esc(value["text"])}</li>' for value in values)
    return (
        f'<section class="stage-block {kind}">'
        f'<h4><span class="block-dot"></span>{_esc(label)}</h4>'
        f'<ul class="info-list">{items}</ul></section>'
    )


def _hidden_stage_block(values: list[dict[str, str]]) -> str:
    if not values:
        return ""
    items = "".join(
        f'<li><a href="#secret-{_esc(item["id"])}">{_esc(item["title"])}</a>'
        f'<p>{_esc(item["text"])}</p></li>'
        for item in values
    )
    return (
        '<section class="stage-block hidden-progress"><h4>'
        '<span class="block-dot"></span>本话隐藏进度</h4>'
        f'<ul class="hidden-list">{items}</ul></section>'
    )


def _stage_card_html(
    record: dict[str, Any],
    hidden: dict[int, list[dict[str, str]]],
    progression: dict[int, dict[str, list[str]]],
) -> str:
    ordinal = record["ordinal"]
    update = progression.get(
        ordinal,
        {
            "acquisitions": [],
            "temporary": [],
            "availability": [],
            "upgrades": [],
            "akurasu_corrections": [],
        },
    )
    content = "".join(
        (
            _simple_list_block("加入／取得", "acquisition", update["acquisitions"]),
            _simple_list_block("临时参战", "temporary", update["temporary"]),
            _simple_list_block("离队／换机", "availability", update["availability"]),
            _simple_list_block("强化／新能力", "upgrade", update["upgrades"]),
            _hidden_stage_block(hidden.get(ordinal, [])),
            _simple_list_block(
                "Akurasu 校正", "correction", update["akurasu_corrections"]
            ),
        )
    )
    return f"""
    <article class="stage-card" id="stage-{ordinal:03d}">
      <header class="stage-header"><span class="lane">{_esc(record['lane'])}</span>
      <h3>{_esc(record['title'])}</h3>
      <p class="source-title">{_esc(record['source_title'])}</p></header>
      <div class="stage-content">{content}</div>
    </article>"""


def _flow_html(
    sections: list[dict[str, Any]],
    catalog: dict[int, dict[str, Any]],
    hidden: dict[int, list[dict[str, str]]],
    progression: dict[int, dict[str, list[str]]],
) -> str:
    blocks = []
    for section_index, section in enumerate(sections, start=1):
        rows = []
        for row in section["rows"]:
            cards = "".join(
                _stage_card_html(catalog[cell["ordinal"]], hidden, progression)
                for cell in row["cells"]
            )
            rows.append(
                f'<div class="flow-row" style="--lanes:{max(1, len(row["cells"]))}">'
                f'<div class="stage-number"><span>第</span><strong>{row["stage"]}</strong><span>话</span></div>'
                f'<div class="stage-lanes">{cards}</div></div>'
            )
        blocks.append(
            f'<section class="flow-section" id="flow-{section_index}">'
            f'<h2>{_esc(section["title"])}</h2>{"".join(rows)}</section>'
        )
    return "".join(blocks)


CATEGORY_LABELS = {
    "character": "隐藏人物",
    "unit": "隐藏机体",
    "weapon": "隐藏武器",
    "item": "隐藏强化零件",
    "system": "点数与结局",
}

def _hidden_html(entries: list[dict[str, Any]]) -> str:
    cards = []
    for entry in entries:
        steps = []
        for step in entry["steps"]:
            stage = step.get("stage")
            when = f"第{stage}话" if stage else step.get("when", "跨关条件")
            steps.append(
                f'<li><div class="step-head"><span class="when">{_esc(when)}</span>'
                f'</div><p>{_esc(step["text"])}</p></li>'
            )
        cards.append(
            f'<article class="secret-card" id="secret-{_esc(entry["id"])}" '
            f'data-category="{_esc(entry["category"])}">'
            f'<div class="secret-kicker">{_esc(CATEGORY_LABELS[entry["category"]])}</div>'
            f'<h3>{_esc(entry["title"])}</h3><p class="secret-summary">{_esc(entry.get("summary", ""))}</p>'
            f'<ol class="secret-steps">{"".join(steps)}</ol>'
            f'</article>'
        )
    return "".join(cards)


def _notice_html(values: list[str]) -> str:
    if not values:
        return ""
    return (
        '<aside class="reference-notice"><div class="reference-notice-title">'
        'Akurasu 资料差异</div><ul>'
        + "".join(f"<li>{_esc(value)}</li>" for value in values)
        + "</ul></aside>"
    )


def _carryover_html(reference: dict[str, Any]) -> str:
    data = reference["carryover"]
    rates = "".join(
        f'<div class="rate-card"><strong>{_esc(item["rate"])}</strong>'
        f'<span>{_esc(item["playthrough"])}</span></div>'
        for item in data["rates"]
    )
    facts = "".join(
        f'<li><strong>{_esc(item["label"])}</strong><span>{_esc(item["value"])}</span></li>'
        for item in data["items"]
    )
    modes = "".join(
        f'<article class="mode-card"><div><h3>{_esc(item["name"])}</h3>'
        f'<span>{_esc(item["unlock"])}</span></div><p>{_esc(item["rules"])}</p></article>'
        for item in data["modes"]
    )
    notes = "".join(f"<li>{_esc(value)}</li>" for value in data["notes"])
    return (
        '<div class="reference-shell">'
        f'<section class="reference-card"><h2>继承比例</h2><div class="rate-grid">{rates}</div></section>'
        f'<section class="reference-card"><h2>继承范围</h2><ul class="fact-list">{facts}</ul></section>'
        f'<section class="reference-card wide"><h2>通关模式</h2><div class="mode-grid">{modes}</div></section>'
        f'<section class="reference-card wide"><h2>容易弄错的规则</h2><ul class="note-list">{notes}</ul></section>'
        f'{_notice_html(data["akurasu_issues"])}'
        '</div>'
    )


def _upgrade_carryover_html(reference: dict[str, Any]) -> str:
    rows = "".join(
        '<tr>'
        f'<td><strong>{_esc(item["from"])}</strong></td>'
        f'<td><span class="carry-arrow">→</span><strong>{_esc(item["to"])}</strong></td>'
        f'<td>{_esc(item["when"])}</td>'
        f'<td><span class="keep-badge {"yes" if item["keeps_old"] else "no"}">'
        f'{"保留" if item["keeps_old"] else "替换"}</span>'
        + (f'<p class="cell-note">{_esc(item["note"])}</p>' if item.get("note") else "")
        + "</td></tr>"
        for item in reference["upgrade_carryover"]
    )
    notes = "".join(
        f"<li>{_esc(value)}</li>" for value in reference["upgrade_notes"]
    )
    return (
        '<div class="reference-shell one-column">'
        '<section class="reference-card"><h2>剧情换机改造继承</h2>'
        '<p class="section-lead">“保留”表示旧机仍在；“替换”表示旧机退出，由后继机接手改造。</p>'
        '<div class="table-wrap"><table class="reference-table"><thead><tr>'
        '<th>原机体</th><th>继承到</th><th>发生时间</th><th>旧机</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div></section>'
        f'<section class="reference-card"><h2>继承规则</h2><ul class="note-list">{notes}</ul></section>'
        f'{_notice_html(reference["upgrade_akurasu_issues"])}'
        '</div>'
    )


def _full_upgrade_bonus_html(reference: dict[str, Any]) -> str:
    bonuses = "".join(
        f'<li><span>{index:02d}</span><strong>{_esc(value)}</strong></li>'
        for index, value in enumerate(reference["full_upgrade_bonuses"], start=1)
    )
    notes = "".join(
        f"<li>{_esc(value)}</li>" for value in reference["full_upgrade_notes"]
    )
    return (
        '<div class="reference-shell one-column">'
        f'<section class="reference-card"><h2>通用全改造奖励</h2><ul class="bonus-grid">{bonuses}</ul></section>'
        f'<section class="reference-card"><h2>选择规则</h2><ul class="note-list">{notes}</ul></section>'
        '</div>'
    )


def _rare_holders_html(item: dict[str, Any]) -> str:
    holders = item.get("holders", [])
    if not holders:
        return ""
    return (
        '<div class="rare-meta"><span class="rare-badge">稀有</span>'
        f'<span>持有人：{_esc("、".join(holders))}</span></div>'
    )


def _skill_note_html(item: dict[str, Any]) -> str:
    note = item.get("note")
    if not note:
        return ""
    return (
        '<div class="skill-note">'
        f'<span class="skill-note-badge">{_esc(note["label"])}</span>'
        f'<span>{_esc(note["text"])}</span></div>'
    )


def _skill_level_detail_html(item: dict[str, Any]) -> str:
    detail = item.get("level_detail")
    if not detail:
        return ""
    headers = "".join(f"<th>{_esc(value)}</th>" for value in detail["columns"])
    rows = "".join(
        "<tr>" + "".join(f"<td>{_esc(value)}</td>" for value in row) + "</tr>"
        for row in detail["rows"]
    )
    note = detail.get("note")
    note_html = f'<p class="level-note">{_esc(note)}</p>' if note else ""
    return (
        '<div class="skill-level-detail"><div class="skill-level-title">等级效果</div>'
        '<div class="level-table-wrap"><table class="level-table">'
        f'<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>'
        f'{note_html}</div>'
    )


def _catalog_cards_html(
    entries: list[dict[str, Any]], *, lead: str, notices: list[str] | None = None
) -> str:
    cards = "".join(
        '<article class="catalog-card">'
        f'<h3>{_esc(item["name"])}</h3><p>{_esc(item["effect"])}</p>'
        f'{_rare_holders_html(item)}'
        f'{_skill_note_html(item)}'
        f'{_skill_level_detail_html(item)}'
        '</article>'
        for item in entries
    )
    return (
        '<div class="reference-shell one-column">'
        f'<section class="reference-card"><p class="section-lead catalog-lead">{_esc(lead)}</p>'
        f'<div class="catalog-grid">{cards}</div></section>'
        f'{_notice_html(notices or [])}</div>'
    )


def _leadership_html(catalogs: dict[str, Any]) -> str:
    groups = "".join(
        '<article class="catalog-card leadership-card">'
        f'<h3>{_esc(group["label"])}</h3><ul>'
        + "".join(
            f'<li><span class="leadership-effect">{_esc(item["effect"])}</span>'
            f'{_rare_holders_html(item)}</li>'
            for item in group["effects"]
        )
        + '</ul></article>'
        for group in catalogs["leadership_groups"]
    )
    return (
        '<div class="reference-shell one-column"><section class="reference-card">'
        '<p class="section-lead catalog-lead">成为小队长时生效；战舰舰长效果作用于相邻友军。标有“稀有”的效果，在可用／客串角色中仅有一人持有。</p>'
        f'<div class="catalog-grid">{groups}</div></section>'
        f'{_notice_html(catalogs["leadership_notices"])}</div>'
    )


def _bazaar_html(reference: dict[str, Any], catalogs: dict[str, Any]) -> str:
    part_rows = "".join(
        '<tr>'
        f'<td><strong>{_esc(item["name"])}</strong></td>'
        f'<td>{_esc(item["effect"])}</td>'
        f'<td class="number-cell">{_esc(item["buy"])}</td>'
        f'<td class="number-cell">{_esc(item["sell"])}</td>'
        '</tr>'
        for item in catalogs["bazaar_parts"]
    )
    unit_rows = "".join(
        '<tr>'
        f'<td><strong>{_esc(item["name"])}</strong></td>'
        f'<td class="number-cell">{_esc(item["cost"])}</td>'
        f'<td>{_esc(item["availability"])}</td>'
        '</tr>'
        for item in reference["bazaar_units"]
    )
    notes = "".join(f'<li>{_esc(value)}</li>' for value in reference["bazaar_notes"])
    return (
        '<div class="reference-shell one-column">'
        '<section class="reference-card"><h2>常规强化零件</h2>'
        '<div class="table-wrap"><table class="reference-table data-table"><thead><tr>'
        '<th>物品</th><th>效果</th><th>购买BS</th><th>出售BS</th>'
        f'</tr></thead><tbody>{part_rows}</tbody></table></div></section>'
        '<section class="reference-card"><h2>可购买机体</h2>'
        '<div class="table-wrap"><table class="reference-table data-table"><thead><tr>'
        '<th>机体</th><th>BS</th><th>出现时期</th>'
        f'</tr></thead><tbody>{unit_rows}</tbody></table></div></section>'
        f'<section class="reference-card"><h2>购买规则</h2><ul class="note-list">{notes}</ul></section>'
        '</div>'
    )


def _team_attacks_html(reference: dict[str, Any]) -> str:
    rows = "".join(
        '<tr>'
        f'<td><strong>{_esc(item["name"])}</strong>'
        + (f'<p class="cell-note">{_esc(item["note"])}</p>' if item.get("note") else "")
        + '</td>'
        f'<td>{_esc(item["units"])}</td>'
        f'<td class="number-cell">{_esc(item["morale"])}</td>'
        f'<td class="number-cell">{_esc(item["range"])}</td>'
        '</tr>'
        for item in reference["team_attacks"]
    )
    notes = "".join(
        f'<li>{_esc(value)}</li>' for value in reference["team_attack_notes"]
    )
    return (
        '<div class="reference-shell one-column">'
        '<section class="reference-card"><h2>合体攻击一览</h2>'
        '<div class="table-wrap"><table class="reference-table data-table"><thead><tr>'
        '<th>攻击</th><th>所需机体</th><th>气力</th><th>射程</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div></section>'
        f'<section class="reference-card"><h2>使用规则</h2><ul class="note-list">{notes}</ul></section>'
        '</div>'
    )


def _validate_reference_against_game(
    reference: dict[str, Any], catalogs: dict[str, Any]
) -> None:
    rates = [item["rate"] for item in reference["carryover"]["rates"]]
    if rates != ["50%", "75%", "100%"]:
        raise GuideBuildError(f"carryover-rate drift: {rates}")
    game_ui = json.dumps(_json(REMAINING_UI), ensure_ascii=False)
    for token in ("2周目", "50％", "3周目", "75％", "4周目起", "100％", "15段"):
        if token not in game_ui:
            raise GuideBuildError(f"carryover rule missing from game UI: {token}")
    if len(reference["upgrade_carryover"]) != 20:
        raise GuideBuildError("upgrade-carryover table must contain 20 rows")
    if len(reference["full_upgrade_bonuses"]) != 14:
        raise GuideBuildError("full-upgrade bonus table must contain 14 choices")
    full_upgrade_ui = json.dumps(_json(UNCLASSIFIED_UI), ensure_ascii=False)
    for token in ("装甲值", "移动力", "获得干扰功能", "武器射程＋1", "武器CT修正"):
        if token not in full_upgrade_ui:
            raise GuideBuildError(f"full-upgrade rule missing from game UI: {token}")
    expected_counts = {
        "pilot_skills": 45,
        "leadership_groups": 15,
        "mech_abilities": 45,
        "bazaar_parts": 28,
    }
    for key, expected in expected_counts.items():
        if len(catalogs[key]) != expected:
            raise GuideBuildError(
                f"reference catalog count drift: {key}={len(catalogs[key])}"
            )
    if sum(len(group["effects"]) for group in catalogs["leadership_groups"]) != 59:
        raise GuideBuildError("leadership effect table must contain 59 effects")
    if len(reference.get("bazaar_units", [])) != 15:
        raise GuideBuildError("bazaar unit table must contain 15 units")
    if len(reference.get("team_attacks", [])) != 12:
        raise GuideBuildError("team-attack table must contain 12 attacks")
    weapon_ui = json.dumps(_json(PROJECT_ROOT / "corpus/zh/menu/weapons.json"), ensure_ascii=False)
    for item in reference["team_attacks"]:
        if item["name"] not in weapon_ui:
            raise GuideBuildError(f"team attack missing from game weapon UI: {item['name']}")


def _render_html(
    sections: list[dict[str, Any]],
    catalog: dict[int, dict[str, Any]],
    hidden_entries: list[dict[str, Any]],
    hidden_by_stage: dict[int, list[dict[str, str]]],
    progression_by_stage: dict[int, dict[str, list[str]]],
    reference: dict[str, Any],
    catalogs: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    embedded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    flow = _flow_html(sections, catalog, hidden_by_stage, progression_by_stage)
    secrets = _hidden_html(hidden_entries)
    carryover = _carryover_html(reference)
    upgrade_carryover = _upgrade_carryover_html(reference)
    full_upgrade_bonus = _full_upgrade_bonus_html(reference)
    leadership = _leadership_html(catalogs)
    pilot_skills = _catalog_cards_html(
        catalogs["pilot_skills"],
        lead="游戏内全部45项特殊技能及其实际效果。有等级的技能直接列出每级效果。不可通过PP购买、且我方常驻或可控客串角色中持有人去重后不超过5人的技能标为稀有；同一人物的化名与剧情形态合并计算。",
        notices=catalogs["pilot_skill_notices"],
    )
    mech_abilities = _catalog_cards_html(
        catalogs["mech_abilities"],
        lead="游戏内有名称的机体特殊能力。相同效果会按不同能力名分别列出。",
        notices=reference["mech_ability_akurasu_issues"],
    )
    bazaar = _bazaar_html(reference, catalogs)
    team_attacks = _team_attacks_html(reference)
    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>《超级机器人大战Z》流程、隐藏要素与资料攻略</title>
<style>
:root{{--background:#f8fafc;--foreground:#0f172a;--card:#fff;--muted:#64748b;--muted-bg:#f1f5f9;--border:#e2e8f0;--primary:#0f172a;--blue:#2563eb;--blue-bg:#eff6ff;--green:#15803d;--green-bg:#f0fdf4;--amber:#a16207;--amber-bg:#fffbeb;--red:#b91c1c;--red-bg:#fef2f2;--violet:#7c3aed;--violet-bg:#f5f3ff;--orange:#c2410c;--orange-bg:#fff7ed;--ring:rgba(37,99,235,.18);--shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.04)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;background:var(--background)}}body{{margin:0;background:var(--background);color:var(--foreground);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC","Microsoft YaHei",sans-serif;line-height:1.55;-webkit-font-smoothing:antialiased}}
a{{color:inherit;text-decoration:none}}button{{font:inherit}}.mode-tabs{{position:sticky;top:0;z-index:20;display:flex;height:52px;overflow-x:auto;background:rgba(255,255,255,.94);border-bottom:1px solid var(--border);backdrop-filter:blur(12px);scrollbar-width:none}}.mode-tabs::-webkit-scrollbar{{display:none}}.mode-tab{{flex:1 0 96px;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:.88rem;font-weight:650;white-space:nowrap;border-bottom:2px solid transparent;transition:.15s ease}}.mode-tab:hover{{background:var(--muted-bg);color:var(--foreground)}}.mode-tab.active{{color:var(--foreground);border-bottom-color:var(--foreground)}}main{{width:min(1280px,calc(100% - 32px));margin:22px auto 64px}}.guide-panel[hidden]{{display:none}}
.flow-section{{margin:0 0 42px}}.flow-section h2{{margin:0 0 12px;padding:0 2px 9px;border-bottom:1px solid var(--border);font-size:.8rem;line-height:1.2;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}}.flow-row{{display:grid;grid-template-columns:56px 1fr;gap:10px;margin:0 0 10px;align-items:stretch}}.stage-number{{position:sticky;top:62px;align-self:start;min-height:78px;border:1px solid var(--border);border-radius:10px;background:var(--card);display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1;box-shadow:0 1px 2px rgba(15,23,42,.03)}}.stage-number strong{{font-size:1.35rem;font-variant-numeric:tabular-nums}}.stage-number span{{font-size:.65rem;color:var(--muted);margin:2px 0}}.stage-lanes{{display:grid;grid-template-columns:repeat(var(--lanes),minmax(0,1fr));gap:10px}}.stage-card,.secret-card{{background:var(--card);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow)}}.stage-card{{overflow:hidden;scroll-margin-top:62px}}.stage-header{{padding:14px 16px 12px;border-bottom:1px solid var(--border)}}.lane{{display:inline-flex;align-items:center;min-height:22px;padding:2px 8px;border:1px solid #bfdbfe;border-radius:999px;background:var(--blue-bg);color:#1d4ed8;font-size:.7rem;font-weight:650}}.stage-card h3,.secret-card h3{{margin:7px 0 0;font-size:1rem;line-height:1.35;letter-spacing:-.01em}}.source-title{{margin:2px 0 0;color:var(--muted);font-size:.75rem}}.stage-content{{padding:4px 16px 10px}}.stage-block{{padding:11px 0;border-top:1px solid var(--border)}}.stage-block:first-child{{border-top:0}}.stage-block h4{{display:flex;align-items:center;gap:7px;margin:0 0 6px;font-size:.76rem;line-height:1.25;font-weight:700;color:var(--muted)}}.block-dot{{width:7px;height:7px;border-radius:999px;background:var(--muted)}}.acquisition h4{{color:var(--blue)}}.acquisition .block-dot{{background:var(--blue)}}.temporary h4{{color:var(--violet)}}.temporary .block-dot{{background:var(--violet)}}.availability h4{{color:var(--orange)}}.availability .block-dot{{background:var(--orange)}}.upgrade h4{{color:var(--green)}}.upgrade .block-dot{{background:var(--green)}}.hidden-progress h4{{color:var(--amber)}}.hidden-progress .block-dot{{background:var(--amber)}}.correction{{margin:5px -8px 2px;padding:10px 8px;border:1px solid #fecaca!important;border-radius:8px;background:var(--red-bg)}}.correction h4{{color:var(--red)}}.correction .block-dot{{background:var(--red)}}.info-list,.hidden-list{{list-style:none;padding:0;margin:0}}.info-list li,.hidden-list li{{position:relative;padding:4px 0 4px 13px;font-size:.81rem;line-height:1.55}}.info-list li::before,.hidden-list li::before{{content:"";position:absolute;left:1px;top:.78rem;width:3px;height:3px;border-radius:50%;background:#94a3b8}}.hidden-list a{{color:#92400e;font-weight:650;text-decoration:underline;text-decoration-color:#fde68a;text-underline-offset:3px}}.hidden-list p{{margin:2px 0 0;color:#475569}}.source-badge{{display:inline-flex;margin-left:7px;padding:0 5px;border:1px solid #fed7aa;border-radius:999px;background:var(--orange-bg);color:var(--orange);font-size:.6rem;font-weight:700;vertical-align:1px}}.empty{{margin:0;color:var(--muted);font-size:.78rem}}
#flow,#hidden-elements{{scroll-margin-top:62px}}.category-filters{{position:sticky;top:52px;z-index:10;display:flex;flex-wrap:wrap;gap:7px;margin:0 0 14px;padding:10px 0;background:linear-gradient(var(--background) 78%,transparent)}}.category-filters button{{min-height:34px;padding:5px 11px;border:1px solid var(--border);border-radius:8px;background:var(--card);color:var(--muted);cursor:pointer;font-size:.78rem;font-weight:600;box-shadow:0 1px 2px rgba(15,23,42,.02)}}.category-filters button:hover{{color:var(--foreground);border-color:#cbd5e1}}.category-filters button.active{{background:var(--primary);color:white;border-color:var(--primary)}}.category-filters button:focus-visible,.mode-tab:focus-visible{{outline:3px solid var(--ring);outline-offset:-2px}}.secret-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.secret-card{{padding:17px 18px;scroll-margin-top:106px}}.secret-kicker{{display:inline-flex;padding:2px 7px;border-radius:999px;background:var(--amber-bg);color:var(--amber);font-size:.68rem;font-weight:700}}.secret-summary{{color:var(--muted);font-size:.82rem;margin:7px 0 12px}}.secret-steps{{padding:0;margin:0;list-style:none;counter-reset:secret-step}}.secret-steps>li{{position:relative;padding:10px 0 10px 38px;border-top:1px solid var(--border);counter-increment:secret-step}}.secret-steps>li::before{{content:counter(secret-step);position:absolute;left:0;top:10px;display:grid;place-items:center;width:24px;height:24px;border:1px solid var(--border);border-radius:7px;background:var(--muted-bg);color:var(--muted);font-size:.7rem;font-weight:700}}.secret-steps p{{margin:4px 0 0;font-size:.82rem}}.step-head{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}}.when{{display:inline-flex;padding:1px 7px;border-radius:999px;background:var(--blue-bg);color:#1d4ed8;font-size:.68rem;font-weight:700}}.is-hidden{{display:none!important}}
#carryover,#upgrade-carryover,#full-upgrade-bonus,#leadership,#pilot-skills,#mech-abilities,#bazaar,#team-attacks{{scroll-margin-top:62px}}.reference-shell{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;max-width:1120px;margin:auto}}.reference-shell.one-column{{grid-template-columns:1fr}}.reference-card,.reference-notice{{padding:18px;background:var(--card);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow)}}.reference-card.wide,.reference-notice{{grid-column:1/-1}}.reference-card h2{{margin:0 0 13px;font-size:.86rem;color:var(--muted);letter-spacing:.04em}}.rate-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.rate-card{{display:flex;flex-direction:column;align-items:center;padding:15px 8px;border:1px solid var(--border);border-radius:10px;background:var(--muted-bg)}}.rate-card strong{{font-size:1.35rem;line-height:1.1}}.rate-card span{{margin-top:5px;color:var(--muted);font-size:.72rem}}.fact-list,.note-list,.reference-notice ul,.bonus-grid{{list-style:none;padding:0;margin:0}}.fact-list li{{display:grid;grid-template-columns:95px 1fr;gap:12px;padding:10px 0;border-top:1px solid var(--border);font-size:.82rem}}.fact-list li:first-child{{border-top:0;padding-top:0}}.fact-list strong{{font-size:.76rem}}.fact-list span,.section-lead,.cell-note{{color:var(--muted)}}.mode-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.mode-card{{padding:14px;border:1px solid var(--border);border-radius:10px;background:var(--muted-bg)}}.mode-card>div{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.mode-card h3{{margin:0;font-size:1rem}}.mode-card span{{color:var(--blue);font-size:.7rem;font-weight:650;text-align:right}}.mode-card p{{margin:8px 0 0;font-size:.8rem}}.note-list li,.reference-notice li{{position:relative;padding:7px 0 7px 15px;font-size:.82rem}}.note-list li::before,.reference-notice li::before{{content:"";position:absolute;left:1px;top:.82rem;width:4px;height:4px;border-radius:99px;background:#94a3b8}}.reference-notice{{border-color:#fecaca;background:var(--red-bg);box-shadow:none;color:#7f1d1d}}.reference-notice-title{{margin-bottom:5px;font-size:.76rem;font-weight:750}}.section-lead{{margin:-5px 0 14px;font-size:.78rem}}.catalog-lead{{margin:0 0 14px}}.catalog-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}}.catalog-card{{padding:13px 14px;border:1px solid var(--border);border-radius:10px;background:var(--muted-bg)}}.catalog-card h3{{margin:0;font-size:.84rem}}.catalog-card p{{margin:6px 0 0;color:#475569;font-size:.78rem;white-space:pre-line}}.rare-meta{{display:flex;align-items:flex-start;gap:7px;margin-top:9px;color:#7c2d12;font-size:.7rem;line-height:1.45}}.rare-badge{{flex:0 0 auto;padding:1px 6px;border:1px solid #fed7aa;border-radius:999px;background:#fff7ed;color:#c2410c;font-size:.62rem;font-weight:750}}.leadership-card ul{{margin:7px 0 0;padding:0;list-style:none}}.leadership-card li{{padding:7px 0;border-top:1px solid var(--border);color:#475569;font-size:.77rem;white-space:pre-line}}.leadership-card .rare-meta{{white-space:normal}}.table-wrap{{overflow-x:auto;border:1px solid var(--border);border-radius:10px}}.reference-table{{width:100%;border-collapse:collapse;font-size:.79rem;min-width:720px}}.reference-table th{{padding:9px 11px;background:var(--muted-bg);color:var(--muted);font-size:.7rem;text-align:left}}.reference-table td{{padding:10px 11px;border-top:1px solid var(--border);vertical-align:top}}.reference-table td:nth-child(1),.reference-table td:nth-child(2){{width:25%}}.reference-table td:nth-child(3){{width:30%}}.data-table td{{width:auto!important;white-space:pre-line}}.data-table td:first-child{{min-width:150px}}.data-table .number-cell{{width:86px!important;white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}}.carry-arrow{{margin-right:8px;color:var(--muted)}}.keep-badge{{display:inline-flex;padding:2px 7px;border-radius:999px;font-size:.68rem;font-weight:700}}.keep-badge.yes{{background:var(--blue-bg);color:var(--blue)}}.keep-badge.no{{background:var(--muted-bg);color:var(--muted)}}.cell-note{{margin:5px 0 0;font-size:.7rem}}.bonus-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.bonus-grid li{{display:flex;gap:10px;align-items:center;padding:11px 12px;border:1px solid var(--border);border-radius:9px;font-size:.8rem}}.bonus-grid li>span{{display:grid;place-items:center;flex:0 0 24px;width:24px;height:24px;border-radius:7px;background:var(--muted-bg);color:var(--muted);font-size:.65rem}}
.catalog-card{{min-width:0}}.skill-note{{display:flex;align-items:flex-start;gap:7px;margin-top:9px;color:#475569;font-size:.7rem;line-height:1.45}}.skill-note-badge{{flex:0 0 auto;padding:1px 6px;border:1px solid #cbd5e1;border-radius:999px;background:#f8fafc;color:#475569;font-size:.62rem;font-weight:750}}.skill-level-detail{{margin-top:12px;padding-top:11px;border-top:1px solid var(--border)}}.skill-level-title{{margin-bottom:7px;color:var(--muted);font-size:.67rem;font-weight:750;letter-spacing:.04em}}.level-table-wrap{{max-width:100%;overflow-x:auto;border:1px solid var(--border);border-radius:8px;background:var(--card)}}.level-table{{width:100%;min-width:max-content;border-collapse:collapse;font-size:.68rem;font-variant-numeric:tabular-nums}}.level-table th{{padding:6px 8px;background:#f8fafc;color:var(--muted);font-size:.62rem;text-align:left;white-space:nowrap}}.level-table td{{padding:6px 8px;border-top:1px solid var(--border);white-space:nowrap}}.level-note{{margin:7px 0 0!important;color:var(--muted)!important;font-size:.67rem!important;line-height:1.5}}.reference-card{{min-width:0}}@media(max-width:900px){{.stage-lanes,.secret-grid{{grid-template-columns:1fr}}}}
@media(max-width:620px){{.mode-tab{{flex-basis:78px;font-size:.78rem}}main{{width:min(100% - 16px,1280px);margin-top:12px}}.flow-row{{grid-template-columns:42px 1fr;gap:7px}}.stage-number{{top:59px;min-height:68px;border-radius:9px}}.stage-number strong{{font-size:1.12rem}}.stage-header{{padding:12px 13px 10px}}.stage-content{{padding:3px 13px 8px}}.secret-card{{padding:15px}}.reference-shell{{grid-template-columns:1fr}}.reference-card{{padding:15px}}.mode-grid,.bonus-grid,.catalog-grid{{grid-template-columns:1fr}}.fact-list li{{grid-template-columns:82px 1fr;gap:9px}}}}
@media(max-width:620px){{.catalog-grid{{grid-template-columns:minmax(0,1fr)}}}}
@media print{{.mode-tabs,.category-filters{{display:none}}body{{background:white}}main{{width:100%;margin:0}}.guide-panel[hidden]{{display:block}}.stage-card,.secret-card{{box-shadow:none;break-inside:avoid}}.stage-number{{position:static}}}}
</style>
</head>
<body>
<nav class="mode-tabs" aria-label="攻略页面">
  <a class="mode-tab active" data-panel="flow" href="#flow">流程图</a>
  <a class="mode-tab" data-panel="hidden-elements" href="#hidden-elements">隐藏要素</a>
  <a class="mode-tab" data-panel="carryover" href="#carryover">周目继承</a>
  <a class="mode-tab" data-panel="upgrade-carryover" href="#upgrade-carryover">改造继承</a>
  <a class="mode-tab" data-panel="full-upgrade-bonus" href="#full-upgrade-bonus">全改造奖励</a>
  <a class="mode-tab" data-panel="leadership" href="#leadership">小队长能力</a>
  <a class="mode-tab" data-panel="pilot-skills" href="#pilot-skills">人物技能</a>
  <a class="mode-tab" data-panel="mech-abilities" href="#mech-abilities">机体能力</a>
  <a class="mode-tab" data-panel="bazaar" href="#bazaar">集市物品</a>
  <a class="mode-tab" data-panel="team-attacks" href="#team-attacks">合体攻击</a>
</nav>
<main>
  <section class="guide-panel" id="flow" data-panel-content="flow">{flow}</section>
  <section class="guide-panel" id="hidden-elements" data-panel-content="hidden-elements" hidden><div class="category-filters"><button class="active" data-category="all">全部</button>{''.join(f'<button data-category="{key}">{label}</button>' for key,label in CATEGORY_LABELS.items())}</div><div class="secret-grid">{secrets}</div></section>
  <section class="guide-panel" id="carryover" data-panel-content="carryover" hidden>{carryover}</section>
  <section class="guide-panel" id="upgrade-carryover" data-panel-content="upgrade-carryover" hidden>{upgrade_carryover}</section>
  <section class="guide-panel" id="full-upgrade-bonus" data-panel-content="full-upgrade-bonus" hidden>{full_upgrade_bonus}</section>
  <section class="guide-panel" id="leadership" data-panel-content="leadership" hidden>{leadership}</section>
  <section class="guide-panel" id="pilot-skills" data-panel-content="pilot-skills" hidden>{pilot_skills}</section>
  <section class="guide-panel" id="mech-abilities" data-panel-content="mech-abilities" hidden>{mech_abilities}</section>
  <section class="guide-panel" id="bazaar" data-panel-content="bazaar" hidden>{bazaar}</section>
  <section class="guide-panel" id="team-attacks" data-panel-content="team-attacks" hidden>{team_attacks}</section>
</main>
<script type="application/json" id="guide-manifest">{embedded}</script>
<script>
(()=>{{const tabs=[...document.querySelectorAll('[data-panel]')];const panels=[...document.querySelectorAll('[data-panel-content]')];const categoryButtons=[...document.querySelectorAll('button[data-category]')];const pageNames=new Set(panels.map(panel=>panel.dataset.panelContent));function selectPanel(){{const hash=location.hash;let name=hash.startsWith('#secret-')?'hidden-elements':hash.slice(1);if(!pageNames.has(name))name='flow';panels.forEach(panel=>panel.hidden=panel.dataset.panelContent!==name);tabs.forEach(tab=>tab.classList.toggle('active',tab.dataset.panel===name));tabs.find(tab=>tab.dataset.panel===name)?.scrollIntoView({{inline:'center',block:'nearest'}});if(hash.startsWith('#secret-'))requestAnimationFrame(()=>document.querySelector(hash)?.scrollIntoView());}}function selectCategory(category){{categoryButtons.forEach(button=>button.classList.toggle('active',button.dataset.category===category));document.querySelectorAll('.secret-card').forEach(card=>card.classList.toggle('is-hidden',category!=='all'&&card.dataset.category!==category));}}window.addEventListener('hashchange',selectPanel);categoryButtons.forEach(button=>button.addEventListener('click',()=>selectCategory(button.dataset.category)));selectPanel();}})();
</script>
</body></html>
"""


def build() -> tuple[bytes, bytes]:
    sections = parse_route_map()
    resources, stage_report = parse_stage_resources()
    catalog = _stage_catalog(sections, resources)
    terms, term_sources = _load_terms()
    hidden_source = _json(HIDDEN_ELEMENTS)
    hidden_entries, hidden_terms = _expand_hidden_terms(hidden_source, terms)
    hidden_by_stage = _attach_hidden(hidden_entries, catalog)
    progression_source = _json(PROGRESSION)
    progression_entries, progression_terms = _expand_progression_terms(
        progression_source, terms
    )
    source_surfaces = _load_term_source_surfaces()
    progression_by_stage, progression_verification = _attach_progression(
        progression_entries, catalog, source_surfaces
    )
    reference_source = _json(REFERENCE)
    reference, reference_terms = _expand_reference_terms(reference_source, terms)
    catalogs = _load_reference_catalogs(reference)
    _validate_reference_against_game(reference, catalogs)
    verified_progression = (
        progression_verification.get("stage-script", 0)
        + progression_verification.get("stage-script-partial", 0)
    )
    supplement_progression = progression_verification.get("guide-supplement", 0)
    if verified_progression <= supplement_progression:
        raise GuideBuildError(
            "Timeline cross-check coverage must exceed guide-only supplements"
        )
    used_terms = hidden_terms | progression_terms | reference_terms
    flow_conditions = {
        condition["id"]
        for ordinal in range(107)
        for resource in resources[ordinal + 1]
        for condition in resource["conditions"]
    }
    evidence_counts: dict[str, int] = defaultdict(int)
    for entry in hidden_entries:
        if entry.get("category") not in CATEGORY_LABELS:
            raise GuideBuildError(f"unknown hidden category: {entry.get('category')}")
        for term_id in entry.get("term_refs", []):
            if term_id not in terms:
                raise GuideBuildError(f"unknown declared term ref: {term_id}")
        for step in entry["steps"]:
            level = step.get("evidence_level", "cross-stage")
            if level not in {"stage-static", "cross-stage", "cross-file"}:
                raise GuideBuildError(f"unknown evidence level: {level}")
            evidence_counts[level] += 1

    source_files = [
        ROUTE_MAP,
        STAGE_NAMES,
        STAGE_CONDITIONS,
        REMAINING_UI,
        UNCLASSIFIED_UI,
        PILOT_SKILLS_UI,
        MECH_ABILITIES_UI,
        LEADERSHIP_UI,
        PARTS_UI,
        HIDDEN_ELEMENTS,
        PROGRESSION,
        REFERENCE,
        STAGE_LAYOUT,
        DISPLAY_NAME_CONFIG,
        COMPDATA,
        STAGE_ARCHIVE,
        SLPS,
        TEXT_TABLE,
    ]
    manifest = {
        "schema_version": 1,
        "generator": "tools/build_stage_guide.py",
        "source_policy": {
            "hidden_elements": hidden_source.get("source_policy", {}),
            "timeline": progression_source.get("source_policy", {}),
            "reference": reference_source.get("source_policy", {}),
        },
        "inputs": {
            path.relative_to(PROJECT_ROOT).as_posix(): {
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for path in source_files
        },
        "coverage": {
            "playable_title_count": len(catalog),
            "playable_resource_number_count": stage_report[
                "playable_resource_number_count"
            ],
            "playable_chunk_count": stage_report["playable_chunk_count"],
            "flow_condition_count": len(flow_conditions),
            "all_parsed_condition_count": stage_report["parsed_condition_count"],
            "condition_corpus_count": stage_report["corpus_condition_count"],
            "hidden_entry_count": len(hidden_entries),
            "hidden_step_count": sum(len(entry["steps"]) for entry in hidden_entries),
            "progression_entry_count": len(progression_entries),
            "progression_stage_card_count": len(progression_by_stage),
            "akurasu_correction_count": sum(
                len(entry.get("akurasu_corrections", []))
                for entry in progression_entries
            ),
            "akurasu_hidden_text_correction_count": sum(
                len(entry.get("akurasu_text_corrections", []))
                for entry in progression_entries
            ),
            "akurasu_correction_card_count": sum(
                len(entry["akurasu_corrections"])
                for entry in progression_by_stage.values()
            ),
            "progression_verification_counts": progression_verification,
            "reference_upgrade_carryover_count": len(
                reference["upgrade_carryover"]
            ),
            "reference_full_upgrade_bonus_count": len(
                reference["full_upgrade_bonuses"]
            ),
            "reference_pilot_skill_count": len(catalogs["pilot_skills"]),
            "reference_pilot_skill_level_table_count": sum(
                bool(item["level_detail"]) for item in catalogs["pilot_skills"]
            ),
            "reference_rare_pilot_skill_count": sum(
                bool(item["holders"]) for item in catalogs["pilot_skills"]
            ),
            "reference_leadership_category_count": len(
                catalogs["leadership_groups"]
            ),
            "reference_leadership_effect_count": sum(
                len(group["effects"]) for group in catalogs["leadership_groups"]
            ),
            "reference_rare_leadership_effect_count": sum(
                bool(item["holders"])
                for group in catalogs["leadership_groups"]
                for item in group["effects"]
            ),
            "reference_mech_ability_count": len(catalogs["mech_abilities"]),
            "reference_bazaar_part_count": len(catalogs["bazaar_parts"]),
            "reference_bazaar_unit_count": len(reference["bazaar_units"]),
            "reference_team_attack_count": len(reference["team_attacks"]),
            "evidence_level_counts": dict(sorted(evidence_counts.items())),
            "used_global_term_count": len(used_terms),
        },
        "terminology": {
            "used_ids": sorted(used_terms),
            "sources": {term_id: term_sources[term_id] for term_id in sorted(used_terms)},
        },
        "resources": {
            f"{number:03d}": [
                {
                    key: value
                    for key, value in resource.items()
                    if not key.startswith("_") and key != "conditions"
                }
                for resource in resources[number]
            ]
            for number in range(1, 108)
        },
    }
    html_text = _render_html(
        sections,
        catalog,
        hidden_entries,
        hidden_by_stage,
        progression_by_stage,
        reference,
        catalogs,
        manifest,
    )
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return html_text.encode("utf-8"), manifest_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--check", action="store_true", help="fail if checked-in outputs are stale"
    )
    args = parser.parse_args()
    html_bytes, manifest_bytes = build()
    outputs = ((args.output, html_bytes), (args.manifest, manifest_bytes))
    if args.check:
        stale = [str(path) for path, payload in outputs if not path.is_file() or path.read_bytes() != payload]
        if stale:
            raise SystemExit("stage guide outputs are stale: " + ", ".join(stale))
        print("stage guide check passed")
        return 0
    for path, payload in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        print(f"wrote {path.relative_to(PROJECT_ROOT)} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
