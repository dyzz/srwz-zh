"""Native reserved-height audit with structural owners, three editions.
Covers all decoded STAGE bytes, library text fields, COMPDATA raw candidates,
indexed battle subtitles and executable byte candidates. Does not certify
unexamined image/resource formats or runtime-manufactured control strings.
"""
from pathlib import Path
import sys,json,hashlib,struct,re
OUT=Path(__file__).parent;ROOT=OUT.parents[2];sys.path[:0]=[str(ROOT/'tools'),str(OUT),'/tmp/srwz-font-audit-deps']
from inventory import native,decode as disasm
from srwz.iso9660 import member_map,scan_iso9660
from srwz.codec import decode_production
from srwz.stage import parse_stage,parse_stage_system_dialogues
from srwz.text import load_text_table,decode_text
from srwz.library import ZKAN_TEXT_TAGS
from srwz.srvc import parse_srvc_archive
import srwz.srvc as srvc_module
from srwz.image_export import parse_seg_offsets
from special_disc.writeback.migrate_library import raw_fields,sp_offsets,ARCHIVES
import capstone
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
table=load_text_table(ROOT/'vendor/upstream-python/project/tbl_all.json');original=json.loads((ROOT/'config/library/v0.2.0.json').read_text())['source_member_locks'];best={r['member']:r for r in json.loads((ROOT/'config/editions/best/source-layout.json').read_text())['archive_tables']};results=[]
def hits(data):
 result=[]
 for value in range(0x8a,0x8f):
  at=data.find(bytes([0x33,value]))
  while at>=0:result.append((at,value));at=data.find(bytes([0x33,value]),at+1)
 return sorted(result)
for ed in ('original','best','sp'):
 e,lock=native(ed);cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());iso=ROOT/cfg['source_iso']['path'];members=member_map(scan_iso9660(iso));locks={}
 def read(name):
  m=members[name]
  with iso.open('rb') as f:f.seek(m.extent_lba*2048);data=f.read(m.size)
  locks[name]=hashlib.sha256(data).hexdigest();return data
 exe=read(cfg['executable']['member']);assert exe==e.b
 stage,hb=read('DATA/STAGE.BIN'),read('HEDBDY/HB.BIN');offsets=sp_offsets(hb,0x5170 if ed=='sp' else 30320,len(stage));base=int(cfg['layout']['stage_base'],16);ft=int(cfg['layout']['stage_function_table'],16);stage_fields=0;system_fields=0;metadata=[];stage_hash=hashlib.sha256()
 for index,(a,b) in enumerate(zip(offsets,offsets[1:])):
  data=decode_production(stage[a:b]).output;stage_hash.update(data);parsed=parse_stage(data,table,stage_index=index,function_address=struct.unpack_from('<I',exe,ft+index*4)[0],base_address=base);stage_fields+=len(parsed.entries)
  if index==0:system_fields+=len(parse_stage_system_dialogues(data,table,base_address=base))
  for at,value in hits(data):
   assert at==0x13 and data[0x10:0x14]==b'MWo3',(ed,index,hex(at),'nonheader reserved height bytes')
   name=data[0x30:0x50].split(b'\0')[0].decode();assert re.fullmatch(r'stg_[0-9a-z]+\.bin',name)
   metadata.append(dict(chunk=index,offset=at,parameter=value,header_magic='MWo3',header_word14=struct.unpack_from('<I',data,0x14)[0],native_name=name))
 library_fields=0
 for member in ARCHIVES:
  data=read(member)
  if ed=='sp':off=sp_offsets(exe,ARCHIVES[member][1],len(data))
  else:
   start=int(original[member]['slps_table_start'],16) if ed=='original' else best[member]['best_start'];count=original[member]['expected_chunk_count'];off=list(struct.unpack_from('<'+str(count)+'I',exe,start));
   if off[-1]!=len(data):off.append(len(data))
  for index,(a,b) in enumerate(zip(off,off[1:])):
   for tag,payload in raw_fields(decode_production(data[a:b]).output)[1]:
    if tag not in ZKAN_TEXT_TAGS:continue
    library_fields+=1;assert not hits(payload),(ed,member,index,tag,'reserved height operand')
 comp=decode_production(read('DATA/COMPDATA.BN')).output;pilot_start,pilot_stride,pilot_count=(0x2b50,178,969) if ed=='sp' else (0x2160,176,933);stats=[]
 for at,value in hits(comp):
  index,relative=divmod(at-pilot_start,pilot_stride)
  assert 0<=index<pilot_count and relative>=69,(ed,'reserved bytes outside pilot metadata',hex(at),index,relative)
  assert struct.unpack_from('<H',comp,pilot_start+index*pilot_stride)[0]==index
  stats.append(dict(offset=at,parameter=value,pilot=index,record_offset=relative,classification='pilot binary fields after three fixed name slots'))
 srvc_module.SRVC_MAGIC=0x4f01 if ed=='sp' else 0x4f00
 srvc=read('BTL/SRVC.BIN');segments=parse_seg_offsets(read('BTL/SRVC.SEG'),len(srvc));battle=parse_srvc_archive(srvc,segments,table);battle_fields=0
 for chunk in battle:
  for record in chunk.records:
   battle_fields+=1;payload=srvc[record.archive_text_start:record.archive_text_end];assert not hits(payload),(ed,chunk.chunk_index,record.record_index,'battle reserved height operand')
 executable=[]
 for at,value in hits(exe):
  word_at=at&~3;word=struct.unpack_from('<I',exe,word_at)[0];entry=dict(offset=at,parameter=value,word=hex(word))
  if at%4==2 and word>>26==0x23 or ed=='sp' and at==0x30e855:
   entry['classification']='native instruction-byte candidate';entry['instruction']=disasm(md,word,word_at+({'original':0xfe580,'best':0xfe580,'sp':0xff680}[ed]))[0]
  else:
   left=right=word_at
   while left>=4 and struct.unpack_from('<I',exe,left-4)[0]<struct.unpack_from('<I',exe,left)[0]:left-=4
   while right+8<=len(exe) and struct.unpack_from('<I',exe,right)[0]<struct.unpack_from('<I',exe,right+4)[0]:right+=4
   values=struct.unpack_from('<'+str((right-left)//4+1)+'I',exe,left);assert values[0]==0 and len(values)>1000,(ed,'unclassified executable bytes',entry)
   entry.update(classification='monotone u32 resource-offset table candidate',table_start=left,table_end=right+4,entry_count=len(values),first=values[0],last=values[-1])
  executable.append(entry)
 results.append(dict(edition=ed,native_executable=lock,member_sha256=locks,stage_chunks=len(offsets)-1,stage_entries=stage_fields,system_dialogue_entries=system_fields,decoded_stage_sequence_sha256=stage_hash.hexdigest(),stage_nontext_header_hits=metadata,library_fields=library_fields,compdata_nontext_stat_hits=stats,battle_indexed_fields=battle_fields,executable_candidates=executable,text_operand_conflicts=[]))
 print(ed,'stage',stage_fields,'system',system_fields,'library',library_fields,'battle',battle_fields,'text records: no reserved height operands',flush=True)
(OUT/'native-optical-operand-audit.json').write_text(json.dumps(dict(scope=__doc__,status='no_reserved_height_operands_in_declared_native_structured_text_domains',editions=results,unproven=['other resource/text formats outside listed owners','runtime-generated control strings','whole-program executable instruction/table reachability']),indent=2)+'\n')
