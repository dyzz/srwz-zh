"""Execute actual MIPS hooks; stub only the unchanged native glyph producer."""
import json,struct,sys
from pathlib import Path
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
R=Path.cwd();binary=Path(sys.argv[1]).read_bytes();cases=[]
def vm():
 u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0x100000,0x800000);u.mem_map(0x1000000,0x10000)
 u.mem_write(0x822000,binary[:0x700]);u.reg_write(UC_MIPS_REG_SP,0x1008000);return u
def reg(u,r):return u.reg_read(r)&0xffffffffffffffff
for source,height in [(0x820050,8),(0x820050,9),(0x900010,8),(0x820100,9),(0x820102,9),(0x820108,9),(0x82010a,9)]:
 u=vm();base=0x600000;font=0x4ed5b0
 u.mem_write(0x821bf0,struct.pack('<II',0x820100,0x82010a))
 u.mem_write(font+0x4a,b'\x05')
 before=bytearray(32);struct.pack_into('<hh',before,12,14,height);struct.pack_into('<h',before,6,-18)
 u.mem_write(base,bytes(before));u.reg_write(UC_MIPS_REG_S0,base);u.reg_write(UC_MIPS_REG_S1,font);u.reg_write(UC_MIPS_REG_S4,source)
 u.emu_start(0x822600,0x13b5f8,count=1000)
 after=bytes(u.mem_read(base,32));expected=bytearray(before);expected[0x12]=5
 if 0x820000<=source<0x821be0 and height==8:struct.pack_into('<h',expected,6,-17)
 assert after==bytes(expected),(hex(source),after.hex())
 active=struct.unpack('<II',u.mem_read(0x821be0,8));want=(base,base+32) if 0x820000<=source<0x821be0 else (0,0)
 assert active==want,(active,want)
 assert reg(u,UC_MIPS_REG_AT)==0x70000000 and reg(u,UC_MIPS_REG_V1)==5
 # The next unrelated glyph clears the previous correction range.
 u.reg_write(UC_MIPS_REG_S4,0x900000);u.emu_start(0x822600,0x13b5f8,count=1000)
 assert bytes(u.mem_read(0x821be0,8))==bytes(8)
 cases.append(dict(kind='glyph',source=hex(source),height=height,range=active,result='pass'))
for lo,hi in [(0,0),(0x600020,0x6000a0)]:
 for ptr in [0x600000,0x600020,0x600040,0x600080,0x6000a0,0x6000c0]:
  for height in [8,9]:
   u=vm();u.mem_write(0x821be0,struct.pack('<II',lo,hi));u.reg_write(UC_MIPS_REG_A3,ptr)
   u.mem_write(ptr+14,struct.pack('<H',height))
   u.reg_write(UC_MIPS_REG_T4,0x4560);u.reg_write(UC_MIPS_REG_T1,0x80000000);u.reg_write(UC_MIPS_REG_T5,0x70001230);u.reg_write(UC_MIPS_REG_T0,321)
   u.emu_start(0x822580,0x13bda8,count=100)
   shift=0x80000 if lo<=ptr<hi and height==8 else 0
   assert reg(u,UC_MIPS_REG_T1)==0x80004560
   assert reg(u,UC_MIPS_REG_T5)==0x70001230-shift
   assert reg(u,UC_MIPS_REG_T3)==344 and reg(u,UC_MIPS_REG_T0)==321
   cases.append(dict(kind='packet',range=[lo,hi],pointer=ptr,height=height,gs_top_delta=-(shift>>16),bottom_unchanged=True,result='pass'))
for base in [0x500000,0x600000]:
 for index in [0,109,110,111,4479]:
  u=vm();u.reg_write(UC_MIPS_REG_T2,base);u.reg_write(UC_MIPS_REG_T1,index*288);u.reg_write(UC_MIPS_REG_T0,0x700000);u.reg_write(UC_MIPS_REG_A2,48)
  u.emu_start(0x8225d0,0x13d0d4,count=100)
  expected=0x821d00 if index==110 else base+index*288
  assert reg(u,UC_MIPS_REG_T4)==expected
  assert reg(u,UC_MIPS_REG_A2)==48 and reg(u,UC_MIPS_REG_T3)==0x700030
  assert reg(u,UC_MIPS_REG_T1)==index*288 and reg(u,UC_MIPS_REG_T2)==base
  cases.append(dict(kind='glyph_upload',index=index,source=hex(expected),result='pass'))
print(json.dumps(dict(cases=cases,passed=len(cases)),indent=2))
