#!/usr/bin/env python3
"""Write the user's picks for the title-demo battle lines (2026-11-13) back to the SRVC corpus.

The title-idle demo (BTL/OP0-2.BIN) draws its subtitles from the regular battle lines; the
99 lines it shows were captured in the ARMSX2 runner and offered on
work/review/opening-demo-lines-20261113. Dry run unless --apply. Every written line must
clear: no online suggestion newer than the page's snapshot (same line or same Japanese
source), the corpus text the page showed, the round-3 checker and the stored battle
geometry gate.

  python3 tools/editorial_review/apply_opening_demo_lines_20261113.py
  python3 tools/editorial_review/apply_opening_demo_lines_20261113.py --apply --authorization "..."
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

REVIEW = ROOT / "work/review/opening-demo-lines-20261113"
RECEIPT = ROOT / "config/editorial/opening-demo-lines-20261113.json"
# ブレストバーン is 胸部火焰 in the weapon glossary (user, 2026-09-04); the user chose to unify the shout.
TERM = {"battle:07277": dict(text="胸部火焰！！", kind="term", why="ブレストバーン跟武器表统一为“胸部火焰”")}
# A pick of "now" means the text first proposed in this session (not in HEAD).
NOW = {"battle:10512": "就算是第二世代机体又怎样！"}
CHECK_ALLOW = {"term"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.authorization:
        raise SystemExit("--apply needs --authorization")
    picks = json.loads((REVIEW / "decisions-user-20261113.json").read_text(encoding="utf-8"))
    proposals = {row["id"]: row for row in json.loads((REVIEW / "proposals.json").read_text(encoding="utf-8"))["changes"]}
    page_rows = json.loads((REVIEW / "lines.json").read_text(encoding="utf-8"))
    raw = base.CORPUS.read_bytes()
    document = json.loads(raw)
    if base.dump(document).encode("utf-8") != raw:
        raise SystemExit("battle corpus is not in canonical serialisation")
    entries = {entry["id"]: entry for entry in document["entries"]}

    wanted = []
    for identity, pick in picks["choices"].items():
        if pick == "cur":
            continue
        if pick == "now":
            wanted.append(dict(id=identity, text=NOW[identity], **{k: proposals[identity][k] for k in ("kind", "why")},
                               evidence=proposals[identity].get("evidence", "")))
        elif pick == "new":
            row = proposals[identity]
            wanted.append(dict(id=identity, text=row["new"], kind=row["kind"], why=row["why"], evidence=row.get("evidence", "")))
        else:
            raise SystemExit(f"unknown pick {pick!r} for {identity}")
    if picks.get("term") == "unify":
        wanted += [dict(id=identity, evidence="", **row) for identity, row in TERM.items()]

    snapshot = json.loads((REVIEW / "online.json").read_text(encoding="utf-8"))
    known = {row["id"]: row.get("updatedAt") for row in snapshot["all"]}
    online = base.fetch_online()
    (REVIEW / "online-snapshot-writeback.json").write_text(base.dump(online), encoding="utf-8")
    fresh = [row for row in online["all"] if known.get(row["id"], "new") != row.get("updatedAt")]
    direct = {row["targetId"] for row in fresh if row["targetType"] == "battle-line"}
    same_source = {base.norm(row.get("sourceText") or "") for row in fresh} - {""}
    sources = {row["id"]: row["ja"] for row in page_rows}
    shown = {row["id"]: row["zh"] for row in page_rows}

    spec = importlib.util.spec_from_file_location("battle_polish_check_20261110", ROOT / "work/review/battle-polish-20261110/check.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    from srwz.build_layout import stored_geometry_issues

    planned, skipped = [], []
    for row in wanted:
        identity, reasons = row["id"], []
        entry = entries.get(identity)
        if entry is None:
            skipped.append(dict(id=identity, reasons=["unknown line"]))
            continue
        current = entry["translation"]
        if identity in direct:
            reasons.append("online suggestion on this line since the page was built")
        elif base.norm(sources.get(identity, "")) in same_source:
            reasons.append("online suggestion on the same Japanese source since the page was built")
        if identity in shown and current != shown[identity] and identity not in NOW:
            reasons.append("corpus translation changed since the page was built")
        stored = base.compose(row["text"], current)
        if row["kind"] not in CHECK_ALLOW:
            for reason in checker.check(dict(id=identity, new=row["text"], kind=row["kind"], evidence=row.get("evidence", ""))):
                if not reason.startswith("reviewed line"):
                    reasons.append(reason)
        if base.short_last_row(stored):
            reasons.append("last row is one character or punctuation only")
        if reasons:
            skipped.append(dict(id=identity, reasons=reasons))
            continue
        item = dict(id=identity, before=current, after=stored, kind=row["kind"], why=row["why"])
        if row.get("evidence"):
            item["evidence"] = row["evidence"]
        planned.append(item)
    geometry = stored_geometry_issues([(row["id"], row["after"], False) for row in planned], "battle")
    skipped += [dict(id=row["id"], reasons=list(geometry[row["id"]])) for row in planned if row["id"] in geometry]
    planned = [row for row in planned if row["id"] not in geometry]
    summary = dict(page_lines=len(page_rows), offered=len(proposals) + len(TERM), picked=len(wanted), write=len(planned), skipped=len(skipped),
                   kept_current=sorted(i for i, p in picks["choices"].items() if p == "cur"),
                   online_page_snapshot_at=snapshot["fetched_at"], online_snapshot_at=online["fetched_at"],
                   online_snapshot_total=online["total"], online_changed_since_page=len(fresh))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for row in planned:
        print("WRITE", row["id"], row["before"], "->", row["after"])
    for row in skipped:
        print("SKIP", row["id"], row["reasons"])
    if not args.apply:
        (REVIEW / "writeback-dry-run.json").write_text(base.dump(dict(summary=summary, write=planned, skipped=skipped)), encoding="utf-8")
        return 0
    if skipped:
        raise SystemExit("refusing to write while picks are skipped")
    for row in planned:
        entries[row["id"]]["translation"] = row["after"]
    after = base.dump(document).encode("utf-8")
    before_lock = dict(path=base.CORPUS_REF, size=len(raw), sha256=base.sha256_bytes(raw))
    after_lock = dict(path=base.CORPUS_REF, size=len(after), sha256=base.sha256_bytes(after))
    refreshed = base.refresh_battle_input_lock(before_lock, after_lock)
    base.CORPUS.write_bytes(after)
    RECEIPT.write_text(base.dump(dict(
        schema_version=1, review_id="opening-demo-lines-20261113", translation_writeback=True,
        purpose="标题画面闲置 demo（BTL/OP0-2.BIN）所用的 99 条战斗台词精翻：ARMSX2 实录取全集，Claude 提建议，用户在挑选页逐条选定；ブレストバーン 台词跟武器表统一为“胸部火焰”。",
        authorization=args.authorization, feedback_snapshot_at=online["fetched_at"], feedback_snapshot_total=online["total"],
        decisions=dict(path="work/review/opening-demo-lines-20261113/decisions-user-20261113.json",
                       sha256=base.sha256_bytes((REVIEW / "decisions-user-20261113.json").read_bytes())),
        summary=summary,
        application=dict(files=[dict(path=base.CORPUS_REF, before_sha256=before_lock["sha256"], after_sha256=after_lock["sha256"])],
                         input_lock_refresh=dict(before=before_lock, after=after_lock, files=refreshed), site_writeback=False),
        entries=planned)), encoding="utf-8")
    print(f"wrote {len(planned)} lines; receipt {RECEIPT.relative_to(ROOT)}; refreshed {len(refreshed)} lock files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
