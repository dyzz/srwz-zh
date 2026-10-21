"""Compose native number/symbol producers with native GIF packet construction.
Byte-exact integer execution and C composition; no GS/DMA or LRPS2 claim.
Existing primary/secondary queues are seeded and checked for exact restoration.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
OUT=Path(__file__).parent;rng=random.Random(0x4e554d49);results=[]
with tempfile.TemporaryDirectory(prefix='srwz-numeric-immediate-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'numeric_model.c'),str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_number_records_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int32,ctypes.c_int16,ctypes.c_int16,ctypes.c_int,ctypes.c_uint32,ctypes.c_uint]
 c.native_symbol_records_model.argtypes=[ctypes.c_void_p]*4+[ctypes.c_uint,ctypes.c_int16,ctypes.c_int16,ctypes.c_int32,ctypes.c_uint32,ctypes.c_uint]
 c.native_secondary_immediate_model.argtypes=[ctypes.c_void_p]*2+[ctypes.c_uint16]*2+[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p];c.native_secondary_immediate_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  u,e,row,fn,F,templates,seed,adapted=machine(ed);ct=ctypes.create_string_buffer(templates);se=ctypes.create_string_buffer(seed)
  cases=[]
  for k in range(72):
   name='symbol_list' if k&1 else 'unsigned_number';value=(seed[(k%42)*2:(k%42)*2+2]*((k%5)+1)) if k&1 else (0,1,9,10,999,2147483647)[k//2%6]
   cases.append((name,value,k%2,(0,7,253,254)[k//2%4],k//4%2,k//8%4*16,(0,0x30000000)[k//16%2],(0,2,128)[k//3%3],k//6%2))
  for chain in (0,1):cases.append(('symbol_list',b'',0,9,chain,48,0x30000000,0,0))
  for i,(name,value,right,old_secondary,chain,align,alias,shear,outline) in enumerate(cases):
   initial=bytearray(rng.randbytes(0x90));struct.pack_into('<HH2h',initial,0,7,old_secondary,2048,2048);struct.pack_into('<3h',initial,0x2c,14,13,12);struct.pack_into('<I',initial,0x58,0x1b00000);struct.pack_into('<I',initial,0x60,0x1a00000);initial[0x4a]=shear;initial[0x50]=outline
   records=rng.randbytes(400*32);primary=rng.randbytes(320*32);capacity=131072;addr=0x1c00000+align;pointer=addr|alias;x,y=180,36;z=0xffffffff if i&1 else 0x12345678
   u.mem_write(F,bytes(initial));u.mem_write(0x1a00000,records);u.mem_write(0x1b00000,primary);u.mem_write(addr,b'\xa5'*capacity)
   state=ctypes.create_string_buffer(bytes(initial));rec=ctypes.create_string_buffer(records);out=ctypes.create_string_buffer(b'\xa5'*capacity)
   if name=='unsigned_number':
    args=[value,x,y,right,pointer,ctypes.c_int32(z).value,chain];assert c.native_number_records_model(state,rec,value,x,y,right,z,400)==0
   else:
    payload=value+b'\0\0';u.mem_write(0x1900000,payload);text=ctypes.create_string_buffer(payload);args=[0x1900000,x,y,12,pointer,ctypes.c_int32(z).value,chain]
    assert c.native_symbol_records_model(state,rec,text,se,42,x,y,12,z,400)==0
   written=ctypes.c_size_t();expected_return=c.native_secondary_immediate_model(state,rec,7,old_secondary,out,capacity,pointer,chain,ct,ctypes.byref(written))
   returned=call(u,int(fn[name]['entry'],16),args)
   assert returned==expected_return,(ed,i,name,'return',hex(returned),hex(expected_return))
   actual=bytes(u.mem_read(F,0x90));expected=bytes(state)[:0x90]
   assert actual==expected,(ed,i,name,'state',[(j,a,b) for j,(a,b) in enumerate(zip(actual,expected)) if a!=b])
   actual_rec=bytes(u.mem_read(0x1a00000,len(records)));assert actual_rec==bytes(rec)[:len(records)],(ed,i,name,'secondary records')
   assert bytes(u.mem_read(0x1b00000,len(primary)))==primary,(ed,i,name,'existing primary records changed')
   packet=bytes(u.mem_read(addr,capacity));expected_packet=bytes(out)[:capacity]
   assert packet==expected_packet,(ed,i,name,'packet',[(j,a,b) for j,(a,b) in enumerate(zip(packet,expected_packet)) if a!=b][:20])
   results.append({'edition':ed,'case':i,'operation':name,'input':value.hex() if isinstance(value,bytes) else value,'existing_primary':7,'existing_secondary':old_secondary,'chain':chain,'alignment':align,'alias':hex(alias),'shear':shear,'outline':outline,'returned_pointer':hex(returned),'written':written.value,'full_packet_buffer_sha256':hashlib.sha256(packet).hexdigest(),'full_state_sha256':hashlib.sha256(actual).hexdigest(),'full_record_buffer_sha256':hashlib.sha256(actual_rec).hexdigest()})
  print(ed,len(cases),'native immediate numeric/symbol compositions match full state, records, packet and return',flush=True)
(OUT/'numeric-immediate-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_immediate_numeric_symbol_compositions_match_C','case_count':len(results),'cases':results},indent=2)+'\n')
