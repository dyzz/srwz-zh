#!/usr/bin/env python3
"""Derive the Hong Kong Traditional sources from the Taiwan ones (docs/ZH_HANT_HK_TW_PLAN_20261118.md, H2).

Taiwan text (corpus/zh-hant, corpus/glossary-zh-hant, corpus/runtime-zh-hant, config/zh-hant/text-layout)
  -> regional terms, stage 'hk' (config/zh-hant/regional-terms.json: Taiwan form -> Hong Kong form, bound to the
     Simplified string and the Japanese source like the Taiwan pass)
  -> Hong Kong character forms (config/zh-hant/hk-characters.json) on every translatable string
  -> per-string overrides (config/zh-hant/hk-overrides.json: {file, id, key, tw, hk}; applied only while the Taiwan
     string still equals `tw`, otherwise listed as stale for review)
  -> build/zh-hant-hk/{corpus/zh-hant, corpus/glossary-zh-hant, corpus/runtime-zh-hant, text-layout}

The output is a build input, never edited by hand. Report: build/zh-hant-hk/derive-report.json.
Usage: derive_hk.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import regional_terms as rt          # noqa: E402
import sync_corpus as sc_mod         # noqa: E402

KANA = re.compile('[぀-ヺー-ヿ]')
CHARS = ROOT / 'config/zh-hant/hk-characters.json'
OVERRIDES = ROOT / 'config/zh-hant/hk-overrides.json'


def char_table() -> dict:
    return str.maketrans(json.loads(CHARS.read_text(encoding='utf-8'))['map'])


def forms(doc, table, frozen: set, report: dict, key=None):
    if isinstance(doc, str):
        if key in frozen or KANA.search(doc): return doc
        out = doc.translate(table)
        if out != doc: report['char_strings'] = report.get('char_strings', 0) + 1
        return out
    if isinstance(doc, list):
        return [forms(x, table, frozen, report, key) for x in doc]
    if isinstance(doc, dict):
        return {k: (v if k in frozen or k.endswith('_sha256') or k in ('zh_hans_sha256', 'zh_hant_status', 'zh_hant_meta')
                    else forms(v, table, frozen, report, k)) for k, v in doc.items()}
    return doc


def overrides_for(rel: str) -> list:
    if not OVERRIDES.exists(): return []
    return [o for o in json.loads(OVERRIDES.read_text(encoding='utf-8'))['overrides'] if o['file'] == rel]


def apply_overrides(hk, tw, rel: str, report: dict):
    for o in overrides_for(rel):
        def find(node):
            if isinstance(node, dict):
                if node.get('id') == o['id'] or node.get('entry_index') == o['id']: return node
                for v in node.values():
                    r = find(v)
                    if r is not None: return r
            if isinstance(node, list):
                for v in node:
                    r = find(v)
                    if r is not None: return r
        t, h = find(tw), find(hk)
        if t is None or h is None or t.get(o['key']) != o['tw']:
            report.setdefault('stale_overrides', []).append({k: o[k] for k in ('file', 'id', 'key')}); continue
        h[o['key']] = o['hk']; report['overrides'] = report.get('overrides', 0) + 1
    return hk


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--out', type=Path, default=ROOT / 'build/zh-hant-hk')
    a = p.parse_args()
    table, report = char_table(), {}
    if a.out.exists(): shutil.rmtree(a.out)
    for src_root, dst_root, _ in sc_mod.TREES:
        for f in sorted((ROOT / dst_root).rglob('*.json')):
            rel = f.relative_to(ROOT / dst_root)
            sp = rel.parts[0] == sc_mod.SP_TREE and src_root == 'corpus/zh'
            frozen = (sc_mod.FROZEN_KEYS - {'review_history'}) | sc_mod.SP_FROZEN if sp else sc_mod.FROZEN_KEYS
            keys = ('id', 'entry_index', 'source') if sp else ('id', 'entry_index')
            tw = json.loads(f.read_text(encoding='utf-8'))
            src = ROOT / src_root / rel
            hk = rt.apply_doc(json.loads(src.read_text(encoding='utf-8')), tw, 'hk', frozen, keys, report,
                              fixed=rt.length_bound(f'{dst_root}/{rel}')) if src.exists() else tw
            hk = forms(hk, table, frozen, report)
            hk = apply_overrides(hk, tw, f'{dst_root}/{rel}', report)
            out = a.out / dst_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(hk, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lay = a.out / 'text-layout'
    rt.layout_lists('hk', ROOT / 'config/zh-hant/text-layout', ROOT / 'config/text-layout', lay, report, False)
    for name in rt.LAYOUT:
        doc = json.loads((lay / name).read_text(encoding='utf-8'))
        for field in ('common_words', 'proper_names'):
            doc[field] = list(dict.fromkeys(w.translate(table) for w in doc[field]))
        (lay / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (a.out / 'derive-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items() if k != 'layout_hits'},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
