"""Complete two-entity cache initializer and its local helper/source bindings.
No UI/product name is inferred for the runtime entities; their +28 text producer
and lifetime above this initializer remain separate requirements.
"""
from pathlib import Path
import json,sys,hashlib,ctypes
from inventory import native,decode
from resource_inventory import find
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent;src,_=native('original');rows=[]
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
cache=json.loads((OUT/'measure-cache-inventory.json').read_text());preset=json.loads((OUT/'preset-inventory.json').read_text())
specs={'side_order':(0x319014,0x3199a0,0x319a00),'category':(0x31902c,0x3a0960,0x3a09c0),'category_icon':(0x319078,0x3a09c0,0x3a0a28),'first_pair_icon':(0x31908c,0x319920,0x319954),'special_flag':(0x319138,0x3a0310,0x3a0388),'shape':(0x319160,0x3a0690,0x3a06e8),'second_pair_icon':(0x31929c,0x319960,0x319994)}
s16=lambda w:ctypes.c_int16(w&65535).value
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in cache['editions'] if x['edition']==ed);a=find(e,src.words(0x318ff0,22));end=a+0x594;assert a+0x550==int(r['writer_tail_start'],16);assert e.words(end-8,1)[0]==0x03e00008
 helpers={};listing=[]
 for name,(site,oa,ob) in specs.items():
  pc=a+site-0x318ff0;w=e.words(pc,1)[0];assert w>>26==3;target=(w&0x3ffffff)<<2
  assert e.words(target+(ob-oa)-8,1)[0]==0x03e00008
  helpers[name]=dict(entry=hex(target),end=hex(target+ob-oa),call=hex(pc),sha256=hashlib.sha256(e.read(target,ob-oa)).hexdigest())
  for p in range(target,target+ob-oa,4):listing.append(f'{p:08x} {e.words(p,1)[0]:08x} {decode(md,e.words(p,1)[0],p)[0]}')
 for p in range(a,end,4):listing.append(f'{p:08x} {e.words(p,1)[0]:08x} {decode(md,e.words(p,1)[0],p)[0]}')
 (OUT/f'{ed}-measure-source.asm').write_text('\n'.join(listing)+'\n')
 def address(pc1,pc2):return ((e.words(pc1,1)[0]&65535)<<16)+s16(e.words(pc2,1)[0])
 first=int(helpers['first_pair_icon']['entry'],16);second=int(helpers['second_pair_icon']['entry'],16);pair=address(first+0x18,first+0x20);assert address(second+0x18,second+0x20)==pair+2
 shapes=address(a+0x20c,a+0x210);default_slot=address(a+0x230,a+0x234);default=e.words(default_slot,1)[0];text=e.read(default,64).split(b'\0')[0];assert text==bytes.fromhex('815b')*5
 pr=next(x for x in preset['editions'] if x['edition']==ed);pc=a+0x548;assert (e.words(pc,1)[0]&0x3ffffff)<<2==int(pr['entry'],16);index=e.words(pc+4,1)[0]&65535
 immediates={}
 for label,offset in [('action_first',0xb0),('action_second',0x2c0),('category0',0xec),('category1',0x104),('category2',0x11c),('category3',0x134),('palette0',0xf4),('palette_other',0x10c),('shape0',0x1d4),('shape1',0x1b4),('shape2',0x1c4),('shape3',0x1e4),('special',0x164)]:
  w=e.words(a+offset,1)[0];assert w>>26==9 and (w>>21)&31==0
  immediates[label]=w&65535
 for off in (0xec,0x104,0x11c,0x134,0xf4,0x10c,0x124,0x13c,0x164,0x1b4,0x1c4,0x1d4,0x1e4):assert e.words(a+off,1)[0]==e.words(a+off+0x210,1)[0]
 shape_texts=[]
 for ptr in e.words(shapes,4):
  raw=e.read(ptr,128).split(b'\0')[0]
  shape_texts.append(dict(pointer=hex(ptr),hex=raw.hex(),cp932=raw.decode('cp932'),sha256=hashlib.sha256(raw).hexdigest()))
 first_global=address(a-0x20,a-0x1c);second_global=address(a-0x18,a-0x10)
 assert e.words(a-0x14,1)[0]>>26==2 and (e.words(a-0x14,1)[0]&0x3ffffff)<<2==a
 row=dict(edition=ed,native_executable=lock,entry=hex(a),end=hex(end),sha256=hashlib.sha256(e.read(a,end-a)).hexdigest(),helpers=helpers,object_base=r['object_base'],tail_wrapper_entry=hex(a-0x20),tail_wrapper_argument_globals=[hex(first_global),hex(second_global)],shape_texts=shape_texts,pair_icon_table=hex(pair),pair_icon_values=list(e.words(pair,5)),shape_pointer_table=hex(shapes),shape_pointer_values=list(e.words(shapes,4)),default_pointer_slot=hex(default_slot),default_text_pointer=hex(default),default_text_hex=text.hex(),preset_index=index,preset=pr,immediates=immediates,config_words=[int(r['object_base'],16),int(next(x for x in json.loads((OUT/'inventory.json').read_text())['editions'] if x['edition']==ed)['state_va'],16),int(pr['table'],16),0x1800000+pr['GP_offset'],pair,shapes,default,index]+list(immediates.values()))
 rows.append(row);print(ed,hex(a),'name source entity+28/default',hex(default),'preset',index,flush=True)
(OUT/'measure-source-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=rows),indent=2)+'\n')
