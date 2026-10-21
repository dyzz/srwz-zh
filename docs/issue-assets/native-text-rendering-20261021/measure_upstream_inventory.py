"""Executable-section direct callers and local +28 strcpy destination candidates.
The shared field offset alone does not prove that a candidate writes an entity
that reaches this cache initializer. Memory aliasing and global-pointer writers
remain to be bound; these are annotated leads rather than natural reachability.
"""
from pathlib import Path
import json,struct,hashlib,sys,ctypes
from inventory import native,decode
from resource_inventory import text_sections
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent;src=json.loads((OUT/'measure-source-inventory.json').read_text());strings=json.loads((OUT/'string-inventory.json').read_text());results=[]
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
def context(e,pc,before=32,after=12):
 return [dict(pc=hex(a),word=hex(e.words(a,1)[0]),asm=decode(md,e.words(a,1)[0],a)[0]) for a in range(pc-before,pc+after,4)]
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in src['editions'] if x['edition']==ed);writer=int(r['entry'],16);copy=int(next(x for x in strings['editions'] if x['edition']==ed)['functions']['strcpy']['entry'],16);callers=[];copies=[]
 for va,off,n in text_sections(e):
  for k in range(0,n,4):
   w=struct.unpack_from('<I',e.b,off+k)[0]
   if w>>26 not in (2,3):continue
   target=(w&0x3ffffff)<<2;pc=va+k
   if target==writer:
    binding={}
    def formed(hi,low):return ((e.words(hi,1)[0]&65535)<<16)+ctypes.c_int16(e.words(low,1)[0]&65535).value
    if w>>26==3:
     gw=e.words(pc-16,1)[0];assert gw>>26==3
     getter=(gw&0x3ffffff)<<2;g=e.words(getter,4)
     assert g[0]>>16==0x3c01 and g[1]==0x03e00008 and g[2]>>16==0x8c22 and g[3]==0
     binding=dict(first_argument_global=hex(formed(pc-8,pc-4)),second_argument_getter=hex(getter),second_argument_global=hex(((g[0]&65535)<<16)+ctypes.c_int16(g[2]&65535).value),getter_sha256=hashlib.sha256(e.read(getter,16)).hexdigest())
    else:binding=dict(first_argument_global=hex(formed(pc-12,pc-8)),second_argument_global=hex(formed(pc-4,pc+4)))
    callers.append(dict(site=hex(pc),kind='JAL' if w>>26==3 else 'J',argument_sources=binding,context=context(e,pc)))
   if target!=copy or w>>26!=3:continue
   candidates=[]
   for a in list(range(pc-24,pc,4))+[pc+4]:
    x=e.words(a,1)[0]
    if x>>26==9 and ((x>>16)&31)==4 and x&65535==0x28:candidates.append(dict(pc=hex(a),base_gpr=(x>>21)&31,delay_slot=a==pc+4))
   if candidates:copies.append(dict(site=hex(pc),destination_definitions=candidates,context=context(e,pc),window_sha256=hashlib.sha256(e.read(pc-32,44)).hexdigest(),identity_status='field-offset candidate, shared runtime type not yet established'))
 results.append(dict(edition=ed,native_executable=lock,initializer_direct_callers=callers,local_name_copy_candidates=copies));print(ed,len(callers),'initializer callers;',len(copies),'local +28 copy candidates',flush=True)
(OUT/'measure-upstream-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=results),indent=2)+'\n')
