"""Composed parser + GIF builder vs native 13A290 with nonzero a1.
Checks native queue rollback and packet output in one complete function call.
EE LQ/SQ are adapted in emulation memory; no GS/rasterizer is executed.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,hashlib
from verify_parse import cases
from execute import run_case
from inventory import native
OUT=Path(__file__).parent;inv=json.loads((OUT/'inventory.json').read_text());report=[]
with tempfile.TemporaryDirectory(prefix='srwz-immediate-model-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'parse_model.c'),str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_parse_model.argtypes=[ctypes.c_void_p]*7+[ctypes.c_uint32,ctypes.c_uint,ctypes.c_uint];c.native_parse_model.restype=ctypes.c_int
 c.native_packet_model.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint,ctypes.c_int16,ctypes.c_int16,ctypes.c_void_p,ctypes.c_void_p];c.native_packet_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  elf,_=native(ed);e=next(r for r in inv['editions'] if r['edition']==ed);d=int(e['core_va_delta'],16)
  hi,lo=elf.words(0x13acd0+d,2);im=lo&65535;tv=((hi&65535)<<16)+(im if im<32768 else im-65536);templates=ctypes.create_string_buffer(elf.read(tv,0xd0))
  a,b=elf.words(0x13a8ac+d,1)[0],elf.words(0x13a8b4+d,1)[0];im=b&65535;va=((a&65535)<<16)+(im if im<32768 else im-65536);table=bytearray()
  for o in range(0,65536,4):
   row=elf.read(va+o,4);table.extend(row)
   if row[:2]==b'\0\0':break
  ext=ctypes.create_string_buffer(bytes(table))
  expanded=[('empty_input',b'',{})]+cases
  for k,(name,payload,oldkw) in enumerate(expanded):
   kw=dict(oldkw);patch={0:struct.pack('<2H',k%3,3),4:struct.pack('<2h',2048,2048)};patch.update(kw.get('state_patch') or {});kw['state_patch']=patch
   ptr=0x31c00000+(k%4)*16;chain=k%2
   r=run_case(ed,payload,details=True,packet_addr=ptr,packet_chain=chain,**kw)
   initial=bytes.fromhex(r['initial_state']);state=ctypes.create_string_buffer(initial);records=ctypes.create_string_buffer(b'\xa5'*(320*32));pending=(ctypes.c_uint16*4096)();n=ctypes.c_uint(0);text=ctypes.create_string_buffer(payload+b'\0\0')
   subs=kw.get('substitutions',(b'',b'',b'',b''));subbuffers=[ctypes.create_string_buffer(b+b'\0\0\0') for b in subs];ptrs=(ctypes.c_void_p*4)(*[ctypes.addressof(b) for b in subbuffers])
   early=c.native_parse_model(state,records,pending,ctypes.byref(n),text,ext,ptrs,kw.get('z_arg',0xffffffff),320,4096)
   out=ctypes.create_string_buffer(b'\xa5'*131072);written=ctypes.c_size_t();ret=ptr
   if not early:
    old_count=int.from_bytes(initial[:2],'little');new_count=int.from_bytes(bytes(state)[:2],'little')
    ret=c.native_packet_model(out,131072,ptr,chain,ctypes.byref(records,old_count*32),new_count-old_count,None,0,*struct.unpack_from('<2h',initial,4),templates,ctypes.byref(written))
    ctypes.memmove(ctypes.addressof(state),initial[:4],4)
   assert early==int(r['early']),(ed,name,'exit mismatch')
   expected=bytes(state)[:0x90];actual=bytes.fromhex(r['final_state'])
   if actual!=expected:raise AssertionError((ed,name,'state',[(hex(i),hex(a),hex(b)) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b]))
   assert bytes(records)[:320*32]==bytes.fromhex(r['records']),(ed,name,'record buffer')
   assert n.value==r['pending_count'] and bytes(pending)[:n.value*2]==bytes.fromhex(r['pending']),(ed,name,'upload list')
   assert ret==r['packet_return'],(ed,name,'return',hex(ret),hex(r['packet_return']))
   native_out=bytes.fromhex(r['packet_buffer']);expected_out=bytes(out)[:131072]
   if native_out!=expected_out:raise AssertionError((ed,name,'packet bytes',[(hex(i),hex(a),hex(b)) for i,(a,b) in enumerate(zip(native_out,expected_out)) if a!=b][:10]))
   report.append({'edition':ed,'case':name,'early':bool(early),'initial_counts':list(struct.unpack_from('<2H',initial)),'final_counts':list(struct.unpack_from('<2H',actual)),'pending_uploads':n.value,'packet_bytes':written.value,'packet_return':hex(ret),'packet_sha256':hashlib.sha256(native_out).hexdigest(),'state_sha256':hashlib.sha256(actual).hexdigest()})
  print(ed,len(expanded),'complete native parse + immediate packet calls match composed models',flush=True)
(OUT/'immediate-execution.json').write_text(json.dumps({'status':'three_complete_native_renderer_calls_match_composed_models_with_queue_rollback_and_packets','scope':__doc__,'case_count':len(report),'cases':report},indent=2)+'\n')
