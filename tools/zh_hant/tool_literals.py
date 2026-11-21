#!/usr/bin/env python3
"""Regional versions of the Chinese string constants in the build tools (layout-protected words, label
fragments, gate literals) and of config labels (scenario / mode select labels) that are not whole corpus strings.

Each language keeps its own text in config/zh-hant/tool-literals/<tw|hk>.json, static and written by hand like
the corpora. A build only reads these files (build_dual.prepare_tc); a
constant that is missing stops it.

Usage: tool_literals.py [--check]   list constants with no regional text (exit 1 if any)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STORE = ROOT / 'config/zh-hant/tool-literals'
CONSTANT = re.compile(r'(["\'])([^"\'\n]*[一-鿿][^"\'\n]*)\1')


def constants(root: Path = ROOT) -> list[str]:
    sys.path.insert(0, str(HERE))
    from build_dual import BUILD_TOOL_SOURCES
    found = {}
    for pattern in BUILD_TOOL_SOURCES:
        for path in sorted(root.glob(pattern)):
            for m in CONSTANT.finditer(path.read_text(encoding='utf-8')):
                found.setdefault(m.group(2), None)
    return list(found)


def load(variant: str) -> dict:
    path = STORE / f'{variant}.json'
    return json.loads(path.read_text(encoding='utf-8'))['literals'] if path.exists() else {}


def corpus_counterparts(variant: str, root: Path = ROOT) -> tuple[dict, dict]:
    """(unique literals, ambiguous literals) of a variant's corpus as its build sees it: Hong Kong takes the files
    of config/zh-hant/hk-uses-taiwan.json from Taiwan."""
    sys.path.insert(0, str(HERE))
    import build_dual as bd
    counterparts = bd.literal_counterparts(root / 'corpus/zh', root / 'corpus' / bd.VARIANTS[variant]['suffix'])
    if variant != 'tw':
        for rel in bd.hk_uses_taiwan():
            for k, v in bd.literal_counterparts((root / 'corpus/zh' / rel).parent, (root / 'corpus/zh-hant' / rel).parent,
                                                only=Path(rel).name).items():
                counterparts.setdefault(k, [])
                counterparts[k] += [x for x in v if x not in counterparts[k]]
    return ({k: v[0] for k, v in counterparts.items() if len(v) == 1},
            {k: v for k, v in counterparts.items() if len(v) > 1})


def missing(variant: str, corpus_literals: dict, ambiguous: dict) -> list[str]:
    have = load(variant)
    return [c for c in constants() if c not in corpus_literals and c not in ambiguous and c not in have]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--check', action='store_true')
    a = p.parse_args()
    sys.path.insert(0, str(HERE))
    import build_dual as bd
    status = 0
    for variant, inputs in bd.VARIANTS.items():
        literals, ambiguous = corpus_counterparts(variant)
        gaps = missing(variant, literals, ambiguous)
        if gaps:
            status = 1
            print(f'{variant}: {len(gaps)} tool constants have no regional text, e.g. {gaps[:5]}')
        else:
            print(f'{variant}: all tool constants have regional text')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
