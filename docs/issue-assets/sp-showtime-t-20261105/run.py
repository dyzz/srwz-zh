import sys,json,struct,subprocess,concurrent.futures
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from special_disc.event_gallery import menu
from special_disc.event_gallery.ligature import CHARACTER
source=R/'build/iso/test/sp-showtime-w-c-20261105.iso';root=R/'work/analysis/sp-showtime-t-20261105'
e=member_map(scan_iso9660(source))['SLPS_259.20']
with source.open('rb') as f:f.seek(e.extent_lba*2048);original_elf=f.read(e.size)
from srwz.font import decode_glyph,encode_glyph
ph=struct.unpack_from('<I',original_elf,28)[0];n=struct.unpack_from('<H',original_elf,44)[0]
seg=next(struct.unpack_from('<8I',original_elf,ph+i*32) for i in range(n) if struct.unpack_from('<I',original_elf,ph+i*32+8)[0]==menu.DATA_BASE)
offset=seg[1]+0x1d00
raw=original_elf[offset:offset+288];pixels=decode_glyph(raw,0)
variants=[]
for label,trim in [('A',0),('B',1),('C',2)]:
 out=root/label;out.mkdir(parents=True,exist_ok=True)
 changed=bytearray(pixels)
 top=min(y for y in range(24) if any(pixels[y*24+2:y*24+12]))
 for y in range(top,top+trim):changed[y*24+2:y*24+12]=bytes(10)
 assert all(changed[y*24+14:y*24+18]==pixels[y*24+14:y*24+18] for y in range(24))
 assert changed[21*24:22*24]==pixels[21*24:22*24]
 elf=bytearray(original_elf);elf[offset:offset+288]=encode_glyph(changed)
 iso=R/f'build/iso/test/sp-showtime-t-{label.lower()}-20261105.iso';subprocess.run(['cp','-c',str(source),str(iso)],check=True)
 with iso.open('r+b') as f:f.seek(e.extent_lba*2048);f.write(elf)
 with iso.open('rb') as f:f.seek(e.extent_lba*2048);assert f.read(e.size)==elf
 variants.append(dict(label=label,t_top_trim=trim,w_advance=12,ti_width=16,ti_advance=12,height=9,iso=str(iso),out=str(root/label/'runtime')))
(root/'variants.json').write_text(json.dumps(variants,ensure_ascii=False,indent=2)+'\n')
def test(v):
 with (root/v['label']/'runtime.log').open('w') as log:
  subprocess.run([sys.executable,str(R/'work/analysis/sp-gallery-font-20261105/verify_ti_runtime.py'),v['iso'],v['out']],stdout=log,stderr=subprocess.STDOUT,check=True)
 return v['label']+' ARMSX2 passed'
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 for result in pool.map(test,variants):print(result,flush=True)
