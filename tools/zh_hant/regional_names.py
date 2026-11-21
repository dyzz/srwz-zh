#!/usr/bin/env python3
"""Taiwan / Hong Kong proper names for the Traditional text: config/zh-hant/regional-names.json.

The table holds every glossary name with its regional forms (settled 2026-11-20, see
docs/ZH_HANT_HK_TW_PLAN_20261118.md §6). A name is rewritten in a regional string only when
  * the paired Simplified string contains the Simplified name (longer names first; a longer name masks its span),
  * the record's Japanese, when known, contains one of the name's Japanese source terms (unknown Japanese: only
    names of three or more characters outside the system categories),
  * the regional string holds the earlier regional form exactly as often as the Simplified string holds the name.
Names whose regional form did not change (`apply` false) only mask and protect their spans.
regional_terms.py covers vocabulary; this covers names. The corpora carry the names already; the build uses this
module for text that is drafted from Simplified at build time (the SP configs, build_dual_sp.sp_config_drafts).
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / 'config/zh-hant/regional-names.json'
SYSTEM = {'skill', 'spirit', 'ability', 'part', 'system'}
PRIVATE = 0xF0000
KANA = re.compile('[ぁ-ヺ]')


def norm(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


@lru_cache(maxsize=None)
def rules(region: str) -> tuple:
    rows = json.loads(TABLE.read_text(encoding='utf-8'))['names']
    out = [dict(id=r['id'], sc=r['sc'], ja=tuple(r['ja']), cat=r['category'], to=r[region]['to'],
                forms=tuple(r[region]['from']), apply=bool(r[region]['apply'])) for r in rows if r['sc']]
    order = sorted(range(len(out)), key=lambda i: (-len(out[i]['sc']), i))
    return tuple(out[i] for i in order)


class Names:
    def __init__(self, region: str):
        self.rules = rules(region)
        self.first = frozenset(r['sc'][0] for r in self.rules)
        self.hits: dict = {}

    def string(self, sc: str, text: str, jp, *, fixed: bool = False) -> str:
        if not any(c in self.first for c in sc):
            return text
        rest, slots, done = sc, [], set()
        njp = norm(jp) if isinstance(jp, str) else None
        for r in self.rules:
            if r['sc'] not in rest or r['sc'] in done:
                continue
            if r['sc'] == sc and len({x['to'] for x in self.rules if x['sc'] == sc}) == 1:
                pass                    # the string is exactly one name (a speaker field): no Japanese needed
            elif njp is not None:
                if not any(j in njp for j in r['ja']):
                    continue
            elif r['apply'] and (len(r['sc']) < 3 or r['cat'] in SYSTEM):
                continue
            done.add(r['sc'])
            want = rest.count(r['sc'])
            rest = rest.replace(r['sc'], '\0')
            if r['apply'] and any(f != r['to'] and f in r['to'] for f in r['forms']) and r['to'] in text:
                # the regional string already reads as the new name (墮天翅族 for 堕天翅族): not rewritten again
                text = text.replace(r['to'], chr(PRIVATE + len(slots))); slots.append(r['to'])
            src = next((f for f in r['forms'] if f in text), None)
            keep = not r['apply'] or src is None or src == r['to'] or (fixed and len(src) != len(r['to'])) \
                or text.count(src) != want
            if keep:
                for f in (*r['forms'], r['to']):
                    if f in text:
                        text = text.replace(f, chr(PRIVATE + len(slots))); slots.append(f)
                continue
            text = text.replace(src, chr(PRIVATE + len(slots))); slots.append(r['to'])
            self.hits[r['id']] = self.hits.get(r['id'], 0) + want
        for i, s in enumerate(slots):
            text = text.replace(chr(PRIVATE + i), s)
        return text

    def doc(self, sc, tc, frozen: set, keys: tuple, jp=None, key=None):
        """Walk the Simplified and regional documents in parallel; return the rewritten regional document."""
        if isinstance(sc, str) and isinstance(tc, str):
            return tc if key in frozen else self.string(sc, tc, jp)
        if isinstance(sc, dict) and isinstance(tc, dict):
            if 'source_terms' in sc:
                jp = ' '.join(sc['source_terms'])
            elif any(k in sc for k in ('source_text_sha256', 'source_text', 'source', 'id')):
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import regional_terms
                jp = regional_terms.jp_of(sc) or jp
            # a key that is itself Japanese (name tables: Japanese name -> translations) binds its value
            return {k: (v if k in frozen or k.endswith('_sha256') or k not in sc
                        else self.doc(sc[k], v, frozen, keys, k if KANA.search(k) else jp, k))
                    for k, v in tc.items()}
        if isinstance(sc, list) and isinstance(tc, list):
            def ek(e):
                return next((e[f] for f in keys if isinstance(e, dict) and f in e), None)
            if sc and all(isinstance(e, dict) and ek(e) is not None for e in sc):
                by = {json.dumps(ek(e), ensure_ascii=False, sort_keys=True): e for e in sc}
                return [self.doc(by[json.dumps(ek(t), ensure_ascii=False, sort_keys=True)], t, frozen, keys, jp, key)
                        if isinstance(t, dict) and json.dumps(ek(t), ensure_ascii=False, sort_keys=True) in by else t for t in tc]
            if len(sc) == len(tc):
                return [self.doc(a, b, frozen, keys, jp, key) for a, b in zip(sc, tc)]
        return tc


def apply_doc(sc, tc, region: str, frozen: set, keys: tuple = ('id', 'entry_index')):
    return Names(region).doc(sc, tc, frozen, keys)
