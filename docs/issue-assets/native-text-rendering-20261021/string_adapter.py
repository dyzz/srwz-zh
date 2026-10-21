"""Declared EE full128 adapters for native CRT strcpy/strlen spans.
LQ/SQ, MOVZ/MOVN (low64), PSUBB, PCPYLD, PCPYUD, PAND, PNOR; remaining ops execute unchanged.
Semantics reference: pinned libretro/ps2 MMI.cpp and opcode tables identified
in crt-adapter-sources.json. This is not a general EE interpreter.
"""
import ctypes
from execute import GPRS
from unicorn import UC_HOOK_CODE
MASK=(1<<64)-1;FULL=(1<<128)-1

def install(u,e,spans):
 adapted={};upper=[0]*32;seen=set()
 for lo,hi in spans:
  for pc in range(lo,hi,4):
   w=e.words(pc,1)[0];op=w>>26;fn=w&63;sub=(w>>6)&31
   if op in (0x1e,0x1f) or (op==0 and fn in (10,11)) or (op==0x1c and (fn==8 and sub==9 or fn==9 and sub in (14,18) or fn==41 and sub in (14,19))):adapted[pc]=w;u.mem_write(pc,b'\0'*4)
 def hook(uc,pc,size,data):
  w=adapted.get(pc)
  if w is None:return
  seen.add(pc);op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31;rd=(w>>11)&31;fn=w&63;sub=(w>>6)&31
  def get(r):return (uc.reg_read(GPRS[r])|(upper[r]<<64)) if r else 0
  def put(r,v):
   if r:uc.reg_write(GPRS[r],v&MASK);upper[r]=(v>>64)&MASK
  if op in (0x1e,0x1f):
   addr=(uc.reg_read(GPRS[rs])+ctypes.c_int16(w&65535).value)&0xffffffff
   if op==0x1e:put(rt,int.from_bytes(uc.mem_read(addr,16),'little'))
   else:uc.mem_write(addr,get(rt).to_bytes(16,'little'))
   return
  if op==0:
   condition=uc.reg_read(GPRS[rt])
   if rd and ((condition==0) if fn==10 else (condition!=0)):uc.reg_write(GPRS[rd],uc.reg_read(GPRS[rs]))
   return
  a,b=get(rs),get(rt)
  if fn==8:result=sum((((a>>(i*8))-(b>>(i*8)))&255)<<(i*8) for i in range(16))
  elif fn==9 and sub==14:result=((a&MASK)<<64)|(b&MASK)
  elif fn==9:result=a&b
  elif sub==14:result=(a>>64)|((b>>64)<<64)
  else:result=~(a|b)&FULL
  put(rd,result)
 u.hook_add(UC_HOOK_CODE,hook)
 return seen
