"""Independent library byte-line selectors, range renderer and context wrappers."""
from pathlib import Path
import json,struct,ctypes,sys,hashlib
from inventory import native,decode
from resource_inventory import find,mask
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
spec={'count_below_limit':(0x220f70,0xc0),'select_byte_line':(0x221030,0x100),'render_line_range':(0x221130,0x180),'render_physical_row':(0x220db0,0xc0),'context_draw':(0x225290,0x180),'color_lookup':(0x225410,0x90),'context_store':(0x2254a0,0x30),'context_select':(0x2254d0,0xb0),'strncpy':(0x1a1190,0x1c0)}
for ed in ('original','best','sp'):
 e,lock=native(ed);f={};lines=[]
 for name,(a,n) in spec.items():
  if name=='render_physical_row':
   call=int(f['render_line_range']['entry'],16)+0xf0;word=e.words(call,1)[0];assert word>>26==3;start=(word&0x3ffffff)<<2
   assert all((x&mask(y))==(y&mask(y)) for x,y in zip(e.words(start,20),src.words(a,20)))
  else:start=find(e,src.words(a,20 if n>=80 else 8))
  f[name]={'entry':hex(start),'end':hex(start+n),'sha256':hashlib.sha256(e.read(start,n)).hexdigest()};lines.append(f'; {name} {start:08x}..{start+n:08x}')
  for pc in range(start,start+n,4):lines.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(m,e.words(pc,1)[0],pc)[0]}')
 def entry(name):return int(f[name]['entry'],16)
 def address(hi,lo):return ((e.words(hi,1)[0]&65535)<<16)+ctypes.c_int16(e.words(lo,1)[0]&65535).value
 ss=struct.unpack_from('<I',e.b,32)[0];sz,n=struct.unpack_from('<HH',e.b,46);reg=[struct.unpack_from('<10I',e.b,ss+i*sz) for i in range(n)];ri=next(x for x in reg if x[1]==0x70000006);gp=struct.unpack_from('<I',e.b,ri[4]+20)[0]
 lineoff=ctypes.c_int16(e.words(entry('select_byte_line')+0x54,1)[0]&65535).value;countoff=ctypes.c_int16(e.words(entry('count_below_limit')+0x48,1)[0]&65535).value;assert e.read(gp+lineoff,1)==e.read(gp+countoff,1)==b'\x0a'
 store=entry('context_store');select=entry('context_select');draw=entry('context_draw');lookup=entry('color_lookup');rr=entry('render_line_range')
 globals={'x':address(store,store+8),'y':address(store+0xc,store+0x10),'z':address(store+0x14,store+0x18),'rgba':address(store+0x1c,store+0x24),'palette':address(select+0x80,select+0x84)}
 table=address(lookup,lookup+8);scratch=address(rr+0xb0,rr+0xb8)
 row={'edition':ed,'native_executable':lock,'functions':f,'line_delimiter_GP_offset':lineoff,'count_delimiter_GP_offset':countoff,'delimiter_byte':10,'scratch':hex(scratch),'context_globals':{k:hex(v) for k,v in globals.items()},'context_force_GP_offset':ctypes.c_int16(e.words(draw+0x5c,1)[0]&65535).value,'fade_GP_offset':ctypes.c_int16(e.words(draw+0x70,1)[0]&65535).value,'color_table':hex(table),'color_rows_11':e.read(table,88).hex()}
 (OUT/f'{ed}-library-split.asm').write_text('\n'.join(lines)+'\n');rows.append(row);print(ed,{k:v['entry'] for k,v in f.items()},'delimiter offsets',lineoff,countoff,flush=True)
(OUT/'split-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
