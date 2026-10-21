"""Byte-exact native GIF packet builder comparisons, three unmodified ELF sources.
No GS execution. EE LQ/SQ are replaced in emulation RAM by NOP and adapted
with complete 128-bit load/store lanes; no packed arithmetic is used here.
All other executed integer instructions come directly from the native ELF.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from inventory import native
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent;inv=json.loads((OUT/'inventory.json').read_text());GPRS=[globals()[f'UC_MIPS_REG_{i}'] for i in range(32)]
def record(kind,style,outline,k=0):
 b=bytearray(b'\xa5'*32);struct.pack_into('<4hI',b,0,24*k,24*(k%10),30+7*k,50+3*k,0x123456+k)
 if kind:struct.pack_into('<5B',b,0xc,18+k,11+k,3+k,0x24,style)
 else:struct.pack_into('<2h3B',b,0xc,21+k,12+k,3+k,0x24,style)
 struct.pack_into('<2I',b,0x14,0x78563412+k,0x87654321+k);b[0x1c]=outline
 return bytes(b)
cases=[]
for typ in (0,1):
 for shear in (0,2,128,255):
  for outline in (0,1):
   for chain in (0,1):
    r=record(typ,shear,outline);cases.append((f'type{typ}_shear{shear}_outline{outline}_chain{chain}',r if not typ else b'',r if typ else b'',chain,0,0,(2048,2048)))
for align in (0,16,32,48):
 for chain in (0,1):cases.append((f'empty_align{align}_chain{chain}',b'',b'',chain,align,0x30000000,(2048,2048)))
rng=random.Random(0x474946)
for k in range(50):
 primary=b''.join(record(0,rng.choice((0,2,128)),rng.randrange(2),i) for i in range(rng.randrange(4)))
 secondary=b''.join(record(1,rng.choice((0,3,128)),rng.randrange(2),i) for i in range(rng.randrange(4)))
 cases.append((f'mixed_records_{k:02}',primary,secondary,rng.randrange(2),rng.randrange(4)*16,rng.choice((0,0x30000000)),rng.choice(((2048,2048),(0,0),(-16,32760)))))
report=[]
with tempfile.TemporaryDirectory(prefix='srwz-packet-model-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 model=ctypes.CDLL(str(lib));model.native_packet_model.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint,ctypes.c_int16,ctypes.c_int16,ctypes.c_void_p,ctypes.c_void_p];model.native_packet_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  elf,lock=native(ed);r=next(x for x in inv['editions'] if x['edition']==ed);d=int(r['core_va_delta'],16);F=int(r['state_va'],16)
  hi,lo=elf.words(0x13acd0+d,2);im=lo&65535;template_va=((hi&65535)<<16)+(im if im<32768 else im-65536);templates=elf.read(template_va,0xd0);ct=ctypes.create_string_buffer(templates)
  for name,primary,secondary,chain,align,alias,offset in cases:
   u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20)
   for _,off,va,_,n,*_ in elf.loads:u.mem_write(va,elf.b[off:off+n])
   adapted={};upper=[b'\0'*8 for _ in range(32)]
   for pc in range(0x13aca0+d,0x13bd60+d,4):
    w=elf.words(pc,1)[0]
    if w>>26 in (0x1e,0x1f):adapted[pc]=w;u.mem_write(pc,b'\0'*4)
   STOP=0x8000;addr=0x1c00000+align;capacity=65536
   u.mem_write(addr,b'\xa5'*capacity);u.mem_write(0x1a00000,primary or b'\0'*32);u.mem_write(0x1b00000,secondary or b'\0'*32)
   u.mem_write(F,struct.pack('<2H2h',len(primary)//32,len(secondary)//32,*offset));u.mem_write(F+0x58,struct.pack('<I',0x1a00000));u.mem_write(F+0x60,struct.pack('<I',0x1b00000))
   u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_RA,STOP);u.reg_write(UC_MIPS_REG_4,addr|alias);u.reg_write(UC_MIPS_REG_5,chain)
   adapted_count=[0]
   def hook(uc,pc,size,data):
    if pc==STOP:uc.emu_stop();return
    if pc not in adapted:return
    w=adapted[pc];rs=(w>>21)&31;rt=(w>>16)&31;im=w&65535;im=im if im<32768 else im-65536;a=(uc.reg_read(GPRS[rs])+im)&0xffffffff
    if w>>26==0x1e:
     value=bytes(uc.mem_read(a,16))
     if rt:uc.reg_write(GPRS[rt],int.from_bytes(value[:8],'little'));upper[rt]=value[8:]
    else:uc.mem_write(a,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
    adapted_count[0]+=1
   h=u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x13aca0+d,0,count=1000000)
   assert u.reg_read(UC_MIPS_REG_PC)==STOP,(ed,name,'native did not return',hex(u.reg_read(UC_MIPS_REG_PC)))
   native_out=bytes(u.mem_read(addr,capacity));native_return=u.reg_read(UC_MIPS_REG_2)&0xffffffff
   out=ctypes.create_string_buffer(b'\xa5'*capacity);a=ctypes.create_string_buffer(primary);b=ctypes.create_string_buffer(secondary);written=ctypes.c_size_t()
   ret=model.native_packet_model(out,capacity,addr|alias,chain,a,len(primary)//32,b,len(secondary)//32,*offset,ct,ctypes.byref(written))
   assert ret==native_return,(ed,name,'return',hex(ret),hex(native_return))
   if bytes(out)[:capacity]!=native_out:
    diff=[(hex(i),hex(x),hex(y)) for i,(x,y) in enumerate(zip(native_out,bytes(out))) if x!=y];raise AssertionError((ed,name,'packet bytes differ',diff[:20]))
   report.append({'edition':ed,'case':name,'primary_count':len(primary)//32,'secondary_count':len(secondary)//32,'chain':chain,'input_pointer':hex(addr|alias),'returned_pointer':hex(ret),'written':written.value,'packet_sha256':hashlib.sha256(native_out[:written.value]).hexdigest(),'full_buffer_sha256':hashlib.sha256(native_out).hexdigest(),'adapted_128bit_load_store_count':adapted_count[0]})
  print(ed,len(cases),'native packet buffers match C byte for byte',flush=True)
(OUT/'packet-execution.json').write_text(json.dumps({'status':'three_native_packet_builders_match_reconstructed_C_all_written_and_untouched_buffer_bytes','scope':__doc__,'case_count':len(report),'cases':report},indent=2)+'\n')
