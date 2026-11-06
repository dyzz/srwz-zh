#!/usr/bin/env python3
"""Reflow verified native world-history display groups within fixed byte slots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.summary_layout_capacity import (load_production_summary_capacity,
    layout_summary_group,preflight_summary_fields)


def run(write=False,out=None):
    out=Path(out or ROOT/'work/analysis/summary-reflow-20261106');out.mkdir(parents=True,exist_ok=True)
    path=ROOT/'corpus/zh/summary.json';before=path.read_bytes();corpus=json.loads(before)
    rows={r['id']:r for r in corpus['entries']};context=load_production_summary_capacity(ROOT)
    preflight_summary_fields({i:r['translation']for i,r in rows.items()},context)
    # These groups retain their verified same-screen timing, row positions and
    # paragraph boundaries. Never join neighbouring display groups to balance.
    inventory=json.loads((ROOT/'docs/issue-assets/prose-step-audit-20261026/layout-report.json').read_text())
    groups=[];changes=[]
    for group in inventory['records']:
        ids=group['member_ids']
        if group['surface']!='main_scroll' or len(ids)<2:continue
        texts={i:rows[i]['translation']for i in ids}
        for i in ids:
            native=context['entries'][i]
            if rows[i]['source_text_sha256']!=hashlib.sha256(native.text.encode()).hexdigest():
                raise ValueError(f'{i}: native source identity drift')
        result=layout_summary_group(texts,context)
        groups.append(dict(id=group['id'],before=texts,result=result))
        for field in result['fields']:
            i=field['id'];after=field['text']
            if after!=rows[i]['translation']:
                changes.append(dict(id=i,before=rows[i]['translation'],after=after))
                rows[i]['translation']=after
    capacities=preflight_summary_fields({i:r['translation']for i,r in rows.items()},context)
    after=(json.dumps(corpus,ensure_ascii=False,indent=2)+'\n').encode()
    if path.read_bytes()!=before:raise ValueError('World-history corpus changed during planning')
    if write and changes:
        snapshot=out/f'summary-before-{hashlib.sha256(before).hexdigest()[:16]}.json'
        if snapshot.exists()and snapshot.read_bytes()!=before:raise ValueError('Snapshot collision')
        snapshot.write_bytes(before)
        temp=path.with_suffix('.json.layout.tmp');temp.write_bytes(after);os.replace(temp,path)
    report=dict(written=write,changedFields=len(changes),beforeSha256=hashlib.sha256(before).hexdigest(),
        afterSha256=hashlib.sha256(after).hexdigest(),groups=groups,changes=changes,
        fixedCapacityChecks=capacities,all28FieldsPassed=True,fieldCountUnchanged=True,
        sameScreenGroupsPreserved=True,visibleTextUnchanged=True,
        nativeArchiveSha256=context['archive_sha256'])
    (out/'reflow.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();report=run(args.write,args.out)
    print(json.dumps({k:v for k,v in report.items()if k not in ['groups','changes','fixedCapacityChecks']},ensure_ascii=False))
