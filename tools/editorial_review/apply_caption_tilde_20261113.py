#!/usr/bin/env python3
"""Unify the title-caption wave dash on 〜 (U+301C) across menu and SP surfaces.

The Japanese banner captions are written 〜...〜.  Story dialogue and the SP
story file were normalised to 〜 by ``normalize_location_captions.py`` on
2026-11-07, but that pass only covers ``story-dialogue/stage-*.json`` and the
SP story file, so the menu and SP system captions kept ～ (U+FF5E).  Both
characters have their own re-rastered glyph (〜 = 8160/glyph 32, 66 ink px;
～ = 889A/glyph 1434, 28 ink px), so the two render as visibly different
marks on neighbouring menu screens.

Each rewrite binds to the Japanese source: a record is touched only when its
source is a 〜...〜 caption and the translation is the matching ～...～ caption,
so drawn-out vowels ("好厉害～！") are never caught.

    python3 tools/editorial_review/apply_caption_tilde_20261113.py --dry-run
    python3 tools/editorial_review/apply_caption_tilde_20261113.py
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

CAPTION = re.compile(r"^[　 ]*[~〜～].*[~〜～][　 ]*$")


def is_caption(text: str) -> bool:
    return bool(text) and bool(CAPTION.match(text.strip()))


def walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, path + "/" + key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, path + "/%d" % index)
    elif isinstance(node, str):
        yield path, node


def load_japanese():
    cache = PROJECT_ROOT / "work/review/caption-tilde-20261113/jp-by-sha.json"
    if not cache.exists():
        raise SystemExit(
            f"missing {cache}; run tools/editorial_review/japanese_sources.py --out {cache}"
        )
    return json.loads(cache.read_text(encoding="utf-8"))["by_sha"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    japanese = load_japanese()
    targets = sorted(
        set(glob.glob(str(PROJECT_ROOT / "corpus/zh/menu/*.json")))
        | set(glob.glob(str(PROJECT_ROOT / "corpus/zh/special-disc/*.json")))
    )

    changed = collections.Counter()
    for path_str in targets:
        path = Path(path_str)
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
        groups = collections.defaultdict(dict)
        for pointer, value in walk(document):
            base, key = pointer.rsplit("/", 1)
            groups[base][key] = value

        edits = []
        for record in groups.values():
            translation = record.get("translation")
            if not translation or "～" not in translation:
                continue
            source = record.get("source_text") or japanese.get(
                record.get("source_text_sha256", ""), ""
            )
            # Bind to the Japanese: only 〜...〜 captions qualify.
            if not source or "〜" not in source:
                continue
            if not is_caption(source) or not is_caption(translation):
                continue
            edits.append((translation, translation.replace("～", "〜")))

        # The same caption can occupy several slots in one file (a menu string
        # reached from more than one screen); every copy gets the same fix.
        for before, after in dict(edits).items():
            needle = json.dumps(before, ensure_ascii=False)
            replacement = json.dumps(after, ensure_ascii=False)
            hits = raw.count(needle)
            if not hits:
                raise SystemExit(f"{path}: {before!r} not found")
            raw = raw.replace(needle, replacement)
            changed[str(path.relative_to(PROJECT_ROOT))] += hits

        if edits and not args.dry_run:
            path.write_text(raw, encoding="utf-8")

    total = sum(changed.values())
    for name, count in sorted(changed.items()):
        print("%-46s %d" % (name, count))
    print(("dry-run: " if args.dry_run else "") + f"captions unified: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
