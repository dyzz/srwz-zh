"""Native whole-parser differential proof for guarded production digit policy.
Includes classification flags/range boundaries and explicit/conditional dimensions.
No LRPS2 or production-candidate acceptance is claimed.
"""
from pathlib import Path
import sys,json,struct,itertools,hashlib
R=Path.cwd();sys.path.insert(0,str(R/'docs/issue-assets/native-text-rendering-20261021'))
from numeric_harness import machine,call
sys.path.insert(0,str(R/'tools'))
from srwz.library_optical_metrics import regions,layout
from numeric_harness import GPRS
from unicorn import UC_HOOK_CODE
OUT=Path(__file__).parent
codes=[0x8140,0x824e,*range(0x824f,0x8259),0x8259,0x8260,0x8279,0x827a,0x8281,0x829a,0x829b,0x829f,0x82f1,0x82f2,0x8340,0x8491,0x8492,0x889f]
payload=b''.join(c.to_bytes(2,'big') for c in codes)+b'\0\0'
rows=[]
for ed in ('original','best','sp'):
 u,e,row,fn,F,_,_,_=machine(ed,True);d=int(row['core_va_delta'],16);patches=regions(ed)
 movn=layout(ed)['base']+60
 def adapt_movn(uc,pc,size,data):
  if uc.reg_read(GPRS[3])!=0:uc.reg_write(GPRS[2],uc.reg_read(GPRS[1]))
 u.hook_add(UC_HOOK_CODE,adapt_movn,begin=movn,end=movn)
 gpimm=e.words(0x13aa84+d,1)[0]&65535;gpcount=gpimm-65536 if gpimm>=32768 else gpimm
 def run(initial,patched):
  for index,(va,before,after) in enumerate(patches):u.mem_write(va,after if patched or index<len(patches)-2 else before)
  u.mem_write(movn,bytes(4))
  u.ctl_flush_tb()
  u.mem_write(F,initial);u.mem_write(0x1a00000,b'\xa5'*10240);u.mem_write(0x1b00000,b'\xa5'*8192);u.mem_write(F-0x10,struct.pack('<I',0x1b00000));u.mem_write(0x1800000+gpcount,b'\0\0');u.mem_write(0x1900000,(bytes((0x33,h)) if manual else b'')+payload)
  call(u,0x13a290+d,[0x1900000,0,0xffffffff,0])
  return bytes(u.mem_read(F,0x90)),bytes(u.mem_read(0x1a00000,10240)),bytes(u.mem_read(0x1b00000,8192)),bytes(u.mem_read(0x1800000+gpcount,2))
 for h,mode,flags,fast,shape,manual in itertools.product((0,1,8,9,10,11,12,13,16,255),(0,1),tuple(itertools.product((0,1),repeat=5)),(0,1),((14,12),(16,16)),(False,True)):
  initial=bytearray(0x90);struct.pack_into('<2h',initial,8,0,48);struct.pack_into('<4h',initial,0x14,shape[0],h,shape[1],12);struct.pack_into('<8h',initial,0x38,21,h,21,14,shape[0],h,shape[1],14);struct.pack_into('<h',initial,0x48,mode);initial[0x4b:0x50]=bytes(flags);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x88,fast)
  before=run(bytes(initial),False);after=run(bytes(initial),True)
  assert before[0]==after[0],(ed,h,mode,'persistent state changed');assert before[2:]==after[2:],(ed,'glyph uploads changed')
  expected=bytearray(before[1]);changes=[]
  for i,code in enumerate(codes):
   w,rh=struct.unpack_from('<2h',expected,i*32+12)
   # Digits classified as B only by the broad flag; explicit mode uses own advance.
   adv=shape[1] if manual or not mode or flags[4] else 21
   if not manual and 0x824f<=code<0x8259 and w==14 and adv==12 and 9<=rh<=12:
    struct.pack_into('<h',expected,i*32+14,rh-1);changes.append(i)
  assert bytes(expected)==after[1],(ed,h,mode,flags,fast,shape,'records differ')
  rows.append(dict(edition=ed,height=h,explicit_height_control=manual,classified=mode,flags=flags,dynamic_digits=fast,explicit_width_advance=shape,changed_record_indices=changes,persistent_state_unchanged=True,uploads_unchanged=True))
 print(ed,'automatic compact digits differential cases passed',flush=True)
(OUT/'automatic-digit-production-proof.json').write_text(json.dumps(dict(scope=__doc__,status='current_production_patch_native_differential_passed',case_count=len(rows),source_sha256=hashlib.sha256((R/'tools/srwz/compact_digit_metrics.py').read_bytes()).hexdigest(),codes=[hex(x) for x in codes],cases=rows),indent=2)+'\n')
