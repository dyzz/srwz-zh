"""Exhaustive native glyph-index checks, plus classification boundary matrices.
Executes original standard-MIPS instruction slices; no LQ/SQ adapter required.
No PS2 graphical emulator is started and no game/source binary is written.
"""
from pathlib import Path
import json,struct,sys,ctypes,tempfile,subprocess,time,hashlib
sys.path.insert(0,str(Path(__file__).parent))
from inventory import native
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_2,UC_MIPS_REG_17,UC_MIPS_REG_PC
OUT=Path(__file__).parent
inv=json.loads((OUT/'inventory.json').read_text())
results=[]
with tempfile.TemporaryDirectory(prefix='srwz-glyph-model-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'core_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_glyph_resolve_model.argtypes=[ctypes.c_uint16,ctypes.c_void_p];c.native_glyph_resolve_model.restype=ctypes.c_uint16
 c.native_draw_uses_b.argtypes=[ctypes.c_void_p,ctypes.c_uint16];c.native_draw_uses_b.restype=ctypes.c_int
 for ed in ('original','best','sp'):
  elf,lock=native(ed);r=next(r for r in inv['editions'] if r['edition']==ed);d=int(r['core_va_delta'],16);F=int(r['state_va'],16)
  u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20);u.mem_map(0x70000000,0x1000)
  for _,off,va,_,n,*_ in elf.loads:u.mem_write(va,elf.b[off:off+n])
  a,b=elf.words(0x13a8ac+d,1)[0],elf.words(0x13a8b4+d,1)[0];imm=b&65535;table_va=((a&65535)<<16)+(imm if imm<32768 else imm-65536)
  table=bytearray();keys=[]
  for off in range(0,65536,4):
   row=elf.read(table_va+off,4);table.extend(row);key=int.from_bytes(row[:2],'little')
   if not key:break
   keys.append(key)
  else:raise AssertionError('unterminated extended glyph table')
  ct=ctypes.create_string_buffer(bytes(table));start=time.monotonic();digest=hashlib.sha256();outside=0
  stop=u.hook_add(UC_HOOK_CODE,lambda uc,pc,size,data:uc.emu_stop(),begin=0x13a990+d,end=0x13a990+d)
  for code in range(65536):
   u.reg_write(UC_MIPS_REG_2,code);u.emu_start(0x13a7a0+d,0,count=100000)
   assert u.reg_read(UC_MIPS_REG_PC)==0x13a990+d,(ed,code,'resolver failed to return',hex(u.reg_read(UC_MIPS_REG_PC)))
   result=bytes(u.mem_read(0x70000062,2));actual=int.from_bytes(result,'little');expected=c.native_glyph_resolve_model(code,ct)
   assert actual==expected,(ed,hex(code),actual,expected)
   digest.update(result);outside+=actual>=4480
  print(ed,'65536 glyph codes matched',round(time.monotonic()-start,2),'s',flush=True)
  # Every classification flag combination, range boundaries and neighbors.
  codes=sorted({0,65535,0x824f,0x8258,0x8259}|{v+o for v in (0x8140,0x8260,0x827a,0x8281,0x829b,0x829f,0x82f2,0x8340,0x8492,0x889f) for o in (-1,0,1)})
  u.hook_del(stop);stop=u.hook_add(UC_HOOK_CODE,lambda uc,pc,size,data:uc.emu_stop(),begin=0x13a7a0+d,end=0x13a7a0+d)
  count=0
  for mask in range(32):
   state=bytearray(0x50);struct.pack_into('<8h',state,0x38,21,12,21,14,14,10,12,13);struct.pack_into('<h',state,0x48,1)
   state[0x4b:0x50]=bytes((mask>>i)&1 for i in range(5));u.mem_write(F,bytes(state));model_state=ctypes.create_string_buffer(bytes(state));u.reg_write(UC_MIPS_REG_17,F)
   for code in codes:
    u.reg_write(UC_MIPS_REG_2,code);u.emu_start(0x13a630+d,0,count=1000)
    assert u.reg_read(UC_MIPS_REG_PC)==0x13a7a0+d
    actual=bytes(u.mem_read(0x7000003c,4))+bytes(u.mem_read(0x70000038,4));use_b=c.native_draw_uses_b(model_state,code)
    assert actual==struct.pack('<4h',*( (14,10,12,13) if use_b else (21,12,21,14))),(ed,mask,hex(code),actual.hex())
    count+=1
  result={'edition':ed,'native_executable':lock,'resolver_range':[hex(0x13a7a0+d),hex(0x13a990+d)],'code_count':65536,'all_results_le16_sha256':digest.hexdigest(),'results_outside_4480_glyph_store':outside,'extended_table_va':hex(table_va),'extended_table_records':len(keys),'extended_table_sha256':hashlib.sha256(table).hexdigest(),'classification_flag_combinations':32,'classification_boundary_codes':len(codes),'classification_cases':count,'elapsed_seconds':round(time.monotonic()-start,3)}
  results.append(result)
(OUT/'resolver-execution.json').write_text(json.dumps({'status':'three_native_resolvers_all_16bit_codes_and_draw_classification_boundary_matrix_match_C_models','scope':__doc__,'editions':results},indent=2)+'\n')
