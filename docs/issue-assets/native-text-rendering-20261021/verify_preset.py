"""Native upper font-preset setters vs complete C state update, all three editions.
Native rows through observed static indices and low-byte aliases; no inferred table bound.
No instruction adapters required; no GS or LRPS2 claim.
"""
from pathlib import Path
import json,ctypes,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
OUT=Path(__file__).parent;inv=json.loads((OUT/'preset-inventory.json').read_text());rng=random.Random(0x50524553);results=[]
with tempfile.TemporaryDirectory(prefix='srwz-font-preset-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'preset_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_font_preset_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int64,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);table=ctypes.create_string_buffer(bytes.fromhex(r['table_bytes']));gpaddr=0x1800000+r['GP_offset'];entry=int(r['entry'],16)
  for fixture in range(3):
   initial=rng.randbytes(0x90)
   for alias in (0,256,1<<32):
    for index in range(r['row_count']):
     arg=index+alias;u.mem_write(F,initial);u.mem_write(gpaddr,b'\xa5');state=ctypes.create_string_buffer(initial);selected=ctypes.c_uint8(0xa5)
     c.native_font_preset_model(state,table,arg,ctypes.byref(selected));call(u,entry,[arg]);actual=bytes(u.mem_read(F,0x90));assert actual==bytes(state)[:0x90],(ed,fixture,arg,'state');assert bytes(u.mem_read(gpaddr,1))==bytes([selected.value]),(ed,fixture,arg,'selected byte')
     assert actual[0x10:0x1c]==initial[0x10:0x1c],(ed,fixture,arg,'explicit geometry or pen changed')
     results.append({'edition':ed,'fixture':fixture,'argument':arg,'row':index,'explicit_geometry_retained':True,'state_sha256':hashlib.sha256(actual).hexdigest(),'selected_byte':selected.value})
  print(ed,9*r['row_count'],'native upper font-preset state/selector comparisons passed',flush=True)
(OUT/'preset-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_upper_preset_setters_match_C_state_model','case_count':len(results),'cases':results},indent=2)+'\n')
