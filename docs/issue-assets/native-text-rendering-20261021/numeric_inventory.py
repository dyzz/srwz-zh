"""Independent native numeric/symbol renderer bindings and literal tables."""
from pathlib import Path
import json,sys,hashlib
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent;orig,_=native('original');md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
SPECS={'unsigned_number':(0x13bd60,20,0x13c000),'signed_number':(0x13c000,20,0x13c190),'symbol_list':(0x13c190,20,0x13c390),'initialize_record_group':(0x13c410,20,0x13c5a0),'text_at_position':(0x13c5a0,8,0x13c5c0)}
rows=[]
for ed in ('original','best','sp'):
 e,lock=native(ed);f={};listing=[]
 for name,(a,n,b) in SPECS.items():
  if name=='symbol_list' and ed=='sp':
   # Register allocation differs; disambiguate the shared ABI prologue
   # using independently bound numeric core and the reset function boundary.
   from resource_inventory import mask
   candidates=[];pattern=orig.words(a,12);masks=[mask(w) for w in pattern]
   import struct
   for _,off,va,_,size,*_ in e.loads:
    for pos in range(off,off+size-48,4):
     words=struct.unpack_from('<12I',e.b,pos)
     if all(x&m==y&m for x,y,m in zip(words,pattern,masks)):candidates.append(va+pos-off)
   candidates=[v for v in candidates if v!=int(f['unsigned_number']['entry'],16)]
   assert len(candidates)==1,candidates;start=candidates[0]
   resources=json.loads((OUT/'resource-inventory.json').read_text());end=int(next(x for x in resources['editions'] if x['edition']==ed)['functions']['frame_clear']['entry'],16)
  else:start=find(e,orig.words(a,n));end=start+b-a
  f[name]={'entry':hex(start),'end':hex(end),'sha256':hashlib.sha256(e.read(start,end-start)).hexdigest()};listing.append(f'\n; {name} {start:08x}..{end:08x}')
  for pc in range(start,end,4):
   w=e.words(pc,1)[0];asm,kind=decode(md,w,pc);listing.append(f'{pc:08x} {w:08x} {asm}')
 (OUT/f'{ed}-numeric.asm').write_text('\n'.join(listing)+'\n');rows.append({'edition':ed,'native_executable':lock,'functions':f});print(ed,{k:v['entry'] for k,v in f.items()})
(OUT/'numeric-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
