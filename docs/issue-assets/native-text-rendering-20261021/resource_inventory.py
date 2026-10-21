"""Independent native bindings for font resource, scatter and frame reset functions."""
from pathlib import Path
import json,struct,sys,hashlib
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent
SPECS={'resource_initialize':(0x139f60,16,0x13a260),'atlas_reset_to_reserved':(0x13a260,12,0x13a290),'frame_clear':(0x13c390,20,0x13c3e0),'font_reset_wrapper':(0x13c3e0,12,0x13c410),'scatter':(0x13c5c0,20,0x13c6b0),'default_palette_upload':(0x139f00,16,0x139f60)}
def mask(w):
 op=w>>26
 if op in (2,3):return 0xfc000000
 if op in (1,4,5,6,7,20,21,22,23,0xf,9,0x20,0x21,0x23,0x24,0x25,0x28,0x29,0x2b):return 0xffff0000
 return 0xffffffff
def find(elf,pattern):
 masks=[mask(w) for w in pattern];size=len(pattern)*4;out=[]
 for _,off,va,_,n,*_ in elf.loads:
  for p in range(off,off+n-size,4):
   first=struct.unpack_from('<I',elf.b,p)[0]
   if first&masks[0]!=pattern[0]&masks[0]:continue
   words=struct.unpack_from('<'+'I'*len(pattern),elf.b,p)
   if all(x&m==y&m for x,y,m in zip(words,pattern,masks)):out.append(va+p-off)
 if len(out)!=1:raise ValueError(('nonunique native skeleton',out))
 return out[0]
def text_sections(elf):
 b=elf.b;so=struct.unpack_from('<I',b,32)[0];sz,n=struct.unpack_from('<2H',b,46)
 for i in range(n):
  s=struct.unpack_from('<10I',b,so+i*sz)
  if s[2]&4:yield s[3],s[4],s[5]
def build():
 original,_=native('original');md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN);results=[]
 for ed in ('original','best','sp'):
  e,lock=native(ed);entries={name:find(e,original.words(va,n)) for name,(va,n,end) in SPECS.items()};listing=[];functions={}
  for name,entry in entries.items():
   ov,n,oe=SPECS[name];end=entry+oe-ov;data=e.read(entry,end-entry);listing.append(f'\n; {name} {entry:08x}..{end:08x}')
   calls=[]
   for pc in range(entry,end,4):
    w=e.words(pc,1)[0];asm,kind=decode(md,w,pc);listing.append(f'{pc:08x} {w:08x} {asm}')
    if w>>26==3:calls.append({'site':hex(pc),'target':hex(((pc+4)&0xf0000000)|((w&0x3ffffff)<<2))})
   functions[name]={'entry':hex(entry),'end':hex(end),'sha256':hashlib.sha256(data).hexdigest(),'direct_calls':calls,'callers':[]}
  for va,off,n in text_sections(e):
   for p in range(0,n,4):
    w=struct.unpack_from('<I',e.b,off+p)[0]
    if w>>26!=3:continue
    target=((va+p+4)&0xf0000000)|((w&0x3ffffff)<<2)
    for name,entry in entries.items():
     if target==entry:functions[name]['callers'].append(hex(va+p))
  (OUT/f'{ed}-resources.asm').write_text('\n'.join(listing)+'\n');results.append({'edition':ed,'native_executable':lock,'functions':functions})
  print(ed,{k:hex(v) for k,v in entries.items()})
 (OUT/'resource-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':results},indent=2)+'\n')
if __name__=='__main__':build()
