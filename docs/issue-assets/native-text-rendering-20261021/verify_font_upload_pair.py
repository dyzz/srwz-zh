"""Complete six native dirty-gated atlas scheduling blocks vs independent C.
Calls original transfer builder and original flush helper, no body stubs.
Stops at the block's enclosing-function continuation; no DMA/GS timing claim.
"""
from pathlib import Path
import json,ctypes,struct,tempfile,subprocess,hashlib
from numeric_harness import machine,GPRS
from string_adapter import install
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_PC
OUT=Path(__file__).parent;inventory=json.loads((OUT/'transfer-inventory.json').read_text());results=[]
with tempfile.TemporaryDirectory(prefix='srwz-upload-pair-') as td:
 path=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'transfer_model.c'),'-o',str(path)],check=True)
 c=ctypes.CDLL(str(path));c.native_font_upload_pair_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inventory['editions'] if x['edition']==ed);builder=int(r['transfer_builder'],16);install(u,e,[(builder,builder+0x1d8)])
  def address(hi,lo):
   h,l=e.words(hi,1)[0],e.words(lo,1)[0];return ((h&65535)<<16)+ctypes.c_int16(l&65535).value
  chain_global=address(builder+0x70,builder+0x78);globals_va=(chain_global-16,chain_global-8,chain_global);dirty_va=F+0x70
  for block_index,b in enumerate(r['blocks']):
   start,end=int(b['start'],16),int(b['end'],16);chain_base=address(start+0x10,start+0x20);packet_base=address(start+0x18,start+0x28);temporary_va=address(start+0x78,start+0x7c);origin_va=chain_global+8
   # Independent native opcode contracts for the fixed buffers and atlas source.
   assert e.words(start+0x10,1)[0]>>16==0x3c02 and e.words(start+0x20,1)[0]>>16==0x2442
   assert e.words(start+0x18,1)[0]>>16==0x3c08 and e.words(start+0x28,1)[0]>>16==0x2508
   assert e.words(start+0x7c,1)[0]>>16==0xac24
   def stop(uc,pc,size,data):
    if pc==end:uc.emu_stop()
   hook=u.hook_add(UC_HOOK_CODE,stop)
   for dirty in (0,1,0x80000000,0xffffffff):
    for atlas in (0x1b00000,0x31b00000,5,0xfffffff0,0):
     g=(ctypes.c_uint32*3)(0x1a00120,0x1a000e0,chain_base+96);d=ctypes.c_uint32(dirty);temporary=ctypes.c_uint32(0x13572468);origin=ctypes.c_uint32(0x24681357);chain=ctypes.create_string_buffer(b'\xa5'*1024);packet=ctypes.create_string_buffer(b'\xa5'*512)
     expected=c.native_font_upload_pair_model(g,chain,1024,chain_base,packet,512,packet_base,ctypes.byref(d),atlas,ctypes.byref(temporary),ctypes.byref(origin));assert expected==0
     for addr,v in zip(globals_va,(0x1a00120,0x1a000e0,chain_base+96)):u.mem_write(addr,struct.pack('<I',v))
     for addr,v in ((dirty_va,dirty),(F+0x80,atlas),(temporary_va,0x13572468),(origin_va,0x24681357)):u.mem_write(addr,struct.pack('<I',v))
     u.mem_write(chain_base,b'\xa5'*1024);u.mem_write(packet_base,b'\xa5'*512);u.mem_write(0x1ff0000,b'\xa5'*16)
     for reg in GPRS[1:]:u.reg_write(reg,0)
     u.reg_write(GPRS[29],0x1ff0000);u.reg_write(GPRS[28],0x1800000);u.reg_write(GPRS[31],0x8000);u.emu_start(start,0,count=100000);assert u.reg_read(UC_MIPS_REG_PC)==end
     assert bytes(u.mem_read(chain_base,1024))==bytes(chain)[:1024],(ed,block_index,dirty,atlas,'chain');assert bytes(u.mem_read(packet_base,512))==bytes(packet)[:512],(ed,block_index,dirty,atlas,'packet');assert [int.from_bytes(u.mem_read(a,4),'little') for a in globals_va]==list(g),(ed,block_index,dirty,atlas,'globals')
     for addr,v in ((dirty_va,d.value),(temporary_va,temporary.value),(origin_va,origin.value)):assert int.from_bytes(u.mem_read(addr,4),'little')==v,(ed,block_index,dirty,atlas,'state',hex(addr))
     assert int.from_bytes(u.mem_read(F+0x80,4),'little')==atlas
     assert bytes(u.mem_read(0x1ff0000,16))==(struct.pack('<2Q',512,240) if dirty else b'\xa5'*16)
     results.append(dict(edition=ed,block=block_index,start=hex(start),end=hex(end),initial_dirty=hex(dirty),atlas=hex(atlas),packet_base=hex(packet_base),chain_base=hex(chain_base),chain_entries=(g[2]-chain_base)//16,final_globals=list(g),dirty=d.value,temporary=hex(temporary.value),packet_sha256=hashlib.sha256(bytes(packet)[:512]).hexdigest(),chain_sha256=hashlib.sha256(bytes(chain)[:1024]).hexdigest()))
   u.hook_del(hook)
  print(ed,'40 complete native dirty-gated two-half atlas scheduling cases match C',flush=True)
(OUT/'font-upload-pair-execution.json').write_text(json.dumps(dict(scope=__doc__,status='six_native_atlas_scheduling_blocks_match_C_with_real_transfer_and_flush_callees',case_count=len(results),cases=results),indent=2)+'\n')
