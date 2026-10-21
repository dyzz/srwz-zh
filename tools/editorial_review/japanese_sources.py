#!/usr/bin/env python3
"""Resolve the Japanese source of every Chinese corpus record.

The production corpus stores only ``source_text_sha256`` for most surfaces.
This module decodes the locked Original disc members under ``work/disc``
exactly as the component builders do and returns ``sha256 -> Japanese text``
for: STAGE dialogue, speakers and conditions; the chunk-zero system
dialogues and story overviews; MTV_PROS world-history summaries; every menu
descriptor section (SLPS and COMPDATA, so stage names and Compdata battle
lines included).  Battle (SRVC) lines, the library and display names come
from the community site's published data, and the remaining UI strings from
the 2026-09-22 misc-text export; those files carry the same hashes.

    python3 tools/editorial_review/japanese_sources.py --out work/review/term-sweep-20261021/jp-by-sha.json
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))

from build_story_component import DEFAULT_CONFIG, _json, _locked_file, _project_path, _read_iso_member  # noqa: E402
from srwz.codec import decode_production as decode  # noqa: E402
from srwz.iso_layout import CORE_ARCHIVE_SPECS, ExecutableOffsetSpec, read_executable_archive_offsets  # noqa: E402
from srwz.menu import parse_menu_file  # noqa: E402
from srwz.stage import parse_stage, parse_stage_system_dialogues, read_stage_function_addresses  # noqa: E402
from srwz.stage_overview import parse_stage_overviews  # noqa: E402
from srwz.summary import parse_summary  # noqa: E402
from srwz.text import load_text_table  # noqa: E402

SITE_DATA = WORKSPACE_ROOT / "srwz-community-web/public/data"
MISC_EXPORTS = (
    PROJECT_ROOT / "work/exports/misc-text-20260922/combined.json",
    PROJECT_ROOT / "work/exports/explanatory-text-20260922/combined.json",
)
MENU_DESCRIPTORS = PROJECT_ROOT / "vendor/upstream-python/project/menu_files.json"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def disc_sources() -> tuple[dict[str, str], dict[str, str]]:
    """(sha -> text, entry id -> text) decoded from the locked Original members."""

    config = _json(DEFAULT_CONFIG)
    source = config["source"]
    _p, slps = _locked_file(source["slps"], label="source SLPS")
    _p, stage = _locked_file(source["stage"], label="source STAGE")
    table_path, _b = _locked_file(source["text_table"], label="source text table")
    hb = _read_iso_member(_project_path(source["iso"]), source["hb"])
    table = load_text_table(table_path)
    by_sha: dict[str, str] = {}
    by_id: dict[str, str] = {}

    def put(entry_id: str, text: str) -> None:
        if text:
            by_sha.setdefault(sha256_text(text), text)
            by_id.setdefault(entry_id, text)

    offsets = read_executable_archive_offsets(
        hb, ExecutableOffsetSpec(name="HEDBDY/HB.BIN STAGE offsets", member=source["hb"]["member"], table_start=30320, table_end=31144), len(stage)
    )
    functions = read_stage_function_addresses(slps)
    for index in range(len(offsets) - 1):
        chunk = stage[offsets[index] : offsets[index + 1]]
        if not chunk:
            continue
        decoded = decode(chunk).output
        for entry in parse_stage(decoded, table, stage_index=index, function_address=functions[index]).entries:
            if entry.kind in ("dialogue", "speaker", "condition"):
                put(entry.entry_id, entry.text)
        if index == 0:
            for entry in parse_stage_system_dialogues(decoded, table):
                put(entry.entry_id, entry.text)
                put(entry.entry_id + "#speaker", entry.speaker)
            for entry in parse_stage_overviews(decoded, table):
                put(entry.entry_id, entry.source_text)

    mtv = (PROJECT_ROOT / "work/disc/DATA/MTV_PROS.BIN").read_bytes()
    mtv_offsets = read_executable_archive_offsets(slps, CORE_ARCHIVE_SPECS["MTV_PROS.BIN"], len(mtv))
    for index, (start, end) in enumerate(zip(mtv_offsets, mtv_offsets[1:])):
        if end <= start:
            continue
        for entry in parse_summary(decode(mtv[start:end]).output, table, chunk_index=index).entries:
            put(entry.entry_id, entry.text)

    compdata = decode((PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN").read_bytes()).output
    for descriptor in json.loads(MENU_DESCRIPTORS.read_text(encoding="utf-8")):
        data = slps if descriptor["friendly_name"] == "SLPS" else compdata
        for entry in parse_menu_file(data, descriptor, table).entries:
            put(entry.entry_id, entry.text)
    return by_sha, by_id


def site_and_export_sources() -> dict[str, str]:
    by_sha: dict[str, str] = {}
    for name in ("library/character.json", "library/robot.json", "library/glossary.json"):
        path = SITE_DATA / name
        if not path.exists():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            for field in entry.get("fields", []):
                text = field.get("sourceText")
                if isinstance(text, str) and text:
                    by_sha.setdefault(sha256_text(text), text)
    for path in sorted(glob.glob(str(SITE_DATA / "catalog/work-*.json"))):
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("people", "units", "weapons", "battleLines"):
            for entry in document.get(key, []):
                text = entry.get("sourceText")
                if isinstance(text, str) and text:
                    for variant in (text, text.replace("\\n", "\n"), text.replace("\n", "\\n")):
                        by_sha.setdefault(sha256_text(variant), variant)
    for path in MISC_EXPORTS:
        if not path.exists():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            for edition in (entry.get("editions") or {}).values():
                text = (edition or {}).get("source_ja")
                if isinstance(text, str) and text:
                    by_sha.setdefault(sha256_text(text), text)
    return by_sha


def resolve_all() -> tuple[dict[str, str], dict[str, str]]:
    by_sha, by_id = disc_sources()
    for sha, text in site_and_export_sources().items():
        by_sha.setdefault(sha, text)
    return by_sha, by_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    by_sha, by_id = resolve_all()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"by_sha": by_sha, "by_id": by_id}, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"japanese strings: {len(by_sha)} by hash, {len(by_id)} by id -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
