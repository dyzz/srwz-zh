"""Audit native library row wrappers, separately from shared measurement callers."""
from pathlib import Path
import sys,json,hashlib
sys.path.insert(0,str(Path(__file__).parent))
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
OUT=Path(__file__).parent
spec={'original':(0,0),'best':(0x3c0,0x3c0),'sp':(0x4de0,0x4f70)}
inv=json.loads((OUT/'inventory.json').read_text());records=[]
for ed,(row_delta,wrapper_delta) in spec.items():
 elf,lock=native(ed);core=next(r for r in inv['editions'] if r['edition']==ed)
 ranges=[('library_row_and_split_wrappers',0x220db0+row_delta,0x2212b0+row_delta),('draw_and_context_wrappers',0x225290+wrapper_delta,0x225580+wrapper_delta)]
 lines=[];calls=[]
 for name,lo,hi in ranges:
  lines.append(f'\n; {name} {lo:08x}..{hi:08x}')
  for pc in range(lo,hi,4):
   w=elf.words(pc,1)[0];asm,kind=decode(md,w,pc);assert not kind.startswith('unresolved')
   lines.append(f'{pc:08x} {w:08x} {asm}')
   if w>>26==3:calls.append({'site':hex(pc),'target':hex(((pc+4)&0xf0000000)|((w&0x3ffffff)<<2))})
 assert not any(c['target']==core['measure_entry'] for c in calls)
 expected=[(0x221220+row_delta,0x220db0+row_delta),(0x220e3c+row_delta,0x225290+wrapper_delta),(0x2253a8+wrapper_delta,int(core['renderer_entry'],16)),(0x2253c4+wrapper_delta,int(core['renderer_entry'],16))]
 for site,target in expected:assert {'site':hex(site),'target':hex(target)} in calls
 (OUT/f'{ed}-library.asm').write_text('\n'.join(lines)+'\n')
 records.append({'edition':ed,'native_executable':lock,'ranges':[[name,hex(lo),hex(hi)] for name,lo,hi in ranges],'direct_calls':calls,'verified_row_to_renderer_edges':[[hex(a),hex(b)] for a,b in expected],'direct_measure_calls_in_these_wrappers':0,'scope':'wrapper direct edges; not proof that every transitive callee is measurement-free'})
(OUT/'library-path.json').write_text(json.dumps(records,indent=2)+'\n')
print('Three native library wrapper chains verified; no direct calls to core measure in these ranges.')
