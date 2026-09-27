#!/usr/bin/env python3
"""Unify diverging translations of identical Japanese story lines.

The same Japanese dialogue recurs across route branches and repeated scenes.
Where its Chinese translations drifted apart, this tool groups every corpus
record by its source hash, classifies each group, and copies one winning
translation to the other members of the classes selected with ``--apply``.

Classes (decided per group, in this order):

* ``A`` decided: a member's current wording is recorded as a decision in an
  editorial batch (community, subtitle, 2026-09-07 applications) or pinned by
  a regression test; that wording wins.  ``A-conflict``: two or more variants
  are decided, so the difference is deliberate and the group is left alone.
* ``different-context``: the neighbouring lines differ, so this is the same
  sentence in another scene (a stock shout, a caption, a similar speech in a
  later episode); never unified.
* ``protagonist-differs``: spoken by ``$n`` in Setsuko's and Rand's own route
  stages, which are different people; never unified.
* ``D`` different speakers: the Japanese source is spoken by more than one
  character, so wording may differ on purpose; never applied automatically,
  and checked before ``A`` so a decision never crosses speakers.
* ``B`` short: every variant is at most 6 content characters.
* ``C`` near-identical: variants differ only slightly (similarity >= 0.85).
* ``E`` longer differences that need editorial judgment.

Winner within a group: confirmed/pinned member, else a ``reviewed`` member,
else the wording used most often, else the earliest stage file.  Only the
``translation`` field changes; line breaks come with the winning text and are
already in final layout because the whole corpus passes the layout gate.

    python3 tools/editorial_review/unify_same_source_dialogue.py --dry-run
    python3 tools/editorial_review/unify_same_source_dialogue.py --apply A,C \\
        --apply-when-decided B,E --batch-id same-source-unify-20260927

Every applied change is recorded under ``config/editorial``; the candidates
of classes that were not applied are written next to it under ``work/review``.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import difflib
import glob
import json
import random
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/text_layout"))

from rebalance_story_dialogue import source_dialogue_index, source_stage_ordinals  # noqa: E402
from srwz.chinese_layout import dialogue_layout_issues, load_layout_profiles  # noqa: E402

DIALOGUE_ROOT = PROJECT_ROOT / "corpus/zh/story-dialogue"
EDITORIAL_DIR = PROJECT_ROOT / "config/editorial"
PROFILES_PATH = PROJECT_ROOT / "config/text-layout/zh-layout-profiles.json"
TESTS_DIR = PROJECT_ROOT / "tests"
ENTRY_ID = re.compile(r"story/\d{3}/dialogue/[0-9.]+/\d{4}")
SHORT_LIMIT = 6
NEAR_SIMILARITY = 0.85


def core(text: str) -> str:
    """Wording only: drop punctuation, spaces and line breaks."""

    return re.sub(r"[^一-鿿A-Za-z0-9$]", "", text)


DECISION_FILES = (
    "community-*.json",
    "episode*-subtitle-confirmed-*.json",
    "*-application-*.json",
    "*-finalization-*.json",
    "*-decisions-*.json",
    "*-confirmation*.json",
    "site-decisions-*.json",
    "gingham-self-address-*.json",
    "mail-pun-review-*.json",
    "story-battle-polish-*.json",
    "polish-feedback-pilot-*.json",
    "zaft-terminology-*.json",
)
DECISION_KEYS = (
    "after",
    "final_translation",
    "updated_submission",
    "expected_translation",
    "final",
    "translation",
)


def _decisions_in(value, found: set[tuple[str, str]], current_id: str | None = None) -> None:
    if isinstance(value, dict):
        entry_id = current_id
        for key in ("id", "target_id", "entry_id", "stable_id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and ENTRY_ID.fullmatch(candidate):
                entry_id = candidate
                break
        for key in DECISION_KEYS:
            text = value.get(key)
            if entry_id and isinstance(text, str) and text:
                found.add((entry_id, core(text)))
        for child in value.values():
            _decisions_in(child, found, entry_id)
    elif isinstance(value, list):
        for child in value:
            _decisions_in(child, found, current_id)


def decided_pairs() -> frozenset[tuple[str, str]]:
    """(entry id, wording core) pairs recorded as decisions in editorial batches."""

    found: set[tuple[str, str]] = set()
    seen = set()
    for pattern in DECISION_FILES:
        for path in EDITORIAL_DIR.glob(pattern):
            if path in seen or "layout-rebalance" in path.name:
                continue
            seen.add(path)
            _decisions_in(json.loads(path.read_text(encoding="utf-8")), found)
    return frozenset(found)


def site_decisions() -> tuple[frozenset[tuple[str, str]], dict[str, int]]:
    """Review-site decisions: (target id, wording core) pairs and per-stage attention."""

    pairs: set[tuple[str, str]] = set()
    attention: dict[str, int] = {}
    for path in sorted(EDITORIAL_DIR.glob("site-decisions-*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for target in document.get("targets", []):
            for text in target.get("decided_texts", []):
                pairs.add((target["target_id"], core(text)))
        for stage, count in document.get("stage_suggestion_counts", {}).items():
            attention[stage] = max(attention.get(stage, 0), int(count))
    return frozenset(pairs), attention


IGNORED_STAGES = {185}  # tutorial text that the game never shows
ATTENTION_MIN = 5
CONTEXT_WINDOW = 3  # neighbouring lines compared on each side
CONTEXT_MIN_SHARED = 3  # of the 2 * CONTEXT_WINDOW neighbours

# Stage-name ordinals (resource number - 1) that belong to one protagonist's
# own route; ``$n`` there is Setsuko or Rand, not an interchangeable speaker.
SETSUKO_ORDINALS = set(range(0, 9)) | {33} | set(range(39, 57)) | {81, 102, 103}
RAND_ORDINALS = set(range(9, 18)) | {34} | set(range(57, 75)) | {82, 104, 105}


def protagonist_of(stage_ordinal: int | None) -> str:
    if stage_ordinal in SETSUKO_ORDINALS:
        return "setsuko"
    if stage_ordinal in RAND_ORDINALS:
        return "rand"
    return "shared"


class ContextIndex:
    """Neighbouring source hashes of every corpus record, in stage order."""

    def __init__(self, corpus: dict[Path, dict]) -> None:
        self.position: dict[str, tuple[Path, int]] = {}
        self.sequence: dict[Path, list[str]] = {}
        for path, document in corpus.items():
            rows = [entry["source_text_sha256"] for entry in document["entries"]]
            self.sequence[path] = rows
            for index, entry in enumerate(document["entries"]):
                self.position[entry["id"]] = (path, index)

    def shared_neighbours(self, a: str, b: str) -> int:
        pa, ka = self.position[a]
        pb, kb = self.position[b]
        sa, sb = self.sequence[pa], self.sequence[pb]
        before = set(sa[max(0, ka - CONTEXT_WINDOW) : ka]) & set(sb[max(0, kb - CONTEXT_WINDOW) : kb])
        after = set(sa[ka + 1 : ka + 1 + CONTEXT_WINDOW]) & set(sb[kb + 1 : kb + 1 + CONTEXT_WINDOW])
        return len(before) + len(after)

    def identical_situation(self, ids: list[str]) -> bool:
        return all(
            self.shared_neighbours(a, b) >= CONTEXT_MIN_SHARED
            for i, a in enumerate(ids)
            for b in ids[i + 1 :]
        )


def pinned_ids() -> frozenset[str]:
    """IDs whose wording a regression test asserts."""

    ids = set()
    for path in TESTS_DIR.glob("*.py"):
        ids.update(ENTRY_ID.findall(path.read_text(encoding="utf-8")))
    return frozenset(ids)


def stage_of(entry_id: str) -> int:
    return int(entry_id[6:9])


def load_corpus() -> dict[Path, dict]:
    return {
        path: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(DIALOGUE_ROOT.glob("stage-*.json"))
    }


def build_groups(
    corpus: dict[Path, dict],
    source_index: dict,
    decided: frozenset[tuple[str, str]],
    pinned: frozenset[str],
    stage_ordinals: dict[int, int] | None = None,
) -> list[dict]:
    context = ContextIndex(corpus)
    stage_ordinals = stage_ordinals or {}
    by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for path, document in corpus.items():
        for entry in document["entries"]:
            by_source[entry["source_text_sha256"]].append({**entry, "_path": path})
    groups = []
    for sha, members in by_source.items():
        variants: dict[str, list[dict]] = collections.defaultdict(list)
        for member in members:
            variants[core(member["translation"])].append(member)
        if len(variants) < 2:
            continue
        speakers = sorted(
            {
                source_index.get(m["id"], {}).get("speaker") or ""
                for m in members
            }
            - {""}
        )
        rows = []
        for key, rows_for_variant in variants.items():
            rows_for_variant.sort(key=lambda m: m["id"])
            rows.append({
                "core": key,
                "text": rows_for_variant[0]["translation"],
                "ids": [m["id"] for m in rows_for_variant],
                "count": len(rows_for_variant),
                "reviewed": sum(m["editorial_status"] == "reviewed" for m in rows_for_variant),
                "decided": sum(
                    m["id"] in pinned or (m["id"], core(m["translation"])) in decided
                    for m in rows_for_variant
                ),
                "texts": sorted({m["translation"] for m in rows_for_variant}),
            })
        cores = [row["core"] for row in rows]
        similarity = min(
            difflib.SequenceMatcher(None, a, b).ratio()
            for i, a in enumerate(cores)
            for b in cores[i + 1 :]
        )
        decided_variants = sum(1 for row in rows if row["decided"])
        member_ids = [m["id"] for m in members]
        protagonists = {
            protagonist_of(stage_ordinals.get(stage_of(i))) for i in member_ids
        } - {"shared"}
        if any(stage_of(m["id"]) in IGNORED_STAGES for m in members):
            klass = "ignored-185"
        elif not context.identical_situation(member_ids):
            # The same Japanese line in a different scene (stock shouts,
            # location captions, similar speeches in other episodes) is not
            # the same line; never unified.
            klass = "different-context"
        elif speakers == ["$n"] and len(protagonists) > 1:
            klass = "protagonist-differs"
        elif len(speakers) > 1:
            # Different characters can say the same Japanese in different
            # senses (「ワン！」 is a bark for a dog and "one!" for a person),
            # so even a recorded decision must not travel across speakers.
            klass = "D"
        elif decided_variants > 1:
            klass = "A-conflict"
        elif decided_variants == 1:
            klass = "A"
        elif max(len(c) for c in cores) <= SHORT_LIMIT:
            klass = "B"
        elif similarity >= NEAR_SIMILARITY:
            klass = "C"
        else:
            klass = "E"
        groups.append({
            "source_text_sha256": sha,
            "source_text": next(
                (source_index[m["id"]]["text"] for m in members if m["id"] in source_index),
                None,
            ),
            "speakers": speakers,
            "class": klass,
            "min_similarity": round(similarity, 3),
            "variants": rows,
        })
    groups.sort(key=lambda g: min(i for row in g["variants"] for i in row["ids"]))
    return groups


def choose_winner(group: dict, attention: dict[str, int]) -> tuple[dict, str]:
    """Pick the wording to keep.

    Order: a recorded decision, a ``reviewed`` member, the wording used most
    often, then the route that reviewers actually read (its stage collected
    at least ATTENTION_MIN site suggestions while the other side collected
    none), then the earliest stage file as a deterministic tie-break.
    """

    def side_attention(row: dict) -> int:
        return max(attention.get(i[6:9], 0) for i in row["ids"])

    rows = group["variants"]

    def reviewed_route(row: dict) -> bool:
        return side_attention(row) >= ATTENTION_MIN and all(
            side_attention(other) == 0 for other in rows if other is not row
        )

    def key(row: dict):
        return (
            row["decided"] > 0,
            row["reviewed"] > 0,
            row["count"],
            reviewed_route(row),
            -min(stage_of(i) for i in row["ids"]),
        )

    winner = max(rows, key=key)
    others = [row for row in rows if row is not winner]
    if winner["decided"]:
        reason = "decided"
    elif winner["reviewed"]:
        reason = "reviewed"
    elif winner["count"] > max(row["count"] for row in others):
        reason = "majority"
    elif reviewed_route(winner):
        reason = "reviewed_route"
    else:
        reason = "earliest_stage"
    return winner, reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report only")
    parser.add_argument("--sample", type=int, default=0, help="with --dry-run: print N sample changes")
    parser.add_argument(
        "--apply", default="", help="comma-separated classes to write back, e.g. A,C"
    )
    parser.add_argument(
        "--apply-when-decided",
        default="",
        help=(
            "classes written back only when the winner is a recorded decision "
            "or a reviewed member (reason decided/reviewed), e.g. B,E; the "
            "reviewed-route tie-break only orders candidates"
        ),
    )
    parser.add_argument(
        "--trust-reviewed-route",
        action="store_true",
        help=(
            "also treat reason reviewed_route as strong for --apply-when-decided "
            "classes: the side whose stage collected site suggestions wins"
        ),
    )
    parser.add_argument(
        "--batch-id",
        default=f"same-source-unify-{dt.date.today():%Y%m%d}",
    )
    args = parser.parse_args()
    apply_classes = {c.strip().upper() for c in args.apply.split(",") if c.strip()}
    judged_classes = {
        c.strip().upper() for c in args.apply_when_decided.split(",") if c.strip()
    }
    never = {"D", "A-CONFLICT", "IGNORED-185", "DIFFERENT-CONTEXT", "PROTAGONIST-DIFFERS"}
    if (apply_classes | judged_classes) & never:
        raise SystemExit(f"classes {sorted(never)} are never applied")
    strong_reasons = {"decided", "reviewed"}
    if args.trust_reviewed_route:
        strong_reasons.add("reviewed_route")

    source_index = source_dialogue_index()
    site_pairs, attention = site_decisions()
    decided = decided_pairs() | site_pairs
    pinned = pinned_ids()
    corpus = load_corpus()
    profile = load_layout_profiles(PROFILES_PATH)["story_dialogue"]
    stage_ordinals = {
        stage: meta["stage_ordinal"]
        for stage, meta in source_stage_ordinals(source_index).items()
    }
    groups = build_groups(corpus, source_index, decided, pinned, stage_ordinals)

    by_class = collections.Counter(g["class"] for g in groups)
    members_by_class = collections.Counter()
    changes = []
    candidates = []
    touched_paths = set()
    entry_index = {
        entry["id"]: (path, entry)
        for path, document in corpus.items()
        for entry in document["entries"]
    }
    for group in groups:
        winner, reason = choose_winner(group, attention)
        losers = [row for row in group["variants"] if row is not winner]
        members_by_class[group["class"]] += sum(row["count"] for row in losers)
        record = {
            "class": group["class"],
            "source_text_sha256": group["source_text_sha256"],
            "source_text": group["source_text"],
            "speakers": group["speakers"],
            "min_similarity": group["min_similarity"],
            "winner": winner["text"],
            "winner_ids": winner["ids"],
            "reason": reason,
            "losers": [{"text": row["text"], "ids": row["ids"]} for row in losers],
        }
        applicable = group["class"] in apply_classes or (
            group["class"] in judged_classes and reason in strong_reasons
        )
        if not applicable:
            candidates.append(record)
            continue
        links = source_index.get(winner["ids"][0], {}).get("keyword_links", False)
        issues = dialogue_layout_issues(
            winner["text"], profile=profile, stage_keyword_links=links
        )
        if issues:
            raise SystemExit(f"{winner['ids'][0]} winner is not in final layout: {issues}")
        for row in losers:
            for entry_id in row["ids"]:
                path, entry = entry_index[entry_id]
                if entry["translation"] == winner["text"]:
                    continue
                changes.append({
                    "id": entry_id,
                    "file": str(path.relative_to(PROJECT_ROOT)),
                    "class": group["class"],
                    "reason": reason,
                    "winner_id": winner["ids"][0],
                    "before": entry["translation"],
                    "after": winner["text"],
                    "source_text_sha256": entry["source_text_sha256"],
                })
                entry["translation"] = winner["text"]
                touched_paths.add(path)

    print(f"groups: {len(groups)} by class {dict(sorted(by_class.items()))}")
    print(f"members that differ from the winner: {dict(sorted(members_by_class.items()))}")
    print(f"applied classes {sorted(apply_classes)}: {len(changes)} records in {len(touched_paths)} files")
    print(
        "  by class/reason: "
        + json.dumps(
            dict(collections.Counter(f"{c['class']}:{c['reason']}" for c in changes)),
            ensure_ascii=False,
        )
    )
    if args.dry_run or not (apply_classes or judged_classes):
        if args.dry_run and args.sample:
            random.seed(1)
            for change in random.sample(changes, min(args.sample, len(changes))):
                print(
                    f"- {change['id']} [{change['class']}/{change['reason']}] ← {change['winner_id']}\n"
                    f"    前: {change['before'].replace(chr(10), '/')}\n"
                    f"    后: {change['after'].replace(chr(10), '/')}"
                )
        return 0

    for path in sorted(touched_paths):
        path.write_text(
            json.dumps(corpus[path], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    batch = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reason": (
            "同一日文原句在不同路线／场景的译文措辞不一致；按 决定稿 > reviewed > "
            "出现次数 > 最早关卡 的顺序选出统一措辞，复制给同源的其他记录。"
        ),
        "rules": {
            "applied_classes": sorted(apply_classes),
            "applied_when_decided": sorted(judged_classes),
            "trust_reviewed_route": bool(args.trust_reviewed_route),
            "ignored_stages": sorted(IGNORED_STAGES),
            "attention_min": ATTENTION_MIN,
            "short_limit": SHORT_LIMIT,
            "near_similarity": NEAR_SIMILARITY,
            "winner_order": ["decided", "reviewed", "majority", "earliest_stage"],
        },
        "counts": {
            "groups_by_class": dict(sorted(by_class.items())),
            "changed": len(changes),
            "changed_by_class": dict(collections.Counter(c["class"] for c in changes)),
            "changed_by_reason": dict(collections.Counter(c["reason"] for c in changes)),
            "files_touched": len(touched_paths),
            "candidates_not_applied": len(candidates),
        },
        "changes": changes,
    }
    output = EDITORIAL_DIR / f"{args.batch_id}.json"
    output.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate_dir = PROJECT_ROOT / "work/review" / args.batch_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = candidate_dir / "candidates.json"
    candidate_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote {output.relative_to(PROJECT_ROOT)} and {candidate_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
