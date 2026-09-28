#!/usr/bin/env python3
"""Audit and store SP dialogue formatting using its verified native bindings."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.chinese_layout import (
    FORBIDDEN_LINE_END_CHARACTERS, FORBIDDEN_LINE_START_CHARACTERS,
    fit_chinese_dialogue_layout, load_layout_profiles, logical_dialogue_text,
    reflow_chinese_dialogue, dialogue_layout_issues,
)
from srwz.text import normalize_original_fullwidth_ascii
from text_layout.rebalance_story_dialogue import normalize_indent

STRUCTURAL = re.compile(r'\$[A-Za-z]|%[-+0-9.*]*[sduxf]|<<[^<>]*>>|<[^<>]*>|\{[^{}]*\}|＜ｔｍ＞.*?＜／ｔｍ＞', re.S)
NUMBER = re.compile(r'[0-9]+(?::[0-9]{2}|\.[0-9]+)?(?:亿[0-9]*)?(?:万[0-9]*)?(?:千[0-9]*)?(?:年|个月|月|天|小时|分钟|秒|人|架|台|艘|倍|公里|米|%|％)?')
OWNED = ('corpus/zh/special-disc/', 'config/editorial/special-disc/')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line_edge_issues(text):
    lines = text.split('\n')
    return (['closing_punctuation_at_line_start'] if any(
        line.lstrip('　 ') and line.lstrip('　 ')[0] in FORBIDDEN_LINE_START_CHARACTERS
        for line in lines[1:]
    ) else []) + (['opening_punctuation_at_line_end'] if any(
        line and line[-1] in FORBIDDEN_LINE_END_CHARACTERS for line in lines[:-1]
    ) else [])


def profile_for(text, profile):
    terms = tuple(dict.fromkeys(NUMBER.findall(logical_dialogue_text(text))))
    return replace(profile, unbroken_terms=(*profile.unbroken_terms, *terms))


def visible_ascii_identity(text):
    """Keep the complete spelling of runtime format tokens intact."""
    parts, cursor = [], 0
    for match in STRUCTURAL.finditer(text):
        parts.extend((normalize_original_fullwidth_ascii(text[cursor:match.start()]), match.group()))
        cursor = match.end()
    parts.append(normalize_original_fullwidth_ascii(text[cursor:]))
    return ''.join(parts)


def ending_mark(text):
    if not (text.startswith('“') and text.endswith('”')):
        return ''
    body = text[1:-1]
    if not body or body[-1] in '。！？!?…〜～~—”’）)]》>' or not re.search(r'[\u3400-\u9fff]$', body):
        return ''
    return '？' if body.endswith(('吗', '么')) else '。'


def normalize_dialogue(text, profile):
    canonical = visible_ascii_identity(text)
    reasons = ['fullwidth_ascii_identity'] if canonical != text else []
    mark = ending_mark(canonical)
    if mark:
        canonical = canonical[:-1] + mark + '”'
        reasons.append('ending_punctuation')
    effective = profile_for(canonical, profile)
    indented = normalize_indent(canonical, profile.continuation_indent)
    if indented != canonical:
        reasons.append('continuation_indent')
    issues = [*dialogue_layout_issues(indented, profile=effective), *line_edge_issues(indented)]
    result = (reflow_chinese_dialogue(indented, profile=effective) if issues
              else fit_chinese_dialogue_layout(indented, profile=effective))
    remaining = [*dialogue_layout_issues(result.text, profile=effective), *line_edge_issues(result.text)]
    if remaining:
        raise ValueError('; '.join(remaining))
    if logical_dialogue_text(result.text) != logical_dialogue_text(canonical):
        raise ValueError('layout changed logical text')
    if STRUCTURAL.findall(text) != STRUCTURAL.findall(result.text):
        raise ValueError('runtime tokens changed')
    if result.text != indented:
        repairs = any('line break inside' in issue or 'indent' in issue or 'punctuation' in issue for issue in issues)
        reasons.append('repair_layout' if repairs else 'store_generated_layout')
    return result.text, reasons, issues


def normalize_battle(text):
    result = visible_ascii_identity(text)
    reasons = ['fullwidth_ascii_identity'] if result != text else []
    mark = ending_mark(result)
    if mark:
        result = result[:-1] + mark + '”'
        reasons.append('ending_punctuation')
    if len(result.split('\\n')) != len(text.split('\\n')) or STRUCTURAL.findall(result) != STRUCTURAL.findall(text):
        raise ValueError('battle controls or line count changed')
    if any(len(line.strip('“”　')) > 20 for line in result.split('\\n')):
        raise ValueError('battle subtitle exceeds 20 cells')
    if re.search(r'\\n(?!　)', result):
        raise ValueError('battle continuation lacks fullwidth indent')
    return result, reasons


def run(*, apply=False, batch_id='sp-format-layout-20260928'):
    receipt_path = ROOT / 'manifests/editions/sp/current.json'
    receipt = read(receipt_path)
    proof_path = ROOT / receipt['readback']['path']
    if sha(proof_path) != receipt['readback']['sha256']:
        raise ValueError('SP receipt drift')
    proof = read(proof_path)
    component = next(p for p in proof['components'] if p.endswith('/stage/report.json'))
    stage_path = ROOT / receipt['workspace'] / component
    if sha(stage_path) != proof['components'][component]:
        raise ValueError('SP stage component drift')
    bindings = [r for c in read(stage_path)['chunk_reports'] for r in c['bindings'] if r.get('layout') == 'story_dialogue']
    profile = replace(load_layout_profiles(ROOT / 'config/text-layout/zh-layout-profiles.json')['story_dialogue'], default_advance_px=22)
    documents, rows, references = {}, {}, defaultdict(list)
    for b in bindings:
        key = b['corpus'], b['corpus_id']
        if b['corpus'] not in documents:
            documents[b['corpus']] = read(ROOT / b['corpus'])
            rows[b['corpus']] = {e['id']: e for e in documents[b['corpus']]['entries']}
        row = rows[b['corpus']][b['corpus_id']]
        if row['source_text_sha256'] != b['source_text_sha256']:
            raise ValueError('native source identity drift: ' + b['target'])
        references[key].append(b['target'])
    changes, failures, preserved, borrowed = [], [], [], []
    for (path, id_), targets in references.items():
        row = rows[path][id_]
        before = row['translation']
        if '＜ｔｍ＞' in before:
            preserved.append(dict(path=path, id=id_, targets=targets, reason='runtime template markup requires a separate renderer-width contract', translation=before))
            continue
        try:
            after, reasons, issues = normalize_dialogue(before, profile)
        except (ValueError, AssertionError) as error:
            failures.append(dict(path=path, id=id_, reason=str(error)))
            continue
        if not path.startswith(OWNED):
            borrowed.append(dict(path=path, id=id_, targets=targets, layout_issues=issues))
            continue
        if after != before:
            changes.append(dict(path=path, id=id_, targets=targets, source_text_sha256=row['source_text_sha256'], before=before, after=after, reasons=reasons, layout_issues_before=issues))
            row['translation'] = after
        if re.fullmatch('“?…+”?', before) and before.count('…') > 3:
            preserved.append(dict(path=path, id=id_, reason='source-bound long silence', source=row.get('source_text'), translation=after))
    battle_path = 'corpus/zh/special-disc/battle-lines.json'
    documents[battle_path] = read(ROOT / battle_path)
    for row in documents[battle_path]['entries']:
        before = row['translation']
        try:
            after, reasons = normalize_battle(before)
        except ValueError as error:
            failures.append(dict(path=battle_path, id=row['id'], reason=str(error)))
            continue
        if after != before:
            changes.append(dict(path=battle_path, id=row['id'], source_text_sha256=row['source_text_sha256'], before=before, after=after, reasons=reasons))
            row['translation'] = after
    result = dict(schema_version=1, batch_id=batch_id, status='failed' if failures else 'audit_passed', applied=apply,
                  policy='Use the verified SP native dialogue owners and current main layout profile; retain scene/title/condition layouts, wave marks, runtime tokens, identifier values, battle line counts and source-bound silences.',
                  counts=dict(native_dialogue_bindings=len(bindings),unique_dialogue_owners=len(references),battle_entries=len(documents[battle_path]['entries']),changed=len(changes),reasons=dict(Counter(reason for c in changes for reason in c['reasons']))),
                  changes=changes, failures=failures, preserved=preserved, borrowed_main_owners=borrowed,
                  profile_sha256=sha(ROOT/'config/text-layout/zh-layout-profiles.json'),words_sha256=sha(ROOT/'config/text-layout/zh-story-unbroken-words.json'))
    if apply and changes and not failures:
        paths = {c['path'] for c in changes}
        for path in sorted(paths):
            indent = len(re.search(r'\n( +)"', (ROOT/path).read_text()).group(1))
            (ROOT/path).write_text(json.dumps(documents[path], ensure_ascii=False, indent=indent)+'\n')
        locks_path = ROOT/'config/editions/sp/inputs.json'
        locks = read(locks_path)
        for lock in locks['files']:
            if lock['path'] in paths:
                lock.update(size=(ROOT/lock['path']).stat().st_size, sha256=sha(ROOT/lock['path']))
        locks_path.write_text(json.dumps(locks, ensure_ascii=False, indent=2)+'\n')
        (ROOT/'config/editorial/special-disc'/f'{batch_id}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    output = ROOT/'work/reviews'/batch_id
    output.mkdir(parents=True, exist_ok=True)
    (output/('apply.json' if apply else 'audit.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','counts','failures','preserved')}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--batch-id', default='sp-format-layout-20260928')
    args = parser.parse_args()
    raise SystemExit(run(apply=args.apply, batch_id=args.batch_id))
