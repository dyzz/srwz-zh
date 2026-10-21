"""Bind viewport descriptors to page roles through renderer vtables and labels.
Static native instruction/data chain, no inferred constructor-name ownership.
Setup -> renderer constructor -> vtable draw slot -> metadata -> label getters.
"""
from pathlib import Path
import json,ctypes,hashlib,sys
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;inv=json.loads((OUT/'viewport-inventory.json').read_text());results=[];md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for r in inv['editions']:
 ed=r['edition'];e,lock=native(ed);entries=[];listing=[]
 for setup in r['setup_call_sites'][::2]:
  site=int(setup['site'],16);call=site+0x30;w=e.words(call,1)[0];assert w>>26==3;ctor=(w&0x3ffffff)<<2;hi,lo=e.words(ctor+0x14,1)[0],e.words(ctor+0x1c,1)[0];assert hi>>16==0x3c03 and lo>>16==0x2463
  vtable=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;draw=e.words(vtable+0x10,1)[0];end=next(p+8 for p in range(draw,draw+0x400,4) if e.words(p,1)[0]==0x03e00008)
  metadata=[]
  for pc in range(draw,end,4):
   w=e.words(pc,1)[0]
   if w>>26==3 and e.words(pc-8,2)==(0x0240202d,0x0200302d) and e.words(pc+4,1)[0]==0x0220282d:metadata.append((pc,(w&0x3ffffff)<<2))
  assert len(metadata)==1,(ed,hex(draw),metadata);meta_site,meta=metadata[0];meta_end=next(p+8 for p in range(meta,meta+0x1000,4) if e.words(p,1)[0]==0x03e00008);labels=[]
  for pc in range(meta,meta_end,4):
   w=e.words(pc,1)[0]
   if w>>26!=3:continue
   getter=(w&0x3ffffff)<<2
   try:h,j,l=e.words(getter,3)
   except ValueError:continue
   if h>>16!=0x3c02 or j!=0x03e00008 or l>>16!=0x2442:continue
   addr=((h&65535)<<16)+ctypes.c_int16(l&65535).value
   try:p=e.words(addr,1)[0];b=e.read(p,80).split(b'\0')[0]
   except ValueError:continue
   try:text=b.decode('shift_jis')
   except UnicodeDecodeError:continue
   if text:labels.append({'call':hex(pc),'getter':hex(getter),'descriptor':hex(addr),'text_pointer':hex(p),'native_label':text})
  names={x['native_label'] for x in labels};role='character' if {'愛称','声優'}<=names else 'robot' if {'全長','重量'}<=names else 'keyword' if '：用語の切り替え' in names else 'unclassified'
  entries.append({'role':role,'setup':setup,'renderer_constructor_call':hex(call),'renderer_constructor':hex(ctor),'renderer_vtable':hex(vtable),'draw_slot':'0x10','draw_method':hex(draw),'metadata_call':hex(meta_site),'metadata_method':hex(meta),'labels':labels})
  for name,a,b in [('setup_to_renderer_constructor',site-0x20,site+0x38),('renderer_constructor',ctor,ctor+0x30),('draw_and_metadata_edge',draw,end),('metadata_labels',meta,meta_end)]:
   listing.append(f'; {name} {a:08x}..{b:08x}')
   for pc in range(a,b,4):listing.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(md,e.words(pc,1)[0],pc)[0]}')
  print(ed,role,setup['visible_rows'],setup['descriptor']['address'],names,flush=True)
 (OUT/f'{ed}-surface-bindings.asm').write_text('\n'.join(listing)+'\n');results.append({'edition':ed,'native_executable':lock,'surfaces':entries})
(OUT/'surface-bindings.json').write_text(json.dumps({'scope':__doc__,'editions':results},ensure_ascii=False,indent=2)+'\n')
