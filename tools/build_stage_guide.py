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
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.archive import load_offset_layout, slice_archive, verify_archive  # noqa: E402
from srwz.codec import decode_production  # noqa: E402
from srwz.stage import parse_stage, read_stage_function_addresses  # noqa: E402
from srwz.text import load_text_table  # noqa: E402


ROUTE_MAP = PROJECT_ROOT / "docs/STAGE_ROUTE_MAP.md"
STAGE_NAMES = PROJECT_ROOT / "corpus/zh/menu/stage-names.json"
STAGE_CONDITIONS = PROJECT_ROOT / "corpus/zh/story-conditions.json"
HIDDEN_ELEMENTS = PROJECT_ROOT / "guide/data/hidden-elements.json"
PROGRESSION = PROJECT_ROOT / "guide/data/progression.json"
STAGE_LAYOUT = PROJECT_ROOT / "config/stage-offsets.json"
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

    return walk(entries), used


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
    entries: list[dict[str, Any]], catalog: dict[int, dict[str, Any]]
) -> dict[int, dict[str, list[str]]]:
    attached: dict[int, dict[str, list[str]]] = defaultdict(
        lambda: {
            "acquisitions": [],
            "upgrades": [],
            "akurasu_corrections": [],
        }
    )
    allowed = {"acquisitions", "upgrades", "akurasu_corrections"}
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
                attached[ordinal][key].extend(entry.get(key, []))
    return dict(attached)


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


def _simple_list_block(label: str, kind: str, values: list[str]) -> str:
    if not values:
        return ""
    items = "".join(f"<li>{_esc(value)}</li>" for value in values)
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
        {"acquisitions": [], "upgrades": [], "akurasu_corrections": []},
    )
    content = "".join(
        (
            _simple_list_block("加入／取得", "acquisition", update["acquisitions"]),
            _simple_list_block("强化／新能力", "upgrade", update["upgrades"]),
            _hidden_stage_block(hidden.get(ordinal, [])),
            '<section class="stage-block conditions-block"><h4>'
            '<span class="block-dot"></span>胜败／SR条件</h4>'
            f'{_conditions_html(record["resources"])}</section>',
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


def _render_html(
    sections: list[dict[str, Any]],
    catalog: dict[int, dict[str, Any]],
    hidden_entries: list[dict[str, Any]],
    hidden_by_stage: dict[int, list[dict[str, str]]],
    progression_by_stage: dict[int, dict[str, list[str]]],
    manifest: dict[str, Any],
) -> str:
    embedded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    flow = _flow_html(sections, catalog, hidden_by_stage, progression_by_stage)
    secrets = _hidden_html(hidden_entries)
    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>《超级机器人大战Z》流程与隐藏要素攻略</title>
<style>
:root{{--background:#f8fafc;--foreground:#0f172a;--card:#fff;--muted:#64748b;--muted-bg:#f1f5f9;--border:#e2e8f0;--primary:#0f172a;--blue:#2563eb;--blue-bg:#eff6ff;--green:#15803d;--green-bg:#f0fdf4;--amber:#a16207;--amber-bg:#fffbeb;--red:#b91c1c;--red-bg:#fef2f2;--ring:rgba(37,99,235,.18);--shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.04)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;background:var(--background)}}body{{margin:0;background:var(--background);color:var(--foreground);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC","Microsoft YaHei",sans-serif;line-height:1.55;-webkit-font-smoothing:antialiased}}
a{{color:inherit;text-decoration:none}}button{{font:inherit}}.mode-tabs{{position:sticky;top:0;z-index:20;display:grid;grid-template-columns:1fr 1fr;height:52px;background:rgba(255,255,255,.94);border-bottom:1px solid var(--border);backdrop-filter:blur(12px)}}.mode-tab{{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:.92rem;font-weight:650;border-bottom:2px solid transparent;transition:.15s ease}}.mode-tab:hover{{background:var(--muted-bg);color:var(--foreground)}}.mode-tab.active{{color:var(--foreground);border-bottom-color:var(--foreground)}}main{{width:min(1280px,calc(100% - 32px));margin:22px auto 64px}}.guide-panel[hidden]{{display:none}}
.flow-section{{margin:0 0 42px}}.flow-section h2{{margin:0 0 12px;padding:0 2px 9px;border-bottom:1px solid var(--border);font-size:.8rem;line-height:1.2;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}}.flow-row{{display:grid;grid-template-columns:56px 1fr;gap:10px;margin:0 0 10px;align-items:stretch}}.stage-number{{position:sticky;top:62px;align-self:start;min-height:78px;border:1px solid var(--border);border-radius:10px;background:var(--card);display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1;box-shadow:0 1px 2px rgba(15,23,42,.03)}}.stage-number strong{{font-size:1.35rem;font-variant-numeric:tabular-nums}}.stage-number span{{font-size:.65rem;color:var(--muted);margin:2px 0}}.stage-lanes{{display:grid;grid-template-columns:repeat(var(--lanes),minmax(0,1fr));gap:10px}}.stage-card,.secret-card{{background:var(--card);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow)}}.stage-card{{overflow:hidden;scroll-margin-top:62px}}.stage-header{{padding:14px 16px 12px;border-bottom:1px solid var(--border)}}.lane{{display:inline-flex;align-items:center;min-height:22px;padding:2px 8px;border:1px solid #bfdbfe;border-radius:999px;background:var(--blue-bg);color:#1d4ed8;font-size:.7rem;font-weight:650}}.stage-card h3,.secret-card h3{{margin:7px 0 0;font-size:1rem;line-height:1.35;letter-spacing:-.01em}}.source-title{{margin:2px 0 0;color:var(--muted);font-size:.75rem}}.stage-content{{padding:4px 16px 10px}}.stage-block{{padding:11px 0;border-top:1px solid var(--border)}}.stage-block:first-child{{border-top:0}}.stage-block h4{{display:flex;align-items:center;gap:7px;margin:0 0 6px;font-size:.76rem;line-height:1.25;font-weight:700;color:var(--muted)}}.block-dot{{width:7px;height:7px;border-radius:999px;background:var(--muted)}}.acquisition h4{{color:var(--blue)}}.acquisition .block-dot{{background:var(--blue)}}.upgrade h4{{color:var(--green)}}.upgrade .block-dot{{background:var(--green)}}.hidden-progress h4{{color:var(--amber)}}.hidden-progress .block-dot{{background:var(--amber)}}.conditions-block .block-dot{{background:var(--foreground)}}.correction{{margin:5px -8px 2px;padding:10px 8px;border:1px solid #fecaca!important;border-radius:8px;background:var(--red-bg)}}.correction h4{{color:var(--red)}}.correction .block-dot{{background:var(--red)}}.info-list,.hidden-list,.conditions{{list-style:none;padding:0;margin:0}}.info-list li,.hidden-list li,.conditions li{{position:relative;padding:4px 0 4px 13px;font-size:.81rem;line-height:1.55}}.info-list li::before,.hidden-list li::before,.conditions li::before{{content:"";position:absolute;left:1px;top:.78rem;width:3px;height:3px;border-radius:50%;background:#94a3b8}}.hidden-list a{{color:#92400e;font-weight:650;text-decoration:underline;text-decoration-color:#fde68a;text-underline-offset:3px}}.hidden-list p{{margin:2px 0 0;color:#475569}}.conditions li{{display:grid;grid-template-columns:78px 1fr;gap:7px}}.condition-kind{{font-weight:650;color:var(--muted)}}.empty{{margin:0;color:var(--muted);font-size:.78rem}}
#flow,#hidden-elements{{scroll-margin-top:62px}}.category-filters{{position:sticky;top:52px;z-index:10;display:flex;flex-wrap:wrap;gap:7px;margin:0 0 14px;padding:10px 0;background:linear-gradient(var(--background) 78%,transparent)}}.category-filters button{{min-height:34px;padding:5px 11px;border:1px solid var(--border);border-radius:8px;background:var(--card);color:var(--muted);cursor:pointer;font-size:.78rem;font-weight:600;box-shadow:0 1px 2px rgba(15,23,42,.02)}}.category-filters button:hover{{color:var(--foreground);border-color:#cbd5e1}}.category-filters button.active{{background:var(--primary);color:white;border-color:var(--primary)}}.category-filters button:focus-visible,.mode-tab:focus-visible{{outline:3px solid var(--ring);outline-offset:-2px}}.secret-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.secret-card{{padding:17px 18px;scroll-margin-top:106px}}.secret-kicker{{display:inline-flex;padding:2px 7px;border-radius:999px;background:var(--amber-bg);color:var(--amber);font-size:.68rem;font-weight:700}}.secret-summary{{color:var(--muted);font-size:.82rem;margin:7px 0 12px}}.secret-steps{{padding:0;margin:0;list-style:none;counter-reset:secret-step}}.secret-steps>li{{position:relative;padding:10px 0 10px 38px;border-top:1px solid var(--border);counter-increment:secret-step}}.secret-steps>li::before{{content:counter(secret-step);position:absolute;left:0;top:10px;display:grid;place-items:center;width:24px;height:24px;border:1px solid var(--border);border-radius:7px;background:var(--muted-bg);color:var(--muted);font-size:.7rem;font-weight:700}}.secret-steps p{{margin:4px 0 0;font-size:.82rem}}.step-head{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}}.when{{display:inline-flex;padding:1px 7px;border-radius:999px;background:var(--blue-bg);color:#1d4ed8;font-size:.68rem;font-weight:700}}.is-hidden{{display:none!important}}
@media(max-width:900px){{.stage-lanes,.secret-grid{{grid-template-columns:1fr}}}}
@media(max-width:620px){{main{{width:min(100% - 16px,1280px);margin-top:12px}}.flow-row{{grid-template-columns:42px 1fr;gap:7px}}.stage-number{{top:59px;min-height:68px;border-radius:9px}}.stage-number strong{{font-size:1.12rem}}.stage-header{{padding:12px 13px 10px}}.stage-content{{padding:3px 13px 8px}}.conditions li{{display:block}}.condition-kind{{display:block;margin-bottom:1px}}.secret-card{{padding:15px}}}}
@media print{{.mode-tabs,.category-filters{{display:none}}body{{background:white}}main{{width:100%;margin:0}}.guide-panel[hidden]{{display:block}}.stage-card,.secret-card{{box-shadow:none;break-inside:avoid}}.stage-number{{position:static}}}}
</style>
</head>
<body>
<nav class="mode-tabs" aria-label="攻略页面">
  <a class="mode-tab active" data-panel="flow" href="#flow">流程图</a>
  <a class="mode-tab" data-panel="hidden-elements" href="#hidden-elements">隐藏要素</a>
</nav>
<main>
  <section class="guide-panel" id="flow" data-panel-content="flow">{flow}</section>
  <section class="guide-panel" id="hidden-elements" data-panel-content="hidden-elements" hidden><div class="category-filters"><button class="active" data-category="all">全部</button>{''.join(f'<button data-category="{key}">{label}</button>' for key,label in CATEGORY_LABELS.items())}</div><div class="secret-grid">{secrets}</div></section>
</main>
<script type="application/json" id="guide-manifest">{embedded}</script>
<script>
(()=>{{const tabs=[...document.querySelectorAll('[data-panel]')];const panels=[...document.querySelectorAll('[data-panel-content]')];const categoryButtons=[...document.querySelectorAll('button[data-category]')];function selectPanel(){{const hash=location.hash;const name=hash==='#hidden-elements'||hash.startsWith('#secret-')?'hidden-elements':'flow';panels.forEach(panel=>panel.hidden=panel.dataset.panelContent!==name);tabs.forEach(tab=>tab.classList.toggle('active',tab.dataset.panel===name));if(hash.startsWith('#secret-'))requestAnimationFrame(()=>document.querySelector(hash)?.scrollIntoView());}}function selectCategory(category){{categoryButtons.forEach(button=>button.classList.toggle('active',button.dataset.category===category));document.querySelectorAll('.secret-card').forEach(card=>card.classList.toggle('is-hidden',category!=='all'&&card.dataset.category!==category));}}window.addEventListener('hashchange',selectPanel);categoryButtons.forEach(button=>button.addEventListener('click',()=>selectCategory(button.dataset.category)));selectPanel();}})();
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
    progression_by_stage = _attach_progression(progression_entries, catalog)
    used_terms = hidden_terms | progression_terms
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
        HIDDEN_ELEMENTS,
        PROGRESSION,
        STAGE_LAYOUT,
        STAGE_ARCHIVE,
        SLPS,
        TEXT_TABLE,
    ]
    manifest = {
        "schema_version": 1,
        "generator": "tools/build_stage_guide.py",
        "source_policy": hidden_source.get("source_policy", {}),
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
            "akurasu_correction_card_count": sum(
                len(entry["akurasu_corrections"])
                for entry in progression_by_stage.values()
            ),
            "evidence_level_counts": dict(sorted(evidence_counts.items())),
            "used_global_term_count": len(used_terms),
        },
        "terminology": {
            "used_ids": sorted(used_terms),
            "sources": {term_id: term_sources[term_id] for term_id in sorted(used_terms)},
        },
        "resources": {
            f"{number:03d}": resources[number] for number in range(1, 108)
        },
    }
    html_text = _render_html(
        sections,
        catalog,
        hidden_entries,
        hidden_by_stage,
        progression_by_stage,
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
