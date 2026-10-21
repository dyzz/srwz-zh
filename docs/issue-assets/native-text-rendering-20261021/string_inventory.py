"""Independent native strcpy/strlen bindings, including EE packed fast paths."""
from pathlib import Path
import json,sys,hashlib
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);fns={};lines=[]
 for name,a,n in [('strcpy',0x1a0d88,0x118),('strlen',0x1a0ea0,0x138)]:
  entry=find(e,src.words(a,20));end=entry+n;fns[name]={'entry':hex(entry),'end':hex(end),'sha256':hashlib.sha256(e.read(entry,n)).hexdigest()}
  for p in range(entry,end,4):lines.append(f'{p:08x} {e.words(p,1)[0]:08x} {decode(m,e.words(p,1)[0],p)[0]}')
 (OUT/f'{ed}-strings.asm').write_text('\n'.join(lines)+'\n');rows.append({'edition':ed,'native_executable':lock,'functions':fns});print(ed,fns,flush=True)
(OUT/'string-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
