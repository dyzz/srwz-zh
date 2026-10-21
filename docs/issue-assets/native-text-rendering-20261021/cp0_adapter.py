"""Limited CP0 Status/DI/EI adapter pinned to cp0-adapter-sources.json.
Only MFC0 Status(masked signed32), DI, EI and SYNC used by native IRQ leaves.
No real interrupt delivery, memory barrier or advancing hardware-cycle model.
"""
import ctypes
from execute import GPRS
from unicorn import UC_HOOK_CODE
class StatusAdapter:
 def __init__(self,u,elf,spans):
  self.status=0;self.cycle=0;self.next_event=100;self.events=[];self.words={}
  for lo,hi in spans:
   for pc in range(lo,hi,4):
    w=elf.words(pc,1)[0]
    if w in (0x42000038,0x42000039,0x0000040f) or w>>26==16 and w>>21&31==0 and w>>11&31==12:
     self.words[pc]=w;u.mem_write(pc,b'\0'*4)
  def execute(uc,pc,size,data):
   w=self.words[pc];before=self.status
   allowed=bool(self.status&0x20006) or self.status&0x18==0
   if w==0x42000039:
    if allowed:self.status&=~0x10000
    op='DI'
   elif w==0x42000038:
    if allowed:
     self.status|=0x10000
     if ctypes.c_int32((self.next_event-self.cycle)&0xffffffff).value>4:self.next_event=(self.cycle+4)&0xffffffffffffffff
    op='EI'
   elif w==0x0000040f:op='SYNC_declared_barrier_only'
   else:
    rt=w>>16&31
    if rt:uc.reg_write(GPRS[rt],ctypes.c_int32(self.status&0xf0c79c1f).value&0xffffffffffffffff)
    op='MFC0_Status'
   self.events.append(dict(pc=hex(pc),operation=op,status_before=hex(before),status_after=hex(self.status)))
  for pc in self.words:u.hook_add(UC_HOOK_CODE,execute,begin=pc,end=pc)
 def reset(self,status,cycle=0,next_event=100):self.status=status;self.cycle=cycle;self.next_event=next_event;self.events.clear()
