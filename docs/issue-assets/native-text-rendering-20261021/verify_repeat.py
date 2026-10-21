"""Execute native @N packet geometry after an explicit decimal-parser contract.
Lazy cache initialization is marked already complete; cache bytes are supplied.
The atoi call is intercepted with declared int32 output; its CRT arithmetic
uses additional EE MMI not covered by this harness. No complete @N parser,
lazy-setup proof, GS or LRPS2 claim.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib,argparse
from numeric_harness import machine,call
from execute import GPRS
args=argparse.ArgumentParser();args.add_argument('--native-decimal',action='store_true');args.add_argument('--native-lazy',action='store_true');options=args.parse_args();NATIVE=options.native_decimal;LAZY=options.native_lazy
assert not LAZY or NATIVE,'--native-lazy requires --native-decimal'
OUT=Path(__file__).parent;inv=json.loads((OUT/'cache-inventory.json').read_text());rng=random.Random(0x52455054);results=[]
with tempfile.TemporaryDirectory(prefix='srwz-repeat-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'repeat_model.c'),*([str(OUT/'cache_setup_model.c'),str(OUT/'packet_model.c')] if LAZY else []),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_repeat_model.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int32,ctypes.c_int16,ctypes.c_int16,ctypes.c_uint32,ctypes.c_void_p];c.native_repeat_model.restype=ctypes.c_uint32
 if LAZY:c.native_cache_setup_model.argtypes=[ctypes.c_void_p]*5+[ctypes.c_uint32,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,templates,seed,_=machine(ed,True);r=next(x for x in inv['editions'] if x['edition']==ed);entry=int(r['repeat'],16);end=int(r['repeat_end'],16);cacheaddr=int(r['cached_packet'],16)
  # machine hook only adapts its registered ranges; add a separate full128
  # LQ/SQ adapter for this independently located renderer span.
  from unicorn import UC_HOOK_CODE
  adapters={};upper=[bytes(8) for _ in range(32)]
  for pc in range(int(r['setup'],16) if LAZY else entry,end,4):
   w=e.words(pc,1)[0]
   if w>>26 in (0x1e,0x1f):adapters[pc]=w;u.mem_write(pc,b'\0'*4)
  if NATIVE:
   from crt_adapter import install
   crt_seen=install(u,e)
  from collections import deque
  recent=deque(maxlen=12)
  def hook(uc,pc,size,data):
   recent.append(hex(pc))
   if not NATIVE and pc==int(r['atoi'],16):
    from unicorn.mips_const import UC_MIPS_REG_RA,UC_MIPS_REG_2,UC_MIPS_REG_PC
    uc.reg_write(UC_MIPS_REG_2,count&0xffffffffffffffff);uc.reg_write(UC_MIPS_REG_PC,uc.reg_read(UC_MIPS_REG_RA));return
   w=adapters.get(pc)
   if w is None:return
   rs=(w>>21)&31;rt=(w>>16)&31;address=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
   if w>>26==0x1e:
    b=bytes(uc.mem_read(address,16))
    if rt:uc.reg_write(GPRS[rt],int.from_bytes(b[:8],'little'));upper[rt]=b[8:]
   else:uc.mem_write(address,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
  u.hook_add(UC_HOOK_CODE,hook)
  cases=[(str(n),n) for n in (-2147483648,-10,-1,0,1,2,7,8,9,15,16,17,31,32,32766,32767,32768)]+[('  +9xyz',9),('nondigit',0),('',0)]
  for i,(text,count) in enumerate(cases):
   state=bytearray(rng.randbytes(0x90));struct.pack_into('<3h',state,0x40,14,12,12);cache=rng.randbytes(208);capacity=144+32767*64+128;address=0x1900000;x,y=(32760,-32760) if i%3==0 else (180,36);z=0x12345678
   if LAZY:
    struct.pack_into('<HH',state,0,7,9);struct.pack_into('<I',state,0x58,0x1a00000);struct.pack_into('<I',state,0x60,0x1d00000)
   u.mem_write(F,bytes(state));u.mem_write(cacheaddr,cache);u.mem_write(int(r['lazy_flag'],16),struct.pack('<I',1 if LAZY else 0));u.mem_write(0x1800000,b'@'+text.encode()+b'\0');u.mem_write(address,b'\xa5'*capacity)
   s=ctypes.create_string_buffer(bytes(state));ca=ctypes.create_string_buffer(cache);out=ctypes.create_string_buffer(b'\xa5'*capacity);written=ctypes.c_size_t()
   if LAZY:
    temporary=0x1ff0000-0x60-0x240+0x40;u.mem_write(temporary,b'\xa5'*512)
    u.mem_write(0x1d00000,b'\xa5'*(400*32));rec=ctypes.create_string_buffer(b'\xa5'*(400*32));second=ctypes.create_string_buffer(208);ct=ctypes.create_string_buffer(templates);se=ctypes.create_string_buffer(seed)
    assert c.native_cache_setup_model(s,rec,se,ca,second,temporary,ct)==0
   ret=c.native_repeat_model(out,capacity,address,ca,s,count,x,y,z,ctypes.byref(written));
   try:actual_return=call(u,entry,[0x1800000,x,y,address,z])
   except Exception:print('native recent PCs',list(recent),flush=True);raise
   assert actual_return==ret,(ed,i,text,'return',hex(actual_return),hex(ret))
   actual=bytes(u.mem_read(address,capacity));expected=bytes(out)[:capacity];assert actual==expected,(ed,i,text,'packet',[(j,a,b) for j,(a,b) in enumerate(zip(actual,expected)) if a!=b][:16])
   actual_cache=bytes(u.mem_read(cacheaddr,208));assert actual_cache==bytes(ca)[:208],(ed,i,text,'cache')
   assert bytes(u.mem_read(F,0x90))==bytes(s)[:0x90],(ed,i,text,'font state changed')
   if LAZY:
    assert bytes(u.mem_read(0x1d00000,400*32))==bytes(rec)[:400*32],(ed,i,'lazy secondary records')
    assert bytes(u.mem_read(cacheaddr-208,208))==bytes(second)[:208],(ed,i,'lazy second cache')
    assert bytes(u.mem_read(int(r['lazy_flag'],16),4))==b'\0'*4,(ed,i,'lazy flag not cleared')
   results.append({'edition':ed,'case':i,'input':text,'expected_atoi_result':count,'cache_initialization':'native full setup' if LAZY else 'preinitialized cache contract','atoi_execution':'native CRT instructions with explicit EE adapters' if NATIVE else 'explicit external contract, CRT body not executed','written':written.value,'returned_pointer':hex(ret),'xy':[x,y],'packet_sha256':hashlib.sha256(actual[:written.value]).hexdigest(),'full_buffer_sha256':hashlib.sha256(actual).hexdigest(),'cache_sha256':hashlib.sha256(actual_cache).hexdigest()})
  print(ed,len(cases),'native @N post-parse packet buffers, cache mutations, state and returns match C model',flush=True)
(OUT/('repeat-full-execution.json' if LAZY else 'repeat-native-decimal-execution.json' if NATIVE else 'repeat-execution.json')).write_text(json.dumps({'scope':(('Native decimal parser and lazy setup executed, complete C composition of state, caches, records, packet and flag; declared EE adapters; no GS/LRPS2 claim.' if LAZY else 'Native decimal parser executed; cached lazy setup marked complete; EE MOVZ/N and declared CRT MMI subset adapted. No GS/LRPS2 claim.') if NATIVE else __doc__),'status':(('three_native_cached_repeat_paths_with_full_lazy_setup_and_decimal_match_C_composition' if LAZY else 'three_native_cached_repeat_paths_with_native_decimal_match_C_byte_model') if NATIVE else 'three_native_cached_repeat_post_parse_paths_match_C_byte_model_with_explicit_atoi_contract'),'case_count':len(results),'cases':results},indent=2)+'\n')
