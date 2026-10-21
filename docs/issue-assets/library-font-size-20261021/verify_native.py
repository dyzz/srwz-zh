"""Execute unmodified Original MIPS font routines; no PS2 graphics or live game state."""
import json,struct,hashlib
from pathlib import Path
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
from unicorn.mips_const import *
R=Path(__file__).resolve().parents[3];b=(R/'work/disc/SLPS_258.87').read_bytes()
assert hashlib.sha256(b).hexdigest()=='6c4c81c4e5aa3db1f52d70b8183ce11c01fc6b265ae4d53fa4d6a657c5019b50', 'Original executable lock drift'
u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20);u.mem_map(0x70000000,0x1000)
ph=struct.unpack_from('<I',b,28)[0];es,n=struct.unpack_from('<HH',b,42)
for i in range(n):
 typ,off,va,pa,sz,*_=struct.unpack_from('<8I',b,ph+i*es)
 if typ==1:u.mem_write(va,b[off:off+sz])
F=0x46e330;SP=0x1ff0000;STOP=0x8000;TEXT=0x9000
u.reg_write(UC_MIPS_REG_SP,SP)
regs=[UC_MIPS_REG_4,UC_MIPS_REG_5,UC_MIPS_REG_6,UC_MIPS_REG_7,UC_MIPS_REG_8,UC_MIPS_REG_9,UC_MIPS_REG_10,UC_MIPS_REG_11]
def run(start,end=STOP):
 u.reg_write(UC_MIPS_REG_RA,STOP)
 def stop(uc,address,size,data):
  if address==end:uc.emu_stop()
 hook=u.hook_add(UC_HOOK_CODE,stop)
 try:u.emu_start(start,0,count=1000)
 finally:u.hook_del(hook)
 assert u.reg_read(UC_MIPS_REG_PC)==end, (hex(start),hex(end),hex(u.reg_read(UC_MIPS_REG_PC)))

def half(a):return struct.unpack('<H',bytes(u.mem_read(a,2)))[0]
def state():return dict(render=list(struct.unpack('<2H',bytes(u.mem_read(F+0x14,4)))),advance=list(struct.unpack('<2H',bytes(u.mem_read(F+0x18,4)))),mode=half(F+0x48),classified_render_A=list(struct.unpack('<2H',bytes(u.mem_read(F+0x38,4)))),classified_render_B=list(struct.unpack('<2H',bytes(u.mem_read(F+0x40,4)))))
def setter(values):
 for reg,v in zip(regs,values):u.reg_write(reg,v)
 for o in (0,8,16,24,32):u.mem_write(SP+o,b'\x01')
 run(0x139d50)
def metrics(values):
 for reg,v in zip(regs,values):u.reg_write(reg,v)
 run(0x139e40)
def ctrl(name,value):
 u.mem_write(TEXT,bytes([value]));u.reg_write(UC_MIPS_REG_20,TEXT);u.reg_write(UC_MIPS_REG_17,F)
 run({'width':0x13a470,'height':0x13a490,'space':0x13a4b0}[name],0x13a390)
def glyph(code):
 u.mem_write(TEXT,bytes([code&255]));u.reg_write(UC_MIPS_REG_20,TEXT);u.reg_write(UC_MIPS_REG_17,F);u.reg_write(UC_MIPS_REG_1,0x70000000);u.reg_write(UC_MIPS_REG_2,code>>8)
 u.mem_write(0x70000034,bytes(u.mem_read(F+0x14,4)))
 run(0x13a5f8,0x13a7a0)
 return dict(render=list(struct.unpack('<2H',bytes(u.mem_read(0x7000003c,4)))),advance=list(struct.unpack('<2H',bytes(u.mem_read(0x70000038,4)))))
records=[]
for surface,va in [('character',0x41f0e0),('robot',0x41f020),('keyword',0x41eee0),('story_default',0x41e730)]:
 p=list(u.mem_read(va+14,8))
 for inherited_height in (10,11):
  run(0x139930);metrics([22,inherited_height,22,11]);setter(p)
  before=state();plain=glyph(0x889f)
  ctrl('width',22);ctrl('space',22);prefix=state();explicit=glyph(0x889f)
  ctrl('width',14);ctrl('space',12);english=glyph(0x8266)
  ctrl('width',22);ctrl('space',22);restored=glyph(0x889f)
  # Native renderer saves incoming mode at entry and restores only that mode on exit.
  u.mem_write(0x70000068,struct.pack('<I',1));u.reg_write(UC_MIPS_REG_17,F)
  run(0x13ac58,0x13ac68);after_exit=state()
  setter(p);next_line=glyph(0x889f)
  records.append(dict(surface=surface,descriptor_va=hex(va),native_arguments=p,inherited_explicit_height=inherited_height,after_line_init=before,plain=plain,after_prefix=prefix,explicit=explicit,english=english,restored_chinese=restored,after_renderer_exit=after_exit,next_plain_line=next_line))
  assert prefix['mode']==0 and restored['render']==[22,inherited_height]
  assert next_line['render']==p[:2] and after_exit['mode']==1
# Each of the three handlers clears mode, and touches only its declared dimension.
handlers=[]
for name in ('width','height','space'):
 run(0x139930);setter([21,12,21,14]*2);before=state();ctrl(name,7);after=state();assert after['mode']==0
 handlers.append(dict(control=name,before=before,after=after))
out=dict(status='unmodified_Original_MIPS_instruction_execution_passed',scope='isolated font routines, not emulator graphics or live user ISO',executable_sha256=hashlib.sha256(b).hexdigest(),records=records,handlers=handlers)
(R/'docs/issue-assets/library-font-size-20261021/native-execution.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
for r in records:
 if r['inherited_explicit_height']==11:print(r['surface'],'native',r['plain']['render'],'explicit',r['explicit']['render'],'english',r['english']['render'],'restored',r['restored_chinese']['render'],'next line',r['next_plain_line']['render'])
print('8 surface/height cases and 3 native control handlers passed')
