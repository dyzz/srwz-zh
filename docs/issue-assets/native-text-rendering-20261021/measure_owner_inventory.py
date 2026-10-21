"""Native selected-entry iterator, context setters and actual UI-to-cache windows.
The secondary setter's two selection-service callees remain unclosed; locating
its store is not a proof of its full effects. Global producer completeness and
actual UI lifetime are not inferred from this bounded inventory.
"""
from pathlib import Path
import json,sys,ctypes,hashlib
from inventory import native,decode
from resource_inventory import find,text_sections
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone,struct
OUT=Path(__file__).parent;source,_=native('original');up=json.loads((OUT/'measure-upstream-inventory.json').read_text());si=json.loads((OUT/'measure-source-inventory.json').read_text());rows=[]
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);u=next(x for x in up['editions'] if x['edition']==ed);s=next(x for x in si['editions'] if x['edition']==ed);it=find(e,source.words(0x34dd10,24));first=find(e,source.words(0x39b440,20));second=find(e,source.words(0x39b550,20));reset=it-16;getter=it+0xa0
 assert e.words(reset+4,1)[0]==0x03e00008 and e.words(getter+4,1)[0]==0x03e00008 and e.words(it+0x90,1)[0]==0x03e00008
 def formed(a,b):return ((e.words(a,1)[0]&65535)<<16)+ctypes.c_int16(e.words(b,1)[0]&65535).value
 cursor=formed(it,it+4);limit=formed(it+8,it+12);index=formed(it+16,it+20);selected=formed(getter,getter+8);alias=formed(it+0x84,it+0x88);table=formed(it+0x44,it+0x48)
 mirror0=formed(first+0x20,first+0x40);mirror1=formed(first+0x48,first+0x4c);context=int(s['tail_wrapper_argument_globals'][0],16)-4
 assert context+0xcc==int(s['tail_wrapper_argument_globals'][1],16)
 services=[]
 for pc in range(second,second+0x88,4):
  w=e.words(pc,1)[0]
  if w>>26==3:services.append(dict(site=hex(pc),target=hex((w&0x3ffffff)<<2)))
 assert len(services)==2;windows=[]
 for caller in u['initializer_direct_callers']:
  if caller['kind']!='JAL':continue
  call=int(caller['site'],16);entry=call-0x28;branch=call-0x18;w=e.words(branch,1)[0];assert w>>26==5
  assert (e.words(entry,1)[0]&0x3ffffff)<<2==it
  assert (e.words(call-16,1)[0]&0x3ffffff)<<2==getter==int(caller['argument_sources']['second_argument_getter'],16)
  failure=branch+4+4*ctypes.c_int16(w&65535).value;success=call+8
  fw=e.words(failure,5)
  if fw[0]>>26==15:
   assert fw[1]>>16==0x8c22 and fw[2]==0x24030014 and fw[4]==0xa0430000
   state_slot=formed(failure,failure+4);failure_config=[state_slot,1,1];failure_branch=failure+12
  else:
   assert fw[0]==0x24020014 and fw[1]>>16==0x3c01 and fw[3]>>16==0xa422
   state_slot=formed(failure+4,failure+12);failure_config=[state_slot,0,2];failure_branch=failure+8
  bw=e.words(failure_branch,1)[0];assert bw>>16==0x1000
  failure_join=failure_branch+4+4*ctypes.c_int16(bw&65535).value
  windows.append(dict(start=hex(entry),branch=hex(branch),success_stop=hex(success),failure_entry=hex(failure),failure_stop=hex(failure_join),failure_config=failure_config,failure_block_sha256=hashlib.sha256(e.read(failure,failure_branch+8-failure)).hexdigest(),sha256=hashlib.sha256(e.read(entry,success-entry)).hexdigest()))
 functions={'iterator':(it,it+0x98),'reset':(reset,reset+16),'getter':(getter,getter+16),'primary_setter':(first,first+0x58),'secondary_setter':(second,second+0x88)};function_rows={}
 listing=[]
 for name,(a,b) in functions.items():
  function_rows[name]=dict(entry=hex(a),end=hex(b),sha256=hashlib.sha256(e.read(a,b-a)).hexdigest());listing.append('; '+name)
  for pc in range(a,b,4):listing.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(md,e.words(pc,1)[0],pc)[0]}')
 for win in windows:
  listing.append('; caller window')
  for pc in range(int(win['start'],16),int(win['success_stop'],16),4):listing.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(md,e.words(pc,1)[0],pc)[0]}')
  listing.append('; failure block')
  for pc in range(int(win['failure_entry'],16),int(win['failure_entry'],16)+(20 if win['failure_config'][1] else 16),4):listing.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(md,e.words(pc,1)[0],pc)[0]}')
 (OUT/f'{ed}-measure-owner.asm').write_text('\n'.join(listing)+'\n')
 setter_callers=[]
 for va,off,n in text_sections(e):
  for k in range(0,n,4):
   w=struct.unpack_from('<I',e.b,off+k)[0]
   if w>>26!=3 or (w&0x3ffffff)<<2 not in (first,second):continue
   pc=va+k;setter_callers.append(dict(site=hex(pc),target=hex((w&0x3ffffff)<<2),context=[dict(pc=hex(a),asm=decode(md,e.words(a,1)[0],a)[0]) for a in range(pc-28,pc+8,4)]))
 row=dict(edition=ed,native_executable=lock,functions=function_rows,caller_windows=windows,secondary_external_services=services,setter_direct_call_candidates=setter_callers,owner_config=[context,cursor,limit,index,selected,alias,table,mirror0,mirror1],globals=dict(context=hex(context),cursor=hex(cursor),limit=hex(limit),index=hex(index),selected=hex(selected),alias=hex(alias),table=hex(table),mirror_primary=hex(mirror0),mirror_member=hex(mirror1)))
 rows.append(row);print(ed,row['globals'],'setter calls',len(setter_callers),flush=True)
(OUT/'measure-owner-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=rows),indent=2)+'\n')
