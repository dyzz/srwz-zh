"""Independent native bindings of cached-symbol setup and @ repetition renderer."""
from pathlib import Path
import json,hashlib,ctypes,sys
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent;source,_=native('original');rows=[];md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);cache=find(e,source.words(0x3a9830,20));repeat=find(e,source.words(0x3a99d0,20));end=repeat+0x560
 assert e.words(end-16,1)[0]==0x03e00008,(ed,'repeat end drift')
 def addr(hi,lo):return ((e.words(hi,1)[0]&65535)<<16)+ctypes.c_int16(e.words(lo,1)[0]&65535).value
 flag=addr(repeat+0x3c,repeat+0x40)
 packet=addr(repeat+0x80,repeat+0x84)
 atoi=((e.words(repeat+0x60,1)[0]&0x3ffffff)<<2)
 listing=[]
 for name,a,b in [('cached_symbol_setup',cache,repeat),('repeat_renderer',repeat,end)]:
  listing.append(f'; {name} {a:08x}..{b:08x}')
  for pc in range(a,b,4):listing.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(md,e.words(pc,1)[0],pc)[0]}')
 (OUT/f'{ed}-cached-symbols.asm').write_text('\n'.join(listing)+'\n')
 # Recover the actual strings passed to the two symbol-list calls.
 ni=json.loads((OUT/'numeric-inventory.json').read_text());symbol=int(next(x for x in ni['editions'] if x['edition']==ed)['functions']['symbol_list']['entry'],16)
 strings=[]
 for pc in range(cache,repeat,4):
  if e.words(pc,1)[0]>>26==3 and (e.words(pc,1)[0]&0x3ffffff)<<2==symbol:
   prefix=[(q,e.words(q,1)[0]) for q in range(pc-64,pc,4)]
   lows=[(q,w) for q,w in prefix if w>>16==0x2484];lowpc,low=lows[-1];his=[(q,w) for q,w in prefix if q<lowpc and w>>16==0x3c04];high=his[-1][1]
   va=((high&65535)<<16)+ctypes.c_int16(low&65535).value;strings.append({'call':hex(pc),'address':hex(va),'bytes':e.read(va,4).hex()})
 rows.append({'edition':ed,'native_executable':lock,'setup':hex(cache),'repeat':hex(repeat),'repeat_end':hex(end),'lazy_flag':hex(flag),'cached_packet':hex(packet),'atoi':hex(atoi),'symbol_strings':strings,'repeat_sha256':hashlib.sha256(e.read(repeat,end-repeat)).hexdigest()})
 print(ed,rows[-1],flush=True)
(OUT/'cache-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
