"""Differential native queued numeric/symbol records and record-group reset.
Executes unpatched native instructions except documented EE LQ/SQ and MULT-rd
adapters. No GIF submission, signed wrapper, LRPS2 or visual claims here.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from inventory import native
from execute import GPRS
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent
inv=json.loads((OUT/'inventory.json').read_text()); ni=json.loads((OUT/'numeric-inventory.json').read_text())
rng=random.Random(0x4e554d);results=[]
def s32(v):return ctypes.c_int32(v).value
def sx(v):return v&0xffffffffffffffff
with tempfile.TemporaryDirectory(prefix='srwz-native-numeric-') as td:
 lib=Path(td)/'model.dylib'
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'numeric_model.c'),str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib))
 c.native_number_records_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int32,ctypes.c_int16,ctypes.c_int16,ctypes.c_int,ctypes.c_uint32,ctypes.c_uint]
 c.native_symbol_records_model.argtypes=[ctypes.c_void_p]*4+[ctypes.c_uint,ctypes.c_int16,ctypes.c_int16,ctypes.c_int32,ctypes.c_uint32,ctypes.c_uint]
 c.native_record_group_model.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint]
 for ed in ('original','best','sp'):
  e,_=native(ed);row=next(x for x in inv['editions'] if x['edition']==ed);fns=next(x for x in ni['editions'] if x['edition']==ed)['functions'];F=int(row['state_va'],16)
  u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20)
  for _,off,va,_,n,*_ in e.loads:u.mem_write(va,e.b[off:off+n])
  adapters={};upper=[bytes(8) for _ in range(32)]
  for fn in fns.values():
   for pc in range(int(fn['entry'],16),int(fn['end'],16),4):
    w=e.words(pc,1)[0]
    if w>>26 in (0x1e,0x1f) or (w>>26==0 and w&63 in (0x18,0x19) and (w>>11)&31):adapters[pc]=w;u.mem_write(pc,b'\0'*4)
  def hook(uc,pc,size,data):
   if pc==0x8000:uc.emu_stop();return
   w=adapters.get(pc)
   if w is None:return
   op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31
   if op in (0x1e,0x1f):
    addr=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
    if op==0x1e:
     v=bytes(uc.mem_read(addr,16));uc.reg_write(GPRS[rt],int.from_bytes(v[:8],'little'));upper[rt]=v[8:]
    else:uc.mem_write(addr,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
   else:
    a=uc.reg_read(GPRS[rs])&0xffffffff;b=uc.reg_read(GPRS[rt])&0xffffffff
    product=(s32(a)*s32(b) if w&63==0x18 else a*b)&0xffffffffffffffff
    uc.reg_write(GPRS[(w>>11)&31],sx(s32(product)));uc.reg_write(UC_MIPS_REG_LO,sx(s32(product)));uc.reg_write(UC_MIPS_REG_HI,sx(s32(product>>32)))
  u.hook_add(UC_HOOK_CODE,hook)
  sym=int(fns['symbol_list']['entry'],16)
  hi,lo=e.words(sym+0x78,2);pointer=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value
  seedva=int.from_bytes(e.read(pointer,4),'little');seed=e.read(seedva,84)
  cases=[]
  for value in (0,1,2,9,10,99,100,999,1000000000,2147483647,-1,-2147483648):
   for right in (0,1):cases.append(('unsigned_number',value,right,0))
  for count in (253,254,255):cases.append(('unsigned_number',123456,1,count))
  for k in range(65):cases.append(('unsigned_number',rng.randrange(2147483648),k&1,rng.randrange(240)))
  for k in range(42):cases.append(('symbol_list',seed[k*2:k*2+2]+seed[((k+20)%42)*2:((k+20)%42)*2+2],0,0))
  cases.extend([('symbol_list',b'',0,0),('symbol_list',seed[:8],0,254)])
  for group in range(5):cases.append(('initialize_record_group',group,0,0))
  for i,(name,value,right,count) in enumerate(cases):
   initial=bytearray(rng.randbytes(0x90));struct.pack_into('<HH',initial,0,7,count);struct.pack_into('<II',initial,0x58,0x1a00000,0)
   struct.pack_into('<I',initial,0x60,0x1a00000)
   width,height,advance=(14,13,12) if i%2 else (257,271,-7)
   struct.pack_into('<3h',initial,0x2c,width,height,advance)
   u.mem_write(F,bytes(initial));records=rng.randbytes(400*32);u.mem_write(0x1a00000,records)
   state=ctypes.create_string_buffer(bytes(initial));rec=ctypes.create_string_buffer(records);x,y=(32760,-32760) if i%3==0 else (180,36);z=0xffffffff if i%2 else 0x12345678
   if name=='unsigned_number':
    args=[value,x,y,right,0,s32(z),0];assert c.native_number_records_model(state,rec,value,x,y,right,z,400)==0
   elif name=='symbol_list':
    payload=value+b'\0\0';u.mem_write(0x1900000,payload);text=ctypes.create_string_buffer(payload);se=ctypes.create_string_buffer(seed)
    args=[0x1900000,x,y,advance,0,s32(z),0];assert c.native_symbol_records_model(state,rec,text,se,42,x,y,advance,z,400)==0
   else:
    args=[value];assert c.native_record_group_model(rec,value,400)==0
   for reg in GPRS[1:]:u.reg_write(reg,0)
   u.reg_write(UC_MIPS_REG_2,0x13572468);u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_RA,0x8000)
   for reg,v in zip(GPRS[4:],args):u.reg_write(reg,sx(v))
   u.emu_start(int(fns[name]['entry'],16),0,count=200000)
   assert u.reg_read(UC_MIPS_REG_PC)==0x8000,(ed,name,i,'did not return')
   actual=bytes(u.mem_read(F,0x90));expected=bytes(state)[:0x90]
   assert actual==expected,(ed,name,i,'state',[(j,a,b) for j,(a,b) in enumerate(zip(actual,expected)) if a!=b])
   actual_rec=bytes(u.mem_read(0x1a00000,len(records)));expected_rec=bytes(rec)[:len(records)]
   assert actual_rec==expected_rec,(ed,name,i,'record',[(j,a,b) for j,(a,b) in enumerate(zip(actual_rec,expected_rec)) if a!=b][:20])
   ret=u.reg_read(UC_MIPS_REG_2)&0xffffffff
   if name=='symbol_list':assert ret==(0 if ed=='sp' else 0x13572468),(ed,name,i,'return',hex(ret))
   results.append({'edition':ed,'operation':name,'case':i,'input':value.hex() if isinstance(value,bytes) else value,'right':right,'initial_count':count,'number_metrics':[width,height,advance],'input_xy':[x,y],'return':hex(ret),'secondary_count':int.from_bytes(actual[2:4],'little'),'full_state_sha256':hashlib.sha256(actual).hexdigest(),'full_record_buffer_sha256':hashlib.sha256(actual_rec).hexdigest()})
  print(ed,len(cases),'native numeric/symbol/group state and full-record comparisons passed',flush=True)
(OUT/'numeric-execution.json').write_text(json.dumps({'scope':__doc__,'status':'queued_numeric_symbol_and_group_models_match_three_native_editions','case_count':len(results),'cases':results},indent=2)+'\n')
