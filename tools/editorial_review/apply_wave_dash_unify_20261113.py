#!/usr/bin/env python3
"""Write the Japanese wave dash 〜 (U+301C, code 8160) where the source has one.

Follow-up to ``apply_caption_tilde_20261113.py`` (title captions).  A
translation is rewritten only when its own Japanese source contains the wave
dash; the rewrite replaces ～ (889A) and ASCII ~ (9FA9) with 〜 and changes
nothing else.  Evidence used per kind of record:

* entry records: the record's ``source_text`` / ``source`` field, or the
  Japanese text looked up by ``source_text_sha256`` in the cache built by
  ``japanese_sources.py``;
* Q&A / tutorial pages (``pages[].records[]``): zh and Japanese rows of a page
  are not aligned record by record, so the page's Japanese rows together are
  the evidence;
* ``menu/remaining-ui.json`` offset maps: the stock Japanese bytes at that
  offset in ``work/disc`` (SLPS file offset, decoded COMPDATA offset).

Translations whose Japanese source has no wave dash (the translator's own mark
for ー or a small kana) are rewritten only with ``--all``; the user decided on
2026-11-13 to unify them too.  Left alone on purpose: review-history copies,
notes, and every wording choice.

    python3 tools/editorial_review/apply_wave_dash_unify_20261113.py --dry-run
    python3 tools/editorial_review/apply_wave_dash_unify_20261113.py --ledger PATH
    python3 tools/editorial_review/apply_wave_dash_unify_20261113.py --all
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
CORPUS = PROJECT_ROOT / "corpus/zh"
JAPANESE_CACHE = PROJECT_ROOT / "work/review/caption-tilde-20261113/jp-by-sha.json"

WAVE = "〜"
SMALL = ("～", "~")
# Shift-JIS 8160 decodes to 〜 (JIS) or ～ (CP932); both spell the same byte pair.
JAPANESE_WAVE = re.compile("[〜～]")

MAP_FILE = "menu/remaining-ui.json"
MAP_SOURCES = {
    "compdata_context_help_by_offset": "compdata",
    "slps_context_ui_by_offset": "slps",
}


def unify(text: str) -> str:
    for mark in SMALL:
        text = text.replace(mark, WAVE)
    return text


def strings(node, pointer=""):
    """Every string in document order with its JSON pointer."""
    if isinstance(node, dict):
        for name, value in node.items():
            yield from strings(value, f"{pointer}/{name}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from strings(value, f"{pointer}/{index}")
    elif isinstance(node, str):
        yield pointer, node


def resolve(document, pointer):
    node = document
    for part in pointer.split("/")[1:]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def stock_text(kind: str, offset: int, cache: dict) -> str:
    if kind not in cache:
        if kind == "slps":
            cache[kind] = (PROJECT_ROOT / "work/disc/SLPS_258.87").read_bytes()
        else:
            from srwz.codec import decode_production

            cache[kind] = decode_production(
                (PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN").read_bytes()
            ).output
    data = cache[kind]
    return data[offset:data.index(b"\0", offset)].decode("shift_jis")


def evidence(document, relative, pointer, japanese, stock, unify_all=False):
    """Return (kind, Japanese text) proving a wave dash, or None."""
    parts = pointer.split("/")
    if relative == MAP_FILE and len(parts) == 3 and parts[1] in MAP_SOURCES:
        text = stock_text(MAP_SOURCES[parts[1]], int(parts[2], 16), stock)
        return ("stock bytes", text) if JAPANESE_WAVE.search(text) else None
    if parts[-1] != "translation":
        return None
    record = resolve(document, "/".join(parts[:-1]))
    if re.fullmatch(r"/pages/\d+/records/\d+/translation", pointer):
        page = resolve(document, "/".join(parts[:3]))
        rows = [row.get("source", "") for row in page["records"]]
        hits = [row for row in rows if JAPANESE_WAVE.search(row)]
        return ("page rows", "\n".join(hits)) if hits else None
    if not re.fullmatch(r"/entries/\d+/translation", pointer):
        return None  # review-history copies and other nested fields
    source = record.get("source_text") or record.get("source") or japanese.get(
        record.get("source_text_sha256", ""), ""
    )
    if JAPANESE_WAVE.search(source):
        return ("record source", source)
    # 2026-11-13 user decision: one wave glyph everywhere, including marks the
    # translator added for ー or a small kana.
    return ("user decision 2026-11-13", source) if unify_all else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ledger", type=Path, help="write every decision as JSON")
    parser.add_argument(
        "--all", action="store_true",
        help="also rewrite entry translations whose Japanese source has no wave dash",
    )
    args = parser.parse_args()

    if not JAPANESE_CACHE.exists():
        raise SystemExit(
            f"missing {JAPANESE_CACHE}; run tools/editorial_review/japanese_sources.py --out {JAPANESE_CACHE}"
        )
    japanese = json.loads(JAPANESE_CACHE.read_text(encoding="utf-8"))["by_sha"]
    stock: dict = {}

    ledger = []
    changed = collections.Counter()
    for path_str in sorted(glob.glob(str(CORPUS / "**/*.json"), recursive=True)):
        path = Path(path_str)
        relative = str(path.relative_to(CORPUS))
        raw = path.read_text(encoding="utf-8")
        if not any(mark in raw for mark in SMALL):
            continue
        document = json.loads(raw)

        # Occurrence n of a (key, value) pair in the text is occurrence n in
        # document order, so one copy can be rewritten without its twins.
        seen = collections.Counter()
        selected = collections.defaultdict(set)
        totals = collections.Counter()
        for pointer, value in strings(document):
            key = pointer.rsplit("/", 1)[1]
            index = seen[(key, value)]
            seen[(key, value)] += 1
            totals[(key, value)] += 1
            is_map = relative == MAP_FILE and pointer.split("/")[1] in MAP_SOURCES
            if not (key == "translation" or is_map) or unify(value) == value:
                continue
            proof = evidence(document, relative, pointer, japanese, stock, args.all)
            parent = resolve(document, pointer.rsplit("/", 1)[0])
            ledger.append({
                "file": relative,
                "pointer": pointer,
                "id": parent.get("id", "") if key == "translation" else key,
                "editorial_status": parent.get("editorial_status", "") if key == "translation" else "",
                "before": value,
                "after": unify(value) if proof else value,
                "decision": "rewritten" if proof else "kept",
                "evidence": proof[0] if proof else "no wave dash in the Japanese source",
                "japanese": proof[1] if proof else (
                    parent.get("source_text") or parent.get("source")
                    or japanese.get(parent.get("source_text_sha256", ""), "")
                    if key == "translation" else ""
                ),
            })
            if proof:
                selected[(key, value)].add(index)

        for (key, value), indexes in selected.items():
            pattern = re.compile(
                "(" + re.escape(json.dumps(key, ensure_ascii=False)) + r"\s*:\s*)"
                + re.escape(json.dumps(value, ensure_ascii=False))
            )
            if len(pattern.findall(raw)) != totals[(key, value)]:
                raise SystemExit(f"{relative}: {value!r} is not written as expected")
            counter = iter(range(totals[(key, value)]))
            replacement = json.dumps(unify(value), ensure_ascii=False)
            raw = pattern.sub(
                lambda match: match.group(1) + replacement
                if next(counter) in indexes else match.group(0),
                raw,
            )
            changed[relative] += len(indexes)

        if selected and not args.dry_run:
            path.write_text(raw, encoding="utf-8")

    for name, count in sorted(changed.items()):
        print("%-52s %d" % (name, count))
    kept = sum(1 for row in ledger if row["decision"] == "kept")
    print(("dry-run: " if args.dry_run else "")
          + f"rewritten: {sum(changed.values())}, kept without source evidence: {kept}")
    if args.ledger:
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        args.ledger.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
