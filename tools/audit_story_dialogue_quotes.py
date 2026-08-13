#!/usr/bin/env python3
"""Audit Chinese outer punctuation across every translated STAGE record."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
for import_root in (PROJECT_ROOT, TOOLS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

try:
    from build_story_component import (
        _json,
        _locked_file,
        _project_path,
        _read_iso_member,
        _stage_files,
    )
    from srwz.codec import decode_production as decode
    from srwz.diagnostics import require_work_output
    from srwz.iso_layout import (
        ExecutableOffsetSpec,
        read_executable_archive_offsets,
    )
    from srwz.stage import parse_stage, read_stage_function_addresses
    from srwz.story_quotes import evaluate_story_quote
    from srwz.text import load_text_table
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.build_story_component import (
        _json,
        _locked_file,
        _project_path,
        _read_iso_member,
        _stage_files,
    )
    from tools.srwz.codec import decode_production as decode
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.iso_layout import (
        ExecutableOffsetSpec,
        read_executable_archive_offsets,
    )
    from tools.srwz.stage import parse_stage, read_stage_function_addresses
    from tools.srwz.story_quotes import evaluate_story_quote
    from tools.srwz.text import load_text_table

WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/story-component.json"
DEFAULT_REPORT = WORK_ROOT / "review/story-dialogue-quotes.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _source_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit(config_path: Path = DEFAULT_CONFIG) -> dict:
    """Return a deterministic full-corpus punctuation audit report."""

    config = _json(config_path.resolve())
    if config.get("profile_id") != "srwz-zh-story-component-v1":
        raise ValueError("unexpected story-component profile")
    source = config["source"]
    translations = config["translations"]
    _slps_path, source_slps = _locked_file(source["slps"], label="source SLPS")
    _stage_path, source_stage = _locked_file(
        source["stage"], label="source STAGE"
    )
    source_hb = _read_iso_member(_project_path(source["iso"]), source["hb"])
    table = load_text_table(_project_path(source["text_table"]["path"]))
    offsets = read_executable_archive_offsets(
        source_hb,
        ExecutableOffsetSpec(
            name="HEDBDY/HB.BIN STAGE offsets",
            member=source["hb"]["member"],
            table_start=30320,
            table_end=31144,
        ),
        len(source_stage),
    )
    functions = read_stage_function_addresses(source_slps)
    stage_files = _stage_files(translations)

    style_counts: Counter[str] = Counter()
    actual_style_counts: Counter[str] = Counter()
    mismatches = []
    hash_mismatches = []
    entry_count = 0
    keyword_link_count = 0

    for stage_index, path in sorted(stage_files.items()):
        document = _json(path)
        rows = {entry["id"]: entry for entry in document.get("entries", [])}
        decoded = decode(
            source_stage[offsets[stage_index] : offsets[stage_index + 1]]
        )
        parsed = parse_stage(
            decoded.output,
            table,
            stage_index=stage_index,
            function_address=functions[stage_index],
        )
        speakers = {
            entry.speaker_id: entry.text
            for entry in parsed.entries
            if entry.kind == "speaker"
        }
        source_entries = {
            entry.entry_id: entry
            for entry in parsed.entries
            if entry.kind == "dialogue"
        }
        if set(rows) != set(source_entries):
            raise ValueError(
                f"STAGE {stage_index:03d} source/translation ID coverage drift"
            )

        for entry_id, source_entry in source_entries.items():
            row = rows[entry_id]
            translation = row.get("translation")
            if not isinstance(translation, str) or not translation:
                raise ValueError(f"{entry_id}: empty or invalid translation")
            source_hash = _source_sha256(source_entry.text)
            if row.get("source_text_sha256") != source_hash:
                hash_mismatches.append(
                    {
                        "entry_id": entry_id,
                        "expected": source_hash,
                        "actual": row.get("source_text_sha256"),
                    }
                )
            has_keyword_links = "《" in source_entry.text
            keyword_link_count += source_entry.text.count("《")
            verdict = evaluate_story_quote(
                source_entry.text,
                translation,
                speakers[source_entry.speaker_id],
                has_keyword_links=has_keyword_links,
            )
            style_counts[verdict.expected] += 1
            actual_style_counts[verdict.actual] += 1
            entry_count += 1
            if not verdict.exact:
                mismatches.append(
                    {
                        "entry_id": entry_id,
                        "speaker": speakers[source_entry.speaker_id],
                        "source": source_entry.text,
                        "translation": translation,
                        "expected_style": verdict.expected,
                        "actual_style": verdict.actual,
                    }
                )

    expected_styles = translations.get("expected_dialogue_quote_styles")
    expected_entry_count = translations.get("expected_dialogue_entry_count")
    expected_keyword_links = translations.get(
        "expected_runtime_keyword_link_count"
    )
    counts_exact = (
        entry_count == expected_entry_count
        and dict(sorted(style_counts.items())) == expected_styles
        and keyword_link_count == expected_keyword_links
    )
    return {
        "schema_version": 1,
        "status": "passed"
        if counts_exact and not mismatches and not hash_mismatches
        else "failed",
        "profile_id": "srwz-story-dialogue-quotes-v1",
        "policy": {
            "spoken_dialogue": "中文双引号“”",
            "parenthetical_dialogue": "全角括号（）",
            "blank_speaker_location_or_system_card": "不加外层引号",
            "runtime_keyword_records": "由关键词管线独立校验，不自动改引号",
        },
        "stage_count": len(stage_files),
        "entry_count": entry_count,
        "expected_style_counts": expected_styles,
        "actual_expected_style_counts": dict(sorted(style_counts.items())),
        "translated_outer_style_counts": dict(
            sorted(actual_style_counts.items())
        ),
        "runtime_keyword_link_count": keyword_link_count,
        "mismatch_count": len(mismatches),
        "source_hash_mismatch_count": len(hash_mismatches),
        "counts_exact": counts_exact,
        "mismatches": mismatches,
        "source_hash_mismatches": hash_mismatches,
    }


def main() -> int:
    args = parse_args()
    report_path = require_work_output(args.report_output.resolve(), WORK_ROOT)
    if report_path.exists() and not args.force:
        raise ValueError(f"report exists; use --force: {report_path}")
    report = audit(args.config)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Story dialogue quotes:",
        f"stages={report['stage_count']}",
        f"entries={report['entry_count']}",
        f"mismatches={report['mismatch_count']}",
        f"source_hash_mismatches={report['source_hash_mismatch_count']}",
    )
    print(f"quote report: {report_path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"story dialogue quote audit failed: {error}", file=sys.stderr)
        raise SystemExit(1)
