"""Complete native selector2 resolver and opcode5039 direct-ID dispatch branch.
Executes real coordinate COP1 instructions and native strcpy, no resolver stubs.
Controlled unit/pilot graphs and real ISO command/text bytes; not natural script
reachability, arbitrary invalid pointers, other selectors or general EE FPU proof.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,hashlib
from numeric_harness import machine,call
from string_adapter import install
OUT=Path(__file__).parent;inv=json.loads((OUT/'name-lookup-inventory.json').read_text());audit=json.loads((OUT/'name-command-source-audit.json').read_text());results=[];coordinates=[]
with tempfile.TemporaryDirectory(prefix='srwz-name-lookup-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-ffp-contract=off','-shared','-fPIC',str(OUT/'name_lookup_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_selector2_lookup_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int32,ctypes.c_int32,ctypes.c_uint32,ctypes.c_uint32];c.native_selector2_lookup_model.restype=ctypes.c_int32;c.native_selector02_wrapper_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int32,ctypes.c_int32,ctypes.c_uint32,ctypes.c_uint32];c.native_selector02_wrapper_model.restype=ctypes.c_int32;c.native_name5039_selector2_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32];c.native_name5039_selector2_model.restype=ctypes.c_uint32;c.native_name_lookup_coordinate_model.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  r=next(x for x in inv['editions'] if x['edition']==ed);u,e,row,fn,F,_,_,_=machine(ed);f=r['functions'];install(u,e,[(int(x['entry'],16),int(x['end'],16)) for x in f.values()]);cfg=(ctypes.c_uint32*2)(*r['config']);ram=ctypes.create_string_buffer(bytes(u.mem_read(0,32<<20)),32<<20);base=ctypes.addressof(ram);grid=0x1b00000;context=0x1a00000;command=0x1982000;text=0x1983000
  grid_bytes=bytes((i*37)&255 for i in range(65536))
  def write(addr,data):u.mem_write(addr,data);ctypes.memmove(base+addr,data,len(data))
  write(cfg[1],struct.pack('<I',grid));write(grid,grid_bytes)
  cases=[]
  for entity_row in range(120):
   for member in range(3):
    for slot in range(6):cases.append(dict(name=f'position_{entity_row}_{member}_{slot}',row=entity_row,member=member,slot=slot,id=0x321,flags=0,side=-1,active=1,hidden=0,enabled=1,pilot_flag=0,unit_flag=0,parent=(entity_row+1)%120,mode='lookup',context=True))
  for flags in range(16):
   for rejection in range(6):cases.append(dict(name=f'filter_{flags}_{rejection}',row=4,member=2,slot=5,id=0x321,flags=flags,side=5 if rejection==4 else -1,active=0 if rejection==0 else 1,hidden=64 if rejection==1 else 0,enabled=0 if rejection==2 else 1,pilot_flag=1 if rejection==3 else 0,unit_flag=4 if rejection&1 else 0,parent=-1 if rejection==5 else 3,mode='lookup',context=rejection!=5))
  for options in range(1024):
   for mode in (0,2):cases.append(dict(name=f'wrapper_{mode}_{options}',row=60,member=1,slot=3,id=0x321,flags=0,options=options,side=-1,active=1,hidden=64 if options&16 else 0,enabled=0,pilot_flag=1 if options&32 else 0,unit_flag=4 if options&64 else 0,parent=3,mode='wrapper',selector=mode,context=not bool(options&128)))
  for mode in (0,2):
   cases.append(dict(name=f'full_dispatch_mode{mode}',row=119,member=2,slot=5,id=0x321,flags=0,side=-1,active=1,hidden=0,enabled=1,pilot_flag=0,unit_flag=0,parent=1,mode='command',selector=mode,context=True,source_hex='889f889f',source_label='controlled ideographs'))
   cases.append(dict(name=f'full_dispatch_nomatch_mode{mode}',row=119,member=2,slot=5,id=0x321,flags=0,side=-1,active=0,hidden=0,enabled=1,pilot_flag=0,unit_flag=0,parent=1,mode='command',selector=mode,context=True,source_hex='889f889f',source_label='controlled nonmatch'))
  stage_base=int(json.loads((OUT.parents[2]/f'config/editions/{ed}/edition.json').read_text())['layout']['stage_base'],16)
  for version in next(x for x in audit['editions'] if x['edition']==ed)['versions']:
   for ordinal,actual in enumerate(version['hits']):
    assert actual['selector']==2 and actual['value']<0x8000
    cases.append(dict(name=f"ISO_{version['version']}_{actual['chunk']}_{actual['offset']}",row=(ordinal*17)%120,member=ordinal%3,slot=ordinal%6,id=actual['value'],flags=0,side=-1,active=1,hidden=0,enabled=1,pilot_flag=0,unit_flag=0,parent=(ordinal*17+1)%120,mode='command',selector=2,context=True,source_hex=actual['raw_text_hex'],source_label=actual['text'],command_pointer=stage_base+actual['offset'],source_pointer=int(actual['text_pointer'],16),raw_record_hex=actual['raw_record_hex'],actual_ISO_record=dict(version=version['version'],chunk=actual['chunk'],offset=actual['offset'],argument=actual['argument'],text_sha256=actual['text_sha256'])))
  for serial,k in enumerate(cases):
   table=bytearray(120*176);entity=cfg[0]+k['row']*176;off=k['row']*176;unit=0x1c00000;unit_def=0x1c01000;pilot=0x1c02000;pilot_def=0x1c03000
   table[off+0x14]=k['active'];table[off+0x16]=k['hidden'];table[off+0x24]=k['enabled'];table[off+0x25]=3;struct.pack_into('<I',table,off+8+k['member']*4,unit);struct.pack_into('<h',table,off+0x68,k['parent']);table[off+0x6c:off+0x6e]=bytes([99,88]);parent=(k['parent'] if k['parent']>=0 else 0)*176;table[parent+0x6c:parent+0x6e]=bytes([(serial*13)&255,(serial*29)&255])
   units=bytearray(256);struct.pack_into('<I',units,0xa8,unit_def);struct.pack_into('<I',units,0xb0+k['slot']*4,pilot);udef=bytearray(64);udef[0x30]=k['unit_flag'];p=bytearray(80);struct.pack_into('<I',p,0,pilot_def);p[0x40]=k['pilot_flag'];pdef=struct.pack('<H',k['id'])+b'\xa5'*14
   regions={cfg[0]:bytes(table),unit:bytes(units),unit_def:bytes(udef),pilot:bytes(p),pilot_def:pdef,context:b'\xa5'*0x2fa0}
   payload=bytes.fromhex(k.get('source_hex','889f'));command_va=k.get('command_pointer',command);text_va=k.get('source_pointer',text);record=bytes.fromhex(k['raw_record_hex']) if 'raw_record_hex' in k else struct.pack('<3I',5039,(k.get('selector',2)<<16)|k['id'],text_va);regions[command_va]=record;regions[text_va]=payload+b'\0\0'
   for addr,data in regions.items():write(addr,data)
   ctx=context if k['context'] else 0
   if k['mode']=='lookup':expected=c.native_selector2_lookup_model(ram,cfg,k['id'],k['side'],k['flags'],ctx)&0xffffffff;actual_ret=call(u,int(f['lookup']['entry'],16),[k['id'],k['side'],k['flags'],ctx])
   elif k['mode']=='wrapper':expected=c.native_selector02_wrapper_model(ram,cfg,k['selector'],k['id'],k['options'],ctx)&0xffffffff;actual_ret=call(u,int(f['selector_wrapper']['entry'],16),[k['selector'],k['id'],k['options'],ctx])
   else:expected=c.native_name5039_selector2_model(ram,cfg,command_va,ctx);actual_ret=call(u,int(f['dispatcher']['entry'],16),[command_va,0,ctx])
   assert actual_ret==expected,(ed,k['name'],'return',hex(actual_ret),hex(expected))
   for addr,data in regions.items():
    actual=bytes(u.mem_read(addr,len(data)));wanted=ctypes.string_at(base+addr,len(data));assert actual==wanted,(ed,k['name'],hex(addr),[(i,a,b) for i,(a,b) in enumerate(zip(actual,wanted)) if a!=b][:12])
   if k['mode']=='command' and actual_ret==1:assert bytes(u.mem_read(entity+40,len(payload)+1))==payload+b'\0',(ed,k['name'],'copied ISO/fixture bytes')
   changed=bytes(u.mem_read(entity,176));outputs=bytes(u.mem_read(context+0x2f90,12));results.append(dict(edition=ed,case=k,return_hex=hex(actual_ret),context_pointers=list(map(hex,struct.unpack('<3I',outputs))),entity_table_sha256=hashlib.sha256(bytes(u.mem_read(cfg[0],120*176))).hexdigest(),matched_entity_coords=list(changed[0x6c:0x6e]),world_float_bits=list(map(hex,struct.unpack_from('<3I',changed,0x50)))))
   if (serial+1)%512==0:print(ed,serial+1,'lookup/dispatch cases',flush=True)
  for value in range(256):
   entity=cfg[0];data=bytearray(b'\xa5'*176);data[0x6c:0x6e]=bytes([value,255-value]);write(entity,bytes(data));c.native_name_lookup_coordinate_model(ram,entity,cfg);call(u,int(f['coordinate']['entry'],16),[entity]);actual=bytes(u.mem_read(entity,176));assert actual==ctypes.string_at(base+entity,176),(ed,value,'COP1 finite-coordinate bytes');coordinates.append(dict(edition=ed,input=[value,255-value],clamped=list(actual[0x6c:0x6e]),world_float_bits=list(map(hex,struct.unpack_from('<3I',actual,0x50)))))
  for height in range(256):
   entity=cfg[0];data=bytearray(b'\xa5'*176);data[0x6c:0x6e]=bytes([3,7]);write(entity,bytes(data));write(grid+7*352+3*8,bytes([height]));c.native_name_lookup_coordinate_model(ram,entity,cfg);call(u,int(f['coordinate']['entry'],16),[entity]);actual=bytes(u.mem_read(entity,176));assert actual==ctypes.string_at(base+entity,176),(ed,height,'signed grid-height float bytes');coordinates.append(dict(edition=ed,input=[3,7],grid_height_byte=height,clamped=list(actual[0x6c:0x6e]),world_float_bits=list(map(hex,struct.unpack_from('<3I',actual,0x50)))))
  print(ed,len(cases),'full lookup/dispatch cases and512 coordinate/height cases match C',flush=True)
(OUT/'name-lookup-execution.json').write_text(json.dumps(dict(scope=__doc__,status='native_selector2_lookup_and_actual_5039_command_domains_match_C',case_count=len(results),coordinate_case_count=len(coordinates),cases=results,coordinates=coordinates),ensure_ascii=False,indent=2)+'\n')
