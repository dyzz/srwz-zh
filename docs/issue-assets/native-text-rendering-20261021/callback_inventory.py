"""Name-entry vtable storage and validation-to-confirmation indirect edge."""
from pathlib import Path
import json,ctypes,sys,hashlib
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN);writers=json.loads((OUT/'name-writer-inventory.json').read_text())
for ed in ('original','best','sp'):
 e,lock=native(ed);constructor=find(e,src.words(0x30ba00,20));gate=find(e,src.words(0x2c46e0,20));hi=e.words(constructor+0x1c,1)[0];lo=e.words(constructor+0x24,1)[0];vtable=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value
 writer=int(next(x for x in writers['editions'] if x['edition']==ed)['entry'],16);assert e.words(vtable+0x98,1)[0]==writer;assert e.words(gate+0xf0,1)[0]==0x0320f809
 branch=e.words(gate+0xf8,1)[0];assert branch>>26==4;exit=gate+0xfc+ctypes.c_int16(branch&65535).value*4
 lines=[]
 for name,a,b in [('constructor_vtable_store',constructor,constructor+0x34),('nonblank_validation_and_indirect_dispatch',gate,gate+0x108)]:
  lines.append(f'; {name} {a:08x}..{b:08x}')
  for p in range(a,b,4):lines.append(f'{p:08x} {e.words(p,1)[0]:08x} {decode(m,e.words(p,1)[0],p)[0]}')
 (OUT/f'{ed}-name-callback.asm').write_text('\n'.join(lines)+'\n');rows.append({'edition':ed,'native_executable':lock,'constructor':hex(constructor),'vtable':hex(vtable),'confirmation_slot':'0x98','confirmation_word':hex(vtable+0x98),'confirmation_target':hex(writer),'validation_block':hex(gate),'validation_end':hex(gate+0x108),'dispatch_call':hex(gate+0xf0),'common_exit':hex(exit),'validated_block_sha256':hashlib.sha256(e.read(gate,0x108)).hexdigest()});print(ed,hex(vtable),'slot98 ->',hex(writer),'gate',hex(gate),flush=True)
(OUT/'callback-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
