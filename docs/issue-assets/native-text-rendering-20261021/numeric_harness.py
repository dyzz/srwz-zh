"""Native numeric composition harness; explicit EE instruction adaptation only."""
import ctypes,struct,json
from pathlib import Path
from inventory import native
from execute import GPRS
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent

def machine(edition,parser=False):
 e,_=native(edition)
 row=next(x for x in json.loads((OUT/'inventory.json').read_text())['editions'] if x['edition']==edition)
 fn=next(x for x in json.loads((OUT/'numeric-inventory.json').read_text())['editions'] if x['edition']==edition)['functions']
 d=int(row['core_va_delta'],16);F=int(row['state_va'],16)
 u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20);u.mem_map(0x70000000,0x1000)
 for _,off,va,_,n,*_ in e.loads:u.mem_write(va,e.b[off:off+n])
 spans=[(int(f['entry'],16),int(f['end'],16)) for f in fn.values()]+[(0x13aca0+d,0x13bd60+d)]
 if parser:spans.append((0x13a290+d,0x13ac90+d))
 adapters={};upper=[bytes(8) for _ in range(32)];executed=set()
 for a,b in spans:
  for pc in range(a,b,4):
   w=e.words(pc,1)[0]
   if w>>26 in (0x1e,0x1f) or (w>>26==0 and w&63 in (0x18,0x19) and (w>>11)&31):adapters[pc]=w;u.mem_write(pc,b'\0'*4)
 def hook(uc,pc,size,data):
  if pc==0x8000:uc.emu_stop();return
  w=adapters.get(pc)
  if w is None:return
  executed.add(pc);op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31
  if op in (0x1e,0x1f):
   addr=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
   if op==0x1e:
    value=bytes(uc.mem_read(addr,16))
    if rt:uc.reg_write(GPRS[rt],int.from_bytes(value[:8],'little'));upper[rt]=value[8:]
   else:uc.mem_write(addr,uc.reg_read(GPRS[rt]).to_bytes(8,'little')+upper[rt])
  else:
   a=uc.reg_read(GPRS[rs])&0xffffffff;b=uc.reg_read(GPRS[rt])&0xffffffff
   product=(ctypes.c_int32(a).value*ctypes.c_int32(b).value if w&63==0x18 else a*b)&0xffffffffffffffff
   uc.reg_write(GPRS[(w>>11)&31],ctypes.c_int32(product).value&0xffffffffffffffff)
   uc.reg_write(UC_MIPS_REG_LO,ctypes.c_int32(product).value&0xffffffffffffffff);uc.reg_write(UC_MIPS_REG_HI,ctypes.c_int32(product>>32).value&0xffffffffffffffff)
 u.hook_add(UC_HOOK_CODE,hook)
 hi,lo=e.words(0x13acd0+d,2);template_va=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value
 sym=int(fn['symbol_list']['entry'],16);hi,lo=e.words(sym+0x78,2);pointer=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value
 seed=e.read(int.from_bytes(e.read(pointer,4),'little'),84)
 return u,e,row,fn,F,e.read(template_va,0xd0),seed,executed

def call(u,entry,args):
 for reg in GPRS[1:]:u.reg_write(reg,0)
 u.reg_write(UC_MIPS_REG_2,0x13572468);u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_GP,0x1800000);u.reg_write(UC_MIPS_REG_RA,0x8000)
 for reg,v in zip(GPRS[4:],args):u.reg_write(reg,v&0xffffffffffffffff)
 try:u.emu_start(entry,0,count=2000000)
 except Exception as ex:raise RuntimeError((hex(entry),hex(u.reg_read(UC_MIPS_REG_PC)),str(ex))) from ex
 assert u.reg_read(UC_MIPS_REG_PC)==0x8000,('native did not return',hex(entry),hex(u.reg_read(UC_MIPS_REG_PC)))
 return u.reg_read(UC_MIPS_REG_2)&0xffffffff
