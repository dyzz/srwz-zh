#!/usr/bin/env python3
"""Read-only editorial audit. Compare identifiable authored translation fields across the three corpora.

Run with the project interpreter. Use --baseline PREVIOUS.json to label new or changed
findings. The report contains observed text and review candidates, never writeback instructions.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import unicodedata

from sync_corpus import FROZEN_KEYS, ROOT, SP_FROZEN, TM_SCOPE, TREES

sys.path.insert(0, str(ROOT / 'tools/editorial_review'))
from japanese_sources import resolve_all

CONFIG = ROOT / 'config/zh-hant'
# Common simplified glyphs to review. Proper names can legitimately contain them. Characters like 后, 干, 里 and 台 need context.
SIMPLIFIED = frozenset('这们为发国过还来对说话让给从机战舰体动弹觉见长门间开关进击军队员时点实变现与阵强敌标线图场头铁风击转响资档储话车龙达传备领处导续级压试确伤厉样剑飞认')
CONFUSIONS = {'幹涉': '干涉', '乾涉': '干涉', '幹擾': '干擾', '乾擾': '干擾',
              '幹脆': '乾脆', '新發型': '新髮型', '恢複': '恢復', '迫不急待': '迫不及待'}
CONTROL = re.compile(r'\$[A-Za-z]|\{\{[^{}]+\}\}|%[0-9]*[ds]')
BREAKS = re.compile(r'(?:\\n|\r?\n)[ 　]*')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def records(doc, path=(), japanese=None):
    """Key named list entries independently of ordering, keep indices for unnamed rows."""
    if isinstance(doc, list):
        seen = Counter()
        for i, row in enumerate(doc):
            key = i
            if isinstance(row, dict):
                for field in ('id', 'entry_index', 'page', 'source_text_sha256', 'source'):
                    if isinstance(row.get(field), (str, int)):
                        base = f'{field}={row[field]}'
                        seen[base] += 1
                        key = base if seen[base] == 1 else f'{base}#{seen[base]}'
                        break
            yield from records(row, path + (key,), japanese)
    elif isinstance(doc, dict):
        source = doc.get('source_text') or doc.get('japanese') or doc.get('source')
        terms = doc.get('source_terms', [])
        if isinstance(source, str):
            japanese = ('literal', source)
        elif isinstance(terms, list) and len(terms) == 1:
            japanese = ('literal', terms[0])
        elif 'source_text_sha256' in doc or 'id' in doc:
            japanese = ('lookup', doc.get('source_text_sha256'), doc.get('id'))
        for key, value in doc.items():
            if key in FROZEN_KEYS or key in SP_FROZEN or key in ('submitted_translation', 'baseline_translation'):
                continue
            if key == 'translation' and isinstance(value, str):
                yield path + (key,), (value, japanese)
            elif isinstance(value, (dict, list)):
                yield from records(value, path + (key,), japanese)


def index(file):
    rows = {}
    if file.exists():
        for key, value in records(load(file)):
            if key in rows:
                raise ValueError(f'Duplicate record: {file} {key}')
            rows[key] = value
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/zh-hant/editorial-audit.json')
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if args.baseline and args.baseline.resolve() == args.out.resolve():
        parser.error('save the current report separately from the baseline')
    def fingerprint(row):
        return tuple(row[k] for k in ('file', 'field', 'region', 'rule', 'match', 'expected',
                                      'ja', 'sc', 'tw', 'hk'))
    previous = {fingerprint(r) for r in load(args.baseline)['findings']} if args.baseline else set()
    by_sha, by_id = resolve_all()
    names = defaultdict(list)
    for r in load(CONFIG / 'regional-names.json')['names']:
        for jp in r['ja']:
            names[jp].append(r)
    terms = load(CONFIG / 'regional-terms.json')['rules']
    decisions = load(CONFIG / 'system-terms-20261120.json')['terms']
    # A settled compound (e.g. 生化感應器) takes precedence over a generic term.
    protected = {}
    for region in ('tw', 'hk'):
        accepted = {r[region]['to'] for r in decisions}
        accepted.update(r[region]['to'] for group in names.values() for r in group if r[region]['apply'])
        for rule in terms:
            for old in (rule['tw'], rule['hk'], rule['tc']):
                compounds = sorted((v for v in accepted if old in v and v != old), key=len, reverse=True)
                if compounds:
                    protected[region, old] = re.compile('|'.join(map(re.escape, compounds)))
    hk_glyphs = load(CONFIG / 'hk-characters.json')['map']
    findings = []
    coverage = Counter()
    for sc_root, tw_root, _ in TREES:
        roots = [ROOT / p for p in (sc_root, tw_root, tw_root + '-hk')]
        paths = sorted({f.relative_to(root) for root in roots for f in root.rglob('*.json')})
        for rel in paths:
            sc, tw, hk = [index(root / rel) for root in roots]
            for key in sorted(tw.keys() | hk.keys(), key=str):
                sc_text, source = sc.get(key, (None, None))
                texts = {loc: doc.get(key, (None, None))[0] for loc, doc in [('tw', tw), ('hk', hk)]}
                for region, doc in [('tw', tw), ('hk', hk)]:
                    if key not in doc:
                        continue
                    raw, regional_source = doc[key]
                    ref = regional_source or source
                    jp = None
                    if ref:
                        jp = ref[1] if ref[0] == 'literal' else by_sha.get(ref[1]) or by_id.get(ref[2])
                    coverage[region] += 1
                    if jp:
                        coverage[region + '_with_ja'] += 1
                    text = BREAKS.sub('', TM_SCOPE.sub('\0', raw))
                    def flag(rule, match, expected=''):
                        row = dict(file=str((roots[1 if region=='tw' else 2]/rel).relative_to(ROOT)),
                                   field='/'.join(map(str,key)), region=region, rule=rule, match=match,
                                   expected=expected, ja=jp, sc=sc_text, **texts)
                        if args.baseline:
                            row['new_or_changed'] = fingerprint(row) not in previous
                        findings.append(row)
                    for char in sorted(SIMPLIFIED.intersection(text)):
                        flag('simplified-glyph', char)
                    for word, good in CONFUSIONS.items():
                        if word in text:
                            flag('word-form', word, good)
                    if region == 'hk':
                        for char in sorted(hk_glyphs.keys() & set(text)):
                            flag('hk-house-form', char, hk_glyphs[char])
                    if sc_text is None:
                        continue
                    if Counter(TM_SCOPE.findall(raw)) != Counter(TM_SCOPE.findall(sc_text)):
                        flag('runtime-placeholder', ' '.join(TM_SCOPE.findall(raw)), ' '.join(TM_SCOPE.findall(sc_text)))
                    if Counter(CONTROL.findall(raw)) != Counter(CONTROL.findall(sc_text)):
                        flag('control-tokens', ' '.join(CONTROL.findall(raw)), ' '.join(CONTROL.findall(sc_text)))
                    simplified = BREAKS.sub('', sc_text)
                    for rule in terms:
                        if rule['sc'] not in simplified:
                            continue
                        if rule.get('jp') and not any(j in (jp or '') for j in rule['jp']):
                            continue
                        if any(j in (jp or '') for j in rule.get('jp_not', [])):
                            continue
                        target = rule[region]
                        other = rule['hk' if region == 'tw' else 'tw']
                        for old in sorted({other, rule['tc']} - {target}):
                            remaining = text.replace(target, '\0')
                            compounds = protected.get((region, old))
                            if compounds:
                                remaining = compounds.sub('\0', remaining)
                            if old and old in remaining:
                                flag('regional-term', old, target)
                    jp_normalized = unicodedata.normalize('NFKC', jp or '')
                    for decision in decisions:
                        if decision['sc'] not in simplified:
                            continue
                        if decision['decision'] == 'keep':
                            source_name = unicodedata.normalize('NFKC', decision['ja'])
                            expected = decision[region]['to']
                            if jp_normalized == source_name and simplified == decision['sc']:
                                if text != expected:
                                    flag('decided-system-term', text, expected)
                            elif (decision.get('check_named_mentions') and source_name in jp_normalized
                                  and text.count(expected) < simplified.count(decision['sc'])):
                                flag('decided-system-term', text, expected)
                            continue
                        forms = decision[region]
                        old, new = forms['from'], forms['to']
                        if old == new or old not in text:
                            continue
                        if decision['scope'] == 'everywhere' or (jp == decision['ja'] and old == text):
                            flag('decided-system-term', old, new)
                    # Only an entire Japanese name, matched to its Simplified equivalent.
                    # A line mentioning a character can legitimately use a nickname.
                    matches = {r[region]['to'] for r in names.get(jp, [])
                               if r[region]['apply'] and r['sc'] == simplified}
                    if len(matches) == 1 and text not in matches:
                        flag('approved-name', text, next(iter(matches)))
    counts = Counter(row['rule'] for row in findings)
    report = dict(scope='Translation fields in game, glossary and runtime corpora; Hong Kong shared images counted under Taiwan.',
                  coverage=dict(coverage), counts=dict(counts), findings=findings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(dict(coverage), dict(counts), args.out)


if __name__ == '__main__':
    main()
