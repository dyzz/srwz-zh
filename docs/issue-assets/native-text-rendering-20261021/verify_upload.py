"""Verify native glyph scatter and its unchanged state/count contract, three editions.
CPU memory operations only. No GS or graphics emulator is invoked.
"""
from pathlib import Path
import json,sys,struct,ctypes,tempfile,subprocess,hashlib,random
from inventory import native
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent;inv=json.loads((OUT/'inventory.json').read_text());results=[]
rng=random.Random(0x46544e)
font=rng.randbytes(4480*288) if hasattr(rng,'randbytes') else bytes(rng.randrange(256) for _ in range(4480*288))
cases=[('empty',[],0,48),('first_slot',[0],0,48),('last_glyph',[4479],24,48),('odd_x_source_shift',[207],1,48),('row_wrap',[207,224,4479],480,48),('page_boundary',[0,207,224],480,216),('last_slot',[4479],480,456),('full_dynamic_after_seed',[rng.randrange(4480) for _ in range(378)],0,48),('full_empty_atlas',[rng.randrange(4480) for _ in range(420)],0,0)]
for k in range(40):cases.append((f'fixed_seed_scatter_{k:02}',[rng.randrange(4480) for _ in range(rng.randrange(1,50))],rng.randrange(16)*24,rng.randrange(10)*24))
with tempfile.TemporaryDirectory(prefix='srwz-upload-model-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'upload_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_scatter_model.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_uint,ctypes.c_int16,ctypes.c_int16];c.native_scatter_model.restype=ctypes.c_int
 for ed in ('original','best','sp'):
  e,lock=native(ed);info=next(x for x in inv['editions'] if x['edition']==ed);d=int(info['core_va_delta'],16);F=int(info['state_va'],16)
  # Independently bind the scatter entry by its two source-load instructions.
  original,_=native('original');pattern=original.words(0x13c5c0,20);matches=[]
  for _,off,va,_,n,*_ in e.loads:
   for k in range(off,off+n-80,4):
    if struct.unpack_from('<I',e.b,k)[0]>>16!=pattern[0]>>16:continue
    words=struct.unpack_from('<20I',e.b,k)
    if all(a>>16==b>>16 for a,b in zip(words,pattern)):matches.append(va+k-off)
  assert len(matches)==1,(ed,matches)
  start=matches[0]
  gp_im=e.words(start+0xd8,1)[0]&65535;gp_off=gp_im if gp_im<32768 else gp_im-65536
  u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20)
  for _,off,va,_,n,*_ in e.loads:u.mem_write(va,e.b[off:off+n])
  u.mem_write(0x1800000,font);u.reg_write(UC_MIPS_REG_GP,0x1700000);u.reg_write(UC_MIPS_REG_RA,0x8000)
  # upload request indices are a static native array, loaded independently.
  hi,lo=e.words(start+4,1)[0],e.words(start+12,1)[0];im=lo&65535;indices_va=((hi&65535)<<16)+(im if im<32768 else im-65536)
  u.mem_write(F+0x78,struct.pack('<I',0x1800000));u.mem_write(F+0x80,struct.pack('<I',0x1a00000))
  def stop(uc,pc,size,data):uc.emu_stop()
  h=u.hook_add(UC_HOOK_CODE,stop,begin=0x8000,end=0x8000)
  for name,indices,x,y in cases:
   atlas=bytes([0xa5])*0x1e000;u.mem_write(0x1a00000,atlas);u.mem_write(indices_va,struct.pack('<'+'H'*len(indices),*indices) or b'\0\0');u.mem_write(F+12,struct.pack('<2h',x,y));u.mem_write(0x1700000+gp_off,struct.pack('<H',len(indices)))
   before=bytes(u.mem_read(F,0x90));u.emu_start(start,0,count=1000000);assert u.reg_read(UC_MIPS_REG_PC)==0x8000,(ed,name)
   actual=bytes(u.mem_read(0x1a00000,len(atlas)));expected=ctypes.create_string_buffer(atlas);cf=ctypes.create_string_buffer(font);ci=(ctypes.c_uint16*max(1,len(indices)))(*indices)
   assert c.native_scatter_model(expected,len(atlas),cf,len(font),ci,len(indices),x,y)==0
   assert actual==bytes(expected)[:len(atlas)],(ed,name,'atlas bytes')
   assert bytes(u.mem_read(F,0x90))==before,(ed,name,'scatter changed global font state')
   assert int.from_bytes(u.mem_read(0x1700000+gp_off,2),'little')==len(indices),(ed,name,'scatter unexpectedly cleared count')
   results.append({'edition':ed,'case':name,'count':len(indices),'scatter_va':hex(start),'native_gp_count_offset':gp_off,'start':[x,y],'atlas_sha256':hashlib.sha256(actual).hexdigest(),'state_unchanged':True,'pending_count_unchanged':True})
  u.hook_del(h)
  print(ed,len(cases),'full atlas scatter buffers match C; state and pending counts unchanged',flush=True)
(OUT/'upload-execution.json').write_text(json.dumps({'status':'three_native_scatter_functions_match_C_full_atlas_buffers','scope':__doc__,'font_fixture_sha256':hashlib.sha256(font).hexdigest(),'case_count':len(results),'cases':results},indent=2)+'\n')
