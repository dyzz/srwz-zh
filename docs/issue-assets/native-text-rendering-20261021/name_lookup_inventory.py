"""Native selector2 name lookup, coordinate side effect, and 5039 dispatch span.
The shared dispatcher has other opcodes; binding its range does not mean all
of them are reconstructed. Selector1/3, 80 and special-value resolvers stay open.
"""
from pathlib import Path
import json,sys,hashlib,ctypes
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent;src,_=native('original');inv=json.loads((OUT/'squad-name-command-inventory.json').read_text());strings=json.loads((OUT/'string-inventory.json').read_text());md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN);rows=[]
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in inv['editions'] if x['edition']==ed);wrapper=int(r['unclosed_parameter_helpers'][1]['target'],16);lookup=find(e,src.words(0x1b2ce0,24));coordinate=(e.words(lookup+0x1b4,1)[0]&0x3ffffff)<<2;assert (e.words(wrapper+0xbc,1)[0]&0x3ffffff)<<2==lookup;assert e.words(coordinate+0x10c,1)[0]==0x03e00008
 handler=int(r['handler'],16);jump=handler+0x110;w=e.words(jump,1)[0];assert w>>16==0x1000
 join=jump+4+4*ctypes.c_int16(w&65535).value;w=e.words(join,1)[0];assert w>>16==0x1000
 epilogue=join+4+4*ctypes.c_int16(w&65535).value;assert e.words(epilogue,11)==src.words(0x1c42b0,11)
 dispatcher=int(r['dispatch'],16)-0x30;frame=-ctypes.c_int16(e.words(dispatcher,1)[0]&65535).value;assert e.words(epilogue+44,1)[0]==0x27bd0000|frame
 copy=next(x for x in strings['editions'] if x['edition']==ed)['functions']['strcpy']
 def formed(a,b):return ((e.words(a,1)[0]&65535)<<16)+ctypes.c_int16(e.words(b,1)[0]&65535).value
 table=formed(lookup+0x68,lookup+0x78);assert table==int(r['entity_table'],16);grid=formed(coordinate+0x64,coordinate+0x88)
 f={'lookup':(lookup,lookup+0x290),'coordinate':(coordinate,coordinate+0x114),'selector_wrapper':(wrapper,wrapper+0x104),'dispatcher':(dispatcher,epilogue+48),'strcpy':(int(copy['entry'],16),int(copy['end'],16))};functions={};listing=[]
 for name,(a,b) in f.items():
  functions[name]=dict(entry=hex(a),end=hex(b),sha256=hashlib.sha256(e.read(a,b-a)).hexdigest())
  spans=[(a,b)] if name!='dispatcher' else [(a,a+0x68),(handler,handler+0x118),(epilogue,epilogue+48)]
  for lo,hi in spans:
   listing.append('; '+name)
   for pc in range(lo,hi,4):listing.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(md,e.words(pc,1)[0],pc)[0]}')
 (OUT/f'{ed}-name-lookup.asm').write_text('\n'.join(listing)+'\n')
 rows.append(dict(edition=ed,native_executable=lock,functions=functions,entity_table=hex(table),grid_pointer_global=hex(grid),dispatcher_frame_bytes=frame,context_output_offsets=['0x2f90','0x2f94','0x2f98'],config=[table,grid],opcode=5039,selector_modes_exercised=[0,2]));print(ed,'lookup',hex(lookup),'coordinate',hex(coordinate),'grid',hex(grid),flush=True)
(OUT/'name-lookup-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=rows),indent=2)+'\n')
