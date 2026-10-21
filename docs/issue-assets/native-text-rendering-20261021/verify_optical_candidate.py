"""Analysis-only candidate: 3072 exhaustive operand/mode/digit-route cases
and 144 reset/raw-height/signed-coordinate edge cases across three editions.
Two complete native parser calls per case check transient-marker lifetime.
Also checks classified heights resembling markers and signed Y wrap domains.
No production executable/ISO edits, no GS or LRPS2 visual acceptance.
"""
from pathlib import Path
import sys,json,struct,ctypes,subprocess,tempfile,hashlib,argparse
parser=argparse.ArgumentParser();parser.add_argument('--packed',action='store_true');PACKED=parser.parse_args().packed
OUT=Path(__file__).parent;sys.path.insert(0,str(OUT.parents[2]/'tools'))
from numeric_harness import machine,call
if PACKED:
 from optical_packed_candidate import install
else:
 from optical_candidate import install
from unicorn import UC_HOOK_CODE
results=[]
with tempfile.TemporaryDirectory(prefix='srwz-optical-parser-') as td:
 path=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'optical_model.c'),'-o',str(path)],check=True)
 c=ctypes.CDLL(str(path));c.native_parse_optical_model.argtypes=[ctypes.c_void_p]*7+[ctypes.c_uint32,ctypes.c_uint,ctypes.c_uint]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed,True);proof=install(u,e,ed);d=int(row['core_va_delta'],16)
  hi=e.words(0x13a8ac+d,1)[0];lo=e.words(0x13a8b4+d,1)[0];va=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;table=bytearray()
  for off in range(0,65536,4):
   r=e.read(va+off,4);table+=r
   if r[:2]==b'\0\0':break
  ext=ctypes.create_string_buffer(bytes(table));gp=ctypes.c_int16(e.words(0x13aa84+d,1)[0]&65535).value
  observed_early=[False]
  def atlas_exit(uc,pc,size,data):observed_early[0]=True
  u.hook_add(UC_HOOK_CODE,atlas_exit,begin=0x13aa34+d,end=0x13aa34+d)
  cases=[]
  for mode in (0,1):
   for fast in (0,1):
    for value in range(256):cases.append((f'height_{value:02x}_mode{mode}_fast{fast}',bytes([0x33,value])+bytes.fromhex('8260824f889f'),mode,fast,12,36,(21,12,21,14,14,12,12,14),12))
  if PACKED:
   for opcode in (0x32,0x34,0x35,0x36):
    for mode in (0,1):
     for value in range(256):
      payload=bytes([opcode,value])+bytes.fromhex('8260824f889f')+(bytes.fromhex('0a889f') if opcode==0x35 else b'')
      cases.append((f'control_{opcode:02x}_{value:02x}_mode{mode}',payload,mode,mode%2,12,36,(21,12,21,14,14,12,12,14),12))
  for y in (-32768,-32767,-1,0,32767):
   for v in (0x8a,0x8b,0x8c,0x8d,0x8e):cases.append((f'coordinate_wrap_y{y}_h{v:02x}',bytes([0x33,v])+bytes.fromhex('8260889f'),1,0,-32768,y,(21,12,21,14,14,12,12,14),12))
  for mode in (0,1):
   for classified in (138,139,140,141,142,267,268,269,270):
    cases.append((f'raw_native_height_{classified}_mode{mode}',bytes.fromhex('8260889f'),mode,0,12,36,(21,classified,21,14,14,classified,12,14),classified if not mode else classified-128))
  for value in (0x8a,0x8b,0x8c,0x8d,0x8e):
   cases.append((f'optical_reset_{value:02x}',bytes([0x33,value])+bytes.fromhex('826030ff889f'),1,0,12,36,(21,12,21,14,14,12,12,14),12))
  if PACKED:
   for edge in ('record_limit','atlas_full','atlas_last_tile','atlas_page_boundary'):
    cases.append((edge,bytes.fromhex('338e82608260889f'),1,0,12,36,(21,12,21,14,14,12,12,14),12))
  for name,payload,mode,fast,x,y,classified,explicit_h in cases:
   initial=bytearray(0x90);struct.pack_into('<2h',initial,0x10,x,y);struct.pack_into('<4h',initial,0x14,18,explicit_h,18,14);struct.pack_into('<8h',initial,0x38,*classified);struct.pack_into('<H',initial,0x48,mode);initial[0x4b:0x50]=b'\1'*5;struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x88,0 if fast else 1)
   if name=='record_limit':struct.pack_into('<H',initial,0,318)
   if name=='atlas_full':struct.pack_into('<2h',initial,8,0,480)
   if name=='atlas_last_tile':struct.pack_into('<2h',initial,8,480,456)
   if name=='atlas_page_boundary':struct.pack_into('<2h',initial,8,480,216)
   u.mem_write(F,bytes(initial));u.mem_write(F-16,struct.pack('<I',0x1b00000));u.mem_write(0x1800000+gp,b'\0\0');u.mem_write(0x1a00000,b'\xa5'*(320*32));u.mem_write(0x1b00000,b'\0'*8192)
   state=ctypes.create_string_buffer(bytes(initial));records=ctypes.create_string_buffer(b'\xa5'*(320*32));pending=(ctypes.c_uint16*4096)();n=ctypes.c_uint();empty=ctypes.create_string_buffer(b'\0'*4);subs=(ctypes.c_void_p*4)(*[ctypes.addressof(empty)]*4)
   calls=[]
   for index,data in enumerate((payload,bytes.fromhex('889f'))):
    text=ctypes.create_string_buffer(data+b'\0\0');u.mem_write(0x1900000,data+b'\0\0');early=c.native_parse_optical_model(state,records,pending,ctypes.byref(n),text,ext,subs,0xffffffff,320,4096);assert early>=0;observed_early[0]=False
    call(u,0x13a290+d,[0x1900000,0,-1,0]);assert observed_early[0]==bool(early),(ed,name,index,'atlas early-exit path');actual=bytes(u.mem_read(F,0x90));expected=bytes(state)[:0x90];assert actual==expected,(ed,name,index,'state',[(i,a,b) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b][:20]);rec=bytes(u.mem_read(0x1a00000,320*32));assert rec==bytes(records)[:320*32],(ed,name,index,'records');assert bytes(u.mem_read(0x1b00000,n.value*2))==bytes(pending)[:n.value*2],(ed,name,index,'pending');assert int.from_bytes(u.mem_read(0x1800000+gp,2),'little')==n.value;assert int.from_bytes(u.mem_read(F-16,4),'little')==0x1b00000+n.value*2
    count=int.from_bytes(actual[:2],'little')
    if name.startswith('optical_reset_'):
     height=int(name[-2:],16)-128
     assert struct.unpack_from('<h',rec,32+14)[0]==height,(ed,name,'working height must stay decoded after reset')
    calls.append(dict(call=index,early_exit=bool(early),pen=list(struct.unpack_from('<2h',actual,0x10)),explicit_height=struct.unpack_from('<h',actual,0x16)[0],record_positions=[list(struct.unpack_from('<2h',rec,i*32+4)) for i in range(count)],record_geometry=[list(struct.unpack_from('<2h',rec,i*32+12)) for i in range(count)],state_sha256=hashlib.sha256(actual).hexdigest(),records_sha256=hashlib.sha256(rec).hexdigest()))
   results.append(dict(edition=ed,case=name,mode=mode,fast_digits=bool(fast),payload_hex=payload.hex(' '),calls=calls))
  print(ed,len(cases),'two-call optical-candidate compositions match C',flush=True)
(OUT/('optical-packed-candidate-execution.json' if PACKED else 'optical-candidate-execution.json')).write_text(json.dumps(dict(scope=__doc__,packed_native_code_space=PACKED,status='analysis_only_native_candidate_matches_C_two_call_state_record_and_upload_domains',case_count=len(results),native_calls=len(results)*2,cases=results),indent=2)+'\n')
