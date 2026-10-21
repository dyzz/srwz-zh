"""Native opcode5039 handler -> entity name table -> context setter binding.
Confirms the same computed runtime table base/stride, not just a +28 offset.
Parameter resolver callees, STAGE command reachability and all producer paths
are not yet proved; this inventory does not claim a natural execution trace.
"""
from pathlib import Path
import json,hashlib,ctypes,sys
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent;original,_=native('original');strings=json.loads((OUT/'string-inventory.json').read_text());owners=json.loads((OUT/'measure-owner-inventory.json').read_text());md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN);rows=[]
for ed in ('original','best','sp'):
 e,lock=native(ed);dispatch=find(e,original.words(0x1bfa10,13));consumer=find(e,original.words(0x3103ec,25))
 def formed(a,b):return ((e.words(a,1)[0]&65535)<<16)+ctypes.c_int16(e.words(b,1)[0]&65535).value
 # move S1,A0, read opcode, subtract lower bound, unsigned bounds, then table.
 w=e.words(dispatch,13);assert w[0]==0x0080882d and w[1]==0x8c830000 and w[2]>>16==0x2465 and w[3]>>16==0x2ca1 and w[11]==0x00a00008
 low=-ctypes.c_int16(w[2]&65535).value;count=w[3]&65535;table=formed(dispatch+0x18,dispatch+0x20);opcode=5039;assert low==5000 and count==71
 handler=e.words(table+4*(opcode-low),1)[0];assert e.words(handler,1)[0]==0x8e230004
 entity_table=formed(handler+0x80,handler+0x88);consumer_table=formed(consumer+12,consumer+24);assert entity_table==consumer_table
 context=formed(consumer+16,consumer+28);owner=next(x for x in owners['editions'] if x['edition']==ed);assert context==owner['owner_config'][0]
 copy=int(next(x for x in strings['editions'] if x['edition']==ed)['functions']['strcpy']['entry'],16)
 first=handler+0x94;second=handler+0xf8
 assert (e.words(first,1)[0]&0x3ffffff)<<2==copy and (e.words(second,1)[0]&0x3ffffff)<<2==copy
 assert e.words(handler+0x74,1)[0]==0x8e250008 and e.words(handler+0xe0,1)[0]==0x8e250008
 # Exact address scaling is 4*i + i, times2, plusi, times16 =176*i.
 assert e.words(handler+0x78,1)[0]==0x00622021 and e.words(handler+0x7c,1)[0]==0x00042040 and e.words(handler+0x84,1)[0]==0x00821021 and e.words(handler+0x8c,1)[0]==0x00021100
 listing=[]
 for name,a,b in [('dispatch',dispatch,dispatch+52),('handler',handler,handler+0x110),('context_consumer',consumer,consumer+0x6c)]:
  listing.append('; '+name)
  for pc in range(a,b,4):listing.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(md,e.words(pc,1)[0],pc)[0]}')
 (OUT/f'{ed}-squad-name-command.asm').write_text('\n'.join(listing)+'\n')
 rows.append(dict(edition=ed,native_executable=lock,opcode=opcode,dispatch=hex(dispatch),dispatch_table=hex(table),dispatch_lower_bound=low,dispatch_entry_count=count,handler=hex(handler),handler_sha256=hashlib.sha256(e.read(handler,0x110)).hexdigest(),entity_table=hex(entity_table),entity_stride=176,name_offset=40,source_pointer_slot='command+8',strcpy_calls=list(map(hex,(first,second))),context_consumer=hex(consumer),context_base=hex(context),unclosed_parameter_helpers=[dict(site=hex(pc),target=hex((e.words(pc,1)[0]&0x3ffffff)<<2)) for pc in range(handler,handler+0x110,4) if e.words(pc,1)[0]>>26==3 and (e.words(pc,1)[0]&0x3ffffff)<<2!=copy]));print(ed,'opcode',opcode,'handler',hex(handler),'entity table',hex(entity_table),flush=True)
(OUT/'squad-name-command-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=rows),indent=2)+'\n')
