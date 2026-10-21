"""Compare reconstructed full integer parser against three native renderer paths.
Covers a1==0 record construction. Native GIF emission is not invoked here.
EE LQ/SQ ABI adaptation is inherited from execute.py and is explicitly recorded.
"""
from pathlib import Path
import json,struct,ctypes,tempfile,subprocess,random,hashlib
from execute import run_case
from inventory import native
OUT=Path(__file__).parent
inv=json.loads((OUT/'inventory.json').read_text())
subs=(bytes.fromhex('82668260'),bytes.fromhex('82818282'),bytes.fromhex('889f'),bytes.fromhex('8340'))
cases=[]
def case(name,payload,**kw):cases.append((name,payload,kw))
case('plain',bytes.fromhex('889f889f'))
case('closed_height',bytes.fromhex('320e340c330e826632153415330c889f'))
case('newline_and_custom_vertical',bytes.fromhex('350f889f0a889f'))
case('literal_internal_linebreak',bytes.fromhex('889f2e889f'))
case('literal_internal_terminator',bytes.fromhex('889f2f889f'))
case('reset_after_compact',bytes.fromhex('320e330f340c889f30ff889f0a889f'))
case('palette_and_numeric_attributes',bytes.fromhex('31073609370d38083911889f'))
case('zero_parameters',bytes.fromhex('32003300340035003100889f'))
case('all_substitutions',bytes.fromhex('889f3a3b3c3d889f'),substitutions=subs)
case('empty_substitution',bytes.fromhex('3a889f'),substitutions=(b'',)+subs[1:])
case('substitution_first_control_byte_is_glyph',bytes.fromhex('3a889f'),substitutions=(bytes.fromhex('320e889f'),)+subs[1:])
case('atlas_row_wrap',bytes.fromhex('889f889f'),state_patch={8:struct.pack('<2h',480,0)})
case('atlas_page_transition',bytes.fromhex('889f889f'),state_patch={8:struct.pack('<2h',480,216)})
case('atlas_last_tile_then_exhaustion',bytes.fromhex('330e889f889f'),state_patch={8:struct.pack('<2h',480,456)})
case('atlas_already_exhausted',bytes.fromhex('330e889f'),atlas_y=480)
case('record_limit_clamp',bytes.fromhex('889f82608340'),state_patch={0:struct.pack('<H',318)})
case('record_count_and_atlas_capacity',bytes.fromhex('889f')*425)
case('fast_digits_and_space',bytes.fromhex('824f82588140889f'),fast_digits=True)
case('forced_dynamic_digits_and_space',bytes.fromhex('824f82588140889f'))
case('color_depth_style_attributes',bytes.fromhex('31038260889f'),state_patch={0x24:bytes.fromhex('12345678'),0x28:bytes.fromhex('21436587'),0x4a:b'\x02',0x50:b'\x01'},z_arg=0x123456)
rng=random.Random(0x5352575a)
for k in range(80):
 units=[]
 for _ in range(rng.randrange(2,35)):
  v=rng.randrange(12)
  if v<4:units.append(bytes([0x31+v,rng.randrange(32)]))
  elif v==4:units.append(b'\x35'+bytes([rng.randrange(1,20)]))
  elif v==5:units.append(b'\x0a')
  elif v==6:units.append(b'\x30\xff')
  elif v==7:units.append(bytes([rng.randrange(0x36,0x3a),rng.randrange(24)]))
  else:units.append(rng.choice([bytes.fromhex(c) for c in ('8140','824f','8266','8281','829f','8340','889f','989f')]))
 case(f'deterministic_mixed_stream_{k:02}',b''.join(units),fast_digits=bool(k&1),flags=tuple(rng.randrange(2) for _ in range(5)))
def main():
 report=[]
 with tempfile.TemporaryDirectory(prefix='srwz-parse-model-') as td:
  lib=Path(td)/'model.dylib';subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(OUT/'parse_model.c'),'-o',str(lib)],check=True)
  c=ctypes.CDLL(str(lib));c.native_parse_model.argtypes=[ctypes.c_void_p]*4+[ctypes.c_void_p]*3+[ctypes.c_uint32,ctypes.c_uint,ctypes.c_uint];c.native_parse_model.restype=ctypes.c_int
  for ed in ('original','best','sp'):
   elf,lock=native(ed);r=next(r for r in inv['editions'] if r['edition']==ed);d=int(r['core_va_delta'],16)
   a,b=elf.words(0x13a8ac+d,1)[0],elf.words(0x13a8b4+d,1)[0];im=b&65535;va=((a&65535)<<16)+(im if im<32768 else im-65536);table=bytearray()
   for o in range(0,65536,4):
    row=elf.read(va+o,4);table.extend(row)
    if row[:2]==b'\0\0':break
   ext=ctypes.create_string_buffer(bytes(table))
   for name,payload,kw in cases:
    r=run_case(ed,payload,details=True,**kw);state=ctypes.create_string_buffer(bytes.fromhex(r['initial_state']));records=ctypes.create_string_buffer(b'\xa5'*(320*32));pending=(ctypes.c_uint16*4096)();n=ctypes.c_uint(0);text=ctypes.create_string_buffer(payload+b'\0\0')
    subbuffers=[ctypes.create_string_buffer(b+b'\0\0\0') for b in kw.get('substitutions',subs)];ptrs=(ctypes.c_void_p*4)(*[ctypes.addressof(b) for b in subbuffers])
    early=c.native_parse_model(state,records,pending,ctypes.byref(n),text,ext,ptrs,kw.get('z_arg',0xffffffff),320,4096)
    actual=bytes.fromhex(r['final_state']);expected=bytes(state)[:len(actual)]
    if expected!=actual:
     diff=[(hex(i),hex(a),hex(b)) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b];raise AssertionError((ed,name,'state',diff))
    assert bytes(records)[:320*32]==bytes.fromhex(r['records']),(ed,name,'records differ')
    assert n.value==r['pending_count'],(ed,name,'pending count')
    assert bytes(pending)[:n.value*2]==bytes.fromhex(r['pending']),(ed,name,'glyph upload list')
    assert r['pending_pointer']==0x1b00000+n.value*2,(ed,name,'native upload pointer')
    assert early==int(r['early']),(ed,name,'early exit',early,r['early'])
    report.append({'edition':ed,'case':name,'payload_hex':payload.hex(' '),'record_count':int.from_bytes(actual[:2],'little'),'pending_uploads':n.value,'cursor':r['cursor'],'atlas':list(struct.unpack_from('<2h',actual,8)),'early':bool(early),'final_state_sha256':hashlib.sha256(actual).hexdigest(),'record_buffer_sha256':hashlib.sha256(bytes(records)[:320*32]).hexdigest(),'adapted_EE_ABI_instructions':sorted(set(r['ee_save_restore_adapters']))})
   print(ed,len(cases),'whole parser/state/record/upload-list comparisons passed',flush=True)
 (OUT/'parse-execution.json').write_text(json.dumps({'status':'three_native_integer_parsers_match_reconstructed_C_state_records_and_upload_lists','scope':__doc__,'seed':'0x5352575a','case_count':len(report),'cases':report},indent=2)+'\n')

if __name__=='__main__':main()
