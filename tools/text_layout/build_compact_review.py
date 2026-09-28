#!/usr/bin/env python3
"""Build a local, source-backed compact-text and prose review page."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.text import CONTROL_NOTATION


def resolve(document, pointer):
    for part in pointer.lstrip('/').split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        document = document[int(key)] if isinstance(document, list) else document[key]
    return document


def build(inventory_path: Path, preview_path: Path, output: Path):
    inventory = json.loads(inventory_path.read_text())
    preview = json.loads(preview_path.read_text())
    documents = {}
    queues = {}
    for queue, records in [('compact', inventory['records']),
                           ('symbols', inventory['symbol_review_records']),
                           ('dynamic', inventory['dynamic_records'])]:
        queues[queue] = []
        for record in records:
            path = record['path']
            if path not in documents:
                documents[path] = json.loads((ROOT / path).read_text())
            text = resolve(documents[path], record['json_pointer']).replace('\\n', '\n')
            queues[queue].append(dict(record, text=text,
                editions=record.get('editions', ['sp'] if '/special-disc/' in path else
                    ['original', 'best', 'sp'] if '/library/' in path else ['original', 'best']),
                group=record.get('group', path.rsplit('/', 1)[0])))
    originals = {(r['path'], r['id']): r['before'] for r in preview['records'] if 'before' in r}
    queues['prose'] = [dict(r, text=CONTROL_NOTATION.sub('', r.get('after', r.get('before', ''))),
        editions=['sp'] if r['surface'].startswith('sp_') else
            ['original', 'best', 'sp'] if r['surface'].startswith('library_') else ['original', 'best'],
        group=r['surface'], status='blocked' if r.get('error') else 'changed' if r['changed'] else 'unchanged',
        before=CONTROL_NOTATION.sub('', r.get('before', originals.get((r['path'], r['id']), ''))),
        after=CONTROL_NOTATION.sub('', r.get('after', ''))) for r in preview['records']]
    for record in queues['prose']:
        if not record.get('error'):
            continue
        record['diagnostic'] = record['error']
        if record['id'] == 'library-text/2755c95ab9cf91f5':
            record['error'] = '英文全称连同左引号为 540 px，超过 528 px 行宽。需明确在词间分段，并闭合／重开窄距标签。'
        elif record['id'] == 'library-text/c5c3bc8563abe5e6':
            record['error'] = '英文全称整段为 530 px，超过 528 px 行宽。需明确词间分段，或另选可读参数。'
        elif match := re.fullmatch(r'prose exceeds (\d+) physical rows: (\d+)', record['error']):
            record['error'] = f'新排版需要 {match[2]} 行，当前预算为 {match[1]} 行。需单独调整分行并核对滚动时序。'
    data = json.dumps(dict(queues=queues, count=inventory['candidate_owners'],
        runs=inventory['eligible_runs']), ensure_ascii=False).replace('</', '<\\/')
    template = (ROOT / 'tools/text_layout/compact-review.html').read_text()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace('__REVIEW_DATA__', data))
    return {k: len(v) for k, v in queues.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--preview', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.inventory, args.preview, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
