"""Native ELF-only inventory; no patched ISO, simulator or game-state writes.

Requires Capstone; --dependency-path allows an existing local installation.
Raw R5900 LQ/SQ are decoded explicitly. Unhandled EE MMI/COP2 are labeled
unresolved rather than misreported as MIPS DSP/MSA instructions.
"""
from pathlib import Path
import argparse,hashlib,json,struct,sys
ROOT=Path(__file__).resolve().parents[3]
REG='zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split()
class Elf:
 def __init__(self,b):
  self.b=b;off=struct.unpack_from('<I',b,28)[0];size,n=struct.unpack_from('<HH',b,42)
  self.loads=[x for i in range(n) if (x:=struct.unpack_from('<8I',b,off+i*size))[0]==1]
 def off(self,a):
  for _,o,v,_,n,*_ in self.loads:
   if v<=a<v+n:return o+a-v
  raise ValueError(hex(a))
 def read(self,a,n):o=self.off(a);return self.b[o:o+n]
 def words(self,a,n):return struct.unpack('<'+'I'*n,self.read(a,n*4))
 def unique(self,p):
  o=self.b.find(p)
  if o<0 or self.b.find(p,o+1)>=0:raise ValueError('nonunique signature')
  for _,f,v,_,n,*_ in self.loads:
   if f<=o<f+n:return v+o-f
  raise ValueError('signature outside load')
def decode(md,word,pc):
 op=word>>26;rs=(word>>21)&31;rt=(word>>16)&31;imm=word&65535
 if op==0 and (word&63) in (0x18,0x19) and (word>>11)&31:
  rd=(word>>11)&31
  return ('mult' if (word&63)==0x18 else 'multu')+f' ${REG[rd]}, ${REG[rs]}, ${REG[rt]}','ee_mult_rd'
 if op in (0x1e,0x1f):return ('lq' if op==0x1e else 'sq')+f' ${REG[rt]}, {imm if imm<32768 else imm-65536}(${REG[rs]})','ee_lq_sq'
 if op in (0x1c,0x12):return f'.word 0x{word:08x} ; unresolved EE '+('MMI' if op==0x1c else 'COP2'),'unresolved_ee'
 ins=list(md.disasm(struct.pack('<I',word),pc,count=1))
 if len(ins)!=1 or ins[0].size!=4:return f'.word 0x{word:08x} ; unresolved','unresolved'
 i=ins[0];return i.mnemonic+' '+i.op_str,'mips64'
def native(ed):
 cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text())
 p=ROOT/'work/analysis/library-font-fix-20261021'/f'{ed}.elf';b=p.read_bytes()
 assert hashlib.sha256(b).hexdigest()==cfg['executable']['sha256'],ed+' native ELF identity drift'
 return Elf(b),cfg['executable']
def build(dep=None):
 if dep:sys.path.insert(0,dep)
 import capstone
 md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
 source,lock=native('original');report={'scope':'unmodified native executable inventories, not full decompilation','capstone':capstone.__version__,'editions':[]}
 regions=[('state_setters',0x139930,0x139B00),('measure',0x139B00,0x139D50),('classification_and_setters',0x139D50,0x139F00),('font_resources',0x139F00,0x13A290),('render_parse_and_glyphs',0x13A290,0x13AC90),('post_renderer_helpers_unclassified',0x13ACA0,0x13C5C0)]
 for ed in ('original','best','sp'):
  elf,lock=native(ed)
  measure=elf.unique(source.read(0x139B00,0x1c));render_loop=elf.unique(source.read(0x13A390,0x38));delta=render_loop-0x13A390
  assert measure-0x139B00==delta,(ed,'core layout changed')
  # A jump-table base is formed by LUI a0 / ADDIU a0, read from original instructions.
  table_hi,table_lo=elf.words(0x13A3C8+delta,1)[0],elf.words(0x13A3D0+delta,1)[0]
  assert table_hi>>16==0x3c04 and table_lo>>16==0x2484
  base=((table_hi&65535)<<16)+((table_lo&65535)-65536 if table_lo&32768 else table_lo&65535)
  init_candidates=[]
  pattern=struct.unpack('<24I',source.read(0x139930,96))
  for _,off,va,_,n,*_ in elf.loads:
   for k in range(off,off+n-96,4):
    words=struct.unpack_from('<24I',elf.b,k)
    if all((x&0xffff0000)==(y&0xffff0000) for x,y in zip(words,pattern)):init_candidates.append(va+k-off)
  assert len(init_candidates)==1,(ed,init_candidates)
  initializer=init_candidates[0]
  table=elf.words(base,16);calls=[];branches=[];unknown=[];listing=[];rr=[]
  for name,lo,hi in regions:
   lo=(initializer if name=='state_setters' else lo+delta);hi+=delta;listing.append(f'\n; {name} [{lo:08x}, {hi:08x}) native\n');counts={}
   for pc in range(lo,hi,4):
    w=elf.words(pc,1)[0];s,kind=decode(md,w,pc);counts[kind]=counts.get(kind,0)+1;listing.append(f'{pc:08x} {w:08x}  {s}')
    op=w>>26
    if op==3:calls.append({'site':hex(pc),'target':hex(((pc+4)&0xf0000000)|((w&0x3ffffff)<<2))})
    if op in (1,4,5,6,7,20,21,22,23):
     imm=w&65535;target=pc+4+4*(imm if imm<32768 else imm-65536);branches.append({'site':hex(pc),'target':hex(target),'delay_slot':hex(pc+4)})
    if kind.startswith('unresolved'):unknown.append({'pc':hex(pc),'word':hex(w),'region':name})
   rr.append({'name':name,'start':hex(lo),'end':hex(hi),'sha256':hashlib.sha256(elf.read(lo,hi-lo)).hexdigest(),'decoding':counts})
  (Path(__file__).parent/f'{ed}.asm').write_text('\n'.join(listing)+'\n')
  controls=[{'raw_byte':hex(i+0x2e),'target':hex(target),'original_equivalent':hex(target-delta)} for i,target in enumerate(table)]
  row={'edition':ed,'native_executable':lock,'core_va_delta':hex(delta),'state_va':hex(0x46e330+({'original':0,'best':0x800,'sp':0x7f280}[ed])),'initializer_entry':hex(initializer),'measure_entry':hex(measure),'renderer_entry':hex(0x13A290+delta),'control_table_va':hex(base),'controls':controls,'regions':rr,'direct_calls':calls,'branches':branches,'unresolved_instructions':unknown}
  report['editions'].append(row)
 p=Path(__file__).parent/'inventory.json';p.write_text(json.dumps(report,indent=2)+'\n')
 for r in report['editions']:print(r['edition'],'delta',r['core_va_delta'],'controls',len(r['controls']),'unresolved',len(r['unresolved_instructions']))
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dependency-path');a=p.parse_args();build(a.dependency_path)
