"""Real native two-measure writer tail, followed by two real draw-argument blocks.
Shared font-state writes and full object bytes checked against independent C.
Entry object/font and intervening drawing state are explicit controlled inputs.
Stops at draw bridge entry: no full prefix/frame, real UI or LRPS2 pixel claim.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,hashlib
from numeric_harness import machine,GPRS
from string_adapter import install
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_PC,UC_MIPS_REG_SP,UC_MIPS_REG_RA,UC_MIPS_REG_GP
OUT=Path(__file__).parent;inv=json.loads((OUT/'measure-cache-inventory.json').read_text());results=[]
plain=bytes.fromhex('889f');letter=bytes.fromhex('8260');digit=bytes.fromhex('824f')
cases=[('plain',plain*2,plain*3),('empty',b'',b''),('first_width_persists',bytes.fromhex('320e')+letter,plain*2),('first_advance_persists',bytes.fromhex('340c')+letter,plain*2),('height_counted_as_glyph',bytes.fromhex('338e')+letter,plain),('native_height_counted_as_glyph',bytes.fromhex('330e')+letter,plain),('safe_height_counted_as_glyph',bytes.fromhex('338a')+plain,plain),('palette_skipped',bytes.fromhex('3103')+plain,plain),('closed_character',bytes.fromhex('320e340c338e8260330c824f32153415330c889f'),plain),('closed_robot',bytes.fromhex('320e340c338b8260338a824f32153415338a889f'),plain),('newline_consumes_following_byte',plain+b'\n'+plain,plain),('reset_is_not_measure_reset',bytes.fromhex('30ff')+plain,plain),('symbol_class_boundary',bytes.fromhex('814082608281829f834084918492889f'),digit*4),('cache_signed16_wrap',bytes.fromhex('34ff')+plain*600,plain*601),('width_then_other_string',bytes.fromhex('3215')+plain,letter+digit),('zero_advance',bytes.fromhex('3400')+plain,plain),('large_advance',bytes.fromhex('34ff')+plain*257,plain*258)]
with tempfile.TemporaryDirectory(prefix='srwz-measure-cache-') as td:
 path=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'measure_cache_model.c'),'-o',str(path)],check=True)
 c=ctypes.CDLL(str(path));c.native_center_cache_model.argtypes=[ctypes.c_void_p]*5;c.native_center_cache_args_model.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int16,ctypes.c_int16,ctypes.c_int16,ctypes.c_uint32,ctypes.c_void_p]
 for ed in ('original','best','sp'):
  r=next(x for x in inv['editions'] if x['edition']==ed);u,e,row,fn,F,_,_,_=machine(ed);measure=int(r['measure_entry'],16);start=int(r['writer_tail_start'],16);end=int(r['writer_tail_end'],16);base=int(r['object_base'],16);install(u,e,[(measure,measure+0x250)])
  boundary=[end]
  def stop_boundary(uc,pc,size,data):
   if pc==boundary[0]:uc.emu_stop()
  u.hook_add(UC_HOOK_CODE,stop_boundary)
  for name,left,right in cases:
   for variant in range(4):
    state=bytearray(b'\xa5'*0x90);struct.pack_into('<4h',state,0x14,21,12,21,14);struct.pack_into('<8h',state,0x38,21,12,-21 if variant==3 else 21,14,14,12,12,14);struct.pack_into('<h',state,0x48,variant&1);state[0x4b:0x50]=bytes([variant>>1]*5)
    obj=bytearray(b'\xa5'*0x30);struct.pack_into('<2I',obj,0x1c,0x1900000,0x1940000);u.mem_write(base,bytes(obj));u.mem_write(F,bytes(state));u.mem_write(0x1900000,left+b'\0\0');u.mem_write(0x1940000,right+b'\0\0')
    for reg in GPRS[1:]:u.reg_write(reg,0)
    u.reg_write(GPRS[16],base);u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.reg_write(UC_MIPS_REG_GP,0x1800000);u.reg_write(UC_MIPS_REG_RA,0x8000)
    boundary[0]=end;u.emu_start(start,0,count=2000000);assert u.reg_read(UC_MIPS_REG_PC)==end,(ed,name,'writer not finished',hex(u.reg_read(UC_MIPS_REG_PC)),hex(end))
    expected_state=ctypes.create_string_buffer(bytes(state));expected_obj=ctypes.create_string_buffer(bytes(obj));raw=(ctypes.c_int32*2)();lt=ctypes.create_string_buffer(left+b'\0\0');rt=ctypes.create_string_buffer(right+b'\0\0');c.native_center_cache_model(expected_state,expected_obj,lt,rt,raw)
    actual_state=bytes(u.mem_read(F,0x90));actual_obj=bytes(u.mem_read(base,0x30));assert actual_state==bytes(expected_state)[:0x90],(ed,name,variant,'font state');assert actual_obj==bytes(expected_obj)[:0x30],(ed,name,variant,'object')
    probes=[]
    for second,block in enumerate(r['draw_consumers']):
     # Both fragments start after opaque style/graphics calls. Supply their
     # live-in registers independently; neither block mutates the text cache.
     x,y,color=[(-320,112,128),(32767,-32768,-32768),(-32768,32767,32767),(0,-6,0)][variant];packet=0x31c00000+second*0x1000
     for reg in GPRS[1:]:u.reg_write(reg,0)
     u.reg_write(UC_MIPS_REG_SP,0x1ff0000);u.mem_write(0x1ff0000+0xac,struct.pack('<I',packet));u.reg_write(GPRS[18],x&0xffffffffffffffff)
     if not second:
      u.reg_write(GPRS[17],y&0xffffffffffffffff);u.reg_write(GPRS[4],(color&65535)<<48);u.reg_write(GPRS[3],0xffff9c)
     else:
      u.reg_write(GPRS[17],(color+0xffff9c)&0xffffffff);u.reg_write(GPRS[22],(y+6)&0xffffffffffffffff);u.reg_write(GPRS[21],packet)
     target=int(block['draw_target'],16);boundary[0]=target;u.emu_start(int(block['block_start'],16),0,count=100);assert u.reg_read(UC_MIPS_REG_PC)==target,(ed,name,'draw bridge not reached')
     args=[u.reg_read(reg)&0xffffffff for reg in GPRS[4:10]];want=(ctypes.c_uint32*6)();c.native_center_cache_args_model(expected_obj,second,x,y,color,packet,want);assert args==list(want),(ed,name,variant,second,args,list(want));assert bytes(u.mem_read(base,0x30))==actual_obj
     probes.append(dict(cache_offset=block['cache_offset'],live_in_xy=[x,y],color=color,arguments=args))
    results.append(dict(edition=ed,case=name,variant=variant,left_sha256=hashlib.sha256(left).hexdigest(),right_sha256=hashlib.sha256(right).hexdigest(),raw_measure_results=list(raw),cached_signed16=list(struct.unpack_from('<2h',actual_obj,0x24)),final_explicit_width_advance=struct.unpack_from('<h',actual_state,0x14)[0:1]+struct.unpack_from('<h',actual_state,0x18)[0:1],final_classified=struct.unpack_from('<h',actual_state,0x48)[0],object_sha256=hashlib.sha256(actual_obj).hexdigest(),state_sha256=hashlib.sha256(actual_state).hexdigest(),draw_probes=probes))
  print(ed,len(cases)*4,'native shared-state cache writes and',len(cases)*8,'draw-argument fragments match C',flush=True)
report=dict(scope=__doc__,status='declared_native_writer_tail_and_draw_blocks_match_C',case_count=len(results),native_measure_calls=2*len(results),native_draw_argument_blocks=2*len(results),cases=results)
(OUT/'measure-cache-execution.json').write_text(json.dumps(report,indent=2)+'\n')
