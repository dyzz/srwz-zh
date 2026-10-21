"""Original integer wait/recovery harness without per-instruction Python hooks.
Default: no instruction replacement, external diagnostic and IRQ leaf services.
Optional native IRQ mode: original IRQ leaves plus declared CP0 instruction
adaptation; diagnostic stays external. All device register values are shadows.
"""
import struct,json,ctypes,time
from pathlib import Path
from inventory import native
from execute import GPRS
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.mips_const import UC_MIPS_REG_PC
OUT=Path(__file__).parent
BASE=0x1d00000
class Harness:
 def __init__(self,edition,native_interrupts=False):
  self.row=next(r for r in json.loads((OUT/'dma-wait-inventory.json').read_text())['editions'] if r['edition']==edition);self.elf,_=native(edition);self.u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u=self.u;u.mem_map(0,32<<20);u.mem_map(0x10000000,0x10000)
  for _,off,va,_,n,*_ in self.elf.loads:u.mem_write(va,self.elf.b[off:off+n])
  self.functions={name:int(v['entry'],16) for name,v in self.row['functions'].items()};self.diagnostics=[];self.interrupts=[];self.stores=[];self.reads=[];self.irq=0;self.ready_poll=0;self.polls=0
  def stop(uc,pc,size,data):uc.emu_stop()
  u.hook_add(UC_HOOK_CODE,stop,begin=0x8000,end=0x8000)
  def external(uc,pc,size,data):
   if pc==int(self.row['diagnostic_entry'],16):
    address=uc.reg_read(GPRS[4]);message=bytes(uc.mem_read(address,96)).split(b'\0')[0];assert message.hex()==self.row['format_hex'];self.diagnostics.append(dict(address=hex(address),message_hex=message.hex(),counter=ctypes.c_int32(uc.reg_read(GPRS[17])&0xffffffff).value));result=0
   elif pc==self.functions['interrupt_enter']:self.interrupts.append('enter');result=self.irq
   else:self.interrupts.append('exit');result=0
   uc.reg_write(GPRS[2],result);uc.reg_write(UC_MIPS_REG_PC,uc.reg_read(GPRS[31]))
  services=[int(self.row['diagnostic_entry'],16)]
  self.cp0=None
  if native_interrupts:
   from cp0_adapter import StatusAdapter
   enter=self.functions['interrupt_enter'];exit=self.functions['interrupt_exit']
   self.cp0=StatusAdapter(u,self.elf,[(enter,enter+0x50),(exit,exit+0x18)])
   def irq_entry(uc,pc,size,data):self.interrupts.append('enter' if pc==enter else 'exit')
   for pc in (enter,exit):u.hook_add(UC_HOOK_CODE,irq_entry,begin=pc,end=pc)
  else:services += [self.functions['interrupt_enter'],self.functions['interrupt_exit']]
  for pc in services:u.hook_add(UC_HOOK_CODE,external,begin=pc,end=pc)
  def written(uc,access,address,size,value,data):self.stores.append((address,value&0xffffffff))
  u.hook_add(UC_HOOK_MEM_WRITE,written,begin=BASE,end=BASE+127);u.hook_add(UC_HOOK_MEM_WRITE,written,begin=0x1000f590,end=0x1000f593)
  def read(uc,access,address,size,value,data):self.reads.append(address)
  u.hook_add(UC_HOOK_MEM_READ,read,begin=0x1000e000,end=0x1000f523)
 def run(self,entry,channel,enable,irq,ready_poll=0,args=None,cp0_status=None):
  u=self.u;self.diagnostics.clear();self.interrupts.clear();self.stores.clear();self.reads.clear();self.irq=irq;self.ready_poll=ready_poll;self.polls=0
  if self.cp0:self.cp0.reset((irq<<16) if cp0_status is None else cp0_status)
  u.mem_write(BASE,channel);u.mem_write(0x1000f520,struct.pack('<I',enable));u.mem_write(0x1000f590,struct.pack('<I',0x13572468));u.mem_write(0x1000e000,struct.pack('<I',0x24681357))
  for reg in GPRS[1:]:u.reg_write(reg,0)
  u.reg_write(GPRS[29],0x1ff0000);u.reg_write(GPRS[31],0x8000)
  for reg,value in zip(GPRS[4:],args or [BASE]):u.reg_write(reg,value&0xffffffffffffffff)
  hook=None
  if ready_poll:
   def poll(uc,access,address,size,value,data):
    if uc.reg_read(UC_MIPS_REG_PC) not in (self.functions['wait']+0x1c,self.functions['wait']+0x48):return
    self.polls+=1
    if self.polls==self.ready_poll:
     old=struct.unpack('<I',uc.mem_read(BASE,4))[0];uc.mem_write(BASE,struct.pack('<I',old&0xfffffeff))
   hook=u.hook_add(UC_HOOK_MEM_READ,poll,begin=BASE,end=BASE+3)
  started=time.monotonic();u.emu_start(entry,0,count=150000000);elapsed=time.monotonic()-started
  if hook is not None:u.hook_del(hook)
  assert u.reg_read(UC_MIPS_REG_PC)==0x8000,('native did not return',hex(u.reg_read(UC_MIPS_REG_PC)))
  return dict(return_value=u.reg_read(GPRS[2])&0xffffffff,channel=bytes(u.mem_read(BASE,128)),enable_write=struct.unpack('<I',u.mem_read(0x1000f590,4))[0],stores=list(self.stores),reads=list(self.reads),diagnostics=list(self.diagnostics),interrupts=list(self.interrupts),polls=self.polls if ready_poll else None,elapsed_seconds=elapsed,cp0_status=self.cp0.status if self.cp0 else None,cp0_operations=sorted(set(x['operation'] for x in self.cp0.events)) if self.cp0 else [])
