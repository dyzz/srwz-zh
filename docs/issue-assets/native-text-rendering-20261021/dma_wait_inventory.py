"""Three independently derived native busy-wait and timeout recovery bindings.
Interrupt services and diagnostic output are external leaves for the planned
integer/MMIO-shadow proof; this inventory does not prove CP0 device semantics.
"""
from pathlib import Path
import json,sys,ctypes,hashlib
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;inv=json.loads((OUT/'submission-inventory.json').read_text());results=[];md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in inv['editions'] if x['edition']==ed);wait=int(r['functions']['wait_channel']['entry'],16)
 def call(pc):
  w=e.words(pc,1)[0];assert w>>26==3;return (w&0x3ffffff)<<2
 recovery=call(wait+0x40);diagnostic=call(wait+0x38);disable=call(recovery+0x10);restore=call(recovery+0x78)
 hi=e.words(wait+0x28,1)[0];lo=e.words(wait+0x3c,1)[0];format_address=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;message=e.read(format_address,96).split(b'\0')[0]
 assert e.words(wait+0xc,1)==(0x3c110100,);assert e.words(wait+0x30,1)==(0x06210005,);assert e.words(wait+0x54,1)==(0x2631ffff,)
 functions={name:dict(entry=hex(start),end=hex(end),sha256=hashlib.sha256(e.read(start,end-start)).hexdigest()) for name,start,end in [('wait',wait,wait+0x70),('recovery',recovery,recovery+0x98),('interrupt_enter',disable,disable+0x50),('interrupt_exit',restore,restore+0x18)]}
 listing=[]
 for name,f in functions.items():
  listing.append('\n; '+name)
  for pc in range(int(f['entry'],16),int(f['end'],16),4):
   w=e.words(pc,1)[0];listing.append(f'{pc:08x} {w:08x} {decode(md,w,pc)[0]}')
 (OUT/f'{ed}-dma-wait.asm').write_text('\n'.join(listing)+'\n');results.append(dict(edition=ed,native_executable=lock,functions=functions,diagnostic_entry=hex(diagnostic),format_address=hex(format_address),format_hex=message.hex(),counter_seed=0x1000000,mmio=dict(enable_read='0x1000f520',enable_write='0x1000f590',dmac_control='0x1000e000')))
 print(ed,'native wait/recovery',hex(wait),hex(recovery),'counter seed',0x1000000,flush=True)
(OUT/'dma-wait-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=results),indent=2)+'\n')
