#!/usr/bin/env python3
"""Write the confirmed round-3 battle polish (2026-11-10) back to the SRVC corpus.

Dry run unless --apply. Every accepted line must clear: no online review suggestion
newer than the snapshot the round was drafted against (same line or same Japanese
source), the corpus text it was drafted against, the round's checker, the stored
battle geometry gate and the short-last-row rule. Lines that already carried a review
opinion are written only as recorded corrections of an error, with the evidence kept
in the receipt.

  python3 tools/editorial_review/apply_battle_polish_20261110.py
  python3 tools/editorial_review/apply_battle_polish_20261110.py --apply --authorization "..."
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_battle_polish_20261109 as base  # noqa: E402

REVIEW = ROOT / "work/review/battle-polish-20261110"
RECEIPT = ROOT / "config/editorial/battle-polish-20261110.json"
# Checker findings that are the point of the correction, not a defect.
ALLOW = {"battle:14873": "term dropped: 泽拉拜亚", "battle:04746": "text unchanged (do not report break-only changes)"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.authorization:
        raise SystemExit("--apply needs --authorization")
    decisions = json.loads((REVIEW / "decisions-claude-20261110.json").read_text(encoding="utf-8"))["decisions"]
    accepted = [row for row in decisions if row["decision"] == "accept"]
    raw = base.CORPUS.read_bytes()
    document = json.loads(raw)
    if base.dump(document).encode("utf-8") != raw:
        raise SystemExit("battle corpus is not in canonical serialisation")
    entries = {entry["id"]: entry for entry in document["entries"]}
    drafted = json.loads((REVIEW / "online-snapshot.json").read_text(encoding="utf-8"))
    known = {row["id"]: row.get("updatedAt") for row in drafted["all"]}
    online = base.fetch_online()
    (REVIEW / "online-snapshot-writeback.json").write_text(base.dump(online), encoding="utf-8")
    fresh = [row for row in online["all"] if known.get(row["id"], "new") != row.get("updatedAt")]
    direct = {row["targetId"] for row in fresh if row["targetType"] == "battle-line"}
    same_source = {base.norm(row.get("sourceText") or "") for row in fresh} - {""}
    sources = {}
    for path in sorted((ROOT.parent / "srwz-community-web/public/data/catalog").glob("work-*.json")):
        for line in json.loads(path.read_text(encoding="utf-8")).get("battleLines", []):
            sources[line["id"]] = line["sourceText"]

    spec = importlib.util.spec_from_file_location("battle_polish_check_20261110", REVIEW / "check.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    from srwz.build_layout import stored_geometry_issues

    show = lambda stored: stored.replace("\\n\u3000", "/").replace("\\n", "/").strip("“”")
    planned, skipped = [], []
    for row in accepted:
        identity, reasons, entry = row["id"], [], entries.get(row["id"])
        if entry is None:
            skipped.append(dict(id=identity, reasons=["unknown line"]))
            continue
        current = entry["translation"]
        if identity in direct:
            reasons.append("online suggestion on this line since the round was drafted")
        elif base.norm(sources.get(identity, "")) in same_source:
            reasons.append("online suggestion on the same Japanese source since the round was drafted")
        if show(current) != row["cur"]:
            reasons.append("corpus translation changed since the candidate was drafted")
        stored = base.compose(row["text"], current)
        current_rows = current.count("\\n") + 1
        for reason in checker.check(dict(id=identity, new=row["text"], kind=row["kind"], evidence=row.get("evidence", ""))):
            short = reason.startswith("row too short: ") and current_rows == 2 and reason[len("row too short: "):] != row["text"].split("/")[-1]
            if not short and ALLOW.get(identity) != reason:
                reasons.append(reason)
        if base.short_last_row(stored):
            reasons.append("last row is one character or punctuation only")
        if reasons:
            skipped.append(dict(id=identity, reasons=reasons))
        else:
            item = dict(id=identity, before=current, after=stored, kind=row["kind"], why=row["why"], edited=bool(row.get("edited")), source=row["source"])
            if row.get("evidence"):
                item["evidence"] = row["evidence"]
            planned.append(item)
    geometry = stored_geometry_issues([(row["id"], row["after"], False) for row in planned], "battle")
    skipped += [dict(id=row["id"], reasons=list(geometry[row["id"]])) for row in planned if row["id"] in geometry]
    planned = [row for row in planned if row["id"] not in geometry]
    counts = {}
    for row in planned:
        counts[row["source"]] = counts.get(row["source"], 0) + 1
    summary = dict(decisions=len(decisions), accepted=len(accepted),
                   rejected=sum(row["decision"] == "reject" for row in decisions), held=sum(row["decision"] == "hold" for row in decisions),
                   write=len(planned), skipped=len(skipped), by_source=counts,
                   online_drafted_at=drafted["fetched_at"], online_snapshot_at=online["fetched_at"], online_snapshot_total=online["total"],
                   online_changed_since_draft=len(fresh))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for row in skipped:
        print("SKIP", row["id"], row["reasons"])
    if not args.apply:
        (REVIEW / "writeback-dry-run.json").write_text(base.dump(dict(summary=summary, write=planned, skipped=skipped)), encoding="utf-8")
        return 0
    if not planned:
        raise SystemExit("nothing to write")
    for row in planned:
        entries[row["id"]]["translation"] = row["after"]
    after = base.dump(document).encode("utf-8")
    before_lock = dict(path=base.CORPUS_REF, size=len(raw), sha256=base.sha256_bytes(raw))
    after_lock = dict(path=base.CORPUS_REF, size=len(after), sha256=base.sha256_bytes(after))
    refreshed = base.refresh_battle_input_lock(before_lock, after_lock)
    base.CORPUS.write_bytes(after)
    RECEIPT.write_text(base.dump(dict(
        schema_version=1, review_id="battle-polish-20261110", translation_writeback=True,
        purpose="战斗台词第三轮润色：全部台词带场景重读，Claude 逐条复核后确认的改动。审阅过的句子只在确实译错、漏译或有错字时改，证据记在条目里。",
        authorization=args.authorization, feedback_snapshot_at=online["fetched_at"], feedback_snapshot_total=online["total"],
        decisions=dict(path="work/review/battle-polish-20261110/decisions-claude-20261110.json",
                       sha256=base.sha256_bytes((REVIEW / "decisions-claude-20261110.json").read_bytes())),
        summary=summary,
        application=dict(files=[dict(path=base.CORPUS_REF, before_sha256=before_lock["sha256"], after_sha256=after_lock["sha256"])],
                         input_lock_refresh=dict(before=before_lock, after=after_lock, files=refreshed), site_writeback=False),
        entries=planned, skipped=skipped)), encoding="utf-8")
    print(f"wrote {len(planned)} lines; receipt {RECEIPT.relative_to(ROOT)}; refreshed {len(refreshed)} lock files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
