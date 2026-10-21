"""Native cached-symbol first initialization against complete C composition.
Executes real setters, symbol producer and GIF builder; no function stubs.
Adapters only model EE LQ/SQ save/load semantics; this is not GS/LRPS2 proof.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
from execute import GPRS
from unicorn import UC_HOOK_CODE
OUT=Path(__file__).parent;inv=json.loads((OUT/'cache-inventory.json').read_text());rng=random.Random(0x43414348);results=[]
with tempfile.TemporaryDirectory(prefix='srwz-cache-setup-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'cache_setup_model.c'),str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_cache_setup_model.argtypes=[ctypes.c_void_p]*5+[ctypes.c_uint32,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,templates,seed,executed=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);entry=int(r['setup'],16);end=int(r['repeat'],16);cache1=int(r['cached_packet'],16)
  hi,lo=e.words(entry+0xfc,1)[0],e.words(entry+0x104,1)[0];cache2=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value
  adapters={};upper=[bytes(8) for _ in range(32)]
  for pc in range(entry,end,4):
   w=e.words(pc,1)[0]
   if w>>26 in (0x1e,0x1f):adapters[pc]=w;u.mem_write(pc,b'\0'*4)
  def hook(uc,pc,size,data):
   w=adapters.get(pc)
   if w is None:return
   rs=(w>>21)&31;rt=(w>>16)&31;address=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
   if w>>26==0x1e:
    b=bytes(uc.mem_read(address,16))
    if rt:uc.reg_write(GPRS[rt],int.from_bytes(b[:8],'little'));upper[rt]=b[8:]
   else:uc.mem_write(address,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
  u.hook_add(UC_HOOK_CODE,hook);ct=ctypes.create_string_buffer(templates);se=ctypes.create_string_buffer(seed)
  for i in range(48):
   initial=bytearray(rng.randbytes(0x90));struct.pack_into('<HH2h',initial,0,7,(0,9,254,255)[i%4],2048,2048);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x60,0x1d00000);struct.pack_into('<3h',initial,0x2c,14,(11,13,271)[i%3],12);initial[0x4a]=(0,2,128,255)[i%4];initial[0x50]=(0,1,128,255)[i//4%4]
   records=rng.randbytes(400*32);primary=rng.randbytes(320*32);initial_cache1=rng.randbytes(240);initial_cache2=rng.randbytes(240)
   u.mem_write(F,bytes(initial));u.mem_write(0x1d00000,records);u.mem_write(0x1a00000,primary);u.mem_write(cache1,initial_cache1);u.mem_write(cache2,initial_cache2);u.mem_write(int(r['lazy_flag'],16),struct.pack('<I',0x12345678))
   u.mem_write(0x1ff0000-0x240+0x40,b'\xa5'*512)
   s=ctypes.create_string_buffer(bytes(initial));rec=ctypes.create_string_buffer(records);a=ctypes.create_string_buffer(initial_cache1);b=ctypes.create_string_buffer(initial_cache2)
   assert c.native_cache_setup_model(s,rec,se,a,b,0x1ff0000-0x240+0x40,ct)==0
   call(u,entry,[])
   actual_state=bytes(u.mem_read(F,0x90));expected_state=bytes(s)[:0x90];assert actual_state==expected_state,(ed,i,'state',[(j,a,b) for j,(a,b) in enumerate(zip(actual_state,expected_state)) if a!=b])
   regions=[('secondary',0x1d00000,len(records),bytes(rec)[:len(records)]),('primary',0x1a00000,len(primary),primary),('cache_first',cache1,240,bytes(a)[:240]),('cache_second',cache2,240,bytes(b)[:208]+bytes(a)[:32])]
   hashes={}
   for name,address,n,expected in regions:
    actual=bytes(u.mem_read(address,n));assert actual==expected,(ed,i,name,[(j,a,b) for j,(a,b) in enumerate(zip(actual,expected)) if a!=b][:12]);hashes[name]=hashlib.sha256(actual).hexdigest()
   assert bytes(u.mem_read(int(r['lazy_flag'],16),4))==struct.pack('<I',0x12345678),(ed,i,'setup changed caller-owned lazy flag')
   results.append({'edition':ed,'case':i,'secondary_initial_count':int.from_bytes(initial[2:4],'little'),'initial_height':ctypes.c_int16(int.from_bytes(initial[0x2e:0x30],'little')).value,'shear':initial[0x4a],'outline':initial[0x50],'second_cache_address':hex(cache2),'state_sha256':hashlib.sha256(actual_state).hexdigest(),'region_sha256':hashes})
  print(ed,48,'native first cache setup full-state/record/cache comparisons passed',flush=True)
(OUT/'cache-setup-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_cache_initializers_match_complete_C_composition','case_count':len(results),'cases':results},indent=2)+'\n')
