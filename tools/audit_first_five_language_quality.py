#!/usr/bin/env python3
"""Audit the review-facing language quality gates for stages 001-005."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    from srwz.chinese_layout import (
        DEFAULT_LINE_WIDTH,
        DEFAULT_MAX_LINES,
        FORBIDDEN_LINE_END_CHARACTERS,
        FORBIDDEN_LINE_START_CHARACTERS,
        dialogue_line_widths,
    )
    from srwz.diagnostics import require_work_output
    from srwz.translation_review import (
        KANA_PATTERN,
        STRUCTURAL_TOKEN_PATTERN,
        TranslationRecord,
        TranslationReviewError,
        load_source_corpus,
        load_translations,
    )
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.srwz.chinese_layout import (
        DEFAULT_LINE_WIDTH,
        DEFAULT_MAX_LINES,
        FORBIDDEN_LINE_END_CHARACTERS,
        FORBIDDEN_LINE_START_CHARACTERS,
        dialogue_line_widths,
    )
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.translation_review import (
        KANA_PATTERN,
        STRUCTURAL_TOKEN_PATTERN,
        TranslationRecord,
        TranslationReviewError,
        load_source_corpus,
        load_translations,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_RELEASE = PROJECT_ROOT / "corpus/releases/v1.json"
DEFAULT_REPORT = WORK_ROOT / "review/first-five-language-quality.json"
DEFAULT_FINDINGS = (
    WORK_ROOT / "review/first-five-language-quality-findings.tsv"
)
STAGE_INDICES = (1, 2, 3, 4, 5)
MAX_RENDER_LINE_CHARACTERS = DEFAULT_LINE_WIDTH
MAX_RENDER_LINES = DEFAULT_MAX_LINES
CONTEXTUAL_VARIANT_NOTE_PREFIX = "跨关同源"
MIXED_PUNCTUATION_PATTERN = re.compile(
    r"[，。！？；：][,\.\?!;:]|[,\.\?!;:][，。！？；：]"
)


def _project_path(raw: object) -> Path:
    return (PROJECT_ROOT / str(raw)).resolve()


def audit_first_five_language_quality(
    source_entries: Iterable[Mapping[str, object]],
    translations: Iterable[TranslationRecord],
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    source_by_id = {str(entry["id"]): entry for entry in source_entries}
    records = []
    for record in translations:
        source = source_by_id.get(record.entry_id)
        if source is None:
            continue
        if (
            record.batch_id != "v1-story-dialogue"
            or source.get("domain") != "story"
            or source.get("kind") != "dialogue"
            or int(source.get("scope_index", -1)) not in STAGE_INDICES
        ):
            continue
        records.append((record, source))

    issues: list[dict[str, object]] = []
    stage_counts = Counter()
    unique_sources_by_stage: dict[int, set[str]] = defaultdict(set)
    widest_line = 0
    most_lines = 0
    for record, source in records:
        stage_index = int(source["scope_index"])
        stage_counts[stage_index] += 1
        unique_sources_by_stage[stage_index].add(
            record.source_text_sha256
        )
        source_text = str(source["source_text"])
        translation = record.translation
        lines = translation.splitlines()
        line_widths = dialogue_line_widths(translation)
        line_width = max(line_widths, default=0)
        widest_line = max(widest_line, line_width)
        most_lines = max(most_lines, len(lines))
        forbidden_starts = [
            line.lstrip("　 ")[0]
            for line in lines[1:]
            if line.lstrip("　 ")
            and line.lstrip("　 ")[0]
            in FORBIDDEN_LINE_START_CHARACTERS
        ]
        forbidden_ends = [
            line.rstrip()[-1]
            for line in lines
            if line.rstrip()
            and line.rstrip()[-1] in FORBIDDEN_LINE_END_CHARACTERS
        ]
        checks = (
            (
                "japanese_kana",
                KANA_PATTERN.search(translation) is not None,
                "译文仍含平假名或片假名",
            ),
            (
                "structural_token_mismatch",
                sorted(STRUCTURAL_TOKEN_PATTERN.findall(source_text))
                != sorted(
                    STRUCTURAL_TOKEN_PATTERN.findall(translation)
                ),
                "玩家名、控制码或遮蔽符号与原文不一致",
            ),
            (
                "unbalanced_quotes",
                translation.count("“") != translation.count("”"),
                "中文引号不成对",
            ),
            (
                "unbalanced_parentheses",
                translation.count("（") != translation.count("）"),
                "中文括号不成对",
            ),
            (
                "mixed_punctuation",
                MIXED_PUNCTUATION_PATTERN.search(translation) is not None,
                "中英文句末标点相邻混用",
            ),
            (
                "line_too_long",
                line_width > MAX_RENDER_LINE_CHARACTERS,
                (
                    f"最长行 {line_width} 字符，超过 "
                    f"{MAX_RENDER_LINE_CHARACTERS} 字符门限"
                ),
            ),
            (
                "too_many_lines",
                len(lines) > MAX_RENDER_LINES,
                (
                    f"对白共 {len(lines)} 行，超过 "
                    f"{MAX_RENDER_LINES} 行门限"
                ),
            ),
            (
                "forbidden_line_start",
                bool(forbidden_starts),
                f"续行以禁则字符开头：{forbidden_starts!r}",
            ),
            (
                "forbidden_line_end",
                bool(forbidden_ends),
                f"行尾为开标点：{forbidden_ends!r}",
            ),
            (
                "editorial_status",
                record.editorial_status != "reviewed",
                f"编辑状态为 {record.editorial_status!r}，不是 reviewed",
            ),
        )
        for finding_type, failed, detail in checks:
            if failed:
                issues.append(
                    {
                        "severity": "error",
                        "finding_type": finding_type,
                        "stage_index": stage_index,
                        "entry_id": record.entry_id,
                        "section": str(source.get("section", "")),
                        "source_text": source_text,
                        "translation": translation,
                        "notes": record.notes,
                        "detail": detail,
                    }
                )

    by_source_hash: dict[
        str,
        list[tuple[TranslationRecord, Mapping[str, object]]],
    ] = defaultdict(list)
    for record, source in records:
        by_source_hash[record.source_text_sha256].append((record, source))

    contextual_findings = []
    variant_source_count = 0
    for source_hash, group in sorted(by_source_hash.items()):
        if len({record.translation for record, _ in group}) <= 1:
            continue
        variant_source_count += 1
        for record, source in group:
            finding = {
                "severity": "reviewed"
                if record.notes.startswith(
                    CONTEXTUAL_VARIANT_NOTE_PREFIX
                )
                else "error",
                "finding_type": "contextual_same_source_variant",
                "stage_index": int(source["scope_index"]),
                "entry_id": record.entry_id,
                "section": str(source.get("section", "")),
                "source_text": str(source["source_text"]),
                "translation": record.translation,
                "notes": record.notes,
                "detail": (
                    "同一原文按说话人或上下文保留不同译法；"
                    "需有“跨关同源”审核说明"
                ),
                "source_text_sha256": source_hash,
            }
            contextual_findings.append(finding)
            if finding["severity"] == "error":
                issues.append(finding)

    findings = tuple(
        sorted(
            (*issues, *contextual_findings),
            key=lambda item: (
                0 if item["severity"] == "error" else 1,
                int(item["stage_index"]),
                str(item["entry_id"]),
                str(item["finding_type"]),
            ),
        )
    )
    report = {
        "schema_version": 1,
        "status": "passed" if not issues else "failed",
        "scope": {
            "kind": "story dialogue",
            "stage_indices": list(STAGE_INDICES),
        },
        "entry_count": len(records),
        "unique_source_text_count": len(by_source_hash),
        "stage_entry_counts": {
            str(stage): stage_counts[stage] for stage in STAGE_INDICES
        },
        "stage_unique_source_text_counts": {
            str(stage): len(unique_sources_by_stage[stage])
            for stage in STAGE_INDICES
        },
        "maximum_render_line_characters": widest_line,
        "render_line_character_limit": MAX_RENDER_LINE_CHARACTERS,
        "maximum_render_line_count": most_lines,
        "render_line_count_limit": MAX_RENDER_LINES,
        "hard_issue_count": len(issues),
        "same_source_translation_variant_source_count": (
            variant_source_count
        ),
        "reviewed_contextual_variant_record_count": sum(
            item["severity"] == "reviewed"
            for item in contextual_findings
        ),
        "finding_count": len(findings),
    }
    return report, findings


def write_findings_tsv(
    path: Path,
    findings: Sequence[Mapping[str, object]],
) -> None:
    columns = (
        "severity",
        "finding_type",
        "stage_index",
        "entry_id",
        "section",
        "source_text",
        "translation",
        "notes",
        "detail",
        "source_text_sha256",
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
        for finding in findings:
            writer.writerow(finding)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--findings-output",
        type=Path,
        default=DEFAULT_FINDINGS,
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_output = require_work_output(args.report_output, WORK_ROOT)
    findings_output = require_work_output(args.findings_output, WORK_ROOT)
    if not args.force:
        for path in (report_output, findings_output):
            if path.exists():
                raise TranslationReviewError(
                    f"output exists; use --force: {path}"
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
    report, findings = audit_first_five_language_quality(
        source_entries,
        translations,
    )
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_findings_tsv(findings_output, findings)
    print(
        "first-five language quality: "
        f"entries={report['entry_count']} "
        f"issues={report['hard_issue_count']} "
        f"contextual={report['reviewed_contextual_variant_record_count']} "
        f"status={report['status']}"
    )
    print(f"report: {report_output}")
    print(f"findings: {findings_output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"first-five language quality failed: {error}", file=sys.stderr)
        raise SystemExit(1)
