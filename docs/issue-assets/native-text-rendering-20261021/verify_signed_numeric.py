"""Native signed wrapper vs independent C call plan composed with native leaves.
All leaves execute their real instructions; no function-body stubs. The parser,
numeric producer and GIF builder have separate byte-exact C-model proofs.
This verifies wrapper coordination, not an independent full-C signed renderer.
No GS, DMA or LRPS2 evidence is claimed.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
from unicorn import UC_HOOK_CODE
from execute import GPRS
OUT=Path(__file__).parent;rng=random.Random(0x5349474e);results=[]
with tempfile.TemporaryDirectory(prefix='srwz-signed-number-') as td:
 lib=Path(td)/'plan.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'signed_numeric_plan.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_signed_numeric_plan.argtypes=[ctypes.c_int32,ctypes.c_int16,ctypes.c_int16,ctypes.c_int,ctypes.c_int16,ctypes.c_int16,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,templates,seed,adapted=machine(ed,True);v,_,_,_,_,_,_,_=machine(ed,True)
  d=int(row['core_va_delta'],16);signed=int(fn['signed_number']['entry'],16);bridge=int(fn['text_at_position']['entry'],16);number=int(fn['unsigned_number']['entry'],16)
  hi=e.words(signed+0x48,1)[0];lo=e.words(signed+0x58,1)[0];minus=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value
  assert e.read(minus,4)[2:]==b'\0\0',(ed,'minus string')
  observed=[]
  def trace(uc,pc,size,data):
   if pc in (bridge,number):observed.append({'entry':hex(pc),'args':[uc.reg_read(GPRS[k])&0xffffffff for k in range(4,11)]})
  u.hook_add(UC_HOOK_CODE,trace)
  cases=[]
  for value in (0,1,9,10,2147483647,-1,-9,-10,-99,-100,-1000000000,-2147483648):
   for right in (0,1):
    for immediate in (0,1):cases.append((value,right,immediate))
  cases.extend((rng.randrange(-2147483648,2147483648),k&1,(k>>1)&1) for k in range(40))
  for i,(value,right,immediate) in enumerate(cases):
   call(v,int(row['initializer_entry'],16),[]);initial=bytearray(v.mem_read(F,0x90));struct.pack_into('<HH2h',initial,0,7,9,2048,2048);struct.pack_into('<2h',initial,8,0,48);struct.pack_into('<4h',initial,0x14,21,12,21,14);struct.pack_into('<3h',initial,0x2c,14,13,12);struct.pack_into('<8h',initial,0x38,21,12,21,14,14,12,12,14);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x60,0x1d00000);initial[0x4a]=(0,2,128)[i%3];initial[0x50]=i%2;struct.pack_into('<I',initial,0x88,i%2)
   if i%11==0:struct.pack_into('<h',initial,10,480)
   primary=rng.randbytes(320*32);secondary=rng.randbytes(400*32);capacity=131072;addr=0x1c00000+(i%4)*16;pointer=(addr|0x30000000) if immediate else 0;x,y=(32760,-32760) if i%7==0 else (180,36);z=0xffffffff if i&1 else 0x12345678;chain=i%2
   gpimm=e.words(0x13aa84+d,1)[0]&65535;gpoff=ctypes.c_int16(gpimm).value
   for m in (u,v):
    m.mem_write(F,bytes(initial));m.mem_write(F-0x10,struct.pack('<I',0x1b00000));m.mem_write(0x1800000+gpoff,b'\0\0');m.mem_write(0x1b00000,b'\xa5'*1024);m.mem_write(0x1a00000,primary);m.mem_write(0x1d00000,secondary);m.mem_write(addr,b'\xa5'*capacity)
   plan=(ctypes.c_int32*8)();c.native_signed_numeric_plan(value,x,y,right,12,12,plan)
   leaf_pointer=pointer
   if plan[0]:leaf_pointer=call(v,bridge,[minus,plan[1],plan[2],pointer,ctypes.c_int32(z).value,0])
   expected_return=call(v,number,[plan[3],plan[4],plan[5],right,leaf_pointer,ctypes.c_int32(z).value,chain])
   observed.clear();actual_return=call(u,signed,[value,x,y,right,pointer,ctypes.c_int32(z).value,chain]);events=list(observed)
   assert actual_return==expected_return,(ed,i,'return',hex(actual_return),hex(expected_return))
   expected_entries=[hex(bridge),hex(number)] if value<0 else [hex(number)]
   assert [event['entry'] for event in events]==expected_entries,(ed,i,'leaf schedule',events)
   if value<0:assert events[0]['args'][1:3]==[plan[1]&0xffffffff,plan[2]&0xffffffff],(ed,i,'minus coords',events,list(plan))
   assert events[-1]['args'][:4]==[plan[3]&0xffffffff,plan[4]&0xffffffff,plan[5]&0xffffffff,right],(ed,i,'numeric args',events,list(plan))
   regions=[('state',F,0x90),('primary',0x1a00000,len(primary)),('secondary',0x1d00000,len(secondary)),('packet',addr,capacity),('upload_indices',0x1b00000,1024),('upload_count',0x1800000+gpoff,2),('upload_pointer',F-0x10,4)]
   hashes={}
   for name,address,n in regions:
    a=bytes(u.mem_read(address,n));b=bytes(v.mem_read(address,n));assert a==b,(ed,i,value,right,immediate,name,[(j,x,y) for j,(x,y) in enumerate(zip(a,b)) if x!=y][:12]);hashes[name]=hashlib.sha256(a).hexdigest()
   results.append({'edition':ed,'case':i,'value':value,'right':right,'immediate':immediate,'chain':chain,'input_xy':[x,y],'atlas_exhausted':i%11==0,'plan':list(plan),'observed_leaf_calls':events,'return':hex(actual_return),'region_sha256':hashes})
  print(ed,len(cases),'native signed wrapper schedules and full observable state match C-plan native-leaf composition',flush=True)
(OUT/'signed-numeric-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_signed_wrappers_match_independent_C_plan_native_leaf_composition','case_count':len(results),'cases':results},indent=2)+'\n')
