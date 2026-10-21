"""Independent native placeholder-number and style-table helper bindings."""
from pathlib import Path
import json,hashlib,ctypes,sys
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;source,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);entry=find(e,source.words(0x3a9f30,20));style=find(e,source.words(0x3aa530,20));end=entry+0x5f8;styleend=style+0x9c
 assert e.words(end-8,1)[0]==0x03e00008;assert e.words(styleend-8,1)[0]==0x03e00008
 hi,lo=e.words(style+4,1)[0],e.words(style+0x14,1)[0];table=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;gpoff=ctypes.c_int16(e.words(style+8,1)[0]&65535).value
 lines=[]
 for name,a,b in [('placeholder_number',entry,end),('style_table_apply',style,styleend)]:
  lines.append(f'; {name} {a:08x}..{b:08x}')
  for pc in range(a,b,4):lines.append(f'{pc:08x} {e.words(pc,1)[0]:08x} {decode(m,e.words(pc,1)[0],pc)[0]}')
 (OUT/f'{ed}-placeholder.asm').write_text('\n'.join(lines)+'\n')
 rows.append({'edition':ed,'native_executable':lock,'entry':hex(entry),'end':hex(end),'style':hex(style),'style_end':hex(styleend),'style_table':hex(table),'style_GP_offset':gpoff,'style_first_12_rows':e.read(table,108).hex(),'entry_sha256':hashlib.sha256(e.read(entry,end-entry)).hexdigest()})
 print(ed,hex(entry),hex(style),hex(table),gpoff,flush=True)
(OUT/'geometry-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
