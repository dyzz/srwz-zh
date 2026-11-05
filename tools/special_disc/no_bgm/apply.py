"""Install the SP Battle Viewer no-BGM option after the event-gallery stage."""
from pathlib import Path
import struct,subprocess,hashlib
from special_disc.writeback.migrate_slps_text import encoding_tables
from special_disc.writeback.write_system_text import Writer

def apply_no_bgm(elf: bytes, *, workdir: Path, proposal: Path | None = None):
 w=Path(workdir).resolve();w.mkdir(parents=True,exist_ok=True);b=bytearray(elf)
 original=bytes(b);ph=struct.unpack_from('<I',b,28)[0];n=struct.unpack_from('<H',b,44)[0];hs=[struct.unpack_from('<8I',b,ph+i*32) for i in range(n)]
 def off(addr):
  for t,o,v,pa,sz,mem,flags,al in hs:
   if t==1 and v<=addr<v+sz:return o+addr-v
  raise ValueError(hex(addr))
 # Reuse the zero-length ELF end marker in the gap between native overlays and gallery.
 assert hs[70]==(1,0x3cb700,0x81c600,0x81c600,0,0,6,16),hs[70]
 base=0x81e000;limit=0x820000
 assert all(not(sz or mem) or max(base,v)>=min(limit,v+mem) for t,o,v,pa,sz,mem,fl,al in hs if t==1)
 # This gap is below the gallery heap boundary; neither heap nor gallery data moves.
 assert struct.unpack_from('<I',b,off(0x44e734))[0]>=limit
 table,_,overrides,_=encoding_tables(proposal)
 writer=Writer(table,overrides,None)
 for file,text in [('label.bin','无 BGM'),('option.bin','关闭 BGM（保留音效）'),('help.bin','关闭战斗背景音乐，保留驾驶员台词和音效。')]:
  (w/file).write_bytes(writer.encode(text))
 asm=Path(__file__).with_name('runtime.S');subprocess.run(['mipsel-linux-gnu-as','-march=r5900','-o',str(w/'runtime.o'),str(asm)],cwd=w,check=True)
 subprocess.run(['mipsel-linux-gnu-ld','-Ttext',hex(base),'-e','settings_init','-o',str(w/'runtime.elf'),str(w/'runtime.o')],check=True)
 subprocess.run(['mipsel-linux-gnu-objcopy','-O','binary','-j','.text',str(w/'runtime.elf'),str(w/'runtime.bin')],check=True)
 payload=(w/'runtime.bin').read_bytes();assert len(payload)<=limit-base
 syms={x.split()[2]:int(x.split()[0],16) for x in subprocess.check_output(['mipsel-linux-gnu-nm',str(w/'runtime.elf')],text=True).splitlines() if len(x.split())==3}
 changes=[]
 for addr,expected,new in [
  (0x41855c,[0xc10603c],[0x0c000000|(syms['settings_init']>>2)]),
  (0x418400,[0x27bdffe0,0x3c010076],[0x08000000|(syms['settings_confirm']>>2),0]),
  (0x418260,[0x240a002e],[0x240a003d]),
  (0x418388,[0x2aa30003],[0x2aa30004]),
  (0x418330,[0x3c13007d],[0x3c130000|((syms['option_names']+0x8000)>>16)]),
  (0x418340,[0x2673f2f0],[0x26730000|(syms['option_names']&0xffff)]),
  (0x4185a4,[0x3c03007d],[0x3c030000|((syms['option_help']+0x8000)>>16)]),
  (0x4185b0,[0x2463f300],[0x24630000|(syms['option_help']&0xffff)]),
  (0x182e30,[0x27bdffa0,0x24020003],[0x08000000|(syms['bgm_sync']>>2),0]),
  (0x182fc0,[0x27bdff90,0x24020003],[0x08000000|(syms['bgm_async']>>2),0])]:
  pos=off(addr);old=struct.unpack_from('<'+'I'*len(expected),b,pos);assert old==tuple(expected),(hex(addr),old)
  struct.pack_into('<'+'I'*len(new),b,pos,*new);changes.append({'address':hex(addr),'before':expected,'after':new})
 fo=(len(b)+4095)&~4095;b+=bytes(fo-len(b))+payload;struct.pack_into('<8I',b,ph+70*32,1,fo,base,base,len(payload),len(payload),7,16)
 out=dict(source_elf_sha256=hashlib.sha256(original).hexdigest(),elf_sha256=hashlib.sha256(b).hexdigest(),payload_address=hex(base),payload_bytes=len(payload),label_hex=(w/'label.bin').read_bytes().hex(),patches=changes,symbols=syms,source_files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),asm]})
 return bytes(b),out
