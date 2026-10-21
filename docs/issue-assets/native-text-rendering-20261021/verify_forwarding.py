"""Native cached-repeat wrapper non-@ branch vs native position/parser bridge.
Validates forwarding only: both leaves execute real instructions, whose separate
C-model evidence exists. No independent full-C wrapper, GS or LRPS2 claim.
"""
from pathlib import Path
import json,ctypes,struct,hashlib
from numeric_harness import machine,call
from execute import GPRS
from unicorn import UC_HOOK_CODE
OUT=Path(__file__).parent;inv=json.loads((OUT/'cache-inventory.json').read_text());results=[]
payloads=[b'',bytes.fromhex('889f'),bytes.fromhex('8266824f889f'),bytes.fromhex('330e8266330c889f'),bytes.fromhex('320e340c826632153415889f'),bytes.fromhex('889f0a889f'),bytes.fromhex('3101889f'),bytes.fromhex('3080889f')]
for ed in ('original','best','sp'):
 u,e,row,fn,F,_,_,_=machine(ed,True);v,_,_,_,_,_,_,_=machine(ed,True);r=next(x for x in inv['editions'] if x['edition']==ed);entry=int(r['repeat'],16);end=int(r['repeat_end'],16);bridge=int(fn['text_at_position']['entry'],16);d=int(row['core_va_delta'],16)
 adapters={};upper=[bytes(8) for _ in range(32)];events=[]
 for pc in range(entry,end,4):
  w=e.words(pc,1)[0]
  if w>>26 in (0x1e,0x1f):adapters[pc]=w;u.mem_write(pc,b'\0'*4)
 def hook(uc,pc,size,data):
  if pc==bridge:events.append([uc.reg_read(GPRS[j])&0xffffffff for j in range(4,10)])
  w=adapters.get(pc)
  if w is None:return
  rs=(w>>21)&31;rt=(w>>16)&31;addr=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
  if w>>26==0x1e:
   b=bytes(uc.mem_read(addr,16))
   if rt:uc.reg_write(GPRS[rt],int.from_bytes(b[:8],'little'));upper[rt]=b[8:]
  else:uc.mem_write(addr,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
 u.hook_add(UC_HOOK_CODE,hook)
 gp_off=ctypes.c_int16(e.words(0x13aa84+d,1)[0]&65535).value
 for i,payload in enumerate(payloads):
  for variant in range(6):
   call(v,int(row['initializer_entry'],16),[]);initial=bytearray(v.mem_read(F,0x90));struct.pack_into('<HH2h',initial,0,7,9,2048,2048);struct.pack_into('<2h',initial,8,0,480 if variant==5 else 48);struct.pack_into('<4h',initial,0x14,21,(10,12)[variant%2],21,14);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x60,0x1d00000);struct.pack_into('<I',initial,0x88,variant%2);initial[0x4a]=variant%3;initial[0x50]=variant%2
   pointer=0x31c00000 if variant%2 else 0;x,y=180,36;z=0x12345678 if variant%3 else -1
   for m in (u,v):
    m.mem_write(F,bytes(initial));m.mem_write(F-0x10,struct.pack('<I',0x1b00000));m.mem_write(0x1800000+gp_off,b'\0\0');m.mem_write(0x1b00000,b'\xa5'*1024);m.mem_write(0x1a00000,b'\xa5'*(320*32));m.mem_write(0x1d00000,b'\xa5'*(400*32));m.mem_write(0x1c00000,b'\xa5'*131072);m.mem_write(0x1900000,payload+b'\0\0');m.mem_write(int(r['lazy_flag'],16),b'\xff'*4)
   args=[0x1900000,x,y,pointer,z,0];expected=call(v,bridge,args);events.clear();actual=call(u,entry,args[:5]);assert actual==expected,(ed,i,variant,'return');assert events==[[x&0xffffffff for x in args]],(ed,i,variant,'forwarded arguments',events)
   regions=[('state',F,0x90),('primary',0x1a00000,320*32),('secondary',0x1d00000,400*32),('packet',0x1c00000,131072),('indices',0x1b00000,1024),('pending',0x1800000+gp_off,2),('index_pointer',F-0x10,4),('lazy_flag',int(r['lazy_flag'],16),4)];hashes={}
   for name,address,n in regions:
    a=bytes(u.mem_read(address,n));b=bytes(v.mem_read(address,n));assert a==b,(ed,i,variant,name);hashes[name]=hashlib.sha256(a).hexdigest()
   results.append({'edition':ed,'payload':payload.hex(),'variant':variant,'immediate':bool(pointer),'return':hex(actual),'forwarded_arguments':events[0],'region_sha256':hashes})
 print(ed,len(payloads)*6,'native non-@ wrapper forwarding comparisons passed',flush=True)
(OUT/'forwarding-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_non_at_wrappers_match_direct_native_bridge_composition','case_count':len(results),'cases':results},indent=2)+'\n')
