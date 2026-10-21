"""Three native negative-placeholder/positive-number wrappers vs full C composition.
Tests initialized and lazy caches, exact state/records/packets/style byte/flags.
Explicit EE LQ/SQ and MULT-rd adapters only; no body stubs or GS/LRPS2 claim.
Style indices tested are readable rows 0..11, plus signed-byte -1 sentinel;
no claim that arbitrary negative style indices are valid.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
from execute import GPRS
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_LO,UC_MIPS_REG_HI
OUT=Path(__file__).parent;inv=json.loads((OUT/'geometry-inventory.json').read_text());ci=json.loads((OUT/'cache-inventory.json').read_text());rng=random.Random(0x504c4844);results=[]
with tempfile.TemporaryDirectory(prefix='srwz-placeholder-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'placeholder_model.c'),str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_placeholder_model.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32]+[ctypes.c_void_p]*6+[ctypes.c_int32,ctypes.c_int16,ctypes.c_int16,ctypes.c_int,ctypes.c_uint32,ctypes.c_int,ctypes.c_void_p];c.native_placeholder_model.restype=ctypes.c_uint32
 c.native_cache_setup_model.argtypes=[ctypes.c_void_p]*5+[ctypes.c_uint32,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,templates,seed,_=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);cache=next(x for x in ci['editions'] if x['edition']==ed);entry=int(r['entry'],16);first=int(cache['cached_packet'],16);second=first-208;flag=int(cache['lazy_flag'],16);gpstyle=0x1800000+r['style_GP_offset'];ct=ctypes.create_string_buffer(templates);table=ctypes.create_string_buffer(bytes.fromhex(r['style_first_12_rows']));se=ctypes.create_string_buffer(seed)
  adapters={};upper=[bytes(8) for _ in range(32)]
  spans=[(int(cache['setup'],16),int(cache['repeat'],16)),(entry,int(r['style_end'],16))]
  for lo,hi in spans:
   for pc in range(lo,hi,4):
    w=e.words(pc,1)[0]
    if w>>26 in (0x1e,0x1f) or (w>>26==0 and w&63 in (24,25) and (w>>11)&31):adapters[pc]=w;u.mem_write(pc,b'\0'*4)
  def hook(uc,pc,size,data):
   w=adapters.get(pc)
   if w is None:return
   rs=(w>>21)&31;rt=(w>>16)&31
   if w>>26==0:
    a=uc.reg_read(GPRS[rs])&0xffffffff;b=uc.reg_read(GPRS[rt])&0xffffffff;product=(ctypes.c_int32(a).value*ctypes.c_int32(b).value if w&63==24 else a*b)&0xffffffffffffffff
    uc.reg_write(GPRS[(w>>11)&31],ctypes.c_int32(product).value&0xffffffffffffffff);uc.reg_write(UC_MIPS_REG_LO,ctypes.c_int32(product).value&0xffffffffffffffff);uc.reg_write(UC_MIPS_REG_HI,ctypes.c_int32(product>>32).value&0xffffffffffffffff);return
   address=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
   if w>>26==0x1e:
    b=bytes(uc.mem_read(address,16))
    if rt:uc.reg_write(GPRS[rt],int.from_bytes(b[:8],'little'));upper[rt]=b[8:]
   else:uc.mem_write(address,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
  u.hook_add(UC_HOOK_CODE,hook)
  cases=[]
  for value in (-2147483648,-32768,-17,-16,-9,-8,-2,-1,0,1,10,2147483647):
   for right in (0,1):cases.append((value,right,False))
  for k in range(16):cases.append((-(k+1),k&1,True))
  cases=[(*item,None) for item in cases]+[(-2,k&1,False,k) for k in range(12)]
  for i,(value,right,lazy,style_override) in enumerate(cases):
   state=bytearray(rng.randbytes(0x90));struct.pack_into('<HH2h',state,0,7,9,2048,2048);struct.pack_into('<I',state,0x58,0x1a00000);struct.pack_into('<I',state,0x60,0x1b00000);struct.pack_into('<3h',state,0x2c,14,13,(12,-7)[i%2]);state[0x4a]=i%3;state[0x50]=i%2
   records=rng.randbytes(400*32);primary=rng.randbytes(320*32);cached=rng.randbytes(416);addr=0x1c00000;capacity=144+32767*64+256;x,y=(32760,-32760) if i%3==0 else (180,36);z=0x12345678;style=(255,511,256,0,1,4,8,11)[i%8];style=style if style_override is None else style_override;lazy_value=1 if lazy else 0;temporary=0x1ff0000-0xa0-0x240+0x40
   u.mem_write(F,bytes(state));u.mem_write(0x1b00000,records);u.mem_write(0x1a00000,primary);u.mem_write(second,cached);u.mem_write(addr,b'\xa5'*capacity);u.mem_write(flag,struct.pack('<I',lazy_value));u.mem_write(gpstyle,b'\xa5');u.mem_write(temporary,b'\xa5'*512)
   s=ctypes.create_string_buffer(bytes(state));rec=ctypes.create_string_buffer(records);ca=ctypes.create_string_buffer(cached[208:]);cb=ctypes.create_string_buffer(cached[:208]);out=ctypes.create_string_buffer(b'\xa5'*capacity);last=ctypes.c_uint8(0xa5);written=ctypes.c_size_t()
   if lazy and value<0:assert c.native_cache_setup_model(s,rec,se,ca,cb,temporary,ct)==0;lazy_value=0
   ret=c.native_placeholder_model(out,capacity,addr,cb,s,rec,ct,table,ctypes.byref(last),value,x,y,right,z,style,ctypes.byref(written));actual_return=call(u,entry,[value,x,y,right,addr,z,style])
   assert ret==actual_return,(ed,i,'return',hex(ret),hex(actual_return))
   regions=[('state',F,0x90,bytes(s)[:0x90]),('secondary',0x1b00000,len(records),bytes(rec)[:len(records)]),('primary',0x1a00000,len(primary),primary),('caches',second,416,bytes(cb)[:208]+bytes(ca)[:208]),('packet',addr,capacity,bytes(out)[:capacity])];hashes={}
   for name,address,n,expected in regions:
    actual=bytes(u.mem_read(address,n));assert actual==expected,(ed,i,value,right,lazy,name,[(j,a,b) for j,(a,b) in enumerate(zip(actual,expected)) if a!=b][:12]);hashes[name]=hashlib.sha256(actual).hexdigest()
   assert bytes(u.mem_read(gpstyle,1))==bytes([last.value]),(ed,i,'last style');assert int.from_bytes(u.mem_read(flag,4),'little')==lazy_value,(ed,i,'lazy flag')
   results.append({'edition':ed,'case':i,'value':value,'right':right,'lazy':lazy,'style':style,'xy':[x,y],'advance':(12,-7)[i%2],'written':written.value,'returned_pointer':hex(ret),'last_style_byte':last.value,'region_sha256':hashes})
  print(ed,len(cases),'native placeholder/number full-composition comparisons passed',flush=True)
(OUT/'placeholder-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_placeholder_and_positive_number_paths_match_complete_C_composition','case_count':len(results),'cases':results},indent=2)+'\n')
