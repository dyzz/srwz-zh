"""Execute native nonblank validation block and its real vtable +0x98 callback.
A controlled object uses the original ELF vtable; no constructor/GUI/runtime
reachability claim. Stops at native common exit after this block, not full UI
handler return. Valid allocated fields only, field count 0..3. No body stubs.
"""
from pathlib import Path
import json,ctypes,struct,tempfile,subprocess,random,hashlib
from numeric_harness import machine
from string_adapter import install
from execute import GPRS
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_SP,UC_MIPS_REG_GP,UC_MIPS_REG_RA,UC_MIPS_REG_PC
OUT=Path(__file__).parent;inv=json.loads((OUT/'callback-inventory.json').read_text());si=json.loads((OUT/'string-inventory.json').read_text());wi=json.loads((OUT/'name-writer-inventory.json').read_text());rng=random.Random(0x47415445);results=[]
spc=bytes.fromhex('8140');glyph=bytes.fromhex('8389');cases=[(b'',b'',b''),(spc*8,spc*8,spc*5),(glyph+spc*7,glyph+spc*7,glyph+spc*4),(glyph*8,spc*8,glyph*5),(spc*8,glyph*8,glyph*5),(glyph*8,glyph*8,b'')]
for _ in range(24):cases.append(tuple(b''.join(rng.choice((spc,glyph)) for _ in range(rng.randrange(cap+1))) for cap in (8,8,5)))
with tempfile.TemporaryDirectory(prefix='srwz-name-gate-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'name_gate_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_name_gate_model.argtypes=[ctypes.c_void_p]*5+[ctypes.c_uint,ctypes.c_int16,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);writer=next(x for x in wi['editions'] if x['edition']==ed);strings=next(x for x in si['editions'] if x['edition']==ed)['functions'];install(u,e,[(int(x['entry'],16),int(x['end'],16)) for x in strings.values()]);base=int(writer['substitution_buffers'][0],16)-1;target=int(r['confirmation_target'],16);gate=int(r['validation_block'],16);exit=int(r['common_exit'],16);adapted={};upper=[bytes(8) for _ in range(32)];calls=[]
  for pc in range(target,int(writer['end'],16),4):
   w=e.words(pc,1)[0]
   if w>>26 in (0x1e,0x1f):adapted[pc]=w;u.mem_write(pc,b'\0'*4)
  def hook(uc,pc,size,data):
   if pc==exit:uc.emu_stop();return
   if pc==target:calls.append(uc.reg_read(GPRS[4])&0xffffffff)
   w=adapted.get(pc)
   if w is None:return
   rs=(w>>21)&31;rt=(w>>16)&31;a=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
   if w>>26==0x1e:
    b=bytes(uc.mem_read(a,16))
    if rt:uc.reg_write(GPRS[rt],int.from_bytes(b[:8],'little'));upper[rt]=b[8:]
   else:uc.mem_write(a,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
  u.hook_add(UC_HOOK_CODE,hook)
  for i,fields in enumerate(cases):
   for count in range(4):
    obj=bytearray(rng.randbytes(0x70));struct.pack_into('<I',obj,0,int(r['vtable'],16));struct.pack_into('<3I',obj,0x50,0x1910000,0x1920000,0x1930000);glob=rng.randbytes(96);buffers=[]
    for j,(text,cap) in enumerate(zip(fields,(8,8,5))):
     b=bytearray(rng.randbytes(0x80));b[8:8+len(text)+2]=text+b'\0\0';b[0x42]=cap;buffers.append(ctypes.create_string_buffer(bytes(b)));u.mem_write(0x1910000+j*0x10000,bytes(b))
    ob=ctypes.create_string_buffer(bytes(obj));gb=ctypes.create_string_buffer(glob);event=ctypes.c_int32(0x5a);expected=c.native_name_gate_model(ob,*buffers,gb,96,count,ctypes.byref(event));assert expected in (0,1)
    u.mem_write(0x1900000,bytes(obj));u.mem_write(base,glob)
    for reg in GPRS[1:]:u.reg_write(reg,0)
    u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_GP,0x1800000);u.reg_write(UC_MIPS_REG_RA,0x8000);u.reg_write(GPRS[16],0x1900000);u.reg_write(GPRS[17],count);u.reg_write(GPRS[23],0x5a);calls.clear();u.emu_start(gate,0,count=100000)
    assert u.reg_read(UC_MIPS_REG_PC)==exit,(ed,i,count,'common exit not reached');assert calls==([0x1900000] if expected else []),(ed,i,count,'dispatch',calls);assert u.reg_read(GPRS[23])==event.value,(ed,i,count,'event code')
    regions=[('object',0x1900000,0x70,bytes(ob)[:0x70]),('globals',base,96,bytes(gb)[:96])]+[(f'field{j}',0x1910000+j*0x10000,0x80,bytes(b)[:0x80]) for j,b in enumerate(buffers)];hashes={}
    for name,address,n,expected_bytes in regions:
     actual=bytes(u.mem_read(address,n));assert actual==expected_bytes,(ed,i,count,name);hashes[name]=hashlib.sha256(actual).hexdigest()
    results.append({'edition':ed,'case':i,'field_count':count,'input_hex':[x.hex() for x in fields],'confirmation_called':bool(expected),'event_code':event.value,'region_sha256':hashes})
  print(ed,len(cases)*4,'native validation and virtual confirmation compositions passed',flush=True)
(OUT/'name-gate-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_validation_blocks_dispatch_real_name_writer_vtable_and_match_C_composition','case_count':len(results),'cases':results},indent=2)+'\n')
