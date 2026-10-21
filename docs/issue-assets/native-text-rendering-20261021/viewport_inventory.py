"""Library viewport state, row-range caller and statically bound setup descriptors."""
from pathlib import Path
import json,struct,ctypes,sys,hashlib
from inventory import native,decode
from resource_inventory import find,text_sections,mask
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);setup=find(e,src.words(0x20e1b0,20));draw=find(e,src.words(0x20e1e0,20));down=find(e,src.words(0x20e2b0,16));can=((e.words(draw+0x50,1)[0]&0x3ffffff)<<2);up=down+0x40
 assert e.read(up,0x20)==src.read(0x20e2f0,0x20)
 assert all((x&mask(y))==(y&mask(y)) for x,y in zip(e.words(can,20),src.words(0x20e310,20)))
 functions={};lines=[]
 for name,a,n in [('setup',setup,0x30),('draw',draw,0xd0),('scroll_down',down,0x40),('scroll_up',up,0x20),('can_scroll_down',can,0x50)]:
  functions[name]={'entry':hex(a),'end':hex(a+n),'sha256':hashlib.sha256(e.read(a,n)).hexdigest()};lines.append(f'; {name} {a:08x}..{a+n:08x}')
  for pc in range(a,a+n,4):lines.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(m,e.words(pc,1)[0],pc)[0]}')
 sites=[]
 for va,off,n in text_sections(e):
  for p in range(0,n-3,4):
   w=struct.unpack_from('<I',e.b,off+p)[0]
   if w>>26!=3 or (w&0x3ffffff)<<2!=setup:continue
   pc=va+p;word=e.words(pc+4,1)[0];assert word>>16==0x2407
   refs={}
   for label,offset in [('descriptor',-0x20),('arrows',-0x18)]:
    call=e.words(pc+offset,1)[0];assert call>>26==3;getter=(call&0x3ffffff)<<2;hi,jr,lo=e.words(getter,3);assert hi>>16==0x3c02 and jr==0x03e00008 and lo>>16==0x2442
    address=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;refs[label]={'getter':hex(getter),'address':hex(address),'bytes':e.read(address,28 if label=='descriptor' else 6).hex()}
   sites.append({'site':hex(pc),'visible_rows':ctypes.c_int16(word&65535).value,**refs})
 row={'edition':ed,'native_executable':lock,'functions':functions,'object_fields':{'text':4,'top_row':8,'visible_rows':12,'descriptor':16,'up_y':20,'down_y':22,'arrow_x':24},'arrow_draw':hex((e.words(draw+0x70,1)[0]&0x3ffffff)<<2),'arrow_depth_GP_offset':ctypes.c_int16(e.words(draw+0x60,1)[0]&65535).value,'setup_call_sites':sites}
 (OUT/f'{ed}-viewport.asm').write_text('\n'.join(lines)+'\n');rows.append(row);print(ed,'viewport',hex(draw),'setups',[(x['visible_rows'],x['descriptor']['address']) for x in sites],flush=True)
(OUT/'viewport-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
