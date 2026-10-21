"""Native name-entry confirmation writer bindings and immutable default strings."""
from pathlib import Path
import json,ctypes,sys,hashlib
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN);inv=json.loads((OUT/'inventory.json').read_text())
for ed in ('original','best','sp'):
 e,lock=native(ed);a=find(e,src.words(0x30c430,20));b=a+0x1fc;assert e.words(b-8,1)[0]==0x03e00008
 row=next(x for x in inv['editions'] if x['edition']==ed);subs=[]
 for i in range(4):
  h=int(row['controls'][12+i]['target'],16);subs.append(((e.words(h+0x14,1)[0]&65535)<<16)+ctypes.c_int16(e.words(h+0x1c,1)[0]&65535).value)
 calls=[]
 for pc in range(a,b,4):
  w=e.words(pc,1)[0]
  if w>>26==3:calls.append({'site':hex(pc),'target':hex((w&0x3ffffff)<<2)})
 assert len(calls)==3 and len({x['target'] for x in calls})==1
 (OUT/f'{ed}-name-writer.asm').write_text('\n'.join(f'{p:08x} {e.words(p,1)[0]:08x} {decode(m,e.words(p,1)[0],p)[0]}' for p in range(a,b,4))+'\n')
 rows.append({'edition':ed,'native_executable':lock,'entry':hex(a),'end':hex(b),'substitution_buffers':[hex(x) for x in subs],'copy_calls':calls,'input_slot_to_substitution':[[0x50,1],[0x54,2],[0x58,0]],'entry_sha256':hashlib.sha256(e.read(a,b-a)).hexdigest()});print(ed,hex(a),'strcpy',calls[0]['target'],flush=True)
(OUT/'name-writer-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
