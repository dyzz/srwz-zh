"""Native whole-parser differential proof for analysis-only digit policy.
Includes classification flags/range boundaries and explicit/conditional dimensions.
No LRPS2 or production-candidate acceptance is claimed.
"""
from pathlib import Path
import sys,json,struct,itertools,hashlib
R=Path.cwd();sys.path.insert(0,str(R/'docs/issue-assets/native-text-rendering-20261021'))
from numeric_harness import machine,call
from automatic_digit_candidate import regions
OUT=Path(__file__).parent
codes=[0x8140,0x824e,*range(0x824f,0x8259),0x8259,0x8260,0x8279,0x827a,0x8281,0x829a,0x829b,0x829f,0x82f1,0x82f2,0x8340,0x8491,0x8492,0x889f]
payload=b''.join(c.to_bytes(2,'big') for c in codes)+b'\0\0'
rows=[]
for ed in ('original','best','sp'):
 u,e,row,fn,F,_,_,_=machine(ed,True);d=int(row['core_va_delta'],16);patches=regions(e,d)
 gpimm=e.words(0x13aa84+d,1)[0]&65535;gpcount=gpimm-65536 if gpimm>=32768 else gpimm
 def run(initial,patched):
  for va,before,after in patches:u.mem_write(va,after if patched else before)
  u.ctl_flush_tb()
  u.mem_write(F,initial);u.mem_write(0x1a00000,b'\xa5'*10240);u.mem_write(0x1b00000,b'\xa5'*8192);u.mem_write(F-0x10,struct.pack('<I',0x1b00000));u.mem_write(0x1800000+gpcount,b'\0\0');u.mem_write(0x1900000,payload)
  call(u,0x13a290+d,[0x1900000,0,0xffffffff,0])
  return bytes(u.mem_read(F,0x90)),bytes(u.mem_read(0x1a00000,10240)),bytes(u.mem_read(0x1b00000,8192)),bytes(u.mem_read(0x1800000+gpcount,2))
 for h,mode,flags,fast,shape in itertools.product((9,10,11,12),(0,1),((0,)*5,(1,)*5,(1,0,1,0,1)),(0,1),((14,12),(16,16))):
  initial=bytearray(0x90);struct.pack_into('<2h',initial,8,0,48);struct.pack_into('<4h',initial,0x14,shape[0],h,shape[1],12);struct.pack_into('<8h',initial,0x38,21,h,21,14,shape[0],h,shape[1],14);struct.pack_into('<h',initial,0x48,mode);initial[0x4b:0x50]=bytes(flags);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x88,fast)
  before=run(bytes(initial),False);after=run(bytes(initial),True)
  assert before[0]==after[0],(ed,h,mode,'persistent state changed');assert before[2:]==after[2:],(ed,'glyph uploads changed')
  expected=bytearray(before[1]);changes=[]
  for i,code in enumerate(codes):
   w,rh=struct.unpack_from('<2h',expected,i*32+12)
   # Digits classified as B only by the broad flag; explicit mode uses own advance.
   adv=shape[1] if not mode or flags[4] else 21
   if 0x824f<=code<0x8259 and w==14 and adv==12 and rh>=2:
    struct.pack_into('<h',expected,i*32+14,rh-1);changes.append(i)
  assert bytes(expected)==after[1],(ed,h,mode,flags,fast,shape,'records differ')
  rows.append(dict(edition=ed,height=h,classified=mode,flags=flags,dynamic_digits=fast,explicit_width_advance=shape,changed_record_indices=changes,persistent_state_unchanged=True,uploads_unchanged=True))
 print(ed,'automatic compact digits differential cases passed',flush=True)
(OUT/'automatic-digit-candidate-proof.json').write_text(json.dumps(dict(scope=__doc__,status='analysis_candidate_only',case_count=len(rows),source_sha256=hashlib.sha256((OUT/'automatic_digit_candidate.py').read_bytes()).hexdigest(),codes=[hex(x) for x in codes],cases=rows),indent=2)+'\n')
