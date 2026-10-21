"""Native name-entry writer vs C trim/copy/state model, three editions.
Executes real strcpy (unaligned fixed destinations select byte-copy path).
Only EE LQ/SQ ABI adaptation. No UI interaction, GS or LRPS2 proof.
Field widths sampled as 8/8/5 two-byte cells; malformed larger domains unproven.
"""
from pathlib import Path
import json,ctypes,struct,tempfile,subprocess,random,hashlib
from numeric_harness import machine,call
from execute import GPRS
from unicorn import UC_HOOK_CODE
OUT=Path(__file__).parent;inv=json.loads((OUT/'name-writer-inventory.json').read_text());rng=random.Random(0x4e414d45);results=[]
space=bytes.fromhex('8140');kanji=bytes.fromhex('889f');kana=bytes.fromhex('8389');digit=bytes.fromhex('824f')
cases=[([b'',b'',b''],[8,8,5]),([space*8,space*8,space*5],[8,8,5]),([kana+space*7,kanji+space*7,digit+space*4],[8,8,5]),([kana+space+digit+space*5,kanji*8,kana*5],[8,8,5]),([kana*8,kanji*8,digit*5],[0,-1,0]),([kana*8,kanji*8,digit*5],[3,4,2])]
for _ in range(42):
 fields=[];counts=[]
 for cap in (8,8,5):
  n=rng.randrange(cap+1);fields.append(b''.join(rng.choice((space,kanji,kana,digit)) for _ in range(n)));counts.append(rng.choice((cap,n,0,-1)))
 cases.append((fields,counts))
with tempfile.TemporaryDirectory(prefix='srwz-name-writer-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'name_writer_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_name_writer_model.argtypes=[ctypes.c_void_p]*5+[ctypes.c_uint]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inv['editions'] if x['edition']==ed);entry=int(r['entry'],16);globalbase=int(r['substitution_buffers'][0],16)-1;adapted={};upper=[bytes(8) for _ in range(32)]
  for pc in range(entry,int(r['end'],16),4):
   w=e.words(pc,1)[0]
   if w>>26 in (0x1e,0x1f):adapted[pc]=w;u.mem_write(pc,b'\0'*4)
  def hook(uc,pc,size,data):
   w=adapted.get(pc)
   if w is None:return
   rs=(w>>21)&31;rt=(w>>16)&31;a=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
   if w>>26==0x1e:
    b=bytes(uc.mem_read(a,16))
    if rt:uc.reg_write(GPRS[rt],int.from_bytes(b[:8],'little'));upper[rt]=b[8:]
   else:uc.mem_write(a,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
  u.hook_add(UC_HOOK_CODE,hook)
  for i,(fields,counts) in enumerate(cases):
   obj=bytearray(rng.randbytes(0x70));struct.pack_into('<3I',obj,0x50,0x1910000,0x1920000,0x1930000);initial_global=rng.randbytes(96);buffers=[]
   for j,(text,count) in enumerate(zip(fields,counts)):
    b=bytearray(rng.randbytes(0x80));b[8:8+len(text)+2]=text+b'\0\0';b[0x42]=count&255;buffers.append(ctypes.create_string_buffer(bytes(b)));u.mem_write(0x1910000+j*0x10000,bytes(b))
   object_buffer=ctypes.create_string_buffer(bytes(obj));globals_buffer=ctypes.create_string_buffer(initial_global);u.mem_write(0x1900000,bytes(obj));u.mem_write(globalbase,initial_global);assert c.native_name_writer_model(object_buffer,*buffers,globals_buffer,96)==0
   call(u,entry,[0x1900000]);regions=[('object',0x1900000,0x70,bytes(object_buffer)[:0x70]),('globals',globalbase,96,bytes(globals_buffer)[:96])]+[(f'field{j}',0x1910000+j*0x10000,0x80,bytes(b)[:0x80]) for j,b in enumerate(buffers)];hashes={}
   for name,address,n,expected in regions:
    actual=bytes(u.mem_read(address,n));assert actual==expected,(ed,i,name,[(j,a,b) for j,(a,b) in enumerate(zip(actual,expected)) if a!=b][:12]);hashes[name]=hashlib.sha256(actual).hexdigest()
   results.append({'edition':ed,'case':i,'input_hex':[b.hex() for b in fields],'signed_limits':counts,'output_hex':[bytes(globals_buffer)[off:].split(b'\0')[0].hex() for off in (1,12,29)],'region_sha256':hashes})
  print(ed,len(cases),'native name trim/copy/input mutation/state comparisons passed',flush=True)
(OUT/'name-writer-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_name_writers_match_C_trim_copy_and_state_model','case_count':len(results),'cases':results},indent=2)+'\n')
