"""Whole native measure-to-draw centered-label caller vs full C composition.
Uses controlled text-pointer table entry, original style13 row and real callees.
Verifies geometry/state/queues/packets; no natural UI or LRPS2 display claim.
"""
from pathlib import Path
import json,ctypes,struct,tempfile,subprocess,hashlib
from numeric_harness import machine,call
from string_adapter import install
OUT=Path(__file__).parent;inv=json.loads((OUT/'centered-label-inventory.json').read_text());gi=json.loads((OUT/'geometry-inventory.json').read_text());results=[]
cases=[('plain_single',bytes.fromhex('889f')),('plain',bytes.fromhex('889f889f')),('latin_digit',bytes.fromhex('8266824f889f')),('height',bytes.fromhex('330e889f')),('closed_height',bytes.fromhex('320e340c330e826632163416330b889f')),('newline',bytes.fromhex('889f0a889f')),('palette',bytes.fromhex('3103889f')),('width',bytes.fromhex('320e889f')),('space',bytes.fromhex('340c889f')),('empty',b'')]
with tempfile.TemporaryDirectory(prefix='srwz-center-label-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'centered_label_model.c'),str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_centered_label_model.argtypes=[ctypes.c_void_p]*8+[ctypes.c_size_t,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];c.native_centered_label_model.restype=ctypes.c_uint32
 for ed in ('original','best','sp'):
  u,e,row,fn,F,templates,_,_=machine(ed,True);r=next(x for x in inv['editions'] if x['edition']==ed);geom=next(x for x in gi['editions'] if x['edition']==ed);entry=int(r['entry'],16);d=int(row['core_va_delta'],16);install(u,e,[(entry,int(r['end'],16)),(0x139b00+d,0x139d50+d)])
  hi,lo=e.words(0x13a8ac+d,1)[0],e.words(0x13a8b4+d,1)[0];extva=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;extdata=bytearray()
  for offset in range(0,65536,4):
   b=e.read(extva+offset,4);extdata+=b
   if b[:2]==b'\0\0':break
  ext=ctypes.create_string_buffer(bytes(extdata));ct=ctypes.create_string_buffer(templates);style=ctypes.create_string_buffer(e.read(int(geom['style_table'],16)+13*9,9));gpcount=ctypes.c_int16(e.words(0x13aa84+d,1)[0]&65535).value
  for name,payload in cases:
   for variant in range(4):
    initial=bytearray(b'\xa5'*0x90);struct.pack_into('<HH2h2h',initial,0,7,3,2048,2048,0,480 if variant==3 else 48);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x60,0x1d00000);struct.pack_into('<I',initial,0x88,variant&1);pointer=0x31c00000 if variant&1 else 0
    u.mem_write(F,bytes(initial));u.mem_write(0x1a00000,b'\xa5'*(320*32));u.mem_write(0x1d00000,b'\xa5'*(400*32));u.mem_write(0x1b00000,b'\xa5'*8192);u.mem_write(F-0x10,struct.pack('<I',0x1b00000));u.mem_write(0x1800000+gpcount,b'\0\0');u.mem_write(0x1800000+r['text_index_GP_offset'],b'\0\0');u.mem_write(int(r['text_pointer_table'],16),struct.pack('<I',0x1900000));u.mem_write(0x1900000,payload+b'\0\0');u.mem_write(0x1c00000,b'\xa5'*131072)
    state=ctypes.create_string_buffer(bytes(initial));rec=ctypes.create_string_buffer(b'\xa5'*(320*32));pending=(ctypes.c_uint16*4096)();n=ctypes.c_uint();text=ctypes.create_string_buffer(payload+b'\0\0');packet=ctypes.create_string_buffer(b'\xa5'*131072);x=ctypes.c_int32();written=ctypes.c_size_t()
    ret=c.native_centered_label_model(state,rec,pending,ctypes.byref(n),text,ext,style,packet,131072,pointer,ct,ctypes.byref(x),ctypes.byref(written));actual_return=call(u,entry,[0,pointer]);assert ret==actual_return,(ed,name,variant,'return',hex(ret),hex(actual_return))
    actual_state=bytes(u.mem_read(F,0x90));expected_state=bytes(state)[:0x90];assert actual_state==expected_state,(ed,name,variant,'state',[(j,a,b) for j,(a,b) in enumerate(zip(actual_state,expected_state)) if a!=b])
    actual_records=bytes(u.mem_read(0x1a00000,320*32));assert actual_records==bytes(rec)[:320*32],(ed,name,variant,'records');actual_packet=bytes(u.mem_read(0x1c00000,131072));assert actual_packet==bytes(packet)[:131072],(ed,name,variant,'packet')
    assert int.from_bytes(u.mem_read(0x1800000+gpcount,2),'little')==n.value,(ed,name,variant,'pending count');assert bytes(u.mem_read(0x1b00000,n.value*2))==bytes(pending)[:n.value*2],(ed,name,variant,'pending indices');assert int.from_bytes(u.mem_read(F-0x10,4),'little')==0x1b00000+n.value*2,(ed,name,variant,'pending pointer')
    assert bytes(u.mem_read(0x1d00000,400*32))==b'\xa5'*(400*32),(ed,name,variant,'secondary changed');assert bytes(u.mem_read(0x1800000+geom['style_GP_offset'],1))==b'\x0d',(ed,name,variant,'style selection')
    results.append({'edition':ed,'case':name,'variant':variant,'payload':payload.hex(),'immediate':bool(pointer),'atlas_full':variant==3,'force_dynamic_digits':bool(variant&1),'measured_center_x':x.value,'final_pen':list(struct.unpack_from('<2h',actual_state,0x10)),'first_record_xywh':list(struct.unpack_from('<2h',actual_records,7*32+4))+list(struct.unpack_from('<2h',actual_records,7*32+12)) if n.value else None,'pending_uploads':n.value,'return':hex(ret),'state_sha256':hashlib.sha256(actual_state).hexdigest(),'packet_sha256':hashlib.sha256(actual_packet).hexdigest()})
  print(ed,len(cases)*4,'native centered-label complete measure/draw compositions passed',flush=True)
(OUT/'centered-label-execution.json').write_text(json.dumps({'scope':__doc__,'status':'three_native_centered_label_callers_match_full_C_measure_parse_packet_composition','case_count':len(results),'cases':results},indent=2)+'\n')
