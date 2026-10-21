"""Native primary setter/reset and actual two UI iterator-to-cache call windows.
No copied or synthetic execution wrapper: stops at real success/failure PCs.
Table/objects/text mutation are controlled RAM fixtures, not a natural UI run.
Compares retained stale-selection state and cache remeasure only on success.
"""
from pathlib import Path
import json,ctypes,struct,subprocess,tempfile,hashlib,collections
from numeric_harness import machine,call,GPRS
from string_adapter import install
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_PC,UC_MIPS_REG_SP,UC_MIPS_REG_GP,UC_MIPS_REG_RA
OUT=Path(__file__).parent;oi=json.loads((OUT/'measure-owner-inventory.json').read_text());si=json.loads((OUT/'measure-source-inventory.json').read_text());results=[];commands=json.loads((OUT/'squad-name-command-inventory.json').read_text());strings=json.loads((OUT/'string-inventory.json').read_text())
with tempfile.TemporaryDirectory(prefix='srwz-measure-owner-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'measure_owner_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_primary_source_set_model.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint64];c.native_primary_source_set_model.restype=ctypes.c_uint32;c.native_owner_reset_model.argtypes=[ctypes.c_void_p]*2;c.native_owner_presentation_step_model.argtypes=[ctypes.c_void_p]*4;c.native_owner_presentation_step_model.restype=ctypes.c_uint32
 c.native_name_command_tail_model.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32];c.native_name_command_tail_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  r=next(x for x in oi['editions'] if x['edition']==ed);s=next(x for x in si['editions'] if x['edition']==ed);u,e,row,fn,F,_,_,_=machine(ed);owner=(ctypes.c_uint32*len(r['owner_config']))(*r['owner_config']);source=(ctypes.c_uint32*len(s['config_words']))(*s['config_words']);sf=s['helpers'];spans=[(int(s['entry'],16),int(s['end'],16)),(int(row['measure_entry'],16),int(row['measure_entry'],16)+0x250)]+[(int(x['entry'],16),int(x['end'],16)) for x in sf.values()]+[(int(x['entry'],16),int(x['end'],16)) for k,x in r['functions'].items() if k!='secondary_setter'];command_row=next(x for x in commands['editions'] if x['edition']==ed);copy_fn=next(x for x in strings['editions'] if x['edition']==ed)['functions']['strcpy'];handler=int(command_row['handler'],16);copy_start=handler+0x70;copy_stop=handler+0x9c;spans += [(int(copy_fn['entry'],16),int(copy_fn['end'],16)),(copy_start,copy_stop)];install(u,e,spans)
  ram=ctypes.create_string_buffer(bytes(u.mem_read(0,32<<20)),32<<20);base=ctypes.addressof(ram);boundaries=set()
  def stop(uc,pc,size,data):
   if pc in boundaries:uc.emu_stop()
  u.hook_add(UC_HOOK_CODE,stop)
  scenario=0
  for wi,window in enumerate(r['caller_windows']):
   failure=(ctypes.c_uint32*3)(*window['failure_config'])
   for start_index in (-1,0,1,2,3):
    for limit in (0,1,3,4):
     for holes in (0,1,2,4,7):
      for new_primary in (False,True):
       scenario+=1;chunks={};entities=[int(command_row['entity_table'],16)+i*176 for i in range(4)]
       for i,p in enumerate(entities):
        data=bytearray(256);link=0x1920000+i*0x1000;definition=0x1940000+i*0x1000;struct.pack_into('<3I',data,8,link,link if i&1 else 0,0);data[0x19]=(i+scenario)%4;data[0x25]=(i*5+scenario)%16;name=bytes.fromhex('889f')*(i+1)+b'\0\0';data[0x28:0x28+len(name)]=name;chunks[p]=bytes(data);linked=bytearray(256);struct.pack_into('<I',linked,0xa8,definition);chunks[link]=bytes(linked);defs=bytearray(64);defs[0x30]=(scenario+i)&255;chunks[definition]=bytes(defs)
       table=bytearray(b'\xa5'*72)
       for k in range(-1,5):
        node_a=0x1960000+(k+1)*0x100;node_b=0x1970000+(k+1)*0x100;struct.pack_into('<I',table,(k+1)*12,0 if holes&(1<<((k+3)%3)) else node_a);a=bytearray(16);b=bytearray(16);struct.pack_into('<I',a,8,node_b);struct.pack_into('<I',b,8,entities[1+(k%3)]);chunks[node_a]=bytes(a);chunks[node_b]=bytes(b)
       chunks[owner[6]-12]=bytes(table);context=bytearray(b'\xa5'*0x200);struct.pack_into('<I',context,4,entities[3]);chunks[owner[0]]=bytes(context)
       for addr,value in [(owner[1],start_index),(owner[2],limit),(owner[3],-777),(owner[4],entities[3]),(owner[5],entities[3]),(owner[7],entities[3]),(owner[8],0x1940000)]:chunks[addr]=struct.pack('<I',value&0xffffffff)
       initial=bytearray(b'\xa5'*0x90);struct.pack_into('<4h',initial,0x14,21,12,21,14);chunks[F]=bytes(initial);chunks[source[0]]=b'\xa5'*0x30;chunks[source[3]]=b'\xa5';chunks[0x1981000]=bytes.fromhex('889f')*6+b'\0\0';chunks[0x1982000]=struct.pack('<4I',5039,0,0x1981000,0)
       if failure[1]:chunks[failure[0]]=struct.pack('<I',0x1980000);chunks[0x1980000]=b'\x55'*16
       else:chunks[failure[0]]=b'\x55'*2
       def write(addr,data):u.mem_write(addr,data);ctypes.memmove(base+addr,data,len(data))
       for addr,data in chunks.items():write(addr,data)
       def compare(label):
        for addr,data in chunks.items():
         actual=bytes(u.mem_read(addr,len(data)));expected=ctypes.string_at(base+addr,len(data));assert actual==expected,(ed,scenario,label,hex(addr),[(i,a,b) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b][:8])
       c.native_owner_reset_model(ram,owner);call(u,int(r['functions']['reset']['entry'],16),[]);compare('reset only cursor');write(owner[1],struct.pack('<I',start_index&0xffffffff))
       entity=entities[0] if new_primary else 0;flag=(0,1,0x100,1<<32)[scenario%4];expected=c.native_primary_source_set_model(ram,owner,entity,flag);actual=call(u,int(r['functions']['primary_setter']['entry'],16),[owner[0],entity,flag]);assert actual==expected,(ed,scenario,'setter return');compare('primary setter')
       steps=[]
       for step in range(6):
        mutated=False
        if step==1:
         entity_index=0 if new_primary else 3;expected_destination=c.native_name_command_tail_model(ram,int(command_row['entity_table'],16),entity_index,0x1982000)
         for reg in GPRS[1:]:u.reg_write(reg,0)
         u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_GP,0x1800000);u.reg_write(UC_MIPS_REG_RA,0x8000);u.reg_write(GPRS[2],entity_index);u.reg_write(GPRS[17],0x1982000);boundaries={copy_stop};u.emu_start(copy_start,0,count=2000000);assert u.reg_read(UC_MIPS_REG_PC)==copy_stop and u.reg_read(GPRS[2])&0xffffffff==expected_destination;boundaries=set();compare('native opcode5039 copy tail');mutated=True
        before_obj=bytes(u.mem_read(source[0],0x30));before_font=bytes(u.mem_read(F,0x90));before_selected=bytes(u.mem_read(owner[4],4));expected_success=c.native_owner_presentation_step_model(ram,owner,source,failure)
        for reg in GPRS[1:]:u.reg_write(reg,0)
        u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_GP,0x1800000);u.reg_write(UC_MIPS_REG_RA,0x8000);boundaries={int(window['success_stop'],16),int(window['failure_stop'],16)};u.emu_start(int(window['start'],16),0,count=2000000);pc=u.reg_read(UC_MIPS_REG_PC);boundaries=set();assert pc==int(window['success_stop' if expected_success else 'failure_stop'],16),(ed,scenario,'branch stop',hex(pc));compare('UI step '+str(step))
        obj=bytes(u.mem_read(source[0],0x30));cursor=struct.unpack('<i',bytes(u.mem_read(owner[1],4)))[0];index=struct.unpack('<i',bytes(u.mem_read(owner[3],4)))[0];selected=int.from_bytes(u.mem_read(owner[4],4),'little')
        if not expected_success:
         assert before_obj==obj and before_font==bytes(u.mem_read(F,0x90)) and before_selected==bytes(u.mem_read(owner[4],4)),(ed,scenario,'failure must preserve cached display/font/selection')
        steps.append(dict(step=step,success=bool(expected_success),cursor=cursor,published_index=index,selected=hex(selected),mutated_name_before_step=mutated,text_pointers=list(map(hex,struct.unpack_from('<2I',obj,0x1c))),cached_signed16=list(struct.unpack_from('<2h',obj,0x24)),presentation_sha256=hashlib.sha256(obj).hexdigest(),font_sha256=hashlib.sha256(bytes(u.mem_read(F,0x90))).hexdigest()))
        if not expected_success:break
       results.append(dict(edition=ed,window=wi,start_index=start_index,limit=limit,hole_mask=holes,new_primary=new_primary,primary_flag=flag,primary_setter_return=hex(actual),steps=steps))
  print(ed,scenario,'native setter/reset and real UI iterator/cache scenarios match C',flush=True)
report=dict(scope=__doc__,status='three_native_primary_setter_and_real_UI_windows_match_C',scenario_count=len(results),step_count=sum(len(x['steps']) for x in results),success_steps=sum(s['success'] for x in results for s in x['steps']),failure_steps=sum(not s['success'] for x in results for s in x['steps']),native_5039_name_copy_tails=sum(s['mutated_name_before_step'] for x in results for s in x['steps']),scenarios=results)
(OUT/'measure-owner-execution.json').write_text(json.dumps(report,indent=2)+'\n')
