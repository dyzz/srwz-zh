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

Every language's text is static and maintained by hand: nothing here drafts or converts. Check, per entry:
    missing     a Simplified entry, field or file the regional tree lacks
    stale       the Simplified entry changed since the regional one was written (follow it by hand, then set
                zh_hans_sha256: tools/zh_hant/port_sc_changes.py lists them with the old and new Simplified text)
    orphan      a regional file with no Simplified counterpart
for Taiwan (corpus/*-zh-hant) and Hong Kong (corpus/*-zh-hant-hk).

Usage: sync_corpus.py [--check]    (report; exit 1 when anything is missing, stale or orphaned)
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


def translation_view(entry: dict) -> dict:
    """The part of a Simplified entry a Traditional entry is written against (no JP source, no notes)."""
    return {k: v for k, v in entry.items() if k not in FROZEN_KEYS and not k.endswith('_sha256') and k not in META}


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


def hk_skips(src_root: str, rel) -> bool:
    """corpus/zh files Hong Kong takes from Taiwan (config/zh-hant/hk-uses-taiwan.json): no Hong Kong copy."""
    if src_root != 'corpus/zh':
        return False
    path = ROOT / 'config/zh-hant/hk-uses-taiwan.json'
    return path.exists() and str(rel) in json.loads(path.read_text(encoding='utf-8'))['files']


def stale_entries(region: str) -> list[dict]:
    """Regional entries whose Simplified entry changed since they were written (no OpenCC needed)."""
    global KEY_FIELDS
    out = []
    for src_root, dst_root, excluded in TREES:
        dst_root = dst_root + ('-hk' if region == 'hk' else '')
        for f in sorted((ROOT / src_root).rglob('*.json')):
            rel = f.relative_to(ROOT / src_root)
            target = ROOT / dst_root / rel
            if rel.parts[0] in excluded or not target.exists() or (region == 'hk' and hk_skips(src_root, rel)):
                continue
            KEY_FIELDS = ('id', 'entry_index', 'source') if rel.parts[0] == SP_TREE and src_root == 'corpus/zh' else ('id', 'entry_index')
            src = json.loads(f.read_text(encoding='utf-8')); tc = json.loads(target.read_text(encoding='utf-8'))
            if isinstance(src, dict) and isinstance(src.get('entries'), list):
                by = {json.dumps(entry_key(e), ensure_ascii=False): e for e in src['entries'] if entry_key(e) is not None}
                for e in tc.get('entries', []):
                    k = entry_key(e); s_e = by.get(json.dumps(k, ensure_ascii=False))
                    if s_e is not None and e.get('zh_hans_sha256') != sha(translation_view(s_e)):
                        out.append({'file': f'{dst_root}/{rel}', 'id': k, 'status': e.get('zh_hant_status')})
            else:
                meta = tc.get('zh_hant_meta') if isinstance(tc, dict) else None
                if meta and meta.get('zh_hans_sha256') != sha(translation_view(src) if isinstance(src, dict) else src):
                    out.append({'file': f'{dst_root}/{rel}', 'id': None, 'status': meta.get('zh_hant_status')})
    return out


def missing_values(region: str) -> list[str]:
    """Regional files that lack a file, record or field Simplified has (fill_corpora.fill finds them)."""
    import fill_corpora
    global KEY_FIELDS
    out = []
    for src_root, dst_root, excluded in TREES:
        dst_root = dst_root + ('-hk' if region == 'hk' else '')
        for f in sorted((ROOT / src_root).rglob('*.json')):
            rel = f.relative_to(ROOT / src_root)
            if rel.parts[0] in excluded or (region == 'hk' and hk_skips(src_root, rel)): continue
            target = ROOT / dst_root / rel
            if not target.exists():
                out.append(f'{dst_root}/{rel} (file missing)'); continue
            sp = rel.parts[0] == SP_TREE and src_root == 'corpus/zh'
            keys = ('id', 'entry_index', 'source') if sp else ('id', 'entry_index')
            old = json.loads(target.read_text(encoding='utf-8'))
            if fill_corpora.fill(json.loads(f.read_text(encoding='utf-8')), old, keys=keys) != old:
                out.append(f'{dst_root}/{rel}')
    return out


def orphans(region: str) -> list[str]:
    out = []
    for src_root, dst_root, excluded in TREES:
        dst = ROOT / (dst_root + ('-hk' if region == 'hk' else ''))
        for f in sorted(dst.rglob('*.json')) if dst.exists() else []:
            if not (ROOT / src_root / f.relative_to(dst)).exists():
                out.append(str(f.relative_to(ROOT)))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--check', action='store_true', help='kept for compatibility: the tool only ever checks')
    p.parse_args()
    report = {}
    for region in ('tw', 'hk'):
        report[f'missing_{region}'] = missing_values(region)
        report[f'stale_{region}'] = stale_entries(region)
        report[f'orphans_{region}'] = orphans(region)
    report['stale'] = report['stale_tw']               # older readers
    out = ROOT / 'build/zh-hant/sync-report.json'; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: len(v) for k, v in report.items() if k != 'stale'}, ensure_ascii=False))
    if any(v for k, v in report.items() if k != 'stale'):
        sys.exit(1)


if __name__ == '__main__':
    main()
