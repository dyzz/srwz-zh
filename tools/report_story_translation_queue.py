#!/usr/bin/env python3
"""Report the full STAGE dialogue translation queue.

The report is deliberately read-only with respect to source and upstream
repositories.  It distinguishes committed reviewed batches from ignored
machine drafts and records whether an adjacent upstream English XML provides a
pointer-level reference.  The generated JSON belongs under ``work/`` and is a
planning/audit artifact, not a translation release.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Mapping

try:
    from srwz.translation_review import TranslationReviewError, load_source_corpus
except ModuleNotFoundError:
    from tools.srwz.translation_review import TranslationReviewError, load_source_corpus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_SOURCE = PROJECT_ROOT / "work" / "corpus" / "srwz-corpus.jsonl"
DEFAULT_UPSTREAM = PROJECT_ROOT.parent / "2_translated" / "story"
DEFAULT_OUTPUT = WORK_ROOT / "review" / "story-translation-queue.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--upstream-story-dir", type=Path, default=DEFAULT_UPSTREAM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _upstream_counts(path: Path) -> tuple[int, int, int]:
    if not path.is_file():
        return (0, 0, 0)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise TranslationReviewError(f"invalid upstream story XML: {path}: {error}") from error
    pointers = set()
    for entry in root.findall("./Strings/Entry"):
        raw_pointer = (entry.findtext("PointerOffset") or "").strip()
        english = (entry.findtext("EnglishText") or "").strip()
        if raw_pointer and english:
            try:
                pointers.add(int(raw_pointer, 10))
            except ValueError as error:
                raise TranslationReviewError(
                    f"invalid upstream PointerOffset {raw_pointer!r}: {path}"
                ) from error
    return (len(pointers), 0, path.stat().st_size)


def _load_committed(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TranslationReviewError(f"invalid committed translation {path}: {error}") from error
    entries = document.get("entries", [])
    if not isinstance(entries, list):
        raise TranslationReviewError(f"translation entries must be an array: {path}")
    statuses = Counter(
        str(entry.get("editorial_status", ""))
        for entry in entries
        if isinstance(entry, Mapping)
    )
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "entry_count": len(entries),
        "status_counts": dict(sorted(statuses.items())),
        "complete_reviewed": bool(entries)
        and all(status in {"reviewed", "final"} for status in statuses),
    }


def _load_draft(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TranslationReviewError(f"invalid machine draft {path}: {error}") from error
    audit = document.get("machine_audit")
    corpus = document.get("source_corpus")
    if not isinstance(audit, Mapping) or not isinstance(corpus, Mapping):
        raise TranslationReviewError(f"machine draft is missing audit metadata: {path}")
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "entry_count": int(corpus.get("entry_count", 0)),
        "unique_source_text_count": int(corpus.get("unique_source_text_count", 0)),
        "translation_source_counts": dict(audit.get("translation_source_counts", {})),
        "upstream_pointer_match_count": int(audit.get("upstream_pointer_match_count", 0)),
        "missing_placeholder_count": int(audit.get("missing_placeholder_count", 0)),
        "layout_error_count": int(audit.get("layout_error_count", 0)),
        "kana_residue_count": int(audit.get("kana_residue_count", 0)),
    }


def build_report(
    source_path: Path,
    upstream_dir: Path,
) -> dict[str, object]:
    source_entries = load_source_corpus(source_path)
    grouped: OrderedDict[int, list[dict]] = OrderedDict()
    for entry in source_entries:
        if entry.get("domain") != "story" or entry.get("kind") != "dialogue":
            continue
        grouped.setdefault(int(entry.get("scope_index", -1)), []).append(entry)
    stages = []
    for stage, entries in grouped.items():
        source_pointers = {
            int(entry["provenance"]["pointer_offset"])
            for entry in entries
            if isinstance(entry.get("provenance"), Mapping)
            and entry["provenance"].get("pointer_offset") is not None
        }
        upstream_path = upstream_dir / f"{stage:03d}.xml"
        pointer_count, _, _ = _upstream_counts(upstream_path)
        matched_count = 0
        if pointer_count:
            root = ET.parse(upstream_path).getroot()
            upstream_pointers = {
                int(entry.findtext("PointerOffset"))
                for entry in root.findall("./Strings/Entry")
                if (entry.findtext("PointerOffset") or "").strip()
                and (entry.findtext("EnglishText") or "").strip()
            }
            matched_count = len(source_pointers & upstream_pointers)
        committed_path = PROJECT_ROOT / "corpus" / "zh" / "story-dialogue" / f"stage-{stage:03d}.json"
        draft_path = WORK_ROOT / "review" / f"story-dialogue-stage-{stage:03d}-machine-draft.json"
        committed = _load_committed(committed_path)
        draft = _load_draft(draft_path)
        unique_count = len({str(entry["source_text_sha256"]) for entry in entries})
        status = "source_only"
        if committed and committed["complete_reviewed"] and committed["entry_count"] == len(entries):
            status = "committed_reviewed"
        elif draft:
            status = "draft_ready"
        stages.append(
            {
                "stage_index": stage,
                "entry_count": len(entries),
                "unique_source_text_count": unique_count,
                "upstream_xml": str(upstream_path.relative_to(PROJECT_ROOT.parent))
                if upstream_path.is_file()
                else None,
                "upstream_pointer_count": pointer_count,
                "upstream_pointer_match_count": matched_count,
                "status": status,
                "committed": committed,
                "draft": draft,
            }
        )
    return {
        "schema_version": 1,
        "source_corpus": str(source_path.relative_to(PROJECT_ROOT)),
        "source_story_dialogue_entry_count": sum(len(entries) for entries in grouped.values()),
        "stage_count": len(stages),
        "stages": stages,
    }


def main() -> int:
    args = parse_args()
    output = _resolve(args.output).resolve()
    try:
        output.relative_to(WORK_ROOT.resolve())
    except ValueError as error:
        raise TranslationReviewError(f"output must stay under {WORK_ROOT}") from error
    if output.exists() and not args.force:
        raise TranslationReviewError(f"output exists; use --force: {output}")
    report = build_report(_resolve(args.source).resolve(), _resolve(args.upstream_story_dir).resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = Counter(stage["status"] for stage in report["stages"])
    print(
        f"story translation queue: stages={report['stage_count']} "
        f"entries={report['source_story_dialogue_entry_count']} "
        f"statuses={dict(sorted(counts.items()))}"
    )
    print(f"queue report: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"story translation queue failed: {error}", file=sys.stderr)
        raise SystemExit(1)
