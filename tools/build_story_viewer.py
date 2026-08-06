#!/usr/bin/env python3
"""Build a self-contained, local SRWZ story-text viewer.

The viewer deliberately keeps two orderings separate:

* ``route_groups`` comes from the human-reviewed route map and is used as a
  navigation/reference catalogue.
* ``resource_stages`` comes from the clean-room story dialogue queue and is
  the exact order in which the text resources are displayed.

The route map documents that Stage Name ordinals are not story resource file
numbers.  Keeping these datasets separate is therefore a correctness
requirement, not merely a presentation choice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = ROOT / "work/review/local-model/story-dialogue-unique.jsonl"
DEFAULT_ROUTE_MAP = ROOT / "docs/STAGE_ROUTE_MAP.md"
DEFAULT_STAGE_NAMES = ROOT / "corpus/zh/menu/stage-names.json"
DEFAULT_CORPUS = ROOT / "work/corpus/srwz-corpus.jsonl"
DEFAULT_SPEAKERS = ROOT / "corpus/zh/story-speakers.json"
DEFAULT_VALIDATED = ROOT / "work/review/local-model/validated/story-dialogue-validated.jsonl"
DEFAULT_SAMPLE = ROOT / "work/review/local-model/lmstudio-samples/story-dialogue-sample.jsonl"
TEMPLATE_DIR = ROOT / "tools/story_viewer"
DEFAULT_OUTPUT = ROOT / "work/review/local-model/story-viewer"

TITLE_RE = re.compile(
    r"\[(?P<ordinal>\d{3})\]\s*(?P<title>.*?)(?:（日：(?P<source>.*?)）)?\s*$"
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic path
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            rows.append(value)
    return rows


def split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def is_markdown_separator(line: str) -> bool:
    cells = split_markdown_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def parse_title_cell(cell: str) -> dict[str, Any] | None:
    """Parse a route-map title cell without changing its editorial text."""

    clean = cell.replace("`", "").strip()
    match = TITLE_RE.search(clean)
    if not match:
        return None
    title = match.group("title").strip()
    source = (match.group("source") or "").strip()
    return {
        "ordinal": int(match.group("ordinal")),
        "title": title,
        "source_title": source,
        "raw": clean,
    }


def parse_route_map(path: Path = DEFAULT_ROUTE_MAP) -> list[dict[str, Any]]:
    """Parse the route-map tables into JSON-friendly data.

    This is intentionally a small Markdown-table parser tailored to the
    repository's documented route map.  It retains every cell and only adds
    structured title metadata when a cell contains ``[NNN]``.
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    groups: list[dict[str, Any]] = []
    heading = "路线目录"
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            heading = line[3:].strip()
            index += 1
            continue
        if not (line.startswith("|") and index + 1 < len(lines) and is_markdown_separator(lines[index + 1])):
            index += 1
            continue

        headers = split_markdown_row(line)
        rows: list[dict[str, Any]] = []
        index += 2
        while index < len(lines) and lines[index].startswith("|"):
            cells = split_markdown_row(lines[index])
            if len(cells) == len(headers):
                titles = [parse_title_cell(cell) for cell in cells]
                ordinal: int | None = None
                if cells and re.fullmatch(r"\d+", cells[0].strip()):
                    ordinal = int(cells[0].strip())
                rows.append({"cells": cells, "titles": titles, "ordinal": ordinal})
            index += 1
        groups.append({"heading": heading, "headers": headers, "rows": rows})
    return groups


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_stage_and_speaker_id(identifier: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"story/(\d+)/speaker/(\d+)", identifier)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_stage_and_ordinal(identifier: str) -> int | None:
    match = re.fullmatch(r"menu/Compdata/03/(\d+)", identifier)
    return int(match.group(1)) if match else None


def load_speaker_maps(
    corpus_path: Path = DEFAULT_CORPUS,
    translations_path: Path = DEFAULT_SPEAKERS,
) -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], dict[str, Any]]]:
    """Return source speaker names and their current Chinese entries."""

    source_names: dict[tuple[int, int], str] = {}
    if corpus_path.exists():
        with corpus_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("domain") != "story" or record.get("kind") != "speaker":
                    continue
                key = parse_stage_and_speaker_id(str(record.get("id", "")))
                if key is not None:
                    source_names[key] = str(record.get("source_text", ""))

    translated: dict[tuple[int, int], dict[str, Any]] = {}
    if translations_path.exists():
        document = json.loads(translations_path.read_text(encoding="utf-8"))
        for entry in document.get("entries", []):
            key = parse_stage_and_speaker_id(str(entry.get("id", "")))
            if key is not None:
                translated[key] = {
                    "translation": str(entry.get("translation", "")),
                    "status": str(entry.get("editorial_status", "")),
                }
    return source_names, translated


def load_stage_titles(
    stage_names_path: Path = DEFAULT_STAGE_NAMES,
    corpus_path: Path = DEFAULT_CORPUS,
) -> dict[int, dict[str, Any]]:
    """Load translated Stage Name entries and their source Japanese text."""

    titles: dict[int, dict[str, Any]] = {}
    if stage_names_path.exists():
        document = json.loads(stage_names_path.read_text(encoding="utf-8"))
        for entry in document.get("entries", []):
            ordinal = parse_stage_and_ordinal(str(entry.get("id", "")))
            if ordinal is not None:
                titles[ordinal] = {
                    "ordinal": ordinal,
                    "source_title": "",
                    "translation": str(entry.get("translation", "")),
                    "status": str(entry.get("editorial_status", "")),
                    "notes": str(entry.get("notes", "")),
                }
    if corpus_path.exists():
        with corpus_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("domain") != "menu" or record.get("section") != "Stage Name":
                    continue
                ordinal = record.get("ordinal")
                if not isinstance(ordinal, int):
                    continue
                titles.setdefault(ordinal, {"ordinal": ordinal, "translation": "", "status": "", "notes": ""})
                titles[ordinal]["source_title"] = str(record.get("source_text", ""))
    return dict(sorted(titles.items()))


def load_machine_translations(
    validated_path: Path = DEFAULT_VALIDATED,
    sample_path: Path = DEFAULT_SAMPLE,
) -> dict[tuple[int, int, str], dict[str, Any]]:
    """Load model drafts without replacing committed reviewed translations."""

    drafts: dict[tuple[int, int, str], dict[str, Any]] = {}
    paths: list[Path] = [validated_path, sample_path]
    for path in paths:
        if not path.exists():
            continue
        for row in load_jsonl(path):
            if path == validated_path and row.get("decision_source") == "committed_reviewed":
                continue
            translation = str(row.get("translation", "")).strip()
            if not translation:
                continue
            key = (int(row.get("stage_index")), int(row.get("unique_index")), str(row.get("source_text_sha256", "")))
            drafts[key] = {
                "translation": translation,
                "notes": str(row.get("notes", "")),
            }
    return drafts


def display_status(row: dict[str, Any], machine_translation: str) -> str:
    existing = str(row.get("existing_translation", "")).strip()
    review_state = str(row.get("review_state", ""))
    editorial_status = str(row.get("existing_editorial_status", ""))
    if existing and (review_state == "locked_reviewed" or editorial_status == "reviewed"):
        return "已审校"
    if existing:
        return "已有译文"
    if machine_translation:
        return "机器草稿"
    return "待翻译"


def compact_entry(
    row: dict[str, Any],
    speaker_sources: dict[tuple[int, int], str],
    speaker_translations: dict[tuple[int, int], dict[str, Any]],
    machine_drafts: dict[tuple[int, int, str], dict[str, Any]],
) -> dict[str, Any]:
    stage = int(row["stage_index"])
    unique_index = int(row["unique_index"])
    source_hash = str(row["source_text_sha256"])
    machine = machine_drafts.get((stage, unique_index, source_hash), {})
    machine_translation = str(machine.get("translation", ""))
    speakers: list[dict[str, Any]] = []
    for speaker_id in row.get("speaker_ids", []):
        key = (stage, int(speaker_id))
        translated = speaker_translations.get(key, {})
        speakers.append(
            {
                "id": int(speaker_id),
                "source": speaker_sources.get(key, ""),
                "translation": str(translated.get("translation", "")),
                "status": str(translated.get("status", "")),
            }
        )
    existing = str(row.get("existing_translation", ""))
    status = display_status(row, machine_translation)
    return {
        "unique_index": unique_index,
        "source_hash": source_hash,
        "source_text": str(row.get("source_text", "")),
        "occurrence_count": int(row.get("occurrence_count", len(row.get("occurrence_ids", [])))),
        "occurrence_ids": list(row.get("occurrence_ids", [])),
        "sections": list(row.get("sections", [])),
        "speakers": speakers,
        "existing_translation": existing,
        "machine_translation": machine_translation,
        "machine_notes": str(machine.get("notes", "")),
        "display_translation": existing if existing.strip() else machine_translation,
        "display_status": status,
        "source_quote_shape": str(row.get("source_quote_shape", "")),
        "structural_tokens": list(row.get("structural_tokens", [])),
    }


def build_viewer_data(
    queue_path: Path = DEFAULT_QUEUE,
    route_map_path: Path = DEFAULT_ROUTE_MAP,
    stage_names_path: Path = DEFAULT_STAGE_NAMES,
    corpus_path: Path = DEFAULT_CORPUS,
    speakers_path: Path = DEFAULT_SPEAKERS,
    validated_path: Path = DEFAULT_VALIDATED,
    sample_path: Path = DEFAULT_SAMPLE,
) -> dict[str, Any]:
    if not queue_path.exists():
        raise FileNotFoundError(
            f"missing {queue_path}; run tools/export_story_dialogue_local_model_batch.py first"
        )
    queue = load_jsonl(queue_path)
    speaker_sources, speaker_translations = load_speaker_maps(corpus_path, speakers_path)
    machine_drafts = load_machine_translations(validated_path, sample_path)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in queue:
        grouped[int(row["stage_index"])].append(row)

    resource_stages: list[dict[str, Any]] = []
    counts = {"unique": 0, "occurrences": 0, "reviewed": 0, "existing": 0, "machine": 0, "missing": 0}
    for stage_index in sorted(grouped):
        entries = [
            compact_entry(row, speaker_sources, speaker_translations, machine_drafts)
            for row in sorted(grouped[stage_index], key=lambda item: int(item["unique_index"]))
        ]
        sections: list[dict[str, Any]] = []
        section_map: dict[str, dict[str, Any]] = {}
        for entry in entries:
            section_name = entry["sections"][0] if entry["sections"] else "未分段"
            section = section_map.get(section_name)
            if section is None:
                section = {"name": section_name, "entries": []}
                section_map[section_name] = section
                sections.append(section)
            section["entries"].append(entry)
            counts["unique"] += 1
            counts["occurrences"] += entry["occurrence_count"]
            if entry["display_status"] == "已审校":
                counts["reviewed"] += 1
            if entry["existing_translation"].strip():
                counts["existing"] += 1
            elif entry["machine_translation"].strip():
                counts["machine"] += 1
            else:
                counts["missing"] += 1
        resource_stages.append(
            {
                "stage_index": stage_index,
                "label": f"资源 {stage_index:03d}",
                "unique_count": len(entries),
                "occurrence_count": sum(entry["occurrence_count"] for entry in entries),
                "reviewed_count": sum(entry["display_status"] == "已审校" for entry in entries),
                "translated_count": sum(bool(entry["display_translation"].strip()) for entry in entries),
                "missing_count": sum(not bool(entry["display_translation"].strip()) for entry in entries),
                "preview": next((entry["display_translation"].replace("\n", " ") for entry in entries if entry["display_translation"].strip()), ""),
                "sections": sections,
            }
        )

    return {
        "schema_version": 1,
        "source": {
            "queue": str(queue_path.relative_to(ROOT)),
            "queue_sha256": file_sha256(queue_path),
            "route_map": str(route_map_path.relative_to(ROOT)),
            "ordering_note": "路线标题使用 Stage Name ordinal；正文按 story/NNN 资源号顺序展示，两者不作一对一映射。",
        },
        "counts": {
            **counts,
            "resource_stages": len(resource_stages),
            "route_groups": len(parse_route_map(route_map_path)),
        },
        "stage_titles": load_stage_titles(stage_names_path, corpus_path),
        "route_groups": parse_route_map(route_map_path),
        "resource_stages": resource_stages,
    }


def write_output(data: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "styles.css"):
        source = TEMPLATE_DIR / name
        if not source.exists():
            raise FileNotFoundError(f"missing viewer template: {source}")
        shutil.copyfile(source, output_dir / name)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Keep the generated payload safe when embedded in a script element.
    encoded = encoded.replace("</", "<\\/")
    (output_dir / "data.js").write_text(
        "window.SRWZ_STORY_VIEWER_DATA = " + encoded + ";\n",
        encoding="utf-8",
    )
    (output_dir / "BUILD-MANIFEST.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "counts": data["counts"],
                "source": data["source"],
                "files": ["index.html", "app.js", "styles.css", "data.js"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--route-map", type=Path, default=DEFAULT_ROUTE_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    data = build_viewer_data(queue_path=args.queue, route_map_path=args.route_map)
    write_output(data, args.output)
    print(json.dumps({"output": str(args.output), "counts": data["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
