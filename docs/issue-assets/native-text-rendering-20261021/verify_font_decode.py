"""Execute each native font decompressor on actual font/resources and fixed streams.
Original integer code executes; only EE LQ/SQ ABI save/restore is adapted.
No disc I/O is emulated: compressed source members are independently read first.
"""
from pathlib import Path
import json,sys,struct,ctypes,tempfile,subprocess,hashlib,random
from inventory import native
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from srwz.codec import decode,encode,encode_coded_integer
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent;ROOT=OUT.parents[2];resources=json.loads((OUT/'resource-inventory.json').read_text());results=[]
fixtures=[('empty',b''),('single',b'A'),('overlapping_run',b'A'*4096),('alternating',b'AB'*1024),('byte_domain',bytes(range(256))*3)]
rng=random.Random(0x434f4445)
fixtures.extend((f'fixed_seed_{i}',bytes(rng.randrange(256) for _ in range(i*47+1))) for i in range(10))
streams=[(name+'_'+strategy,encode(data,strategy=strategy),data,'valid') for name,data in fixtures for strategy in ('literal','greedy')]
# Explicit native error behaviors: wrapper ignores body return status; literals
# may overrun the declared size. Strict tooling is expected to reject both.
h=lambda n:encode_coded_integer(n)+encode_coded_integer(0)+encode_coded_integer(0)
streams += [('bad_match_returns_declared',h(5)+bytes.fromhex('114115'),None,'bad_match'),('literal_overrun',h(1)+bytes.fromhex('02015859'),None,'literal_overrun')]
with tempfile.TemporaryDirectory(prefix='srwz-font-decoder-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'font_decode_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_font_decode_model.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];c.native_font_decode_model.restype=ctypes.c_int32
 for ed in ('original','best','sp'):
  elf,lock=native(ed);rr=next(x for x in resources['editions'] if x['edition']==ed);init=int(rr['functions']['resource_initialize']['entry'],16)
  call=elf.words(init+0x254,1)[0];assert call>>26==3;entry=(call&0x3ffffff)<<2
  hi,lo=elf.words(init+0x200,1)[0],elf.words(init+0x208,1)[0];im=lo&65535;table_va=((hi&65535)<<16)+(im if im<32768 else im-65536)
  cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());iso=ROOT/cfg['source_iso']['path'];members=member_map(scan_iso9660(iso))
  def read(name):
   m=members[name]
   with iso.open('rb') as f:f.seek(m.extent_lba*2048);return f.read(m.size)
  assert hashlib.sha256(read(cfg['executable']['member'])).hexdigest()==lock['sha256']
  vt1=read('DATA/VT1.BIN');real=[]
  def index_value(hi_off,load_off):
   hi=elf.words(init+hi_off,1)[0]&65535;lo=elf.words(init+load_off,1)[0]&65535
   address=(hi<<16)+(lo if lo<32768 else lo-65536)
   return int.from_bytes(elf.read(address,2),'little')
  for label,parts in (('font',(0x20c,0x214,0x21c,0x224)),('numeric_texture',(0x14,0x20,0x44,0x4c))):
   index=index_value(*parts[:2]);end_index=index_value(*parts[2:])
   a=elf.words(table_va+index*4,1)[0];b=elf.words(table_va+end_index*4,1)[0]
   compressed=vt1[a:b];print('font member',ed,label,index,end_index,hex(a),hex(b),flush=True)
   expected=decode(compressed).output;real.append((f'native_VT1_{label}_{index}',compressed,expected,'valid'))
  u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20)
  for _,o,v,_,n,*_ in elf.loads:u.mem_write(v,elf.b[o:o+n])
  STOP=0x8000;IN=0x1800000;DEST=0x1a00000;SP=0x1ff0000;adapted={}
  for pc in range(entry,entry+0x110,4):
   w=elf.words(pc,1)[0]
   if w>>26 in (0x1e,0x1f):adapted[pc]=w;u.mem_write(pc,b'\0'*4)
  regs=[globals()[f'UC_MIPS_REG_{i}'] for i in range(32)];upper=[bytes(8) for _ in range(32)]
  def adapt(uc,pc,size,data):
   w=adapted[pc];rs=(w>>21)&31;rt=(w>>16)&31;im=w&65535;im=im if im<32768 else im-65536;a=(uc.reg_read(regs[rs])+im)&0xffffffff
   if w>>26==0x1e:
    value=bytes(uc.mem_read(a,16));uc.reg_write(regs[rt],int.from_bytes(value[:8],'little'));upper[rt]=value[8:]
   else:uc.mem_write(a,uc.reg_read(regs[rt]).to_bytes(8,'little')+upper[rt])
  for pc in adapted:u.hook_add(UC_HOOK_CODE,adapt,begin=pc,end=pc)
  u.hook_add(UC_HOOK_CODE,lambda uc,pc,size,data:uc.emu_stop(),begin=STOP,end=STOP)
  inner_call=elf.words(entry+0xec,1)[0];body=(inner_call&0x3ffffff)<<2;body_errors=[]
  u.hook_add(UC_HOOK_CODE,lambda uc,pc,size,data:body_errors.append(uc.reg_read(UC_MIPS_REG_2)&0xffffffff),begin=body+0x178,end=body+0x178)
  for name,compressed,expected,kind in streams+real:
   capacity=max(len(expected or b''),8192)+64;u.mem_write(IN,compressed);u.mem_write(DEST,b'\xa5'*capacity);u.reg_write(UC_MIPS_REG_SP,SP);u.reg_write(UC_MIPS_REG_RA,STOP);u.reg_write(UC_MIPS_REG_4,IN);u.reg_write(UC_MIPS_REG_5,DEST);body_errors.clear()
   u.emu_start(entry,0,count=150000000);assert u.reg_read(UC_MIPS_REG_PC)==STOP,(ed,name,hex(u.reg_read(UC_MIPS_REG_PC)))
   ret=u.reg_read(UC_MIPS_REG_2)&0xffffffff;consumed=u.reg_read(UC_MIPS_REG_4)-IN;actual=bytes(u.mem_read(DEST,capacity))
   src=ctypes.create_string_buffer(compressed);out=ctypes.create_string_buffer(b'\xa5'*capacity);n=ctypes.c_size_t();written=ctypes.c_size_t();err=ctypes.c_int()
   cr=c.native_font_decode_model(src,len(compressed),out,capacity,ctypes.byref(n),ctypes.byref(written),ctypes.byref(err))
   assert cr==ret and n.value==consumed,(ed,name,'return/consumed',cr,ret,n.value,consumed)
   assert bytes(out)[:capacity]==actual,(ed,name,'decoded and untouched output bytes')
   assert not body_errors or body_errors[-1]==err.value,(ed,name,'native body error ignored by wrapper')
   if kind=='valid':assert ret==len(expected) and actual[:ret]==expected,(ed,name,'tool decoder disagreement')
   else:
    try:decode(compressed)
    except Exception:pass
    else:raise AssertionError((ed,name,'strict tool accepted malformed case'))
   results.append({'edition':ed,'case':name,'kind':kind,'native_entry':hex(entry),'compressed_sha256':hashlib.sha256(compressed).hexdigest(),'declared_return':ret,'consumed':consumed,'written':written.value,'body_error':err.value,'output_sha256':hashlib.sha256(actual[:written.value]).hexdigest()})
  print(ed,len(streams+real),'native font decode outputs, bounds and returns match C model',flush=True)
(OUT/'font-decode-execution.json').write_text(json.dumps({'status':'three_native_font_resource_decompressors_match_C_and_valid_streams_match_tool_decoder','scope':__doc__,'case_count':len(results),'cases':results},indent=2)+'\n')
