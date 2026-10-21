"""Explicit EE adapters required by native CRT decimal conversion.
Semantics checked against libretro/ps2 MMI.cpp and opcode tables at commit
6664c60294ee05fe5e8c7645ab7da546dae78ed2. No function-body replacements.
Supported subset: MOVZ/N, scalar MULT-rd, MULTU1, MADD, PMFHL.LW, PCPYUD.
All other instructions retain native execution, so missing ops fail visibly.
"""
import ctypes,struct
from execute import GPRS
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_LO,UC_MIPS_REG_HI
MASK=(1<<64)-1

def install(u,e):
 adapters={};upper=[0]*32;extra={'lo1':0,'hi1':0};seen=set()
 def s32(v):return ctypes.c_int32(v).value
 def supported(w):
  if w>>26==0:return w&63 in (10,11) or (w&63 in (24,25) and (w>>11)&31)
  if w>>26!=0x1c:return False
  return w&63 in (0,25) or (w&63==48 and (w>>6)&31==0) or (w&63==41 and (w>>6)&31==14)
 for _,off,va,_,n,*_ in e.loads:
  for pos in range(off,off+n-3,4):
   pc=va+pos-off;w=struct.unpack_from('<I',e.b,pos)[0]
   # Core font MULT adapters are already installed by numeric_harness.
   if supported(w) and not 0x139000<=pc<0x13e000:adapters[pc]=w;u.mem_write(pc,b'\0'*4)
 def hook(uc,pc,size,data):
  w=adapters.get(pc)
  if w is None:return
  seen.add(pc);op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31;rd=(w>>11)&31;fun=w&63
  a=uc.reg_read(GPRS[rs]);b=uc.reg_read(GPRS[rt])
  def write(reg,value):
   if reg:uc.reg_write(GPRS[reg],value&MASK)
  def hilo(product):
   uc.reg_write(UC_MIPS_REG_LO,s32(product)&MASK);uc.reg_write(UC_MIPS_REG_HI,s32(product>>32)&MASK)
  if op==0:
   if fun in (10,11):
    if (b==0) if fun==10 else (b!=0):write(rd,a)
   else:
    product=(s32(a)*s32(b) if fun==24 else (a&0xffffffff)*(b&0xffffffff))&MASK;hilo(product);write(rd,s32(product))
  elif fun==25:
   product=(a&0xffffffff)*(b&0xffffffff);extra['lo1']=s32(product)&MASK;extra['hi1']=s32(product>>32)&MASK;write(rd,extra['lo1'])
  elif fun==0:
   accumulator=(uc.reg_read(UC_MIPS_REG_LO)&0xffffffff)|((uc.reg_read(UC_MIPS_REG_HI)&0xffffffff)<<32)
   product=(accumulator+s32(a)*s32(b))&MASK;hilo(product);write(rd,s32(product))
  elif fun==48:
   value=(uc.reg_read(UC_MIPS_REG_LO)&0xffffffff)|((uc.reg_read(UC_MIPS_REG_HI)&0xffffffff)<<32)
   write(rd,value)
   if rd:upper[rd]=(extra['lo1']&0xffffffff)|((extra['hi1']&0xffffffff)<<32)
  elif fun==41:
   low,high=upper[rs],upper[rt];write(rd,low)
   if rd:upper[rd]=high
 u.hook_add(UC_HOOK_CODE,hook)
 return seen
