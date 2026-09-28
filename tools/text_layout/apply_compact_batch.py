#!/usr/bin/env python3
"""Plan/apply surface-scoped compact text from the confirmed local inventory."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.compact_authoring import compact_controlled_text, unscoped_text
from srwz.chinese_layout import (load_layout_profiles, logical_dialogue_text,
    fit_chinese_dialogue_layout, reflow_chinese_dialogue, dialogue_layout_issues)
from srwz.text import normalize_original_fullwidth_ascii
from build_local_decisions import resolve

BASE = ROOT / 'work/reviews/compact-inventory-20260928'
STAGE_GROUPS = {'main_dialogue', 'main_system_dialogue', 'sp_stage_source'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(output: Path, *, apply: bool):
    scope = json.loads((BASE / 'confirmed-scope/work-scope.json').read_text())
    decisions = json.loads((ROOT / 'config/text-layout/compact-special-decisions-20260928.json').read_text())
    chosen = {(r['path'], r['json_pointer']):r for r in decisions['records']}
    profile = load_layout_profiles(ROOT / 'config/text-layout/zh-layout-profiles.json')['story_dialogue']
    documents = {}; originals = {}; plan = []; changes = []; counts = Counter()
    for record in scope['records']:
        if 'compact' not in record['queues']:
            continue
        path, pointer = record['path'], record['json_pointer']
        if path not in documents:
            originals[path] = (ROOT / path).read_bytes()
            documents[path] = json.loads(originals[path])
        before = resolve(documents[path], pointer)
        decision = chosen.get((path, pointer))
        item = dict(record, before_sha256=sha(before.encode()))
        if decision and decision['decision'] == 'keep':
            item['outcome'] = 'user_keep'
        elif record['group'] not in STAGE_GROUPS:
            item['outcome'] = 'other_consumer'
        else:
            parent = resolve(documents[path], pointer.rsplit('/',1)[0])
            if parent.get('kind') in {'scene_label', 'location_caption'}:
                item['outcome'] = 'other_consumer'
                plan.append(item); counts[item['outcome']] += 1
                continue
            text = before.replace('\\n', '\n')
            spans = None
            if decision:
                if text != decision['display_text'] or sha(before.encode()) != decision['source_sha256']:
                    raise ValueError(f'Confirmed text drift: {path}:{pointer}')
                spans = decision['spans']
            after = compact_controlled_text(text, default_width=22, spans=spans,
                                           keyword_links=record['group']=='main_dialogue')
            if record['group'] in {'main_dialogue','sp_stage_source'}:
                keyword_links = record['group']=='main_dialogue' and '《' in parent.get('source_text','')
                fitted = fit_chinese_dialogue_layout(after, profile=profile, stage_keyword_links=keyword_links)
                after = fitted.text
                if dialogue_layout_issues(after, profile=profile, stage_keyword_links=keyword_links):
                    after = reflow_chinese_dialogue(after, profile=profile, stage_keyword_links=keyword_links).text
                issues = dialogue_layout_issues(after, profile=profile, stage_keyword_links=keyword_links)
                if issues:
                    raise ValueError(f'Layout not final: {record["id"]}: {issues}')
            clean=lambda t:normalize_original_fullwidth_ascii(logical_dialogue_text(unscoped_text(t)))
            if clean(text) != clean(after):
                raise ValueError(f'Logical text/control drift: {record["id"]}')
            item['outcome'] = 'changed' if before != after else 'already_applied'
            if before != after:
                parent['translation'] = after
                changes.append(dict(path=path,id=record['id'],json_pointer=pointer,group=record['group'],
                                    before=before,after=after,after_sha256=sha(after.encode())))
        plan.append(item); counts[item['outcome']] += 1
    refs = {}
    for path in sorted({r['path'] for r in changes}):
        data = (json.dumps(documents[path],ensure_ascii=False,indent=2)+'\n').encode()
        snapshot = BASE / 'compact-execution/before' / path
        if apply:
            snapshot.parent.mkdir(parents=True,exist_ok=True)
            if snapshot.exists() and snapshot.read_bytes()!=originals[path]:
                raise ValueError(f'Snapshot collision: {path}')
        refs[path] = dict(before_sha256=sha(originals[path]),after_sha256=sha(data),snapshot=str(snapshot.relative_to(ROOT)))
    if apply:
        for path,ref in refs.items():
            (ROOT / ref['snapshot']).write_bytes(originals[path])
        for path in refs:
            (ROOT/path).write_text(json.dumps(documents[path],ensure_ascii=False,indent=2)+'\n')
    result = dict(schema_version=1,applied=apply,publication='local_only',scope='stage_dialogue',
                  counts=dict(counts),sources=refs,changes=changes,records=plan)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return dict(counts=dict(counts),files=len(refs),output=str(output.relative_to(ROOT)))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.output.resolve(),apply=a.apply),ensure_ascii=False))
