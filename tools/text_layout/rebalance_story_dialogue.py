#!/usr/bin/env python3
"""Move story-dialogue line breaks out of words using the layout engine.

Manual breaks stored in ``corpus/zh/story-dialogue`` are written to the ISO
verbatim whenever they fit the 21-cell x 3-line message window.  This tool
finds records whose stored break falls inside an unbroken term of the
``story_dialogue`` layout profile (a common word or a proper name) and lets the
engine choose a new break with the same logical text.  Records that overflow
the window are refitted the same way the builder already does at build time,
so the corpus stores what the game displays.

Every change is recorded with before/after text, line widths and the source
hash in a batch document under ``config/editorial``.

    python3 tools/text_layout/rebalance_story_dialogue.py --dry-run
    python3 tools/text_layout/rebalance_story_dialogue.py --batch-id story-layout-rebalance-20260926
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_story_component import (  # noqa: E402
    DEFAULT_CONFIG,
    _json,
    _locked_file,
    _project_path,
    _read_iso_member,
)
from srwz.chinese_layout import (  # noqa: E402
    ChineseLayoutError,
    dialogue_line_widths,
    fit_chinese_dialogue_layout,
    load_layout_profiles,
    logical_dialogue_text,
    reflow_chinese_dialogue,
    split_unbroken_terms,
)
from srwz.codec import decode_production as decode  # noqa: E402
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets  # noqa: E402
from srwz.stage import parse_stage, read_stage_function_addresses  # noqa: E402
from srwz.text import load_text_table  # noqa: E402

DIALOGUE_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
PROFILES_PATH = PROJECT_ROOT / "config/text-layout/zh-layout-profiles.json"
WORDS_PATH = PROJECT_ROOT / "config/text-layout/zh-story-unbroken-words.json"
EDITORIAL_DIR = PROJECT_ROOT / "config/editorial"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keyword_link_ids(config_path: Path = DEFAULT_CONFIG) -> frozenset[str]:
    """IDs of dialogue whose Japanese source carries runtime keyword links.

    The builder decides ``stage_keyword_links`` from the Japanese text, not the
    translation: ``《…》`` in a translation without a Japanese link is a plain
    book-title mark that occupies display cells.  This tool must measure the
    same way, so it decodes the locked source STAGE archive like the builder.
    """

    config = _json(config_path)
    source = config["source"]
    _slps_path, source_slps = _locked_file(source["slps"], label="source SLPS")
    _stage_path, source_stage = _locked_file(source["stage"], label="source STAGE")
    table_path, _ = _locked_file(source["text_table"], label="source text table")
    source_hb = _read_iso_member(_project_path(source["iso"]), source["hb"])
    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member=source["hb"]["member"],
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(source_hb, offset_spec, len(source_stage))
    functions = read_stage_function_addresses(source_slps)
    table = load_text_table(table_path)
    linked = set()
    for stage in range(len(offsets) - 1):
        chunk = source_stage[offsets[stage] : offsets[stage + 1]]
        if not chunk:
            continue
        parsed = parse_stage(
            decode(chunk).output,
            table,
            stage_index=stage,
            function_address=functions[stage],
        )
        for entry in parsed.entries:
            if entry.kind == "dialogue" and "《" in entry.text:
                linked.add(entry.entry_id)
    return frozenset(linked)


def split_terms(text: str, profile, *, stage_keyword_links: bool) -> list[str]:
    """Unbroken terms that the stored line breaks cut through (shared engine check)."""

    return list(
        split_unbroken_terms(
            text, profile=profile, stage_keyword_links=stage_keyword_links
        )
    )


def fits(text: str, profile, *, stage_keyword_links: bool) -> bool:
    widths = dialogue_line_widths(
        text,
        protected_terms=profile.unbroken_terms,
        stage_keyword_links=stage_keyword_links,
    )
    first = profile.first_line_maximum_width or profile.maximum_width
    return (
        len(widths) <= profile.maximum_lines
        and (not widths or widths[0] <= first)
        and all(width <= profile.maximum_width for width in widths[1:])
    )


def process(profile, *, write: bool, link_ids: frozenset[str]) -> dict:
    changes = []
    skipped = []
    files_touched = 0
    for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
        file_changed = False
        for entry in document["entries"]:
            text = entry["translation"]
            links = entry["id"] in link_ids
            hits = split_terms(text, profile, stage_keyword_links=links)
            overflow = not fits(text, profile, stage_keyword_links=links)
            if not hits and not overflow:
                continue
            try:
                if overflow:
                    result = fit_chinese_dialogue_layout(
                        text, profile=profile, stage_keyword_links=links
                    )
                else:
                    result = reflow_chinese_dialogue(
                        text, profile=profile, stage_keyword_links=links
                    )
            except (ChineseLayoutError, AssertionError) as error:
                skipped.append({"id": entry["id"], "reason": str(error)})
                continue
            if result.text == text:
                skipped.append({
                    "id": entry["id"],
                    "reason": result.preserved_reason or "engine_kept_original",
                })
                continue
            if logical_dialogue_text(result.text) != logical_dialogue_text(text):
                raise SystemExit(f"{entry['id']}: reflow changed logical text")
            remaining = split_terms(result.text, profile, stage_keyword_links=links)
            changes.append({
                "id": entry["id"],
                "file": str(path.relative_to(PROJECT_ROOT)),
                "kind": "overflow_refit" if overflow else "split_word",
                "runtime_keyword_links": links,
                "split_terms": hits,
                "before": text,
                "after": result.text,
                "line_widths_before": list(
                    dialogue_line_widths(
                        text,
                        protected_terms=profile.unbroken_terms,
                        stage_keyword_links=links,
                    )
                ),
                "line_widths_after": list(result.line_widths),
                "remaining_split_terms": remaining,
                "source_text_sha256": entry["source_text_sha256"],
            })
            entry["translation"] = result.text
            file_changed = True
        if file_changed and write:
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        files_touched += file_changed
    return {"changes": changes, "skipped": skipped, "files_touched": files_touched}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report only")
    parser.add_argument(
        "--batch-id",
        default=f"story-layout-rebalance-{dt.date.today():%Y%m%d}",
        help="batch document name under config/editorial",
    )
    args = parser.parse_args()
    profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]
    link_ids = keyword_link_ids()
    outcome = process(profile, write=not args.dry_run, link_ids=link_ids)
    changes = outcome["changes"]
    kinds = {}
    for change in changes:
        kinds[change["kind"]] = kinds.get(change["kind"], 0) + 1
    still_split = [c["id"] for c in changes if c["remaining_split_terms"]]
    print(
        f"records changed: {len(changes)} {kinds}; skipped: {len(outcome['skipped'])}; "
        f"files: {outcome['files_touched']}; still split after reflow: {len(still_split)}"
    )
    if args.dry_run:
        return 0
    document = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reason": (
            "剧情对白断行落在词或专名内部；用 story_dialogue 档（21 格 × 3 行，"
            "含不可拆分词表）重新选择断点。逻辑文本不变，只改换行位置。"
        ),
        "layout_profile": {
            "id": profile.profile_id,
            "first_line_maximum_width": profile.first_line_maximum_width,
            "maximum_width": profile.maximum_width,
            "maximum_lines": profile.maximum_lines,
            "profiles_sha256": _sha256(PROFILES_PATH),
            "unbroken_words_sha256": _sha256(WORDS_PATH),
            "unbroken_term_count": len(profile.unbroken_terms),
        },
        "counts": {
            "changed": len(changes),
            "by_kind": kinds,
            "skipped": len(outcome["skipped"]),
            "files_touched": outcome["files_touched"],
        },
        "changes": changes,
        "skipped": outcome["skipped"],
    }
    output = EDITORIAL_DIR / f"{args.batch_id}.json"
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {output.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
