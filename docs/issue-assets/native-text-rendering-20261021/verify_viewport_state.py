"""Native viewport setup/scroll/availability vs independent C object model.
Real native limited line count and strlen execute; declared EE adapters only.
Includes 254/255 line-count sentinel, NULL text, signed/arithmetic boundaries.
No controller-input or LRPS2/UI reachability claim.
"""
from pathlib import Path
import json,ctypes,struct,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
from string_adapter import install
OUT=Path(__file__).parent;inv=json.loads((OUT/'viewport-inventory.json').read_text());li=json.loads((OUT/'split-inventory.json').read_text());si=json.loads((OUT/'string-inventory.json').read_text());rng=random.Random(0x56505354);results=[]
payloads=[None,b'',b'A',b'A\nB',b'A\n',b'\n',b'A\n\nB',b'A\n'*8+b'A',b'A\n'*9+b'A',b'A\n'*253+b'A',b'A\n'*254+b'A',b'A\n'*300]
with tempfile.TemporaryDirectory(prefix='srwz-viewport-state-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'viewport_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_viewport_setup_model.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_int64,ctypes.c_void_p];c.native_viewport_can_down_model.argtypes=[ctypes.c_void_p]*2;c.native_viewport_down_model.argtypes=[ctypes.c_void_p]*2;c.native_viewport_up_model.argtypes=[ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);f=r['functions'];lf=next(x for x in li['editions'] if x['edition']==ed);st=next(x for x in si['editions'] if x['edition']==ed)['functions'];install(u,e,[(int(x['entry'],16),int(x['end'],16)) for x in f.values()]+[(int(lf['functions']['count_below_limit']['entry'],16),int(lf['functions']['count_below_limit']['end'],16))]+[(int(st['strlen']['entry'],16),int(st['strlen']['end'],16))]);u.mem_write(0x1800000+lf['count_delimiter_GP_offset'],b'\x0a');total=0
  for i in range(20):
   initial=rng.randbytes(0x1c);arrows=rng.randbytes(6);ob=ctypes.create_string_buffer(initial);coords=ctypes.create_string_buffer(arrows);visible=(0,5,9,-1,2147483647)[i%5]+((1<<32) if i>=10 else 0);text=0x1900000 if i%2 else 0;descriptor=0x1910000 if i%3 else 0
   c.native_viewport_setup_model(ob,text,descriptor,visible,coords);u.mem_write(0x1920000,initial);u.mem_write(0x1930000,arrows);call(u,int(f['setup']['entry'],16),[0x1920000,text,descriptor,visible,0x1930000]);actual=bytes(u.mem_read(0x1920000,0x1c));assert actual==bytes(ob)[:0x1c],(ed,i,'setup');results.append({'edition':ed,'operation':'setup','fixture':i,'visible_arg':visible,'object_sha256':hashlib.sha256(actual).hexdigest()});total+=1
  for pi,payload in enumerate(payloads):
   text=ctypes.create_string_buffer(payload+b'\0') if payload is not None else None;pointer=0x1900000 if payload is not None else 0
   if pointer:u.mem_write(pointer,payload+b'\0')
   for top in (-2147483648,-2,0,1,5,9,245,254,2147483647):
    for visible in (0,5,9,-1):
     initial=bytearray(rng.randbytes(0x1c));struct.pack_into('<Iii',initial,4,pointer,top,visible)
     for operation in ('can_scroll_down','scroll_down','scroll_up'):
      ob=ctypes.create_string_buffer(bytes(initial));u.mem_write(0x1920000,bytes(initial))
      if operation=='can_scroll_down':expected=c.native_viewport_can_down_model(ob,text)
      elif operation=='scroll_down':expected=c.native_viewport_down_model(ob,text)
      else:c.native_viewport_up_model(ob);expected=None
      returned=call(u,int(f[operation]['entry'],16),[0x1920000]);actual=bytes(u.mem_read(0x1920000,0x1c));assert actual==bytes(ob)[:0x1c],(ed,pi,top,visible,operation,'state')
      if expected is not None:assert returned==expected,(ed,pi,top,visible,operation,'return',returned,expected)
      results.append({'edition':ed,'operation':operation,'payload_case':pi,'top':top,'visible':visible,'return_checked':expected,'final_top':struct.unpack_from('<i',actual,8)[0]});total+=1
  print(ed,total,'native viewport state/scroll/count comparisons passed',flush=True)
(OUT/'viewport-state-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_viewport_state_scroll_and_availability_methods_match_C_model','case_count':len(results),'payloads':[x.hex() if x is not None else None for x in payloads],'cases':results},indent=2)+'\n')
