"""Native IRQ leaves executed with narrowly declared LRPS2 CP0 instructions.
All ordinary native branch/delay/integer operations execute unchanged. Models
cover permission-domain nontermination; this is not LRPS2/hardware acceptance.
"""
from pathlib import Path
import ctypes,struct,json,tempfile,subprocess,hashlib
from inventory import native
from execute import GPRS
from cp0_adapter import StatusAdapter
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_PC
OUT=Path(__file__).parent;inventory=json.loads((OUT/'dma-wait-inventory.json').read_text());results=[]
with tempfile.TemporaryDirectory(prefix='srwz-native-cp0-') as td:
 path=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'cp0_model.c'),'-o',str(path)],check=True);c=ctypes.CDLL(str(path));c.native_irq_enter_model.argtypes=[ctypes.c_void_p];c.native_irq_exit_model.argtypes=[ctypes.c_void_p,ctypes.c_uint64,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  e,_=native(ed);r=next(x for x in inventory['editions'] if x['edition']==ed);u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20)
  for _,off,va,_,n,*_ in e.loads:u.mem_write(va,e.b[off:off+n])
  enter=int(r['functions']['interrupt_enter']['entry'],16);exit=int(r['functions']['interrupt_exit']['entry'],16);adapter=StatusAdapter(u,e,[(enter,enter+0x50),(exit,exit+0x18)])
  def stop(uc,pc,size,data):uc.emu_stop()
  u.hook_add(UC_HOOK_CODE,stop,begin=0x8000,end=0x8000)
  for ksu in range(4):
   for eie in (0,1):
    for edi in (0,1):
     for exl in (0,1):
      for erl in (0,1):
       for noise in (0,0xf0c40001):
        initial=(noise&~0x3001e)|(ksu<<3)|(eie<<16)|(edi<<17)|(exl<<1)|(erl<<2)
        for kind,entry in (('enter',enter),('exit',exit)):
         for next_event in ((3,100) if kind=='exit' else (100,)):
          status=ctypes.c_uint32(initial);next_value=ctypes.c_uint64(next_event);expected=c.native_irq_enter_model(ctypes.byref(status)) if kind=='enter' else c.native_irq_exit_model(ctypes.byref(status),0,ctypes.byref(next_value));adapter.reset(initial,next_event=next_event)
          for reg in GPRS[1:]:u.reg_write(reg,0)
          u.reg_write(GPRS[31],0x8000);u.emu_start(entry,0,count=400);returned=u.reg_read(UC_MIPS_REG_PC)==0x8000
          if expected<0:assert not returned and sum(x['operation']=='DI' for x in adapter.events)>1,(ed,initial,'stable permission-denied DI loop')
          else:assert returned and u.reg_read(GPRS[2])==expected,(ed,kind,initial,'return')
          assert adapter.status==status.value and adapter.next_event==next_value.value,(ed,kind,initial,'status/event')
          results.append(dict(edition=ed,kind=kind,initial_status=hex(initial),returned=returned,expected_return=expected if expected>=0 else None,stable_status_nontermination=expected<0,final_status=hex(adapter.status),initial_next_event=next_event,final_next_event=adapter.next_event,adapted_operations=sorted(set(x['operation'] for x in adapter.events))))
  print(ed,'384 native IRQ-wrapper status/permission/event cases passed',flush=True)
(OUT/'cp0-wrapper-execution.json').write_text(json.dumps(dict(scope=__doc__,status='three_native_IRQ_wrappers_match_C_with_declared_pinned_LRPS2_CP0_instruction_adapter',case_count=len(results),cases=results),indent=2)+'\n')
