"""Native byte row selectors and limited line count vs independent C models.
Real native strlen executes including aligned EE paths; only declared adapters.
Includes control-parameter LF/NUL, empty rows, null pointers and scan budget.
"""
from pathlib import Path
import json,ctypes,tempfile,subprocess,random,struct,hashlib
from numeric_harness import machine,call
from string_adapter import install
OUT=Path(__file__).parent;inv=json.loads((OUT/'split-inventory.json').read_text());si=json.loads((OUT/'string-inventory.json').read_text());rng=random.Random(0x53504c54);results=[]
payloads=[b'',None,b'A',b'A\nB',b'\nA',b'A\n',b'A\n\nB',bytes.fromhex('330a889f0a889f'),bytes.fromhex('3100889f0a889f'),bytes.fromhex('889f330e889f0a8266'),b'A\n'*300]
for _ in range(24):payloads.append(b'\n'.join(bytes(rng.choice([0x41,0x42,0x33,0xe,0x34,0xc,0x88,0x9f])) for _ in range(rng.randrange(0,14))))
with tempfile.TemporaryDirectory(prefix='srwz-byte-split-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'split_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_select_byte_line_model.argtypes=[ctypes.c_void_p,ctypes.c_int32,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint8];c.native_count_below_limit_model.argtypes=[ctypes.c_void_p,ctypes.c_int32,ctypes.c_uint8]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);f=r['functions'];strings=next(x for x in si['editions'] if x['edition']==ed)['functions'];install(u,e,[(int(f[k]['entry'],16),int(f[k]['end'],16)) for k in ('count_below_limit','select_byte_line')]+[(int(strings['strlen']['entry'],16),int(strings['strlen']['end'],16))]);u.mem_write(0x1800000+r['line_delimiter_GP_offset'],b'\x0a');u.mem_write(0x1800000+r['count_delimiter_GP_offset'],b'\x0a');total=0
  for k,payload in enumerate(payloads):
   text=ctypes.create_string_buffer(payload+b'\0') if payload is not None else None;pointer=0x1900000 if payload is not None else 0
   if pointer:u.mem_write(pointer,payload+b'\0')
   for index in (-2147483648,-1,0,1,2,3,253,254,255,256):
    off=ctypes.c_uint32(0x12345678);length=ctypes.c_uint32(0x87654321);expected=c.native_select_byte_line_model(text,index,ctypes.byref(off),ctypes.byref(length),10);u.mem_write(0x1910000,struct.pack('<2I',0x12345678,0x87654321));actual=call(u,int(f['select_byte_line']['entry'],16),[pointer,index,0x1910000,0x1910004]);output=bytes(u.mem_read(0x1910000,8));assert actual==expected and output==struct.pack('<2I',off.value,length.value),(ed,k,index,'select',actual,expected,output.hex(),off.value,length.value)
    results.append({'edition':ed,'payload_case':k,'operation':'select','index':index,'return':actual,'offset':off.value,'length':length.value});total+=1
   for limit in (-1,0,1,2,3,255,301):
    expected=c.native_count_below_limit_model(text,limit,10);actual=call(u,int(f['count_below_limit']['entry'],16),[pointer,limit]);assert actual==expected,(ed,k,limit,'count',actual,expected);results.append({'edition':ed,'payload_case':k,'operation':'count','limit':limit,'return':actual});total+=1
   if pointer:assert bytes(u.mem_read(pointer,len(payload)+1))==payload+b'\0'
  print(ed,total,'native row selector/count comparisons passed',flush=True)
(OUT/'split-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_library_byte_line_selectors_and_counts_match_C','case_count':len(results),'payloads':[p.hex() if p is not None else None for p in payloads],'cases':results},indent=2)+'\n')
