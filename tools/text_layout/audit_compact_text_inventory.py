#!/usr/bin/env python3
"""Inventory compact-text work by source owner and renderer surface; no writeback."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.chinese_layout import logical_dialogue_text
from srwz.renderer_metrics import COMPACT_VISIBLE_RUN
from srwz.text import CONTROL_NOTATION,normalize_original_fullwidth_ascii

LEDGER='corpus/zh/special-disc/reviewed-non-stage-text.json'
SPECIAL_SYMBOLS=frozenset('−–—÷·∞√≤≥≠≒℃°′″Ωαβγδ＃#&＆')
AUTHORING_BOUNDARY=re.compile(CONTROL_NOTATION.pattern+r'|\\[nrt]')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def candidates(text: str) -> tuple[list[dict],list[str]]:
    """Controls are boundaries, never candidate letters/numbers themselves."""
    folded=normalize_original_fullwidth_ascii(text)
    spans=[]
    cursor=0
    chunks=[]
    for token in AUTHORING_BOUNDARY.finditer(folded):
        chunks.append((cursor,folded[cursor:token.start()]))
        cursor=token.end()
    chunks.append((cursor,folded[cursor:]))
    for start,chunk in chunks:
        for match in COMPACT_VISIBLE_RUN.finditer(chunk):
            run=match.group()
            if len(run)<3:
                continue
            at,end=start+match.start(),start+match.end()
            nearby=folded[max(0,at-1):min(len(folded),end+1)]
            pending=sorted(set(nearby)&SPECIAL_SYMBOLS)
            spans.append(dict(start=at,end=end,text=run,division_protected='÷' in run,
                adjacent_symbol_review=pending))
    return spans,sorted(set(folded)&SPECIAL_SYMBOLS)


def rows(document: dict):
    def walk(node,pointer=''):
        if isinstance(node,dict):
            if isinstance(node.get('translation'),str):
                yield node,pointer+'/translation'
            for key,value in node.items():
                if key=='translation':continue
                yield from walk(value,pointer+'/'+str(key).replace('~','~0').replace('/','~1'))
        elif isinstance(node,list):
            for index,value in enumerate(node):
                yield from walk(value,pointer+'/'+str(index))
    yield from walk(document)
    for index,segment in enumerate(document.get('segments',[])):
        first,last=segment['range']
        values=segment.get('translations',[])
        if len(values)!=last-first+1:
            raise ValueError('unit segment range/translation drift')
        for offset,text in enumerate(values):
            yield dict(id=f'display-name/unit/{first+offset:04d}/name',translation=text,
                editorial_status=segment.get('editorial_status')),f'/segments/{index}/translations/{offset}'
    for section,value in document.items():
        if section.startswith('accepted_') or section=='compdata_render_control_prefixes_by_offset':continue
        if not (section.endswith(('_by_offset','_by_source_text')) or section=='nisv_effect_names'):continue
        if not isinstance(value,dict):continue
        for key,text in value.items():
            if isinstance(text,str):
                pointer=f'/{section}/{str(key).replace("~","~0").replace("/","~1")}'
                yield dict(id=f'{section}/{key}',translation=text,section=section),pointer


def group(path: str,row: dict) -> str:
    if '/ui-atlas/' in path or row.get('section')=='atlas_by_source_text':return 'texture_labels'
    if '/story-dialogue/' in path:return 'main_dialogue'
    if path.endswith('story-system-dialogue.json'):return 'main_system_dialogue'
    if path.endswith('story-speakers.json'):return 'speaker_and_pilot_names'
    if path.endswith('story-conditions.json'):return 'main_conditions'
    if path.endswith('story-z-reports.json'):return 'main_z_reports'
    if path.endswith('story-tickers.json'):return 'horizontal_bazaar_tickers'
    if path.endswith('/summary.json'):return 'main_world_history_scroll'
    if '/battle/' in path or path.endswith('/battle-lines.json') and '/special-disc/' not in path:return 'main_battle_text'
    if '/display-names/' in path or path.endswith('/weapons.json') or row.get('section')=='display_names_by_source_text':return 'name_authoring_sources'
    if '/library/' in path:
        if set(row.get('tags',[]))&{'DSCR','DSC2'}:return 'library_body'
        return 'library_metadata'
    if path.endswith('/stage-overviews.json'):return 'main_flow_long'
    if path.endswith('/hsfc-overviews.json'):return 'main_flow_short'
    if path.endswith('/stage-names.json') or path.endswith('/chapter-intertitles.json'):return 'stage_and_chapter_titles'
    if path.endswith('/auto-demo-work-titles.json'):return 'work_titles'
    if '/special-disc/' in path:
        if path.endswith('/story-dialogue.json') or path.endswith('/challenge-dialogue.json'):return 'sp_stage_source'
        if path.endswith('/battle-lines.json'):return 'sp_battle_text'
        if path.endswith('/frame-text.json'):
            kind=row.get('kind')
            return {'synopsis':'sp_flow_long','chart_summary':'sp_flow_short','narration':'sp_narration_scroll',
                'vt1_page':'sp_fixed_pages','image_text':'texture_labels','episode_title':'sp_stage_titles',
                'condition':'sp_conditions','speaker':'sp_names','group_name':'sp_names','formation_name':'sp_names','map_name':'sp_names'}.get(kind,'sp_native_ui')
        if any(word in path for word in ('names.json','squad-')):return 'sp_names'
        return 'sp_native_ui'
    if any(word in path for word in ('nisv-strategy-qa','nisv-tutorial-pages','weapon-special-effect')):return 'main_fixed_help_qa'
    return 'main_menu_and_help'


def priority(path: str) -> int:
    if path.endswith('/instructions-overrides.json'):return 100
    if path.endswith('/srvc-production-overrides.json'):return 90
    if path.endswith('/release-v0.3.json'):return 80
    return 10


def build(root: Path=ROOT) -> dict:
    inputs={};all_rows=[];excluded=[]
    for file in sorted((root/'corpus/zh').rglob('*.json')):
        path=str(file.relative_to(root));raw=file.read_bytes();inputs[path]=digest(raw);document=json.loads(raw)
        if path==LEDGER:
            excluded.append(dict(path=path,reason='Review ledger, not a writeback source; pointers retained as aliases.',entries=len(document['entries'])))
            continue
        for row,pointer in rows(document):
            all_rows.append(dict(path=path,json_pointer=pointer,row=row,group=group(path,row)))
    # Accepted release rows and explicit overrides supersede their earlier
    # source batch at the same bound ID/hash. Different targets stay distinct.
    by_key=defaultdict(list)
    for entry in all_rows:
        row=entry['row'];edition='sp' if '/special-disc/' in entry['path'] else 'shared'
        key=(edition,row.get('id',entry['json_pointer']),row.get('source_text_sha256'))
        by_key[key].append(entry)
    owners=[];aliases=[]
    for entries in by_key.values():
        if len(entries)>1 and any(priority(e['path'])>10 for e in entries):
            chosen=max(entries,key=lambda e:(priority(e['path']),e['path']))
            owners.append(chosen)
            aliases.extend(dict(path=e['path'],id=e['row'].get('id'),canonical_path=chosen['path'],canonical_id=chosen['row'].get('id'),
                translation_equal=e['row']['translation']==chosen['row']['translation']) for e in entries if e is not chosen)
        else:
            owners.extend(entries)
    summary=defaultdict(Counter);records=[];symbol_records=[];dynamic_records=[]
    for entry in owners:
        row=entry['row'];text=row['translation'];bucket=entry['group']
        logical=logical_dialogue_text(text) if bucket in ('main_dialogue','main_system_dialogue','sp_stage_source') else text
        runs,symbols=candidates(logical)
        summary[bucket]['scanned_owners']+=1
        if '＜ｔｍ＞' in text or '<tm>' in text or re.search(r'\$[A-Za-z]|%(?:[-+0-9.]*[sdufXx])',text):
            dynamic_records.append(dict(path=entry['path'],id=row.get('id'),json_pointer=entry['json_pointer'],group=bucket,
                template='tm' if '＜ｔｍ＞' in text or '<tm>' in text else 'format_or_player_name'))
        if symbols:
            symbol_records.append(dict(path=entry['path'],id=row.get('id'),json_pointer=entry['json_pointer'],group=bucket,symbols=symbols))
        if not runs:continue
        status=('texture_glyph_review' if bucket=='texture_labels' else
            'dynamic_template' if '＜ｔｍ＞' in text or '<tm>' in text else
            'existing_dimensions_review' if re.search(r'<(?:width|space):',text) else
            'other_controls_review' if CONTROL_NOTATION.search(text) else
            'symbol_review' if any(r['adjacent_symbol_review'] for r in runs) else 'plain_candidate')
        active=sum(not r['division_protected'] for r in runs)
        summary[bucket]['candidate_owners']+=1;summary[bucket]['candidate_runs']+=active
        summary[bucket]['division_protected_runs']+=len(runs)-active;summary[bucket][status]+=1
        records.append(dict(path=entry['path'],id=row.get('id'),json_pointer=entry['json_pointer'],group=bucket,
            editions=['original','best','sp'] if bucket.startswith('library_') else ['sp'] if '/special-disc/' in entry['path'] else ['original','best'],
            translation_sha256=digest(text.encode()),source_text_sha256=row.get('source_text_sha256'),status=status,
            offset_basis='logical_dialogue_text' if logical!=text else 'translation',
            visible_characters=len(CONTROL_NOTATION.sub('',text).replace('\n','')),runs=runs,
            locations=row.get('locations',row.get('location')),editorial_status=row.get('editorial_status',row.get('status'))))
    bound_summary=None;bound_records=[]
    receipt_path=root/'manifests/editions/sp/current.json'
    binding_inputs={}
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text());proof_path=root/receipt['readback']['path'];proof=json.loads(proof_path.read_text())
        component=next(p for p in proof['components'] if p.endswith('/stage/report.json'))
        stage_path=root/receipt['workspace']/component;stage=json.loads(stage_path.read_text())
        source_cache={};bound_owners={}
        for chunk in stage['chunk_reports']:
            for binding in chunk['bindings']:
                if binding.get('layout')!='story_dialogue':continue
                path,id_=binding['corpus'],binding['corpus_id']
                if path not in source_cache:source_cache[path]={r['id']:r for r,_ in rows(json.loads((root/path).read_text())) if r.get('id')}
                row=source_cache[path][id_]
                if row['source_text_sha256']!=binding['source_text_sha256']:raise ValueError('SP ordinary source binding drift')
                bound_owners.setdefault((path,id_),dict(row=row,targets=[]))['targets'].append(binding['target'])
        matching=[r for r in bound_owners.values() if candidates(logical_dialogue_text(r['row']['translation']))[0]]
        for (path,id_),owner in bound_owners.items():
            runs=candidates(logical_dialogue_text(owner['row']['translation']))[0]
            template='＜ｔｍ＞' in owner['row']['translation'] or '<tm>' in owner['row']['translation']
            if runs or template:
                bound_records.append(dict(path=path,id=id_,targets=owner['targets'],runs=runs,tm_template=template))
        bound_keys={(r['path'],r['id']) for r in bound_records}
        for record in records:
            if (record['path'],record['id']) in bound_keys and 'sp' not in record['editions']:
                record['editions'].append('sp')
        bound_summary=dict(iso_sha256=receipt['output']['sha256'],ordinary_bindings=sum(len(r['targets']) for r in bound_owners.values()),
            unique_source_owners=len(bound_owners),candidate_owners=len(matching),candidate_runs=sum(len(candidates(logical_dialogue_text(r['row']['translation']))[0]) for r in matching),
            candidate_bindings=sum(len(r['targets']) for r in matching),tm_template_bindings=sum(len(r['targets']) for r in bound_owners.values() if '＜ｔｍ＞' in r['row']['translation']))
        binding_inputs={str(p.relative_to(root)):digest(p.read_bytes()) for p in (receipt_path,proof_path,stage_path)}
    return dict(schema_version=1,batch_id='compact-text-inventory-20260928',applied=False,
        coverage='All corpus/zh JSON translation rows, nested scoped overrides, unit segments and remaining-UI offset dictionaries. Current sources; accepted release/override aliases collapsed. Counts are authoring owners, not physical ISO payloads or runtime acceptance.',
        rule='At least 3 visible Latin/digit/expression characters; controls are boundaries; entire division expressions protected; unknown/adjacent symbols require a readable-glyph decision.',
        files_scanned=len(inputs),source_rows_scanned=len(all_rows),canonical_source_owners=len(owners),candidate_owners=len(records),
        eligible_runs=sum(sum(not x['division_protected'] for x in r['runs']) for r in records),
        groups={k:dict(v) for k,v in sorted(summary.items())},records=records,symbol_review_records=symbol_records,dynamic_records=dynamic_records,
        aliases=aliases,excluded=excluded,input_sha256=inputs,
        sp_current_ordinary_bindings=bound_summary,sp_current_ordinary_candidate_records=bound_records,binding_input_sha256=binding_inputs,
        binding_gates=['SP stage source includes both ordinary, battle and non-dialogue owners; active ordinary binding count is reported separately by the prior current-ISO proof.',
            'Runtime executable composers, dynamic placeholders, fixed name pools/caches, fixed field allocations and texture labels require their own consumer/byte/runtime gates.',
            'Unselected source batches remain source-review rows; no claim that every source row is an active current-ISO target.',
            'Configured texture/executable labels outside corpus/zh are enumerated in the surface plan, not counted as ordinary text insertion candidates.'])


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=build();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','aliases','symbol_review_records','dynamic_records','input_sha256','sp_current_ordinary_candidate_records')},ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
