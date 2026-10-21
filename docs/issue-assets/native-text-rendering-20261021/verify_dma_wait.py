"""Native busy/timeout/recovery compositions vs C value and store-order models.
The complete original 0x1000000 counter loop executes for timeout cases.
Default mode contracts diagnostic and IRQ leaves. --native-interrupts executes
original IRQ leaves with the pinned LRPS2 CP0 instruction adapter; diagnostic
output stays external. Readiness/MMIO are device shadows, not hardware timing.
"""
from pathlib import Path
import ctypes,json,struct,tempfile,subprocess,hashlib,argparse
parser=argparse.ArgumentParser();parser.add_argument('--native-interrupts',action='store_true');NATIVE_IRQ=parser.parse_args().native_interrupts
from dma_wait_harness import Harness,BASE
OUT=Path(__file__).parent;submission=json.loads((OUT/'submission-inventory.json').read_text());results=[]
with tempfile.TemporaryDirectory(prefix='srwz-dma-wait-') as td:
 path=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'dma_wait_model.c'),'-o',str(path)],check=True)
 c=ctypes.CDLL(str(path));c.native_dma_recovery_model.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];c.native_dma_recovery_model.restype=ctypes.c_uint32
 c.native_dma_wait_value_model.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];c.native_dma_wait_value_model.restype=ctypes.c_uint32
 c.native_dma_wait_send_model.argtypes=[ctypes.c_void_p]+[ctypes.c_uint32]*4+[ctypes.c_void_p]*4;c.native_dma_wait_send_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  h=Harness(ed,native_interrupts=NATIVE_IRQ);send=int(next(x for x in submission['editions'] if x['edition']==ed)['functions']['send_chain']['entry'],16);cases=[]
  for control in (0,0x100,0x105,0xffffffff,8,0xfffffeff):
   for enable in (0,1,0x10000,0xffffffff):
    for irq in ((0,0x10000,8,0x30008,0x1000a,0x1000c) if NATIVE_IRQ else (0,1)):cases.append(('recovery',control,enable,irq,0,0x12345678))
  for control in (0x100,0x105,0xffffffff):
   for ready in (1,2,3,16,255,1024):cases.append(('wait',control,0,ready%2,ready,0x12345678))
  for enable,irq,tadr in ((0,1,0x12345678),(0x10000,0,0xffffffff)):
   if NATIVE_IRQ:irq=irq<<16
   cases.append(('wait_timeout',0x105,enable,irq,0,tadr));cases.append(('send_timeout',0x105,enable,irq,0,tadr))
  for kind,control,enable,irq,ready,tadr in cases:
   initial=bytearray(b'\xa5'*128);struct.pack_into('<I',initial,0,control);struct.pack_into('<I',initial,0x30,tadr);channel=ctypes.create_string_buffer(bytes(initial));enable_write=ctypes.c_uint32(0x13572468);events=(ctypes.c_uint32*32)();count=ctypes.c_uint();diagnostics=ctypes.c_uint();chain=0x70123450
   if kind=='recovery':expected=c.native_dma_recovery_model(channel,BASE,enable,ctypes.byref(enable_write),events,ctypes.byref(count));entry=h.functions['recovery'];args=[BASE]
   elif kind=='send_timeout':expected=c.native_dma_wait_send_model(channel,BASE,chain,ready,enable,ctypes.byref(enable_write),events,ctypes.byref(count),ctypes.byref(diagnostics));entry=send;args=[BASE,chain]
   else:expected=c.native_dma_wait_value_model(channel,BASE,ready,enable,ctypes.byref(enable_write),events,ctypes.byref(count),ctypes.byref(diagnostics));entry=h.functions['wait'];args=[BASE]
   irq_result=int(bool(irq&0x10000)) if NATIVE_IRQ else irq
   actual=h.run(entry,bytes(initial),enable,irq_result,ready,args,cp0_status=irq if NATIVE_IRQ else None)
   if NATIVE_IRQ:assert actual['cp0_status']==irq,(ed,kind,'IRQ state must be restored')
   assert actual['return_value']==expected,(ed,kind,control,'return');assert actual['channel']==bytes(channel)[:128],(ed,kind,control,'channel');assert actual['enable_write']==enable_write.value,(ed,kind,'enable');expected_stores=[tuple(events[i*2:i*2+2]) for i in range(count.value)];assert actual['stores']==expected_stores,(ed,kind,actual['stores'],expected_stores)
   assert len(actual['diagnostics'])==diagnostics.value
   recovering=kind=='recovery' or diagnostics.value!=0
   assert actual['interrupts']==(['enter']+(['exit'] if irq_result else []) if recovering else []),(ed,kind,'interrupt service calls')
   assert actual['reads']==([0x1000f520,0x1000e000] if recovering else []),(ed,kind,'MMIO shadow reads')
   if ready:assert actual['polls']==ready
   for diagnostic in actual['diagnostics']:assert diagnostic['counter']==-1
   if kind=='send_timeout':assert struct.unpack_from('<I',actual['channel'])[0]&0x100,'timeout send must still arm new chain'
   results.append(dict(edition=ed,kind=kind,initial_control=hex(control),enable_read=hex(enable),interrupt_enter_return=irq_result,initial_cp0_status=hex(irq) if NATIVE_IRQ else None,cp0_operations=actual['cp0_operations'],ready_poll=ready,initial_tadr=hex(tadr),returned=hex(actual['return_value']),stores=[dict(address=hex(a),value=hex(v)) for a,v in actual['stores']],device_reads=list(map(hex,actual['reads'])),interrupt_service_calls=actual['interrupts'],diagnostics=actual['diagnostics'],observed_polls=actual['polls'],full_counter_loop=kind.endswith('timeout'),elapsed_seconds=actual['elapsed_seconds'],channel_sha256=hashlib.sha256(actual['channel']).hexdigest()))
   if kind.endswith('timeout'):print(ed,kind,'full native counter loop and recovery matched C;',round(actual['elapsed_seconds'],3),'s',flush=True)
  print(ed,len(cases),'native recovery/busy/full-timeout/send compositions passed',flush=True)
(OUT/('dma-wait-native-interrupt-execution.json' if NATIVE_IRQ else 'dma-wait-execution.json')).write_text(json.dumps(dict(scope=__doc__,native_interrupt_wrappers=NATIVE_IRQ,status=('three_original_wait_recovery_IRQ_send_paths_match_C_with_CP0_adapter_and_device_shadows' if NATIVE_IRQ else 'three_original_integer_wait_recovery_send_paths_match_C_under_explicit_device_and_leaf_contracts'),case_count=len(results),cases=results),indent=2)+'\n')
