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
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).resolve().parent)]
from build_text_candidate import file_sha,sha,read_member,verify_iso_ranges,write_json,load,require
from srwz.iso9660 import member_map,scan_iso9660
from srwz.codec import decode_production,reencode_changed_suffix
from install_font import sp_offsets,VT1_TABLE,replace_font_slot
from migrate_stage_dialogue import read_disc_member
from chart_visibility import apply_chart_visibility
from special_disc.writeback.unit_names import apply_unit_names
from special_disc.writeback.pilot_names import apply_pilot_names
from special_disc.writeback.keyword_list_names import apply_keyword_names
from weapon_detail_labels import apply_weapon_detail_labels
from migrate_slps_text import encoding_tables
from special_disc.writeback.terrain_names import apply_terrain_names, MEMBER as TERRAIN_MEMBER
from special_disc.writeback.stage_titles import apply_stage_titles, verify_title_bindings
from special_disc.source import CURRENT_ISO
from special_disc.writeback.qa_layout import MEMBER as QA_MEMBER
from special_disc.writeback.qa_native import apply_reviewed_qa as apply_qa_layout
from special_disc.baselines import baseline_iso
from special_disc.writeback.data_link_bonus import apply_data_link_bonus
from special_disc.writeback.battle_square_skip import apply_skip
from special_disc.writeback.squad_names import apply_nisv_names

WORK=ROOT/'work/build/special-disc/full-text'
BASE_SHA='3617b44b263b1a31f14632d89f3ee456a031349ee892b25c6c8eeb9ae8d5ae73'
FONT=ROOT/'work/build/special-disc/text-candidate'
PROPOSAL=FONT/'font/proposal.json'
DEST=CURRENT_ISO
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


def verify_and_publish(temporary, destination, work, report, original_iso_sha, original_manifest):
    """Keep the destination intact when verification fails or another writer wins."""
    manifest_path=destination.with_suffix('.json')
    write_json(temporary.with_suffix('.json'),report)
    try:
        with (work/'verify_full_text.log').open('w') as log:
            subprocess.run([sys.executable,str(ROOT/'tools/special_disc/verification/verify_full_text.py'),
                            '--iso',str(temporary),'--work-directory',str(work)],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        readback=work/'independent-readback.json'
        report['independent_readback']=dict(path=str(readback.relative_to(ROOT)),sha256=file_sha(readback))
        report['status']='all_bound_text_reread_from_final_iso_runtime_pending'
        write_json(temporary.with_suffix('.json'),report)
        require((file_sha(destination) if destination.exists() else None)==original_iso_sha and
                (manifest_path.read_bytes() if manifest_path.exists() else None)==original_manifest,
                'destination ISO/manifest changed during build')
        temporary.replace(destination);temporary.with_suffix('.json').replace(manifest_path)
    finally:
        temporary.unlink(missing_ok=True);temporary.with_suffix('.json').unlink(missing_ok=True)


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
    require(sum(r['entries']for r in rows)==8631,'SP source corpus scope changed; update explicit contract')
    return dict(corpora=rows,total_entries=8631,pending_targets=[],stage_chunks=len(CHUNKS),stage_bindings=len([r for c in stage['chunk_reports'] for r in c['bindings']]),formation_cells=sum(len(r.get('writes',[]))for c in stage['chunk_reports']for r in c['bindings']),frame_bindings=len(frame['bindings']),image_labels=len(reports['image-labels']['bindings']),sp_battle_entries=reports['srvc']['sp_corpus']['entries'],sp_battle_records=reports['srvc']['sp_corpus']['records'])


def assemble():
    original_iso_sha=file_sha(DEST) if DEST.exists() else None
    manifest_path=DEST.with_suffix('.json')
    original_manifest=manifest_path.read_bytes() if manifest_path.exists() else None
    BASE=baseline_iso('text-canary')
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
    for key, filename in (('command_headings', 'command-headings.json'), ('title_atlas', 'title-atlas.json')):
        require(file_sha(ROOT/'config/assets/special-disc'/filename)==reports['image-labels'][key]['config_sha256'],
                f'{key} frozen component input drift')
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
    for name,data in components['frame'].items():
        if name==STAGE:continue
        require(sha(base[name])==reports['frame']['base_files'][name],f'frame {name} base drift');patches[name]=data
    # Compose system and frame edits relative to the preserved canary in
    # decoded space so later system text fixes survive the frame pass.
    frame_cd=decode_production(patches[CD])
    merged_cd,_=merge_delta(frame_cd.output,decode_production(base[CD]).output,decode_production(components['system'][CD]).output)
    if merged_cd!=frame_cd.output:
        packed=reencode_changed_suffix(patches[CD],merged_cd,strategy='rust-fit',max_output_size=len(patches[CD]),original_result=frame_cd)
        require(len(packed)<=len(patches[CD]),'merged COMPDATA exceeds member budget')
        require(decode_production(packed).output==merged_cd,'merged COMPDATA reread mismatch')
        patches[CD]=packed+bytes(len(patches[CD])-len(packed))
    for name,data in components['image-labels'].items():
        require(sha(base[name])==reports['image-labels']['base_files'][name],f'image {name} base drift');patches[name]=data
    patches.update(components['srvc'])
    source_table,menu_overrides,stored_overrides,runtime_table=encoding_tables(PROPOSAL)
    qa_base=patches.get(QA_MEMBER)
    if qa_base is None:qa_base=read_member(BASE,members,QA_MEMBER)
    patches[QA_MEMBER],qa_report=apply_qa_layout(qa_base,patches[EXE],read_disc_member(QA_MEMBER),source_table,stored_overrides)
    patches[QA_MEMBER],squad_report=apply_nisv_names(patches[QA_MEMBER],patches[EXE],read_disc_member(QA_MEMBER),source_table,stored_overrides,runtime_table)
    patches[TERRAIN_MEMBER],terrain_report=apply_terrain_names(patches[TERRAIN_MEMBER],patches[EXE],read_disc_member(TERRAIN_MEMBER),source_table,menu_overrides,runtime_table)
    patches[EXE],weapon_report=apply_weapon_detail_labels(patches[EXE],source_table,menu_overrides,runtime_table)
    patches[VT1]=replace_font_slot(patches[VT1],patches[EXE],(FONT/'sp-font/font.bin').read_bytes(),font_report['font']['decoded_sha256'])
    vt=sp_offsets(patches[EXE],VT1_TABLE,len(patches[VT1]));decoded_font=decode_production(patches[VT1][vt[3]:vt[4]]).output
    require(sha(decoded_font)==font_report['font']['decoded_sha256'],'assembled shared font mismatch')
    patches[CD],unit_report=apply_unit_names(patches[CD],source_table,menu_overrides,runtime_table,decoded_font,proposal)
    patches[CD],pilot_report=apply_pilot_names(patches[CD],source_table,menu_overrides,runtime_table)
    patches[CD],keyword_report=apply_keyword_names(patches[CD],source_table,stored_overrides,runtime_table)
    verify_title_bindings(decode_production(patches[CD]).output)
    patches[VT1],title_report=apply_stage_titles(patches[VT1],patches[EXE])
    patches[EXE],patches[VT1],link_report=apply_data_link_bonus(
        patches[EXE],patches[VT1],source_table,stored_overrides,runtime_table)
    patches[EXE],skip_report=apply_skip(patches[EXE])
    stats['stage_entry_title_slots']=title_report['count']
    stats['stage_entry_title_images_rewritten']=title_report['rewritten']
    stats['inherited_world_map_titles']=reports['image-labels']['world_map_titles']['count']
    stats['sp_title_drawing_records']=reports['image-labels']['title_atlas']['drawing_records']
    stats['additional_native_unit_names']=unit_report['entries']
    stats['additional_native_pilot_name_fields']=pilot_report['entries']
    stats['repaired_keyword_list_names']=keyword_report['repaired_entries']
    stats['additional_native_unit_name_pointers']=unit_report['pointer_count']
    DEST.parent.mkdir(parents=True,exist_ok=True);temporary=DEST.with_suffix('.tmp.iso')
    require(not temporary.exists(),'another ISO assembly is in progress')
    shutil.copyfile(BASE,temporary)
    with temporary.open('r+b')as stream:
        for name,data in patches.items():
            require(len(data)==members[name].size,f'{name} member length changed')
            stream.seek(members[name].extent_lba*2048);stream.write(data)
    after=member_map(scan_iso9660(temporary))
    require({n:(m.extent_lba,m.size)for n,m in members.items()}=={n:(m.extent_lba,m.size)for n,m in after.items()},'ISO directory/LBA drift')
    for name,data in patches.items():require(read_member(temporary,after,name)==data,f'{name} ISO reread mismatch')
    protected=verify_iso_ranges(BASE,temporary,[(members[n].extent_lba*2048,members[n].extent_lba*2048+len(d))for n,d in patches.items()])
    report=dict(schema_version=1,scenario_chart=chart_report,status='all_current_draft_text_written_static_verified_runtime_pending',iso=dict(path=str(DEST.relative_to(ROOT)),size=temporary.stat().st_size,sha256=file_sha(temporary)),baseline=dict(path=str(BASE.relative_to(ROOT)),sha256=BASE_SHA),coverage=stats,files={n:sha(d)for n,d in patches.items()},protected_iso_ranges=protected,system_executable_changed_bytes=delta_count,proposal_sha256=proposal_sha,decoded_font_sha256=sha(decoded_font),components={str((WORK/k/'report.json').relative_to(ROOT)):file_sha(WORK/k/'report.json')for k in reports},source_files={str(p.relative_to(ROOT)):file_sha(p)for p in sorted((ROOT/'tools/special_disc/writeback').glob('*.py'))},runtime='pending',editorial='draft',not_claimed=['all game surfaces translated','all stages runtime verified','PCSX2 manual acceptance','save/load regression'])
    report['weapon_detail_labels']=weapon_report
    report['data_link_bonus']=link_report
    report['battle_square_skip']=skip_report
    report['qa_layout']=qa_report
    report['nisv_squad_names']=squad_report
    report['terrain_names']=terrain_report
    report['unit_names']=unit_report
    report['pilot_names']=pilot_report
    report['keyword_list_names']=keyword_report
    report['stage_titles']=title_report
    report['world_map_titles']=reports['image-labels']['world_map_titles']
    report['title_atlas']=reports['image-labels']['title_atlas']
    # Verification must finish before either the current ISO or its receipt changes.
    verify_and_publish(temporary,DEST,WORK,report,original_iso_sha,original_manifest)
    write_json(WORK/'coverage.json',stats)
    print(json.dumps(report['iso'],ensure_ascii=False,indent=2))


def main():
    global WORK,DEST
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assemble-only',action='store_true')
    parser.add_argument('--work-directory',type=Path)
    parser.add_argument('--output',type=Path,default=CURRENT_ISO)
    args=parser.parse_args();DEST=args.output.resolve()
    if args.work_directory is not None:
        WORK=args.work_directory.resolve()
        if not args.assemble_only:require(not WORK.exists(),'build work directory must be new')
    elif args.assemble_only:
        parser.error('--assemble-only requires --work-directory for the exact build run')
    else:
        runs=WORK/'runs';runs.mkdir(parents=True,exist_ok=True)
        WORK=Path(tempfile.mkdtemp(prefix='build-',dir=runs))
    if not args.assemble_only:build()
    assemble()

if __name__=='__main__':main()
