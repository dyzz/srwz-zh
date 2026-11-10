#!/usr/bin/env python3
"""Write accepted battle-polish candidates (2026-11-09) back to the SRVC corpus.

Dry run unless --apply. Every accepted candidate must clear, in order: the online
review suggestions fetched now (same line, or the same Japanese source, in any state),
the human-finalised list, the corpus baseline it was drafted against, the candidate
checker, the stored battle geometry gate and the short-last-row rule. Anything that
fails is skipped and listed, never forced.

  python3 tools/editorial_review/apply_battle_polish_20261109.py --accept-all
  python3 tools/editorial_review/apply_battle_polish_20261109.py --decisions FILE --apply
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

REVIEW = ROOT / "work/review/battle-polish-20261109"
CORPUS = ROOT / "corpus/zh/battle/srvc-lines.json"
CORPUS_REF = "corpus/zh/battle/srvc-lines.json"
RECEIPT = ROOT / "config/editorial/battle-polish-20261109.json"
API = "https://srwz.dreamquest.club/api/review-suggestions?status=all&scope=all&limit=500&offset={offset}"
PUNCTUATION = "…！？，。~〜♪—、”“）（"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def refresh_battle_input_lock(before: dict, after: dict) -> list[str]:
    """Refresh the active corpus owner, never historical editorial receipts."""
    path = ROOT / "config/full-story-components.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document["srvc_battle_text"]["corpus"] != before:
        raise SystemExit("battle corpus input lock drift: config/full-story-components.json")
    document["srvc_battle_text"]["corpus"] = after
    path.write_text(dump(document), encoding="utf-8")
    return [str(path.relative_to(ROOT))]


def norm(text: str) -> str:
    """Japanese source identity, as recheck/build_packets.py protects it."""

    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[\s「」『』…・!！?？、。,.~〜ー\-—\\n]|\\n", "", text)


def fetch_online() -> dict:
    rows, offset, total = [], 0, None
    while total is None or offset < total:
        request = urllib.request.Request(API.format(offset=offset), headers={"User-Agent": "srwz-zh-battle-polish"})
        with urllib.request.urlopen(request, timeout=60) as response:
            page = json.load(response)
        batch = page["suggestions"]
        total = page["total"]
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
    if total is None or len({row["id"] for row in rows}) != total:
        raise SystemExit(f"online suggestions incomplete: {len(rows)} of {total}")
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), "total": total, "all": rows}


def compose(text: str, current: str) -> str:
    """Review-page text (``/`` = row break, no quotes) to the stored form."""

    parts = [part.strip() for part in text.split("/")]
    body = "\\n\u3000".join(parts)
    return ("“" if current.startswith("“") else "") + body + ("”" if current.endswith("”") else "")


def short_last_row(stored: str) -> bool:
    rows = stored.split("\\n")
    if len(rows) < 2:
        return False
    core = re.sub(r"<[^>]*>", "", rows[-1]).replace("\u3000", "")
    return len([ch for ch in core if ch not in PUNCTUATION]) <= 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--decisions", type=Path, help="battle-polish-decisions.json exported from the review page")
    source.add_argument("--accept-all", action="store_true", help="treat every candidate as accepted with its proposed text")
    parser.add_argument("--authorization", default="", help="the user's words that authorise this write-back (required with --apply)")
    parser.add_argument("--online-snapshot", type=Path, help="reuse a snapshot fetched by an earlier dry run")
    parser.add_argument("--report", type=Path, default=REVIEW / "writeback-dry-run.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.authorization:
        raise SystemExit("--apply needs --authorization")

    package = json.loads((REVIEW / "candidates.json").read_text(encoding="utf-8"))
    candidates = {row["id"]: row for row in package["candidates"]}
    raw = CORPUS.read_bytes()
    document = json.loads(raw)
    if dump(document).encode("utf-8") != raw:
        raise SystemExit("battle corpus is not in canonical serialisation")
    entries = {entry["id"]: entry for entry in document["entries"]}
    protected = json.loads((REVIEW / "protected.json").read_text(encoding="utf-8"))
    # Receipts written after the candidates were drafted finalise more lines.
    drafted_at = (REVIEW / "candidates.json").stat().st_mtime
    finalised_later = {}
    for path in sorted((ROOT / "config/editorial").rglob("*.json")):
        if path != RECEIPT and path.stat().st_mtime > drafted_at:
            for identity in set(re.findall(r"battle:\d{5}", path.read_text(encoding="utf-8"))):
                finalised_later.setdefault(identity, path.name)

    if args.accept_all:
        decisions = [dict(id=row["id"], decision="accept", text=row["new"], edited=False) for row in package["candidates"]]
    else:
        exported = json.loads(args.decisions.read_text(encoding="utf-8"))
        if exported.get("batch") != "battle-polish-20261109":
            raise SystemExit("decision file belongs to another batch")
        decisions = exported["decisions"]
    accepted = [row for row in decisions if row["decision"] == "accept"]
    if len({row["id"] for row in accepted}) != len(accepted):
        raise SystemExit("duplicate decisions")

    if args.online_snapshot:
        online = json.loads(args.online_snapshot.read_text(encoding="utf-8"))
    else:
        online = fetch_online()
        (REVIEW / "online-snapshot-writeback.json").write_text(dump(online), encoding="utf-8")
    direct = {row["targetId"] for row in online["all"] if row["targetType"] == "battle-line"}
    same_source = {norm(row.get("sourceText") or "") for row in online["all"]}
    same_source.discard("")

    spec = importlib.util.spec_from_file_location("battle_polish_check_ctx", REVIEW / "recheck/check_ctx.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    from srwz.build_layout import stored_geometry_issues

    planned, skipped = [], []
    for row in accepted:
        identity, reasons = row["id"], []
        candidate, entry = candidates.get(identity), entries.get(identity)
        if candidate is None or entry is None:
            skipped.append(dict(id=identity, reasons=["not a candidate of this batch"]))
            continue
        if identity in direct:
            reasons.append("online suggestion on this line")
        elif norm(candidate["ja"]) in same_source:
            reasons.append("online suggestion on the same Japanese source")
        if identity in protected:
            reasons.append("human-finalised line")
        if identity in finalised_later:
            reasons.append(f"finalised after drafting by {finalised_later[identity]}")
        if entry["translation"] != candidate["curFull"]:
            reasons.append("corpus translation changed since the candidate was drafted")
        if entry["source_text_sha256"] != candidate["sha"]:
            reasons.append("source hash drift")
        text = row["text"]
        stored = compose(text, candidate["curFull"])
        if not row.get("edited") and stored != candidate["full"]:
            reasons.append("composed text differs from the reviewed candidate")
        if stored.count("\\n") != candidate["curFull"].count("\\n"):
            reasons.append("row count differs from the current line")
        # The candidate checker rejects any short row, but a short first row that the
        # current line already has is an original break and stays (user rule: only a
        # one-character or punctuation-only last row is a defect).
        current_rows = candidate["curFull"].count("\\n") + 1
        for reason in checker.check(dict(id=identity, new=text)):
            short = reason.startswith("row too short: ") and current_rows == 2 and reason[len("row too short: "):] != text.split("/")[-1]
            if not short:
                reasons.append(reason)
        if short_last_row(stored):
            reasons.append("last row is one character or punctuation only")
        if reasons:
            skipped.append(dict(id=identity, reasons=reasons))
        else:
            planned.append(dict(id=identity, before=entry["translation"], after=stored, kind=candidate["kind"],
                                why=row.get("note") or candidate.get("why", ""), edited=bool(row.get("edited")), source=candidate["source"]))
    geometry = stored_geometry_issues([(row["id"], row["after"], False) for row in planned], "battle")
    for row in [row for row in planned if row["id"] in geometry]:
        skipped.append(dict(id=row["id"], reasons=list(geometry[row["id"]])))
    planned = [row for row in planned if row["id"] not in geometry]

    summary = dict(candidates=len(candidates), decisions=len(decisions), accepted=len(accepted),
                   rejected=sum(row["decision"] == "reject" for row in decisions),
                   held=sum(row["decision"] == "hold" for row in decisions),
                   write=len(planned), skipped=len(skipped), edited=sum(row["edited"] for row in planned),
                   online_snapshot_at=online["fetched_at"], online_snapshot_total=online["total"])
    reasons = {}
    for row in skipped:
        for reason in row["reasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    summary["skip_reasons"] = dict(sorted(reasons.items(), key=lambda item: -item[1]))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not args.apply:
        args.report.write_text(dump(dict(summary=summary, write=planned, skipped=skipped)), encoding="utf-8")
        print(f"dry run: {args.report.relative_to(ROOT)}")
        return 0
    if not planned:
        raise SystemExit("nothing to write")

    for row in planned:
        entries[row["id"]]["translation"] = row["after"]
    after = dump(document).encode("utf-8")
    before_lock = dict(path=CORPUS_REF, size=len(raw), sha256=sha256_bytes(raw))
    after_lock = dict(path=CORPUS_REF, size=len(after), sha256=sha256_bytes(after))
    refreshed = refresh_battle_input_lock(before_lock, after_lock)
    CORPUS.write_bytes(after)
    receipt = dict(
        schema_version=1, review_id="battle-polish-20261109", translation_writeback=True,
        purpose="战斗台词全量润色：误译、漏译、不通顺、语气、口吻。只写入通过线上意见复核、基线、版式和字形校验的候选。",
        authorization=args.authorization,
        feedback_snapshot_at=online["fetched_at"], feedback_snapshot_total=online["total"],
        candidate_package=dict(path="work/review/battle-polish-20261109/candidates.json",
                               sha256=sha256_bytes((REVIEW / "candidates.json").read_bytes())),
        summary=summary,
        application=dict(files=[dict(path=CORPUS_REF, before_sha256=before_lock["sha256"], after_sha256=after_lock["sha256"])],
                         input_lock_refresh=dict(before=before_lock, after=after_lock, files=refreshed), site_writeback=False),
        entries=planned, skipped=skipped,
    )
    RECEIPT.write_text(dump(receipt), encoding="utf-8")
    print(f"wrote {len(planned)} lines; receipt {RECEIPT.relative_to(ROOT)}; refreshed {len(refreshed)} lock files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
