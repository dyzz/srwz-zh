"""Whole native two-entity cache initialization, real seven helpers/preset/measure.
Controlled pointer-linked entity graphs and byte domains; compares entity
writes, complete presentation object and font state, selector and return.
Not a natural-game text-producer/lifetime or rendered-frame claim.
"""
from pathlib import Path
import json,ctypes,struct,subprocess,tempfile,hashlib
from numeric_harness import machine,call
from string_adapter import install
from unicorn import UC_HOOK_CODE
OUT=Path(__file__).parent;inv=json.loads((OUT/'measure-source-inventory.json').read_text());results=[];summaries=[]
# Cases cover all byte values at category/flags and normalization low bits,
# every pointer-guard depth, side ties, empty inputs and actual pointer alias.
cases=[]
for raw in range(256):
 for pose in range(4):cases.append((f'category_{raw}_pose{pose}',raw,255-raw,0xa0|pose,0x5c|((pose+1)&3),raw,(raw>>2)&3,3,True,True,False))
for flags in range(256):
 for depth in range(5):cases.append((f'flags_{flags}_depth{depth}',flags%16,flags%16,0xa3,0x5d,flags,depth,depth,True,True,False))
for a,b in ((False,False),(False,True),(True,False),(True,True)):
 for raw in (0,3,4,7,8,11,12,255):cases.append((f'null_{a}_{b}_{raw}',raw,raw,3,2,0xff,2,0,a,b,False))
for raw in (0,3,4,7,8,11,12,255):cases.append((f'alias_{raw}',raw,raw,0xa3,0xa3,0x44,2,2,True,True,True))
texts=[bytes.fromhex('889f889f'),bytes.fromhex('8260824f889f'),bytes.fromhex('320e340c338e8260330c824f32153415330c889f'),b'',bytes.fromhex('340c8260')]
with tempfile.TemporaryDirectory(prefix='srwz-measure-source-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'measure_source_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_two_entity_cache_model.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p];c.native_two_entity_cache_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  r=next(x for x in inv['editions'] if x['edition']==ed);u,e,row,fn,F,_,_,_=machine(ed);start=int(r['entry'],16);end=int(r['end'],16);helpers=[(int(x['entry'],16),int(x['end'],16)) for x in r['helpers'].values()];measure=int(row['measure_entry'],16);spans=[(start,end),(measure,measure+0x250)]+helpers;install(u,e,spans)
  cfg=(ctypes.c_uint32*len(r['config_words']))(*r['config_words']);model_ram=ctypes.create_string_buffer(bytes(u.mem_read(0,32<<20)),32<<20);model_base=ctypes.addressof(model_ram)
  branches={};fixed_branches=set();observed={};pending=[None]
  for lo,hi in spans:
   for pc in range(lo,hi,4):
    w=e.words(pc,1)[0]
    if w>>26 in (1,4,5,6,7,20,21,22,23):
     branches[pc]=pc+4+4*ctypes.c_int16(w&65535).value
     if w>>26 in (4,5,20,21) and ((w>>21)&31)==((w>>16)&31):fixed_branches.add(pc)
  def trace(uc,pc,size,data):
   if pending[0] is not None:
    bp=pending[0]
    if pc!=bp+4:observed.setdefault(bp,set()).add(pc);pending[0]=None
   if pc in branches:pending[0]=pc
  u.hook_add(UC_HOOK_CODE,trace)
  for index,(name,ca,cb,pa,pb,flags,da,db,has_a,has_b,alias) in enumerate(cases):
   chunks={};ap=0x1900000 if has_a else 0;bp=ap if alias else 0x1910000 if has_b else 0
   for side,(addr,cat,pose,depth) in enumerate([(0x1900000,ca,pa,da),(0x1910000,cb,pb,db)]):
    entity=bytearray(b'\xa5'*256);entity[0x19]=pose;entity[0x25]=cat;link=0x1920000+side*0x1000;definition=0x1940000+side*0x1000
    struct.pack_into('<3I',entity,8,link if depth else 0,link if depth==3 else 0,link if depth==4 else 0);data=texts[(index+side)%len(texts)]+b'\0\0';entity[0x28:0x28+len(data)]=data;chunks[addr]=bytes(entity)
    nested=bytearray(256);struct.pack_into('<I',nested,0xa8,definition if depth>=2 else 0);chunks[link]=bytes(nested);definition_bytes=bytearray(64);definition_bytes[0x30]=flags;chunks[definition]=bytes(definition_bytes)
   initial=bytearray(b'\xa5'*0x90);struct.pack_into('<4h',initial,0x14,21,12,21,14);chunks[F]=bytes(initial);chunks[cfg[0]]=bytes([(index*19)&255])*0x30;chunks[cfg[3]]=b'\xa5'
   for addr,value in zip(r['tail_wrapper_argument_globals'],(ap,bp)):chunks[int(addr,16)]=struct.pack('<I',value)
   for addr,data in chunks.items():u.mem_write(addr,data);ctypes.memmove(model_base+addr,data,len(data))
   expected=c.native_two_entity_cache_model(model_ram,ap,bp,cfg);entry_mode='tail_wrapper' if index&1 else 'direct';actual=call(u,int(r['tail_wrapper_entry'],16) if index&1 else start,[ap,bp]);assert actual==expected,(ed,name,'return',actual,expected)
   hashes={}
   for addr,data in chunks.items():
    got=bytes(u.mem_read(addr,len(data)));want=ctypes.string_at(model_base+addr,len(data));assert got==want,(ed,name,hex(addr),'bytes',[(i,a,b) for i,(a,b) in enumerate(zip(got,want)) if a!=b][:16]);hashes[hex(addr)]=hashlib.sha256(got).hexdigest()
   obj=bytes(u.mem_read(cfg[0],0x30));results.append(dict(edition=ed,case=name,entry_mode=entry_mode,input_presence=[bool(ap),bool(bp)],aliased=alias,categories=[ca,cb],poses_before=[pa,pb],flag_byte=flags,pointer_depths=[da,db],text_pointers=list(struct.unpack_from('<2I',obj,0x1c)),cached_center_offsets=list(struct.unpack_from('<2h',obj,0x24)),return_hex=hex(actual),region_hashes=hashes))
  coverage=[]
  for pc,target in sorted(branches.items()):coverage.append(dict(branch=hex(pc),target=hex(target),constant_register_predicate=pc in fixed_branches,successors=list(map(hex,sorted(observed.get(pc,set())))),both_outcomes_seen=observed.get(pc,set())=={pc+8,target}))
  summaries.append(dict(edition=ed,case_count=len(cases),branch_sites=len(branches),conditional_sites=len(branches)-len(fixed_branches),conditional_sites_seen=len(set(observed)-fixed_branches),constant_predicate_sites=len(fixed_branches),both_outcomes_seen=sum(x['both_outcomes_seen'] for x in coverage if not x['constant_register_predicate']),branches=coverage))
  print(ed,len(cases),'whole native source/cache initializers match C;',len(set(observed)-fixed_branches),'conditional sites observed',flush=True)
(OUT/'measure-source-execution.json').write_text(json.dumps(dict(scope=__doc__,status='three_whole_native_initializers_and_helpers_match_C',case_count=len(results),cases=results,branch_coverage=summaries),indent=2)+'\n')
