"""Whole native parser regression: same Chinese before/after real compact scopes.
Controlled state matching the SP flow body, not natural runtime evidence.
Runs each edition's original instructions and current parser patch separately.
"""
from pathlib import Path
import json,sys,struct,hashlib
R=Path.cwd();sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'docs/issue-assets/native-text-rendering-20261021'))
from numeric_harness import machine,call
from srwz.library_optical_metrics import regions
E=Path(__file__).parent;fixture=json.loads((E/'controlled-receipt.json').read_text());payload=bytes.fromhex(fixture['fixture_payload_hex']);results=[]
for ed in ('original','best','sp'):
 u,e,row,_,F,_,_,_=machine(ed,True);d=int(row['core_va_delta'],16);patches=regions(ed);imm=e.words(0x13aa84+d,1)[0]&65535;gpcount=imm-65536 if imm>=32768 else imm
 for dynamic in (0,1):
  initial=bytearray(144);struct.pack_into('<2h',initial,8,0,48);struct.pack_into('<4h',initial,0x14,16,10,16,12);struct.pack_into('<8h',initial,0x38,16,10,16,12,16,10,16,12);struct.pack_into('<h',initial,0x48,1);initial[0x4b:0x50]=bytes([1]*5);struct.pack_into('<I',initial,0x58,0x1a00000);struct.pack_into('<I',initial,0x88,dynamic)
  def run(patched):
   for va,before,after in patches:u.mem_write(va,after if patched else before)
   u.ctl_flush_tb();u.mem_write(F,bytes(initial));u.mem_write(0x1a00000,b'\xa5'*10240);u.mem_write(0x1b00000,b'\xa5'*8192);u.mem_write(F-16,struct.pack('<I',0x1b00000));u.mem_write(0x1800000+gpcount,bytes(2));u.mem_write(0x1900000,payload)
   ret=call(u,0x13a290+d,[0x1900000,0,0xffffffff,0]);return ret,bytes(u.mem_read(F,144)),bytes(u.mem_read(0x1a00000,10240)),bytes(u.mem_read(0x1b00000,8192)),bytes(u.mem_read(0x1800000+gpcount,2))
  baseline=run(False);current=run(True);assert baseline[:2]==current[:2];assert baseline[3:]==current[3:]
  expected=bytearray(baseline[2])
  for index in (11,12,13,22,23,24):assert struct.unpack_from('<2h',expected,index*32+12)==(14,10);struct.pack_into('<h',expected,index*32+14,9)
  assert bytes(expected)==current[2],(ed,dynamic,'unexpected glyph record changes')
  for index in (0,7,14,18,25):assert struct.unpack_from('<2h',current[2],index*32+12)==(16,10)
  results.append(dict(edition=ed,dynamic_digits=bool(dynamic),Chinese_first_glyph_indices=[0,7,14,18,25],Chinese_geometry=[16,10],all_Chinese_record_bytes_unchanged=True,only_changed_record_indices=[11,12,13,22,23,24],state_and_uploads_unchanged=True))
 print(ed,'both digit paths passed first-Chinese boundary regression',flush=True)
(E/'native-boundary-proof.json').write_text(json.dumps(dict(scope=__doc__,cases=results,case_count=6,source_sha256=hashlib.sha256((R/'tools/srwz/compact_digit_metrics.py').read_bytes()).hexdigest()),indent=2)+'\n')
