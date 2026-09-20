"""Independently reread every text binding from the assembled SP candidate ISO."""
from pathlib import Path
import collections
import json
import re
import struct
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
from build_full_text import BASE,BASE_SHA,DEST,WORK,PROPOSAL,CHUNKS
from build_text_candidate import load,sha,file_sha,require,read_member,write_json
import migrate_stage_dialogue as st
from write_system_text import tickers,FULLWIDTH_DIGITS
from srwz.iso9660 import scan_iso9660,member_map
from srwz.codec import decode_production
from srwz.text import decode_text,normalize_original_fullwidth_ascii,two_byte_visible_spaces
from srwz.summary import parse_summary
from weapon_detail_labels import CONTRACT as WEAPON_CONTRACT, verify_weapon_detail_labels
from special_disc.writeback.terrain_names import CONTRACT as TERRAIN_CONTRACT, verify_terrain_names, MEMBER as TERRAIN_MEMBER


def main():
    manifest=load(DEST.with_suffix('.json'));require(file_sha(DEST)==manifest['iso']['sha256'],'ISO identity drift')
    members=member_map(scan_iso9660(DEST));cache={};counts=collections.Counter()
    def member(name):
        if name not in cache:cache[name]=read_member(DEST,members,name)
        return cache[name]
    for name,expected in manifest['files'].items():require(sha(member(name))==expected,f'ISO member drift: {name}')
    for path,expected in manifest['components'].items():require(file_sha(ROOT/path)==expected,f'component report drift: {path}')
    table,_,overrides,readback=st.mst.encoding_tables(PROPOSAL)
    exe=member('SLPS_259.20');arc=member(st.STAGE);hb=member(st.HB)
    terrain=verify_terrain_names(member(TERRAIN_MEMBER),exe,readback)
    require(all(manifest['terrain_names'][k]==v for k,v in terrain.items()),'terrain receipt drift')
    require(file_sha(TERRAIN_CONTRACT)==manifest['terrain_names']['contract_sha256'],'terrain contract drift')
    counts['terrain_names']=terrain['occurrence_count']
    weapon_labels=verify_weapon_detail_labels(exe,readback)
    require(weapon_labels==manifest['weapon_detail_labels']['labels'],'weapon label receipt drift')
    require(file_sha(WEAPON_CONTRACT)==manifest['weapon_detail_labels']['contract_sha256'],'weapon contract drift')
    counts['weapon_detail_runtime_labels']=len(weapon_labels)
    off=struct.unpack_from('<69I',hb,st.sd.HB_STAGE_TABLE)
    mod=st.sd.sd_stage_module();functions=mod.read_stage_function_addresses(st.read_disc_member('SLPS_259.20'),start=st.sd.SD_FUNCTION_TABLE[0],end=st.sd.SD_FUNCTION_TABLE[1])
    stage_data={i:decode_production(arc[off[i]:off[i+1]]).output for i in range(68)}
    # Independently require exactly the chart visibility instruction delta.
    frame_flow=decode_production((WORK/'frame'/st.STAGE).read_bytes()[:off[1]]).output
    expected_flow=bytearray(frame_flow)
    require(expected_flow[0xD88:0xD8C]==bytes.fromhex('2b500200'),'chart source instruction drift')
    expected_flow[0xD88:0xD8C]=bytes.fromhex('01000a24')
    require(stage_data[0]==expected_flow,'chart patch escaped its single instruction')
    counts['chart_visibility_instructions']=1
    report=load(WORK/'stage/report.json')
    for chunk in report['chunk_reports']:
        i=chunk['chunk'];data=stage_data[i];parsed=mod.parse_stage(data,readback,stage_index=i,function_address=functions[i],base_address=st.sd.SD_STAGE_BASE)
        actual={e.entry_id:e for e in parsed.entries if e.kind!='speaker'}
        speakers={int(r['target'].rsplit('/',1)[1]):r['output_text'] for r in chunk['bindings'] if '/speaker/'in r['target']}
        original=(WORK/'system'/st.STAGE).read_bytes() if i==CHUNKS[0] else original
        before=mod.parse_stage(decode_production(original[off[i]:off[i+1]]).output,table,stage_index=i,function_address=functions[i],base_address=st.sd.SD_STAGE_BASE)
        source={e.entry_id:e for e in before.entries}
        for row in chunk['bindings']:
            if row['layout']=='formation_name':
                for w in row['writes']:
                    require(decode_text(data,w['offset'],readback).text==row['output_text'],'formation ISO reread')
                    counts['formation_cells']+=1
            elif '/speaker/'not in row['target']:
                e=actual[row['native_id']];require(e.text==row['output_text'],f"stage ISO reread: {row['target']}")
                if e.kind=='dialogue':
                    prefix=decode_text(data,e.text_offset,readback,stop_at_newline=True)
                    sid=source[e.entry_id].speaker_id
                    if prefix.terminator=='newline':require(prefix.text==speakers[sid],f'speaker ISO reread: {e.entry_id}')
                counts['stage_text_records']+=1
    # Each surface is checked using its physical records, not the component's compressed-byte hash alone.
    decoded_cache={}
    def decoded(name,index,start):
        key=(name,index)
        if key not in decoded_cache:
            offsets=st.sd.table_offsets(exe,start,len(member(name)))
            decoded_cache[key]=decode_production(member(name)[offsets[index]:offsets[index+1]]).output
        return decoded_cache[key]
    for row in load(WORK/'frame/report.json')['bindings']:
        target=row['target'];name=row['member'];text=normalize_original_fullwidth_ascii(row['output_text']).replace(' ','　')
        if target.startswith(('sd/vt1/','sd/group/')):
            data=decoded(name,row['chunk'],st.sd.VT1_TABLE);per=st.sd.VT1_PAGES[row['chunk']];start=row['page']*per
            lines=[decode_text(data,(start+j)*57,readback,stop_at_newline=True).text.rstrip('　') for j in range(per)]
            actual=lines[0].strip('　') if target.startswith('sd/group/') else '\n'.join(lines)
        elif target.startswith('sd/hsfc/'):
            data=decoded(name,0,st.sd.HSFC_TABLE);cell=st.sd.HSFC_SUMMARIES[1]
            actual='\n'.join(decode_text(data,row['offset']+j*cell,readback).text for j in range(3)).rstrip('\n');text=text.rstrip('\n')
        elif target.startswith('sd/mtzspros/'):
            data=decoded(name,row['chunk'],st.sd.MTZSPROS_TABLE);entries=parse_summary(data,readback,chunk_index=row['chunk']).entries
            actual=entries[int(target.rsplit('/',1)[1])].text
        else:
            data=stage_data[0] if name==st.STAGE else decode_production(member(name)).output if name=='DATA/COMPDATA.BN' else member(name)
            actual=decode_text(data,row['offset'],readback).text
            for site in row.get('pointer_sites',[]):require(struct.unpack_from('<I',data,site)[0]==st.sd.COMPDATA_BASE+row['offset'],'chapter title pointer ISO reread')
        require(actual==text,f'frame ISO reread: {target}: {actual!r} != {text!r}')
        counts['frame_targets']+=1
    source_flow=decode_production(st.read_disc_member(st.STAGE)).output
    for start,total in ((0x7510,21),(0x14B20,110)):
        for index in range(total):
            at=start+112*index
            source=decode_text(source_flow,at,table,end=at+16).text
            expected=normalize_original_fullwidth_ascii(source.replace('最終話','最终话').replace('話','话'))
            actual=decode_text(stage_data[0],at,readback,end=at+16)
            require(actual.text==expected and actual.terminator=='nul','chart episode label ISO reread')
            counts['chart_episode_labels' if source else 'chart_empty_labels_preserved']+=1
            if source=='最終話':counts['chart_final_episode_labels']+=1
    # Audit all 110 native titles, including the final three missed by the old 107-record loop.
    require(file_sha(BASE)==BASE_SHA,'Z title baseline drift')
    base_flow=decode_production(read_member(BASE,member_map(scan_iso9660(BASE)),st.STAGE)).output
    endings=load(ROOT/'config/editorial/special-disc/chart-z-ending-titles.json')
    corpus={r['id']:r for r in load(ROOT/endings['corpus'])['entries']}
    ending_rows={r['index']:r for r in endings['entries']}
    require(sorted(ending_rows)==[107,108,109],'Z ending inventory drift')
    require(struct.unpack_from('<I',source_flow,0x17C94)[0]==st.sd.SD_STAGE_BASE+0x14B20,'Z title table pointer drift')
    require(struct.unpack_from('<h',source_flow,0x14B20+110*112+0x50)[0]==70,'Z title terminator drift')
    title_audit=[]
    for index in range(110):
        at=0x14B30+112*index;source=decode_text(source_flow,at,table,end=at+64).text
        if index in ending_rows:
            binding=ending_rows[index];row=corpus[binding['corpus_id']]
            require(binding['offset']==at and binding['max_bytes']==64,'Z ending field drift')
            require(source==binding['source_text'] and sha(source.encode())==binding['source_text_sha256']==row['source_text_sha256'],'Z ending source mismatch')
            expected=normalize_original_fullwidth_ascii(row['translation']).replace(' ','　')
            counts['chart_z_ending_titles']+=1
        else:
            expected=decode_text(base_flow,at,readback,end=at+64).text
            require(stage_data[0][at:at+64]==base_flow[at:at+64],'existing Z title bytes changed')
        actual=decode_text(stage_data[0],at,readback,end=at+64)
        require(actual.text==expected and actual.terminator=='nul','Z title ISO reread')
        require(not re.search('[\u3040-\u30ff]',actual.text),'untranslated kana in Z title')
        title_audit.append(dict(index=index,offset=at,source_text=source,output_text=actual.text,verification='main-stage-name-corpus' if index in ending_rows else 'preserved-translated-baseline'))
        counts['chart_z_titles_audited']+=1
    write_json(WORK/'z-title-audit.json',dict(iso=manifest['iso'],titles=title_audit))
    help_config=load(ROOT/'config/editorial/special-disc/chart-key-help.json')
    original_flow=decode_production(st.read_disc_member(st.STAGE)).output
    for row in help_config['entries']:
        at=row['offset'];size=row['max_bytes'];data=stage_data[0]
        require(decode_text(original_flow,at,table).text==row['source_text'],'chart help source mismatch')
        expected=normalize_original_fullwidth_ascii(row['translation']).replace(' ','　')
        actual=decode_text(data,at,readback,end=at+size)
        require(actual.text==expected and actual.terminator=='nul','chart help final ISO reread')
        for site in row['pointer_sites']:
            require(struct.unpack_from('<I',data,site)[0]==st.sd.SD_STAGE_BASE+at,'chart help final pointer changed')
        counts['chart_key_help']+=1
    # System text: account for every template expansion and every ticker source.
    system=load(WORK/'system/report.json');cd=decode_production(member('DATA/COMPDATA.BN')).output
    shared={r['id']:r for r in system['tail_shared']}
    rows=load(ROOT/'corpus/zh/special-disc/system-text.json')['entries']
    for row in load(ROOT/'corpus/zh/special-disc/frame-text.json')['entries']:
        for target in row['locations']:
            if target.startswith(('sd/exe/','sd/compdata/')):rows.append({**row,'id':target})
    source_stage=(ROOT/'work/build/special-disc/components/flow/DATA/STAGE.BIN').read_bytes()
    ticker_places=collections.defaultdict(list)
    for i in range(1,68):
        for at,text in tickers(decode_production(source_stage[off[i]:off[i+1]]).output,table):ticker_places[text].append((i,at))
    for row in rows:
        target=row['id'];expected=two_byte_visible_spaces(normalize_original_fullwidth_ascii(row['translation']))
        if target=='sd/exe/wallpaper-names':
            original_exe=st.read_disc_member('SLPS_259.20')
            for at in row['locations']:
                source=decode_text(original_exe,at,table).text;number=int(source.translate(FULLWIDTH_DIGITS)[-3:])
                require(decode_text(exe,at,readback).text==expected.format(n=number),'wallpaper template ISO reread');counts['system_writes']+=1
        elif target.startswith('sd/ticker/'):
            places=ticker_places[row['source_text']];require(bool(places),f'ticker has no native occurrence: {target}')
            for i,at in places:
                require(decode_text(stage_data[i],at,readback).text==expected,'ticker ISO reread');counts['ticker_slots']+=1
            counts['ticker_sources']+=1
        else:
            require(target.startswith(('sd/exe/','sd/compdata/')),'unknown system source kind')
            at=int(shared[target]['now'],16) if target in shared else int(target.rsplit('/',1)[1],16)
            data=exe if target.startswith('sd/exe/') else cd
            require(decode_text(data,at,readback).text==expected,f'system ISO reread: {target}');counts['system_writes']+=1
            for site in shared.get(target,{}).get('pointer_slots',[]):require(struct.unpack_from('<I',data,int(site,16))[0]==st.sd.COMPDATA_BASE+at,'shared system title pointer')
    result=dict(status='all_bound_text_reread_from_final_iso',iso=manifest['iso'],counts=dict(counts),component_hashes_verified=True,scope='STAGE dialogue/speakers/conditions/formations; frame physical records; system writes/templates/tickers. SRVC and indexed image component readbacks are bound to exact ISO member hashes.')
    result['weapon_detail_labels']=weapon_labels
    result['scope']+=' Weapon category/effect-2 MIPS strings and surrounding native instructions.'
    write_json(WORK/'independent-readback.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
