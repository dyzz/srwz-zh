"""Isolated menu-only diagnostic: repeat identical hanzi around compact runs."""
import sys,json,struct,subprocess
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from special_disc.event_gallery.menu import build,ELF_ADDRESS_BIAS,DATA_BASE
source=R/sys.argv[1];dest=R/'build/iso/test/sp-gallery-hanzi-probe-20261105.iso';out=R/'work/analysis/sp-gallery-font-20261105/hanzi-menu'
e=member_map(scan_iso9660(source))['SLPS_259.20']
with source.open('rb') as f:f.seek(e.extent_lba*2048);elf=bytearray(f.read(e.size))
base=bytearray(elf)
original={0x3277AC:0x3C050049,0x3277B8:0x24A5B330,0x3270D4:0x3C030049,0x3270D8:0x2463B420,0x3270E8:0x3C030049,0x3270EC:0x2463B3C0}
for va,word in original.items():struct.pack_into('<I',base,va-ELF_ADDRESS_BIAS,word)
items=json.load(open('config/products/special-disc/event-gallery.json'))['entries']
items[0]['name']='赞波特3赞波特';items[1]['name']='奥拉托里奥No.8奥拉托里奥'
build(bytes(base),items,out,proposal=R/'work/build/special-disc/text-candidate/font/proposal.json')
ph=struct.unpack_from('<I',elf,28)[0];count=struct.unpack_from('<H',elf,44)[0]
seg=next(struct.unpack_from('<8I',elf,ph+i*32) for i in range(count) if struct.unpack_from('<I',elf,ph+i*32+8)[0]==DATA_BASE)
data=(out/'menu-data.bin').read_bytes();assert len(data)==0x1c00
elf[seg[1]:seg[1]+len(data)]=data
for va in original:elf[va-ELF_ADDRESS_BIAS:va-ELF_ADDRESS_BIAS+4]=(out/f'patch-{va:x}.bin').read_bytes()
subprocess.run(['cp','-c',str(source),str(dest)],check=True)
with dest.open('r+b') as f:f.seek(e.extent_lba*2048);f.write(elf)
print(dest)
