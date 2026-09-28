#!/usr/bin/env python3
"""Prepare balanced LIBRARY/flow/scroll candidates without corpus or ISO writes."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
from srwz.chinese_layout import LayoutWeights,load_layout_profiles,reflow_chinese_paragraph
from srwz.codec import decode_production
from srwz.stage_overview import parse_stage_overviews
from srwz.summary import parse_summary
from srwz.iso_layout import CORE_ARCHIVE_SPECS,read_executable_archive_offsets
from srwz.text import load_text_table
from srwz.chinese_prose import logical_prose_text,reflow_chinese_prose
from srwz.renderer_metrics import compact_visible_runs,text_extent
from srwz.text import CONTROL_NOTATION,normalize_original_fullwidth_ascii
from build_library_v02_component import load_production_layout,reflow_body
from write_frame_text import flow_synopsis

BREAKABLE_FULL_NAMES = (
    'Fast Acting Integrate Tactical Headquarters',
    'Production Location Ally on Nexas Technology',
)

# Local candidate budgets from the 2026-09-28 same-ISO LRPS2 boundary probes.
# Production configuration is changed only in the later batch writeback.
LOCAL_WIDTHS = {'library_glossary': 25, 'stage_scroll_overview': 30}

preview_flow=flow_synopsis

def build(baseline_revision: str='3af1525',checkpoint: Path | None=None) -> dict:
    profiles=load_layout_profiles(ROOT/'config/text-layout/zh-layout-profiles.json')
    raw=subprocess.check_output(['git','show',f'{baseline_revision}:config/text-layout/zh-layout-profiles.json'],cwd=ROOT)
    baseline=json.loads(raw)
    old={k:replace(v,maximum_width=baseline['profiles'][k]['maximum_width'],weights=LayoutWeights(**{**baseline['default_weights'],**baseline['profiles'][k].get('weights',{})}),
        line_packing=baseline['profiles'][k].get('line_packing','balanced'),
        unbroken_terms=tuple(baseline.get('common_unbroken_terms',[])+baseline['profiles'][k].get('unbroken_terms',[]))) for k,v in profiles.items() if k in baseline['profiles']}
    profiles={k:replace(v,maximum_width=LOCAL_WIDTHS.get(k,v.maximum_width)) for k,v in profiles.items()}
    scope=json.loads((ROOT/'config/library/v0.2-reviewed-writeback.json').read_text())['layout']
    _,terms,*_=load_production_layout(scope,scope['body_line_widths'])
    namespace={'__file__':str(ROOT/'tools/special_disc/writeback/write_frame_text.py'),'__name__':'layout_baseline'}
    exec(compile(subprocess.check_output(['git','show',f'{baseline_revision}:tools/special_disc/writeback/write_frame_text.py'],cwd=ROOT),namespace['__file__'],'exec'),namespace)
    old_flow=namespace['flow_synopsis']
    records=[];summary=Counter();inputs={}

    def document(name):
        p=ROOT/name;data=p.read_bytes();inputs[name]=hashlib.sha256(data).hexdigest();return json.loads(data)['entries']

    def record(surface,path,row,before,after,profile,variant,**extra):
        widths=[text_extent(line,default_advance_px=profile.default_advance_px).occupied_px for line in after.split('\n')]
        clean_after=CONTROL_NOTATION.sub('',after);clean_source=normalize_original_fullwidth_ascii(CONTROL_NOTATION.sub('',row['translation']))
        equal=(clean_after.replace('\n','')==clean_source.replace('\n','')) if surface.startswith('library_') else logical_prose_text(clean_after)==logical_prose_text(clean_source)
        if not equal:raise ValueError(f'visible content changed: {surface}/{row["id"]}')
        records.append(dict(surface=surface,path=path,id=row['id'],variant=variant,before=before,after=after,
            changed=before!=after,content_exact=equal,maximum_width_cells=profile.maximum_width,default_advance_px=profile.default_advance_px,
            line_widths_px=widths,lines=len(widths),**extra))
        summary[surface+'/'+variant+'/scanned']+=1
        summary[surface+'/'+variant+'/changed']+=before!=after

    path='corpus/zh/library/v0.2-reviewed.json'
    library_rows=document(path)
    library_code=''.join((ROOT/name).read_text() for name in (
        'tools/build_library_v02_component.py','tools/srwz/chinese_layout.py',
        'tools/srwz/renderer_metrics.py','tools/srwz/text.py'))
    checkpoint_key=hashlib.sha256((json.dumps(inputs,sort_keys=True)+str(profiles)+str(terms)+baseline_revision+str(BREAKABLE_FULL_NAMES)+library_code).encode()).hexdigest()
    cached=json.loads(checkpoint.read_text()) if checkpoint is not None and checkpoint.exists() else {}
    if cached.get('key')==checkpoint_key:
        records=cached['records'];summary.update(cached['summary']);library_rows=[]
    for index,row in enumerate(library_rows):
        if not set(row.get('tags',[]))&{'DSCR','DSC2'}:continue
        if index%100==0:print(f'LIBRARY source row {index}/{len(library_rows)}',flush=True)
        domain=next(d for d in row['domains'] if d in ('robot','character','glossary'))
        key={'robot':'library_robot','character':'library_character','glossary':'library_glossary'}[domain]
        profile=replace(profiles[key],default_advance_px=22)
        text=normalize_original_fullwidth_ascii(row['translation']).replace('\n','')
        before=reflow_chinese_paragraph(text,profile=replace(old[key],default_advance_px=22),protected_terms=terms).text
        fitted=reflow_chinese_paragraph(text,profile=profile,protected_terms=terms).text
        record('library_'+domain,path,row,before,fitted,profile,'balanced_plain')
        if not CONTROL_NOTATION.search(text):
            tagged=compact_visible_runs(text,default_advance_px=22,
                                        breakable_phrases=BREAKABLE_FULL_NAMES)
            if tagged!=text:
                try:
                    fitted,_=reflow_body(tagged,profile.maximum_width,profile=profile,protected_terms=terms)
                    record('library_'+domain,path,row,before,fitted,profile,'balanced_compact')
                except ValueError as error:
                    records.append(dict(surface='library_'+domain,path=path,id=row['id'],variant='balanced_compact',error=str(error)))
                    summary['library_'+domain+'/balanced_compact/scanned']+=1
                    summary['library_'+domain+'/balanced_compact/failed']+=1

    if checkpoint is not None:
        checkpoint.write_text(json.dumps(dict(key=checkpoint_key,records=records,summary=dict(summary)),ensure_ascii=False)+'\n')
    for path in (ROOT/'config/text-layout').glob('*.json'):
        inputs[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    path='corpus/zh/special-disc/frame-text.json'
    for row in document(path):
        if row.get('kind')=='synopsis':
            before=old_flow(row['translation']);profile=replace(profiles['stage_scroll_overview'],default_advance_px=16)
            record('sp_flow',path,row,before,preview_flow(row['translation']),profile,'balanced_plain',maximum_lines=11)
            tagged=compact_visible_runs(row['translation'],default_advance_px=16)
            if tagged!=row['translation']:
                record('sp_flow',path,row,before,preview_flow(tagged),profile,'balanced_compact',maximum_lines=11)
        elif row.get('kind')=='narration':
            # Native 25px cells: physical edge is 24 cells, author at 23 to
            # retain a right margin. No inline dimensions in this stream.
            text=row['translation'];source=row['source_text']
            profile=profiles['sp_narration_scroll']
            fitted=reflow_chinese_prose(text,profile=profile,maximum_lines=len(source.split('\n')))
            record('sp_scroll',path,row,text,fitted.text,profile,'balanced_plain',source_rows_upper_bound=len(source.split('\n')),width_evidence='SP narration/000 RAM boundary probe; all 10 native geometries equal',scroll_timing_pending=True)

    with (ROOT/'work/disc/DATA/STAGE.BIN').open('rb') as stream:
        stored=stream.read(55392)
    source_overviews={r.entry_id:r for r in parse_stage_overviews(decode_production(stored).output,load_text_table(ROOT/'vendor/upstream-python/project/tbl_all.json'))}
    inputs['work/disc/DATA/STAGE.BIN:first-55392-bytes']=hashlib.sha256(stored).hexdigest()
    archive=(ROOT/'work/disc/DATA/MTV_PROS.BIN').read_bytes()
    exe=(ROOT/'work/disc/SLPS_258.87').read_bytes()
    offsets=read_executable_archive_offsets(exe,CORE_ARCHIVE_SPECS['MTV_PROS.BIN'],len(archive))
    source_scroll={r.entry_id:r for i,(start,end) in enumerate(zip(offsets,offsets[1:]))
        for r in parse_summary(decode_production(archive[start:end]).output,
            load_text_table(ROOT/'vendor/upstream-python/project/tbl_all.json'),chunk_index=i).entries}
    inputs['work/disc/DATA/MTV_PROS.BIN']=hashlib.sha256(archive).hexdigest()
    inputs['work/disc/SLPS_258.87']=hashlib.sha256(exe).hexdigest()
    for surface,path,key in [('main_flow','corpus/zh/menu/stage-overviews.json','stage_scroll_overview'),
                             ('main_scroll','corpus/zh/summary.json','world_history_scroll')]:
        profile=replace(profiles[key],line_count_mode='minimum',default_advance_px=16 if surface=='main_flow' else 24)
        for row in document(path):
            text=row['translation'];limit=len(source_overviews[row['id']].source_text.rstrip('\n').splitlines())+(1 if text.endswith('\n') else 0) if surface=='main_flow' else len(source_scroll[row['id']].text.split('\n'))
            if surface=='main_flow' and hashlib.sha256(source_overviews[row['id']].source_text.encode()).hexdigest()!=row['source_text_sha256']:raise ValueError('main overview source drift')
            if surface=='main_scroll' and hashlib.sha256(source_scroll[row['id']].text.encode()).hexdigest()!=row['source_text_sha256']:raise ValueError('main scroll source drift')
            try:
                fitted=reflow_chinese_prose(text,profile=profile,protected_terms=terms,maximum_lines=limit)
                record(surface,path,row,text,fitted.text,profile,'balanced_plain',source_rows_upper_bound=limit,
                    width_evidence='2026-09-28 same-ISO LRPS2 boundary samples',scroll_timing_pending=surface=='main_scroll')
            except ValueError as error:
                records.append(dict(surface=surface,path=path,id=row['id'],variant='balanced_plain',before=text,error=str(error),source_rows_upper_bound=limit))
                summary[surface+'/balanced_plain/scanned']+=1
                summary[surface+'/balanced_plain/failed']+=1
    return dict(schema_version=1,batch_id='balanced-prose-preview-20260928',baseline_revision=baseline_revision,applied=False,
        policy='Balance within authored paragraphs after punctuation and word/name protection. Keep paragraph indentation/blank rows, pixel limits and source row budgets. Horizontal tickers are excluded.',
        inputs=inputs,local_width_overrides=LOCAL_WIDTHS,sp_narration_width_cells=23,
        baseline_profile_sha256=hashlib.sha256(raw).hexdigest(),summary=dict(sorted(summary.items())),records=records,
        limitations=['Character Dove probe remains a checked RAM text sample in another portrait panel.',
            'Boundary samples validate widths, not every resulting page. Scroll timing, encoded capacity, native controls and full batch runtime remain pending. No compact tags are added to narration/summary streams.',
            'This preview does not rebuild an ISO, alter corpus wording or approve every physical field/cached consumer.'])


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--baseline-revision',default='3af1525')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True);result=build(a.baseline_revision,a.output.parent/'prose-library-checkpoint.json')
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
