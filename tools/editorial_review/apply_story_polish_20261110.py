#!/usr/bin/env python3
"""Write the confirmed 2026-11-10 story polish candidates into the corpus.

Dry run unless --apply.  Every line (and each same-source twin) must clear, in
order: a fresh online-suggestion snapshot (no opinion on the line or on the
same Japanese source), the protection set of the review package, and the base
text recorded when the candidate was read.  Layout, glyph and control-code
gates were applied by work/review/story-polish-20261110/finalize.py.

    python3 tools/editorial_review/apply_story_polish_20261110.py
    python3 tools/editorial_review/apply_story_polish_20261110.py --apply --authorization "..."
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "work/review/story-polish-20261110"
RECEIPT = ROOT / "config/editorial/story-polish-20261110.json"
API = "https://srwz.dreamquest.club/api/review-suggestions?status=all&scope=all&limit=500&offset={offset}"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s「」『』…・!！?？、。,.~〜ー\-—]", "", text)


def fetch_online() -> dict:
    rows, offset, total = [], 0, None
    while total is None or offset < total:
        request = urllib.request.Request(API.format(offset=offset), headers={"User-Agent": "srwz-zh-story-polish"})
        with urllib.request.urlopen(request, timeout=60) as response:
            page = json.load(response)
        total = page["total"]
        if not page["suggestions"]:
            break
        rows.extend(page["suggestions"])
        offset += len(page["suggestions"])
    if total is None or len({row["id"] for row in rows}) != total:
        raise SystemExit(f"online suggestions incomplete: {len(rows)} of {total}")
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), "total": total, "all": rows}


def refresh_active_locks(changed: set[str]) -> list[dict]:
    """Refresh {path, sha256[, size]} nodes in active configs; editorial receipts stay as history."""
    locks = []
    configs = [p for p in (ROOT / "config").rglob("*.json") if "editorial" not in p.parts]
    changed = set(changed)
    for _ in range(6):
        updated = []
        for config in configs:
            document = json.loads(config.read_text(encoding="utf-8"))
            edits = []

            def visit(node, at=""):
                if isinstance(node, dict):
                    if node.get("path") in changed and "sha256" in node:
                        target = ROOT / node["path"]
                        digest, size = sha(target.read_bytes()), target.stat().st_size
                        if node["sha256"] != digest or ("size" in node and node["size"] != size):
                            before = copy.deepcopy(node)
                            node["sha256"] = digest
                            if "size" in node:
                                node["size"] = size
                            edits.append(dict(pointer=at, before=before, after=copy.deepcopy(node)))
                    for key, value in list(node.items()):
                        visit(value, f"{at}/{key}")
                elif isinstance(node, list):
                    for index, value in enumerate(node):
                        visit(value, f"{at}/{index}")

            visit(document)
            if edits:
                rel = str(config.relative_to(ROOT))
                config.write_text(dump(document), encoding="utf-8")
                locks.append(dict(file=rel, edits=edits))
                updated.append(rel)
        if not updated:
            return locks
        changed.update(updated)
    raise SystemExit("cyclic lock refresh")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--online-snapshot", type=Path)
    args = parser.parse_args()
    if args.apply and not args.authorization:
        raise SystemExit("--apply needs --authorization")
    if args.apply and RECEIPT.exists():
        raise SystemExit(f"already applied: {RECEIPT.relative_to(ROOT)}")

    final = json.loads((REVIEW / "final.json").read_text(encoding="utf-8"))
    held = json.loads((REVIEW / "held.json").read_text(encoding="utf-8"))
    rejected = json.loads((REVIEW / "rejected.json").read_text(encoding="utf-8"))
    meta = json.loads((REVIEW / "meta.json").read_text(encoding="utf-8"))
    protected = json.loads((REVIEW / "protected.json").read_text(encoding="utf-8"))
    if args.online_snapshot:
        online = json.loads(args.online_snapshot.read_text(encoding="utf-8"))
    else:
        online = fetch_online()
        (REVIEW / "online-snapshot-writeback.json").write_text(json.dumps(online, ensure_ascii=False), encoding="utf-8")
    direct = {row["targetId"] for row in online["all"] if row["targetType"] == "dialogue"}
    same_source = {norm(row.get("sourceText")) for row in online["all"]} - {""}

    documents, raws, where = {}, {}, {}
    for rel in sorted({m["file"] for m in meta.values()}):
        raws[rel] = (ROOT / rel).read_bytes()
        documents[rel] = json.loads(raws[rel])
        if dump(documents[rel]).encode("utf-8") != raws[rel]:
            raise SystemExit(f"{rel}: not in canonical dump form")
        for entry in documents[rel]["entries"]:
            where[entry["id"]] = (rel, entry)

    planned, skipped, seen = [], [], set()
    for row in final:
        targets = [(row["id"], "primary")] + [(twin, "twin") for twin in row["twins"]]
        for identity, role in targets:
            reasons = []
            rel, entry = where[identity]
            if identity in seen:
                reasons.append("duplicate target")
            if identity in direct:
                reasons.append("online suggestion on this line")
            if norm(meta[identity]["ja"]) in same_source:
                reasons.append("online suggestion on the same Japanese source")
            if identity in protected:
                reasons.append("protected")
            if entry["translation"] != row["old"]:
                reasons.append("base drift")
            item = dict(id=identity, role=role, number=row["n"], file=rel, kind=row["kind"], why=row["why"],
                        before=row["old"], after=row["new"], edited=bool(row.get("edited")))
            if reasons:
                skipped.append(dict(item, reasons=reasons))
                if role == "primary":
                    break  # twins follow their primary
            else:
                seen.add(identity)
                planned.append(item)

    summary = dict(candidates=len(final), held=len(held), rejected=len(rejected),
                   write=len(planned), primary=sum(r["role"] == "primary" for r in planned),
                   twins=sum(r["role"] == "twin" for r in planned), skipped=len(skipped),
                   files=len({r["file"] for r in planned}), by_kind=dict(Counter(r["kind"] for r in planned)),
                   skip_reasons=dict(Counter(x for r in skipped for x in r["reasons"])),
                   online_snapshot_at=online["fetched_at"], online_snapshot_total=online["total"])
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not args.apply:
        (REVIEW / "writeback-dry-run.json").write_text(dump(dict(summary=summary, write=planned, skipped=skipped)), encoding="utf-8")
        return 0

    by_file = defaultdict(list)
    for row in planned:
        where[row["id"]][1]["translation"] = row["after"]
        by_file[row["file"]].append(row["id"])
    files = []
    for rel in sorted(by_file):
        data = dump(documents[rel]).encode("utf-8")
        target = ROOT / rel
        temporary = target.with_suffix(".writeback-tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        files.append(dict(path=rel, entries=len(by_file[rel]), before_sha256=sha(raws[rel]), after_sha256=sha(data)))
    locks = refresh_active_locks(set(by_file))
    receipt = dict(
        schema_version=1, review_id="story-polish-20261110", translation_writeback=True,
        purpose="发布前剧情对话全量通读润色：误译、漏译、前后文不通、生硬、语气、口吻。只写入主审两遍确认、且通过线上意见复核、保护集、基线、版式和字形校验的候选；同源句（同日文、同说话人、同现译）随主条写入。",
        authorization=args.authorization,
        feedback_snapshot_at=online["fetched_at"], feedback_snapshot_total=online["total"],
        candidate_package=dict(path="work/review/story-polish-20261110/final.json", sha256=sha((REVIEW / "final.json").read_bytes())),
        summary=summary, application=dict(files=files, active_lock_updates=locks, site_writeback=False),
        entries=planned, skipped=skipped,
        held=[dict(id=r["id"], number=r["n"], before=r["old"], proposed=r["new"], why=r["why"]) for r in held],
        rejected=[dict(id=r["id"], number=r["n"], proposed=r["new"], why=r["why"]) for r in rejected],
    )
    RECEIPT.write_text(dump(receipt), encoding="utf-8")
    print(f"wrote {len(planned)} lines in {len(files)} files; receipt {RECEIPT.relative_to(ROOT)}; lock files {[l['file'] for l in locks]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
