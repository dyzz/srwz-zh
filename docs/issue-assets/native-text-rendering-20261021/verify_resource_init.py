"""Native resource initializer with explicit external-service contracts.
Archive reads, allocations, GS descriptor/upload and synchronization leaves are
stubbed and logged. Font decode, parser, atlas scatter and state logic execute
native instructions. This is not real disc I/O or GS execution.
"""
from pathlib import Path
import json,sys,struct,ctypes,tempfile,subprocess,hashlib
from inventory import native
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
OUT=Path(__file__).parent;ROOT=OUT.parents[2];resources=json.loads((OUT/'resource-inventory.json').read_text());core=json.loads((OUT/'inventory.json').read_text());results=[]
with tempfile.TemporaryDirectory(prefix='srwz-resource-init-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'resource_model.c'),str(OUT/'font_decode_model.c'),str(OUT/'upload_model.c'),'-o',str(lib)],check=True)
 model=ctypes.CDLL(str(lib));model.native_resource_state_model.argtypes=[ctypes.c_void_p]*8+[ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];model.native_resource_state_model.restype=ctypes.c_int
 for ed in ('original','best','sp'):
  elf,lock=native(ed);r=next(x for x in resources['editions'] if x['edition']==ed);ci=next(x for x in core['editions'] if x['edition']==ed);F=int(ci['state_va'],16);entry=int(r['functions']['resource_initialize']['entry'],16);d=int(ci['core_va_delta'],16)
  def pointer(hi_at,low_at):
   hi=elf.words(hi_at,1)[0]&65535;lo=elf.words(low_at,1)[0]&65535
   return (hi<<16)+(lo if lo<32768 else lo-65536)
  def target(offset):w=elf.words(entry+offset,1)[0];assert w>>26==3;return (w&0x3ffffff)<<2
  table=pointer(entry+0x200,entry+0x208);font_i=int.from_bytes(elf.read(pointer(entry+0x20c,entry+0x214),2),'little');font_j=int.from_bytes(elf.read(pointer(entry+0x21c,entry+0x224),2),'little');aux_i=int.from_bytes(elf.read(pointer(entry+0x14,entry+0x20),2),'little');aux_j=int.from_bytes(elf.read(pointer(entry+0x44,entry+0x4c),2),'little')
  cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());iso=ROOT/cfg['source_iso']['path'];members=member_map(scan_iso9660(iso))
  with iso.open('rb') as f:
   m=members['DATA/VT1.BIN'];f.seek(m.extent_lba*2048);vt1=f.read(m.size)
  font_source=vt1[elf.words(table+font_i*4,1)[0]:elf.words(table+font_j*4,1)[0]];aux_source=vt1[elf.words(table+aux_i*4,1)[0]:elf.words(table+aux_j*4,1)[0]]
  seedptr=elf.words(pointer(entry+0x284,entry+0x288),1)[0];seed=elf.read(seedptr,256).split(b'\0')[0]
  extva=pointer(0x13a8ac+d,0x13a8b4+d);ext=bytearray()
  for k in range(0,65536,4):
   value=elf.read(extva+k,4);ext.extend(value)
   if value[:2]==b'\0\0':break
  u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20);u.mem_map(0x70000000,0x1000)
  for _,off,va,_,n,*_ in elf.loads:u.mem_write(va,elf.b[off:off+n])
  STOP=0x8000;GP=0x1700000;SP=0x1ff0000;SOURCE=0xa00000;TEMP=0xb00000;HEAP=0xc00000;u.mem_write(F,bytes(0x90));u.mem_write(pointer(entry+0x54,entry+0x5c),struct.pack('<I',0x5678))
  regs=[globals()[f'UC_MIPS_REG_{i}'] for i in range(32)];upper=[bytes(8) for _ in range(32)];events=[];allocs=[];descs={};buffers={};adapted={};next_heap=[HEAP]
  decoder=target(0x254)
  spans=[(entry,entry+0x300),(int(ci['renderer_entry'],16),0x13ac90+d),(decoder,decoder+0x110),(int(r['functions']['default_palette_upload']['entry'],16),int(r['functions']['default_palette_upload']['end'],16))]
  for lo,hi in spans:
   for pc in range(lo,hi,4):
    w=elf.words(pc,1)[0]
    if w>>26 in (0x1e,0x1f):adapted[pc]=w;u.mem_write(pc,b'\0'*4)
  def adapt(uc,pc,size,data):
   w=adapted[pc];rs=(w>>21)&31;rt=(w>>16)&31;im=w&65535;im=im if im<32768 else im-65536;a=(uc.reg_read(regs[rs])+im)&0xffffffff
   if w>>26==0x1e:
    value=bytes(uc.mem_read(a,16));uc.reg_write(regs[rt],int.from_bytes(value[:8],'little'));upper[rt]=value[8:]
   else:uc.mem_write(a,uc.reg_read(regs[rt]).to_bytes(8,'little')+upper[rt])
  for pc in adapted:u.hook_add(UC_HOOK_CODE,adapt,begin=pc,end=pc)
  leaves={target(0x64):'archive_read',target(0x6c):'temporary_alloc',target(0xa4):'texture_descriptor',target(0xac):'sync',target(0xb8):'texture_upload',target(0xc4):'close_upload',target(0x110):'temporary_free',target(0x118):'archive_release',target(0x168):'aligned_alloc'}
  def leaf(uc,pc,size,data):
   name=leaves[pc];args=[uc.reg_read(regs[i])&0xffffffff for i in range(4,12)];ret=0;event={'service':name,'entry':hex(pc),'args':[hex(a) for a in args]}
   if name=='archive_read':
    assert args[0]==0x5678;offset,length,record=args[1:4];uc.mem_write(SOURCE,vt1[offset:offset+length]);uc.mem_write(record,struct.pack('<2I',length,SOURCE));event['archive_offset']=hex(offset);event['length']=length
   elif name=='temporary_alloc':assert args[0]==65536;ret=TEMP;uc.mem_write(TEMP,b'\xa5'*65536)
   elif name=='aligned_alloc':
    alignment,length=args[:2];ret=(next_heap[0]+alignment-1)&-alignment;next_heap[0]=ret+length;allocs.append((ret,length));uc.mem_write(ret,b'\xa5'*length)
   elif name=='texture_descriptor':descs[args[0]]=args[1:]
   elif name=='texture_upload':
    spec=descs[args[0]];bits={0:32,2:16,0x14:4}[spec[2]];length=spec[5]*spec[6]*bits//8;data=bytes(uc.mem_read(args[1],length));event.update(descriptor=spec,source_sha256=hashlib.sha256(data).hexdigest(),source_length=length)
   elif name=='temporary_free':assert args[0]==TEMP
   events.append(event);uc.reg_write(UC_MIPS_REG_2,ret);uc.reg_write(UC_MIPS_REG_PC,uc.reg_read(UC_MIPS_REG_RA))
  for pc in leaves:u.hook_add(UC_HOOK_CODE,leaf,begin=pc,end=pc)
  u.hook_add(UC_HOOK_CODE,lambda uc,pc,size,data:uc.emu_stop(),begin=STOP,end=STOP)
  u.reg_write(UC_MIPS_REG_SP,SP);u.reg_write(UC_MIPS_REG_GP,GP);u.reg_write(UC_MIPS_REG_RA,STOP);u.emu_start(entry,0,count=300000000)
  assert u.reg_read(UC_MIPS_REG_PC)==STOP,(ed,hex(u.reg_read(UC_MIPS_REG_PC)))
  assert [n for p,n in allocs]==[0x2800,0x2000,0x1e000,0x13b000],(ed,allocs)
  gpim=elf.words(entry+0x28,1)[0]&65535;gpoff=gpim if gpim<32768 else gpim-65536;count=int.from_bytes(u.mem_read(GP+gpoff,2),'little');indexbase=pointer(entry+4,entry+0x1c)
  state=ctypes.create_string_buffer(bytes(0x90));records=ctypes.create_string_buffer(b'\xa5'*0x2800);pending=(ctypes.c_uint16*512)();n=ctypes.c_uint();atlas=ctypes.create_string_buffer(b'\xa5'*0x1e000);font=ctypes.create_string_buffer(b'\xa5'*0x13b000);temp=ctypes.create_string_buffer(b'\xa5'*65536);fs=ctypes.create_string_buffer(font_source);aux=ctypes.create_string_buffer(aux_source);sd=ctypes.create_string_buffer(seed+b'\0');xt=ctypes.create_string_buffer(bytes(ext));addresses=(ctypes.c_uint32*4)(*[p for p,size in allocs])
  assert model.native_resource_state_model(state,records,pending,ctypes.byref(n),atlas,font,temp,fs,len(font_source),aux,len(aux_source),sd,xt,addresses)==0
  assert bytes(u.mem_read(F,0x90))==bytes(state)[:0x90],(ed,'initializer state')
  for label,addr,expected in [('records',allocs[0][0],bytes(records)[:0x2800]),('atlas',allocs[2][0],bytes(atlas)[:0x1e000]),('font',allocs[3][0],bytes(font)[:0x13b000]),('temporary',TEMP,bytes(temp)[:65536])]:
   assert bytes(u.mem_read(addr,len(expected)))==expected,(ed,label)
   buffers[label]=hashlib.sha256(expected).hexdigest()
  assert count==n.value==42;assert int.from_bytes(u.mem_read(F-0x10,4),'little')==indexbase+84;assert bytes(u.mem_read(indexbase,84))==bytes(pending)[:84]
  assert [e['source_length'] for e in events if e['service']=='texture_upload']==[64,32768,1024]
  results.append({'edition':ed,'scope':__doc__,'entry':hex(entry),'font_VT1_indices':[font_i,font_j],'auxiliary_VT1_indices':[aux_i,aux_j],'seed_hex':seed.hex(' '),'reserved_glyphs':count,'reserved_atlas_marker':list(struct.unpack_from('<2h',bytes(state),12)),'allocations':[[hex(p),size] for p,size in allocs],'buffer_sha256':buffers,'external_service_trace':events})
  print(ed,'native initializer matches composed C state, font, seeded atlas and upload source contracts',flush=True)
(OUT/'resource-init-execution.json').write_text(json.dumps({'status':'three_native_initializers_match_composed_models_under_explicit_external_leaf_contracts','case_count':len(results),'editions':results},indent=2)+'\n')
