#!/usr/bin/env python3
"""List the Taiwan / Hong Kong entries whose Simplified entry changed since they were written, for hand updates.

Every language's text is static and maintained by hand; nothing here drafts. For each stale regional entry
(sync_corpus.stale_entries) the report shows the Simplified text it was written against (looked up in git
history), the new Simplified text and the current regional text. After updating the regional text by hand, accept
the entry: its zh_hans_sha256 becomes the new Simplified hash.

Usage: port_sc_changes.py [--region tw|hk]                          report: build/zh-hant/port-sc-changes.json
       port_sc_changes.py --region tw --accept FILE#ID [FILE#ID ...]  (FILE as in the report, ID its JSON id)
       port_sc_changes.py --region tw --accept-all                    every listed entry, after reviewing them all
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / 'tools')]
import sync_corpus as sc  # noqa: E402


def history(rel: str, wanted: set[str], keys: tuple) -> dict:
    """sha(translation_view) -> Simplified entry, from the index, HEAD and earlier commits of the file."""
    found = {}
    revs = [':'] + subprocess.run(['git', 'log', '--format=%H', '-n', '80', '--', rel], cwd=ROOT,
                                  capture_output=True, text=True).stdout.split()
    for rev in revs:
        out = subprocess.run(['git', 'show', f':{rel}' if rev == ':' else f'{rev}:{rel}'], cwd=ROOT,
                             capture_output=True, text=True)
        if out.returncode:
            continue
        sc.KEY_FIELDS = keys
        for e in json.loads(out.stdout).get('entries', []):
            h = sc.sha(sc.translation_view(e))
            if h in wanted and h not in found:
                found[h] = e
        if wanted <= set(found):
            break
    return found


def source_of(target_rel: str) -> tuple[str, tuple]:
    tree, rel = target_rel.split('/', 2)[1], target_rel.split('/', 2)[2]
    root = {'zh-hant': 'corpus/zh', 'glossary-zh-hant': 'corpus/glossary', 'runtime-zh-hant': 'corpus/runtime'}[tree.removesuffix('-hk')]
    sp = rel.split('/')[0] == sc.SP_TREE and root == 'corpus/zh'
    return f'{root}/{rel}', (('id', 'entry_index', 'source') if sp else ('id', 'entry_index'))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--region', choices=('tw', 'hk'), action='append')
    p.add_argument('--accept', nargs='+', default=[], help='FILE#ID entries updated by hand')
    p.add_argument('--accept-all', action='store_true')
    a = p.parse_args()
    report, accepted = [], 0
    for region in a.region or ['tw', 'hk']:
        by_file: dict[str, list] = {}
        for s in sc.stale_entries(region):
            by_file.setdefault(s['file'], []).append(s['id'])
        for target_rel, ids in sorted(by_file.items()):
            sc_rel, keys = source_of(target_rel)
            sc.KEY_FIELDS = keys
            sc_doc = json.loads((ROOT / sc_rel).read_text(encoding='utf-8'))
            if not isinstance(sc_doc, dict) or not isinstance(sc_doc.get('entries'), list):
                report.append(dict(region=region, file=target_rel, id=None, note='document without entries changed in Simplified'))
                continue
            new_sc = {json.dumps(sc.entry_key(e), ensure_ascii=False): e for e in sc_doc['entries']}
            doc = json.loads((ROOT / target_rel).read_text(encoding='utf-8'))
            wanted = {e['zh_hans_sha256'] for e in doc['entries'] if e.get('zh_hans_sha256') and sc.entry_key(e) in ids}
            old_sc = history(sc_rel, wanted, keys)
            sc.KEY_FIELDS = keys
            changed = False
            for e in doc['entries']:
                k = sc.entry_key(e)
                if k not in ids:
                    continue
                n_sc = new_sc[json.dumps(k, ensure_ascii=False)]
                tag = f'{target_rel}#{json.dumps(k, ensure_ascii=False)}'
                if a.accept_all or tag in a.accept or f'{target_rel}#{k}' in a.accept:
                    e['zh_hans_sha256'] = sc.sha(sc.translation_view(n_sc)); changed = True; accepted += 1
                    continue
                report.append(dict(region=region, file=target_rel, id=k, status=e.get('zh_hant_status'),
                                   sc_old=(old_sc.get(e.get('zh_hans_sha256')) or {}).get('translation'),
                                   sc_new=n_sc.get('translation'), regional=e.get('translation')))
            if changed:
                (ROOT / target_rel).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    out = ROOT / 'build/zh-hant/port-sc-changes.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{len(report)} stale regional entries to update by hand; {accepted} accepted;', out.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
