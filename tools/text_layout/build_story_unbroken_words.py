#!/usr/bin/env python3
"""Generate the story-dialogue unbroken word list used by the layout engine.

The ``story_dialogue`` layout profile treats every entry of
``config/text-layout/zh-story-unbroken-words.json`` as an indivisible unit, so
line breaks never fall inside a common word or a proper name.  This tool
rebuilds that JSON from three checked-in sources:

* ``zh-story-common-words.txt``: hand-reviewed common words.
* ``zh-story-proper-names.txt``: hand-added proper names.
* corpus speakers, glossary terms and unit display names: proper names
  collected automatically.

Run it after editing either text file or the corpus name sources::

    python3 tools/text_layout/build_story_unbroken_words.py
    python3 tools/text_layout/build_story_unbroken_words.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAYOUT_DIR = PROJECT_ROOT / "config/text-layout"
COMMON_WORDS_PATH = LAYOUT_DIR / "zh-story-common-words.txt"
PROPER_NAMES_PATH = LAYOUT_DIR / "zh-story-proper-names.txt"
OUTPUT_PATH = LAYOUT_DIR / "zh-story-unbroken-words.json"
SPEAKERS_PATH = PROJECT_ROOT / "corpus/zh/story-speakers.json"
UNITS_PATH = PROJECT_ROOT / "corpus/zh/display-names/units-full.json"
GLOSSARY_DIR = PROJECT_ROOT / "corpus/glossary"

# A protected term must be at least two display cells and must consist of
# ideographs, optionally joined by the interpunct used in transliterated names.
_NAME_PATTERN = re.compile(r"[一-鿿]+(?:·[一-鿿]+)*")
MAX_NAME_LENGTH = 12


def read_word_file(path: Path) -> list[str]:
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        if "\n" in word or len(word) < 2:
            raise SystemExit(f"{path}: invalid word {word!r}")
        words.append(word)
    if len(words) != len(set(words)):
        duplicates = sorted({w for w in words if words.count(w) > 1})
        raise SystemExit(f"{path}: duplicate words {duplicates}")
    return words


def _is_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and 2 <= len(value) <= MAX_NAME_LENGTH
        and _NAME_PATTERN.fullmatch(value) is not None
    )


def _entries(document: object) -> list:
    if isinstance(document, dict):
        for key in ("entries", "terms"):
            rows = document.get(key)
            if isinstance(rows, list):
                return rows
        return []
    return document if isinstance(document, list) else []


def collect_corpus_names() -> dict[str, list[str]]:
    sources: dict[str, list[str]] = {}
    speakers = set()
    for row in _entries(json.loads(SPEAKERS_PATH.read_text(encoding="utf-8"))):
        if isinstance(row, dict) and _is_name(row.get("translation")):
            speakers.add(row["translation"])
    sources[str(SPEAKERS_PATH.relative_to(PROJECT_ROOT))] = sorted(speakers)

    units = set()
    for row in _entries(json.loads(UNITS_PATH.read_text(encoding="utf-8"))):
        if isinstance(row, dict) and _is_name(row.get("translation")):
            units.add(row["translation"])
    sources[str(UNITS_PATH.relative_to(PROJECT_ROOT))] = sorted(units)

    for path in sorted(GLOSSARY_DIR.glob("*.json")):
        names = set()
        for row in _entries(json.loads(path.read_text(encoding="utf-8"))):
            if not isinstance(row, dict):
                continue
            for key, value in row.items():
                if key.startswith("deprecated"):
                    continue
                candidates = value if isinstance(value, list) else [value]
                if "translation" in key or key == "aliases":
                    names.update(c for c in candidates if _is_name(c))
        sources[str(path.relative_to(PROJECT_ROOT))] = sorted(names)
    return sources


def build_document() -> dict:
    common_words = read_word_file(COMMON_WORDS_PATH)
    manual_names = read_word_file(PROPER_NAMES_PATH)
    for word in manual_names:
        if not _is_name(word):
            raise SystemExit(f"{PROPER_NAMES_PATH}: not a proper name: {word!r}")
    corpus_sources = collect_corpus_names()
    proper_names = set(manual_names)
    for names in corpus_sources.values():
        proper_names.update(names)
    proper_names -= set(common_words)
    return {
        "schema_version": 1,
        "purpose": (
            "story_dialogue 档的不可拆分单元：常用词来自人工复核的拆词断行排查，"
            "专名来自语料说话人、词表和机体名；由 "
            "tools/text_layout/build_story_unbroken_words.py 生成，不要手工编辑。"
        ),
        "sources": {
            "common_words": str(COMMON_WORDS_PATH.relative_to(PROJECT_ROOT)),
            "manual_proper_names": str(PROPER_NAMES_PATH.relative_to(PROJECT_ROOT)),
            "corpus_proper_names": {
                path: len(names) for path, names in corpus_sources.items()
            },
        },
        "common_words": sorted(common_words),
        "proper_names": sorted(proper_names),
    }


def render(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when the checked-in JSON differs from the generated one",
    )
    args = parser.parse_args()
    rendered = render(build_document())
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(f"{OUTPUT_PATH} is stale; rerun without --check", file=sys.stderr)
            return 1
        print(f"{OUTPUT_PATH} is up to date")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    document = json.loads(rendered)
    print(
        f"wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
        f"{len(document['common_words'])} common words, "
        f"{len(document['proper_names'])} proper names"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
