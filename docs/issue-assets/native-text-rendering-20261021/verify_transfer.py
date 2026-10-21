"""Original deferred font-atlas image packet and REF-chain helper comparisons.
All original native instructions, including original flush callee, execute.
EE LQ/SQ save/restore adapted with separate high64 lanes; no DMA/GS call.
Checks complete touched/untouched buffers, state globals and returned pointer.
Packet storage is SD-aligned (8 bytes); 8-mod16 cases expose REF rounding.
Unaligned SD input faults are outside the successful-call C model.
"""
from pathlib import Path
import ctypes,struct,json,subprocess,tempfile,random,hashlib
from numeric_harness import machine,call
from string_adapter import install
OUT=Path(__file__).parent;inventory=json.loads((OUT/'transfer-inventory.json').read_text());results=[]
flush_deltas=[0,1,7,15,16,17,31,32,63,64,4096,-1,-7,-15,-16,-17,-31,-32,-64,-4096]
rng=random.Random(0x41544c4153)
build_cases=[]
for delta in flush_deltas:
 for alignment in (0,8,16):build_cases.append((f'atlas_delta{delta}_align{alignment}',alignment,delta,[0x1180,8,0x24,0x1b00000,0xf00,0,0,512,240]))
for i in range(90):
 p=[rng.choice([0,1,8,0x24,0x1180,0x7fff,0xffff,0xffffffff,0x80000000,rng.getrandbits(32)]) for _ in range(9)]
 build_cases.append((f'raw_parameter_bits_{i:02}',rng.randrange(4)*8,rng.choice(flush_deltas),p))
with tempfile.TemporaryDirectory(prefix='srwz-native-transfer-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'transfer_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_transfer_flush_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_uint32];c.native_transfer_builder_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_void_p];c.native_transfer_builder_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  u,e,row,fn,F,_,_,_=machine(ed);r=next(x for x in inventory['editions'] if x['edition']==ed);builder=int(r['transfer_builder'],16);flush=int(r['flush_ref_chain'],16);install(u,e,[(builder,builder+0x1d8)])
  hi=e.words(builder+0x70,1)[0];lo=e.words(builder+0x78,1)[0];assert hi>>16==0x3c01 and lo>>16==0x8c27
  chain_global=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;current_global=chain_global-16;previous_global=chain_global-8
  assert e.words(flush+4,1)[0]>>16==0xac24 and e.words(flush+4,1)[0]&65535==current_global&65535
  chain_base=0x1c00000;packet_base=0x1a00000;source=0x1b00000;capacity=1024
  for i,delta in enumerate(flush_deltas):
   current=0x1a00040;previous=(current-delta)&0xffffffff;g=(ctypes.c_uint32*3)(0x13572468,previous,chain_base);chain=ctypes.create_string_buffer(b'\xa5'*capacity);u.mem_write(chain_base,b'\xa5'*capacity)
   for addr,v in zip((current_global,previous_global,chain_global),g):u.mem_write(addr,struct.pack('<I',v))
   expected=c.native_transfer_flush_model(g,chain,capacity,chain_base,current);assert expected==0;call(u,flush,[current])
   assert bytes(u.mem_read(chain_base,capacity))==bytes(chain)[:capacity],(ed,delta,'flush chain')
   assert [int.from_bytes(u.mem_read(a,4),'little') for a in (current_global,previous_global,chain_global)]==list(g),(ed,delta,'flush globals')
   results.append(dict(edition=ed,kind='flush',difference=delta,state=list(g),chain_sha256=hashlib.sha256(bytes(chain)[:capacity]).hexdigest()))
  for name,alignment,delta,params in build_cases:
   address=packet_base+alignment;previous=(address-delta)&0xffffffff;g=(ctypes.c_uint32*3)(0x13572468,previous,chain_base);chain=ctypes.create_string_buffer(b'\xa5'*capacity);packet=ctypes.create_string_buffer(b'\xa5'*256);p=(ctypes.c_uint32*9)(*params);u.mem_write(chain_base,b'\xa5'*capacity);u.mem_write(address,b'\xa5'*256)
   for addr,v in zip((current_global,previous_global,chain_global),g):u.mem_write(addr,struct.pack('<I',v))
   expected=c.native_transfer_builder_model(g,chain,capacity,chain_base,packet,256,address,p)
   # EE passes arguments 9/10 in two 8-byte caller stack slots.
   u.mem_write(0x1ff0000,struct.pack('<2Q',params[7],params[8]));actual=call(u,builder,[address,*params[:7]])
   assert actual==expected,(ed,name,'return',hex(actual),hex(expected));assert bytes(u.mem_read(address,256))==bytes(packet)[:256],(ed,name,'packet');assert bytes(u.mem_read(chain_base,capacity))==bytes(chain)[:capacity],(ed,name,'chain');assert [int.from_bytes(u.mem_read(a,4),'little') for a in (current_global,previous_global,chain_global)]==list(g),(ed,name,'globals')
   results.append(dict(edition=ed,kind='builder',case=name,args=params,packet_address=hex(address),difference=delta,return_address=hex(actual),globals=list(g),chain_entries=(g[2]-chain_base)//16,packet_sha256=hashlib.sha256(bytes(packet)[:256]).hexdigest(),chain_sha256=hashlib.sha256(bytes(chain)[:capacity]).hexdigest()))
  print(ed,len(flush_deltas),'flush and',len(build_cases),'native composed image-packet/REF-chain cases match C',flush=True)
(OUT/'transfer-execution.json').write_text(json.dumps(dict(scope=__doc__,status='three_native_transfer_builders_and_original_flush_callees_match_C_buffers_and_globals',case_count=len(results),cases=results),indent=2)+'\n')
