"""Native atlas restore, conditional batch reset and font-parameter reset wrappers.
No EE instruction adapter is required by these exercised functions.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from inventory import native
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent;inv=json.loads((OUT/'inventory.json').read_text());resources=json.loads((OUT/'resource-inventory.json').read_text());results=[];rng=random.Random(0x4652414d)
with tempfile.TemporaryDirectory(prefix='srwz-font-lifecycle-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'upload_model.c'),str(OUT/'parse_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_atlas_restore_model.argtypes=[ctypes.c_void_p];c.native_frame_clear_model.argtypes=[ctypes.c_void_p]*3+[ctypes.c_int64,ctypes.c_uint32];c.native_font_state_reset_model.argtypes=[ctypes.c_void_p]
 for ed in ('original','best','sp'):
  elf,_=native(ed);r=next(x for x in inv['editions'] if x['edition']==ed);rr=next(x for x in resources['editions'] if x['edition']==ed);F=int(r['state_va'],16);frame=int(rr['functions']['frame_clear']['entry'],16)
  gp_im=elf.words(frame+0x34,1)[0]&65535;gp_off=gp_im if gp_im<32768 else gp_im-65536
  hi,lo=elf.words(frame+0x28,1)[0],elf.words(frame+0x30,1)[0];im=lo&65535;index_base=((hi&65535)<<16)+(im if im<32768 else im-65536)
  u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20)
  for _,o,v,_,n,*_ in elf.loads:u.mem_write(v,elf.b[o:o+n])
  u.hook_add(UC_HOOK_CODE,lambda uc,pc,size,data:uc.emu_stop(),begin=0x8000,end=0x8000)
  count=0
  for k in range(12):
   initial=bytes(rng.randrange(256) for _ in range(0x90));pending_value=rng.randrange(1,65536);initial_pointer=0x1b00f00
   for op,arg in [('atlas_reset_to_reserved',0),('font_reset_wrapper',0)]+[('frame_clear',v) for v in (0,1,2,127,128,255,256,257,-1,-256,0x100000000)]:
    entry=int(rr['functions'][op]['entry'],16);u.mem_write(F,initial);u.mem_write(F-0x10,struct.pack('<I',initial_pointer));u.mem_write(0x1700000+gp_off,struct.pack('<H',pending_value))
    u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_GP,0x1700000);u.reg_write(UC_MIPS_REG_RA,0x8000);u.reg_write(UC_MIPS_REG_4,arg&0xffffffffffffffff);u.emu_start(entry,0,count=10000)
    assert u.reg_read(UC_MIPS_REG_PC)==0x8000,(ed,op,arg)
    state=ctypes.create_string_buffer(initial);n=ctypes.c_uint16(pending_value);p=ctypes.c_uint32(initial_pointer)
    if op=='frame_clear':c.native_frame_clear_model(state,ctypes.byref(n),ctypes.byref(p),arg,index_base)
    elif op=='font_reset_wrapper':c.native_font_state_reset_model(state)
    else:c.native_atlas_restore_model(state)
    actual=bytes(u.mem_read(F,0x90));assert actual==bytes(state)[:0x90],(ed,op,arg,'state')
    assert n.value==int.from_bytes(u.mem_read(0x1700000+gp_off,2),'little'),(ed,op,arg,'pending')
    assert p.value==int.from_bytes(u.mem_read(F-0x10,4),'little'),(ed,op,arg,'pointer')
    results.append({'edition':ed,'operation':op,'argument':arg,'state_fixture':k,'entry':hex(entry),'native_index_base':hex(index_base),'native_GP_count_offset':gp_off,'state_sha256':hashlib.sha256(actual).hexdigest(),'pending_count':n.value,'upload_pointer':hex(p.value)})
    count+=1
  print(ed,count,'native lifecycle state/counter/pointer comparisons passed',flush=True)
(OUT/'lifecycle-execution.json').write_text(json.dumps({'status':'three_native_batch_and_atlas_reset_paths_match_C_models','scope':__doc__,'case_count':len(results),'cases':results},indent=2)+'\n')
