"""Native CRT strcpy/strlen byte contracts including packed aligned loops.
Checks source preservation, return pointers/lengths, exact destination and
surrounding bytes. Valid nonoverlapping terminated inputs only; no GS/LRPS2.
"""
from pathlib import Path
import json,random,hashlib
from numeric_harness import machine,call
from string_adapter import install
OUT=Path(__file__).parent;inv=json.loads((OUT/'string-inventory.json').read_text());rng=random.Random(0x53545249);results=[]
for ed in ('original','best','sp'):
 u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);f=r['functions'];seen=install(u,e,[(int(x['entry'],16),int(x['end'],16)) for x in f.values()]);ncase=0
 for sa in range(16):
  for da in sorted({sa,0,1,8,15}):
   for n in (0,1,7,8,9,15,16,17,31,32,33,63):
    src=0x1900040+sa;dst=0x1910040+da;payload=bytes(rng.randrange(1,256) for _ in range(n))+b'\0';source=bytearray(rng.randbytes(192));source[64+sa:64+sa+len(payload)]=payload;destination=rng.randbytes(192);expected=bytearray(destination);expected[64+da:64+da+len(payload)]=payload
    u.mem_write(0x1900000,bytes(source));u.mem_write(0x1910000,destination);length=call(u,int(f['strlen']['entry'],16),[src]);assert length==n,(ed,sa,da,n,'length',length)
    returned=call(u,int(f['strcpy']['entry'],16),[dst,src]);assert returned==dst,(ed,sa,da,n,'pointer');assert bytes(u.mem_read(0x1900000,192))==bytes(source),(ed,sa,da,n,'source changed')
    actual=bytes(u.mem_read(0x1910000,192));assert actual==bytes(expected),(ed,sa,da,n,'destination or guard bytes')
    results.append({'edition':ed,'source_alignment':sa,'destination_alignment':da,'length':n,'destination_sha256':hashlib.sha256(actual).hexdigest()});ncase+=1
 print(ed,ncase,'paired native strlen/strcpy cases passed',flush=True)
(OUT/'string-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_string_fast_and_byte_paths_match_exact_copy_and_length_contracts','case_count':len(results),'native_call_count':len(results)*2,'cases':results},indent=2)+'\n')
