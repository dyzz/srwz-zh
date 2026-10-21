"""Whole native library range->slice->row/context->parser->packet vs C composition.
Real native strlen/strncpy and all row/render helpers execute without body stubs.
Controlled descriptor/context/text inputs, not live UI or pixel evidence.
Rows here have complete controls, no NUL/LF control parameters or substitutions.
"""
from pathlib import Path
import json,ctypes,struct,tempfile,subprocess,hashlib,argparse,sys
from numeric_harness import machine,call
from string_adapter import install
parser=argparse.ArgumentParser();parser.add_argument('--sync-explicit',action='store_true');parser.add_argument('--safe-height',action='store_true');parser.add_argument('--optical-candidate',action='store_true');parser.add_argument('--packed-optical',action='store_true');args=parser.parse_args();PACKED=args.packed_optical;OPT=args.optical_candidate or PACKED;SAFE=args.safe_height or OPT;SYNC=args.sync_explicit or SAFE
OUT=Path(__file__).parent;inv=json.loads((OUT/'split-inventory.json').read_text());si=json.loads((OUT/'string-inventory.json').read_text());results=[]
cases=[('single',bytes.fromhex('889f')),('two_rows',bytes.fromhex('889f0a889f')),('leading_blank',bytes.fromhex('0a889f')),('middle_blank',bytes.fromhex('889f0a0a889f')),('trailing_lf',bytes.fromhex('889f0a')),('height_then_explicit',bytes.fromhex('330e889f0a320e889f')),('closed_metrics',bytes.fromhex('320e340c330e826632153415330c889f0a320e824f3215889f')),('empty',b''),('null',None),('invalid_ranges',bytes.fromhex('889f')),('budget300',(bytes.fromhex('889f')+b'\n')*299+bytes.fromhex('889f')),('viewport10',(bytes.fromhex('889f')+b'\n')*9+bytes.fromhex('889f'))]
if SAFE:cases += [('robot_closed_height',bytes.fromhex('320e340c330c826632153415338a889f0a320e340c330b824f32153415338a889f')),('robot_next_row',bytes.fromhex('330c82660a889f'))]
if OPT:cases += [
 ('optical_character',bytes.fromhex('320e340c338e826032153415330c889f0a320e340c338d824f32153415330c889f')),
 ('optical_robot',bytes.fromhex('320e340c338c826032153415338a889f0a320e340c338b824f32153415338a889f')),
 ('optical_unclosed_then_row',bytes.fromhex('338e82600a889f')),
 ('optical_mixed',bytes.fromhex('320e340c338e8260338d824f338e826132153415330c889f')),
]
with tempfile.TemporaryDirectory(prefix='srwz-library-range-') as td:
 lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'library_range_model.c'),str(OUT/'packet_model.c'),'-o',str(lib)],check=True)
 c=ctypes.CDLL(str(lib));c.native_library_range_model.argtypes=[ctypes.c_void_p]*8+[ctypes.c_size_t]+[ctypes.c_void_p]*3+[ctypes.c_size_t]+[ctypes.c_void_p]*2
 for ed in ('original','best','sp'):
  u,e,row,fn,F,templates,_,_=machine(ed,True);r=next(x for x in inv['editions'] if x['edition']==ed);f=r['functions'];entry=int(f['render_line_range']['entry'],16);strings=next(x for x in si['editions'] if x['edition']==ed)['functions'];install(u,e,[(int(x['entry'],16),int(x['end'],16)) for x in f.values()]+[(int(strings['strlen']['entry'],16),int(strings['strlen']['end'],16))]);d=int(row['core_va_delta'],16)
  if SYNC:
   sys.path.insert(0,str(OUT.parents[2]/'tools'))
   from srwz.library_body_metrics import apply_library_body_metrics,EDITIONS,CAVE_SIZE
   patched,_=apply_library_body_metrics(e.b,ed);spec=EDITIONS[ed]
   for va,size in [(spec['hook'],4),(spec['cave'],CAVE_SIZE)]:u.mem_write(va,patched[va-spec['delta']:va-spec['delta']+size])
  if SAFE and not OPT:
   from srwz.library_height_restore import apply_library_height_restore,addresses,handler_code,cave_code
   apply_library_height_restore(e.b,ed)
   h,cave=addresses(ed);u.mem_write(h,handler_code(ed));u.mem_write(cave,cave_code(ed))
   from numeric_harness import GPRS
   from unicorn import UC_HOOK_CODE
   u.mem_write(cave+12,b'\0'*4)
   def decode_height(uc,pc,size,data):
    if pc==cave+12 and uc.reg_read(GPRS[3])==0:uc.reg_write(GPRS[2],uc.reg_read(GPRS[1]))
   u.hook_add(UC_HOOK_CODE,decode_height)
  if OPT:
   if PACKED:
    from optical_packed_candidate import install as install_optical
   else:
    from optical_candidate import install as install_optical
   optical_proof=install_optical(u,e,ed)
  glyph_trace=[];row_trace=[]
  from unicorn import UC_HOOK_CODE
  def trace(uc,pc,size,data):
   if pc==int(f['render_physical_row']['entry'],16):row_trace.append({'explicit':list(struct.unpack('<4h',uc.mem_read(F+0x14,8)))})
   if OPT and pc==(0x13ab48 if PACKED else 0x13ab44)+d:
    pointer=uc.reg_read(GPRS[16]);glyph_trace.append({'position':list(struct.unpack('<2h',uc.mem_read(pointer+4,4))),'geometry':list(struct.unpack('<2h',uc.mem_read(pointer+12,4))),'pen':list(struct.unpack('<2h',uc.mem_read(0x70000030,4)))})
   if not OPT and pc==0x13ab20+d:glyph_trace.append({'position':list(struct.unpack('<2h',uc.mem_read(0x70000030,4))),'geometry':list(struct.unpack('<2h',uc.mem_read(0x7000003c,4)))})
  u.hook_add(UC_HOOK_CODE,trace)
  hi,lo=e.words(0x13a8ac+d,1)[0],e.words(0x13a8b4+d,1)[0];extva=((hi&65535)<<16)+ctypes.c_int16(lo&65535).value;table=bytearray()
  for off in range(0,65536,4):
   b=e.read(extva+off,4);table+=b
   if b[:2]==b'\0\0':break
  ext=ctypes.create_string_buffer(bytes(table));ct=ctypes.create_string_buffer(templates);colors=ctypes.create_string_buffer(bytes.fromhex(r['color_rows_11']));gpcount=ctypes.c_int16(e.words(0x13aa84+d,1)[0]&65535).value
  for case,payload in cases:
   for variant in range(12):
    from numeric_harness import GPRS
    desc=bytearray(0x1c);desc[0]=(21,0,255)[variant%3];struct.pack_into('<2h',desc,2,12,36);desc[0xe:0x16]=bytes([21,12,21,14,21,12,21,14] if OPT and case in ('optical_character','optical_unclosed_then_row','optical_mixed') else [21,10,21,12,21,10,21,12] if SAFE else [21,12,21,14,14,12,12,14]);struct.pack_into('<I',desc,0x18,0x12345678)
    initial=bytearray(0x90);struct.pack_into('<HH2h2h',initial,0,2,3,2048,2048,0,48);struct.pack_into('<4h',initial,0x14,18,10,18,10);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x60,0x1d00000);struct.pack_into('<I',initial,0x88,variant%2);initial[0x4a]=variant%2;initial[0x50]=variant//2%2
    first,last=([(-1,2),(0,-1),(2,1),(-1,-1)] if case=='invalid_ranges' else [(254,254),(255,255),(0,8),(0,299)] if case=='budget300' else [(0,8),(1,8),(9,12),(10,20)] if case=='viewport10' else [(0,2),(1,2),(0,0),(3,4)])[variant//3];available=variant%3!=2;pointer=0x31c00000 if variant%3==0 else 0;fade=64 if variant%2 else 128;cfg=(ctypes.c_uint32*8)(first,last,available,pointer,0x1c00000,fade,0,int(SYNC)|(2 if SAFE else 0)|(4 if OPT else 0));ctx=(ctypes.c_uint32*6)(101,102,103,0x10203080,104,1);scratch=ctypes.create_string_buffer(b'\xa5'*512);packet=ctypes.create_string_buffer(b'\xa5'*131072);state=ctypes.create_string_buffer(bytes(initial));records=ctypes.create_string_buffer(b'\xa5'*(320*32));pending=(ctypes.c_uint16*4096)();n=ctypes.c_uint();text=ctypes.create_string_buffer(payload+b'\0\0') if payload is not None else None;descriptor=ctypes.create_string_buffer(bytes(desc))
    u.mem_write(F,bytes(initial));u.mem_write(0x1a00000,b'\xa5'*(320*32));u.mem_write(0x1d00000,b'\xa5'*(400*32));u.mem_write(0x1b00000,b'\xa5'*8192);u.mem_write(F-0x10,struct.pack('<I',0x1b00000));u.mem_write(0x1800000+gpcount,b'\0\0');u.mem_write(0x1800000+r['line_delimiter_GP_offset'],b'\x0a');u.mem_write(0x1800000+r['fade_GP_offset'],bytes([fade]));u.mem_write(0x1800000+r['context_force_GP_offset'],b'\x01');u.mem_write(0x1900000,(payload or b'')+b'\0\0');u.mem_write(0x1910000,bytes(desc));u.mem_write(0x1920000,struct.pack('<I',pointer));u.mem_write(int(r['scratch'],16),b'\xa5'*512);u.mem_write(0x1c00000,b'\xa5'*131072)
    for k,v in zip(['x','y','z','rgba','palette'],ctx[:5]):u.mem_write(int(r['context_globals'][k],16),struct.pack('<I',v))
    expected=c.native_library_range_model(state,records,pending,ctypes.byref(n),text,cfg,descriptor,scratch,512,ctx,colors,packet,131072,ct,ext);assert expected>=0;row_trace.clear();glyph_trace.clear();actual=call(u,entry,[0x1900000 if payload is not None else 0,first,last,0x1910000,0x1920000 if available else 0]);assert actual==expected,(ed,case,variant,'return',actual,expected)
    regions=[('state',F,0x90,bytes(state)[:0x90]),('records',0x1a00000,320*32,bytes(records)[:320*32]),('scratch',int(r['scratch'],16),512,bytes(scratch)[:512]),('packet',0x1c00000,131072,bytes(packet)[:131072])];hashes={}
    for name,address,size,expected_bytes in regions:
     a=bytes(u.mem_read(address,size));assert a==expected_bytes,(ed,case,variant,name,[(j,x,y) for j,(x,y) in enumerate(zip(a,expected_bytes)) if x!=y][:16]);hashes[name]=hashlib.sha256(a).hexdigest()
    assert len(row_trace)==cfg[6],(ed,case,variant,'row count')
    if available:assert int.from_bytes(u.mem_read(0x1920000,4),'little')==cfg[3],(ed,case,variant,'packet pointer')
    for k,value in zip(['x','y','z','rgba','palette'],ctx[:5]):assert int.from_bytes(u.mem_read(int(r['context_globals'][k],16),4),'little')==value,(ed,case,variant,'context',k)
    assert int.from_bytes(u.mem_read(0x1800000+r['context_force_GP_offset'],1),'little')==ctx[5],(ed,case,variant,'context flag');assert int.from_bytes(u.mem_read(0x1800000+gpcount,2),'little')==n.value,(ed,case,variant,'pending count');assert bytes(u.mem_read(0x1b00000,n.value*2))==bytes(pending)[:n.value*2],(ed,case,variant,'indices');assert int.from_bytes(u.mem_read(F-0x10,4),'little')==0x1b00000+n.value*2,(ed,case,variant,'index pointer')
    results.append({'edition':ed,'case':case,'variant':variant,'first':first,'last':last,'packet_reference':available,'initial_pointer':hex(pointer),'physical_row_calls':cfg[6],'explicit_sync_patch':SYNC,'safe_height_patch':SAFE,'analysis_optical_candidate':OPT,'native_row_entries':list(row_trace),'native_glyph_geometry':list(glyph_trace),'final_pointer':hex(cfg[3]),'explicit_geometry':list(struct.unpack_from('<4h',bytes(state),0x14)),'final_pen':list(struct.unpack_from('<2h',bytes(state),0x10)),'pending':n.value,'region_sha256':hashes})
  print(ed,len(cases)*12,'whole native library line-range compositions match C',flush=True)
(OUT/('library-range-optical-packed-execution.json' if PACKED else 'library-range-optical-candidate-execution.json' if OPT else 'library-range-safeheight-execution.json' if SAFE else 'library-range-patched-execution.json' if SYNC else 'library-range-execution.json')).write_text(json.dumps({'scope':__doc__,'explicit_sync_patch':SYNC,'safe_height_patch':SAFE,'analysis_optical_candidate':OPT,'packed_native_code_space':PACKED,'status':('analysis_only_optical_candidate_complete_library_compositions_match_C' if OPT else 'three_library_line_range_paths_with_declared_explicit_sync_patch_match_C_composition' if SYNC else 'three_complete_native_library_line_range_context_parser_packet_paths_match_C_composition'),'case_count':len(results),'cases':results},indent=2)+'\n')
