"""Native font-atlas dirty-flag blocks and deferred transfer builder evidence.
Static disassembly and direct references only; no DMA/GS execution claim.
"""
from pathlib import Path
import json,struct,sys
from inventory import native,decode
from resource_inventory import text_sections
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent;inv=json.loads((OUT/'inventory.json').read_text());original,_=native('original');results=[];md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 elf,lock=native(ed);F=int(next(x for x in inv['editions'] if x['edition']==ed)['state_va'],16);dirty=F+0x70;blocks=[];listing=[]
 for va,off,n in text_sections(elf):
  for k in range(4,n-8,4):
   a,w,branch=struct.unpack_from('<3I',elf.b,off+k-4)
   if a>>16!=0x3c01 or w>>26!=0x23 or (w>>21)&31!=1:continue
   im=w&65535;address=((a&65535)<<16)+(im if im<32768 else im-65536)
   if address!=dirty:continue
   assert branch>>26==4 and (branch>>16)&31==0
   im=branch&65535;end=va+k+8+(im if im<32768 else im-65536)*4;start=va+k-4
   calls=[];listing.append(f'\n; dirty-gated atlas transfer requests {start:08x}..{end:08x}')
   for pc in range(start,end,4):
    word=elf.words(pc,1)[0];asm,kind=decode(md,word,pc);listing.append(f'{pc:08x} {word:08x} {asm}')
    if word>>26==3:calls.append({'site':hex(pc),'target':hex(((pc+4)&0xf0000000)|((word&0x3ffffff)<<2))})
   assert len(calls)==2 and calls[0]['target']==calls[1]['target']
   blocks.append({'start':hex(start),'end':hex(end),'direct_calls':calls,'meaning':'clears dirty flag, schedules two atlas halves and restores caller buffer pointers'})
 builder=int(blocks[0]['direct_calls'][0]['target'],16)
 flush_call=elf.words(builder+0x44,1)[0];assert flush_call>>26==3;flush=(flush_call&0x3ffffff)<<2
 assert len(blocks)==2 and all(int(x['direct_calls'][0]['target'],16)==builder for x in blocks)
 for name,start,end in [('transfer_builder',builder,builder+0x1e0),('flush_reference_chain',flush,flush+0x90)]:
  listing.append(f'\n; {name} {start:08x}..{end:08x}')
  for pc in range(start,end,4):
   word=elf.words(pc,1)[0];asm,kind=decode(md,word,pc);listing.append(f'{pc:08x} {word:08x} {asm}')
 (OUT/f'{ed}-transfer.asm').write_text('\n'.join(listing)+'\n');results.append({'edition':ed,'native_executable':lock,'dirty_flag':hex(dirty),'transfer_builder':hex(builder),'flush_ref_chain':hex(flush),'blocks':blocks})
 print(ed,'two dirty-gated font transfer blocks; builder',hex(builder))
(OUT/'transfer-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':results},indent=2)+'\n')
