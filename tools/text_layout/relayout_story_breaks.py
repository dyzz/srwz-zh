#!/usr/bin/env python3
"""Re-break main-game story and map dialogue along the Japanese rows and reviewed breaks.

The 2026-11-08 tag-free migration re-partitioned every record to the fewest
rows and the 2026-11-10 map pass balanced the overflowing ones, so stored and
Japanese breaks were merged away.  This tool restores them; wording never
changes.  Rules live in ``story_breaks.mjs``.

    python3 tools/text_layout/relayout_story_breaks.py --online-snapshot SNAPSHOT.json
    python3 tools/text_layout/relayout_story_breaks.py --online-snapshot SNAPSHOT.json --write

SNAPSHOT is the review-suggestion export (``{"all": [...]}``).  A record counts
as reviewed when it has an online dialogue opinion or appears in a human
decision receipt under ``config/editorial``.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/editorial_review"))

from check_story_dialogue_layout import DIALOGUE_ROOT, keyword_link_ids  # noqa: E402
from japanese_sources import disc_sources  # noqa: E402
from srwz.build_layout import dialogue_scene  # noqa: E402

# Last corpus state before the mechanical reflow (756a5ac0).
PRE_REFLOW_COMMIT = "d2a96df2"
REFLOW_DATE = "2026-11-08"
# Every file the Special Disc stage writer binds dialogue from.
SP_FILES = (PROJECT_ROOT / "corpus/zh/special-disc/story-dialogue.json",
            PROJECT_ROOT / "corpus/zh/special-disc/challenge-dialogue.json",
            PROJECT_ROOT / "config/editorial/special-disc/stage-native-overrides.json",
            PROJECT_ROOT / "config/editorial/special-disc/stage-context-reuse.json")
RECORD_ID = re.compile(r"story/\d{3}/dialogue/\d\d\.\d\d/\d{4}")
# Receipts written by tools, not by a person deciding on a line.
MECHANICAL = re.compile(
    r"^(compact-|same-source-unify|same-source-final-repair|same-source-scene-completion|remaining-duplicates|"
    r"low-hanging-triage|story-ending-punctuation|story-layout-|story-punctuation-numerals|story-number-time-breaks|"
    r"sp-format-layout|location-captions|quote-unification|visible-text-storage|prose-width|balanced-prose|"
    r"name-unification|main-old-renderings|nero-layout-compat|obvious-errors-expanded|opaque-text-review|"
    r"japanese-calques-review|edition-battle-sync|community-layout|community-site-readable-text|"
    r"community-site-cache|map-dialogue-width|story-breaks-)")


def untagged(text):
    return re.sub(r"</?z>", "", text or "", flags=re.I)


def logical(text):
    return re.sub(r"\n[　 ]*", "", text or "")


def pre_reflow_texts():
    texts = {}
    for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
        shown = subprocess.run(["git", "show", f"{PRE_REFLOW_COMMIT}:{path.relative_to(PROJECT_ROOT)}"],
                               cwd=PROJECT_ROOT, capture_output=True)
        if shown.returncode == 0:
            for entry in json.loads(shown.stdout)["entries"]:
                texts[entry["id"]] = untagged(entry["translation"])
    return texts


def reviewed_records(snapshot):
    """Return ({id: reasons}, {id: [opinion texts whose breaks were themselves reviewed]})."""
    reasons, opinions = collections.defaultdict(set), collections.defaultdict(list)
    break_only = collections.defaultdict(list)
    for path in sorted((PROJECT_ROOT / "config/editorial").rglob("*.json")):
        if MECHANICAL.match(path.name) or "special-disc" in path.parts:
            continue
        for record in set(RECORD_ID.findall(path.read_text(encoding="utf-8"))):
            reasons[record].add("receipt")
    for opinion in sorted(snapshot, key=lambda row: row["createdAt"]):
        if opinion["targetType"] != "dialogue" or not opinion["targetId"].startswith(("story/", "sd/")):
            continue
        reasons[opinion["targetId"]].add("online")
        if opinion["targetId"].startswith("sd/"):
            continue
        proposed, base = untagged(opinion.get("proposedTranslation")), untagged(opinion.get("currentTranslation"))
        # After the reflow an opinion inherits mechanical breaks unless it edits only the breaks.
        if "\n" in proposed and opinion["createdAt"] < REFLOW_DATE:
            opinions[opinion["targetId"]].append(proposed)
        elif opinion["createdAt"] >= REFLOW_DATE and logical(proposed) == logical(base) and proposed != base:
            # A break-only opinion posted after the reflow is the newest review of the breaks,
            # joining rows included; it outranks the earlier breaks.
            break_only[opinion["targetId"]].append(proposed)
    return reasons, opinions, break_only


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--online-snapshot", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--batch-id", default="story-breaks-20261113")
    parser.add_argument("--decisions", type=Path, help="also save every decision as JSON")
    args = parser.parse_args()

    japanese = disc_sources()[1]
    earlier = pre_reflow_texts()
    reasons, opinions, break_only = reviewed_records(json.loads(args.online_snapshot.read_text(encoding="utf-8"))["all"])
    links = keyword_link_ids()
    documents, rows = {}, []
    for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
        documents[path] = json.loads(path.read_text(encoding="utf-8"))
        for entry in documents[path]["entries"]:
            if "/dialogue/" not in entry["id"] or not entry.get("translation"):
                continue
            text = entry["translation"]
            rows.append(dict(
                id=entry["id"], zh=text, jp=japanese.get(entry["id"]), old=earlier.get(entry["id"]),
                scene=dialogue_scene(entry["id"]), links=entry["id"] in links,
                reviewed=sorted(reasons.get(entry["id"], ())),
                opinion=[t for t in opinions.get(entry["id"], ()) if logical(t) == logical(text)][-1:],
                break_only=[t for t in break_only.get(entry["id"], ()) if logical(t) == logical(text)][-1:]))
    # Special Disc: the stored breaks are the authored ones (its build used to re-break
    # them); reviewed entries keep theirs, drafts follow the Japanese rows.
    for path in SP_FILES:
        documents[path] = json.loads(path.read_text(encoding="utf-8"))
        for entry in documents[path]["entries"]:
            text, source = entry.get("translation"), entry.get("source_text") or ""
            if entry.get("kind", "dialogue") != "dialogue" or not text or source[:1] not in "「（『":
                continue
            status = ["status"] if entry.get("editorial_status") == "reviewed" else []
            rows.append(dict(id=entry["id"], zh=text, jp=source, old=text,
                             scene=dialogue_scene(entry["id"], edition="sp"), links=False,
                             reviewed=sorted({*status, *reasons.get(entry["id"], ())}), opinion=[],
                             main_id=entry.get("main_id")))
    def solve(batch):
        with tempfile.TemporaryDirectory() as scratch:
            source, target = Path(scratch) / "in.json", Path(scratch) / "out.json"
            source.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
            subprocess.run(["node", str(Path(__file__).with_name("story_breaks.mjs")), str(source), str(target)],
                           check=True, stdout=subprocess.DEVNULL)
            return json.loads(target.read_text(encoding="utf-8"))

    # Main game first: Special Disc records bound to a main record follow its breaks.
    decisions = solve([row for row in rows if "main_id" not in row])
    # Copies of one line (same Japanese, same wording, same box) share one set of breaks:
    # a reviewed copy decides, then a copy that keeps the Japanese row count.
    by_id = {row["id"]: row for row in rows}
    groups = collections.defaultdict(list)
    for record in decisions:
        row = by_id[record]
        groups[row["jp"], logical(row["zh"]), row["scene"], row["links"]].append(record)

    def rank(record):
        decision, row = decisions[record], by_id[record]
        tier = {"reviewed_breaks": 0, "reviewed_opinion": 0, "reviewed_old": 1}.get(
            decision["cat"], 2 if decision["text"].count("\n") == (row["jp"] or "").count("\n") else 3)
        return tier, -texts[decision["text"]], decision["text"]

    for members in groups.values():
        texts = collections.Counter(decisions[record]["text"] for record in members)
        if len(texts) > 1 and not any(decisions[record]["cat"] == "keep_structured" for record in members):
            best = decisions[min(members, key=rank)]["text"]
            for record in members:
                if decisions[record]["text"] != best:
                    decisions[record] = dict(cat="same_line_copy", text=best)
    for row in rows:
        if row.get("main_id") in decisions:
            row["twin"] = decisions[row["main_id"]]["text"]
    decisions.update(solve([row for row in rows if "main_id" in row]))
    if args.decisions:
        args.decisions.write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")

    current = {row["id"]: row["zh"] for row in rows}
    categories = collections.Counter(d["cat"] for d in decisions.values())
    changed = {i: d["text"] for i, d in decisions.items() if d["text"] != current[i]}
    for record, text in changed.items():
        if logical(text) != logical(current[record]):
            raise SystemExit(f"{record}: wording changed")
    print(json.dumps(dict(records=len(rows), changed=len(changed), categories=dict(sorted(categories.items()))),
                     ensure_ascii=False, indent=2) + ("" if args.write else "\n(dry run)"))
    if not args.write:
        return 0
    files = {}
    for path, document in documents.items():
        for entry in document["entries"]:
            if entry["id"] in changed:
                entry["translation"] = changed[entry["id"]]
        relative = str(path.relative_to(PROJECT_ROOT))
        committed = {entry["id"]: entry.get("translation") for entry in json.loads(subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=PROJECT_ROOT, capture_output=True, check=True).stdout)["entries"]}
        count = sum(committed.get(entry["id"]) != entry.get("translation") for entry in document["entries"])
        if count:
            data = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            path.write_text(data, encoding="utf-8")
            files[str(path.relative_to(PROJECT_ROOT))] = dict(records=count, sha256=hashlib.sha256(data.encode()).hexdigest())
    receipt = dict(batch_id=args.batch_id, tool="tools/text_layout/relayout_story_breaks.py",
                   pre_reflow_commit=PRE_REFLOW_COMMIT,
                   online_snapshot_sha256=hashlib.sha256(args.online_snapshot.read_bytes()).hexdigest(),
                   records=len(rows), changed=sum(f["records"] for f in files.values()), categories=dict(sorted(categories.items())), files=files)
    output = PROJECT_ROOT / "config/editorial" / f"{args.batch_id}.json"
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
