"""Native atoi and underlying CRT arithmetic against independent value model.
EE adapters follow pinned LRPS2 source; no replacement of native functions.
Only return-value contract is checked: errno/endptr and non-ASCII not covered.
"""
from pathlib import Path
import json,ctypes,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
from crt_adapter import install
OUT=Path(__file__).parent;inv=json.loads((OUT/'cache-inventory.json').read_text());rng=random.Random(0x44454349);results=[]
cases=['',' ','\t\n\r\v\f +17tail','+','-','--1','+-1','0x10','0123','1e3','nondigit','-0','+0']
cases += [str(x) for x in [-9223372036854775809,-9223372036854775808,-9223372036854775807,-4294967296,-4294967295,-2147483649,-2147483648,-2147483647,-1,0,1,2147483647,2147483648,4294967295,4294967296,9223372036854775806,9223372036854775807,9223372036854775808]]
cases += ['9'*80,'-'+'9'*80]
cases += [rng.choice(['',' ','\t',' +',' -'])+str(rng.randrange(1<<63))+rng.choice(['','tail','e3',' 7']) for _ in range(80)]
with tempfile.TemporaryDirectory(prefix='srwz-decimal-value-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'decimal_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_decimal_value_model.argtypes=[ctypes.c_void_p];c.native_decimal_value_model.restype=ctypes.c_int32
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);seen=install(u,e);r=next(x for x in inv['editions'] if x['edition']==ed);entry=int(r['atoi'],16)
  for i,text in enumerate(cases):
   payload=text.encode()+b'\0';u.mem_write(0x1900000,payload);buffer=ctypes.create_string_buffer(payload);expected=c.native_decimal_value_model(buffer);returned=ctypes.c_int32(call(u,entry,[0x1900000])).value
   assert returned==expected,(ed,i,text,returned,expected)
   results.append({'edition':ed,'case':i,'input':text,'returned_int32':returned})
  print(ed,len(cases),'native decimal return values match independent C model',flush=True)
(OUT/'decimal-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_decimal_return_paths_match_independent_C_value_model','case_count':len(results),'cases':results},indent=2)+'\n')
