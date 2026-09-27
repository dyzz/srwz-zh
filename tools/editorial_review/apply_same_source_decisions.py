#!/usr/bin/env python3
"""Write back chosen wordings for same-source dialogue groups.

Input: a decisions JSON of the form::

    {"batch_id": "...", "reason": "...",
     "decisions": [{"source_text_sha256": "...", "chosen": "<exact text>",
                    "reason": "site_attention|manual|..."}]}

For every decision, every corpus record with that source hash whose speaker
matches the chosen record's speaker and whose surrounding lines match (the same
identical-situation rule as ``unify_same_source_dialogue.py``) is set to the
chosen text.  Records in other scenes or by other speakers are never touched.
The chosen text must already exist on one member of the group and must pass
the layout gate.  A batch record with before/after per record is written under
``config/editorial``.

    python3 tools/editorial_review/apply_same_source_decisions.py decisions.json --dry-run
    python3 tools/editorial_review/apply_same_source_decisions.py decisions.json
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/editorial_review"))

from rebalance_story_dialogue import source_dialogue_index  # noqa: E402
from srwz.chinese_layout import dialogue_layout_issues, load_layout_profiles  # noqa: E402
from unify_same_source_dialogue import (  # noqa: E402
    ContextIndex,
    DIALOGUE_ROOT,
    EDITORIAL_DIR,
    PROFILES_PATH,
    load_corpus,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.decisions.read_text(encoding="utf-8"))
    batch_id = document["batch_id"]
    corpus = load_corpus()
    context = ContextIndex(corpus)
    source_index = source_dialogue_index()
    profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]
    by_source: dict[str, list[tuple[Path, dict]]] = collections.defaultdict(list)
    for path, doc in corpus.items():
        for entry in doc["entries"]:
            by_source[entry["source_text_sha256"]].append((path, entry))

    changes = []
    skipped = []
    touched = set()
    for decision in document["decisions"]:
        sha = decision["source_text_sha256"]
        chosen = decision["chosen"]
        members = by_source.get(sha, [])
        holders = [e for _, e in members if e["translation"] == chosen]
        if not holders:
            raise SystemExit(f"{sha[:12]}: chosen text is not held by any member")
        anchor = holders[0]
        speaker = source_index[anchor["id"]]["speaker"]
        links = source_index[anchor["id"]]["keyword_links"]
        issues = dialogue_layout_issues(chosen, profile=profile, stage_keyword_links=links)
        if issues:
            raise SystemExit(f"{anchor['id']}: chosen text fails layout gate: {issues}")
        for path, entry in members:
            if entry["translation"] == chosen:
                continue
            if source_index[entry["id"]]["speaker"] != speaker:
                skipped.append({"id": entry["id"], "reason": "different speaker"})
                continue
            if not context.identical_situation([entry["id"], anchor["id"]]):
                skipped.append({"id": entry["id"], "reason": "different context"})
                continue
            changes.append({
                "id": entry["id"],
                "file": str(path.relative_to(PROJECT_ROOT)),
                "source_text_sha256": sha,
                "source_text": source_index[entry["id"]]["text"],
                "speaker": speaker,
                "reason": decision.get("reason", "manual"),
                "note": decision.get("note", ""),
                "before": entry["translation"],
                "after": chosen,
                "anchor_id": anchor["id"],
            })
            entry["translation"] = chosen
            touched.add(path)
    print(f"decisions {len(document['decisions'])}: {len(changes)} records change, {len(skipped)} skipped, {len(touched)} files")
    for s in skipped:
        print("  skipped", s)
    if args.dry_run:
        return 0
    for path in sorted(touched):
        path.write_text(json.dumps(corpus[path], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {
        "schema_version": 1,
        "batch_id": batch_id,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reason": document.get("reason", ""),
        "decisions_file": str(args.decisions),
        "counts": {
            "decisions": len(document["decisions"]),
            "changed": len(changes),
            "by_reason": dict(collections.Counter(c["reason"] for c in changes)),
            "skipped": len(skipped),
            "files_touched": len(touched),
        },
        "changes": changes,
        "skipped": skipped,
    }
    out = EDITORIAL_DIR / f"{batch_id}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
