#!/usr/bin/env python3
"""Reflow every translated stage for the Chinese SRWZ dialogue window."""

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
TRANSLATION_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
DEFAULT_RELEASE = PROJECT_ROOT / "corpus/releases/v1.json"
DEFAULT_REPORT = WORK_ROOT / "review/full-story-chinese-layout.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--line-width", type=int, default=DEFAULT_LINE_WIDTH)
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write canonical reflowed translations; default is check-only",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _project_path(raw: object) -> Path:
    return (PROJECT_ROOT / str(raw)).resolve()


def _load_protected_terms(release_path: Path) -> tuple[str, ...]:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    terms = set()
    for raw_path in release.get("glossary_sources", ()):
        glossary_path = _project_path(raw_path)
        glossary = json.loads(glossary_path.read_text(encoding="utf-8"))
        for term in glossary.get("terms", ()):
            translation = term.get("translation")
            if isinstance(translation, str) and len(translation) > 1:
                terms.add(translation)
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))


def _distribution(entries: list[dict]) -> dict[str, int]:
    counts = Counter(entry["translation"].count("\n") + 1 for entry in entries)
    return {
        str(line_count): counts[line_count]
        for line_count in sorted(counts)
    }


def _translation_paths() -> tuple[tuple[int, Path], ...]:
    paths = []
    for path in TRANSLATION_ROOT.glob("stage-*.json"):
        try:
            stage_index = int(path.stem.removeprefix("stage-"))
        except ValueError as error:
            raise ChineseLayoutError(
                f"invalid stage translation filename: {path.name}"
            ) from error
        paths.append((stage_index, path))
    if not paths:
        raise ChineseLayoutError("no stage dialogue translations found")
    return tuple(sorted(paths))


def main() -> int:
    args = parse_args()
    if args.line_width <= 0 or args.max_lines <= 0:
        raise ChineseLayoutError("--line-width and --max-lines must be positive")
    report_output = require_work_output(args.report_output, WORK_ROOT)
    if report_output.exists() and not args.force:
        raise ChineseLayoutError(
            f"report exists; use --force: {report_output}"
        )

    protected_terms = _load_protected_terms(args.release.resolve())
    changed = []
    preserved = Counter()
    stage_reports = {}
    widest_width = 0
    total_entries = 0

    translation_paths = _translation_paths()
    for stage_index, path in translation_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = document["entries"]
        before_distribution = _distribution(entries)
        projected_entries = []
        for entry in entries:
            original = entry["translation"]
            result = reflow_chinese_dialogue(
                original,
                protected_terms=protected_terms,
                line_width=args.line_width,
                max_lines=args.max_lines,
            )
            if logical_dialogue_text(result.text) != logical_dialogue_text(
                original
            ):
                raise AssertionError(
                    f"{entry['id']}: reflow changed dialogue content"
                )
            if result.preserved_reason:
                preserved[result.preserved_reason] += 1
            if result.changed:
                changed.append(
                    {
                        "entry_id": entry["id"],
                        "stage_index": stage_index,
                        "before": original,
                        "after": result.text,
                        "before_line_widths": list(
                            dialogue_line_widths(
                                original,
                                protected_terms=protected_terms,
                            )
                        ),
                        "after_line_widths": list(result.line_widths),
                    }
                )
                if args.apply:
                    entry["translation"] = result.text
            projected_entries.append(
                {
                    **entry,
                    "translation": result.text,
                }
            )
            widest_width = max(
                widest_width,
                max(result.line_widths, default=0),
            )
            total_entries += 1
        after_distribution = _distribution(projected_entries)
        stage_reports[str(stage_index)] = {
            "entry_count": len(entries),
            "before_line_count_distribution": before_distribution,
            "after_line_count_distribution": after_distribution,
        }
        if args.apply:
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    report = {
        "schema_version": 1,
        "status": "applied"
        if args.apply
        else ("passed" if not changed else "changes_required"),
        "line_width": args.line_width,
        "maximum_lines": args.max_lines,
        "player_name_render_width": 6,
        "entry_count": total_entries,
        "stage_count": len(translation_paths),
        "protected_glossary_term_count": len(protected_terms),
        "changed_entry_count": len(changed),
        "preserved_entry_counts": dict(sorted(preserved.items())),
        "maximum_projected_line_width": widest_width,
        "stages": stage_reports,
        "changes": changed,
    }
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Chinese dialogue layout: entries={total_entries} "
        f"changed={len(changed)} width={args.line_width} "
        f"max_lines={args.max_lines}"
    )
    print(f"layout report: {report_output}")
    if not args.apply and changed:
        print(
            "Chinese dialogue layout is not canonical; rerun with --apply",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, ChineseLayoutError) as error:
        print(f"Chinese dialogue reflow failed: {error}", file=sys.stderr)
        raise SystemExit(1)
