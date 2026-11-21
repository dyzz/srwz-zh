#!/usr/bin/env python3
"""Write the user's 2026-11-20 weapon-name decisions into the corpus.

Decisions (answered in chat after the weapon-name review of 2026-11-20):
- ブレストファイヤー (Mazinger Z) → 胸甲火焰 and ブレストバーン (Great Mazinger) → 胸甲爆炎,
  the two names the SRW DD Chinese wiki uses; both had read 胸部火焰 since 2026-09-04, so the
  Final Dynamic Special called out 胸部火焰 twice.
- シグマブレスト → Σ射线 on both sides: the story and battle shouts said Σ冲击 while the menu
  weapon シグマブレスト無双剣 already reads Σ射线无双剑.

Every rewrite is bound to the record's own Japanese source (a line naming ブレストファイヤー
only takes 胸甲火焰, and so on); nothing else in a line changes and stored line breaks stay.
Gates: the base text still holds the old rendering, the story / battle layout gates pass,
and a fresh online-suggestion snapshot is recorded.  Dry run unless --apply.

    python3 tools/editorial_review/apply_breast_sigma_names_20261120.py
    python3 tools/editorial_review/apply_breast_sigma_names_20261120.py --apply
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/text_layout"))
sys.path.insert(0, str(ROOT / "tools/editorial_review"))

import apply_story_polish_20261110 as base  # noqa: E402  (fetch_online, refresh_active_locks, sha, dump)
from apply_term_leftovers_20261115 import serialise  # noqa: E402

REVIEW = ROOT / "work/review/breast-sigma-names-20261120"
RECEIPT = ROOT / "config/editorial/breast-sigma-names-20261120.json"
JP_BY_SHA = ROOT / "work/review/caption-tilde-20261113/jp-by-sha.json"
LIBRARY_OVERRIDES = ROOT / "config/library/v0.2-editorial-overrides.json"
GLOSSARY = ROOT / "corpus/glossary/weapons-v1.json"

# group, Japanese pattern, user's words, old rendering, new rendering
RULES = [
    ("breast-fire", re.compile(r"ブレストファイ[ヤア]ー"), "胸甲火焰（超级机器人大战DD 中文 wiki 写法）", "胸部火焰", "胸甲火焰"),
    ("breast-burn", re.compile(r"ブレストバーン"), "胸甲爆炎（超级机器人大战DD 中文 wiki 写法）", "胸部火焰", "胸甲爆炎"),
    # the stretched shout シグマァァァ・ブレェェェストォッ counts; the menu weapon シグマブレスト無双剣 already reads Σ射线无双剑
    ("sigma-breast", re.compile(r"シグマ[ァー]*・?ブレ[ェー]*スト"), "两边统一成“Σ射线”", "Σ冲击", "Σ射线"),
]
GLOSSARY_TERMS = {"weapon/0007": "breast-fire", "weapon/0020": "breast-burn", "weapon/sigma-breast": "sigma-breast"}

# records outside the sha-indexed corpus: (file, id) — matched against their own source_text
EXPLICIT = [("corpus/zh/special-disc/story-dialogue.json", "sd/story/014/dialogue/02.02/0011")]


def load(rel: str):
    raw = (ROOT / rel).read_bytes()
    return raw, json.loads(raw)


def edit_glossary_text(raw: bytes, edited: dict) -> bytes:
    """The glossary mixes inline and expanded lists, so edit the three term blocks as text
    and require the result to parse to exactly the edited document."""
    text = raw.decode("utf-8")
    terms = {t["id"]: t for t in edited["terms"]}
    for identity in GLOSSARY_TERMS:
        term = terms[identity]
        start = text.index(f'"id": "{identity}"')
        end = text.index("\n    }", start)
        block = text[start:end]
        block = re.sub(r'"translation": "[^"]*"', lambda _: f'"translation": {json.dumps(term["translation"], ensure_ascii=False)}', block, count=1)
        block = re.sub(r'"notes": "(?:[^"\\]|\\.)*"', lambda _: f'"notes": {json.dumps(term["notes"], ensure_ascii=False)}', block, count=1)
        listing = re.search(r'"deprecated_translations": \[(.*?)\]', block, flags=re.S)
        indent = re.search(r'\n( *)"translation"', block).group(1)
        items = ",\n".join(f'{indent}  {json.dumps(v, ensure_ascii=False)}' for v in term["deprecated_translations"])
        replacement = f'"deprecated_translations": [\n{items}\n{indent}]'
        if listing:
            block = block[:listing.start()] + replacement + block[listing.end():]
        else:
            raise SystemExit(f"{identity}: no deprecated_translations list to extend")
        text = text[:start] + block + text[end:]
    if json.loads(text) != edited:
        raise SystemExit("glossary text edit does not reproduce the edited document; nothing written")
    return text.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--online-snapshot", type=Path)
    args = parser.parse_args()
    if args.apply and RECEIPT.exists():
        raise SystemExit(f"already applied: {RECEIPT.relative_to(ROOT)}")
    REVIEW.mkdir(parents=True, exist_ok=True)

    by_sha = json.loads(JP_BY_SHA.read_text(encoding="utf-8"))["by_sha"]
    rule = {g: (pattern, words, old, new) for g, pattern, words, old, new in RULES}
    docs, raws, planned, errors = {}, {}, [], []

    def consider(rel, entry, japanese):
        flat = re.sub(r"\n　?", "", japanese)
        groups = [g for g, (pattern, *_rest) in rule.items() if pattern.search(flat)]
        before = entry.get("translation") or ""
        olds = {rule[g][2] for g in groups}
        if len(groups) > 1 and len(olds) < len(groups):
            if any(rule[g][2] in before for g in groups):
                errors.append(f"{entry['id']}: names more than one renamed weapon; decide by hand")
            return
        for group in groups:
            _, _, old, new = rule[group]
            if old in before:
                after = before.replace(old, new)
                planned.append(dict(id=entry["id"], file=rel, group=group, ja=japanese, before=before, after=after, _entry=entry))
                before = after

    for path in sorted(glob.glob(str(ROOT / "corpus/zh/**/*.json"), recursive=True)):
        rel = os.path.relpath(path, ROOT)
        try:
            raw, document = load(rel)
        except ValueError:
            continue
        if not (isinstance(document, dict) and isinstance(document.get("entries"), list)):
            continue
        docs[rel], raws[rel] = document, raw
        for entry in document["entries"]:
            if isinstance(entry, dict) and "id" in entry:
                consider(rel, entry, str(by_sha.get(entry.get("source_text_sha256"), "")))
    seen = {(row["file"], row["id"]) for row in planned}
    for rel, identity in EXPLICIT:
        if (rel, identity) in seen:
            continue
        entry = next(e for e in docs[rel]["entries"] if e.get("id") == identity)
        count = len(planned)
        consider(rel, entry, entry.get("source_text") or "")
        if len(planned) == count:
            raise SystemExit(f"{rel} {identity}: explicit record no longer holds the old rendering")

    # anything still holding an old rendering after the plan is reported, not silently left
    planned_ids = {(r["file"], r["id"]) for r in planned}
    leftovers = []
    for rel, document in docs.items():
        for entry in document["entries"]:
            if not isinstance(entry, dict):
                continue
            text = entry.get("translation") or ""
            if ("胸部火焰" in text or "Σ冲击" in text) and (rel, entry.get("id")) not in planned_ids:
                leftovers.append(dict(file=rel, id=entry.get("id"), translation=text))

    # ---- gates
    from rebalance_story_dialogue import PROFILES_PATH, keyword_link_ids
    from srwz.build_layout import stored_geometry_issues
    from srwz.chinese_layout import battle_subtitle_layout_issues, dialogue_layout_issues, load_layout_profiles
    profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]
    links = keyword_link_ids()
    story = [r for r in planned if r["id"].startswith("story/") and "/dialogue/" in r["id"]]
    battle = [r for r in planned if r["id"].startswith("battle:")]
    geometry = {}
    if story:
        geometry.update(stored_geometry_issues([(r["id"], r["after"], r["id"] in links) for r in story], "story"))
    if battle:
        geometry.update(stored_geometry_issues([(r["id"], r["after"], False) for r in battle], "battle"))
    for r in story:
        issues = list(dialogue_layout_issues(r["after"], profile=profile, stage_keyword_links=r["id"] in links, check_width=False))
        issues += list(geometry.get(r["id"], ()))
        errors += [f"{r['id']}: {m}" for m in issues]
    for r in battle:
        errors += [f"{r['id']}: {m}" for m in list(battle_subtitle_layout_issues(r["after"])) + list(geometry.get(r["id"], ()))]
    for r in planned:
        if r["after"].count("\n") != r["before"].count("\n"):
            errors.append(f"{r['id']}: row count changed")

    if args.online_snapshot:
        online = json.loads(args.online_snapshot.read_text(encoding="utf-8"))
    else:
        online = base.fetch_online()
        (REVIEW / "online-snapshot-writeback.json").write_text(json.dumps(online, ensure_ascii=False), encoding="utf-8")
    opinions = defaultdict(list)
    for row in online["all"]:
        opinions[row["targetId"]].append(dict(id=row["id"], by=row.get("displayNameSnapshot"), resolution=row.get("resolution"),
                                              proposed=row.get("proposedTranslation")))
    for r in planned:
        r["online_opinions"] = opinions.get(r["id"], [])
        r["editorial_status"] = r["_entry"].get("editorial_status", "")

    # ---- library override layer: same rewrite on the override of a changed library record
    raw_overrides, overrides = load(str(LIBRARY_OVERRIDES.relative_to(ROOT)))
    changed_library = defaultdict(list)
    for r in planned:
        if r["id"].startswith("library-text/"):
            changed_library[r["id"]].append(r["group"])
    override_edits = []

    def visit(node):
        if isinstance(node, dict):
            identity = node.get("id") or node.get("entry_id")
            if identity in changed_library and isinstance(node.get("translation"), str):
                new = node["translation"]
                for group in changed_library[identity]:
                    new = new.replace(rule[group][2], rule[group][3])
                if new != node["translation"]:
                    override_edits.append(dict(id=identity, before=node["translation"], after=new))
                    node["translation"] = new
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(overrides)

    # ---- glossary: current form, the replaced form kept as deprecated, the decision appended to notes
    raw_glossary, glossary = load(str(GLOSSARY.relative_to(ROOT)))
    glossary_edits = []
    for term in glossary["terms"]:
        group = GLOSSARY_TERMS.get(term["id"])
        if not group:
            continue
        _, words, old, new = rule[group]
        if term["translation"] != old:
            errors.append(f"{term['id']}: glossary reads {term['translation']!r}, expected {old!r}")
            continue
        before = dict(translation=term["translation"], deprecated=list(term.get("deprecated_translations", [])))
        term["translation"] = new
        term["deprecated_translations"] = [old] + [v for v in term.get("deprecated_translations", []) if v not in (old, new)]
        term["notes"] = (term.get("notes", "") + f" 2026-11-20 用户在对话中改定为“{new}”：{words}。").strip()
        glossary_edits.append(dict(id=term["id"], before=before, after=new))

    summary = dict(write=len(planned), files=len({r["file"] for r in planned}), by_group=dict(Counter(r["group"] for r in planned)),
                   reviewed=sum(r["editorial_status"] == "reviewed" for r in planned),
                   with_online_opinions=sum(bool(r["online_opinions"]) for r in planned),
                   library_override_edits=len(override_edits), glossary_edits=len(glossary_edits),
                   leftovers=len(leftovers),
                   online_snapshot_at=online["fetched_at"], online_snapshot_total=online["total"], gate_errors=len(errors))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for r in planned:
        print(f"  {r['group']:13} {r['id']:45} {r['before'][:40]!r} -> {r['after'][:40]!r}")
    for row in leftovers:
        print("LEFTOVER", row["file"], row["id"], row["translation"][:60])
    for message in errors:
        print("GATE", message)
    public = [{k: v for k, v in r.items() if k != "_entry"} for r in planned]
    if not args.apply:
        (REVIEW / "writeback-dry-run.json").write_text(json.dumps(dict(summary=summary, write=public, library_overrides=override_edits,
                                                                       glossary=glossary_edits, leftovers=leftovers, errors=errors),
                                                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 1 if errors else 0
    if errors:
        raise SystemExit("gate errors; nothing written")

    by_file = defaultdict(list)
    for r in planned:
        r["_entry"]["translation"] = r["after"]
        by_file[r["file"]].append(r["id"])
    outputs = {}
    for rel in sorted(by_file):
        data = serialise(docs[rel], raws[rel])
        if not data:
            raise SystemExit(f"{rel}: cannot reproduce the file's JSON style; nothing written")
        outputs[rel] = data
    if override_edits:
        rel = str(LIBRARY_OVERRIDES.relative_to(ROOT))
        data = serialise(overrides, raw_overrides)
        if not data:
            raise SystemExit(f"{rel}: cannot reproduce the file's JSON style; nothing written")
        outputs[rel] = data
    if glossary_edits:
        outputs[str(GLOSSARY.relative_to(ROOT))] = edit_glossary_text(raw_glossary, glossary)
    files = []
    for rel, data in outputs.items():
        target = ROOT / rel
        before = target.read_bytes()
        temporary = target.with_suffix(".writeback-tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        files.append(dict(path=rel, entries=len(by_file.get(rel, [])), before_sha256=base.sha(before), after_sha256=base.sha(data)))
    locks = base.refresh_active_locks(set(outputs))
    receipt = dict(
        schema_version=1, review_id=RECEIPT.stem, translation_writeback=True,
        purpose="2026-11-20 武器名复核后的两项决定：ブレストファイヤー／ブレストバーン 分别改为“胸甲火焰”“胸甲爆炎”（此前同为“胸部火焰”）；シグマブレスト 统一为“Σ射线”，与菜单“Σ射线无双剑”一致。每条改写绑定该记录自己的日文原文，只替换名称，不动其他措辞和换行。",
        authorization={"breast": "用户 2026-11-20 在对话中贴出 DD 中文 wiki 的“胸甲火焰”“胸甲爆炎”两页", "sigma-breast": "两边统一成“Σ射线”"},
        decisions=[dict(id="breast-fire", source_text="ブレストファイヤー", form="胸甲火焰", variants=["胸部火焰", "胸甲烈焰", "胸甲火焰"]),
                   dict(id="breast-burn", source_text="ブレストバーン", form="胸甲爆炎", variants=["胸部火焰", "胸甲爆燃", "胸甲爆炎"]),
                   dict(id="sigma-breast", source_text="シグマブレスト", form="Σ射线", variants=["Σ冲击", "Σ射线"])],
        feedback_snapshot_at=online["fetched_at"], feedback_snapshot_total=online["total"],
        summary=summary, application=dict(files=files, active_lock_updates=locks, site_writeback=False),
        entries=public, library_overrides=override_edits, glossary=glossary_edits, leftovers=leftovers,
    )
    RECEIPT.write_text(base.dump(receipt), encoding="utf-8")
    print(f"wrote {len(planned)} records in {len(files)} files; receipt {RECEIPT.relative_to(ROOT)}; lock files {[l['file'] for l in locks]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
