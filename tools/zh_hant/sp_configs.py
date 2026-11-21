#!/usr/bin/env python3
"""Regional copies of the SP configs that carry translations (build_dual_sp.SP_CONFIG_DRAFTS).

Each language keeps its own text: the Taiwan and Hong Kong copies live in config/zh-hant/sp-configs/<tw|hk>/<path>
and are edited there by hand, like the parallel corpora; a build copies them unchanged into the regional SP view.
sources.json records optional editorial provenance. Each language can be revised independently.

Usage: sp_configs.py status            list missing copies (exit 1 if any)
       sp_configs.py accept PATH ...   record the current Simplified file as the source of a hand-updated copy
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / 'tools')]
STORE = ROOT / 'config/zh-hant/sp-configs'
SOURCES = STORE / 'sources.json'
VARIANTS = ('tw', 'hk')


def stored_paths() -> list[str]:
    from build_dual_sp import SP_CONFIG_DRAFTS
    return list(SP_CONFIG_DRAFTS)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> dict:
    return json.loads(SOURCES.read_text(encoding='utf-8')) if SOURCES.exists() else {}


def status() -> list[str]:
    problems = []
    for variant in VARIANTS:
        for rel in stored_paths():
            copy = STORE / variant / rel
            if not copy.exists():
                problems.append(f'{variant}: {rel} has no regional copy (write {copy.relative_to(ROOT)} by hand)')
    return problems


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('command', choices=('status', 'accept'))
    p.add_argument('paths', nargs='*')
    a = p.parse_args()
    if a.command == 'status':
        problems = status()
        print('\n'.join(problems) or 'SP regional configs: all current')
        return 1 if problems else 0
    known = sources()
    for rel in a.paths:
        for variant in VARIANTS:
            known[f'{variant}/{rel}'] = sha(ROOT / rel)
    SOURCES.write_text(json.dumps(dict(sorted(known.items())), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('accepted', a.paths)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
