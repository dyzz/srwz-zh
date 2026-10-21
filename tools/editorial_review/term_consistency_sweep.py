#!/usr/bin/env python3
"""Sweep the corpus for proper nouns rendered inconsistently in Chinese.

Two passes over story dialogue (and battle lines when a Japanese inventory
is given):

1. Glossary pass.  Every global glossary term whose Japanese surface occurs
   in a line (``srwz.glossary.relevant_glossary_terms`` boundary rules) must
   appear in the Chinese text in its decided form; a deprecated form must
   not.  Violations are grouped by term with examples.
2. Discovery pass.  Katakana runs that are not covered by any glossary
   surface are treated as candidate proper nouns.  For each one the Chinese
   substrings that co-occur with it far more often than elsewhere are its
   likely renderings; a term with two or more competing renderings is
   reported (this is how 天堂基地 / 赫文斯基地 shows up).

    python3 tools/editorial_review/term_consistency_sweep.py --out work/review/term-sweep.json
    python3 tools/editorial_review/term_consistency_sweep.py --battle-jp <jsonl with text+sha> --out ...
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))

from rebalance_story_dialogue import source_dialogue_index  # noqa: E402
from srwz.glossary import (  # noqa: E402
    deprecated_translation_conflicts,
    load_global_glossary,
    relevant_glossary_terms,
)

DIALOGUE_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
BATTLE_CORPUS = PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json"
GLOSSARY_DIR = PROJECT_ROOT / "corpus/glossary"
KATAKANA_RUN = re.compile(r"[ァ-ヺー・]{3,}")
CJK = re.compile(r"[一-鿿]")
CONTROL = re.compile(r"<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>")


def logical(text: str) -> str:
    """Visible Chinese without authoring wraps, indents, or width controls."""

    return CONTROL.sub("", text).replace("\\n", "\n").replace("\n　", "").replace("\n", "")


SP_ROOT = PROJECT_ROOT / "corpus/zh/special-disc"


def load_sp_lines() -> list[dict]:
    """Special Disc records: every entry that stores its own Japanese source."""

    lines = []
    for path in sorted(SP_ROOT.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = document.get("entries") if isinstance(document, dict) else document
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            jp = entry.get("source_text") or entry.get("source")
            zh = entry.get("translation") or entry.get("submitted_translation")
            if isinstance(jp, str) and isinstance(zh, str) and jp and zh:
                lines.append({"id": f"sp:{path.stem}:{entry.get('id', len(lines))}", "kind": f"sp-{path.stem}", "speaker": str(entry.get("speaker") or ""), "jp": jp, "zh": zh})
    return lines


def load_lines(battle_jp: Path | None, *, sp_only: bool = False) -> list[dict]:
    if sp_only:
        return load_sp_lines()
    index = source_dialogue_index()
    lines = []
    for path in sorted(DIALOGUE_ROOT.glob("stage-*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            meta = index.get(entry["id"])
            if not meta:
                continue
            lines.append({"id": entry["id"], "kind": "story", "speaker": meta["speaker"], "jp": meta["text"], "zh": entry["translation"]})
    if battle_jp:
        by_sha = {}
        for raw in battle_jp.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            text = row.get("text") or row.get("source_text") or row.get("source")
            if not isinstance(text, str):
                continue
            by_sha[row.get("sha256") or row.get("source_text_sha256") or hashlib.sha256(text.encode("utf-8")).hexdigest()] = text
        for entry in json.loads(BATTLE_CORPUS.read_text(encoding="utf-8"))["entries"]:
            jp = by_sha.get(entry["source_text_sha256"])
            if jp:
                lines.append({"id": entry["id"], "kind": "battle", "speaker": "", "jp": jp, "zh": entry["translation"]})
    return lines


def glossary_pass(lines: list[dict], glossary: list[dict]) -> dict:
    surfaces = sorted({str(s) for t in glossary if t.get("registry_match", "automatic") != "explicit_only" for s in t["source_terms"]}, key=len, reverse=True)
    finder = re.compile("|".join(re.escape(s) for s in surfaces))
    by_surface: dict[str, list[dict]] = collections.defaultdict(list)
    for term in glossary:
        for s in term["source_terms"]:
            by_surface[str(s)].append(term)
    per_term: dict[str, dict] = {}
    for line in lines:
        hits = set(finder.findall(line["jp"]))
        if not hits:
            continue
        candidates = [t for s in hits for t in by_surface[s]]
        zh = logical(line["zh"])
        for match in relevant_glossary_terms(line["jp"], candidates):
            term_id = match["id"]
            rec = per_term.setdefault(term_id, {"id": term_id, "translation": match["translation"], "status": match["status"], "enforce": match["declared_enforce"], "lines": 0, "missing": [], "deprecated": []})
            rec["lines"] += 1
            if match["translation"] not in zh:
                rec["missing"].append({"id": line["id"], "kind": line["kind"], "jp": line["jp"], "zh": line["zh"]})
            for conflict in deprecated_translation_conflicts(zh, [match]):
                rec["deprecated"].append({"id": line["id"], "kind": line["kind"], "matched": conflict["matched"], "zh": line["zh"]})
    rows = [r for r in per_term.values() if r["missing"] or r["deprecated"]]
    rows.sort(key=lambda r: (-len(r["deprecated"]), -len(r["missing"]) / max(r["lines"], 1)))
    return {"terms_checked": len(per_term), "terms_with_findings": len(rows), "rows": rows}


def discovery_pass(lines: list[dict], glossary: list[dict], *, min_lines: int = 3) -> list[dict]:
    covered = {str(s) for t in glossary for s in t["source_terms"]}
    # Route twins repeat whole lines; count each distinct (Japanese, Chinese) pair once
    # so a repeated sentence cannot pose as a rendering of its own katakana word.
    seen_pairs: set[tuple[str, str]] = set()
    unique_lines = []
    for line in lines:
        key = (line["jp"], logical(line["zh"]))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        unique_lines.append(line)
    lines = unique_lines
    occurrences: dict[str, list[int]] = collections.defaultdict(list)
    for index, line in enumerate(lines):
        for run in set(KATAKANA_RUN.findall(line["jp"])):
            if any(run in s or s in run for s in covered if len(s) >= 3):
                continue
            occurrences[run].append(index)
    # document frequency of every Chinese substring (2..7 chars) over the corpus
    def substrings(zh: str) -> set[str]:
        text = "".join(ch for ch in logical(zh) if CJK.match(ch) or ch == "·")
        return {text[i : i + n] for n in range(2, 8) for i in range(len(text) - n + 1)}

    subs_by_line = [substrings(line["zh"]) for line in lines]
    global_df: collections.Counter = collections.Counter()
    for subs in subs_by_line:
        global_df.update(subs)
    findings = []
    for run, idxs in occurrences.items():
        if len(idxs) < min_lines:
            continue
        local_df: collections.Counter = collections.Counter()
        for i in idxs:
            local_df.update(subs_by_line[i])
        n = len(idxs)
        candidates = []
        jp_by_sub: dict[str, set[str]] = collections.defaultdict(set)
        for i in idxs:
            for sub in subs_by_line[i]:
                jp_by_sub[sub].add(lines[i]["jp"])
        for sub, c in local_df.items():
            if c < 2 or c / n < 0.2 or len(jp_by_sub[sub]) < 2:
                continue
            precision = c / global_df[sub]
            if precision < 0.6:
                continue
            candidates.append((sub, c, precision))
        # keep maximal strings: drop a candidate contained in a longer one with similar coverage
        candidates.sort(key=lambda x: (-len(x[0]), -x[1]))
        kept = []
        for sub, c, p in candidates:
            if any(sub in k[0] and k[1] >= c * 0.8 for k in kept):
                continue
            kept.append((sub, c, p))
        renderings = [k for k in kept if not any(k[0] != o[0] and k[0] in o[0] for o in kept)]
        if len(renderings) < 2:
            continue
        findings.append({
            "term": run,
            "lines": n,
            "renderings": [{"zh": s, "lines": c, "precision": round(p, 2)} for s, c, p in sorted(renderings, key=lambda x: -x[1])],
            "examples": [{"id": lines[i]["id"], "zh": lines[i]["zh"]} for i in idxs[:4]],
        })
    findings.sort(key=lambda f: -f["lines"])
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--battle-jp", type=Path, default=None, help="JSONL with the Japanese text (and sha256) of battle lines")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-lines", type=int, default=3)
    parser.add_argument("--sp", action="store_true", help="sweep corpus/zh/special-disc instead of the main game")
    args = parser.parse_args()
    glossary = load_global_glossary(GLOSSARY_DIR)
    lines = load_lines(args.battle_jp, sp_only=args.sp)
    report = {
        "lines": collections.Counter(l["kind"] for l in lines),
        "glossary": glossary_pass(lines, glossary),
        "discovery": discovery_pass(lines, glossary, min_lines=args.min_lines),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    g = report["glossary"]
    print(f"lines {dict(report['lines'])}; glossary terms checked {g['terms_checked']}, with findings {g['terms_with_findings']}; discovery candidates {len(report['discovery'])}")
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
