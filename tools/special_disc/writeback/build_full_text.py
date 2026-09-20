"""Build all currently translated SP text onto the preserved font/image canary.

Every component is reread, every corpus target must be consumed, and the final
ISO retains original member sizes/LBAs. This is a draft-text candidate, not a
claim that every game surface has been translated or manually accepted.
"""
from __future__ import annotations
import argparse
import collections
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).resolve().parent)]
from build_text_candidate import file_sha,sha,read_member,verify_iso_ranges,write_json,load,require
from srwz.iso9660 import member_map,scan_iso9660
from srwz.codec import decode_production
from install_font import sp_offsets,VT1_TABLE
from migrate_stage_dialogue import read_disc_member
from chart_visibility import apply_chart_visibility

WORK=ROOT/'work/build/special-disc/full-text'
BASE=ROOT/'build/iso/special-disc/text-candidate/sp-text-canary.iso'
BASE_SHA='4ecc53fb34dd195fedc4018dbcb09306ee929eaf5d1f1fa1b4859242524ff953'
FONT=ROOT/'work/build/special-disc/text-candidate'
PROPOSAL=FONT/'font/proposal.json'
DEST=ROOT/'build/iso/special-disc/full-text/sp-zh-full-text.iso'
CHUNKS=[1,2,3,4,5,7,8,9,11,13,14,15,16,18,19,20,21,23,24,25,26,27,28,29,*range(39,57)]
EXE,STAGE,VT1,CD='SLPS_259.20','DATA/STAGE.BIN','DATA/VT1.BIN','DATA/COMPDATA.BN'


def build():
    WORK.mkdir(parents=True,exist_ok=True)
    def run(script,*args):
        print(script,flush=True)
        with (WORK/f'{Path(script).stem}.log').open('w') as log:
            subprocess.run([sys.executable,str(ROOT/'tools/special_disc/writeback'/script),*map(str,args)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    run('write_system_text.py','--proposal',PROPOSAL,'--output',WORK/'system')
    run('migrate_stage_dialogue.py','--allow-draft','--include-formations','--chunks',*CHUNKS,'--proposal',PROPOSAL,'--base',WORK/'system','--output',WORK/'stage')
    run('migrate_srvc.py','--include-sp','--allow-draft','--proposal',PROPOSAL,'--output',WORK/'srvc')
    run('write_frame_text.py','--proposal',PROPOSAL,'--output',WORK/'frame')
    run('write_image_labels.py','--output',WORK/'image-labels')


def merge_delta(current,before,after):
    require(len(current)==len(before)==len(after),'delta lengths differ')
    out=bytearray(current);count=0
    for i,(a,b) in enumerate(zip(before,after)):
        if a!=b:
            require(current[i]==a,f'component delta preimage mismatch at {i:X}')
            out[i]=b;count+=1
    return bytes(out),count


def coverage(reports):
    corpus_root=ROOT/'corpus/zh/special-disc';stage=reports['stage'];frame=reports['frame']
    consumed={row['target'] for c in stage['chunk_reports'] for row in c['bindings']}
    consumed.update(r['target'] for r in frame['bindings'])
    consumed.update(r['target'] for r in reports['image-labels']['bindings'])
    require(not any(reports['system']['left'].values()),'system component has pending text')
    require(reports['srvc']['untranslated_records']==0,'battle subtitle residue')
    rows=[]
    for kind in ('story-dialogue','challenge-dialogue','battle-lines','frame-text','system-text'):
        path=corpus_root/f'{kind}.json';entries=load(path)['entries'];pending=[];targets_count=0
        for row in entries:
            for target in row.get('locations',[row['id']]):
                targets_count+=1
                if kind in ('system-text','battle-lines') or target.startswith(('sd/exe/','sd/compdata/')):continue
                if target not in consumed:pending.append(target)
        require(not pending,f'{kind}: unwritten corpus targets: {pending}')
        rows.append(dict(corpus=str(path.relative_to(ROOT)),sha256=file_sha(path),entries=len(entries),targets=targets_count,pending=pending))
    require(sum(r['entries']for r in rows)==8629,'SP source corpus scope changed; update explicit contract')
    return dict(corpora=rows,total_entries=8629,pending_targets=[],stage_chunks=len(CHUNKS),stage_bindings=len([r for c in stage['chunk_reports'] for r in c['bindings']]),formation_cells=sum(len(r.get('writes',[]))for c in stage['chunk_reports']for r in c['bindings']),frame_bindings=len(frame['bindings']),image_labels=len(reports['image-labels']['bindings']),sp_battle_entries=reports['srvc']['sp_corpus']['entries'],sp_battle_records=reports['srvc']['sp_corpus']['records'])


def assemble():
    require(file_sha(BASE)==BASE_SHA,'preserved canary ISO identity drift')
    reports={k:load(WORK/k/'report.json')for k in ('system','stage','srvc','frame','image-labels')}
    require(reports['stage']['status']=='static_component_verified_runtime_pending' and reports['stage']['chunks']==CHUNKS,'full STAGE component scope/status')
    require(not reports['stage']['pending_native_targets'],'unconsumed STAGE targets')
    proposal_sha=file_sha(PROPOSAL)
    for k in ('system','srvc','frame'):require(reports[k]['proposal_sha256']==proposal_sha,f'{k} codebook drift')
    require(reports['stage']['proposal']['sha256']==proposal_sha,'stage codebook drift')
    for lock in reports['frame']['z_ending_inputs']:
        require(file_sha(ROOT/lock['path'])==lock['sha256'],'Z ending title input drift')
    require(len(reports['frame']['z_ending_titles'])==3,'Z ending title scope drift')
    label_lock=reports['frame']['episode_label_config']
    require(file_sha(ROOT/label_lock['path'])==label_lock['sha256'],'chart episode label input drift')
    require(len(reports['frame']['episode_labels'])==128,'chart episode label scope drift')
    help_lock=reports['frame']['key_help_config']
    require(file_sha(ROOT/help_lock['path'])==help_lock['sha256'],'chart help editorial input drift')
    require(len(reports['frame']['key_help'])==5,'chart help binding scope drift')
    for k in ('frame','image-labels'):require(reports[k]['status']=='static_verified_runtime_pending',f'{k} failed')
    for path,expected in reports['stage']['inputs'].items():require(file_sha(ROOT/path)==expected,f'input drift: {path}')
    for k in ('system','srvc'):
        lock=reports[k]['corpus'] if k=='system' else dict(path=reports[k]['corpus'],sha256=reports[k]['corpus_sha256'])
        require(file_sha(ROOT/lock['path'])==lock['sha256'],f'{k} corpus drift')
    for k in ('frame','image-labels'):require(file_sha(ROOT/'corpus/zh/special-disc/frame-text.json')==reports[k]['corpus_sha256'],'frame corpus drift')
    for lock in (reports['system']['frame_corpus'],reports['srvc']['sp_corpus'],reports['image-labels']['snapshot']):
        require(file_sha(ROOT/lock['path'])==lock['sha256'],'component input drift')
    components={}
    for k,r in reports.items():
        components[k]={}
        for name,expected in r['files'].items():
            data=(WORK/k/name).read_bytes();require(sha(data)==expected,f'{k}/{name} component drift');components[k][name]=data
    current_font=load(ROOT/'config/fonts/zh-release-font.json');snapshot=current_font['allocation_snapshot']
    require(file_sha(ROOT/snapshot['path'])==snapshot['sha256'],'shared codebook allocation drift')
    require(load(FONT/'font/profile.json')['allocation_snapshot']==snapshot,'shared font profile drift')
    font_report=load(FONT/'sp-font/report.json');manifest=load(FONT/'font/manifest.json')
    require(manifest['proposal']['sha256']==proposal_sha,'verified font proposal drift')
    require(manifest['font_component']['decoded_font_sha256']==font_report['font']['decoded_sha256'],'verified font identity mismatch')
    stats=coverage(reports)
    stats['additional_chart_z_ending_titles']=len(reports['frame']['z_ending_titles'])
    stats['additional_chart_episode_labels']=len(reports['frame']['episode_labels'])
    stats['additional_chart_key_help']=len(reports['frame']['key_help'])
    proposal=load(PROPOSAL)
    verified_chars={a['character'] for key in ('assignments','surface_alias_assignments','source_compatibility_assignments') for a in proposal[key]}
    displayed=[r['output_text'] for c in reports['stage']['chunk_reports'] for r in c['bindings']]
    displayed.extend(r['output_text'] for r in reports['frame']['bindings'])
    displayed.extend(r['output_text'] for r in reports['frame']['key_help'])
    displayed.extend(r['output_text'] for r in reports['frame']['episode_labels'])
    displayed.extend(r['output_text'] for r in reports['frame']['z_ending_titles'])
    missing=sorted({ch for text in displayed for ch in text if ord(ch)>127 and ch!='　' and ch not in verified_chars})
    require(not missing,f'display characters outside verified shared font: {missing}')
    stats['unassigned_display_characters']=missing
    members=member_map(scan_iso9660(BASE));base={n:read_member(BASE,members,n)for n in {n for c in components.values()for n in c}|{EXE,VT1}}
    patches={}
    old_system=ROOT/'work/build/special-disc/components/system-text';old_report=load(old_system/'report.json');old_exe=(old_system/EXE).read_bytes()
    require(sha(old_exe)==old_report['files'][EXE],'old system executable drift')
    patches[EXE],delta_count=merge_delta(base[EXE],old_exe,components['system'][EXE])
    for site in (0x3B0E0,0x168A1C):require(patches[EXE][site:site+4]==bytes.fromhex('9f820134'),'special-range patch missing')
    require(reports['stage']['baseline']['sha256']==reports['system']['files'][STAGE],'stage/system composition drift')
    stage_data=components['stage'][STAGE];frame_stage=components['frame'][STAGE]
    require(sha(base[STAGE])==reports['frame']['base_files'][STAGE],'frame stage base drift')
    slot=struct.unpack_from('<I',read_disc_member('HEDBDY/HB.BIN'),0x5174)[0]
    require(stage_data[:slot]==base[STAGE][:slot] and frame_stage[slot:]==base[STAGE][slot:],'STAGE chunk-zero overlay escaped its owner')
    patches[STAGE]=frame_stage[:slot]+stage_data[slot:]
    patches[STAGE],chart_report=apply_chart_visibility(patches[STAGE],slot)
    require(components['system'][CD]==base[CD],'system/frame COMPDATA preimage drift')
    for name,data in components['frame'].items():
        if name==STAGE:continue
        require(sha(base[name])==reports['frame']['base_files'][name],f'frame {name} base drift');patches[name]=data
    for name,data in components['image-labels'].items():
        require(sha(base[name])==reports['image-labels']['base_files'][name],f'image {name} base drift');patches[name]=data
    patches.update(components['srvc'])
    vt=sp_offsets(patches[EXE],VT1_TABLE,len(patches[VT1]));decoded_font=decode_production(patches[VT1][vt[3]:vt[4]]).output
    require(sha(decoded_font)==font_report['font']['decoded_sha256'],'assembled shared font mismatch')
    DEST.parent.mkdir(parents=True,exist_ok=True);temporary=DEST.with_suffix('.tmp.iso');shutil.copyfile(BASE,temporary)
    with temporary.open('r+b')as stream:
        for name,data in patches.items():
            require(len(data)==members[name].size,f'{name} member length changed')
            stream.seek(members[name].extent_lba*2048);stream.write(data)
    after=member_map(scan_iso9660(temporary))
    require({n:(m.extent_lba,m.size)for n,m in members.items()}=={n:(m.extent_lba,m.size)for n,m in after.items()},'ISO directory/LBA drift')
    for name,data in patches.items():require(read_member(temporary,after,name)==data,f'{name} ISO reread mismatch')
    protected=verify_iso_ranges(BASE,temporary,[(members[n].extent_lba*2048,members[n].extent_lba*2048+len(d))for n,d in patches.items()])
    temporary.replace(DEST)
    report=dict(schema_version=1,scenario_chart=chart_report,status='all_current_draft_text_written_static_verified_runtime_pending',iso=dict(path=str(DEST.relative_to(ROOT)),size=DEST.stat().st_size,sha256=file_sha(DEST)),baseline=dict(path=str(BASE.relative_to(ROOT)),sha256=BASE_SHA),coverage=stats,files={n:sha(d)for n,d in patches.items()},protected_iso_ranges=protected,system_executable_changed_bytes=delta_count,proposal_sha256=proposal_sha,decoded_font_sha256=sha(decoded_font),components={str((WORK/k/'report.json').relative_to(ROOT)):file_sha(WORK/k/'report.json')for k in reports},source_files={str(p.relative_to(ROOT)):file_sha(p)for p in sorted((ROOT/'tools/special_disc/writeback').glob('*.py'))},runtime='pending',editorial='draft',not_claimed=['all game surfaces translated','all stages runtime verified','PCSX2 manual acceptance','save/load regression'])
    write_json(DEST.with_suffix('.json'),report);write_json(WORK/'coverage.json',stats)
    print(json.dumps(report['iso'],ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--assemble-only',action='store_true');args=parser.parse_args()
    if not args.assemble_only:build()
    assemble()

if __name__=='__main__':main()
