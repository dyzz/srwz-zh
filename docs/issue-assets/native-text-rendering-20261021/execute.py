"""Differential checks against all three native integer font routines.

Unicorn executes original integer instructions. EE LQ/SQ save/restore are adapted only
with separate high-lane storage; core-only checks do not use high lanes.
LQ/SQ words are replaced by NOP in emulation memory and handled by a hook with complete 128-bit load/store values,
including in branch delay slots. This is not LRPS2 or pixel evidence.
"""
from pathlib import Path
import json,struct,sys,ctypes,tempfile,subprocess
sys.path.insert(0,str(Path(__file__).parent))
from inventory import native
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent
INV=json.loads((OUT/'inventory.json').read_text())
GPRS=[getattr(sys.modules['unicorn.mips_const'],f'UC_MIPS_REG_{i}') for i in range(32)]
def run_case(ed,payload,measure=False,flags=(1,1,1,1,1),a=(21,12,21,14),b=(14,12,12,14),atlas_y=0,details=False,state_patch=None,substitutions=None,fast_digits=False,z_arg=0xffffffff,packet_addr=0,packet_chain=0):
 elf,lock=native(ed);row=next(r for r in INV['editions'] if r['edition']==ed)
 d=int(row['core_va_delta'],16);F=int(row['state_va'],16);u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN)
 u.mem_map(0,32<<20);u.mem_map(0x70000000,0x1000)
 for _,off,va,_,n,*_ in elf.loads:u.mem_write(va,elf.b[off:off+n])
 adapted={}
 spans=[(0x139B00,0x139D50),(0x13A290,0x13AC90)]
 if packet_addr:spans.append((0x13ACA0,0x13BD60))
 for lo,hi in spans:
  for pc in range(lo+d,hi+d,4):
   w=elf.words(pc,1)[0]
   if w>>26 in (0x1e,0x1f):adapted[pc]=w;u.mem_write(pc,b'\0'*4)
 SP=0x1ff0000;TEXT=0x1900000;STOP=0x8000
 u.reg_write(UC_MIPS_REG_SP,SP);u.reg_write(UC_MIPS_REG_GP,0x1800000)
 adapters=[];trace=[];events=[];upper=[bytes(8) for _ in range(32)]
 def hook(uc,pc,size,data):
  if pc==STOP:uc.emu_stop();return
  w=adapted.get(pc,struct.unpack('<I',bytes(uc.mem_read(pc,4)))[0]);op=w>>26
  if op in (0x1e,0x1f):
   rs=(w>>21)&31;rt=(w>>16)&31;im=w&65535;im=im if im<32768 else im-65536
   addr=(uc.reg_read(GPRS[rs])+im)&0xffffffff
   if op==0x1e:
    if rt:
     value=bytes(uc.mem_read(addr,16));uc.reg_write(GPRS[rt],int.from_bytes(value[:8],'little'));upper[rt]=value[8:]
   else:uc.mem_write(addr,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
   adapters.append(hex(pc))
  if pc==0x13AA34+d:events.append('atlas_exhaustion_exit')
  if pc==0x13AB20+d:
   trace.append({'code':hex(int.from_bytes(uc.mem_read(0x70000060,2),'little')),'glyph':int.from_bytes(uc.mem_read(0x70000062,2),'little'),'render':list(struct.unpack('<2h',bytes(uc.mem_read(0x7000003c,4)))),'advance':list(struct.unpack('<2h',bytes(uc.mem_read(0x70000038,4)))),'position':list(struct.unpack('<2h',bytes(uc.mem_read(0x70000030,4))))})
 h=u.hook_add(UC_HOOK_CODE,hook)
 def call(pc):
  u.reg_write(UC_MIPS_REG_RA,STOP)
  try:u.emu_start(pc,0,count=2000000 if packet_addr else 100000)
  except Exception as e:raise RuntimeError((ed,measure,hex(u.reg_read(UC_MIPS_REG_PC)),str(e),adapters)) from e
  assert u.reg_read(UC_MIPS_REG_PC)==STOP,(ed,hex(u.reg_read(UC_MIPS_REG_PC)))
 call(int(row['initializer_entry'],16))
 # Explicit metrics plus different A/B metrics expose mismatched classification.
 u.mem_write(F+0x14,struct.pack('<4h',21,12,21,14))
 u.mem_write(F+0x38,struct.pack('<8h',*(a+b)));u.mem_write(F+0x48,struct.pack('<h',1));u.mem_write(F+0x4b,bytes(flags))
 u.mem_write(F-0x10,struct.pack('<I',0x1b00000));u.mem_write(F+0x58,struct.pack('<I',0x1a00000));u.mem_write(F+0x88,struct.pack('<I',0 if fast_digits else 1))
 u.mem_write(F+8,struct.pack('<2h',0,atlas_y))
 if packet_addr:
  u.mem_write(packet_addr&0x0fffffff,b'\xa5'*131072);u.mem_write(F+0x60,struct.pack('<I',0x1d00000))
 if details:u.mem_write(0x1a00000,b'\xa5'*(320*32))
 if state_patch:
  for off,values in state_patch.items():u.mem_write(F+off,values)
 if substitutions is not None:
  for i,text in enumerate(substitutions):
   handler=int(row['controls'][0x3a-0x2e+i]['target'],16)
   hi=elf.words(handler+0x14,1)[0]&65535;lo=elf.words(handler+0x1c,1)[0]&65535
   va=(hi<<16)+(lo if lo<32768 else lo-65536)
   u.mem_write(va,text+b'\0\0')
 u.mem_write(TEXT,payload+b'\0\0')
 for reg,v in zip(GPRS[4:8],(TEXT,1 if measure else packet_addr,0xffffffffffffffff if z_arg==0xffffffff else z_arg,packet_chain)):u.reg_write(reg,v)
 initial_state=bytes(u.mem_read(F,0x90 if details else 0x50)).hex()
 call((0x139B00 if measure else 0x13A290)+d)
 result={'initial_state':initial_state,'return':u.reg_read(UC_MIPS_REG_2)&0xffffffff,'explicit':list(struct.unpack('<4h',bytes(u.mem_read(F+0x14,8)))),'mode':int.from_bytes(u.mem_read(F+0x48,2),'little'),'cursor':list(struct.unpack('<2h',bytes(u.mem_read(F+0x10,4)))),'glyphs':trace,'ee_save_restore_adapters':adapters}
 if details:
  gp_imm=elf.words(0x13aa84+d,1)[0]&65535
  gp_off=gp_imm if gp_imm<32768 else gp_imm-65536
  n=int.from_bytes(u.mem_read(0x1800000+gp_off,2),'little')
  result.update(final_state=bytes(u.mem_read(F,0x90)).hex(),records=bytes(u.mem_read(0x1a00000,320*32)).hex(),pending_count=n,pending=bytes(u.mem_read(0x1b00000,n*2)).hex(),pending_pointer=int.from_bytes(u.mem_read(F-0x10,4),'little'),early=bool(events))
 if packet_addr:result.update(packet_return=u.reg_read(UC_MIPS_REG_2)&0xffffffff,packet_buffer=bytes(u.mem_read(packet_addr&0x0fffffff,131072)).hex())
 u.hook_del(h);return result
CASES={'plain':bytes.fromhex('889f889f'),'width_space':bytes.fromhex('320e340c889f889f'),'height':bytes.fromhex('330e889f889f'),'vertical_advance':bytes.fromhex('350f889f889f'),'newline':bytes.fromhex('889f0a889f'),'nul_parameter':bytes.fromhex('3100889f'),'classification_overlap':bytes.fromhex('824f82608281829f8340889f'),'disabled_specific_with_blanket':bytes.fromhex('8260'),'closed_height_scope':bytes.fromhex('320e340c330e826632153415330c889f'),'atlas_exhaustion_exit':bytes.fromhex('330e889f')}
def main():
 temp=tempfile.TemporaryDirectory(prefix='srwz-native-text-model-')
 lib=Path(temp.name)/'model.dylib'
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'core_model.c'),'-o',str(lib)],check=True)
 model=ctypes.CDLL(str(lib));model.native_measure_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int];model.native_measure_model.restype=ctypes.c_int32
 model.native_draw_uses_b.argtypes=[ctypes.c_void_p,ctypes.c_uint16];model.native_draw_uses_b.restype=ctypes.c_int
 rows=[]
 for ed in ('original','best','sp'):
  for name,payload in CASES.items():
   flags=(0,0,0,0,1) if name=='disabled_specific_with_blanket' else (1,1,1,1,1)
   m=run_case(ed,payload,True,flags);r=run_case(ed,payload,False,flags,atlas_y=480 if name=='atlas_exhaustion_exit' else 0)
   state=ctypes.create_string_buffer(bytes.fromhex(m['initial_state']));text=ctypes.create_string_buffer(payload+b'\0\0')
   model_width=model.native_measure_model(state,text,1)
   assert model_width==m['return'],(ed,name,'C model width differs')
   assert bytes(state)[0x14:0x1c]==struct.pack('<4h',*m['explicit'])
   assert int.from_bytes(bytes(state)[0x48:0x4a],'little')==m['mode']
   if name in ('plain','classification_overlap','disabled_specific_with_blanket'):
    draw_state=ctypes.create_string_buffer(bytes.fromhex(r['initial_state']))
    for g in r['glyphs']:
     use_b=model.native_draw_uses_b(draw_state,int(g['code'],16))
     assert g['advance'][0]==(12 if use_b else 21),(ed,name,g,use_b)
   expected={'plain':(42,42,2),'width_space':(24,24,2),'height':(63,42,2),'vertical_advance':(63,42,2),'newline':(63,21,2),'nul_parameter':(21,21,1),'classification_overlap':(81,81,6),'disabled_specific_with_blanket':(21,12,1),'closed_height_scope':(66,33,2),'atlas_exhaustion_exit':(42,0,0)}[name]
   assert (m['return'],r['cursor'][0],len(r['glyphs']))==expected,(ed,name,m,r)
   if name=='height':assert r['glyphs'][0]['render']==[21,14]
   if name=='closed_height_scope':assert [g['render'] for g in r['glyphs']]==[[14,14],[21,12]]
   if name=='atlas_exhaustion_exit':assert r['mode']==0
   elif name in ('height','closed_height_scope'):assert r['mode']==1
   rows.append({'edition':ed,'case':name,'bytes':payload.hex(' '),'measure':m,'render':r})
   print(ed,name,'measure',m['return'],'glyphs',len(r['glyphs']),'cursor',r['cursor'])
 (OUT/'execution.json').write_text(json.dumps({'status':'30_native_integer_path_cases_and_C_model_comparisons_passed','scope':__doc__,'cases':rows},indent=2)+'\n')
 
 temp.cleanup()

if __name__=='__main__':main()
