import sys,struct,json,subprocess,hashlib
from pathlib import Path
sys.path.insert(0,'tools')
from srwz.iso9660 import member_map,scan_iso9660
from srwz.font import decode_glyph,encode_glyph,standard_glyph_index,glyph_raster_metrics
R=Path.cwd();out=R/'work/analysis/sp-showtime-me-align-20261105';src=R/'build/iso/test/sp-showtime-me-b-20261105.iso';iso=R/'build/iso/test/sp-showtime-me-align-20261105.iso'
e=member_map(scan_iso9660(src))['SLPS_259.20']
with src.open('rb') as f:f.seek(e.extent_lba*2048);elf=bytearray(f.read(e.size))
ph=struct.unpack_from('<I',elf,28)[0];n=struct.unpack_from('<H',elf,44)[0];seg=next(struct.unpack_from('<8I',elf,ph+i*32) for i in range(n) if struct.unpack_from('<I',elf,ph+i*32+8)[0]==0x820000)
off=seg[1];assert seg[6]&1
font=Path('/tmp/sp-showtime-font.bin').read_bytes();receipt={}
for c,code,slot,addr in [('m',0x828d,111,0x1400),('e',0x8285,112,0x1520)]:
 assert not any(decode_glyph(font,slot))
 pix=decode_glyph(font,standard_glyph_index(code));shifted=bytes(24)+bytes(pix[:-24]);assert not any(pix[-24:])
 assert not any(elf[off+addr:off+addr+288]);elf[off+addr:off+addr+288]=encode_glyph(shifted)
 hits=[]
 for line in Path('work/analysis/sp-showtime-me-20261105/B/runtime/page1-trace.jsonl').read_text().splitlines():
  j=json.loads(line)
  if j['name']=='glyph' and j['s4'].startswith('0x0082') and int.from_bytes(bytes.fromhex(j['mem']['@70000060:2']),'little')==code:
   b=bytes.fromhex(j['mem']['s0:20'])
   if struct.unpack_from('<h',b,6)[0]==-18:hits.append(int(j['s4'],16)-2)
 assert len(hits)==1,hits
 pos=off+hits[0]-0x820000;assert elf[pos:pos+2]==code.to_bytes(2,'big');elf[pos:pos+2]=(0x81af+(slot-111)).to_bytes(2,'big')
 receipt[c]={'before':glyph_raster_metrics(pix),'after':glyph_raster_metrics(shifted),'code':hex(0x81af+slot-111),'source':hex(hits[0])}
asm='''.set noreorder
.set noat
.text
.globl start
start:
 addu $t4,$t2,$t1
 ori $at,$zero,0x7bc0
 beq $t1,$at,ti
 nop
 ori $at,$zero,0x7ce0
 beq $t1,$at,mg
 nop
 ori $at,$zero,0x7e00
 bne $t1,$at,done
 nop
 lui $t4,0x82
 b done
 ori $t4,$t4,0x1520
mg:
 lui $t4,0x82
 b done
 ori $t4,$t4,0x1400
ti:
 lui $t4,0x82
 ori $t4,$t4,0x1d00
done:
 j 0x13d0d4
 addu $t3,$t0,$a2
'''
(out/'upload.S').write_text(asm)
subprocess.run(['mipsel-linux-gnu-as','-EL','-mips3','-o',str(out/'upload.o'),str(out/'upload.S')],check=True)
subprocess.run(['mipsel-linux-gnu-ld','-EL','-Ttext=0x821700','-e','start','-o',str(out/'upload.elf'),str(out/'upload.o')],check=True)
subprocess.run(['mipsel-linux-gnu-objcopy','-O','binary','-j','.text',str(out/'upload.elf'),str(out/'upload.bin')],check=True)
b=(out/'upload.bin').read_bytes();assert len(b)<0x100 and not any(elf[off+0x1700:off+0x1700+len(b)]);elf[off+0x1700:off+0x1700+len(b)]=b
from special_disc.event_gallery.menu import ELF_ADDRESS_BIAS
struct.pack_into('<I',elf,0x13d0cc-ELF_ADDRESS_BIAS,0x08000000|(0x821700>>2))
subprocess.run(['cp','-c',str(src),str(iso)],check=True)
with iso.open('r+b') as f:f.seek(e.extent_lba*2048);f.write(elf)
with iso.open('rb') as f:f.seek(e.extent_lba*2048);assert f.read(e.size)==elf
(out/'receipt.json').write_text(json.dumps(receipt,indent=2))
subprocess.run([sys.executable,'work/analysis/sp-gallery-font-20261105/verify_ti_runtime.py',str(iso),str(out/'runtime')],check=True)
