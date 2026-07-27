#!/usr/bin/env python3
"""Build a bounded English-reference audit for SRWZ stages 001-005."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    from srwz.diagnostics import require_work_output
    from srwz.translation_review import (
        TranslationRecord,
        TranslationReviewError,
        load_source_corpus,
        load_translations,
    )
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.translation_review import (
        TranslationRecord,
        TranslationReviewError,
        load_source_corpus,
        load_translations,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_RELEASE = PROJECT_ROOT / "corpus/releases/v1.json"
DEFAULT_UPSTREAM_LOCK = PROJECT_ROOT / "config/upstream.lock.json"
DEFAULT_UPSTREAM_ROOT = PROJECT_ROOT.parent
DEFAULT_REPORT = (
    WORK_ROOT / "review/first-five-upstream-english-reference.json"
)
DEFAULT_TSV = (
    WORK_ROOT / "review/first-five-upstream-english-reference.tsv"
)
STAGE_INDICES = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class UpstreamStoryEntry:
    stage_index: int
    kind: str
    section: str
    ordinal: int
    japanese: str
    english: str
    status: str
    notes: str

    @property
    def location(self) -> str:
        return (
            f"{self.stage_index:03d}.xml:"
            f"{self.section}:{self.ordinal:04d}"
        )


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise TranslationReviewError(
            f"cannot inspect upstream checkout: {detail}"
        )
    return result.stdout.strip()


def validate_upstream_checkout(
    root: Path,
    expected_commit: str,
) -> dict[str, object]:
    actual_commit = _run_git(root, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise TranslationReviewError(
            "adjacent upstream checkout does not match pinned commit: "
            f"{actual_commit} != {expected_commit}"
        )
    status = _run_git(root, "status", "--porcelain=v1")
    if status:
        raise TranslationReviewError(
            "adjacent upstream checkout is dirty; English audit is read-only"
        )
    return {
        "commit": actual_commit,
        "clean": True,
    }


def load_upstream_story_entries(
    story_root: Path,
) -> tuple[tuple[UpstreamStoryEntry, ...], dict[str, object]]:
    paths = sorted(
        story_root.glob("*.xml"),
        key=lambda path: int(path.stem),
    )
    if not paths:
        raise TranslationReviewError(
            f"no upstream story XML files found: {story_root}"
        )
    entries = []
    digest = hashlib.sha256()
    total_size = 0
    for path in paths:
        data = path.read_bytes()
        total_size += len(data)
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(data).digest())
        try:
            root = ET.fromstring(data)
        except ET.ParseError as error:
            raise TranslationReviewError(
                f"cannot parse upstream XML {path}: {error}"
            ) from error
        stage_index = int(path.stem)
        speakers = root.find("Speakers")
        if speakers is not None:
            section = speakers.findtext("Section") or "Speaker"
            for ordinal, node in enumerate(speakers.findall("Entry")):
                entries.append(
                    UpstreamStoryEntry(
                        stage_index=stage_index,
                        kind="speaker",
                        section=section,
                        ordinal=ordinal,
                        japanese=node.findtext("JapaneseText") or "",
                        english=node.findtext("EnglishText") or "",
                        status=node.findtext("Status") or "",
                        notes=node.findtext("Notes") or "",
                    )
                )
        for group in root.findall("Strings"):
            section = group.findtext("Section") or ""
            kind = "condition" if section.startswith("_") else "dialogue"
            for ordinal, node in enumerate(group.findall("Entry")):
                entries.append(
                    UpstreamStoryEntry(
                        stage_index=stage_index,
                        kind=kind,
                        section=section,
                        ordinal=ordinal,
                        japanese=node.findtext("JapaneseText") or "",
                        english=node.findtext("EnglishText") or "",
                        status=node.findtext("Status") or "",
                        notes=node.findtext("Notes") or "",
                    )
                )
    return tuple(entries), {
        "file_count": len(paths),
        "entry_count": len(entries),
        "total_size": total_size,
        "aggregate_sha256": digest.hexdigest(),
    }


def audit_first_five_upstream_english(
    source_entries: Iterable[Mapping[str, object]],
    translations: Iterable[TranslationRecord],
    upstream_entries: Iterable[UpstreamStoryEntry],
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    selected = []
    for record in translations:
        source = source_by_id.get(record.entry_id)
        if source is None:
            continue
        if (
            record.batch_id == "v1-story-dialogue"
            and source.get("domain") == "story"
            and source.get("kind") == "dialogue"
            and int(source.get("scope_index", -1)) in STAGE_INDICES
        ):
            selected.append((record, source))

    direct_by_key = {}
    english_by_japanese: dict[str, list[UpstreamStoryEntry]] = defaultdict(
        list
    )
    upstream_english_count = 0
    for entry in upstream_entries:
        if entry.kind != "dialogue":
            continue
        key = (
            entry.stage_index,
            entry.section,
            entry.ordinal,
        )
        if key in direct_by_key:
            raise TranslationReviewError(
                f"duplicate upstream dialogue location: {entry.location}"
            )
        direct_by_key[key] = entry
        if entry.english.strip():
            english_by_japanese[entry.japanese].append(entry)
            upstream_english_count += 1

    alignment_issues = []
    occurrence_rows = []
    stage_counts: dict[int, Counter] = defaultdict(Counter)
    for record, source in selected:
        stage_index = int(source["scope_index"])
        key = (
            stage_index,
            str(source.get("section", "")),
            int(source.get("ordinal", -1)),
        )
        direct = direct_by_key.get(key)
        source_text = str(source["source_text"])
        if direct is None:
            alignment_issues.append(
                {
                    "entry_id": record.entry_id,
                    "issue": "missing_direct_upstream_entry",
                    "expected_location": (
                        f"{stage_index:03d}.xml:{key[1]}:{key[2]:04d}"
                    ),
                }
            )
        elif direct.japanese != source_text:
            alignment_issues.append(
                {
                    "entry_id": record.entry_id,
                    "issue": "direct_japanese_mismatch",
                    "upstream_location": direct.location,
                    "source_text": source_text,
                    "upstream_japanese": direct.japanese,
                }
            )

        direct_references = (
            (direct,)
            if direct is not None
            and direct.japanese == source_text
            and direct.english.strip()
            else ()
        )
        fallback_references = (
            ()
            if direct_references
            else tuple(english_by_japanese.get(source_text, ()))
        )
        if direct_references:
            reference_kind = "direct_upstream_english"
        elif fallback_references:
            reference_kind = "exact_japanese_elsewhere"
        else:
            reference_kind = "none"
        stage_counts[stage_index][reference_kind] += 1
        occurrence_rows.append(
            {
                "record": record,
                "source": source,
                "direct": direct,
                "direct_references": direct_references,
                "fallback_references": fallback_references,
                "reference_kind": reference_kind,
            }
        )

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in occurrence_rows:
        if row["reference_kind"] != "none":
            record = row["record"]
            assert isinstance(record, TranslationRecord)
            grouped[record.source_text_sha256].append(row)

    review_rows = []
    for source_hash, group in sorted(
        grouped.items(),
        key=lambda item: str(item[1][0]["record"].entry_id),
    ):
        records = [item["record"] for item in group]
        sources = [item["source"] for item in group]
        direct_references = _unique(
            reference.location
            for item in group
            for reference in item["direct_references"]
        )
        fallback_objects = tuple(
            reference
            for item in group
            for reference in item["fallback_references"]
        )
        fallback_locations = _unique(
            reference.location for reference in fallback_objects
        )
        direct_english = _unique(
            reference.english.strip()
            for item in group
            for reference in item["direct_references"]
        )
        fallback_english = _unique(
            reference.english.strip() for reference in fallback_objects
        )
        kinds = {str(item["reference_kind"]) for item in group}
        reference_kind = (
            "direct_upstream_english"
            if "direct_upstream_english" in kinds
            else "exact_japanese_elsewhere"
        )
        review_rows.append(
            {
                "reference_kind": reference_kind,
                "source_text_sha256": source_hash,
                "source_text": str(sources[0]["source_text"]),
                "current_translation_variants": " || ".join(
                    _unique(record.translation for record in records)
                ),
                "occurrence_count": len(records),
                "stage_indices": ", ".join(
                    str(value)
                    for value in sorted(
                        {int(source["scope_index"]) for source in sources}
                    )
                ),
                "entry_ids": ", ".join(
                    record.entry_id for record in records
                ),
                "direct_upstream_english_variants": " || ".join(
                    direct_english
                ),
                "direct_upstream_locations": ", ".join(
                    direct_references
                ),
                "fallback_upstream_english_variants": " || ".join(
                    fallback_english
                ),
                "fallback_upstream_locations": ", ".join(
                    fallback_locations
                ),
                "fallback_reference_count": len(fallback_locations),
                "upstream_english_variant_count": len(
                    direct_english or fallback_english
                ),
                "review_caution": (
                    "同一日文出现在其他关卡；英语只用于提示可能语义，"
                    "必须回到当前说话人和上下文判断，不能自动覆盖中文。"
                    if reference_kind == "exact_japanese_elsewhere"
                    else "同关卡英语也只是上游翻译稿，不是官方中文术语。"
                ),
            }
        )

    direct_count = sum(
        row["reference_kind"] == "direct_upstream_english"
        for row in occurrence_rows
    )
    fallback_count = sum(
        row["reference_kind"] == "exact_japanese_elsewhere"
        for row in occurrence_rows
    )
    no_reference_count = sum(
        row["reference_kind"] == "none" for row in occurrence_rows
    )
    report = {
        "schema_version": 1,
        "status": "passed" if not alignment_issues else "failed",
        "reference_coverage": (
            "complete"
            if not no_reference_count
            else "limited"
            if direct_count or fallback_count
            else "none"
        ),
        "scope": {
            "kind": "story dialogue",
            "stage_indices": list(STAGE_INDICES),
        },
        "entry_count": len(occurrence_rows),
        "direct_alignment_issue_count": len(alignment_issues),
        "direct_upstream_english_entry_count": direct_count,
        "exact_source_fallback_entry_count": fallback_count,
        "reference_entry_count": direct_count + fallback_count,
        "reference_unique_source_count": len(review_rows),
        "no_reference_entry_count": no_reference_count,
        "upstream_english_dialogue_entry_count": upstream_english_count,
        "upstream_english_unique_source_count": len(english_by_japanese),
        "upstream_english_variant_source_count": sum(
            len(_unique(entry.english.strip() for entry in entries)) > 1
            for entries in english_by_japanese.values()
        ),
        "stage_counts": {
            str(stage_index): {
                "entry_count": sum(stage_counts[stage_index].values()),
                "direct_upstream_english": stage_counts[stage_index][
                    "direct_upstream_english"
                ],
                "exact_japanese_elsewhere": stage_counts[stage_index][
                    "exact_japanese_elsewhere"
                ],
                "none": stage_counts[stage_index]["none"],
            }
            for stage_index in STAGE_INDICES
        },
        "alignment_issues": alignment_issues,
        "limitations": [
            "The pinned upstream English text is a translation reference, not an official terminology source.",
            "Exact Japanese reused in another stage can have a different speaker, addressee, tone or polarity.",
            "Rows without an English reference still require Japanese-context review.",
        ],
    }
    return report, tuple(review_rows)


def write_reference_tsv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> None:
    columns = (
        "reference_kind",
        "source_text_sha256",
        "source_text",
        "current_translation_variants",
        "occurrence_count",
        "stage_indices",
        "entry_ids",
        "direct_upstream_english_variants",
        "direct_upstream_locations",
        "fallback_upstream_english_variants",
        "fallback_upstream_locations",
        "fallback_reference_count",
        "upstream_english_variant_count",
        "review_caution",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=columns,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _project_path(raw: object) -> Path:
    return (PROJECT_ROOT / str(raw)).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument(
        "--upstream-lock",
        type=Path,
        default=DEFAULT_UPSTREAM_LOCK,
    )
    parser.add_argument(
        "--upstream-root",
        type=Path,
        default=DEFAULT_UPSTREAM_ROOT,
    )
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--tsv-output", type=Path, default=DEFAULT_TSV)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_output = require_work_output(args.report_output, WORK_ROOT)
    tsv_output = require_work_output(args.tsv_output, WORK_ROOT)
    if not args.force:
        for path in (report_output, tsv_output):
            if path.exists():
                raise TranslationReviewError(
                    f"output exists; use --force: {path}"
                )
    lock = json.loads(args.upstream_lock.read_text(encoding="utf-8"))
    expected_commit = str(lock.get("commit", ""))
    checkout = validate_upstream_checkout(
        args.upstream_root.resolve(),
        expected_commit,
    )
    upstream_entries, upstream_metadata = load_upstream_story_entries(
        args.upstream_root.resolve() / "2_translated/story"
    )
    release = json.loads(args.release.read_text(encoding="utf-8"))
    source_config = release.get("source_corpus")
    if not isinstance(source_config, dict):
        raise TranslationReviewError("release has no source_corpus object")
    source_entries = load_source_corpus(
        _project_path(source_config.get("path"))
    )
    translations = load_translations(
        _project_path(raw)
        for raw in release.get("translation_sources", ())
    )
    report, rows = audit_first_five_upstream_english(
        source_entries,
        translations,
        upstream_entries,
    )
    report["upstream"] = {
        "name": lock.get("name"),
        "remote": lock.get("remote"),
        **checkout,
        "story_xml": upstream_metadata,
    }
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_reference_tsv(tsv_output, rows)
    print(
        "first-five upstream English reference: "
        f"entries={report['entry_count']} "
        f"direct={report['direct_upstream_english_entry_count']} "
        f"fallback={report['exact_source_fallback_entry_count']} "
        f"unique={report['reference_unique_source_count']} "
        f"coverage={report['reference_coverage']} "
        f"status={report['status']}"
    )
    print(f"report: {report_output}")
    print(f"reference TSV: {tsv_output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        ET.ParseError,
        json.JSONDecodeError,
        TranslationReviewError,
        ValueError,
    ) as error:
        print(
            f"first-five upstream English reference failed: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
