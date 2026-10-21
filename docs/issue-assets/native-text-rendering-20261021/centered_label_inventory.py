"""Independent native centered-label caller: measure(false) -> text bridge."""
from pathlib import Path
import json,ctypes,sys,hashlib
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);a=find(e,src.words(0x2c11c0,20));b=a+0xf8;assert e.words(a+0xec,1)[0]==0x03e00008
 hi,lo=e.words(a+0x5c,1)[0],e.words(a+0x60,1)[0];table=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;gpoff=ctypes.c_int16(e.words(a+0x58,1)[0]&65535).value
 (OUT/f'{ed}-centered-label.asm').write_text('\n'.join(f'{p:08x} {e.words(p,1)[0]:08x} {decode(m,e.words(p,1)[0],p)[0]}' for p in range(a,b,4))+'\n')
 rows.append({'edition':ed,'native_executable':lock,'entry':hex(a),'end':hex(b),'text_pointer_table':hex(table),'text_index_GP_offset':gpoff,'measure_call':hex(a+0x70),'text_draw_call':hex(a+0xa4),'entry_sha256':hashlib.sha256(e.read(a,b-a)).hexdigest()});print(ed,hex(a),hex(table),gpoff,flush=True)
(OUT/'centered-label-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
