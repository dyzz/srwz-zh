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
 base=0x81fc00;limit=0x820000
 assert all(not(sz or mem) or max(base,v)>=min(limit,v+mem) for t,o,v,pa,sz,mem,fl,al in hs if t==1)
 # This gap is below the gallery heap boundary; neither heap nor gallery data moves.
 assert struct.unpack_from('<I',b,off(0x44e734))[0]>=limit
 table,_,overrides,_=encoding_tables(proposal)
 writer=Writer(table,overrides,None)
 from special_disc.runtime_text import runtime_text
 for name,text in runtime_text()['no_bgm'].items():
  (w/(name+'.bin')).write_bytes(writer.encode(text))
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
  (0x40f848,[0x0c104544],[0x0c000000|(syms['restore_song']>>2)]),
  (0x411630,[0x27bdffc0,0x24030001],[0x08000000|(syms['auto_song']>>2),0]),
  (0x411544,[0x862404f4,0x24020066],[0x08000000|(syms['format_song']>>2),0x862404f4]),
  (0x422070,[0x28420066,0x14400004],[0x08000000|(syms['song_icon']>>2),0]),
  (0x42fe18,[0x0c0d02d0],[0x0c000000|(syms['select_music_cursor']>>2)]),
  (0x411478,[0x0c0f0550],[0x0c000000|(syms['resolve']>>2)]),
  (0x1439e4,[0x0c060b8c],[0x0c000000|(syms['return_music']>>2)]),
  *((addr,[0x0c063228],[0x0c000000|(syms['volume']>>2)])
    for addr in (0x18b740,0x18bcf4,0x18be24,0x18beb0,0x18bf3c))]:
  pos=off(addr);old=struct.unpack_from('<'+'I'*len(expected),b,pos);assert old==tuple(expected),(hex(addr),old)
  struct.pack_into('<'+'I'*len(new),b,pos,*new);changes.append({'address':hex(addr),'before':expected,'after':new})
 fo=(len(b)+4095)&~4095;b+=bytes(fo-len(b))+payload;struct.pack_into('<8I',b,ph+70*32,1,fo,base,base,len(payload),len(payload),7,16)
 out=dict(source_elf_sha256=hashlib.sha256(original).hexdigest(),elf_sha256=hashlib.sha256(b).hexdigest(),payload_address=hex(base),payload_bytes=len(payload),label_hex=(w/'label.bin').read_bytes().hex(),patches=changes,symbols=syms,source_files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),asm]})
 return bytes(b),out
