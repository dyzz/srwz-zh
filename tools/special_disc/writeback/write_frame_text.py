"""Write SP fixed pages, chart text, synopses, titles, narration and map names.

All surfaces use the shared font proposal. Each surface has its own cell/line
budget. Inputs are the preserved two-stage candidate; STAGE chunk zero is
composed with the full-stage writer by the final assembler.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).resolve().parent)]
import migrate_stage_dialogue as stage
from srwz.codec import decode_production,reencode_changed_suffix
from srwz.iso9660 import member_map,scan_iso9660
from srwz.chinese_layout import ChineseLayoutProfile,fit_chinese_dialogue_layout,load_layout_profiles,rendered_line_width,reflow_chinese_paragraph
from srwz.text import decode_text,encode_text,normalize_original_fullwidth_ascii
from srwz.summary import parse_summary
from srwz.writers import apply_summary_replacements
from stage_bindings import digest
from special_disc.baselines import baseline_iso

sd=stage.sd
EPISODE_LABELS=ROOT/'config/editorial/special-disc/chart-episode-labels.json'
Z_ENDINGS=ROOT/'config/editorial/special-disc/chart-z-ending-titles.json'
Z_TITLE_CORPUS=ROOT/'corpus/zh/menu/stage-names.json'
KEY_HELP=ROOT/'config/editorial/special-disc/chart-key-help.json'
HSFC_PROTECTED_TERMS=('麦康奈尔','布兰少校','西尔维娅','金卡拉姆')


def require(condition,message):
    if not condition: raise ValueError(message)


def paragraphs(text,width,*,max_lines=None,protected_terms=()):
    """Keep authored paragraphs and blank separators, wrap within each paragraph."""
    lines=[]
    for paragraph in normalize_original_fullwidth_ascii(text).split('\n'):
        if not paragraph.strip():
            lines.append('');continue
        indent='　' if paragraph.startswith(('　',' ')) else ''
        profile=ChineseLayoutProfile(profile_id='sp-fixed-paragraph',maximum_width=width-len(indent),
            first_line_maximum_width=None,maximum_lines=None,
            line_count_mode='minimum',line_packing='fill',allow_oversized_token_split=True)
        fitted=reflow_chinese_paragraph(paragraph.strip(),profile=profile,protected_terms=protected_terms).text.split('\n')
        fitted[0]=indent+fitted[0];lines.extend(fitted)
    require(max_lines is None or len(lines)<=max_lines,f'paragraph overflow: {len(lines)}/{max_lines} lines')
    return lines


class Writer:
    def __init__(self,iso,proposal):
        self.iso=iso;self.members=member_map(scan_iso9660(iso));self.base={};self.original={};self.output={};self.rows=[];self.codecs=[];self.key_help=[];self.episode_labels=[];self.z_ending_titles=[]
        self.table,_,self.codes,self.readback=stage.mst.encoding_tables(proposal)
        self.codes=dict(self.codes)
        self.frames=json.loads((ROOT/'corpus/zh/special-disc/frame-text.json').read_text())['entries']
        self.targets={target:row for row in self.frames for target in row['locations']}
        self.exe=self.member('SLPS_259.20');self.original_exe=stage.read_disc_member('SLPS_259.20')
        self.profiles=load_layout_profiles(stage.PROFILES)

    def member(self,name):
        if name not in self.base:
            m=self.members[name]
            with self.iso.open('rb') as stream:
                stream.seek(m.extent_lba*2048);self.base[name]=stream.read(m.size)
        return self.base[name]

    def original_member(self,name):
        if name not in self.original:self.original[name]=stage.read_disc_member(name)
        return self.original[name]

    def bind(self,target,source):
        row=self.targets[target]
        require(digest(source)==row['source_text_sha256'],f'{target}: source drift: {source!r}')
        return row

    def encoded(self,text,terminate=True):
        return encode_text(normalize_original_fullwidth_ascii(text).replace(' ','　'),self.table,overrides=self.codes,terminate=terminate)

    def fixed(self,data,offset,size,text,target):
        payload=self.encoded(text)
        require(len(payload)<=size,f'{target}: {len(payload)} encoded bytes exceed {size}')
        data[offset:offset+size]=payload+bytes(size-len(payload))
        actual=decode_text(bytes(data),offset,self.readback)
        require(actual.text==normalize_original_fullwidth_ascii(text).replace(' ','　'),f'{target}: readback mismatch')

    def record(self,target,text,**extra):
        row=self.targets[target]
        self.rows.append(dict(target=target,corpus_id=row['id'],source_text_sha256=row['source_text_sha256'],
                             editorial_status=row['editorial_status'],output_text=text,**extra))

    def compressed(self,name,index,data,table_start):
        source=self.output.get(name,self.member(name));offsets=sd.table_offsets(self.exe,table_start,len(source))
        a,b=offsets[index:index+2];stored=source[a:b];decoded=decode_production(stored)
        require(len(data)==len(decoded.output),f'{name}/{index}: decoded size changed')
        strategy='rust-maximum' if name=='DATA/HSFC.BIN' else 'rust-fit'
        packed=reencode_changed_suffix(stored,data,strategy=strategy,
            min_match_length=2 if name=='DATA/HSFC.BIN' else 3,max_output_size=b-a,original_result=decoded)
        require(decode_production(packed).output==data,'codec reread')
        self.output[name]=source[:a]+packed+bytes(b-a-len(packed))+source[b:]
        self.codecs.append(dict(member=name,chunk=index,allocated=b-a,compressed=len(packed)))

    def vt1(self):
        name='DATA/VT1.BIN';original=self.original_member(name);original_offsets=sd.table_offsets(self.original_exe,sd.VT1_TABLE,len(original))
        current=self.member(name);offsets=sd.table_offsets(self.exe,sd.VT1_TABLE,len(current))
        for index,per_entry in sd.VT1_PAGES.items():
            src=decode_production(original[original_offsets[index]:original_offsets[index+1]]).output
            data=bytearray(decode_production(current[offsets[index]:offsets[index+1]]).output)
            require(bytes(data)==src,f'VT1 fixed page {index} preimage changed')
            raw_lines=src.splitlines(keepends=True)
            require(all(len(line)==57 and line.endswith(b'\n') for line in raw_lines),'VT1 fixed grid is not 56 bytes + LF')
            for page in range(len(raw_lines)//per_entry):
                target=f'sd/vt1/{index}/{page}'
                start=page*per_entry;lines=[line[:-1].decode('cp932') for line in raw_lines[start:start+per_entry]]
                heading=1 if index==40 else 0
                row=self.bind(target,sd.page_text(lines[heading:]))
                authored=row['translation'].split('\n')
                question=authored[-1].strip() if heading and authored[-1].startswith('　'*4) else None
                if question:authored=authored[:-1]
                body=paragraphs('\n'.join(authored),28,max_lines=per_entry-heading-bool(question))
                body+=['']*(per_entry-heading-bool(question)-len(body))
                if question:body.append('　'*max(0,(28-len(question))//2)+question)
                if heading:
                    if page:
                        title=self.targets[f'sd/group/{page}']['translation']
                        self.bind(f'sd/group/{page}',lines[0].strip('　'))
                        self.record(f'sd/group/{page}',title,member=name,chunk=index,page=page,row=0)
                    else:title='数据链接'
                    body=['　'+title]+body
                for number,line in enumerate(body):
                    payload=self.encoded(line,False)
                    require(len(payload)%2==0 and len(payload)<=56,f'{target}: grid line {number} overflow')
                    payload+=bytes.fromhex('8140')*((56-len(payload))//2)
                    at=(start+number)*57;data[at:at+57]=payload+b'\n'
                    actual=decode_text(payload+b'\0',0,self.readback).text.rstrip('　')
                    require(actual==normalize_original_fullwidth_ascii(line).replace(' ','　').rstrip('　'),f'{target}: grid reread')
                self.record(target,'\n'.join(body),member=name,chunk=index,page=page,width=28,lines=per_entry)
            self.compressed(name,index,bytes(data),sd.VT1_TABLE)

    def hsfc(self):
        name='DATA/HSFC.BIN';orig=self.original_member(name);offs=sd.table_offsets(self.original_exe,sd.HSFC_TABLE,len(orig));src=decode_production(orig[offs[0]:offs[1]]).output
        current=self.member(name);offs=sd.table_offsets(self.exe,sd.HSFC_TABLE,len(current));data=bytearray(decode_production(current[offs[0]:offs[1]]).output)
        first,cell,cells,_=sd.HSFC_SUMMARIES
        for target,row in self.targets.items():
            if not target.startswith('sd/hsfc/'):continue
            record=int(target.rsplit('/',1)[1]);at=first+record*cell*cells
            source='\n'.join(decode_text(src,at+j*cell,self.table,end=at+(j+1)*cell).text for j in range(cells))
            self.bind(target,source)
            text=fit_chinese_dialogue_layout(row['translation'],profile=self.profiles['scenario_chart_overview'],
                protected_terms=HSFC_PROTECTED_TERMS).text
            lines=text.split('\n');require(len(lines)<=3,'HSFC exceeds three lines');lines+=['']*(3-len(lines))
            for j,line in enumerate(lines):self.fixed(data,at+j*cell,cell,line,target)
            self.record(target,text,member=name,chunk=0,offset=at,width=21,lines=3)
        self.compressed(name,0,bytes(data),sd.HSFC_TABLE)

    def narration(self):
        name='DATA/MTZSPROS.BIN';orig=self.original_member(name);offs=sd.table_offsets(self.original_exe,sd.MTZSPROS_TABLE,len(orig))
        current=self.member(name);now=sd.table_offsets(self.exe,sd.MTZSPROS_TABLE,len(current))
        for index,(a,b) in enumerate(zip(offs,offs[1:])):
            src=decode_production(orig[a:b]).output;parsed=parse_summary(src,self.table,chunk_index=index)
            data=decode_production(current[now[index]:now[index+1]]).output;require(data==src,'narration preimage changed')
            replacements={}
            for j,entry in enumerate(parsed.entries):
                target=f'sd/mtzspros/{index:02d}/{j}';row=self.bind(target,entry.text)
                width=max(len(line)-len(line.lstrip('　'))+rendered_line_width(line) for line in entry.text.split('\n'))
                text='\n'.join(paragraphs(row['translation'],width,max_lines=len(entry.text.split('\n')),protected_terms=('下达',))).replace(' ','　')
                replacements[entry.entry_id]=text;self.record(target,text,member=name,chunk=index,width=width,lines=len(text.split('\n')))
            rebuilt=apply_summary_replacements(data,self.table,chunk_index=index,replacements=replacements,overrides=self.codes)
            self.compressed(name,index,rebuilt,sd.MTZSPROS_TABLE)

    def flow(self):
        name='DATA/STAGE.BIN';source=self.original_member(name);src=decode_production(source).output
        current=self.member(name);hb=stage.read_disc_member(stage.HB);slot=struct.unpack_from('<I',hb,sd.HB_STAGE_TABLE+4)[0]
        decoded=decode_production(current[:slot]);data=bytearray(decoded.output)
        for target,row in self.targets.items():
            if target.startswith('sd/flow/episode/'):
                k=int(target.rsplit('/',1)[1]);at=sd.FLOW_EPISODES[0]+k*sd.FLOW_EPISODES[1]+0x20
                self.bind(target,decode_text(src,at,self.table,end=at+64).text)
                text=row['translation'];self.fixed(data,at,64,text,target);self.record(target,text,member=name,chunk=0,offset=at)
            elif target.startswith('sd/flow/synopsis/'):
                k=int(target.rsplit('/',1)[1])-1;site=sd.FLOW_SYNOPSES[0]+k*4;at=struct.unpack_from('<I',src,site)[0]-sd.SD_STAGE_BASE
                original=decode_text(src,at,self.table);self.bind(target,original.text)
                text='\n'.join(paragraphs(row['translation'],29))
                self.fixed(data,at,original.consumed,text,target);self.record(target,text,member=name,chunk=0,offset=at,width=29)
        labels=json.loads(EPISODE_LABELS.read_text())
        require(labels['member']==name and labels['chunk']==0 and labels['label_bytes']==16 and labels['record_stride']==112,'episode label layout drift')
        require([(x['offset'],x['count'])for x in labels['tables']]==[(0x7510,21),(0x14B20,110)],'episode label table drift')
        for table_index,table in enumerate(labels['tables']):
            require(struct.unpack_from('<I',src,0x17C90+4*table_index)[0]==sd.SD_STAGE_BASE+table['offset'],'chart node pointer drift')
            end=table['offset']+table['count']*112
            require(struct.unpack_from('<h',src,end+0x50)[0]==70,'chart table terminator drift')
            for index in range(table['count']):
                at=table['offset']+index*112;original=decode_text(src,at,self.table,end=at+16)
                require(original.terminator=='nul' and not any(src[at+original.consumed:at+16]),'episode label field ownership')
                require(data[at:at+16]==src[at:at+16],'episode label current preimage drift')
                if not original.text:continue
                if original.text==labels['final_label']['source']:text=labels['final_label']['translation']
                else:
                    require(re.fullmatch('第[０-９]+話',original.text) is not None,'unknown episode label')
                    text=original.text[:-1]+labels['numbered_suffix']['translation']
                text=normalize_original_fullwidth_ascii(text)
                target=f"sd/flow/label/{at:05X}"
                self.fixed(data,at,16,text,target)
                self.episode_labels.append(dict(target=target,offset=at,max_bytes=16,source_text=original.text,output_text=text,chart=table['name']))
        endings=json.loads(Z_ENDINGS.read_text())
        require(endings['member']==name and endings['chunk']==0 and endings['corpus']==str(Z_TITLE_CORPUS.relative_to(ROOT)), 'Z ending input scope drift')
        require([r['index'] for r in endings['entries']]==[107,108,109], 'Z ending inventory drift')
        corpus={r['id']:r for r in json.loads(Z_TITLE_CORPUS.read_text())['entries']}
        for binding in endings['entries']:
            at=binding['offset'];size=binding['max_bytes'];row=corpus[binding['corpus_id']]
            require(at==0x14B30+112*binding['index'] and size==64,'Z ending title field drift')
            original=decode_text(src,at,self.table,end=at+size)
            require(original.text==binding['source_text'] and digest(original.text)==binding['source_text_sha256']==row['source_text_sha256'],'Z ending source drift')
            require(original.terminator=='nul' and not any(src[at+original.consumed:at+size]),'Z ending title field ownership')
            require(data[at:at+size]==src[at:at+size],'Z ending title preimage drift')
            target=f"sd/flow/z-ending/{binding['index']}"
            self.fixed(data,at,size,row['translation'],target)
            self.z_ending_titles.append(dict(binding,target=target,output_text=row['translation'],editorial_status=row['editorial_status']))
        help_config=json.loads(KEY_HELP.read_text())
        require(help_config['member']==name and help_config['chunk']==0 and len(help_config['entries'])==5,'chart help scope drift')
        for row in help_config['entries']:
            at=row['offset'];size=row['max_bytes'];original=decode_text(src,at,self.table)
            require(original.text==row['source_text'] and original.consumed==size,f"{row['id']}: source drift")
            require(bytes(data[at:at+size])==src[at:at+size],f"{row['id']}: current preimage drift")
            sites=[p for p in range(0,len(src)-3,4) if struct.unpack_from('<I',src,p)[0]==sd.SD_STAGE_BASE+at]
            require(sites==row['pointer_sites'],'chart help pointer inventory drift')
            for site in sites:require(data[site:site+4]==src[site:site+4],'chart help pointer changed')
            self.fixed(data,at,size,row['translation'],row['id'])
            self.key_help.append(dict(row,output_text=row['translation'],member=name,chunk=0))
        packed=reencode_changed_suffix(current[:slot],bytes(data),strategy='rust-fit',max_output_size=slot,original_result=decoded)
        self.output[name]=packed+bytes(slot-len(packed))+current[slot:]
        self.codecs.append(dict(member=name,chunk=0,allocated=slot,compressed=len(packed)))

    def titles(self):
        name='DATA/COMPDATA.BN';stored=self.member(name);decoded=decode_production(stored)
        src=decode_production(self.original_member(name)).output;data=bytearray(decoded.output)
        first,stride,count=sd.STAGE_NAME_RECORDS
        pointers={first+i*stride:struct.unpack_from('<I',src,first+i*stride)[0]-sd.COMPDATA_BASE for i in range(count)}
        plans={};regions=[]
        for target,row in self.targets.items():
            if not target.startswith('sd/stage-name/'):continue
            record=int(target.rsplit('/',1)[1])-1;site=first+record*stride;at=pointers[site]
            source=decode_text(src,at,self.table);self.bind(target,source.text)
            end=at+source.consumed;limit=(end+7)&~7
            require(not any(src[end:limit]),f'{target}: nonzero title alignment')
            require(not any(at<x<limit for x in pointers.values()),'title source overlap')
            require(bytes(data[at:limit])==src[at:limit],'title preimage drift')
            payload=self.encoded(row['translation'])
            require(at not in plans or plans[at]['payload']==payload,'title alias translation conflict')
            plans[at]=dict(target=target,text=row['translation'],payload=payload,sites=[p for p,t in pointers.items() if t==at])
            regions.append((at,limit))
        known={p for plan in plans.values() for p in plan['sites']}
        for site in range(0,len(src)-3,4):
            if site in known or any(a<=site<b for a,b in regions):continue
            target=struct.unpack_from('<I',src,site)[0]-sd.COMPDATA_BASE
            require(not any(a<=target<b for a,b in regions),f'untyped title reference {site:X}->{target:X}')
        merged=[]
        for a,b in sorted(set(regions)):
            if merged and a==merged[-1][1]:merged[-1][1]=b
            else:merged.append([a,b])
        pools=[r[:] for r in merged]
        for a,b in merged:data[a:b]=bytes(b-a)
        for old,plan in sorted(plans.items(),key=lambda item:(-len(item[1]['payload']),item[0])):
            candidates=[p for p in pools if p[1]-p[0]>=len(plan['payload'])]
            require(bool(candidates),f"title pool cannot fit {plan['target']}")
            pool=min(candidates,key=lambda p:p[1]-p[0]);at=pool[0];payload=plan['payload']
            data[at:at+len(payload)]=payload;pool[0]=(at+len(payload)+7)&~7
            for site in plan['sites']:
                require(struct.unpack_from('<I',data,site)[0]==sd.COMPDATA_BASE+old,'title pointer preimage drift')
                struct.pack_into('<I',data,site,sd.COMPDATA_BASE+at)
                require(decode_text(bytes(data),struct.unpack_from('<I',data,site)[0]-sd.COMPDATA_BASE,self.readback).text==normalize_original_fullwidth_ascii(plan['text']).replace(' ','　'),'title reread')
            self.record(plan['target'],plan['text'],member=name,old_offset=old,offset=at,pointer_sites=plan['sites'],payload=len(payload))
        stage.check_unowned_bytes(decoded.output,bytes(data),merged,known)
        packed=reencode_changed_suffix(stored,bytes(data),strategy='rust-fit',max_output_size=len(stored),original_result=decoded)
        require(decode_production(packed).output==bytes(data),'title codec readback')
        self.output[name]=packed+bytes(len(stored)-len(packed))
        self.codecs.append(dict(member=name,allocated=len(stored),compressed=len(packed)))

    def mapnames(self):
        name='MAP/MAPNAME.BIN';src=self.original_member(name);data=bytearray(self.member(name))
        for target,row in self.targets.items():
            if not target.startswith('sd/mapname/'):continue
            at=int(target.rsplit('/',1)[1])*sd.MAPNAME_SLOT;self.bind(target,decode_text(src,at,self.table).text)
            self.fixed(data,at,sd.MAPNAME_SLOT,row['translation'],target);self.record(target,row['translation'],member=name,offset=at)
        self.output[name]=bytes(data)


def publish_component(output, report, files):
    """Publish a complete successful component; failed attempts stay separate."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if report['status'] == 'failed':
        output.with_name(output.name+'.failed.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        return False
    with tempfile.TemporaryDirectory(prefix='.'+output.name+'-', dir=output.parent) as directory:
        staging = Path(directory)/'component'; staging.mkdir()
        for name, data in files.items():
            path = staging/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (staging/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        previous = Path(directory)/'previous'
        if output.exists():
            output.rename(previous)
        try:
            staging.rename(output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso',type=Path,help='Optional explicit baseline; defaults to the verified text-canary delta.')
    parser.add_argument('--proposal',type=Path,default=ROOT/'work/build/special-disc/text-candidate/font/proposal.json')
    parser.add_argument('--output',type=Path,default=ROOT/'work/build/special-disc/full-text/frame')
    args=parser.parse_args();writer=Writer(args.iso or baseline_iso('text-canary'),args.proposal);failures=[]
    for surface in ('vt1','hsfc','narration','flow','mapnames','titles'):
        try:getattr(writer,surface)();print(surface,'OK',flush=True)
        except ValueError as error:failures.append(dict(surface=surface,reason=str(error)));print(surface,str(error),flush=True)
    report=dict(z_ending_titles=writer.z_ending_titles,z_ending_inputs=[dict(path=str(p.relative_to(ROOT)),sha256=stage.sha256(p.read_bytes())) for p in (Z_ENDINGS,Z_TITLE_CORPUS)],episode_labels=writer.episode_labels,episode_label_config=dict(path=str(EPISODE_LABELS.relative_to(ROOT)),sha256=stage.sha256(EPISODE_LABELS.read_bytes())),key_help=writer.key_help,key_help_config=dict(path=str(KEY_HELP.relative_to(ROOT)),sha256=stage.sha256(KEY_HELP.read_bytes())),status='failed' if failures else 'static_verified_runtime_pending',failures=failures,bindings=writer.rows,codec=writer.codecs,
                files={name:stage.sha256(data) for name,data in writer.output.items()},base_files={name:stage.sha256(writer.base[name]) for name in writer.output},
                corpus_sha256=stage.sha256((ROOT/'corpus/zh/special-disc/frame-text.json').read_bytes()),proposal_sha256=stage.sha256(args.proposal.read_bytes()))
    if not publish_component(args.output,report,writer.output):raise SystemExit(1)


if __name__=='__main__':main()
