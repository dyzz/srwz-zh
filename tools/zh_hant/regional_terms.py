#!/usr/bin/env python3
"""Regional (Taiwan / Hong Kong) vocabulary for the Traditional text: config/zh-hant/regional-terms.json.

A rule fires on a Traditional string only when the paired Simplified string contains the rule's `sc` term and, for a
bound rule (`jp`), the record's Japanese source contains one of `jp` and none of `jp_not`. When the Japanese is not
known only unbound rules fire. Rules with the same `sc` are alternatives: the first one that matches wins. Rules run
longest `sc` first and their output is protected from later rules.

    stage 'tw': the parallel Traditional corpus (rule.tc forms) -> Taiwan forms (sync_corpus.py runs it on every
                document it writes, so drafts, edited and reviewed entries all carry the Taiwan terms)
    stage 'hk': Taiwan text (rule.tw forms) -> Hong Kong forms (the Hong Kong derivation)

Usage: regional_terms.py [--check]   (rewrites corpus/*-zh-hant in place; report build/zh-hant/regional-tw-report.json)
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / 'config/zh-hant/regional-terms.json'
PRIVATE = 0xF8000
KANA = __import__('re').compile('[぀-ヺー-ヿ]')
SPACE = __import__('re').compile(r'[\s\u3000]+')
STAGES = {'tw': ('tc', 'tw'), 'hk': ('tw', 'hk')}


@lru_cache(maxsize=None)
def rules() -> tuple:
    doc = json.loads(RULES.read_text(encoding='utf-8'))
    rs = doc['rules']
    for r in rs:
        for k in ('sc', 'tc', 'tw', 'hk'):
            if not r.get(k): raise SystemExit(f'regional-terms: rule without {k}: {r}')
    order = sorted(range(len(rs)), key=lambda i: (-len(rs[i]['sc']), i))      # stable: alternatives keep file order
    return tuple(rs[i] for i in order)


def length_bound(rel: str) -> bool:
    """`rel` is the Traditional document path (corpus/zh-hant/..., corpus/glossary-zh-hant/...)."""
    return rel in json.loads(RULES.read_text(encoding='utf-8')).get('length_bound_files', {})


@lru_cache(maxsize=None)
def japanese() -> tuple[dict, dict]:
    sys.path.insert(0, str(ROOT / 'tools/editorial_review'))
    from japanese_sources import resolve_all
    return resolve_all()


def jp_of(entry: dict) -> str | None:
    """The record's Japanese source: inline (SP corpus) or resolved by source hash / id (main corpus)."""
    for k in ('source_text', 'source'):
        v = entry.get(k)
        if isinstance(v, str) and KANA.search(v): return v
    by_sha, by_id = japanese()
    return by_sha.get(entry.get('source_text_sha256') or '') or by_id.get(entry.get('id') or '') or None


ANY = object()          # "the Japanese could be anything": bound rules fire too (layout word lists)


DRAFT = object()        # drafting without the Japanese: terms that have a Japanese-bound alternative wait for the
                        # document pass (sync_corpus), which knows the record


@lru_cache(maxsize=None)
def bound_terms() -> frozenset:
    return frozenset(r['sc'] for r in rules() if 'jp' in r)


def fires(rule: dict, jp) -> bool:
    if jp is DRAFT: return rule['sc'] not in bound_terms()
    if 'jp' not in rule or jp is ANY: return True
    if jp is None: return False
    jp = SPACE.sub('', jp)                    # SP sources break lines inside words (情\n報)
    return any(w in jp for w in rule['jp']) and not any(w in jp for w in rule.get('jp_not', ()))


def apply_string(sc: str, text: str, jp, stage: str, hits: dict | None = None, ambiguous: list | None = None,
                 fixed_length: bool = False) -> str:
    src, dst = STAGES[stage]
    slots, done, rest = [], set(), sc
    for r in rules():
        if r['sc'] in done or r['sc'] not in rest or not fires(r, jp): continue
        done.add(r['sc'])                         # an alternative matched: later rules for this term are skipped
        want = rest.count(r['sc'])
        rest = rest.replace(r['sc'], '\0')       # a longer term already took these characters
        if r[src] == r[dst] or r[src] not in text: continue
        if fixed_length and len(r[src]) != len(r[dst]): continue
        n = text.count(r[src])
        if stage == 'hk' and n != want:
            # the Taiwan form also comes from other Simplified text (資料 <- 数据 and 资料): needs an override
            if ambiguous is not None: ambiguous.append({'term': r['sc'], 'tw': r[src], 'hk': r[dst], 'text': text})
            continue
        text = text.replace(r[src], chr(PRIVATE + len(slots))); slots.append(r[dst])
        if hits is not None:
            key = f"{r['sc']}→{r[dst]}" + (f" [{'/'.join(r['jp'])}]" if 'jp' in r else '')
            hits[key] = hits.get(key, 0) + n
    for i, s in enumerate(slots):
        text = text.replace(chr(PRIVATE + i), s)
    return text


def apply_doc(sc, tc, stage: str, frozen: set, key_fields: tuple, report: dict, jp=None, key=None, fixed=False):
    """Walk the Simplified and Traditional documents in parallel; return the rewritten Traditional document."""
    if isinstance(sc, str) and isinstance(tc, str):
        if key in frozen: return tc
        return apply_string(sc, tc, jp, stage, report.setdefault('hits', {}), report.setdefault('ambiguous', []), fixed)
    if isinstance(sc, dict) and isinstance(tc, dict):
        if any(k in sc for k in ('source_text_sha256', 'source_text', 'source', 'id')):
            jp = jp_of(sc) or jp
        return {k: (v if k in frozen or k.endswith('_sha256') or k not in sc or k in ('zh_hans_sha256', 'zh_hant_status', 'zh_hant_meta')
                    else apply_doc(sc[k], v, stage, frozen, key_fields, report, jp, k, fixed)) for k, v in tc.items()}
    if isinstance(sc, list) and isinstance(tc, list):
        def ek(e):
            return next((e[f] for f in key_fields if isinstance(e, dict) and f in e), None)
        if sc and all(isinstance(e, dict) and ek(e) is not None for e in sc):
            by = {ek(e): e for e in sc}
            return [apply_doc(by[ek(t)], t, stage, frozen, key_fields, report, jp, key, fixed) if isinstance(t, dict) and ek(t) in by else t
                    for t in tc]
        if len(sc) == len(tc):
            return [apply_doc(a, b, stage, frozen, key_fields, report, jp, key, fixed) for a, b in zip(sc, tc)]
        report.setdefault('unpaired_lists', 0); report['unpaired_lists'] += 1
    return tc


LAYOUT = ('zh-story-unbroken-words.json', 'zh-flow-scroll-words.json', 'zh-prose-extra-words.json')


def layout_lists(stage: str, src_dir: Path, sc_dir: Path, dst_dir: Path, report: dict, check: bool) -> list:
    """Unbreakable-word lists: each word drafted from the Simplified list at the same index takes the regional forms.
    Forms that only a Japanese-bound rule gives are added beside the word (the binding is unknown for a bare word)."""
    changed = []
    for name in LAYOUT:
        doc = json.loads((src_dir / name).read_text(encoding='utf-8'))
        sc = json.loads((sc_dir / name).read_text(encoding='utf-8'))
        for field in ('common_words', 'proper_names'):
            words, base = doc[field], sc[field]
            out, extra = [], []
            for i, w in enumerate(words):
                s = base[i] if i < len(base) else None
                if s is None: out.append(w); continue
                unbound = apply_string(s, w, None, stage, report.setdefault('layout_hits', {}))
                bound = apply_string(s, w, ANY, stage)
                out.append(unbound)
                if bound != unbound: extra.append(bound)
            out += [w for w in dict.fromkeys(extra) if w not in out]
            doc[field] = out
        text = json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
        if (dst_dir / name).exists() and (dst_dir / name).read_text(encoding='utf-8') == text: continue
        changed.append(str((dst_dir / name).relative_to(ROOT)))
        if not check: dst_dir.mkdir(parents=True, exist_ok=True); (dst_dir / name).write_text(text, encoding='utf-8')
    return changed


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--check', action='store_true')
    a = p.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sync_corpus as sc_mod
    report, written = {}, []
    for src_root, dst_root, _ in sc_mod.TREES:
        for f in sorted((ROOT / dst_root).rglob('*.json')):
            rel = f.relative_to(ROOT / dst_root)
            src = ROOT / src_root / rel
            if not src.exists(): continue
            sp = rel.parts[0] == sc_mod.SP_TREE and src_root == 'corpus/zh'
            frozen = (sc_mod.FROZEN_KEYS - {'review_history'}) | sc_mod.SP_FROZEN if sp else sc_mod.FROZEN_KEYS
            keys = ('id', 'entry_index', 'source') if sp else ('id', 'entry_index')
            tc = json.loads(f.read_text(encoding='utf-8'))
            out = apply_doc(json.loads(src.read_text(encoding='utf-8')), tc, 'tw', frozen, keys, report,
                            fixed=length_bound(f'{dst_root}/{rel}'))
            if out != tc:
                written.append(str(f.relative_to(ROOT)))
                if not a.check:
                    f.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lay = ROOT / 'config/zh-hant/text-layout'
    written += layout_lists('tw', lay, ROOT / 'config/text-layout', lay, report, a.check)
    report['files_changed'] = written
    out = ROOT / 'build/zh-hant/regional-tw-report.json'; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'files_changed': len(written), 'hits': report.get('hits', {}),
                      'unpaired_lists': report.get('unpaired_lists', 0)}, ensure_ascii=False, indent=1))
    if a.check and written: sys.exit(1)


if __name__ == '__main__':
    main()
