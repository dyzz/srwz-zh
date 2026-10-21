"""Native two-string center-offset cache writer and following draw argument blocks.
Actual native identities, exact instruction-pattern binding, no inferred UI name.
The writer prefix's opaque callees and natural object lifetime remain unproved.
"""
from pathlib import Path
import json,sys,struct,hashlib
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
s16=lambda x:x-65536 if x&32768 else x
calls=json.loads((OUT/'caller-inventory.json').read_text());results=[]
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in calls['editions'] if x['edition']==ed);sites=[int(x['site'],16) for x in r['direct_transfer_candidates'] if x['target']=='measure']
 matches=[pc for pc in sites if e.words(pc+8,1)[0]==0xa6020024 and e.words(pc+24,1)[0]==0xa6020026]
 assert len(matches)==1,(ed,matches)
 pc=matches[0];start=pc-4;end=pc+28
 expected=[0x8e04001c,None,0x0000282d,0xa6020024,0x8e040020,None,0x0000282d,0xa6020026]
 words=e.words(start,8)
 for a,b in zip(words,expected):assert b is None or a==b,(ed,hex(a),b)
 assert words[1]>>26==3 and words[5]==words[1]
 # Native initializer establishes the S0 base, with no later S0 assignment
 # in the observed writer body except its eventual epilogue restore.
 inits=[]
 for va in range(start-0x1000,start,4):
  w=e.words(va,1)[0]
  if w>>16!=0x3c10:continue
  for lo in range(va+4,va+24,4):
   low=e.words(lo,1)[0]
   if low>>16==0x2610:inits.append((va,lo,((w&65535)<<16)+s16(low&65535)))
 assert len(inits)==1,(ed,inits)
 lui,add,base=inits[0]
 s0_writes=[]
 for a in range(add+4,start,4):
  w=e.words(a,1)[0];op=w>>26
  if op==0 and ((w>>11)&31)==16 and w&63 not in (8,12,13,17,19,24,25,26,27,28,29,30,31):s0_writes.append(a)
  if op in (8,9,10,11,12,13,14,15,24,25,30,32,33,34,35,36,37,38,39,55) and ((w>>16)&31)==16:s0_writes.append(a)
 assert not s0_writes,(ed,'writer S0 changed',s0_writes)
 # Find the immediately following draw routine's absolute LH/LW fields.
 refs=[]
 for va in range(end,end+0x600,4):
  hi=e.words(va,1)[0]
  if hi>>16!=0x3c01:continue
  found=[]
  for lp in range(va+4,va+16,4):
   lw=e.words(lp,1)[0]
   if ((lw>>21)&31)==1 and lw>>26 in (0x21,0x23):found.append((lp,lw))
   if lw>>16==0x3c01:break
  if not found:continue
  load,lo=found[0];op=lo>>26
  addr=((hi&65535)<<16)+s16(lo&65535)
  if addr not in (base+0x24,base+0x26):continue
  target=None;site=None
  for a in range(va+8,va+60,4):
   w=e.words(a,1)[0]
   if w>>26==3:site=a;target=(w&0x3ffffff)<<2;break
  assert target is not None
  refs.append(dict(cache_offset=hex(addr-base),load=hex(load),block_start=hex(va),draw_call=hex(site),draw_target=hex(target),block_end=hex(site+8),sha256=hashlib.sha256(e.read(va,site+8-va)).hexdigest()))
 assert [x['cache_offset'] for x in refs]==['0x24','0x26'],(ed,refs)
 listing=[]
 for label,a,b in [('writer_tail',start,end)]+[(x['cache_offset'],int(x['block_start'],16),int(x['block_end'],16)) for x in refs]:
  listing.append('; '+label)
  for va in range(a,b,4):listing.append(f'{va:08x} {e.words(va,1)[0]:08x} {decode(md,e.words(va,1)[0],va)[0]}')
 (OUT/f'{ed}-measure-cache.asm').write_text('\n'.join(listing)+'\n')
 row=dict(edition=ed,native_executable=lock,object_base=hex(base),object_initializer_lui=hex(lui),object_initializer_addiu=hex(add),writer_tail_start=hex(start),writer_tail_end=hex(end),measure_entry=hex((words[1]&0x3ffffff)<<2),writer_sha256=hashlib.sha256(e.read(start,end-start)).hexdigest(),text_offsets=['0x1c','0x20'],cache_offsets=['0x24','0x26'],measure_full_width_argument=0,draw_consumers=refs)
 results.append(row);print(ed,hex(base),hex(start),[(x['load'],x['draw_call']) for x in refs],flush=True)
(OUT/'measure-cache-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=results),indent=2)+'\n')
