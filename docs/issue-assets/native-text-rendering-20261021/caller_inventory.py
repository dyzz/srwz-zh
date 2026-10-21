"""Three native ELF static reference candidates, with instruction context.
J/JAL matches in executable sections are candidates (embedded data may exist).
LUI + immediately following memory/addiu/ori matches are exact local patterns;
this is not whole-program dataflow, full caller ownership or indirect-call proof.
"""
from pathlib import Path
import json,struct,sys,ctypes
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
inv=json.loads((OUT/'inventory.json').read_text());ni=json.loads((OUT/'numeric-inventory.json').read_text())
def sections(e):
 off=struct.unpack_from('<I',e.b,32)[0];size,n=struct.unpack_from('<HH',e.b,46);return [struct.unpack_from('<10I',e.b,off+i*size) for i in range(n)]
def context(e,pc):
 result=[]
 for va in range(pc-24,pc+28,4):
  try:w=e.words(va,1)[0]
  except ValueError:continue
  result.append({'pc':hex(va),'word':hex(w),'asm':decode(md,w,va)[0]})
 return result
results=[]
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in inv['editions'] if x['edition']==ed);F=int(r['state_va'],16);fns=next(x for x in ni['editions'] if x['edition']==ed)['functions'];targets={int(v['entry'],16):k for k,v in fns.items()};targets[int(r['measure_entry'],16)]='measure';targets[int(r['renderer_entry'],16)]='main_renderer'
 cache_path=OUT/'cache-inventory.json'
 if cache_path.exists():
  cache=next(x for x in json.loads(cache_path.read_text())['editions'] if x['edition']==ed)
  targets[int(cache['repeat'],16)]='cached_repeat_renderer';targets[int(cache['setup'],16)]='cached_symbol_setup'
 geometry_path=OUT/'geometry-inventory.json'
 if geometry_path.exists():
  geometry=next(x for x in json.loads(geometry_path.read_text())['editions'] if x['edition']==ed)
  targets[int(geometry['entry'],16)]='placeholder_number_renderer';targets[int(geometry['style'],16)]='style_table_apply'
 for metadata,fields in [('preset-inventory.json',{'entry':'font_preset'}),('name-writer-inventory.json',{'entry':'name_confirmation_writer'})]:
  path=OUT/metadata
  if path.exists():
   record=next(x for x in json.loads(path.read_text())['editions'] if x['edition']==ed)
   for key,label in fields.items():targets[int(record[key],16)]=label
 subs=[]
 for i in range(4):
  handler=int(r['controls'][12+i]['target'],16);hi=e.words(handler+0x14,1)[0];lo=e.words(handler+0x1c,1)[0];subs.append(((hi&65535)<<16)+ctypes.c_int16(lo&65535).value)
 calls=[];state=[];buffers=[];literal=[]
 for section in sections(e):
  _,typ,flags,va,off,size,*_=section
  if typ==8:continue
  if flags&4:
   for pos in range(off,off+size-3,4):
    pc=va+pos-off;w=struct.unpack_from('<I',e.b,pos)[0];op=w>>26
    if op in (2,3):
     dest=((pc+4)&0xf0000000)|((w&0x3ffffff)<<2)
     if dest in targets:calls.append({'site':hex(pc),'target':targets[dest],'target_va':hex(dest),'kind':'JAL' if op==3 else 'J','context':context(e,pc)})
    if op!=0xf or pos+8>off+size:continue
    rt=(w>>16)&31;following=struct.unpack_from('<I',e.b,pos+4)[0];nextop=following>>26;base=(following>>21)&31
    if base!=rt:continue
    low=following&65535;address=((w&65535)<<16)+(low if nextop==0xd else ctypes.c_int16(low).value)
    if nextop==0xd:address=((w&65535)<<16)|low
    if nextop not in (9,0xd,0x20,0x21,0x23,0x24,0x25,0x28,0x29,0x2b,0x37,0x3f):continue
    item={'site':hex(pc+4),'address':hex(address),'operation':decode(md,following,pc+4)[0],'context':context(e,pc+4)}
    if F<=address<F+0x90:state.append(dict(item,offset=hex(address-F)))
    for i,start in enumerate(subs):
     if start<=address<start+8:buffers.append(dict(item,substitution=i,buffer_start=hex(start),offset=address-start))
  if flags&2:
   for pos in range(off,off+size-3,4):
    w=struct.unpack_from('<I',e.b,pos)[0]
    if w in targets:literal.append({'location':hex(va+pos-off),'target':targets[w],'executable_section':bool(flags&4),'classification':'raw pointer candidate, may be instruction/data coincidence'})
 row={'edition':ed,'native_executable':lock,'substitution_buffer_addresses':[hex(x) for x in subs],'direct_transfer_candidates':calls,'adjacent_state_references':state,'adjacent_substitution_references':buffers,'literal_function_pointer_candidates':literal}
 results.append(row)
 from collections import Counter
 print(ed,'direct',dict(Counter(x['target'] for x in calls)),'state',len(state),'substitution refs',len(buffers),'pointer candidates',len(literal),flush=True)
(OUT/'caller-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':results},indent=2)+'\n')
