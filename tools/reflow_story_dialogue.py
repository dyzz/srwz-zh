#!/usr/bin/env python3
"""Reflow only SRWZ story-dialogue entries that exceed the runtime limit."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    from srwz.chinese_layout import (
        DEFAULT_LINE_WIDTH,
        DEFAULT_MAX_LINES,
        ChineseLayoutError,
        dialogue_line_widths,
        logical_dialogue_text,
        reflow_chinese_dialogue,
    )
    from srwz.diagnostics import require_work_output
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.srwz.chinese_layout import (
        DEFAULT_LINE_WIDTH,
        DEFAULT_MAX_LINES,
        ChineseLayoutError,
        dialogue_line_widths,
        logical_dialogue_text,
        reflow_chinese_dialogue,
    )
    from tools.srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DIALOGUE_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
DEFAULT_RELEASE = PROJECT_ROOT / "corpus/releases/v1.json"
DEFAULT_REPORT = WORK_ROOT / "review/story-dialogue-layout.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--line-width", type=int, default=DEFAULT_LINE_WIDTH)
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the reflowed canonical translations; default is check-only",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _project_path(raw: object) -> Path:
    return (PROJECT_ROOT / str(raw)).resolve()


def _load_protected_terms(release_path: Path) -> tuple[str, ...]:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    terms = set()
    for raw_path in release.get("glossary_sources", ()):
        glossary = json.loads(
            _project_path(raw_path).read_text(encoding="utf-8")
        )
        for term in glossary.get("terms", ()):
            translation = term.get("translation")
            if isinstance(translation, str) and len(translation) > 1:
                terms.add(translation)
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))


def _translation_paths() -> tuple[Path, ...]:
    paths = tuple(sorted(DIALOGUE_ROOT.glob("stage-*.json")))
    if not paths:
        raise ChineseLayoutError("no story-dialogue translations found")
    return paths


def _within_limit(widths: tuple[int, ...], line_width: int, max_lines: int) -> bool:
    return len(widths) <= max_lines and max(widths, default=0) <= line_width


def main() -> int:
    args = parse_args()
    if args.line_width <= 0 or args.max_lines <= 0:
        raise ChineseLayoutError("--line-width and --max-lines must be positive")
    report_output = require_work_output(args.report_output, WORK_ROOT)
    if report_output.exists() and not args.force:
        raise ChineseLayoutError(f"report exists; use --force: {report_output}")

    protected_terms = _load_protected_terms(args.release.resolve())
    changes = []
    before_widths = Counter()
    after_widths = Counter()
    entry_count = 0
    widest_after = 0

    for path in _translation_paths():
        document = json.loads(path.read_text(encoding="utf-8"))
        path_changed = False
        for entry in document["entries"]:
            entry_count += 1
            original = entry["translation"]
            original_widths = dialogue_line_widths(
                original,
                protected_terms=protected_terms,
            )
            before_widths[max(original_widths, default=0)] += 1
            if _within_limit(original_widths, args.line_width, args.max_lines):
                result_text = original
                result_widths = original_widths
            else:
                result = reflow_chinese_dialogue(
                    original,
                    protected_terms=protected_terms,
                    line_width=args.line_width,
                    max_lines=args.max_lines,
                )
                result_text = result.text
                result_widths = result.line_widths
                if logical_dialogue_text(result_text) != logical_dialogue_text(
                    original
                ):
                    raise AssertionError(
                        f"{entry['id']}: reflow changed logical dialogue text"
                    )
                if not _within_limit(
                    result_widths,
                    args.line_width,
                    args.max_lines,
                ):
                    raise AssertionError(
                        f"{entry['id']}: reflow still exceeds the limit"
                    )
                changes.append(
                    {
                        "entry_id": entry["id"],
                        "path": str(path.relative_to(PROJECT_ROOT)),
                        "before": original,
                        "after": result_text,
                        "before_line_widths": list(original_widths),
                        "after_line_widths": list(result_widths),
                    }
                )
                if args.apply:
                    entry["translation"] = result_text
                    path_changed = True
            after_widths[max(result_widths, default=0)] += 1
            widest_after = max(widest_after, max(result_widths, default=0))
        if args.apply and path_changed:
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    report = {
        "schema_version": 1,
        "status": "applied"
        if args.apply
        else ("passed" if not changes else "changes_required"),
        "line_width": args.line_width,
        "maximum_lines": args.max_lines,
        "continuation_indent_cells": 1,
        "maximum_rendered_continuation_width": args.line_width + 1,
        "entry_count": entry_count,
        "changed_entry_count": len(changes),
        "maximum_projected_line_width": widest_after,
        "before_maximum_width_distribution": dict(sorted(before_widths.items())),
        "after_maximum_width_distribution": dict(sorted(after_widths.items())),
        "changes": changes,
    }
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Story dialogue layout: entries={entry_count} "
        f"changed={len(changes)} width={args.line_width} "
        f"max_lines={args.max_lines}"
    )
    print(f"layout report: {report_output}")
    if not args.apply and changes:
        print("story dialogue layout needs reflow; rerun with --apply", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, ChineseLayoutError) as error:
        print(f"story dialogue reflow failed: {error}", file=sys.stderr)
        raise SystemExit(1)
