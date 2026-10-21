"""Three native DMA address mapper + ready-channel chain-send compositions.
Original wait helper executes against RAM-backed channel with start bit clear.
No stubs or live MMIO. Checks all channel bytes and native store ordering.
No busy-channel completion, cache syscall effects, or DMA/GS timing claim.
"""
from pathlib import Path
import json,ctypes,struct,tempfile,subprocess,hashlib
from numeric_harness import machine,call
from unicorn import UC_HOOK_MEM_WRITE
OUT=Path(__file__).parent;inventory=json.loads((OUT/'submission-inventory.json').read_text());results=[]
with tempfile.TemporaryDirectory(prefix='srwz-submission-') as td:
 path=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'submission_model.c'),'-o',str(path)],check=True)
 c=ctypes.CDLL(str(path));c.native_dma_address_model.argtypes=[ctypes.c_uint32];c.native_dma_address_model.restype=ctypes.c_uint32;c.native_dma_send_ready_model.argtypes=[ctypes.c_void_p,ctypes.c_uint32];c.native_dma_send_ready_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inventory['editions'] if x['edition']==ed);mapper=int(r['functions']['map_address']['entry'],16);send=int(r['functions']['send_chain']['entry'],16)
  for nibble in range(16):
   for low in (0,1,0x0fffffff):
    address=(nibble<<28)|low;actual=call(u,mapper,[address]);expected=c.native_dma_address_model(address);assert actual==expected,(ed,address,actual,expected);results.append(dict(edition=ed,kind='address_map',input=hex(address),output=hex(actual)))
  stores=[];base=0x1d00000
  def written(uc,access,address,size,value,data):
   if base<=address<base+128:stores.append(dict(offset=address-base,size=size,value=value&0xffffffff))
  u.hook_add(UC_HOOK_MEM_WRITE,written)
  for control in (0,2,4,8,0x80,0x200,0xfffffefe):
   assert not control&0x100
   for tadr in (0xffffffff,0x12345678):
    for chain in (0x70001230,0x70100000,0x80001230,0x20001230,0x1c00000,0xffffffff):
     initial=bytearray(b'\xa5'*128);struct.pack_into('<I',initial,0,control);struct.pack_into('<I',initial,0x30,tadr);channel=ctypes.create_string_buffer(bytes(initial));u.mem_write(base,bytes(initial));stores.clear();expected=c.native_dma_send_ready_model(channel,chain);actual=call(u,send,[base,chain]);assert actual==expected,(ed,control,tadr,chain,'return');assert bytes(u.mem_read(base,128))==bytes(channel)[:128],(ed,control,tadr,chain,'channel')
     assert [x['offset'] for x in stores]==([0x20,0] if tadr==0xffffffff else [0x30,0x20,0]),(ed,'native store order',stores)
     results.append(dict(edition=ed,kind='ready_send',initial_control=hex(control),initial_tadr=hex(tadr),chain=hex(chain),returned_control=hex(actual),stores=list(stores),channel_sha256=hashlib.sha256(bytes(channel)[:128]).hexdigest()))
  print(ed,'48 native address maps and 84 complete ready-channel send compositions match C',flush=True)
(OUT/'submission-execution.json').write_text(json.dumps(dict(scope=__doc__,status='three_native_mapper_wait_ready_send_paths_match_C_and_store_order',case_count=len(results),cases=results),indent=2)+'\n')
