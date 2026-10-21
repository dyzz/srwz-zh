from pathlib import Path
import json,hashlib,shutil
from PIL import Image,ImageChops,ImageDraw
R=Path.cwd();E=R/'docs/issue-assets/control-layout-audit-20261021';W=R/'work/runtime/lrps2/control-layout-audit-20261021/characters';C=R/'docs/issue-assets/native-text-rendering-20261021/smaller-body/final'
rows=[];canvas=Image.new('RGB',(1280,3*470),(20,20,20));draw=ImageDraw.Draw(canvas)
for i,ed in enumerate(('original','best','sp')):
 source=W/ed;dest=E/'final'/ed;dest.mkdir(parents=True,exist_ok=True)
 receipt=json.loads((source/'receipt.json').read_text());assert receipt['source_card_sha256_before']==receipt['source_card_sha256_after']
 for name in ('lily-top','lily-scroll','alex-top','alex-scroll'):
  p=source/(name+'.png');shutil.copy2(p,dest/p.name)
  im=Image.open(p).convert('RGB');ref=Image.open(C/ed/p.name).convert('RGB')
  # Compare the smaller current image with the previous character-body size.
  diff=ImageChops.difference(im,ref);bbox=diff.getbbox()
  rows.append(dict(edition=ed,image=name,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),same_as_previous_size=bbox is None,difference_bbox=bbox))
 shutil.copy2(source/'receipt.json',dest/'receipt.json')
 for j,name in enumerate(('lily-scroll','alex-scroll')):canvas.paste(Image.open(source/(name+'.png')),(j*640,i*470+22))
 draw.text((5,i*470+3),ed+' final LRPS2 scroll',fill='white')
canvas.save(E/'scroll-review.png')
# Sampled letter/digit extent and corresponding adjacent Chinese on the final images.
rois={'alex-top':{'EFA':[137,162,171,189],'G':[214,162,226,189],'chinese':[113,162,135,189]},'lily-top':{'G':[221,162,234,189],'Geo':[221,190,255,217],'geo_chinese':[257,190,275,217],'digits':[96,218,120,245],'age':[120,218,138,245]}}
metrics=[]
for ed in ('original','best','sp'):
 for page,rs in rois.items():
  im=Image.open(W/ed/(page+'.png')).convert('RGB')
  for label,b in rs.items():
   for threshold in (100,120,140):
    pts=[(x,y) for y in range(b[1],b[3]) for x in range(b[0],b[2]) if min(im.getpixel((x,y)))>threshold and max(im.getpixel((x,y)))-min(im.getpixel((x,y)))<30]
    assert pts,(ed,page,label);xs,ys=zip(*pts)
    metrics.append(dict(edition=ed,page=page,label=label,threshold=threshold,top=min(ys),bottom_exclusive=max(ys)+1,height=max(ys)-min(ys)+1))
out=dict(scope='LRPS2 current built ISO screenshots, sampled bright-text ROI extents; not whole-font or all-surface acceptance',images=rows,measurements=metrics,selection='character letters12 optical Y-1, digits11 Y0, native Chinese12; width14 advance12 unchanged; robots11 Y-1 unchanged')
(E/'runtime-verification.json').write_text(json.dumps(out,indent=2)+'\n')
for ed in ('original','best','sp'):
 print(ed,[(m['label'],m['top'],m['bottom_exclusive'],m['height']) for m in metrics if m['edition']==ed and m['threshold']==120])
print('Original final pixels unchanged from previous size:',all(r['same_as_previous_size'] for r in rows if r['edition']=='original'))
