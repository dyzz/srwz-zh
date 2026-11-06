import sys,json,struct,subprocess,concurrent.futures
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from special_disc.event_gallery import menu
from special_disc.event_gallery.ligature import CHARACTER
source=R/'build/iso/test/sp-gallery-ti-explicit-20261105.iso';root=R/'work/analysis/sp-showtime-segments-20261105'
e=member_map(scan_iso9660(source))['SLPS_259.20']
with source.open('rb') as f:f.seek(e.extent_lba*2048);original_elf=f.read(e.size)
base=bytearray(original_elf)
original={0x3277AC:0x3C050049,0x3277B8:0x24A5B330,0x3270D4:0x3C030049,0x3270D8:0x2463B420,0x3270E8:0x3C030049,0x3270EC:0x2463B3C0}
for va,word in original.items():struct.pack_into('<I',base,va-menu.ELF_ADDRESS_BIAS,word)
ph=struct.unpack_from('<I',base,28)[0];n=struct.unpack_from('<H',base,44)[0]
seg=next(struct.unpack_from('<8I',base,ph+i*32) for i in range(n) if struct.unpack_from('<I',base,ph+i*32+8)[0]==menu.DATA_BASE)
items=json.load(open('config/products/special-disc/event-gallery.json'))['entries'];normal=menu.compact_list_name
variants=[]
for label,width,space in [('A',14,12),('B',16,12),('C',18,14)]:
 controls=('<width:0E><space:0A><height:09>BIG-O·'
           '<width:14><space:14><height:09>'
           '<width:0E><space:0A><height:09>Show'
           f'<width:{width:02X}><space:{space:02X}><height:09>'+CHARACTER+
           '<width:0E><space:0A><height:09>me'
           '<width:14><space:14><height:09>')
 menu.compact_list_name=lambda name:controls if name=='BIG-O·Showtime' else normal(name)
 out=root/label/'build';menu.build(bytes(base),items,out,proposal=R/'work/build/special-disc/text-candidate/font/proposal.json')
 data=(out/'menu-data.bin').read_bytes();elf=bytearray(original_elf);elf[seg[1]:seg[1]+len(data)]=data
 for va in original:elf[va-menu.ELF_ADDRESS_BIAS:va-menu.ELF_ADDRESS_BIAS+4]=(out/f'patch-{va:x}.bin').read_bytes()
 iso=R/f'build/iso/test/sp-showtime-segment-{label.lower()}-20261105.iso';subprocess.run(['cp','-c',str(source),str(iso)],check=True)
 with iso.open('r+b') as f:f.seek(e.extent_lba*2048);f.write(elf)
 with iso.open('rb') as f:f.seek(e.extent_lba*2048);assert f.read(e.size)==elf
 variants.append(dict(label=label,ti_width=width,ti_advance=space,height=9,controls=controls.replace(CHARACTER,'[ti]'),iso=str(iso),out=str(root/label/'runtime')))
(root/'variants.json').write_text(json.dumps(variants,ensure_ascii=False,indent=2)+'\n')
def test(v):
 with (root/v['label']/'runtime.log').open('w') as log:
  subprocess.run([sys.executable,str(R/'work/analysis/sp-gallery-font-20261105/verify_ti_runtime.py'),v['iso'],v['out']],stdout=log,stderr=subprocess.STDOUT,check=True)
 return v['label']+' ARMSX2 passed'
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 for result in pool.map(test,variants):print(result,flush=True)
