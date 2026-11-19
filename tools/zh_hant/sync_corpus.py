#!/usr/bin/env python3
"""Keep the parallel Traditional corpora in step with the Simplified ones.

Traditional text is maintained as its own files, parallel to the Simplified trees:
    corpus/zh        -> corpus/zh-hant           (special-disc/ too, since the SP dual disc: see SP_FROZEN)
    corpus/glossary  -> corpus/glossary-zh-hant
    corpus/runtime   -> corpus/runtime-zh-hant
Each entry (object with an "id" or an "entry_index") carries
    zh_hans_sha256   sha256 of the Simplified entry's translation-bearing content it was written against
    zh_hant_status   draft (machine, may be redrafted) | edited (changed by hand) | reviewed (approved)
Documents without entries carry the same two fields in a top-level "zh_hant_meta".

Sync rules, per entry:
    missing                                 -> draft from the Simplified entry
    hash unchanged                          -> kept
    hash changed, status draft              -> redrafted
    hash changed, status edited / reviewed  -> kept, listed as stale (needs review); never overwritten
Drafts come from config/zh-hant/bootstrap.json: an OpenCC base conversion (character standard only) plus
term substitutions protected through it. Every document then gets the Taiwan vocabulary of
config/zh-hant/regional-terms.json (tools/zh_hant/regional_terms.py), bound to the Simplified and Japanese text. Japanese sources, notes, ids and hashes stay verbatim; strings
containing kana are treated as Japanese.

Usage: sync_corpus.py [--check]    (--check: report only, exit 1 when anything is missing or stale)
Report: build/zh-hant/sync-report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regional_terms  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TREES = [('corpus/zh', 'corpus/zh-hant', set()),
         ('corpus/glossary', 'corpus/glossary-zh-hant', set()),
         ('corpus/runtime', 'corpus/runtime-zh-hant', set())]
# SP corpus fields that are keys or bindings, not display text: Japanese speaker names (kanji-only ones would be
# converted), Chinese location ids such as sd/image/kvmdata/结算提示图集/0, writeback bindings and provenance.
SP_TREE = 'special-disc'
SP_FROZEN = {'speaker', 'speaker_guess', 'voice_group', 'triggers', 'locations', 'location', 'scope', 'module', 'origin',
             'origin_legend', 'product', 'corpus_path', 'corpus_id', 'config', 'translation_source', 'source_inventory',
             'episode', 'section', 'kind', 'episode_file', 'writeback_contract', 'writeback_binding', 'writeback_status',
             'qa_review_import', 'disposition', 'exception', 'source_classification', 'flags', 'source_corpus'}
KANA = re.compile('[぀-ヺー-ヿㇰ-ㇿｦ-ﾟ]')     # not U+30FB ・ (Chinese names)
HAN = re.compile('[㐀-鿿]')
FROZEN_KEYS = {'id', 'source', 'source_text', 'source_term', 'source_terms', 'notes', 'reason', 'review_history',
               'editorial_status', 'translation_action', 'glossary_refs', 'production_override', 'batch_id', 'language',
               'schema_version', 'glossary_id', 'profile_id', 'status', 'category', 'domains', 'entry_index'}
META = ('zh_hans_sha256', 'zh_hant_status')
STATUSES = {'draft', 'edited', 'reviewed'}
PRIVATE = 0xF0000
TM_SCOPE = re.compile(r'＜[ｔt][ｍm]＞[^＜＞\n]+＜[／/][ｔt][ｍm]＞|<tm>[^<>\n]+</tm>')


def sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class Drafter:
    def __init__(self, bootstrap: Path):
        from importlib.metadata import PackageNotFoundError, version
        try:
            installed = version('OpenCC')
        except PackageNotFoundError:
            installed = None
        if installed != '1.4.2':
            raise SystemExit('Install OpenCC==1.4.2 in SRWZ_LANGUAGE_PYTHON to use the verified s2tw dictionary')
        import opencc
        cfg = json.loads(bootstrap.read_text(encoding='utf-8'))
        self.cc = opencc.OpenCC(cfg['opencc'])
        self.terms = sorted(((t['sc'], t['tc']) for t in cfg['terms']), key=lambda t: -len(t[0]))
        self.frozen = FROZEN_KEYS              # per tree (main() widens it for the SP corpus)

    def text(self, s: str) -> str:
        if not HAN.search(s) or KANA.search(s):
            return s
        source = s
        slots = []
        # numeric template keys (＜ｔｍ＞撃墜数＜／ｔｍ＞) are lookup data the executable matches byte for byte
        for m in TM_SCOPE.findall(s):
            s = s.replace(m, chr(PRIVATE + len(slots)), 1); slots.append(m)
        for sc, tc in self.terms:
            if sc in s:
                s = s.replace(sc, chr(PRIVATE + len(slots))); slots.append(tc)
        out = self.cc.convert(s)
        for i, tc in enumerate(slots):
            out = out.replace(chr(PRIVATE + i), tc)
        return regional_terms.apply_string(source, out, regional_terms.DRAFT, 'tw')

    def value(self, v, key=None):
        if isinstance(v, str):
            return v if key in self.frozen else self.text(v)
        if isinstance(v, list):
            return [self.value(x, key) for x in v]
        if isinstance(v, dict):
            return {k: (x if k in self.frozen or k.endswith('_sha256') or k in META else self.value(x, k)) for k, x in v.items()}
        return v


def translation_view(entry: dict) -> dict:
    """The part of a Simplified entry a Traditional entry is written against (no JP source, no notes)."""
    return {k: v for k, v in entry.items() if k not in FROZEN_KEYS and not k.endswith('_sha256') and k not in META}


REDRAFT = False
KEY_FIELDS = ('id', 'entry_index')          # main() adds 'source' for the SP corpus (terrain names have no id)


def entry_key(e):
    if not isinstance(e, dict): return None
    return next((e[k] for k in KEY_FIELDS if k in e), None)


def strip_meta(doc):
    """The Traditional document as the build sees it (metadata removed)."""
    if isinstance(doc, dict):
        return {k: strip_meta(v) for k, v in doc.items() if k not in META and k != 'zh_hant_meta'}
    if isinstance(doc, list):
        return [strip_meta(v) for v in doc]
    return doc


def sync_document(sc: dict, tc: dict | None, drafter: Drafter, rel: str, report: dict):
    out = _sync_document(sc, tc, drafter, rel, report)
    if isinstance(out, dict) and isinstance(sc, dict) and sc.get('language') == 'zh-Hans':
        out['language'] = 'zh-Hant'                 # the document's own tag; the build checks it (srwz.build_language)
    return out


def _sync_document(sc: dict, tc: dict | None, drafter: Drafter, rel: str, report: dict):
    if isinstance(sc, dict) and isinstance(sc.get('entries'), list):
        old = {entry_key(e): e for e in (tc or {}).get('entries', []) if entry_key(e) is not None}
        head = drafter.value({k: v for k, v in sc.items() if k != 'entries'})
        # Render outputs locked to the Traditional pixels (output_*: written by tools/zh_hant/author_*.py) belong
        # to the Traditional document; a redraft of the header keeps them.
        head.update({k: v for k, v in (tc or {}).items() if k.startswith('output_') and k in head})
        entries = []
        for e in sc['entries']:
            key, want = entry_key(e), sha(translation_view(e))
            prev = old.pop(key, None)
            if prev is None:
                new = drafter.value(e); new.update(zh_hans_sha256=want, zh_hant_status='draft')
                report['drafted' if key is not None else 'unkeyed_drafted'] += 1
            elif prev.get('zh_hans_sha256') == want and not (REDRAFT and prev.get('zh_hant_status', 'draft') == 'draft'):
                new = prev; report['kept'] += 1
            elif prev.get('zh_hant_status', 'draft') == 'draft':
                new = drafter.value(e); new.update(zh_hans_sha256=want, zh_hant_status='draft'); report['redrafted'] += 1
            else:
                new = prev; report['stale'].append({'file': rel, 'id': key, 'status': prev.get('zh_hant_status')})
            if new.get('zh_hant_status') not in STATUSES: raise SystemExit(f'{rel} {key}: bad zh_hant_status')
            entries.append(new)
        report['removed'] += len(old)
        return {**head, 'entries': entries}
    want = sha(translation_view(sc) if isinstance(sc, dict) else sc)
    meta = (tc or {}).get('zh_hant_meta') if isinstance(tc, dict) else None
    if meta and meta.get('zh_hans_sha256') == want:
        report['kept'] += 1; return tc
    if meta and meta.get('zh_hant_status', 'draft') != 'draft':
        report['stale'].append({'file': rel, 'id': None, 'status': meta.get('zh_hant_status')}); return tc
    out = drafter.value(sc)
    if isinstance(out, dict):
        out['zh_hant_meta'] = {'zh_hans_sha256': want, 'zh_hant_status': 'draft'}
    report['drafted' if not meta else 'redrafted'] += 1
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--check', action='store_true')
    p.add_argument('--redraft', action='store_true', help='re-draft every entry still in draft status (drafter rules changed)')
    p.add_argument('--bootstrap', type=Path, default=ROOT / 'config/zh-hant/bootstrap.json')
    a = p.parse_args()
    global REDRAFT
    REDRAFT = a.redraft
    drafter = Drafter(a.bootstrap)
    report = {'drafted': 0, 'unkeyed_drafted': 0, 'redrafted': 0, 'kept': 0, 'removed': 0, 'stale': [], 'files_written': 0}
    for src_root, dst_root, excluded in TREES:
        src, dst = ROOT / src_root, ROOT / dst_root
        wanted = set()
        for f in sorted(src.rglob('*.json')):
            rel = f.relative_to(src)
            if rel.parts[0] in excluded: continue
            wanted.add(rel)
            global KEY_FIELDS
            sp = rel.parts[0] == SP_TREE and src_root == 'corpus/zh'
            # review_history keeps earlier translations, which the font allocator also reads: draft them as well
            drafter.frozen = (FROZEN_KEYS - {'review_history'}) | SP_FROZEN if sp else FROZEN_KEYS
            KEY_FIELDS = ('id', 'entry_index', 'source') if sp else ('id', 'entry_index')
            sc = json.loads(f.read_text(encoding='utf-8'))
            target = dst / rel
            tc = json.loads(target.read_text(encoding='utf-8')) if target.exists() else None
            out = sync_document(sc, tc, drafter, f'{dst_root}/{rel}', report)
            # Taiwan vocabulary (config/zh-hant/regional-terms.json) on every entry, whatever its status; idempotent
            out = regional_terms.apply_doc(sc, out, 'tw', drafter.frozen, KEY_FIELDS, report.setdefault('regional', {}),
                                          fixed=regional_terms.length_bound(f'{dst_root}/{rel}'))
            text = json.dumps(out, ensure_ascii=False, indent=2) + '\n'
            if not target.exists() or target.read_text(encoding='utf-8') != text:
                report['files_written'] += 1
                if not a.check:
                    target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text, encoding='utf-8')
        for f in sorted(dst.rglob('*.json')) if dst.exists() else []:
            if f.relative_to(dst) not in wanted:
                report.setdefault('orphans', []).append(str(f.relative_to(ROOT)))
    out = ROOT / 'build/zh-hant/sync-report.json'; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}, ensure_ascii=False))
    if a.check and (report['files_written'] or report['stale'] or report.get('orphans')):
        sys.exit(1)


if __name__ == '__main__':
    main()
