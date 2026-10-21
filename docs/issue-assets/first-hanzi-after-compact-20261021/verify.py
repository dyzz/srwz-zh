"""Pixel-exact same-word comparison across compact-control boundaries.
Requires Pillow. SP production captures and controlled RAM fixture are separate.
"""
from pathlib import Path
import json,hashlib,struct
from PIL import Image,ImageChops
E=Path(__file__).resolve().parent;R=E.parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def pixels(im):return im.get_flattened_data() if hasattr(im,'get_flattened_data') else im.getdata()
old=Image.open(E/'production-before.png').convert('RGB');current=Image.open(E/'production-current.png').convert('RGB');diff=ImageChops.difference(old,current)
production=[]
for label,roi in [('特',(148,222,164,245)),('特别小队',(148,222,212,245))]:
 crop=diff.crop(roi);n=sum(px!=(0,0,0) for px in pixels(crop));assert n==0;production.append(dict(label=label,roi=roi,changed_pixels=n))
body=diff.crop((64,120,600,400));body_box=body.getbbox();assert body_box is not None;body_box=(body_box[0]+64,body_box[1]+120,body_box[2]+64,body_box[3]+120);assert body_box==(114,225,148,243)
fixture=json.loads((E/'controlled-receipt.json').read_text());im=Image.open(E/'controlled.png').convert('RGB');records=(E/'controlled-records.bin').read_bytes();reference=None;rows=[]
for row in fixture['first_Chinese_records']:
 n=row['record'];x,y=struct.unpack_from('<2h',records,n*32+4);w,h=struct.unpack_from('<2h',records,n*32+12);assert (w,h)==(16,10);assert (x,y,w,h)==(row['x'],row['y'],row['width'],row['height'])
 sx,sy=x+320,2*y+224;roi=(sx,sy,sx+64,sy+20);word=im.crop(roi)
 if reference is None:reference=word
 d=ImageChops.difference(reference,word);nchanged=sum(px!=(0,0,0) for px in pixels(d));assert nchanged==0;rows.append(dict(record=n,geometry=[w,h],roi=roi,word_changed_pixels=nchanged))
assert fixture['pointer_restored'] and fixture['fixture_memory_restored'];natural=json.loads((E/'natural-receipt.json').read_text());assert all(not row['command'].startswith(('poke ','state ')) for row in natural['commands']);assert natural['iso_sha256']==fixture['iso_sha256']
proof=json.loads((E/'native-boundary-proof.json').read_text());assert proof['case_count']==6 and proof['source_sha256']==sha(R/'tools/srwz/compact_digit_metrics.py');assert all(x['all_Chinese_record_bytes_unchanged'] and x['state_and_uploads_unchanged'] for x in proof['cases'])
files=[p for p in sorted(E.iterdir()) if p.is_file() and p.name!='receipt.json']
out=dict(status='passed_same_Chinese_glyph_before_and_after_compact_scope',scope=__doc__,iso_sha256=fixture['iso_sha256'],production_body_diff_bbox=body_box,production_Chinese=production,controlled_fixture_comparisons=rows,native_cases=6,first_Chinese_geometry=[16,10],interpretation='In these captures 特 was already rendered identically before the digit-height change. Five normalized 特别小队 crops are identical; visual uniformity across different Chinese glyphs is a separate typography judgment.',production_source_modified=False,controlled_RAM_text_probe=True,probe_restored=True,files=[dict(path=str(p.relative_to(R)),size=p.stat().st_size,sha256=sha(p)) for p in files]);(E/'receipt.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print('PASS: production 特 pixels unchanged; five entire Chinese words match pixel-exactly; 6 native first-Hanzi boundary cases passed')
