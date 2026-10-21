"""Native post-atlas scheduling chain close, cache syscall and DMA send bindings.
Derived from each edition's second dirty-gated block continuation and its calls.
Static identity only; channel-pointer value and hardware timing need runtime.
"""
from pathlib import Path
import json,sys,hashlib,ctypes
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;inv=json.loads((OUT/'transfer-inventory.json').read_text());results=[];md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in inv['editions'] if x['edition']==ed);continuation=int(r['blocks'][1]['end'],16)
 def target(pc):
  w=e.words(pc,1)[0];assert w>>26==3,(ed,hex(pc));return (w&0x3ffffff)<<2
 def absolute(hi,lo):
  h,l=e.words(hi,1)[0],e.words(lo,1)[0];return ((h&65535)<<16)+ctypes.c_int16(l&65535).value
 send=target(continuation+0xa8);assert target(continuation+0xf0)==send;cache=target(continuation+0x94);assert target(continuation+0xdc)==cache;close=target(continuation+0x44);mapper=target(send+0x14);wait=target(send+0x20)
 channel_global=absolute(continuation+0x9c,continuation+0xa0);chain_origin=absolute(continuation+0xa4,continuation+0xac)
 assert e.words(cache,2)==(0x24030064,0x0000000c)
 functions={name:dict(entry=hex(start),end=hex(end),sha256=hashlib.sha256(e.read(start,end-start)).hexdigest()) for name,start,end in [('send_chain',send,send+0x68),('wait_channel',wait,wait+0x70),('map_address',mapper,mapper+0x28),('cache_syscall',cache,cache+16),('close_chain',close,close+0x28)]}
 listing=[]
 for name,lo,hi in [('post_atlas_continuation',continuation,continuation+0x104)]+[(name,int(f['entry'],16),int(f['end'],16)) for name,f in functions.items()]:
  listing.append(f'\n; {name} {lo:08x}..{hi:08x}')
  for pc in range(lo,hi,4):
   w=e.words(pc,1)[0];listing.append(f'{pc:08x} {w:08x} {decode(md,w,pc)[0]}')
 (OUT/f'{ed}-submission.asm').write_text('\n'.join(listing)+'\n');results.append(dict(edition=ed,native_executable=lock,continuation=hex(continuation),functions=functions,channel_pointer_global=hex(channel_global),font_chain_origin_global=hex(chain_origin),poll_mmio_address='0x1000a000',poll_mask='0x100',cache_syscall_number=100))
 print(ed,'native chain submit',hex(send),'cache syscall',hex(cache),'channel global',hex(channel_global),flush=True)
(OUT/'submission-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=results),indent=2)+'\n')
