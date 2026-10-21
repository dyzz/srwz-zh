"""All 256 native height-parameter transitions vs declared safe8A extension.
Original and modified native handlers execute until the original parse-loop PC.
A single MOVZ in the helper delay slot is adapted with low64-only semantics.
Full font state and scratch height checked; no library/GS/LRPS2 acceptance.
"""
from pathlib import Path
import json,sys,struct,hashlib
from numeric_harness import machine,GPRS
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_PC,UC_MIPS_REG_SP
OUT=Path(__file__).parent;sys.path.insert(0,str(OUT.parents[2]/'tools'))
from srwz.library_height_restore import apply_library_height_restore,addresses,cave_code,handler_code,write_ranges
from srwz.library_body_metrics import apply_library_body_metrics,EDITIONS
results=[]
for ed in ('original','best','sp'):
 original,e,row,fn,F,_,_,_=machine(ed,True);modified,_,_,_,_,_,_,_=machine(ed,True);handler,cave=addresses(ed);loop=handler-0x100;patched,proof=apply_library_height_restore(e.b,ed);again,second=apply_library_height_restore(patched,ed);assert again==patched and second['already_applied']
 # The two independent patch write sets must remain disjoint and commute.
 body_first,_=apply_library_body_metrics(e.b,ed);both,_=apply_library_height_restore(body_first,ed);reverse,_=apply_library_body_metrics(patched,ed);assert both==reverse
 body={i for a,b in __import__('srwz.library_body_metrics',fromlist=['write_ranges']).write_ranges(ed) for i in range(a,b)};safe={i for a,b in write_ranges(ed) for i in range(a,b)};assert not body&safe
 for va,code in [(handler,handler_code(ed)),(cave,cave_code(ed))]:modified.mem_write(va,code)
 modified.mem_write(cave+12,b'\0'*4)
 def stop(uc,pc,size,data):
  if pc==loop:uc.emu_stop()
 def movz(uc,pc,size,data):
  if pc==cave+12 and uc.reg_read(GPRS[3])==0:uc.reg_write(GPRS[2],uc.reg_read(GPRS[1]))
 original.hook_add(UC_HOOK_CODE,stop);modified.hook_add(UC_HOOK_CODE,stop);modified.hook_add(UC_HOOK_CODE,movz)
 for mode in (0,1):
  for value in range(256):
   initial=bytearray(b'\xa5'*0x90);struct.pack_into('<h',initial,0x48,mode)
   for uc in (original,modified):
    uc.mem_write(F,bytes(initial));uc.mem_write(0x1900000,bytes([value,0]));uc.mem_write(0x70000000,b'\xa5'*256)
    for reg in GPRS[1:]:uc.reg_write(reg,0)
    uc.reg_write(GPRS[17],F);uc.reg_write(GPRS[20],0x1900000);uc.reg_write(UC_MIPS_REG_SP,0x1ff0000);uc.emu_start(handler,0,count=30);assert uc.reg_read(UC_MIPS_REG_PC)==loop
   native=bytes(original.mem_read(F,0x90));actual=bytes(modified.mem_read(F,0x90));expected=bytearray(native);decoded=10 if value==0x8a else value;struct.pack_into('<h',expected,0x16,decoded);assert actual==bytes(expected),(ed,mode,value,'state');scratch=bytes(modified.mem_read(0x70000000,256));native_scratch=bytearray(original.mem_read(0x70000000,256));struct.pack_into('<h',native_scratch,0x36,decoded);assert scratch==bytes(native_scratch),(ed,mode,value,'scratch');assert modified.reg_read(GPRS[20])==original.reg_read(GPRS[20])==0x1900001
   results.append({'edition':ed,'initial_mode':mode,'parameter':value,'native_height':value,'extended_height':decoded,'state_sha256':hashlib.sha256(actual).hexdigest(),'scratch_sha256':hashlib.sha256(scratch).hexdigest()})
 print(ed,512,'native safe-height parameter transitions passed; patches commute',flush=True)
(OUT/'height-encoding-execution.json').write_text(json.dumps({'scope':__doc__,'status':'all_three_native_height_handlers_preserve_255_parameters_and_decode_reserved_8A_as10','case_count':len(results),'cases':results},indent=2)+'\n')
