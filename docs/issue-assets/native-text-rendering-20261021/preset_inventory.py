"""Independent upper font-preset setter bindings; native table rows through statically observed constant indices.
Does not infer total table extent or validity of every caller index.
"""
from pathlib import Path
import json,hashlib,struct,ctypes,sys
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[];m=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
for ed in ('original','best','sp'):
 e,lock=native(ed);entry=find(e,src.words(0x3aa8e0,18));end=entry+0xe8;assert e.words(end-8,1)[0]==0x03e00008
 hi,lo=e.words(entry+0xc,1)[0],e.words(entry+0x14,1)[0];table=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;gp_offset=ctypes.c_int16(e.words(entry+4,1)[0]&65535).value
 flow=json.loads((OUT/'dataflow-inventory.json').read_text())
 watched=next(x for x in flow['editions'] if x['edition']==ed)['watched_calls'];indices=[int(x['arguments']['a0']['value'],16)&255 for x in watched if x['target']=='font_preset' and x['arguments']['a0']]
 assert indices and max(indices)<128
 count=max(12,max(indices)+1);data=e.read(table,22*count);decoded=[list(struct.unpack_from('<11h',data,i*22)) for i in range(count)]
 (OUT/f'{ed}-font-preset.asm').write_text('\n'.join(f'{p:08x} {e.words(p,1)[0]:08x} {decode(m,e.words(p,1)[0],p)[0]}' for p in range(entry,end,4))+'\n')
 rows.append({'edition':ed,'native_executable':lock,'entry':hex(entry),'end':hex(end),'table':hex(table),'GP_offset':gp_offset,'fields':['A_width','A_height','A_advance_x','A_advance_y','B_width','B_height','B_advance_x','B_advance_y','number_width','number_height','number_advance'],'row_count_basis':'maximum constant index in dataflow-inventory.json, not a proved table bound','row_count':count,'sampled_rows':decoded,'table_bytes':data.hex(),'setter_sha256':hashlib.sha256(e.read(entry,end-entry)).hexdigest()})
 print(ed,hex(entry),hex(table),'row1',decoded[1],flush=True)
(OUT/'preset-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':rows},indent=2)+'\n')
