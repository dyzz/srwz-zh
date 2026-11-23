#!/usr/bin/env python3
"""Build the offline SRWZ route and hidden-element guide from local data.

The generated HTML is deliberately self-contained.  Route titles, stage
conditions, script provenance and terminology are all resolved from files in
this repository; the browser never needs to fetch JSON, JavaScript or fonts.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import html
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
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
GLOSSARY_DIR = PROJECT_ROOT / "corpus/glossary"
UNITS_FULL = PROJECT_ROOT / "corpus/zh/display-names/units-full.json"
WEAPONS_UI = PROJECT_ROOT / "corpus/zh/menu/weapons.json"
UI_STRINGS = PROJECT_ROOT / "guide/data/ui-strings.json"
REGIONAL_SOURCES = PROJECT_ROOT / "guide/data/regional-sources.json"
GUIDE_DIR = PROJECT_ROOT / "guide"
DEFAULT_OUTPUT = GUIDE_DIR / "srwz-z-flow-guide.html"
DEFAULT_MANIFEST = GUIDE_DIR / "stage-guide-manifest.json"
GUIDE_DATA_NAMES = ("hidden-elements", "progression", "reference")

# Simplified, Taiwan and Hong Kong are three independently written editions
# (no character conversion anywhere).  Each edition reads its own corpus,
# glossary and hand-written guide data; Hong Kong falls back to the Taiwan
# corpus only for files it does not keep (config/zh-hant/hk-uses-taiwan.json).
EDITIONS: dict[str, dict[str, Any]] = {
    "zh": {
        "corpus": ("corpus/zh",),
        "glossary": "corpus/glossary",
        "data": "guide/data",
        "html": "srwz-z-flow-guide.html",
        "lang": "zh-Hans",
        "label": "简体",
    },
    "zh-hant": {
        "corpus": ("corpus/zh-hant",),
        "glossary": "corpus/glossary-zh-hant",
        "data": "guide/data/zh-hant",
        "html": "srwz-z-flow-guide-tw.html",
        "lang": "zh-Hant-TW",
        "label": "台灣繁體",
    },
    "zh-hant-hk": {
        "corpus": ("corpus/zh-hant-hk", "corpus/zh-hant"),
        "glossary": "corpus/glossary-zh-hant-hk",
        "data": "guide/data/zh-hant-hk",
        "html": "srwz-z-flow-guide-hk.html",
        "lang": "zh-Hant-HK",
        "label": "香港繁體",
    },
}
EDITION = "zh"

TITLE_RE = re.compile(r"\[(\d{3})\]\s*(.*?)（日：(.*?)）")
RESOURCE_RE = re.compile(rb"stg_(\d{3})([a-z]?)\.bin", re.IGNORECASE)
TERM_RE = re.compile(r"\{\{([^{}]+)\}\}")


class GuideBuildError(ValueError):
    """Raised when source data no longer satisfies the guide contract."""


def _edition_corpus(relative: str) -> Path:
    for root in EDITIONS[EDITION]["corpus"]:
        path = PROJECT_ROOT / root / relative
        if path.is_file():
            return path
    raise GuideBuildError(f"{EDITION} corpus has no {relative}")


def _use_edition(code: str) -> None:
    """Point the module-level inputs at one edition's corpus and guide data."""

    global EDITION, STAGE_NAMES, STAGE_CONDITIONS, REMAINING_UI, UNCLASSIFIED_UI
    global PILOT_SKILLS_UI, MECH_ABILITIES_UI, LEADERSHIP_UI, PARTS_UI
    global HIDDEN_ELEMENTS, PROGRESSION, REFERENCE, GLOSSARY_DIR, UNITS_FULL, WEAPONS_UI
    if code not in EDITIONS:
        raise GuideBuildError(f"unknown edition: {code}")
    EDITION = code
    STAGE_NAMES = _edition_corpus("menu/stage-names.json")
    STAGE_CONDITIONS = _edition_corpus("story-conditions.json")
    REMAINING_UI = _edition_corpus("menu/remaining-ui.json")
    UNCLASSIFIED_UI = _edition_corpus("menu/unclassified.json")
    PILOT_SKILLS_UI = _edition_corpus("menu/system-ui-skills.json")
    MECH_ABILITIES_UI = _edition_corpus("menu/system-ui-special-abilities.json")
    LEADERSHIP_UI = _edition_corpus("menu/system-ui-leadership.json")
    PARTS_UI = _edition_corpus("menu/system-ui-parts.json")
    UNITS_FULL = _edition_corpus("display-names/units-full.json")
    WEAPONS_UI = _edition_corpus("menu/weapons.json")
    GLOSSARY_DIR = PROJECT_ROOT / EDITIONS[code]["glossary"]
    data = PROJECT_ROOT / EDITIONS[code]["data"]
    HIDDEN_ELEMENTS = data / "hidden-elements.json"
    PROGRESSION = data / "progression.json"
    REFERENCE = data / "reference.json"


@functools.lru_cache(maxsize=None)
def _ui_strings() -> dict[str, dict[str, str]]:
    return _json(UI_STRINGS)["strings"]


def _t(value: str) -> str:
    """This edition's form of an interface string written in Simplified here."""

    if EDITION == "zh":
        return value
    try:
        return _ui_strings()[value][EDITION]
    except KeyError:
        raise GuideBuildError(
            f"guide/data/ui-strings.json has no {EDITION} form of {value!r}"
        ) from None


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


def _load_stage_titles(path: Path | None = None) -> dict[int, dict[str, Any]]:
    entries = _json(path or STAGE_NAMES).get("entries")
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
    for path in sorted(GLOSSARY_DIR.glob("*.json")):
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

    # Leader effects have stable offsets; wording is editorial and can change.
    for offset, translation in _json(REMAINING_UI)["leadership_effect_by_offset"].items():
        term_id = f"leadership-effect/{offset}"
        translations[term_id] = translation
        sources[term_id] = REMAINING_UI.relative_to(PROJECT_ROOT).as_posix()

    display_path = UNITS_FULL
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
        item["name"] for item in pilot_skills if _t("技能等级") in item["effect"]
    }
    if set(skill_levels) != levelled_skill_names:
        missing = sorted(levelled_skill_names - set(skill_levels))
        extra = sorted(set(skill_levels) - levelled_skill_names)
        raise GuideBuildError(
            f"pilot-skill level table coverage drift: missing={missing}, extra={extra}"
        )
    seed = next(item for item in pilot_skills if item["name"] == skill_entries[71]["translation"])
    extended = next(item for item in pilot_skills if item["name"] == skill_entries[73]["translation"])
    if seed["name"] != "SEED" or _t("技能等级") in seed["effect"] or "1.1倍" not in seed["effect"]:
        raise GuideBuildError("SEED effect mapping drift")
    if _t("技能等级") not in extended["effect"] or _t("暴击率") not in extended["effect"]:
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


@functools.lru_cache(maxsize=1)
def _decoded_stages() -> tuple[Any, list[tuple[int, bytes, bytes, str, int, int, Any]]]:
    """Decode the original STAGE archive once; every edition reads the same disc."""

    layout = load_offset_layout(STAGE_LAYOUT)
    verify_archive(STAGE_ARCHIVE, layout)
    archive = STAGE_ARCHIVE.read_bytes()
    executable = SLPS.read_bytes()
    functions = read_stage_function_addresses(executable)
    table = load_text_table(TEXT_TABLE)
    stages = []
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
        stages.append(
            (stage_index, chunk, decoded, resource_name, resource_number,
             functions[stage_index], parsed)
        )
    return layout, stages


def parse_stage_resources() -> tuple[dict[int, list[dict[str, Any]]], dict[str, Any]]:
    """Build reproducible resource facts with this edition's condition text."""

    layout, stages = _decoded_stages()
    conditions = _condition_translations()
    resources: dict[int, list[dict[str, Any]]] = defaultdict(list)
    parsed_condition_ids: set[str] = set()

    for stage_index, chunk, decoded, resource_name, resource_number, function, parsed in stages:
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
                    "kind": _t({
                        "_Victory Conditions": "胜利条件",
                        "_Defeat Condtions": "失败条件",
                        "_SR Conditions": "SR点数条件",
                    }[entry.section]),
                    "text": conditions[entry.entry_id],
                    "pointer_offset": entry.pointer_offset,
                    "text_offset": entry.text_offset,
                }
            )
        resources[resource_number].append(
            {
                "archive_index": stage_index,
                "resource_name": resource_name,
                "function_address": f"0x{function:08X}",
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
    # The route map is written in Simplified; its titles are checked against
    # the Simplified corpus and each edition shows its own corpus title.
    simplified_titles = _load_stage_titles(PROJECT_ROOT / "corpus/zh/menu/stage-names.json")
    catalog: dict[int, dict[str, Any]] = {}
    for section in sections:
        for row in section["rows"]:
            for cell in row["cells"]:
                ordinal = cell["ordinal"]
                corpus = titles[ordinal]
                simplified = simplified_titles[ordinal]
                if simplified["translation"] != cell["title"]:
                    raise GuideBuildError(
                        f"route-map/corpus title drift at ordinal {ordinal}: "
                        f"{cell['title']!r} != {simplified['translation']!r}"
                    )
                if corpus["id"] != simplified["id"]:
                    raise GuideBuildError(f"{EDITION} stage-name id drift at ordinal {ordinal}")
                record = {
                    **cell,
                    "title": corpus["translation"],
                    "lane": _t(cell["lane"]),
                    "stage": row["stage"],
                    "section": _t(section["title"]),
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
        return f'<p class="empty">{_t("本关没有可显示的胜败／SR条件。")}</p>'
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
        f'<span class="block-dot"></span>{_t("本话隐藏进度")}</h4>'
        f'<ul class="hidden-list">{items}</ul></section>'
    )


def _lane_tone(lane: str, index: int, count: int) -> str:
    """Colour key of a route lane, from its Simplified source name."""
    if lane.startswith("节子"):
        return "setsuko"
    if lane.startswith("兰德"):
        return "rand"
    if count <= 1:
        return "common"
    return "a" if index == 0 else "b"


def _stage_card_html(
    record: dict[str, Any],
    hidden: dict[int, list[dict[str, str]]],
    progression: dict[int, dict[str, list[str]]],
    tone: str = "common",
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
            _simple_list_block(_t("加入／取得"), "acquisition", update["acquisitions"]),
            _simple_list_block(_t("临时参战"), "temporary", update["temporary"]),
            _simple_list_block(_t("离队／换机"), "availability", update["availability"]),
            _simple_list_block(_t("强化／新能力"), "upgrade", update["upgrades"]),
            _hidden_stage_block(hidden.get(ordinal, [])),
            _simple_list_block(
                _t("Akurasu 校正"), "correction", update["akurasu_corrections"]
            ),
        )
    )
    return f"""
    <article class="stage-card lane-{tone}" id="stage-{ordinal:03d}">
      <header class="stage-header"><span class="lane">{_esc(record['lane'])}</span>
      <h3>{_esc(record['title'])}</h3>
      <p class="source-title" lang="ja">{_esc(record['source_title'])}</p></header>
      <div class="stage-content">{content}</div>
    </article>"""


def _flow_html(
    sections: list[dict[str, Any]],
    catalog: dict[int, dict[str, Any]],
    hidden: dict[int, list[dict[str, str]]],
    progression: dict[int, dict[str, list[str]]],
) -> str:
    blocks = []
    ruler = []
    anchored: set[int] = set()
    for section_index, section in enumerate(sections, start=1):
        rows = []
        marks: dict[int, list[str]] = {}
        for row in section["rows"]:
            stage = row["stage"]
            cells = row["cells"]
            tones = [
                _lane_tone(cell["lane"], index, len(cells))
                for index, cell in enumerate(cells)
            ]
            cards = "".join(
                _stage_card_html(catalog[cell["ordinal"]], hidden, progression, tone)
                for cell, tone in zip(cells, tones)
            )
            anchor = "" if stage in anchored else f' id="flow-stage-{stage}"'
            anchored.add(stage)
            marks.setdefault(stage, []).extend(tones)
            rows.append(
                f'<div class="flow-row"{anchor} data-stage="{stage}" style="--lanes:{max(1, len(cells))}">'
                f'<div class="stage-number"><span>{_t("第")}</span><strong>{stage}</strong><span>{_t("话")}</span></div>'
                f'<div class="stage-lanes">{cards}</div></div>'
            )
        blocks.append(
            f'<section class="flow-section" id="flow-{section_index}">'
            f'<h2>{_esc(_t(section["title"]))}</h2>{"".join(rows)}</section>'
        )
        ruler.append(
            f'<span class="ruler-group" style="--n:{len(marks)}">'
            + "".join(
                f'<a href="#flow-stage-{stage}" data-stage="{stage}"><b>{stage}</b>'
                '<span class="ruler-dots">'
                + "".join(f'<i class="lane-{tone}"></i>' for tone in tones[:4])
                + "</span></a>"
                for stage, tones in marks.items()
            )
            + "</span>"
        )
    return (
        f'<nav class="stage-ruler" aria-label="{_t("流程图")}">'
        f'<div class="ruler-track">{"".join(ruler)}</div></nav>'
        + "".join(blocks)
    )


CATEGORY_LABELS = {
    "character": "隐藏人物",
    "unit": "隐藏机体",
    "weapon": "隐藏武器",
    "item": "隐藏强化零件",
    "system": "点数与结局",
}


def _category_label(category: str) -> str:
    return _t(CATEGORY_LABELS[category])

def _hidden_html(entries: list[dict[str, Any]]) -> str:
    cards = []
    for entry in entries:
        steps = []
        for step in entry["steps"]:
            stage = step.get("stage")
            when = _t("第{n}话").format(n=stage) if stage else step.get("when", _t("跨关条件"))
            if isinstance(stage, int) and 1 <= stage <= 60:
                label = f'<a class="when" href="#flow-stage-{stage}">{_esc(when)}</a>'
            else:
                label = f'<span class="when loose">{_esc(when)}</span>'
            steps.append(f'<li>{label}<p>{_esc(step["text"])}</p></li>')
        cards.append(
            f'<article class="secret-card" id="secret-{_esc(entry["id"])}" '
            f'data-category="{_esc(entry["category"])}">'
            f'<header class="secret-header"><div class="secret-kicker">{_esc(_category_label(entry["category"]))}</div>'
            f'<h3>{_esc(entry["title"])}</h3><p class="secret-summary">{_esc(entry.get("summary", ""))}</p></header>'
            f'<ol class="secret-steps">{"".join(steps)}</ol>'
            f'</article>'
        )
    return "".join(cards)


def _notice_html(values: list[str]) -> str:
    if not values:
        return ""
    return (
        '<aside class="reference-notice"><div class="reference-notice-title">'
        f'{_t("Akurasu 资料差异")}</div><ul>'
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
        f'<section class="reference-card"><h2>{_t("继承比例")}</h2><div class="rate-grid">{rates}</div></section>'
        f'<section class="reference-card"><h2>{_t("继承范围")}</h2><ul class="fact-list">{facts}</ul></section>'
        f'<section class="reference-card wide"><h2>{_t("通关模式")}</h2><div class="mode-grid">{modes}</div></section>'
        f'<section class="reference-card wide"><h2>{_t("容易弄错的规则")}</h2><ul class="note-list">{notes}</ul></section>'
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
        f'{_t("保留") if item["keeps_old"] else _t("替换")}</span>'
        + (f'<p class="cell-note">{_esc(item["note"])}</p>' if item.get("note") else "")
        + "</td></tr>"
        for item in reference["upgrade_carryover"]
    )
    notes = "".join(
        f"<li>{_esc(value)}</li>" for value in reference["upgrade_notes"]
    )
    return (
        '<div class="reference-shell one-column">'
        f'<section class="reference-card"><h2>{_t("剧情换机改造继承")}</h2>'
        f'<p class="section-lead">{_t("“保留”表示旧机仍在；“替换”表示旧机退出，由后继机接手改造。")}</p>'
        '<div class="table-wrap"><table class="reference-table carry-table"><thead><tr>'
        + "".join(f"<th>{_t(label)}</th>" for label in ("原机体", "继承到", "发生时间", "旧机"))
        + f'</tr></thead><tbody>{rows}</tbody></table></div></section>'
        f'<section class="reference-card"><h2>{_t("继承规则")}</h2><ul class="note-list">{notes}</ul></section>'
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
        f'<section class="reference-card"><h2>{_t("通用全改造奖励")}</h2><ul class="bonus-grid">{bonuses}</ul></section>'
        f'<section class="reference-card"><h2>{_t("选择规则")}</h2><ul class="note-list">{notes}</ul></section>'
        '</div>'
    )


def _rare_holders_html(item: dict[str, Any]) -> str:
    holders = item.get("holders", [])
    if not holders:
        return ""
    return (
        f'<div class="rare-meta"><span class="rare-badge">{_t("稀有")}</span>'
        f'<span>{_t("持有人：")}{_esc("、".join(holders))}</span></div>'
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
        f'<div class="skill-level-detail"><div class="skill-level-title">{_t("等级效果")}</div>'
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
        f'<p class="section-lead catalog-lead">{_t("成为小队长时生效；战舰舰长效果作用于相邻友军。标有“稀有”的效果，在可用／客串角色中仅有一人持有。")}</p>'
        f'<div class="catalog-grid">{groups}</div></section>'
        f'{_notice_html(catalogs["leadership_notices"])}</div>'
    )


def _bazaar_html(reference: dict[str, Any], catalogs: dict[str, Any]) -> str:
    part_rows = "".join(
        '<tr>'
        f'<td><strong>{_esc(item["name"])}</strong></td>'
        f'<td data-label="{_t("效果")}">{_esc(item["effect"])}</td>'
        f'<td class="number-cell" data-label="{_t("购买BS")}">{_esc(item["buy"])}</td>'
        f'<td class="number-cell" data-label="{_t("出售BS")}">{_esc(item["sell"])}</td>'
        '</tr>'
        for item in catalogs["bazaar_parts"]
    )
    unit_rows = "".join(
        '<tr>'
        f'<td><strong>{_esc(item["name"])}</strong></td>'
        f'<td class="number-cell" data-label="BS">{_esc(item["cost"])}</td>'
        f'<td data-label="{_t("出现时期")}">{_esc(item["availability"])}</td>'
        '</tr>'
        for item in reference["bazaar_units"]
    )
    notes = "".join(f'<li>{_esc(value)}</li>' for value in reference["bazaar_notes"])
    return (
        '<div class="reference-shell one-column">'
        f'<section class="reference-card"><h2>{_t("常规强化零件")}</h2>'
        '<div class="table-wrap"><table class="reference-table data-table"><thead><tr>'
        f'<th>{_t("物品")}</th><th>{_t("效果")}</th><th>{_t("购买BS")}</th><th>{_t("出售BS")}</th>'
        f'</tr></thead><tbody>{part_rows}</tbody></table></div></section>'
        f'<section class="reference-card"><h2>{_t("可购买机体")}</h2>'
        '<div class="table-wrap"><table class="reference-table data-table"><thead><tr>'
        f'<th>{_t("机体")}</th><th>BS</th><th>{_t("出现时期")}</th>'
        f'</tr></thead><tbody>{unit_rows}</tbody></table></div></section>'
        f'<section class="reference-card"><h2>{_t("购买规则")}</h2><ul class="note-list">{notes}</ul></section>'
        '</div>'
    )


def _team_attacks_html(reference: dict[str, Any]) -> str:
    rows = "".join(
        '<tr>'
        f'<td><strong>{_esc(item["name"])}</strong>'
        + (f'<p class="cell-note">{_esc(item["note"])}</p>' if item.get("note") else "")
        + '</td>'
        f'<td data-label="{_t("所需机体")}">{_esc(item["units"])}</td>'
        f'<td class="number-cell" data-label="{_t("气力")}">{_esc(item["morale"])}</td>'
        f'<td class="number-cell" data-label="{_t("射程")}">{_esc(item["range"])}</td>'
        '</tr>'
        for item in reference["team_attacks"]
    )
    notes = "".join(
        f'<li>{_esc(value)}</li>' for value in reference["team_attack_notes"]
    )
    return (
        '<div class="reference-shell one-column">'
        f'<section class="reference-card"><h2>{_t("合体攻击一览")}</h2>'
        '<div class="table-wrap"><table class="reference-table data-table"><thead><tr>'
        f'<th>{_t("攻击")}</th><th>{_t("所需机体")}</th><th>{_t("气力")}</th><th>{_t("射程")}</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div></section>'
        f'<section class="reference-card"><h2>{_t("使用规则")}</h2><ul class="note-list">{notes}</ul></section>'
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
    for token in map(_t, ("装甲值", "移动力", "获得干扰功能", "武器射程＋1", "武器CT修正")):
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
    weapon_ui = json.dumps(_json(WEAPONS_UI), ensure_ascii=False)
    for item in reference["team_attacks"]:
        if item["name"] not in weapon_ui:
            raise GuideBuildError(f"team attack missing from game weapon UI: {item['name']}")


_GUIDE_CSS = r"""
:root{color-scheme:light dark;
--font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC","Noto Sans SC","Source Han Sans SC",sans-serif;
--num:"DIN Alternate","Bahnschrift","Roboto Condensed","Arial Narrow",-apple-system,"Segoe UI",sans-serif;
--bg:#f5f2ea;--surface:#fffdf8;--surface-2:#efebe1;--ink:#17232b;--ink-2:#3d4b54;--muted:#5f6c75;--line:#dbd5c8;--line-soft:#e8e3d8;
--band:#10283b;--band-2:#173a54;--band-ink:#fff;--band-muted:rgba(255,255,255,.66);--band-line:rgba(255,255,255,.16);
--accent:#e96c2c;--accent-ink:#b03f12;--chip:#10283b;--chip-ink:#fff;--stage:#10283b;--stage-ink:#fff;
--join:#1c6a8e;--join-bg:#e3eff4;--temp:#6846a0;--temp-bg:#eee8f6;--leave:#b03f12;--leave-bg:#fae8dc;--up:#1f6b54;--up-bg:#e0efe9;--secret:#7d5a08;--secret-bg:#f6edd3;--secret-line:#e3cf94;--warn:#a8241c;--warn-bg:#fbe8e4;--warn-line:#efc0b9;
--lane-common:#6b7a84;--lane-setsuko:#2b7fa5;--lane-rand:#e96c2c;--lane-a:#2f8a6c;--lane-b:#8a63c2;
--tabs-h:48px;--bar-h:46px;--wide:1240px;--shadow:0 1px 2px rgba(16,40,59,.05),0 6px 18px rgba(16,40,59,.05)}
:lang(zh-Hans){--font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC","Noto Sans SC","Source Han Sans SC",sans-serif}
:lang(zh-Hant-TW){--font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Microsoft JhengHei","Noto Sans CJK TC","Noto Sans TC","Source Han Sans TC",sans-serif}
:lang(zh-Hant-HK){--font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang HK","Microsoft JhengHei","Noto Sans CJK HK","Noto Sans HK","Source Han Sans HK","PingFang TC","Noto Sans CJK TC",sans-serif}
:lang(ja){--font:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic","Meiryo","Noto Sans CJK JP","Noto Sans JP",sans-serif}
@media screen and (prefers-color-scheme:dark){:root{
--bg:#0a1620;--surface:#10212e;--surface-2:#172c3b;--ink:#ece7db;--ink-2:#c5cbce;--muted:#94a2ab;--line:#263c4d;--line-soft:#1c3040;
--band:#0d1f2d;--band-2:#14324a;--accent:#f0803f;--accent-ink:#ffa46e;--chip:#ece7db;--chip-ink:#0a1620;--stage:#1f3a4f;--stage-ink:#ece7db;
--join:#74c3e2;--join-bg:rgba(116,195,226,.12);--temp:#b9a0ee;--temp-bg:rgba(185,160,238,.13);--leave:#ffa46e;--leave-bg:rgba(255,164,110,.12);--up:#74d1ac;--up-bg:rgba(116,209,172,.12);--secret:#e6bd5e;--secret-bg:rgba(230,189,94,.11);--secret-line:rgba(230,189,94,.32);--warn:#ff938a;--warn-bg:rgba(255,147,138,.11);--warn-line:rgba(255,147,138,.34);
--lane-common:#7d8c96;--lane-setsuko:#4fa6cc;--lane-rand:#f0803f;--lane-a:#4fb391;--lane-b:#a384dc;--shadow:none}}
*{box-sizing:border-box}
html{background:var(--bg);-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:.9375rem;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none;-webkit-tap-highlight-color:transparent}
button{font:inherit;-webkit-tap-highlight-color:transparent}
h1,h2,h3,h4,p{margin:0}
a:focus-visible,button:focus-visible{outline:3px solid rgba(233,108,44,.45);outline-offset:2px}

/* heading band */
.guide-heading{position:relative;overflow:hidden;background:linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px) 0 0/32px 32px,linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px) 0 0/32px 32px,linear-gradient(120deg,var(--band),var(--band-2));color:var(--band-ink);border-bottom:1px solid var(--band-line)}
.guide-heading::after{content:"Z";position:absolute;right:max(12px,calc((100% - var(--wide))/2));top:50%;transform:translateY(-52%) skewX(-8deg);font:900 11rem/1 var(--num);color:transparent;-webkit-text-stroke:1.5px rgba(255,255,255,.1);pointer-events:none}
.guide-heading-inner{position:relative;z-index:1;display:flex;flex-wrap:wrap;align-items:center;gap:14px 28px;width:min(var(--wide),100% - 32px);margin:auto;padding:26px 0 24px}
.guide-title{flex:1 1 320px;min-width:0;padding-left:14px;border-left:4px solid var(--accent)}
.guide-title h1{font-size:1.5rem;line-height:1.25;font-weight:800;letter-spacing:.01em}
.guide-title p{margin-top:5px;color:var(--band-muted);font-size:.8rem}
.edition-switch{display:flex;padding:3px;border:1px solid var(--band-line);border-radius:10px;background:rgba(0,0,0,.18)}
.edition-switch a{padding:6px 12px;border-radius:7px;color:var(--band-muted);font-family:var(--font);font-size:.82rem;font-weight:600;line-height:1.3;white-space:nowrap}
.edition-switch a:hover{color:#fff}
.edition-switch a[aria-current=page]{background:#fff;color:#10283b}
.guide-actions{display:flex;flex-wrap:wrap;gap:8px}
.guide-actions a{display:inline-flex;align-items:center;min-height:36px;padding:0 14px;border:1px solid var(--band-line);border-radius:9px;color:#fff;font-size:.82rem;font-weight:650;white-space:nowrap}
.guide-actions a:hover{border-color:rgba(255,255,255,.5)}
.guide-actions a[download]{background:#e96c2c;border-color:#e96c2c}
.guide-actions a[download]:hover{background:#d65c1f;border-color:#d65c1f}
.guide-actions a[hidden]{display:none}

/* tabs */
.mode-tabs{position:sticky;top:0;z-index:30;display:flex;height:var(--tabs-h);padding:0 max(6px,calc((100% - var(--wide))/2 - 12px));overflow-x:auto;background:var(--surface);border-bottom:1px solid var(--line);scrollbar-width:none}
.mode-tabs::-webkit-scrollbar,.ruler-track::-webkit-scrollbar,.category-filters::-webkit-scrollbar{display:none}
.mode-tab{flex:0 0 auto;display:flex;align-items:center;padding:3px 13px 0;border-bottom:3px solid transparent;color:var(--muted);font-size:.9rem;font-weight:650;white-space:nowrap}
.mode-tab:hover{color:var(--ink)}
.mode-tab.active{color:var(--ink);border-bottom-color:var(--accent)}
.mode-tab:focus-visible{outline-offset:-3px}
main{width:min(var(--wide),100% - 32px);margin:0 auto 72px}
.guide-panel{scroll-margin-top:var(--tabs-h)}
.guide-panel[hidden]{display:none}
.is-hidden{display:none!important}

/* flow chart: stage ruler */
.stage-ruler,.category-filters{position:sticky;top:var(--tabs-h);z-index:20;margin:0 0 22px;background:var(--bg);border-bottom:1px solid var(--line)}
.ruler-track{position:relative;display:flex;height:var(--bar-h);overflow-x:auto;scrollbar-width:none}
.ruler-group{flex:var(--n) 1 0;display:flex;min-width:0;padding:0 5px}
.ruler-group:first-child{padding-left:0}.ruler-group:last-child{padding-right:0}
.ruler-group+.ruler-group{border-left:1px solid var(--line)}
.ruler-track a{flex:1 0 0;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;color:var(--muted);font:600 .8rem/1 var(--num);font-variant-numeric:tabular-nums}
.ruler-track b{display:grid;place-items:center;min-width:100%;height:22px;border-radius:6px;font-weight:inherit}
.ruler-track a:hover b{background:var(--surface-2);color:var(--ink)}
.ruler-track a.current b{background:var(--chip);color:var(--chip-ink);font-weight:700}
.ruler-dots{display:flex;gap:2px;height:4px}
.ruler-dots i{width:4px;height:4px;border-radius:50%;background:var(--tone)}
.lane-common{--tone:var(--lane-common)}.lane-setsuko{--tone:var(--lane-setsuko)}.lane-rand{--tone:var(--lane-rand)}.lane-a{--tone:var(--lane-a)}.lane-b{--tone:var(--lane-b)}

/* flow chart: rows */
.flow-section{margin:0 0 40px}
.flow-section h2{display:flex;align-items:center;gap:12px;margin:0 0 16px;font-size:1.05rem;line-height:1.35;font-weight:800}
.flow-section h2::after{content:"";flex:1;height:1px;background:var(--line)}
.flow-row{position:relative;display:grid;grid-template-columns:68px minmax(0,1fr);gap:0 14px;padding-bottom:12px;scroll-margin-top:calc(var(--tabs-h) + var(--bar-h) + 12px)}
.flow-row::before{content:"";position:absolute;left:33px;top:0;bottom:0;width:2px;background:var(--line)}
.flow-row:last-child{padding-bottom:0}
.stage-number{position:sticky;top:calc(var(--tabs-h) + var(--bar-h) + 12px);z-index:1;align-self:start;display:flex;align-items:baseline;justify-content:center;gap:1px;height:44px;padding-top:9px;border-radius:9px;background:var(--stage);color:var(--stage-ink);box-shadow:0 0 0 4px var(--bg)}
.stage-number strong{font:700 1.45rem/1 var(--num);font-variant-numeric:tabular-nums}
.stage-number span{font-size:.68rem;opacity:.72}
.stage-lanes{display:grid;grid-template-columns:repeat(var(--lanes),minmax(0,1fr));gap:12px}
.stage-card{min-width:0;background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--tone);border-radius:10px;box-shadow:var(--shadow);scroll-margin-top:calc(var(--tabs-h) + var(--bar-h) + 12px)}
.stage-header{padding:11px 16px 12px}
.lane{display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:.72rem;font-weight:700;letter-spacing:.03em}
.lane::before{content:"";width:8px;height:8px;border-radius:2px;background:var(--tone)}
.stage-card h3{margin-top:3px;font-size:1.06rem;line-height:1.4;font-weight:750}
.source-title{margin-top:1px;color:var(--muted);font-family:var(--font);font-size:.74rem}
.stage-content{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:14px 24px;padding:13px 16px 15px;border-top:1px solid var(--line-soft)}
.stage-content:empty{display:none}
.stage-block{min-width:0;--kind:var(--muted);--kind-bg:var(--surface-2)}
.acquisition{--kind:var(--join);--kind-bg:var(--join-bg)}.temporary{--kind:var(--temp);--kind-bg:var(--temp-bg)}.availability{--kind:var(--leave);--kind-bg:var(--leave-bg)}.upgrade{--kind:var(--up);--kind-bg:var(--up-bg)}.hidden-progress{--kind:var(--secret);--kind-bg:var(--secret-bg)}.correction{--kind:var(--warn);--kind-bg:var(--warn-bg)}
.stage-block h4{display:inline-flex;align-items:center;gap:6px;margin:0 0 5px;padding:2px 8px 2px 7px;border-radius:5px;background:var(--kind-bg);color:var(--kind);font-size:.74rem;line-height:1.5;font-weight:750}
.block-dot{width:6px;height:6px;border-radius:50%;background:var(--kind)}
.info-list,.hidden-list{list-style:none;margin:0;padding:0}
.info-list li{position:relative;padding:3px 0 3px 14px;font-size:.875rem;line-height:1.6}
.info-list li::before{content:"";position:absolute;left:2px;top:.84em;width:5px;height:2px;border-radius:1px;background:var(--kind);opacity:.7}
.hidden-progress,.correction{padding:10px 12px 11px;border:1px solid var(--secret-line);border-radius:8px;background:var(--kind-bg)}
.hidden-progress h4,.correction h4{padding:0;background:none}
.hidden-list li{padding:4px 0;font-size:.85rem;line-height:1.55}
.hidden-list li+li{margin-top:3px;border-top:1px dashed var(--secret-line);padding-top:7px}
.hidden-list a{color:var(--secret);font-weight:750;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
.hidden-list a::after{content:" →";font-weight:400}
.hidden-list p{margin-top:1px;color:var(--ink-2)}
.correction{grid-column:1/-1;border-color:var(--warn-line)}
.correction .info-list li{color:var(--ink)}
.empty{color:var(--muted);font-size:.8rem}
.stage-card:target,.secret-card:target{outline:2px solid var(--accent);outline-offset:2px}

/* hidden elements */
.category-filters{display:flex;align-items:center;gap:7px;height:var(--bar-h);overflow-x:auto;scrollbar-width:none}
.category-filters button{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink-2);cursor:pointer;font-size:.82rem;font-weight:650;white-space:nowrap}
.category-filters button:hover{border-color:var(--muted)}
.category-filters button.active{background:var(--chip);border-color:var(--chip);color:var(--chip-ink)}
.category-filters .count{font:600 .76rem/1 var(--num);opacity:.62}
[data-category=character]{--cat:var(--join)}[data-category=unit]{--cat:var(--leave)}[data-category=weapon]{--cat:var(--temp)}[data-category=item]{--cat:var(--up)}[data-category=system]{--cat:var(--secret)}
.category-filters button[data-category]:not([data-category=all])::before,.secret-kicker::before{content:"";width:8px;height:8px;border-radius:2px;background:var(--cat)}
.secret-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.secret-card{min-width:0;background:var(--surface);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);scroll-margin-top:calc(var(--tabs-h) + var(--bar-h) + 12px)}
.secret-header{padding:14px 18px 13px}
.secret-kicker{display:flex;align-items:center;gap:6px;color:var(--cat);font-size:.72rem;font-weight:750;letter-spacing:.03em}
.secret-card h3{margin-top:3px;font-size:1.08rem;line-height:1.4;font-weight:750}
.secret-summary{margin-top:5px;color:var(--ink-2);font-size:.85rem}
.secret-summary:empty{display:none}
.secret-steps{list-style:none;margin:0;padding:0 18px 8px}
.secret-steps>li{display:grid;grid-template-columns:4.6em minmax(0,1fr);gap:12px;align-items:baseline;padding:9px 0;border-top:1px solid var(--line-soft)}
.secret-steps p{font-size:.875rem;line-height:1.6}
.when{color:var(--join);font-size:.8rem;font-weight:750;white-space:nowrap;font-variant-numeric:tabular-nums}
a.when{text-decoration:underline;text-decoration-color:transparent;text-underline-offset:3px}
a.when:hover{text-decoration-color:currentColor}
.when.loose{color:var(--muted);white-space:normal}

/* reference panels */
.reference-shell{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;padding-top:22px}
.reference-shell.one-column{grid-template-columns:minmax(0,1fr)}
.reference-card,.reference-notice{min-width:0;padding:18px 20px 20px;background:var(--surface);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow)}
.reference-card.wide,.reference-notice{grid-column:1/-1}
.reference-card h2{display:flex;align-items:center;gap:9px;margin:0 0 14px;font-size:1.02rem;line-height:1.35;font-weight:800}
.reference-card h2::before{content:"";width:4px;height:1em;border-radius:2px;background:var(--accent)}
.section-lead{max-width:76ch;margin:-6px 0 14px;color:var(--ink-2);font-size:.85rem}
.catalog-lead{margin:0 0 16px}
.reference-card{display:flex;flex-direction:column}
.rate-grid{flex:1;display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.rate-card{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px 8px 14px;border-radius:9px;background:var(--surface-2)}
.rate-card strong{font:700 2rem/1 var(--num);color:var(--accent-ink)}
.rate-card span{margin-top:7px;color:var(--ink-2);font-size:.8rem;font-weight:600}
.fact-list,.note-list,.reference-notice ul,.bonus-grid{list-style:none;margin:0;padding:0}
.fact-list li{display:grid;grid-template-columns:6.5em minmax(0,1fr);gap:14px;padding:10px 0;border-top:1px solid var(--line-soft);font-size:.875rem}
.fact-list li:first-child{border-top:0;padding-top:0}
.fact-list strong{font-weight:750}
.fact-list span{color:var(--ink-2)}
.mode-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.mode-card{padding:14px 16px;border-radius:9px;background:var(--surface-2)}
.mode-card>div{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:4px 12px}
.mode-card h3{font:700 1.15rem/1.3 var(--num);letter-spacing:.03em}
.mode-card span{color:var(--join);font-size:.76rem;font-weight:650}
.mode-card p{margin-top:8px;color:var(--ink-2);font-size:.875rem}
.note-list li,.reference-notice li{position:relative;max-width:80ch;padding:5px 0 5px 16px;font-size:.875rem}
.note-list li::before,.reference-notice li::before{content:"";position:absolute;left:2px;top:.98em;width:6px;height:2px;border-radius:1px;background:var(--muted)}
.reference-notice{border-color:var(--warn-line);border-left:4px solid var(--warn);background:var(--warn-bg);box-shadow:none}
.reference-notice-title{margin-bottom:4px;color:var(--warn);font-size:.82rem;font-weight:800}
.reference-notice li::before{background:var(--warn)}
.bonus-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px}
.bonus-grid li{display:flex;align-items:center;gap:11px;padding:10px 13px;border-radius:9px;background:var(--surface-2);font-size:.875rem}
.bonus-grid li>span{color:var(--accent-ink);font:700 .95rem/1 var(--num)}
.bonus-grid strong{font-weight:650}
.catalog-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr));gap:10px}
.catalog-card{min-width:0;padding:13px 15px 14px;border:1px solid var(--line-soft);border-radius:9px;background:var(--bg)}
.reference-card:has(>.catalog-grid){padding:0;border:0;background:none;box-shadow:none}
.reference-card:has(>.catalog-grid) .catalog-card{border-color:var(--line);background:var(--surface);box-shadow:var(--shadow)}
.catalog-card h3{font-size:.95rem;line-height:1.4;font-weight:750}
.catalog-card p{margin-top:5px;color:var(--ink-2);font-size:.84rem;line-height:1.6;white-space:pre-line}
.rare-meta,.skill-note{display:flex;align-items:baseline;gap:7px;margin-top:9px;color:var(--ink-2);font-size:.78rem;line-height:1.5}
.rare-badge,.skill-note-badge{flex:0 0 auto;padding:0 6px;border-radius:4px;background:var(--secret-bg);color:var(--secret);font-size:.7rem;font-weight:750;line-height:1.6}
.skill-note-badge{background:var(--surface-2);color:var(--ink-2)}
.leadership-card ul{list-style:none;margin:8px 0 0;padding:0}
.leadership-card li{padding:7px 0;border-top:1px solid var(--line);color:var(--ink-2);font-size:.84rem;line-height:1.6;white-space:pre-line}
.leadership-card li:last-child{padding-bottom:0}
.leadership-card .rare-meta{margin-top:4px;white-space:normal}
.skill-level-detail{margin-top:12px}
.skill-level-title{margin-bottom:6px;color:var(--muted);font-size:.72rem;font-weight:750;letter-spacing:.04em}
.level-table-wrap{max-width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:7px;background:var(--surface)}
.level-table{width:100%;min-width:max-content;border-collapse:collapse;font-size:.76rem;font-variant-numeric:tabular-nums}
.level-table th{padding:5px 9px;background:var(--surface-2);color:var(--muted);font-size:.7rem;font-weight:650;text-align:left;white-space:nowrap}
.level-table td{padding:4px 9px;border-top:1px solid var(--line-soft);white-space:nowrap}
.level-note{margin-top:7px!important;color:var(--muted)!important;font-size:.76rem!important}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:9px}
.reference-table{width:100%;min-width:600px;border-collapse:collapse;font-size:.875rem}
.reference-table th{padding:8px 13px;background:var(--surface-2);color:var(--muted);font-size:.76rem;font-weight:700;text-align:left;white-space:nowrap}
.reference-table td{padding:10px 13px;border-top:1px solid var(--line-soft);vertical-align:top}
.reference-table td strong{font-weight:700}
.carry-table td:nth-child(1),.carry-table td:nth-child(2){width:25%}.carry-table td:nth-child(3){width:30%}
.data-table td{white-space:pre-line}
.data-table td:first-child{min-width:150px}
.number-cell{width:88px;white-space:nowrap!important;font-family:var(--num);font-variant-numeric:tabular-nums}
.carry-arrow{margin-right:8px;color:var(--accent-ink);font-weight:700}
.keep-badge{display:inline-flex;padding:1px 8px;border-radius:5px;font-size:.76rem;font-weight:750}
.keep-badge.yes{background:var(--up-bg);color:var(--up)}
.keep-badge.no{background:var(--surface-2);color:var(--ink-2)}
.cell-note{margin-top:4px;color:var(--muted);font-size:.78rem;font-weight:400}

@media(max-width:900px){.secret-grid{grid-template-columns:minmax(0,1fr)}.stage-lanes{grid-template-columns:repeat(min(var(--lanes),2),minmax(0,1fr))}}
@media(max-width:700px){
:root{--tabs-h:46px;--bar-h:46px}
main{width:calc(100% - 24px)}
.guide-heading::after{font-size:8rem;right:-6px}
.guide-heading-inner{width:calc(100% - 24px);gap:12px;padding:18px 0 16px}
.guide-title{flex-basis:100%}.guide-title h1{font-size:1.22rem}.guide-title p{font-size:.74rem}
.edition-switch a{padding:6px 10px}
.guide-actions a{min-height:34px;padding:0 11px}
.mode-tabs{padding:0 4px}.mode-tab{padding:3px 11px 0;font-size:.875rem}
.stage-ruler,.category-filters{margin:0 -12px 16px;padding:0 12px}
.ruler-group{flex:none;padding:0 4px}
.ruler-track a{flex:0 0 34px}
.flow-section{margin-bottom:30px}
.flow-section h2{margin-bottom:12px;font-size:1rem}
.flow-row{display:block;padding-bottom:16px}
.flow-row::before{display:none}
.stage-number{position:static;display:inline-flex;height:28px;margin-bottom:7px;padding:0 10px;align-items:center;gap:2px;border-radius:7px;box-shadow:none}
.stage-number strong{font-size:1.1rem}
.stage-lanes{grid-template-columns:minmax(0,1fr);gap:8px}
.stage-header{padding:10px 14px 11px}
.stage-content{padding:12px 14px 14px}
.secret-header{padding:13px 15px 12px}.secret-steps{padding:0 15px 6px}
.secret-steps>li{grid-template-columns:4.2em minmax(0,1fr);gap:10px}
.reference-shell{grid-template-columns:minmax(0,1fr);gap:12px;padding-top:16px}
.reference-card,.reference-notice{padding:15px 15px 16px}
.mode-grid{grid-template-columns:minmax(0,1fr)}
.rate-card strong{font-size:1.7rem}
.fact-list li{grid-template-columns:minmax(0,1fr);gap:2px}
.table-wrap{overflow:visible;border:0;border-radius:0}
.reference-table,.reference-table tbody{display:block;min-width:0}
.reference-table thead{display:none}
.reference-table tr{display:block;padding:12px 0;border-top:1px solid var(--line)}
.reference-table tr:first-child{border-top:0;padding-top:0}.reference-table tr:last-child{padding-bottom:0}
.reference-table td{display:block;width:auto!important;min-width:0!important;padding:0;border:0}
.data-table td:first-child{margin-bottom:5px;font-size:.95rem}
.data-table tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}
.data-table td{grid-column:1/-1}
.data-table td.number-cell{grid-column:auto}
.data-table td[data-label]{display:grid;grid-template-columns:4.6em minmax(0,1fr);gap:10px;align-items:baseline;padding:2px 0}
.data-table td[data-label]::before{content:attr(data-label);color:var(--muted);font-family:var(--font);font-size:.76rem;white-space:nowrap}
.carry-table tr{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 2px}
.carry-table td:nth-child(3){flex:1 1 100%;color:var(--ink-2);font-size:.84rem}
.carry-table td:nth-child(4){flex:1 1 100%;margin-top:3px}
.carry-arrow{margin:0 6px}
}
@media print{
:root{--bg:#fff;--surface:#fff;--shadow:none}
body{font-size:10.5pt}
.mode-tabs,.stage-ruler,.category-filters,.edition-switch,.guide-actions,.guide-heading::after{display:none!important}
.guide-heading{background:none;color:#000;border-bottom:2px solid #000}
.guide-heading-inner{width:100%;padding:0 0 8px}.guide-title p{color:#444}
main{width:100%;margin:0}
.guide-panel[hidden]{display:block}
.guide-panel{break-before:page}.guide-panel:first-child{break-before:auto}
.guide-panel::before{content:attr(data-title);display:block;margin:14px 0 10px;font-size:15pt;font-weight:800}
.is-hidden{display:block!important}
.stage-number{position:static;box-shadow:none;background:none;color:#000;border:1px solid #000}
.flow-row::before{display:none}
.stage-card,.secret-card,.catalog-card,.mode-card,.reference-notice,.reference-table tr{break-inside:avoid}
.flow-section h2,.reference-card h2{break-after:avoid}
.table-wrap,.level-table-wrap{overflow:visible}
a.when,.hidden-list a{text-decoration:none}
}
"""

_GUIDE_JS = r"""
if(location.protocol==='http:'||location.protocol==='https:')document.getElementById('review-site-link').hidden=false;
document.querySelectorAll('.edition-switch a[data-edition]').forEach(link=>link.addEventListener('click',()=>{link.href=link.getAttribute('href').split('#')[0]+location.hash;try{localStorage.setItem('srwz-review-locale',link.dataset.edition)}catch{}}));
(()=>{
const tabs=[...document.querySelectorAll('[data-panel]')];
const panels=[...document.querySelectorAll('[data-panel-content]')];
const categoryButtons=[...document.querySelectorAll('button[data-category]')];
const tabBar=document.querySelector('.mode-tabs');
let shown='flow';
function center(strip,item){if(strip&&item&&strip.scrollWidth>strip.clientWidth)strip.scrollLeft=item.offsetLeft-(strip.clientWidth-item.offsetWidth)/2;}
function selectCategory(category){
  categoryButtons.forEach(button=>button.classList.toggle('active',button.dataset.category===category));
  document.querySelectorAll('.secret-card').forEach(card=>card.classList.toggle('is-hidden',category!=='all'&&card.dataset.category!==category));
}
function selectPanel(){
  let target=null;
  try{target=location.hash.length>1?document.getElementById(decodeURIComponent(location.hash.slice(1))):null}catch{}
  const panel=target&&target.closest('[data-panel-content]');
  const name=panel?panel.dataset.panelContent:'flow';
  panels.forEach(item=>item.hidden=item.dataset.panelContent!==name);
  tabs.forEach(tab=>tab.classList.toggle('active',tab.dataset.panel===name));
  center(tabBar,tabs.find(tab=>tab.dataset.panel===name));
  if(target&&target!==panel){
    if(target.classList.contains('is-hidden'))selectCategory('all');
    requestAnimationFrame(()=>target.scrollIntoView());
  }else if(name!==shown&&tabBar&&window.scrollY>tabBar.offsetTop){
    window.scrollTo(0,tabBar.offsetTop);
  }
  shown=name;
}
window.addEventListener('hashchange',selectPanel);
categoryButtons.forEach(button=>button.addEventListener('click',()=>selectCategory(button.dataset.category)));
selectPanel();

const ruler=document.querySelector('.ruler-track');
if(ruler){
  const marks=new Map([...ruler.querySelectorAll('a[data-stage]')].map(mark=>[mark.dataset.stage,mark]));
  const rows=[...document.querySelectorAll('.flow-row[data-stage]')];
  let current=null;
  function mark(stage){
    if(stage===current)return;
    if(marks.has(current))marks.get(current).classList.remove('current');
    current=stage;
    const item=marks.get(stage);
    if(item){item.classList.add('current');center(ruler,item);}
  }
  ruler.addEventListener('click',event=>{
    const link=event.target.closest('a[data-stage]');
    const row=link&&document.getElementById(link.hash.slice(1));
    if(!row)return;
    event.preventDefault();
    row.scrollIntoView();
    mark(link.dataset.stage);
    try{history.replaceState(null,'',link.hash)}catch{}
  });
  if('IntersectionObserver' in window){
    const visible=new Set();
    const observer=new IntersectionObserver(entries=>{
      entries.forEach(entry=>entry.isIntersecting?visible.add(entry.target):visible.delete(entry.target));
      const first=rows.find(row=>visible.has(row));
      if(first)mark(first.dataset.stage);
    },{rootMargin:'-110px 0px -60% 0px'});
    rows.forEach(row=>observer.observe(row));
  }
}
})();
"""


GUIDE_TABS = (
    ("flow", "流程图"),
    ("hidden-elements", "隐藏要素"),
    ("carryover", "周目继承"),
    ("upgrade-carryover", "改造继承"),
    ("full-upgrade-bonus", "全改造奖励"),
    ("leadership", "小队长能力"),
    ("pilot-skills", "人物技能"),
    ("mech-abilities", "机体能力"),
    ("bazaar", "集市物品"),
    ("team-attacks", "合体攻击"),
)


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
        lead=_t("游戏内全部45项特殊技能及其实际效果。有等级的技能直接列出每级效果。不可通过PP购买、且我方常驻或可控客串角色中持有人去重后不超过5人的技能标为稀有；同一人物的化名与剧情形态合并计算。"),
        notices=catalogs["pilot_skill_notices"],
    )
    mech_abilities = _catalog_cards_html(
        catalogs["mech_abilities"],
        lead=_t("游戏内有名称的机体特殊能力。相同效果会按不同能力名分别列出。"),
        notices=reference["mech_ability_akurasu_issues"],
    )
    bazaar = _bazaar_html(reference, catalogs)
    team_attacks = _team_attacks_html(reference)
    edition = EDITIONS[EDITION]
    html_name = edition["html"]
    review_href = "/" if EDITION == "zh" else f"/?lang={EDITION}"
    edition_links = "".join(
        f'<a href="{_esc(item["html"])}" data-edition="{code}" hreflang="{_esc(item["lang"])}" lang="{_esc(item["lang"])}"'
        + (' aria-current="page"' if code == EDITION else "")
        + f'>{_esc(item["label"])}</a>'
        for code, item in EDITIONS.items()
    )
    tabs = "\n".join(
        f'  <a class="mode-tab{" active" if index == 0 else ""}" data-panel="{key}" href="#{key}">{_t(label)}</a>'
        for index, (key, label) in enumerate(GUIDE_TABS)
    )
    category_counts = {
        key: sum(entry["category"] == key for entry in hidden_entries)
        for key in CATEGORY_LABELS
    }
    filters = (
        f'<button class="active" data-category="all">{_t("全部")}'
        f'<span class="count">{len(hidden_entries)}</span></button>'
        + "".join(
            f'<button data-category="{key}">{_category_label(key)}'
            f'<span class="count">{category_counts[key]}</span></button>'
            for key in CATEGORY_LABELS
        )
    )
    panel_bodies = {
        "flow": flow,
        "hidden-elements": (
            f'<div class="category-filters">{filters}</div>'
            f'<div class="secret-grid">{secrets}</div>'
        ),
        "carryover": carryover,
        "upgrade-carryover": upgrade_carryover,
        "full-upgrade-bonus": full_upgrade_bonus,
        "leadership": leadership,
        "pilot-skills": pilot_skills,
        "mech-abilities": mech_abilities,
        "bazaar": bazaar,
        "team-attacks": team_attacks,
    }
    panels = "\n".join(
        f'  <section class="guide-panel" id="{key}" data-panel-content="{key}" '
        f'data-title="{_t(label)}"{"" if index == 0 else " hidden"}>{panel_bodies[key]}</section>'
        for index, (key, label) in enumerate(GUIDE_TABS)
    )
    return f"""<!doctype html>
<html lang="{edition['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#10283b" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d1f2d" media="(prefers-color-scheme: dark)">
<link rel="icon" href="data:,">
<title>{_t("《超级机器人大战Z》流程、隐藏要素与资料攻略")}</title>
<style>
{_GUIDE_CSS}
</style>
</head>
<body>
<header class="guide-heading"><div class="guide-heading-inner">
  <div class="guide-title"><h1>{_t("超级机器人大战 Z · 单页攻略")}</h1><p>{_t("更新：")}{_esc(reference['updated_on'])} · {_t("流程、隐藏要素与资料表 · 可离线阅读")}</p></div>
  <nav class="edition-switch" aria-label="{_t("攻略版本")}">{edition_links}</nav>
  <div class="guide-actions"><a id="review-site-link" href="{review_href}" hidden>{_t("返回审阅站")}</a><a href="{html_name}" download="{html_name}">{_t("下载离线攻略")}</a></div>
</div></header>
<nav class="mode-tabs" aria-label="{_t("攻略页面")}">
{tabs}
</nav>
<main>
{panels}
</main>
<script type="application/json" id="guide-manifest">{embedded}</script>
<script>{_GUIDE_JS}</script>
</body></html>
"""


def _structure_problems(source: Any, regional: Any, path: str) -> list[str]:
    """A regional guide file must mirror the Simplified one except its prose."""

    if type(source) is not type(regional):
        return [f"{path}: type differs"]
    if isinstance(source, dict):
        problems = [] if list(source) == list(regional) else [f"{path}: keys differ"]
        for key in source:
            if key in regional:
                problems += _structure_problems(source[key], regional[key], f"{path}.{key}")
        return problems
    if isinstance(source, list):
        problems = [] if len(source) == len(regional) else [f"{path}: length differs"]
        for index, (left, right) in enumerate(zip(source, regional)):
            problems += _structure_problems(left, right, f"{path}[{index}]")
        return problems
    if isinstance(source, str) and re.search(r"[\u3400-\u9fff]", source):
        if sorted(TERM_RE.findall(source)) != sorted(TERM_RE.findall(regional)):
            return [f"{path}: term placeholders differ"]
        # Every number must survive; a regional name may add its own (鐵甲萬能俠2號).
        missing = Counter(re.findall(r"\d+", source)) - Counter(re.findall(r"\d+", regional))
        if missing:
            return [f"{path}: numbers missing: {sorted(missing)}"]
        return []
    return [] if source == regional else [f"{path}: value differs"]


def _regional_data_status() -> dict[str, str]:
    """Check this edition's guide data against the Simplified files it was written from."""

    if EDITION == "zh":
        return {}
    recorded = _json(REGIONAL_SOURCES).get(EDITION, {}) if REGIONAL_SOURCES.is_file() else {}
    status = {}
    for name in GUIDE_DATA_NAMES:
        source_path = PROJECT_ROOT / "guide/data" / f"{name}.json"
        regional_path = PROJECT_ROOT / EDITIONS[EDITION]["data"] / f"{name}.json"
        if not regional_path.is_file():
            raise GuideBuildError(f"{EDITION} guide data missing: {regional_path.relative_to(PROJECT_ROOT)}")
        problems = _structure_problems(_json(source_path), _json(regional_path), name)
        if problems:
            raise GuideBuildError(
                f"{regional_path.relative_to(PROJECT_ROOT)} does not mirror guide/data/{name}.json: "
                + "; ".join(problems[:8])
            )
        source_hash = _sha256_file(source_path)
        if recorded.get(name) != source_hash:
            raise GuideBuildError(
                f"guide/data/{name}.json changed since its {EDITION} text was written; "
                f"update {regional_path.relative_to(PROJECT_ROOT)} by hand, then run "
                "python3 guide/build.py --accept-regional"
            )
        status[name] = source_hash
    return status


def accept_regional() -> None:
    """Record that every regional guide file matches the current Simplified file."""

    recorded: dict[str, dict[str, str]] = {}
    for code in EDITIONS:
        if code == "zh":
            continue
        _use_edition(code)
        recorded[code] = {}
        for name in GUIDE_DATA_NAMES:
            source_path = PROJECT_ROOT / "guide/data" / f"{name}.json"
            regional_path = PROJECT_ROOT / EDITIONS[code]["data"] / f"{name}.json"
            problems = _structure_problems(_json(source_path), _json(regional_path), name)
            if problems:
                raise GuideBuildError(f"{regional_path}: " + "; ".join(problems[:8]))
            recorded[code][name] = _sha256_file(source_path)
    _use_edition("zh")
    REGIONAL_SOURCES.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "SHA-256 of each Simplified guide data file the Taiwan / Hong Kong text was last written from.",
                **recorded,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _build_edition() -> tuple[str, dict[str, Any]]:
    regional_status = _regional_data_status()
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
        Path(__file__).resolve(),
        WEAPONS_UI,
        UNITS_FULL,
        *sorted(GLOSSARY_DIR.glob("*.json")),
        *((UI_STRINGS, REGIONAL_SOURCES) if EDITION != "zh" else ()),
    ]
    manifest = {
        "schema_version": 1,
        "generator": "guide/build.py",
        "edition": EDITION,
        **({"simplified_sources": regional_status} if regional_status else {}),
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
    return html_text, manifest


def build() -> dict[Path, bytes]:
    """Build every edition: one self-contained HTML each plus the Simplified manifest."""

    outputs: dict[Path, bytes] = {}
    editions: dict[str, Any] = {}
    simplified_manifest: dict[str, Any] | None = None
    try:
        for code, edition in EDITIONS.items():
            _use_edition(code)
            html_text, manifest = _build_edition()
            payload = html_text.encode("utf-8")
            outputs[GUIDE_DIR / edition["html"]] = payload
            editions[code] = {
                "html": edition["html"],
                "sha256": _sha256_bytes(payload),
                "used_global_term_count": manifest["coverage"]["used_global_term_count"],
            }
            if code == "zh":
                simplified_manifest = manifest
    finally:
        _use_edition("zh")
    assert simplified_manifest is not None
    simplified_manifest["editions"] = editions
    outputs[DEFAULT_MANIFEST] = (
        json.dumps(simplified_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if checked-in outputs are stale"
    )
    parser.add_argument(
        "--accept-regional",
        action="store_true",
        help="record that the Taiwan / Hong Kong guide data match the current Simplified files",
    )
    args = parser.parse_args()
    if args.accept_regional:
        accept_regional()
        print(f"recorded {REGIONAL_SOURCES.relative_to(PROJECT_ROOT)}")
    outputs = tuple(build().items())
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
